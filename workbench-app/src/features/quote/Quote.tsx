import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import PageHead from '../../components/PageHead';
import { computeCompliance, computeInputVat, marginRatePercent, type QuoteResult } from './quoteCalc';
import { QuoteParams, VOLT_DEFAULT_COMP } from './QuoteParams';
import { QuoteKpi } from './QuoteKpi';
import { QuoteTable } from './QuoteTable';
import { QuotePreview } from './QuotePreview';
import { QuoteReady, StatusCapsule, computeReady } from './QuoteReady';
import { QuoteActions } from './QuoteActions';
import { previewQuote, optimizeQuote, listOverviewProjects, finalizeOverview, markPlanFinalized, listGroups, renameGroup, copyGroup, finalizeGroup, deleteGroup, getPlan, comparePlans, recomputePlan, type OverviewProject, type PlanGroup, type CompareResult } from './quoteApi';
import { QuotePlanHub } from './QuotePlanHub';
import { QuoteCompareModal } from './QuoteCompareModal';
import { QuoteSchemeBar } from './QuoteSchemeBar';
import { QuoteAuditModal } from './QuoteAuditModal';
import { useConfirm } from '../../components/confirm';
import type { DashFilter } from './quoteCalc';
import type { QuotePreviewResult } from './quoteApi';
import { buildTaxOverride, type TaxComp } from './quoteCalc';

/**
 * 投标报价沙盘（P3 前端整合：由 frontend/index.html 的 #quoteView + app.js 迁入 React）
 *
 * 迁移分块（每块独立验证，与原生逐字段对照）：
 *   块1（本提交）  参数卡（5 张）+ 右栏 KPI 只读 + 明细表空态
 *   块2 上传舱 + 预览       块3 KPI 派生 + 明细表交互
 *   块4 方案中心 + 对比     块5 审计 + 导出 + 穿透
 *
 * 派生数值走 features/quote/quoteCalc（纯函数，有判据）；后端契约不变。
 */
export interface QuoteParamsState {
  projectId: string;
  targetTotal: string;
  fixedPretax: string;
  vatRate: string;
  surtaxRate: string;
  ratioLow: number;
  ratioHigh: number;
  lowRatioConfirmed: boolean;
  lowPriceConfirmedBy: string;
  lowPriceBasisBy: string;
  taxMode: string;
  clauseEnabled: boolean;
  ubMMin: string;
  ubMMax: string;
  ubKwRules: string;
}

const DEFAULT_PARAMS: QuoteParamsState = {
  projectId: '', targetTotal: '', fixedPretax: '', vatRate: '9', surtaxRate: '12',
  ratioLow: 50, ratioHigh: 80, lowRatioConfirmed: false,
  lowPriceConfirmedBy: '', lowPriceBasisBy: '',
  taxMode: 'PARTIAL', clauseEnabled: true, ubMMin: '', ubMMax: '', ubKwRules: '',
};

export default function QuotePage() {
  const [params, setParams] = useState<QuoteParamsState>(DEFAULT_PARAMS);
  const [result, setResult] = useState<QuoteResult | null>(null);

  // 上传舱：File 对象不进 state（不可序列化），用 ref 持有；仅存展示/摘要所需
  const capFileRef = useRef<File | null>(null);
  const costFileRef = useRef<File | null>(null);
  const [capName, setCapName] = useState<string | null>(null);
  const [costName, setCostName] = useState<string | null>(null);
  const [preview, setPreview] = useState<QuotePreviewResult | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const [calculating, setCalculating] = useState(false);
  const [message, setMessage] = useState<{ text: string; kind: 'info' | 'error' | 'success' | 'warn' } | null>(null);
  const [taxComp, setTaxComp] = useState<TaxComp[]>(VOLT_DEFAULT_COMP);
  const [projects, setProjects] = useState<OverviewProject[]>([]);
  const [groups, setGroups] = useState<PlanGroup[]>([]);
  const [expandedGroups, setExpandedGroups] = useState<Set<string>>(new Set());
  const [selectedPlans, setSelectedPlans] = useState<Set<string>>(new Set());
  const [hubOpen, setHubOpen] = useState(false);
  const [compareRes, setCompareRes] = useState<CompareResult | null>(null);
  const [compareOpen, setCompareOpen] = useState(false);
  const [auditOpen, setAuditOpen] = useState(false);
  const confirm = useConfirm();
  const [activeGroupId, setActiveGroupId] = useState('');
  const [activeSlot, setActiveSlot] = useState('A');
  const [currentPlanId, setCurrentPlanId] = useState('');
  // 明细表穿透状态（KPI 卡驱动）
  const [dashFilter, setDashFilter] = useState<DashFilter>('all');
  const [dashSortMargin, setDashSortMargin] = useState(false);
  const [dashPage, setDashPage] = useState(0);

  // 拉「关联投标项目」下拉（仅投标阶段）
  useEffect(() => {
    void listOverviewProjects().then((list) => setProjects(list.filter((p) => !p.stage || p.stage === '投标')));
  }, []);

  // 拉当前项目的方案组
  const refreshGroups = useCallback(async () => {
    if (!params.projectId) { setGroups([]); return; }
    try {
      setGroups(await listGroups(params.projectId));
    } catch {
      setGroups([]);
    }
  }, [params.projectId]);

  useEffect(() => { void refreshGroups(); }, [refreshGroups]);
  const set = (patch: Partial<QuoteParamsState>) => setParams((s) => ({ ...s, ...patch }));

  const onFile = (kind: 'cap' | 'cost', f: File | null) => {
    if (kind === 'cap') { capFileRef.current = f; setCapName(f?.name ?? null); }
    else { costFileRef.current = f; setCostName(f?.name ?? null); }
    setPreview(null);   // 文件变化即清旧预览，避免「未解析却显示上轮数据」
    setMessage(null);
  };

  const runPreview = useCallback(async () => {
    const cap = capFileRef.current, cost = costFileRef.current;
    if (!cap || !cost) { setMessage({ text: '请先上传限价清单和成本清单。', kind: 'error' }); return; }
    setPreviewing(true);
    setMessage({ text: '正在识别文件并核对导入资料，请稍候。', kind: 'info' });
    try {
      const res = await previewQuote(cap, cost, params.projectId, '');
      if (res.status !== 'PASS') throw new Error(res.reason || '预览未通过');
      setPreview(res);
      setMessage({ text: `预览完成：限价 ${res.cap.rows} 行、成本 ${res.cost.rows} 行，可优化 ${res.optimizable_count} 项。`, kind: 'success' });
    } catch (e) {
      setPreview(null);
      setMessage({ text: `预览失败：${(e as Error).message}`, kind: 'error' });
    } finally {
      setPreviewing(false);
    }
  }, [params.projectId]);

  const compliance = useMemo(() => computeCompliance(result), [result]);
  const vat = useMemo(() => computeInputVat(result), [result]);
  const margin = useMemo(() => marginRatePercent(result), [result]);

  // 就绪度（三态之一）：项目 / 清单 / 税口径闭环
  const taxClosed = params.taxMode === 'NONE'
    || Math.abs(taxComp.reduce((s, c) => s + c.proportion, 0) - 1) < 1e-6;
  const ready = computeReady(params, Boolean(capFileRef.current && costFileRef.current), taxClosed);

  /** 组装 /api/quote/optimize 表单（字段对齐 app.js buildOptimizeForm）。 */
  const buildForm = useCallback((strategy: string, groupId = ''): FormData | null => {
    const cap = capFileRef.current, cost = costFileRef.current;
    if (!cap || !cost) return null;
    const data = new FormData();
    data.append('limit_file', cap);
    data.append('cost_file', cost);
    const fields: [string, string][] = [
      ['project_id', params.projectId], ['target_total', params.targetTotal], ['fixed_pretax', params.fixedPretax],
      ['vat_rate', String(Number(params.vatRate) / 100)], ['surtax_rate', String(Number(params.surtaxRate) / 100)],
      ['ratio_min', String(params.ratioLow / 100)], ['ratio_max', String(params.ratioHigh / 100)],
    ];
    fields.forEach(([k, v]) => data.append(k, v));
    data.append('project_name', '');
    data.append('overview_id', '');
    data.append('low_ratio_confirmed', params.lowRatioConfirmed ? 'true' : 'false');
    data.append('low_price_confirmed_by', [params.lowPriceConfirmedBy, params.lowPriceBasisBy].filter(Boolean).join('；'));
    data.append('clause_enabled', params.clauseEnabled ? 'true' : 'false');
    const tax = buildTaxOverride(params.taxMode, taxComp);
    data.append('input_vat_credit_mode', tax.mode);
    data.append('cost_input_vat_rate', '0.13');
    data.append('credit_ratio', String(tax.creditRatio));
    data.append('cost_composition', tax.compositionJson);
    data.append('strategy', strategy);
    data.append('unbalanced_m_min', params.ubMMin || '0');
    data.append('unbalanced_m_max', params.ubMMax || '0.3');
    data.append('unbalanced_strategies', '');
    data.append('unbalanced_kw_rules', params.ubKwRules || '');
    data.append('group_id', groupId);
    return data;
  }, [params, taxComp]);

  /** 一键三方案（P3 块4c）：顺序 A=optimal（主舞台）+ B=uniform（同组 B 槽位）；B 失败不阻断 A。 */
  const runCalculate = useCallback(async () => {
    const formA = buildForm('optimal');
    if (!formA) { setMessage({ text: '请先上传限价清单和成本清单。', kind: 'error' }); return; }
    setCalculating(true);
    setDashFilter('all'); setDashSortMargin(false); setDashPage(0);
    setMessage({ text: '正在识别清单并运行 Phase 2 MILP（方案 A：逐项最优），请稍候。', kind: 'info' });
    try {
      // 后端返回体即完整 result（字段在顶层，无 result 嵌套，与 app.js 一致）。
      const resultA = await optimizeQuote(formA);
      setResult(resultA as QuoteResult);
      setActiveSlot('A');
      setCurrentPlanId(String(resultA.plan_id || ''));
      const gid = String(resultA.group_id || '');
      setActiveGroupId(gid);
      setMessage({
        text: `方案 A 计算完成：竞争性预算 ${Number(resultA.competitive_budget).toLocaleString('zh-CN', { minimumFractionDigits: 2 })} 元，结算调整后利润（不含增值税）${Number(resultA.objective).toLocaleString('zh-CN', { minimumFractionDigits: 2 })} 元。`,
        kind: 'success',
      });
      // 第二步：方案 B（uniform）——失败不阻断 A 的成功结果（同组 B 槽位）
      try {
        const formB = buildForm('uniform', gid);
        if (formB) {
          const resultB = await optimizeQuote(formB);
          setMessage({ text: `方案 A/B 均已生成：A=逐项最优，B=等比下浮（利润 ${Number(resultB.objective).toLocaleString('zh-CN', { minimumFractionDigits: 2 })} 元）。`, kind: 'success' });
        }
      } catch (eB) {
        setMessage({ text: `方案 B（等比下浮）生成失败，原因：${(eB as Error).message}。方案 A 已可用。`, kind: 'warn' });
      }
      await refreshGroups();
      setExpandedGroups((s) => new Set(s).add(gid));
      setActiveGroupId(gid);
    } catch (e) {
      setMessage({ text: `计算失败：${(e as Error).message}`, kind: 'error' });
    } finally {
      setCalculating(false);
    }
  }, [buildForm, refreshGroups]);

  /** 方案切换条：切到组内某槽位方案并回填。 */
  const switchSlot = useCallback(async (slot: string, planId: string | null, index: number) => {
    if (!planId) { setMessage({ text: `方案 ${slot} 槽位暂无方案。`, kind: 'warn' }); return; }
    setActiveSlot(slot);
    setDashFilter('all'); setDashSortMargin(false); setDashPage(0);
    void index;
    try {
      const plan = await getPlan(planId);
      if (plan?.params) {
        const p = plan.params as Record<string, unknown>;
        setParams((s) => ({
          ...s,
          targetTotal: p.target_total != null ? String(p.target_total) : s.targetTotal,
          fixedPretax: p.fixed_pretax != null ? String(p.fixed_pretax) : s.fixedPretax,
          vatRate: p.vat_rate != null ? String(Math.round(Number(p.vat_rate) * 100)) : s.vatRate,
          surtaxRate: p.surtax_rate != null ? String(Math.round(Number(p.surtax_rate) * 100)) : s.surtaxRate,
          ratioLow: p.ratio_min != null ? Math.round(Number(p.ratio_min) * 100) : s.ratioLow,
          ratioHigh: p.ratio_max != null ? Math.round(Number(p.ratio_max) * 100) : s.ratioHigh,
        }));
      }
      if (plan?.result) setResult(plan.result);
      setCurrentPlanId(String(plan?.id || planId));
      setMessage({ text: `已切换至方案 ${slot}。`, kind: 'success' });
    } catch (e) {
      setMessage({ text: `切换方案失败：${(e as Error).message}`, kind: 'error' });
    }
  }, []);

  /** 按当前参数重算当前已打开方案（POST /api/project/recompute?id=）。与 app.js runRecompute 对齐。 */
  const runRecompute = useCallback(async () => {
    if (!currentPlanId) { setMessage({ text: '请先打开或选择一个方案再重算。', kind: 'error' }); return; }
    const fd = new FormData();
    fd.append('target_total', params.targetTotal);
    fd.append('fixed_pretax', params.fixedPretax);
    fd.append('vat_rate', String(Number(params.vatRate) / 100));
    fd.append('surtax_rate', String(Number(params.surtaxRate) / 100));
    fd.append('ratio_min', String(params.ratioLow / 100));
    fd.append('ratio_max', String(params.ratioHigh / 100));
    fd.append('low_ratio_confirmed', params.lowRatioConfirmed ? 'true' : 'false');
    fd.append('low_price_confirmed_by', [params.lowPriceConfirmedBy, params.lowPriceBasisBy].filter(Boolean).join('；'));
    fd.append('clause_enabled', params.clauseEnabled ? 'true' : 'false');
    const tax = buildTaxOverride(params.taxMode, taxComp);
    fd.append('input_vat_credit_mode', tax.mode);
    fd.append('cost_input_vat_rate', '0.13');
    fd.append('credit_ratio', String(tax.creditRatio));
    fd.append('cost_composition', tax.compositionJson);
    // 重算保留该方案策略（A=optimal / B=uniform）
    const g = groups.find((x) => x.group_id === activeGroupId);
    const slotSummary = g?.strategy_slots?.[activeSlot]?.summary;
    fd.append('strategy', String(slotSummary?.strategy || (activeSlot === 'B' ? 'uniform' : 'optimal')));
    setCalculating(true);
    setMessage({ text: '正在按当前参数重算，请稍候。', kind: 'info' });
    try {
      const result = await recomputePlan(currentPlanId, fd);
      setResult(result as QuoteResult);
      setMessage({
        text: `重算完成：竞争性预算 ${Number(result.competitive_budget).toLocaleString('zh-CN', { minimumFractionDigits: 2 })} 元，结算调整后利润（不含增值税）${Number(result.objective).toLocaleString('zh-CN', { minimumFractionDigits: 2 })} 元。`,
        kind: 'success',
      });
      await refreshGroups();
    } catch (e) {
      setMessage({ text: `重算失败：${(e as Error).message}`, kind: 'error' });
    } finally {
      setCalculating(false);
    }
  }, [currentPlanId, params, taxComp, groups, activeGroupId, activeSlot, refreshGroups]);

  /** KPI 穿透：毛利卡 = 切换排序；风险卡 = 切换 risk 筛选；总报价卡 = 清除。 */
  const drillTotal = useCallback(() => { setDashFilter('all'); setDashSortMargin(false); setDashPage(0); }, []);
  const drillMargin = useCallback(() => { setDashSortMargin((v) => !v); setDashPage(0); }, []);
  const drillRisk = useCallback(() => { setDashFilter((f) => (f === 'risk' ? 'all' : 'risk')); setDashPage(0); }, []);

  const hasResult = Boolean(result);

  // Esc 逐层关闭：对比弹层 → 方案中心
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return;
      if (compareOpen) { setCompareOpen(false); return; }
      if (auditOpen) { setAuditOpen(false); return; }
      if (hubOpen) setHubOpen(false);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [compareOpen, hubOpen, auditOpen]);

  /* ==================== 方案中心动作（P3 块4b/4c） ==================== */

  /** 点算指定组的某策略槽位（带 group_id 提交 optimize）。 */
  const calcSlot = useCallback(async (groupId: string, strategy: string) => {
    const form = buildForm(strategy, groupId);
    if (!form) { setMessage({ text: '请先在左栏导入限价清单与成本清单后再点算该槽位。', kind: 'error' }); return; }
    const slotName = strategy === 'optimal' ? 'A' : strategy === 'uniform' ? 'B' : 'C（不平衡报价）';
    setMessage({ text: `正在测算方案 ${slotName} 槽位，请稍候。`, kind: 'info' });
    try {
      const result = await optimizeQuote(form);
      setResult(result as QuoteResult);
      const gid = String(result.group_id || groupId);
      setActiveGroupId(gid);
      await refreshGroups();
      setExpandedGroups((s) => new Set(s).add(gid));
      setMessage({ text: `方案 ${slotName} 槽位测算完成。`, kind: 'success' });
    } catch (e) {
      setMessage({ text: `测算失败：${(e as Error).message}`, kind: 'error' });
    }
  }, [buildForm, refreshGroups]);

  /** 打开某槽位方案：拉方案 → 填参数 → 渲染其 result。 */
  const openSlot = useCallback(async (planId: string, gid: string) => {
    try {
      const plan = await getPlan(planId);
      if (!plan) throw new Error('方案不存在');
      setActiveGroupId(plan.group_id || gid);
      setHubOpen(false);
      if (plan.params) {
        const p = plan.params as Record<string, unknown>;
        setParams((s) => ({
          ...s,
          projectId: String(p.overview_id || p.project_id || s.projectId),
          targetTotal: p.target_total != null ? String(p.target_total) : s.targetTotal,
          fixedPretax: p.fixed_pretax != null ? String(p.fixed_pretax) : s.fixedPretax,
          vatRate: p.vat_rate != null ? String(Math.round(Number(p.vat_rate) * 100)) : s.vatRate,
          surtaxRate: p.surtax_rate != null ? String(Math.round(Number(p.surtax_rate) * 100)) : s.surtaxRate,
          ratioLow: p.ratio_min != null ? Math.round(Number(p.ratio_min) * 100) : s.ratioLow,
          ratioHigh: p.ratio_max != null ? Math.round(Number(p.ratio_max) * 100) : s.ratioHigh,
        }));
      }
      if (plan.result) {
        setResult(plan.result);
        setMessage({ text: `已打开方案「${plan.name || plan.id}」。`, kind: 'success' });
      } else {
        setMessage({ text: '已打开方案，但该槽位尚未生成结果，可点击「按当前参数重算」。', kind: 'success' });
      }
    } catch (e) {
      setMessage({ text: `打开方案失败：${(e as Error).message}`, kind: 'error' });
    }
  }, []);

  const doRename = useCallback(async (gid: string, name: string) => {
    if (!name) return;
    try { await renameGroup(gid, name); await refreshGroups(); setMessage({ text: '已重命名方案组。', kind: 'success' }); }
    catch (e) { setMessage({ text: `重命名失败：${(e as Error).message}`, kind: 'error' }); }
  }, [refreshGroups]);

  const doCopy = useCallback(async (gid: string) => {
    if (!(await confirm('复制整组为独立新组（深拷贝组内已算槽位方案，可独立改参）？', { okLabel: '复制整组', ariaLabel: '复制方案组' }))) return;
    try {
      const res = await copyGroup(gid);
      setMessage({ text: `已复制整组为「${res.group?.group_name || ''}」。`, kind: 'success' });
      await refreshGroups();
    } catch (e) { setMessage({ text: `复制整组失败：${(e as Error).message}`, kind: 'error' }); }
  }, [refreshGroups, confirm]);

  const doFinalizeGroup = useCallback(async (gid: string, on: boolean) => {
    try {
      await finalizeGroup(gid, on);
      setMessage({ text: on ? '已整组定稿锁定（组内槽位不可删改）。' : '已取消整组定稿。', kind: 'success' });
      await refreshGroups();
    } catch (e) { setMessage({ text: `定稿切换失败：${(e as Error).message}`, kind: 'error' }); }
  }, [refreshGroups]);

  const doDelete = useCallback(async (gid: string) => {
    if (!(await confirm('删除该方案组？组内已算槽位方案将一并删除。', {
      danger: true, title: '删除方案组', sub: '组内已算槽位方案将一并删除，此操作不可恢复。', okLabel: '仍要删除', ariaLabel: '删除方案组',
    }))) return;
    try {
      await deleteGroup(gid);
      setSelectedPlans(new Set());
      setExpandedGroups((s) => { const n = new Set(s); n.delete(gid); return n; });
      if (activeGroupId === gid) setActiveGroupId('');
      setMessage({ text: '方案组已删除。', kind: 'success' });
      await refreshGroups();
    } catch (e) { setMessage({ text: `删除方案组失败：${(e as Error).message}`, kind: 'error' }); }
  }, [refreshGroups, activeGroupId, confirm]);

  /** 多方案对比（限同一项目）。 */
  const runCompare = useCallback(async () => {
    const ids = Array.from(selectedPlans);
    if (ids.length < 2) { setMessage({ text: '多方案对比至少需要勾选 2 个槽位。', kind: 'error' }); return; }
    setMessage({ text: '正在对比方案，请稍候。', kind: 'info' });
    try {
      const res = await comparePlans(ids);
      setCompareRes(res);
      setCompareOpen(true);
      setMessage({ text: `对比完成：${(res.plan_ids || []).length} 个方案。低于 50% 报价比率的为风险项，是否构成废标以招标文件为准。`, kind: 'success' });
    } catch (e) { setMessage({ text: `对比失败：${(e as Error).message}`, kind: 'error' }); }
  }, [selectedPlans]);

  /** 定稿并回写项目经营概览（仅写投标报价金额）。 */
  const runFinalize = useCallback(async () => {
    const amt = Number(params.targetTotal);
    if (!Number.isFinite(amt) || amt <= 0) {
      setMessage({ text: '定稿回写取消：目标总报价为空或非正数，没有可写回的金额。请先填写有效的目标总报价。', kind: 'error' });
      return;
    }
    if (!params.projectId) {
      setMessage({ text: '定稿回写需要先选择「关联投标项目」。', kind: 'error' });
      return;
    }
    const proj = projects.find((p) => p.id === params.projectId);
    const ok = await confirm(
      `将本次目标总报价 ${amt.toLocaleString('zh-CN', { minimumFractionDigits: 2 })} 元写回为「${proj?.name ?? ''}」的投标报价金额？`,
      { title: '定稿并回写项目', sub: '投标成本测算不随本次回写，请在「项目经营概览」中手动填写。', okLabel: '定稿回写', ariaLabel: '定稿并回写项目' });
    if (!ok) return;
    try {
      await finalizeOverview(params.projectId, String(amt));
      const planId = result?.plan_id as string | undefined;
      if (planId) await markPlanFinalized(planId);
      setMessage({ text: `已定稿并回写项目经营概览：该项目的投标报价金额已更新为 ${amt.toLocaleString('zh-CN', { minimumFractionDigits: 2 })} 元。`, kind: 'success' });
    } catch (e) {
      setMessage({ text: `定稿回写失败：${(e as Error).message}`, kind: 'error' });
    }
  }, [params.targetTotal, params.projectId, projects, result, confirm]);

  return (
    <div className="page page-quote" id="quoteView">
      <PageHead
        zh="投标报价"
        en="Quote"
        sub="算得准，才敢报。"
        subEn="Price it right — three strategies, one sandbox. All calculations stay local."
      />

      {message && (
        <div className={`ui-alert ui-alert--${message.kind === 'error' ? 'error' : message.kind === 'success' ? 'success' : message.kind === 'warn' ? 'warn' : 'info'}`} role="status">
          {message.text}
        </div>
      )}

      <div className="workbench-layout">
        <QuoteParams
          params={params}
          set={set}
          comp={taxComp}
          setComp={setTaxComp}
          projects={projects}
          capFile={capName}
          costFile={costName}
          onFile={onFile}
          onPreview={runPreview}
          previewing={previewing}
          capStat={preview ? `已解析 ${preview.cap.rows} 行 ｜ 匹配 ${preview.match.matched}` : ''}
          costStat={preview ? `已解析 ${preview.cost.rows} 行` : ''}
        />

        <section className="canvas-column">
          {!hasResult && <QuoteReady ready={ready} onCalculate={runCalculate} calculating={calculating} balanceText="" />}
          {!hasResult && preview && <QuotePreview res={preview} />}
          {hasResult && <StatusCapsule text="推演完成" />}
          {hasResult && <QuoteSchemeBar
            visible={Boolean(activeGroupId)}
            group={groups.find((g) => g.group_id === activeGroupId) || null}
            activeSlot={activeSlot}
            balanceText={`${groups.find((g) => g.group_id === activeGroupId) ? '当前组已算 ' + Object.values(groups.find((g) => g.group_id === activeGroupId)?.strategy_slots || {}).filter((s) => s && (s.plan_id || s.summary?.plan_id)).length + ' 槽' : '未加载方案组'} ｜ 槽位 A=逐项最优 / B=等比下浮`}
            onSwitch={switchSlot}
          />}
          {hasResult && <QuoteKpi
            result={result}
            compliance={compliance}
            vat={vat}
            marginRate={margin}
            drillFilter={dashFilter}
            drillSortMargin={dashSortMargin}
            onDrillTotal={drillTotal}
            onDrillMargin={drillMargin}
            onDrillRisk={drillRisk}
          />}
          {hasResult && <QuoteTable
            items={(result?.items ?? []) as never}
            totalCount={(result?.items ?? []).length}
            filter={dashFilter}
            sortMargin={dashSortMargin}
            page={dashPage}
            onFilter={setDashFilter}
            onSortMargin={setDashSortMargin}
            onPage={setDashPage}
            actions={<QuoteActions result={result as QuoteResult} savedPlan={Boolean(result?.plan_id)} canFinalize={Boolean(params.projectId)} onFinalize={runFinalize} onRecompute={runRecompute} recomputing={calculating} />}
          />}
          {Boolean(params.projectId) && (
            <div className="action-row" style={{ marginTop: 12 }}>
              <button type="button" className="btn-secondary" onClick={() => setHubOpen(true)}>方案中心</button>
              <button type="button" className="btn-ghost" id="auditDockBtn" style={{ marginLeft: 8 }} onClick={() => setAuditOpen(true)}>审计日志</button>
            </div>
          )}
        </section>
      </div>

      <QuotePlanHub
        open={hubOpen}
        projectName={projects.find((p) => p.id === params.projectId)?.name || ''}
        groups={groups}
        selected={selectedPlans}
        expanded={expandedGroups}
        onToggleGroup={(gid) => setExpandedGroups((s) => { const n = new Set(s); n.has(gid) ? n.delete(gid) : n.add(gid); return n; })}
        onRename={doRename}
        onCopy={doCopy}
        onFinalize={doFinalizeGroup}
        onDelete={doDelete}
        onCalcSlot={calcSlot}
        onOpenSlot={openSlot}
        onToggleSelect={(pid, on) => setSelectedPlans((s) => { const n = new Set(s); on ? n.add(pid) : n.delete(pid); return n; })}
        onCompare={runCompare}
        onClose={() => setHubOpen(false)}
      />
      <QuoteCompareModal open={compareOpen} res={compareRes} onClose={() => setCompareOpen(false)} />
      <QuoteAuditModal open={auditOpen} onClose={() => setAuditOpen(false)} />
    </div>
  );
}

import { useCallback, useMemo, useRef, useState } from 'react';
import { computeCompliance, computeInputVat, marginRatePercent, type QuoteResult } from './quoteCalc';
import { QuoteParams, VOLT_DEFAULT_COMP } from './QuoteParams';
import { QuoteKpi } from './QuoteKpi';
import { QuoteTable } from './QuoteTable';
import { QuotePreview } from './QuotePreview';
import { QuoteReady, StatusCapsule, computeReady } from './QuoteReady';
import { previewQuote, optimizeQuote } from './quoteApi';
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
  const [message, setMessage] = useState<{ text: string; kind: 'info' | 'error' | 'success' } | null>(null);
  const [taxComp, setTaxComp] = useState<TaxComp[]>(VOLT_DEFAULT_COMP);
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
  const buildForm = useCallback((strategy: string): FormData | null => {
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
    data.append('group_id', '');
    return data;
  }, [params, taxComp]);

  /** 计算（方案 A optimal）：提交 → 渲染结果。方案组/对比属块 4。 */
  const runCalculate = useCallback(async () => {
    const form = buildForm('optimal');
    if (!form) { setMessage({ text: '请先上传限价清单和成本清单。', kind: 'error' }); return; }
    setCalculating(true);
    setMessage({ text: '正在识别清单并运行 Phase 2 MILP（方案 A：逐项最优），请稍候。', kind: 'info' });
    try {
      // 后端返回体即完整 result（字段在顶层，无 result 嵌套，与 app.js 一致）。
      // 非 PASS（含 BLOCKED）由 postForm 按 !r.ok 抛错，此处只处理 PASS。
      const result = await optimizeQuote(form);
      setResult(result as QuoteResult);
      setMessage({
        text: `方案 A 计算完成：竞争性预算 ${Number(result.competitive_budget).toLocaleString('zh-CN', { minimumFractionDigits: 2 })} 元，结算调整后利润（不含增值税）${Number(result.objective).toLocaleString('zh-CN', { minimumFractionDigits: 2 })} 元。`,
        kind: 'success',
      });
    } catch (e) {
      setMessage({ text: `计算失败：${(e as Error).message}`, kind: 'error' });
    } finally {
      setCalculating(false);
    }
  }, [buildForm]);

  const hasResult = Boolean(result);

  return (
    <div className="page page-quote" id="quoteView">
      <div className="breadcrumb">投标报价 <span>/</span> 优化沙盘</div>

      {message && (
        <div className={`ui-alert ui-alert--${message.kind === 'error' ? 'error' : message.kind === 'success' ? 'success' : 'info'}`} role="status">
          {message.text}
        </div>
      )}

      <div className="workbench-layout">
        <QuoteParams
          params={params}
          set={set}
          comp={taxComp}
          setComp={setTaxComp}
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
          {hasResult && <QuoteKpi result={result} compliance={compliance} vat={vat} marginRate={margin} />}
          {hasResult && <QuoteTable items={(result?.items ?? []) as never} totalCount={(result?.items ?? []).length} />}
        </section>
      </div>
    </div>
  );
}

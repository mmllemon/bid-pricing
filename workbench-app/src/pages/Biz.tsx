import { useCallback, useEffect, useMemo, useState } from 'react';
import { IconClose, IconPlus, IconSearch } from '../components/icons';
import { API_BASE, pct, toNum, yf } from './bizShared';
import type { ProjectOverview } from './bizShared';
import { useNavigate } from 'react-router-dom';
import PageHead from '../components/PageHead';

/**
 * 项目经营（M-01）：母项目「除个人工作台外唯一保留」的功能区，整体迁自
 * `frontend/workbench.js` 的 renderBizPage / bizEditModal / deriveProj。
 * 数据源是本项目 FastAPI（:8000）的 /api/project/overview/*，与母项目 workbench.js
 * 的 API_BASE 约定一致（可用 window.__API_BASE__ 覆盖）。
 *
 * 对齐清单（逐项照搬，不增不减）：
 * - 4 指标卡：项目总数 / 投标中 / 在建中 / 总毛利合计（null 按 0 计入合计）
 * - 五列看板：投标 / 中标在建 / 已竣工 / 已结算 / 售后 + 「未中标」折叠归档
 * - 搜索（按项目名称模糊匹配）、每列独立排序（默认/名称/开标日期/报价金额/总毛利）
 * - 卡片堆叠：列内绝对定位错位下移（TAB_H + i*CAS），悬停/聚焦展开完整指标
 * - 新建/编辑弹窗：11 个可编辑字段 + 3 个自动派生指标实时预览 + 删除
 */
const STAGES = ['投标', '中标在建', '已竣工', '已结算', '售后'];
const ARCHIVE = '未中标';
/** 阶段 → 样式类（与母项目 cls() 同义；仅用系统四色，灰阶以描边代替） */
const STAGE_CLASS: Record<string, string> = {
  投标: 'b-bid',
  中标在建: 'b-run',
  已竣工: 'b-done',
  已结算: 'b-settle',
  售后: 'b-svc',
  未中标: 'b-arch',
};

const TAB_H = 48;
const CARD_CASCADE = 30;

const SORT_OPTIONS: Array<[string, string]> = [
  ['default', '默认'],
  ['name', '名称'],
  ['date', '开标日期'],
  ['amount', '报价金额'],
  ['profit', '总毛利'],
];

/** 派生指标：总毛利/总毛利率/实际收益率（与母项目 deriveProj() 逐行为同）。 */
function derive(f: Record<string, string>): { gross_profit: number | null; gross_margin: number | null; actual_yield: number | null } {
  const ba = toNum(f.bid_amount);
  const bc = toNum(f.bid_cost);
  let gross_profit: number | null = null;
  let gross_margin: number | null = null;
  if (ba != null && bc != null) {
    gross_profit = ba - bc;
    gross_margin = ba ? (ba - bc) / ba : null;
  }
  const ar = toNum(f.actual_revenue);
  const ac = toNum(f.actual_cost);
  const actual_yield = ar != null && ac != null && ac ? (ar - ac) / ac : null;
  return { gross_profit, gross_margin, actual_yield };
}

function sortList(list: ProjectOverview[], key: string): ProjectOverview[] {
  if (!key || key === 'default') return list;
  const arr = list.slice();
  arr.sort((a, b) => {
    if (key === 'name') return (a.name || '').localeCompare(b.name || '', 'zh');
    if (key === 'date') return (a.bid_open_date || '').localeCompare(b.bid_open_date || '');
    const field = key === 'amount' ? 'bid_amount' : 'gross_profit';
    return (toNum(a[field as keyof ProjectOverview]) ?? 0) - (toNum(b[field as keyof ProjectOverview]) ?? 0);
  });
  return arr;
}

interface CardProps {
  p: ProjectOverview;
  index?: number;
  todoCount?: number;
  onOpen: (p: ProjectOverview) => void;
}

function BizCard({ p, index, todoCount, onOpen }: CardProps) {
  const gp = toNum(p.gross_profit);
  const gm = toNum(p.gross_margin);
  const clsV = gm != null ? (gm < 0 ? ' neg' : ' pos') : '';
  const short = (p.short_name || '').trim();
  const disp = short || p.name || '';
  const tip = short && p.name && short !== p.name ? `${short} · ${p.name}` : disp;
  const stacked = typeof index === 'number';
  const stage = p.stage || '—';
  // 收款进度条：已收（actual_revenue）/ 合同额（bid_amount），借鉴参考项目作品卡的数据条
  const recv = toNum(p.actual_revenue);
  const contract = toNum(p.bid_amount);
  const recvRate = recv != null && contract ? Math.max(0, Math.min(1, recv / contract)) : null;

  return (
    <div
      className={`biz-card${stacked ? ' stacked' : ' flat'} rise-in`}
      data-stage={stage}
      role="button"
      tabIndex={0}
      aria-label={`${disp} 项目卡片`}
      style={stacked
        ? { top: (index as number) * CARD_CASCADE, animationDelay: `${(index as number) * 60}ms` }
        : { animationDelay: '0ms' }}
      onClick={() => onOpen(p)}
      onKeyDown={(e) => {
        if (e.key === 'Enter') onOpen(p);
      }}
    >
      <div className={`biz-tab ${STAGE_CLASS[stage] || 'b-arch'}`} title={tip}>
        <b>{disp}</b>
        <i>{stage}</i>
      </div>
      <div className="biz-main">
        <div className="biz-top">
          <span className="biz-name" title={p.name || ''}>{p.name}</span>
          <span className="nb-badge">{stage}</span>
          {(todoCount || 0) > 0 && <span className="nb-badge">待办 {todoCount}</span>}
        </div>
        {recvRate != null && (
          <div className="biz-recv" title={`已收 ${yf(recv)} / 合同额 ${yf(contract)}`}>
            <i style={{ width: `${Math.round(recvRate * 100)}%` }} />
            <span>收款 {Math.round(recvRate * 100)}%</span>
          </div>
        )}
        <div className="biz-metrics">
          <div className="biz-metric"><span className="l">总限价</span><span className="v">{yf(p.limit_total)}</span></div>
          <div className="biz-metric"><span className="l">开标日期</span><span className="v">{p.bid_open_date || '—'}</span></div>
          <div className="biz-metric"><span className="l">投标报价金额</span><span className="v">{yf(p.bid_amount)}</span></div>
          <div className="biz-metric"><span className="l">投标成本测算</span><span className="v">{yf(p.bid_cost)}</span></div>
          <div className="biz-metric"><span className="l">总毛利</span><span className={`v${clsV}`}>{yf(gp)}</span></div>
          <div className="biz-metric"><span className="l">总毛利率</span><span className={`v${clsV}`}>{pct(gm)}</span></div>
        </div>
        <div className="biz-foot">点击卡片进入项目主页 · 阶段下拉为流转唯一入口</div>
      </div>
    </div>
  );
}

const EMPTY_FORM: Record<string, string> = {
  name: '',
  short_name: '',
  limit_total: '',
  bid_open_date: '',
  stage: '投标',
  bid_amount: '',
  bid_cost: '',
  actual_cost: '',
  actual_revenue: '',
  settle_amount: '',
  completed_at: '',
};

const FORM_FIELDS: Array<{ key: string; label: string; placeholder: string }> = [
  { key: 'limit_total', label: '项目总限价金额', placeholder: '如：1500000' },
  { key: 'bid_amount', label: '投标报价金额', placeholder: '定稿后由报价页回写' },
  { key: 'bid_cost', label: '投标成本测算', placeholder: '定稿后由报价页回写' },
  { key: 'actual_cost', label: '实际成本', placeholder: '' },
  { key: 'actual_revenue', label: '实际营收', placeholder: '' },
  { key: 'settle_amount', label: '结算金额', placeholder: '' },
];

export interface BizModalProps {
  project: ProjectOverview | null;
  todos: TodoLite[];
  onClose: () => void;
  onSaved: () => void;
}

export function BizEditModal({ project, todos, onClose, onSaved }: BizModalProps) {
  const isNew = !project;
  const [form, setForm] = useState<Record<string, string>>(() => {
    const base = { ...EMPTY_FORM };
    if (project) {
      Object.keys(EMPTY_FORM).forEach((k) => {
        const v = (project as unknown as Record<string, unknown>)[k];
        if (v != null) base[k] = String(v);
      });
      base.stage = project.stage || '投标';
    }
    return base;
  });
  const [saving, setSaving] = useState(false);
  // W-3：Modal 内错误走行内 ui-alert，不再 window.alert（系统灰框破 V2 视觉）
  const [formError, setFormError] = useState('');
  const [confirmArmed, setConfirmArmed] = useState(false);
  const derived = derive(form);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose]);

  const set = (k: string) => (e: { target: { value: string } }) =>
    setForm((prev) => ({ ...prev, [k]: e.target.value }));

  async function save() {
    if (!form.name.trim()) {
      setFormError('请填写项目名称');
      return;
    }
    setFormError('');
    const data = new FormData();
    Object.entries(form).forEach(([k, v]) => data.append(k, v));
    if (project?.id) data.append('pid', project.id);
    setSaving(true);
    try {
      const r = await fetch(`${API_BASE}/api/project/overview/save`, { method: 'POST', body: data });
      const j = (await r.json()) as { status?: string; reason?: string };
      if (!r.ok || j.status !== 'PASS') throw new Error(j.reason || '保存失败');
      onSaved();
      onClose();
    } catch (err) {
      setSaving(false);
      setFormError(`保存失败：${err instanceof Error ? err.message : String(err)}`);
    }
  }

  async function del() {
    if (!project) return;
    // 二次确认走行内：首次点删除变"确认删除"，3 秒内再点执行（替代 window.confirm）
    if (!confirmArmed) {
      setConfirmArmed(true);
      window.setTimeout(() => setConfirmArmed(false), 3000);
      return;
    }
    const data = new FormData();
    data.append('id', project.id);
    try {
      const r = await fetch(`${API_BASE}/api/project/overview/delete`, { method: 'POST', body: data });
      const j = (await r.json()) as { status?: string; reason?: string };
      if (!r.ok || j.status !== 'PASS') throw new Error(j.reason || '删除失败');
      onSaved();
      onClose();
    } catch (err) {
      setConfirmArmed(false);
      setFormError(`删除失败：${err instanceof Error ? err.message : String(err)}`);
    }
  }

  return (
    <div
      className="biz-mask"
      role="dialog"
      aria-modal="true"
      aria-label={isNew ? '新建项目' : '编辑项目'}
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="biz-modal">
        <div className="biz-mhead">
          <h3>{isNew ? '新建项目' : '编辑项目'}</h3>
          <button type="button" className="nb-btn nb-btn--ghost biz-x" aria-label="关闭" onClick={onClose}>
            <IconClose size={14} />
          </button>
        </div>
        <div className="biz-mform">
          <label className="biz-fld wide">
            <span>项目名称 *</span>
            <input value={form.name} onChange={set('name')} placeholder="如：西永L分区项目" autoFocus />
          </label>
          <label className="biz-fld wide">
            <span>简称（选填，显示在便利贴上）</span>
            <input value={form.short_name} onChange={set('short_name')} placeholder="如：西永L" />
          </label>
          {FORM_FIELDS.slice(0, 1).map((f) => (
            <NumberField key={f.key} field={f} value={form[f.key]} onChange={set(f.key)} />
          ))}
          <label className="biz-fld">
            <span>开标日期</span>
            <input type="date" value={form.bid_open_date} onChange={set('bid_open_date')} />
          </label>
          {FORM_FIELDS.slice(1, 3).map((f) => (
            <NumberField key={f.key} field={f} value={form[f.key]} onChange={set(f.key)} />
          ))}
          <label className="biz-fld">
            <span>项目进行阶段</span>
            <select value={form.stage} onChange={set('stage')}>
              {[...STAGES, ARCHIVE].map((s) => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
          </label>
          {FORM_FIELDS.slice(3).map((f) => (
            <NumberField key={f.key} field={f} value={form[f.key]} onChange={set(f.key)} />
          ))}
          <label className="biz-fld">
            <span>竣工时间</span>
            <input type="date" value={form.completed_at} onChange={set('completed_at')} />
          </label>
          <div className="biz-derived wide">
            <div><span>总毛利（自动）</span><b>{yf(derived.gross_profit)}</b></div>
            <div><span>总毛利率（自动）</span><b>{pct(derived.gross_margin)}</b></div>
            <div><span>实际收益率（自动）</span><b>{pct(derived.actual_yield)}</b></div>
          </div>
          {!isNew && (
            <div className="wide">
              <div className="biz-todos-head">关联待办（{todos.filter((t) => t.projectId === project!.id).length}）</div>
              {todos.filter((t) => t.projectId === project!.id).length === 0 ? (
                <p className="nb-muted" style={{ fontSize: 13 }}>暂无关联待办，可在「待办」页点开待办详情挂到本项目。</p>
              ) : (
                todos.filter((t) => t.projectId === project!.id).map((t) => (
                  <div key={t.id} className="biz-todo-row">
                    <span className="biz-todo-title">{t.title}</span>
                    <span className="nb-badge">{t.status || ''}</span>
                  </div>
                ))
              )}
            </div>
          )}
        </div>
        {formError && <div className="ui-alert ui-alert--error" role="alert">{formError}</div>}
        <div className="biz-mactions">
          {!isNew ? (
            <button type="button" className="nb-btn biz-danger" onClick={del}>
              {confirmArmed ? '再点确认删除' : '删除'}
            </button>
          ) : (
            <span />
          )}
          <button type="button" className="nb-btn nb-btn--ghost" onClick={onClose}>取消</button>
          <button type="button" className="nb-btn nb-btn--primary" onClick={save} disabled={saving}>
            {saving ? '保存中…' : '保存'}
          </button>
        </div>
      </div>
    </div>
  );
}

function NumberField({
  field,
  value,
  onChange,
}: {
  field: { key: string; label: string; placeholder: string };
  value: string;
  onChange: (e: { target: { value: string } }) => void;
}) {
  return (
    <label className="biz-fld">
      <span>{field.label}</span>
      <input type="number" step="0.01" value={value} onChange={onChange} placeholder={field.placeholder} />
    </label>
  );
}

export interface TodoLite {
  id: number;
  title: string;
  status?: string;
  projectId?: string;
}

export default function BizPage() {
  const navigate = useNavigate();
  const [projects, setProjects] = useState<ProjectOverview[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [query, setQuery] = useState('');
  const [sortMap, setSortMap] = useState<Record<string, string>>({});
  const [showModal, setShowModal] = useState(false);
  const [editing, setEditing] = useState<ProjectOverview | null>(null);
  // 待办（:3456 同源 /api，相对路径即可）：按 projectId 聚合到项目卡片/编辑弹窗
  const [todos, setTodos] = useState<TodoLite[]>([]);
  // 全公司资金汇总（:8000）：应收未收 / 资金压力
  const [fund, setFund] = useState<{ receivable: number; fund_pressure: number | null } | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    setError('');
    fetch(`${API_BASE}/api/project/overview/list`)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json() as Promise<{ projects?: ProjectOverview[] }>;
      })
      .then((json) => setProjects(json?.projects ?? []))
      .catch((e: unknown) => {
        setProjects([]);
        setError(e instanceof Error ? e.message : String(e));
      })
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    load();
    // 全公司资金汇总：失败不阻塞（:8000 未起时仅无资金 KPI）
    fetch(`${API_BASE}/api/project/exec/summary`)
      .then((r) => (r.ok ? r.json() : null))
      .then((j: unknown) => {
        const s = (j as { summary?: { receivable?: number; fund_pressure?: number | null } })?.summary;
        if (s) setFund({ receivable: s.receivable ?? 0, fund_pressure: s.fund_pressure ?? null });
      })
      .catch(() => {});
  }, [load]);

  useEffect(() => {
    // 待办列表：失败不阻塞项目页（:3456 未起或接口异常时仅无聚合显示）
    fetch('/api/todos')
      .then((r) => (r.ok ? r.json() : []))
      .then((j: unknown) => setTodos(Array.isArray(j) ? (j as TodoLite[]) : []))
      .catch(() => setTodos([]));
  }, []);

  // projectId → 关联待办数（未关联的不计）
  const todoCountByProject = useMemo(() => {
    const m = new Map<string, number>();
    todos.forEach((t) => {
      if (t.projectId) m.set(t.projectId, (m.get(t.projectId) || 0) + 1);
    });
    return m;
  }, [todos]);

  const bidding = projects.filter((p) => p.stage === '投标').length;
  const building = projects.filter((p) => p.stage === '中标在建').length;
  const grossTotal = projects.reduce((acc, p) => acc + (toNum(p.gross_profit) ?? 0), 0);

  const metrics: Array<{ label: string; en: string; value: string }> = [
    { label: '项目总数', en: 'Total', value: String(projects.length) },
    { label: '投标中', en: 'Bidding', value: String(bidding) },
    { label: '在建中', en: 'Running', value: String(building) },
    { label: '总毛利合计', en: 'Gross profit', value: yf(grossTotal) },
    { label: '应收未收', en: 'Receivable', value: fund ? yf(fund.receivable) : '—' },
    { label: '资金压力', en: 'Pressure', value: fund?.fund_pressure != null ? pct(fund.fund_pressure) : '—' },
  ];

  const q = query.trim().toLowerCase();
  const filtered = useMemo(
    () => (q ? projects.filter((p) => (p.name || '').toLowerCase().includes(q)) : projects),
    [projects, q],
  );

  const { buckets, archived } = useMemo(() => {
    const b: Record<string, ProjectOverview[]> = {};
    STAGES.forEach((s) => { b[s] = []; });
    const arch: ProjectOverview[] = [];
    filtered.forEach((p) => {
      const s = p.stage || '';
      (STAGES.includes(s) ? b[s] : arch).push(p);
    });
    STAGES.forEach((s) => { b[s] = sortList(b[s], sortMap[s]); });
    return { buckets: b, archived: arch };
  }, [filtered, sortMap]);

  const openNew = () => { setEditing(null); setShowModal(true); };

  return (
    <div className="ui-page">
      <PageHead zh="项目库" en="Projects" sub="每个项目，都是一盘生意。" subEn="Every project is a business — stages, money and risks at a glance.">
        <button className="nb-btn nb-btn--ghost" onClick={load} disabled={loading}>
          {loading ? '读取中…' : '刷新'}
        </button>
        <button type="button" className="nb-btn nb-btn--primary" onClick={openNew}>
          <IconPlus size={16} /> 新建项目
        </button>
      </PageHead>

      {error && (
        <div className="ui-alert ui-alert--error">
          暂无法连接后端服务（{error}）。请先启动 8000 端口服务。
        </div>
      )}

      <section className="kpi-band" aria-label="项目经营指标">
        {metrics.map((m) => (
          <div key={m.label}>
            <span className="kpi-label">{m.label}<em>{m.en}</em></span>
            <span className="kpi-value">{m.value}</span>
          </div>
        ))}
      </section>

      <section className="ui-module" aria-label="项目全生命周期看板">
        <div className="ui-module-head">
          <h2 className="ui-module-title"><span className="ui-code">M-01</span>项目全生命周期看板</h2>
          <span className="nb-badge">{projects.length} 个</span>
        </div>

        <div className="biz-toolbar">
          <div className="biz-search">
            <IconSearch size={15} />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="搜索项目…"
              aria-label="搜索项目"
            />
          </div>
        </div>

        {loading && projects.length === 0 ? (
          <div className="empty-state"><p>读取中…</p></div>
        ) : projects.length === 0 ? (
          <div className="empty-state"><p>还没有项目，点右上角「新建项目」创建一个开始经营概览。</p></div>
        ) : filtered.length === 0 ? (
          <div className="empty-state"><p>没有匹配「{query.trim()}」的项目。</p></div>
        ) : (
          <>
            <div className="biz-cols">
              {STAGES.map((s) => {
                const arr = buckets[s];
                const bodyStyle = arr.length ? { height: TAB_H + (arr.length - 1) * CARD_CASCADE + 8 } : undefined;
                return (
                  <div className="biz-col" key={s}>
                    <div className="biz-col-head">
                      <span className={`biz-stage-dot ${STAGE_CLASS[s]}`} aria-hidden="true" />
                      {s}
                      <span className="biz-col-count">{arr.length}</span>
                      <select
                        className="biz-col-sort"
                        aria-label={`${s} 排序`}
                        value={sortMap[s] || 'default'}
                        onChange={(e) => setSortMap((prev) => ({ ...prev, [s]: e.target.value }))}
                      >
                        {SORT_OPTIONS.map(([v, label]) => (
                          <option key={v} value={v}>{label}</option>
                        ))}
                      </select>
                    </div>
                    <div className="biz-col-body" style={bodyStyle}>
                      {arr.length === 0
                        ? <div className="biz-col-empty">—</div>
                        : arr.map((p, i) => <BizCard key={p.id} p={p} index={i} todoCount={todoCountByProject.get(p.id) || 0} onOpen={(pp) => navigate(`/biz/${pp.id}`)} />)}
                    </div>
                  </div>
                );
              })}
            </div>

            <details className="biz-arch">
              <summary>未中标归档（{archived.length}）</summary>
              {archived.length > 0 && (
                <div className="biz-arch-grid">
                  {archived.map((p) => <BizCard key={p.id} p={p} todoCount={todoCountByProject.get(p.id) || 0} onOpen={(pp) => navigate(`/biz/${pp.id}`)} />)}
                </div>
              )}
            </details>
          </>
        )}

        <p className="biz-note">
          所有金额单位：元（保留 2 位小数）。是否废标以招标文件为准；低价确认仅记录留痕，不做废标判定。
        </p>
      </section>

      {showModal && (
        <BizEditModal
          project={editing}
          todos={todos}
          onClose={() => setShowModal(false)}
          onSaved={load}
        />
      )}
    </div>
  );
}

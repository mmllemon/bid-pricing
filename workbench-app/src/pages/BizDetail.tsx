import { useCallback, useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { API_BASE, pct, yf } from './bizShared';
import type { ExecSummary, ProjectOverview } from './bizShared';
import { BizEditModal } from './Biz';
import type { TodoLite } from './Biz';

/**
 * 项目主页（M-01 详情）：/biz/:id
 * 一个项目一页，tab 式——概况 / 报价 / 执行 / 待办，一屏回答「这个项目现在怎么样」。
 * 数据源：:8000 /api/project/overview/*（项目） /api/group/list（报价方案组）
 *         /api/project/exec/*（执行四表）；:3456 /api/todos（待办，相对路径）。
 */

type TabKey = 'overview' | 'quote' | 'exec' | 'docs' | 'todos';
const TABS: Array<[TabKey, string]> = [
  ['overview', '概况'],
  ['quote', '报价'],
  ['exec', '执行'],
  ['docs', '文档'],
  ['todos', '待办'],
];

interface SlotInfo {
  plan_id?: string | null;
  strategy?: string | null;
  status?: string | null;
  summary?: {
    target_total?: number | null;
    competitive_budget?: number | null;
    saved_at?: string | null;
  } | null;
}

interface QuoteGroup {
  group_id: string;
  group_name?: string | null;
  project_name?: string | null;
  finalized?: boolean | number | null;
  strategy_slots?: Record<string, SlotInfo> | null;
}

const SLOT_LABEL: Record<string, string> = { A: '均衡', B: '均匀', C: '不平衡' };

/* ---------------- 执行四表配置 ---------------- */
interface ExecColumn {
  key: string;
  label: string;
  type: 'text' | 'number' | 'date' | 'select';
  options?: string[];
}
interface ExecTableDef {
  key: string;
  title: string;
  columns: ExecColumn[];
}
const EXEC_TABLES: ExecTableDef[] = [
  {
    key: 'contract', title: '收入合同',
    columns: [
      { key: 'contract_no', label: '合同编号', type: 'text' },
      { key: 'client', label: '甲方', type: 'text' },
      { key: 'amount', label: '合同金额', type: 'number' },
      { key: 'signed_at', label: '签订日期', type: 'date' },
      { key: 'note', label: '备注', type: 'text' },
    ],
  },
  {
    key: 'cost', title: '成本台帐',
    columns: [
      { key: 'category', label: '科目', type: 'select', options: ['人工', '材料', '机械', '分包', '其他'] },
      { key: 'target', label: '目标成本', type: 'number' },
      { key: 'actual', label: '实际成本', type: 'number' },
      { key: 'occurred_at', label: '发生日期', type: 'date' },
      { key: 'note', label: '备注', type: 'text' },
    ],
  },
  {
    key: 'payment', title: '进度款',
    columns: [
      { key: 'period', label: '期次', type: 'text' },
      { key: 'claimed', label: '申报金额', type: 'number' },
      { key: 'claimed_at', label: '申报日期', type: 'date' },
      { key: 'status', label: '状态', type: 'select', options: ['待审', '已批', '驳回'] },
      { key: 'received', label: '到账金额', type: 'number' },
      { key: 'received_at', label: '到账日期', type: 'date' },
      { key: 'note', label: '备注', type: 'text' },
    ],
  },
  {
    key: 'visa', title: '签证变更',
    columns: [
      { key: 'no', label: '编号', type: 'text' },
      { key: 'kind', label: '类型', type: 'select', options: ['收方', '变更', '签证', '索赔'] },
      { key: 'amount', label: '金额', type: 'number' },
      { key: 'status', label: '状态', type: 'select', options: ['待批', '已批'] },
      { key: 'date', label: '日期', type: 'date' },
      { key: 'note', label: '备注', type: 'text' },
    ],
  },
  {
    key: 'settlement', title: '结算',
    columns: [
      { key: 'round', label: '轮次', type: 'select', options: ['初审', '终审'] },
      { key: 'submit_amount', label: '送审金额', type: 'number' },
      { key: 'submit_date', label: '送审日期', type: 'date' },
      { key: 'approved_amount', label: '审定金额', type: 'number' },
      { key: 'approved_date', label: '审定日期', type: 'date' },
      { key: 'status', label: '状态', type: 'select', options: ['未送审', '已送审', '审定中', '已审定'] },
      { key: 'note', label: '备注', type: 'text' },
    ],
  },
  {
    key: 'subcontract', title: '劳务分包',
    columns: [
      { key: 'subcontractor', label: '分包单位', type: 'text' },
      { key: 'scope', label: '分包内容', type: 'text' },
      { key: 'amount', label: '合同金额', type: 'number' },
      { key: 'signed_at', label: '签订日期', type: 'date' },
      { key: 'paid', label: '已付金额', type: 'number' },
      { key: 'settled_amount', label: '结算金额', type: 'number' },
      { key: 'status', label: '状态', type: 'select', options: ['未开工', '施工中', '已完工', '已结算'] },
      { key: 'note', label: '备注', type: 'text' },
    ],
  },
  {
    key: 'material', title: '材料采购',
    columns: [
      { key: 'name', label: '材料名称', type: 'text' },
      { key: 'spec', label: '规格型号', type: 'text' },
      { key: 'unit', label: '单位', type: 'text' },
      { key: 'qty', label: '数量', type: 'number' },
      { key: 'price', label: '单价', type: 'number' },
      { key: 'amount', label: '金额', type: 'number' },
      { key: 'supplier', label: '供应商', type: 'text' },
      { key: 'date', label: '采购日期', type: 'date' },
      { key: 'status', label: '状态', type: 'select', options: ['待采购', '已下单', '已到货', '已入库'] },
      { key: 'note', label: '备注', type: 'text' },
    ],
  },
];

const MONEY_KEYS = new Set(['amount', 'target', 'actual', 'claimed', 'received', 'submit_amount', 'approved_amount', 'paid', 'settled_amount', 'qty', 'price']);

function cellText(col: ExecColumn, v: unknown): string {
  if (v == null || v === '') return '—';
  if (MONEY_KEYS.has(col.key)) return yf(v);
  return String(v);
}

/* ---------------- 文档区 ---------------- */
const DOC_CATEGORIES = ['招标文件', '图纸', '合同', '签证', '结算', '其他'];

interface DocItem {
  name: string;
  original?: string;
  category?: string;
  size?: number;
  uploaded_at?: string;
}

function fmtSize(n: unknown): string {
  const v = Number(n);
  if (!Number.isFinite(v) || v < 0) return '—';
  if (v < 1024) return `${v} B`;
  if (v < 1048576) return `${(v / 1024).toFixed(1)} KB`;
  return `${(v / 1048576).toFixed(1)} MB`;
}

function DocsSection({ projectId }: { projectId: string }) {
  const [docs, setDocs] = useState<DocItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [category, setCategory] = useState('其他');

  const load = useCallback(() => {
    setLoading(true);
    fetch(`${API_BASE}/api/project/docs/list?project_id=${encodeURIComponent(projectId)}`)
      .then((r) => r.json() as Promise<{ items?: DocItem[] }>)
      .then((j) => setDocs(j.items ?? []))
      .catch(() => setDocs([]))
      .finally(() => setLoading(false));
  }, [projectId]);

  useEffect(() => { load(); }, [load]);

  async function onFile(e: { target: { files?: FileList | null; value: string } }) {
    const f = e.target.files?.[0];
    e.target.value = '';
    if (!f) return;
    const data = new FormData();
    data.append('project_id', projectId);
    data.append('category', category);
    data.append('file', f);
    setUploading(true);
    try {
      const r = await fetch(`${API_BASE}/api/project/docs/upload`, { method: 'POST', body: data });
      const j = (await r.json()) as { status?: string; reason?: string };
      if (!r.ok || j.status !== 'PASS') throw new Error(j.reason || '上传失败');
      load();
    } catch (err) {
      window.alert(`上传失败：${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setUploading(false);
    }
  }

  async function del(name: string) {
    if (!window.confirm(`确定删除文档「${name}」？此操作不可恢复。`)) return;
    const data = new FormData();
    data.append('project_id', projectId);
    data.append('name', name);
    try {
      const r = await fetch(`${API_BASE}/api/project/docs/delete`, { method: 'POST', body: data });
      const j = (await r.json()) as { status?: string; reason?: string };
      if (!r.ok || j.status !== 'PASS') throw new Error(j.reason || '删除失败');
      load();
    } catch (err) {
      window.alert(`删除失败：${err instanceof Error ? err.message : String(err)}`);
    }
  }

  return (
    <section>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12 }}>
        <span className="nb-muted" style={{ fontSize: 13 }}>分类：</span>
        <select value={category} onChange={(e) => setCategory(e.target.value)}>
          {DOC_CATEGORIES.map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
        <label className="nb-btn" style={{ cursor: 'pointer' }}>
          {uploading ? '上传中…' : '+ 上传文档'}
          <input type="file" style={{ display: 'none' }} disabled={uploading} onChange={onFile} />
        </label>
        <span className="nb-muted" style={{ fontSize: 12 }}>单文件 10MB 上限 · 按项目归档，备份跟着项目目录走</span>
      </div>
      {loading ? (
        <div className="nb-muted">读取中…</div>
      ) : docs.length === 0 ? (
        <div className="empty-state"><p>暂无文档。招标文件、图纸、合同扫描件都可以传上来按项目归档。</p></div>
      ) : (
        <div className="note-table">
          <div className="note-table-head">
            <span className="note-th">文件名</span><span className="note-th">分类</span>
            <span className="note-th">大小</span><span className="note-th">上传时间</span>
            <span className="note-th">操作</span>
          </div>
          {docs.map((d) => (
            <div key={d.name} className="note-row">
              <div className="note-td" title={d.original || d.name}>{d.original || d.name}</div>
              <div className="note-td">{d.category || '其他'}</div>
              <div className="note-td">{fmtSize(d.size)}</div>
              <div className="note-td">{d.uploaded_at || '—'}</div>
              <div className="note-td">
                <a className="nb-btn nb-btn--ghost" style={{ padding: '2px 8px', fontSize: 12 }}
                  href={`${API_BASE}/api/project/docs/download?project_id=${encodeURIComponent(projectId)}&name=${encodeURIComponent(d.name)}`}>
                  下载
                </a>
                <button type="button" className="nb-btn nb-btn--ghost" style={{ padding: '2px 8px', fontSize: 12, marginLeft: 6 }} onClick={() => del(d.name)}>删除</button>
              </div>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

/* ---------------- 单表 CRUD 区 ---------------- */
function ExecSection({ table, projectId }: { table: ExecTableDef; projectId: string }) {
  const [rows, setRows] = useState<Array<Record<string, unknown>>>([]);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState<Record<string, string> | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    fetch(`${API_BASE}/api/project/exec/${table.key}/list?project_id=${encodeURIComponent(projectId)}`)
      .then((r) => r.json() as Promise<{ items?: Array<Record<string, unknown>> }>)
      .then((j) => setRows(j.items ?? []))
      .catch(() => setRows([]))
      .finally(() => setLoading(false));
  }, [table.key, projectId]);

  useEffect(() => { load(); }, [load]);

  const openNew = () => {
    const f: Record<string, string> = {};
    table.columns.forEach((c) => { f[c.key] = c.type === 'select' ? (c.options?.[0] ?? '') : ''; });
    setEditing(f);
  };
  const openEdit = (row: Record<string, unknown>) => {
    const f: Record<string, string> = { id: String(row.id ?? '') };
    table.columns.forEach((c) => {
      const v = row[c.key];
      f[c.key] = v == null ? '' : String(v);
    });
    setEditing(f);
  };

  async function save() {
    if (!editing) return;
    const body = { ...editing, project_id: projectId };
    try {
      const r = await fetch(`${API_BASE}/api/project/exec/${table.key}/save`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      const j = (await r.json()) as { status?: string; reason?: string };
      if (!r.ok || j.status !== 'PASS') throw new Error(j.reason || '保存失败');
      setEditing(null);
      load();
    } catch (err) {
      window.alert(`保存失败：${err instanceof Error ? err.message : String(err)}`);
    }
  }

  async function del(row: Record<string, unknown>) {
    if (!window.confirm('确定删除这条记录？此操作不可恢复。')) return;
    try {
      const r = await fetch(`${API_BASE}/api/project/exec/${table.key}/delete`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id: row.id }),
      });
      const j = (await r.json()) as { status?: string; reason?: string };
      if (!r.ok || j.status !== 'PASS') throw new Error(j.reason || '删除失败');
      load();
    } catch (err) {
      window.alert(`删除失败：${err instanceof Error ? err.message : String(err)}`);
    }
  }

  const set = (k: string) => (e: { target: { value: string } }) =>
    setEditing((prev) => (prev ? { ...prev, [k]: e.target.value } : prev));

  // note-table 的 grid 写死 6 列；执行表列数不一，用动态列数覆盖
  const gridCols = { gridTemplateColumns: `repeat(${table.columns.length + 1}, minmax(96px, 1fr))` };

  return (
    <section style={{ marginBottom: 28 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10 }}>
        <h3 style={{ margin: 0, fontSize: 15 }}>{table.title}（{rows.length}）</h3>
        <button type="button" className="nb-btn nb-btn--ghost" onClick={openNew}>+ 新增</button>
      </div>
      {loading ? (
        <div className="nb-muted">读取中…</div>
      ) : rows.length === 0 ? (
        <div className="empty-state"><p>暂无记录，点右上「新增」开始记账。</p></div>
      ) : (
        <div className="note-table">
          <div className="note-table-head" style={gridCols}>
            {table.columns.map((c) => <span key={c.key} className="note-th">{c.label}</span>)}
            <span className="note-th">操作</span>
          </div>
          {rows.map((row) => (
            <div key={String(row.id)} className="note-row" style={gridCols}>
              {table.columns.map((c) => (
                <div key={c.key} className="note-td" title={String(row[c.key] ?? '')}>
                  {cellText(c, row[c.key])}
                </div>
              ))}
              <div className="note-td">
                <button type="button" className="nb-btn nb-btn--ghost" style={{ padding: '2px 8px', fontSize: 12 }} onClick={() => openEdit(row)}>编辑</button>
                <button type="button" className="nb-btn nb-btn--ghost" style={{ padding: '2px 8px', fontSize: 12, marginLeft: 6 }} onClick={() => del(row)}>删除</button>
              </div>
            </div>
          ))}
        </div>
      )}
      {editing && (
        <div className="biz-mask" onClick={() => setEditing(null)}>
          <div className="biz-modal" onClick={(e) => e.stopPropagation()}>
            <div className="biz-mhead">
              <b>{editing.id ? '编辑' : '新增'}{table.title}</b>
              <button type="button" className="nb-btn nb-btn--ghost biz-x" aria-label="关闭" onClick={() => setEditing(null)}>✕</button>
            </div>
            <div className="biz-mform">
              {table.columns.map((c) => (
                <label key={c.key} className="biz-fld">
                  <span>{c.label}</span>
                  {c.type === 'select' ? (
                    <select value={editing[c.key] ?? ''} onChange={set(c.key)}>
                      {(c.options ?? []).map((o) => <option key={o} value={o}>{o}</option>)}
                    </select>
                  ) : (
                    <input type={c.type === 'number' ? 'number' : c.type === 'date' ? 'date' : 'text'}
                      value={editing[c.key] ?? ''} onChange={set(c.key)} />
                  )}
                </label>
              ))}
            </div>
            <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 12 }}>
              <button type="button" className="nb-btn nb-btn--ghost" onClick={() => setEditing(null)}>取消</button>
              <button type="button" className="nb-btn" onClick={save}>保存</button>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}

/* ---------------- 执行：子 tab（7 节太多，纵向拉太长） ---------------- */
function ExecTabs({ projectId }: { projectId: string }) {
  const [sub, setSub] = useState(EXEC_TABLES[0].key);
  return (
    <div>
      <div style={{ display: 'flex', gap: 4, marginBottom: 16, flexWrap: 'wrap' }}>
        {EXEC_TABLES.map((t) => (
          <button key={t.key} type="button"
            className="nb-btn nb-btn--ghost"
            style={{ fontWeight: sub === t.key ? 700 : 400, opacity: sub === t.key ? 1 : 0.65 }}
            onClick={() => setSub(t.key)}>
            {t.title}
          </button>
        ))}
      </div>
      {EXEC_TABLES.filter((t) => t.key === sub).map((t) => (
        <ExecSection key={t.key} table={t} projectId={projectId} />
      ))}
    </div>
  );
}
export default function BizDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [tab, setTab] = useState<TabKey>('overview');
  const [project, setProject] = useState<ProjectOverview | null>(null);
  const [summary, setSummary] = useState<ExecSummary | null>(null);
  const [groups, setGroups] = useState<QuoteGroup[]>([]);
  const [todos, setTodos] = useState<TodoLite[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [showEdit, setShowEdit] = useState(false);

  const pid = id ?? '';

  const load = useCallback(() => {
    if (!pid) return;
    setLoading(true);
    setError('');
    Promise.all([
      fetch(`${API_BASE}/api/project/overview/list`).then((r) => r.json()),
      fetch(`${API_BASE}/api/project/exec/summary?project_id=${encodeURIComponent(pid)}`).then((r) => r.json()),
      fetch(`${API_BASE}/api/group/list?project_id=${encodeURIComponent(pid)}`).then((r) => r.json()),
      fetch('/api/todos').then((r) => (r.ok ? r.json() : [])).catch(() => []),
    ])
      .then(([ov, sum, grp, td]: Array<{ projects?: ProjectOverview[]; summary?: ExecSummary; groups?: QuoteGroup[] } & unknown>) => {
        const list = (ov as { projects?: ProjectOverview[] })?.projects ?? [];
        const found = list.find((p) => p.id === pid) ?? null;
        if (!found) throw new Error('项目不存在或已删除');
        setProject(found);
        setSummary((sum as { summary?: ExecSummary })?.summary ?? null);
        setGroups((grp as { groups?: QuoteGroup[] })?.groups ?? []);
        setTodos(Array.isArray(td) ? (td as TodoLite[]) : []);
      })
      .catch((e: unknown) => {
        setError(e instanceof Error ? e.message : String(e));
        setProject(null);
      })
      .finally(() => setLoading(false));
  }, [pid]);

  useEffect(() => { load(); }, [load]);

  // Esc 关闭编辑弹窗
  useEffect(() => {
    if (!showEdit) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setShowEdit(false); };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [showEdit]);

  const myTodos = todos.filter((t) => t.projectId === pid);
  const quoteUrl = API_BASE + '/';

  return (
    <div className="ui-page">
      <div className="ui-page-head">
        <div>
          <div className="ui-page-kicker">
            <button type="button" className="nb-btn nb-btn--ghost" style={{ padding: '2px 10px', fontSize: 12 }}
              onClick={() => navigate('/biz')}>← 项目经营</button>
          </div>
          <h1>{project ? (project.short_name || project.name || '项目主页') : '项目主页'}</h1>
        </div>
        {project && (
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <span className="nb-badge">{project.stage || '—'}</span>
            <button type="button" className="nb-btn nb-btn--ghost" onClick={() => setShowEdit(true)}>编辑项目</button>
          </div>
        )}
      </div>

      {error && <div className="ui-alert ui-alert--error">{error}</div>}
      {loading && <div className="nb-muted">读取中…</div>}

      {project && !loading && (
        <>
          {/* KPI 一览 */}
          <div className="biz-metrics" style={{ marginBottom: 16 }}>
            <div className="biz-metric"><span className="l">总限价</span><span className="v">{yf(project.limit_total)}</span></div>
            <div className="biz-metric"><span className="l">投标报价</span><span className="v">{yf(project.bid_amount)}</span></div>
            <div className="biz-metric"><span className="l">总毛利</span><span className="v">{yf(project.gross_profit)}</span></div>
            <div className="biz-metric"><span className="l">总毛利率</span><span className="v">{pct(project.gross_margin)}</span></div>
            {summary && (
              <>
                <div className="biz-metric"><span className="l">合同总额</span><span className="v">{yf(summary.contract_total)}</span></div>
                <div className="biz-metric"><span className="l">已到账</span><span className="v">{yf(summary.received_total)}</span></div>
                <div className="biz-metric"><span className="l">应收未收</span><span className="v">{yf(summary.receivable)}</span></div>
                <div className="biz-metric"><span className="l">成本偏差</span><span className="v">{yf(summary.cost_variance)}</span></div>
              </>
            )}
          </div>

          {/* Tabs */}
          <div style={{ display: 'flex', gap: 4, marginBottom: 16, borderBottom: '1px solid var(--nb-line, #e5e5e5)' }}>
            {TABS.map(([k, label]) => (
              <button key={k} type="button"
                className="nb-btn nb-btn--ghost"
                style={{
                  borderRadius: '8px 8px 0 0',
                  fontWeight: tab === k ? 700 : 400,
                  opacity: tab === k ? 1 : 0.65,
                }}
                onClick={() => setTab(k)}>
                {label}{k === 'todos' && myTodos.length > 0 ? `（${myTodos.length}）` : ''}
              </button>
            ))}
          </div>

          {tab === 'overview' && (
            <div>
              <div className="note-table">
                <div className="note-table-head">
                  <span className="note-th">字段</span><span className="note-th">内容</span>
                </div>
                {[
                  ['项目名称', project.name || '—'],
                  ['简称', project.short_name || '—'],
                  ['阶段', project.stage || '—'],
                  ['总限价', yf(project.limit_total)],
                  ['开标日期', project.bid_open_date || '—'],
                  ['投标报价金额', yf(project.bid_amount)],
                  ['投标成本测算', yf(project.bid_cost)],
                  ['实际成本', yf(project.actual_cost)],
                  ['实际营收', yf(project.actual_revenue)],
                  ['结算金额', yf(project.settle_amount)],
                  ['竣工日期', project.completed_at || '—'],
                  ['实际收益率', pct(project.actual_yield)],
                ].map(([k, v]) => (
                  <div key={k} className="note-row">
                    <div className="note-td nb-muted">{k}</div>
                    <div className="note-td">{v}</div>
                  </div>
                ))}
              </div>
              {summary && (
                <div style={{ marginTop: 16 }}>
                  <h3 style={{ fontSize: 15 }}>资金与成本</h3>
                  <div className="biz-metrics">
                    <div className="biz-metric"><span className="l">已批签证</span><span className="v">{yf(summary.visa_approved)}</span></div>
                    <div className="biz-metric"><span className="l">待批签证</span><span className="v">{yf(summary.visa_pending)}</span></div>
                    <div className="biz-metric"><span className="l">目标成本</span><span className="v">{yf(summary.cost_target)}</span></div>
                    <div className="biz-metric"><span className="l">实际成本</span><span className="v">{yf(summary.cost_actual)}</span></div>
                    <div className="biz-metric"><span className="l">资金压力</span><span className="v">{summary.fund_pressure != null ? pct(summary.fund_pressure) : '—'}</span></div>
                    <div className="biz-metric"><span className="l">送审金额</span><span className="v">{yf(summary.settle_submit)}</span></div>
                    <div className="biz-metric"><span className="l">审定金额</span><span className="v">{yf(summary.settle_approved)}</span></div>
                    <div className="biz-metric"><span className="l">审减额</span><span className="v">{yf(summary.settle_reduction)}</span></div>
                    <div className="biz-metric"><span className="l">分包合同</span><span className="v">{yf(summary.subcontract_total)}</span></div>
                    <div className="biz-metric"><span className="l">分包已付</span><span className="v">{yf(summary.subcontract_paid)}</span></div>
                    <div className="biz-metric"><span className="l">分包应付</span><span className="v">{yf(summary.subcontract_payable)}</span></div>
                    <div className="biz-metric"><span className="l">材料采购</span><span className="v">{yf(summary.material_total)}</span></div>
                  </div>
                </div>
              )}
            </div>
          )}

          {tab === 'quote' && (
            <div>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
                <span className="nb-muted" style={{ fontSize: 13 }}>该项目的报价方案组（A 均衡 / B 均匀 / C 不平衡）</span>
                <a className="nb-btn" href={quoteUrl} target="_blank" rel="noreferrer">去报价页 →</a>
              </div>
              {groups.length === 0 ? (
                <div className="empty-state"><p>暂无报价方案组，去报价页关联本项目做一次测算。</p></div>
              ) : groups.map((g) => (
                <section key={g.group_id} style={{ marginBottom: 20 }}>
                  <h3 style={{ fontSize: 15, margin: '0 0 8px' }}>
                    {g.group_name || g.group_id}
                    {g.finalized ? <span className="nb-badge" style={{ marginLeft: 8 }}>已定稿</span> : null}
                  </h3>
                  <div className="note-table">
                    <div className="note-table-head">
                      <span className="note-th">槽位</span><span className="note-th">策略</span>
                      <span className="note-th">目标总价</span><span className="note-th">竞争性预算</span>
                      <span className="note-th">状态</span><span className="note-th">保存时间</span>
                    </div>
                    {['A', 'B', 'C'].map((letter) => {
                      const s = g.strategy_slots?.[letter];
                      return (
                        <div key={letter} className="note-row">
                          <div className="note-td"><b>{letter}</b></div>
                          <div className="note-td">{SLOT_LABEL[letter] || letter}</div>
                          <div className="note-td">{s?.summary ? yf(s.summary.target_total) : '—'}</div>
                          <div className="note-td">{s?.summary ? yf(s.summary.competitive_budget) : '—'}</div>
                          <div className="note-td">{s?.plan_id ? (s.status || '已算') : '空'}</div>
                          <div className="note-td">{s?.summary?.saved_at || '—'}</div>
                        </div>
                      );
                    })}
                  </div>
                </section>
              ))}
            </div>
          )}

          {tab === 'exec' && <ExecTabs projectId={pid} />}

          {tab === 'docs' && <DocsSection projectId={pid} />}

          {tab === 'todos' && (
            <div>
              {myTodos.length === 0 ? (
                <div className="empty-state"><p>该项目暂无关联待办。</p></div>
              ) : (
                <div className="note-table">
                  <div className="note-table-head">
                    <span className="note-th">待办</span><span className="note-th">状态</span>
                  </div>
                  {myTodos.map((t) => (
                    <div key={t.id} className="note-row">
                      <div className="note-td">{t.title || String(t.id)}</div>
                      <div className="note-td">{t.status || '进行中'}</div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </>
      )}

      {showEdit && project && (
        <BizEditModal project={project} todos={todos} onClose={() => setShowEdit(false)} onSaved={load} />
      )}
    </div>
  );
}

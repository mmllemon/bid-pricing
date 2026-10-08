import { useCallback, useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import PageHead from '../components/PageHead';
import { api } from '../api/client';

/* 关联图谱：单位 ↔ 项目关系网（2026-10-08 liam 提出）
 * 左列单位节点，右列项目节点，连线粗细 ∝ 合同金额。
 * 点节点 → 右侧详情：项目清单 × 合同/已付/应付。
 */

interface GraphUnit {
  name: string;
  role: 'client' | 'subcontractor' | 'supplier';
  project_count: number;
  total_amount: number;
}

interface UnitProject {
  project_id: string;
  project_name: string;
  contracts: { type: string; amount: number; paid?: number; payable?: number; status?: string; scope?: string; name?: string }[];
  total_amount: number;
  total_paid?: number;
  total_payable?: number;
}

interface UnitDetail {
  unit: { name: string; role: string };
  projects: UnitProject[];
  project_count: number;
  grand_total: number;
  grand_payable: number;
}

const ROLE_LABEL: Record<string, string> = {
  client: '建设单位',
  subcontractor: '劳务/分包',
  supplier: '供应商',
};

const ROLE_COLOR: Record<string, string> = {
  client: '#3b82f6',
  subcontractor: '#f97316',
  supplier: '#22c55e',
};

function fmt(n: number | undefined): string {
  if (n === undefined || n === null) return '—';
  return n.toLocaleString('zh-CN', { maximumFractionDigits: 0 }) + ' 元';
}

export default function GraphPage() {
  const [searchParams] = useSearchParams();
  const [units, setUnits] = useState<GraphUnit[]>([]);
  const [roleFilter, setRoleFilter] = useState<string>('all');
  const [keyword, setKeyword] = useState('');
  const [selected, setSelected] = useState<{ name: string; role: string } | null>(null);
  const [detail, setDetail] = useState<UnitDetail | null>(null);
  const [loading, setLoading] = useState(false);

  // 加载单位列表
  useEffect(() => {
    api.request<{ status: string; units: GraphUnit[] }>('/graph/units')
      .then((r) => setUnits(r.units || []))
      .catch(() => setUnits([]));
  }, []);

  // URL 参数预选（如从 Portal 穿透过来）
  useEffect(() => {
    const name = searchParams.get('unit');
    const role = searchParams.get('role') || '';
    if (name) setSelected({ name, role });
  }, [searchParams]);

  // 点单位 → 拉详情
  useEffect(() => {
    if (!selected) { setDetail(null); return; }
    setLoading(true);
    api.request<UnitDetail & { status: string }>(
      `/graph/unit?name=${encodeURIComponent(selected.name)}&role=${encodeURIComponent(selected.role)}`
    )
      .then((r) => setDetail(r))
      .catch(() => setDetail(null))
      .finally(() => setLoading(false));
  }, [selected]);

  const filtered = useMemo(() => {
    return units.filter((u) => {
      if (roleFilter !== 'all' && u.role !== roleFilter) return false;
      if (keyword && !u.name.includes(keyword)) return false;
      return true;
    });
  }, [units, roleFilter, keyword]);

  // SVG 布局：左列单位，右列项目（二分图）
  const selectedProjects = detail?.projects || [];
  const svgH = Math.max(400, Math.max(filtered.length, selectedProjects.length) * 56 + 60);

  const unitY = useCallback(
    (i: number) => 40 + i * 56,
    []
  );
  const projY = useCallback(
    (i: number) => 40 + i * 56,
    []
  );

  // 连线粗细 ∝ 金额
  const maxAmt = useMemo(
    () => Math.max(1, ...selectedProjects.map((p) => p.total_amount)),
    [selectedProjects]
  );

  return (
    <div className="graph-page">
      <PageHead
        zh="关联图谱"
        en="Unit × Project Graph"
        sub="点一个单位，看它参与的所有项目、合同金额、已付应付。不用一个项目一个项目翻。"
      />

      <div className="graph-toolbar nb-toolbar">
        <input
          className="nb-input"
          placeholder="搜索单位名称…"
          value={keyword}
          onChange={(e) => setKeyword(e.target.value)}
          style={{ width: 220 }}
        />
        <select
          className="nb-input"
          value={roleFilter}
          onChange={(e) => setRoleFilter(e.target.value)}
        >
          <option value="all">全部角色</option>
          <option value="client">建设单位</option>
          <option value="subcontractor">劳务/分包</option>
          <option value="supplier">供应商</option>
        </select>
        <span className="nb-muted">{filtered.length} 个单位</span>
      </div>

      <div className="graph-layout">
        {/* 左：关系图 */}
        <div className="graph-canvas nb-card">
          {filtered.length === 0 ? (
            <div className="nb-empty">暂无单位数据。先在项目执行表里录入分包/材料/合同，单位会自动出现。</div>
          ) : (
            <svg width="100%" height={svgH} viewBox={`0 0 640 ${svgH}`}>
              {/* 单位节点（左列） */}
              {filtered.map((u, i) => {
                const y = unitY(i);
                const isSel = selected?.name === u.name && selected?.role === u.role;
                return (
                  <g
                    key={`${u.role}-${u.name}`}
                    onClick={() => setSelected({ name: u.name, role: u.role })}
                    style={{ cursor: 'pointer' }}
                  >
                    <rect
                      x={16} y={y - 18} width={200} height={36} rx={4}
                      fill={isSel ? ROLE_COLOR[u.role] : '#fff'}
                      stroke={ROLE_COLOR[u.role]}
                      strokeWidth={isSel ? 3 : 1.5}
                    />
                    <text
                      x={28} y={y + 5}
                      fontSize={13}
                      fill={isSel ? '#fff' : '#111'}
                      fontWeight={isSel ? 700 : 400}
                    >
                      {u.name.length > 12 ? u.name.slice(0, 12) + '…' : u.name}
                    </text>
                    {/* 连线到已选单位的项目 */}
                    {isSel && selectedProjects.map((p, j) => {
                      const w = Math.max(1, (p.total_amount / maxAmt) * 6);
                      return (
                        <line
                          key={p.project_id}
                          x1={216} y1={y} x2={424} y2={projY(j)}
                          stroke={ROLE_COLOR[u.role]}
                          strokeWidth={w}
                          opacity={0.45}
                        />
                      );
                    })}
                  </g>
                );
              })}
              {/* 项目节点（右列，仅显示选中单位的项目） */}
              {selected && selectedProjects.map((p, j) => {
                const y = projY(j);
                return (
                  <g key={p.project_id}>
                    <rect
                      x={424} y={y - 18} width={200} height={36} rx={4}
                      fill="#111" stroke="#111" strokeWidth={1.5}
                    />
                    <text x={436} y={y + 5} fontSize={13} fill="#fff">
                      {p.project_name.length > 12 ? p.project_name.slice(0, 12) + '…' : p.project_name}
                    </text>
                  </g>
                );
              })}
              {!selected && (
                <text x={320} y={svgH / 2} textAnchor="middle" fill="#999" fontSize={14}>
                  ← 点左侧单位查看关联项目
                </text>
              )}
            </svg>
          )}
        </div>

        {/* 右：详情面板 */}
        <div className="graph-detail nb-card">
          {loading && <div className="nb-muted">加载中…</div>}
          {!loading && !detail && (
            <div className="nb-empty">点左侧单位节点，<br />看它的项目、合同、应付。</div>
          )}
          {!loading && detail && (
            <>
              <div className="graph-detail-head">
                <span
                  className="nb-badge"
                  style={{ background: ROLE_COLOR[detail.unit.role] }}
                >
                  {ROLE_LABEL[detail.unit.role] || detail.unit.role}
                </span>
                <h3>{detail.unit.name}</h3>
                <div className="nb-muted">
                  {detail.project_count} 个项目 · 累计 {fmt(detail.grand_total)}
                  · 应付 {fmt(detail.grand_payable)}
                </div>
              </div>
              <div className="graph-project-list">
                {detail.projects.map((p) => (
                  <div key={p.project_id} className="graph-project-card">
                    <div className="graph-project-name">
                      <a href={`#/biz/${p.project_id}`}>{p.project_name}</a>
                    </div>
                    <div className="graph-project-amounts">
                      <span>合同 <b>{fmt(p.total_amount)}</b></span>
                      {p.total_paid !== undefined && <span>已付 <b>{fmt(p.total_paid)}</b></span>}
                      {p.total_payable !== undefined && (
                        <span className={p.total_payable > 0 ? 'graph-payable' : ''}>
                          应付 <b>{fmt(p.total_payable)}</b>
                        </span>
                      )}
                    </div>
                    <div className="graph-contracts">
                      {p.contracts.map((c, k) => (
                        <div key={k} className="nb-muted" style={{ fontSize: 12 }}>
                          {c.type}{c.scope ? ` · ${c.scope}` : ''}{c.name ? ` · ${c.name}` : ''}
                          ：{fmt(c.amount)}
                          {c.payable !== undefined && c.payable > 0 && `（欠 ${fmt(c.payable)}）`}
                        </div>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

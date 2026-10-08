import { useEffect, useState } from 'react';
import { API_BASE, pct, toNum, yf } from './bizShared';
import type { ProjectOverview } from './bizShared';
import { IconClose } from '../components/icons';

/**
 * 项目快览面板（借鉴 neural-creator-dashboard 的右侧分析栏）。
 *
 * 项目库看板点击卡片时先滑出快览（关键指标 + 收款进度 + 关联计数），
 * 再点「进入项目主页」才跳转整页。Esc / 点击遮罩关闭。
 */
export default function BizQuickView({
  project,
  todoCount,
  onClose,
  onEnter,
}: {
  project: ProjectOverview | null;
  todoCount: number;
  onClose: () => void;
  onEnter: (p: ProjectOverview) => void;
}) {
  const [groupCount, setGroupCount] = useState<number | null>(null);
  const [docCount, setDocCount] = useState<number | null>(null);

  useEffect(() => {
    if (!project) return;
    setGroupCount(null);
    setDocCount(null);
    const pid = project.id;
    // 报价方案组数
    fetch(`${API_BASE}/api/group/list?project_id=${encodeURIComponent(pid)}`)
      .then((r) => (r.ok ? r.json() : {}))
      .then((j: unknown) => {
        const g = (j as { groups?: unknown[] })?.groups;
        setGroupCount(Array.isArray(g) ? g.length : 0);
      })
      .catch(() => setGroupCount(0));
    // 文档数
    fetch(`${API_BASE}/api/project/docs/list?project_id=${encodeURIComponent(pid)}`)
      .then((r) => (r.ok ? r.json() : {}))
      .then((j: unknown) => {
        const items = (j as { items?: unknown[] })?.items;
        setDocCount(Array.isArray(items) ? items.length : 0);
      })
      .catch(() => setDocCount(0));
  }, [project]);

  useEffect(() => {
    if (!project) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [project, onClose]);

  if (!project) return null;

  const gp = toNum(project.gross_profit);
  const gm = toNum(project.gross_margin);
  const clsV = gm != null ? (gm < 0 ? ' neg' : ' pos') : '';
  const recv = toNum(project.actual_revenue);
  const contract = toNum(project.bid_amount);
  const recvRate = recv != null && contract ? Math.max(0, Math.min(1, recv / contract)) : null;
  const disp = (project.short_name || '').trim() || project.name || '';

  const links: Array<{ label: string; en: string; count: number | null; tab: string }> = [
    { label: '报价方案', en: 'Quotes', count: groupCount, tab: 'quote' },
    { label: '项目文档', en: 'Docs', count: docCount, tab: 'docs' },
    { label: '关联待办', en: 'Todos', count: todoCount, tab: 'todos' },
  ];

  return (
    <div className="qv-mask" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <aside className="qv-panel rise-in" role="dialog" aria-label={`${disp} 快览`}>
        <div className="qv-head">
          <div>
            <p className="page-eyebrow">PROJECT <span>项目快览</span></p>
            <h2 className="qv-title" title={project.name || ''}>{disp}</h2>
          </div>
          <button type="button" className="nb-btn nb-btn--ghost qv-x" aria-label="关闭快览" onClick={onClose}>
            <IconClose size={14} />
          </button>
        </div>

        <div className="qv-badges">
          <span className="nb-badge">{project.stage || '—'}</span>
          {project.bid_open_date && <span className="nb-badge">开标 {project.bid_open_date}</span>}
        </div>

        {recvRate != null && (
          <div className="biz-recv" title={`已收 ${yf(recv)} / 合同额 ${yf(contract)}`}>
            <i style={{ width: `${Math.round(recvRate * 100)}%` }} />
            <span>收款 {Math.round(recvRate * 100)}%</span>
          </div>
        )}

        <div className="qv-metrics">
          <div><span className="l">总限价</span><span className="v">{yf(project.limit_total)}</span></div>
          <div><span className="l">投标报价金额</span><span className="v">{yf(project.bid_amount)}</span></div>
          <div><span className="l">投标成本测算</span><span className="v">{yf(project.bid_cost)}</span></div>
          <div><span className="l">总毛利</span><span className={`v${clsV}`}>{yf(gp)}</span></div>
          <div><span className="l">总毛利率</span><span className={`v${clsV}`}>{pct(gm)}</span></div>
        </div>

        <div className="qv-links">
          {links.map((l) => (
            <button
              key={l.tab}
              type="button"
              className="qv-link"
              onClick={() => onEnter(project)}
              title={`进入项目主页 · ${l.label}`}
            >
              <span className="qv-link-label">{l.label}<em>{l.en}</em></span>
              <span className="qv-link-count">{l.count == null ? '…' : l.count}</span>
            </button>
          ))}
        </div>

        <button type="button" className="nb-btn nb-btn--primary qv-enter" onClick={() => onEnter(project)}>
          进入项目主页 →
        </button>
        <p className="qv-hint">Esc 关闭 · 点击遮罩关闭</p>
      </aside>
    </div>
  );
}

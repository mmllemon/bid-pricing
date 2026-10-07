import { useMemo, useState } from 'react';
import { filterDashItems, sortDashItems, pageDashItems, ratioTagClass, type DashFilter, type QuoteItem } from './quoteCalc';

/**
 * 报价页明细表（P3 块1：由 frontend/index.html 的 .table-section + app.js renderDashTable 迁入 React）
 * 筛选/排序/分页走 quoteCalc 纯函数（有判据）；列结构与原生一致（10 列，可横向滚动）。
 */
const fmt = (v: unknown, d = 2) => {
  const n = Number(v);
  return Number.isFinite(n) ? n.toLocaleString('zh-CN', { minimumFractionDigits: d, maximumFractionDigits: d }) : '—';
};

export function QuoteTable({ items, totalCount }: { items: QuoteItem[]; totalCount: number }) {
  const [filter, setFilter] = useState<DashFilter>('all');
  // 毛利排序：由 KPI 毛利卡穿透触发（块 3 接），当前保留状态位
  const [sortMargin] = useState(false);
  const [page, setPage] = useState(0);

  const { rows, pageCount, page: curPage } = useMemo(() => {
    const filtered = sortDashItems(filterDashItems(items, filter), sortMargin);
    return pageDashItems(filtered, page);
  }, [items, filter, sortMargin, page]);

  return (
    <div className="table-section">
      <div className="table-toolbar">
        <div className="filter-chips" role="tablist" aria-label="筛选">
          {([['all', '全部子目'], ['risk', '临界/关注项'], ['early', '早结倾斜项']] as [DashFilter, string][]).map(([k, label]) => (
            <button key={k} type="button" className={`filter-chip${filter === k ? ' active' : ''}`} role="tab"
              aria-selected={filter === k} onClick={() => { setFilter(k); setPage(0); }}>{label}</button>
          ))}
          {filter !== 'all' && (
            <button className="drill-clear" id="clearDrillChip" type="button" aria-label="清除筛选" onClick={() => setFilter('all')}>✕ 清除筛选</button>
          )}
        </div>
        <div className="table-toolbar-side">
          <div className="result-actions" id="resultActions" />
          <div style={{ fontSize: 12, color: 'var(--text-secondary)', display: 'flex', alignItems: 'center', gap: 12 }}>
            <span className="tabular" id="tableCount">合计清单项: {totalCount} 项（显示 {rows.length}）</span>
            <span style={{ color: 'var(--text-tertiary)' }}>共 10 列，可左右滚动查看</span>
            <span id="tablePager" style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
              <button type="button" data-pg="prev" disabled={pageCount <= 1 || curPage <= 0}
                onClick={() => setPage((p) => Math.max(0, p - 1))}>‹ 上页</button>
              <span style={{ fontSize: 12, color: 'var(--text-tertiary)' }}>第 <b>{curPage + 1}</b> / {pageCount} 页</span>
              <button type="button" data-pg="next" disabled={pageCount <= 1 || curPage >= pageCount - 1}
                onClick={() => setPage((p) => Math.min(pageCount - 1, p + 1))}>下页 ›</button>
            </span>
          </div>
        </div>
      </div>

      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th>项目编码</th>
              <th>子目名称与规格</th>
              <th>单位</th>
              <th className="num">清单量</th>
              <th className="num">最高限价</th>
              <th className="num">有效成本</th>
              <th className="num">建议综合单价</th>
              <th className="num">报价比率</th>
              <th className="num">合价 (元)</th>
              <th>量化策略判定</th>
            </tr>
          </thead>
          <tbody id="tableBody">
            {rows.length === 0 ? (
              <tr>
                <td colSpan={10} style={{ textAlign: 'center', color: 'var(--text-tertiary)', padding: 24 }}>
                  {items.length === 0 ? '尚无测算结果，请先导入清单并计算。' : '当前筛选无子目'}
                </td>
              </tr>
            ) : rows.map((row, i) => {
              const ratio = Number(row['报价比率']);
              const qty = Number(row['工程量'] ?? 0);
              const quote = Number(row['最优报价单价'] ?? 0);
              const tag = ratioTagClass(row);
              const ratioPercent = Number.isFinite(ratio) ? `${(ratio * 100).toFixed(1)}%` : '—';
              const tagLabel = tag === 'risk' ? (row['报价状态'] === 'MANUAL_REVIEW' ? '人工报价' : '需复核')
                : tag === 'early' ? `早结倾斜 ${ratioPercent}` : `平准 ${ratioPercent}`;
              return (
                <tr key={i}>
                  <td>{String(row['项目编码'] ?? '')}</td>
                  <td>{String(row['子目名称与规格'] ?? '')}</td>
                  <td>{String(row['单位'] ?? '')}</td>
                  <td className="num">{fmt(qty)}</td>
                  <td className="num">{fmt(row['最高限价'])}</td>
                  <td className="num">{fmt(row['有效成本'])}</td>
                  <td className="num">{fmt(quote)}</td>
                  <td className="num">{ratioPercent}</td>
                  <td className="num">{fmt(qty * quote)}</td>
                  <td><span className={`tag ${tag}`}>{tagLabel}</span></td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

import type { ReactNode } from 'react';
import type { CompareResult } from './quoteApi';

/**
 * 多方案对比弹层（P3 块4c：由 app.js compareHtml/renderCompare + #cmpModal 迁入 React）
 * 指标矩阵 + 单价差异明细，限同一项目的方案变体。
 */
const fmt = (v: unknown, d = 2) => {
  const n = Number(v);
  return Number.isFinite(n) ? n.toLocaleString('zh-CN', { minimumFractionDigits: d, maximumFractionDigits: d }) : '—';
};

export function QuoteCompareModal({ open, res, onClose }: { open: boolean; res: CompareResult | null; onClose: () => void }) {
  if (!res) return (
    <div className={`cmp-modal${open ? ' open' : ''}`} id="cmpModal" role="dialog" aria-modal="true" aria-label="方案对比结果" aria-hidden={!open}>
      <div className="cmp-mask" id="cmpModalMask" onClick={onClose} />
      <div className="cmp-panel" role="document">…</div>
    </div>
  );

  const ids = res.plan_ids || [];
  const summary = res.summary || [];
  const get = (id: string, key: string): unknown => (summary.find((s) => s.plan_id === id) as Record<string, unknown> | undefined)?.[key];
  const headers = ids.map((id) => (get(id, 'name') as string) || id);
  const baseMark = res.base_id ? `（基准：${res.base_id}）` : '';

  const lossCell = (id: string) => {
    const p = (get(id, 'loss_items') as { 项目编码: string; 单项毛利: number }[]) || [];
    return p.length ? p.map((x) => `${x['项目编码']}(${fmt(x['单项毛利'])})`).join('\n') : '—';
  };
  const riskCell = (id: string) => {
    const p = (get(id, 'risk_items') as { 项目编码: string; 报价比率: number }[]) || [];
    return p.length ? p.map((x) => `${x['项目编码']}(${fmt(Number(x['报价比率']) * 100, 2)}%)`).join('\n') : '—';
  };
  const paramsCell = (id: string) => {
    const pa = get(id, 'params') as { target_total?: number; ratio_min?: number; ratio_max?: number } | undefined;
    if (!pa) return '—';
    const parts: string[] = [];
    if (pa.target_total != null) parts.push(`目标 ${Number(pa.target_total).toLocaleString('zh-CN', { maximumFractionDigits: 0 })}`);
    if (pa.ratio_min != null) parts.push(`区间 ${Number(pa.ratio_min) * 100}%~${Number(pa.ratio_max) * 100}%`);
    return parts.join(' ｜ ') || '—';
  };

  const diffs = res.price_diffs || {};
  const diffEntries = Object.entries(diffs).filter(([, e]) => ids.some((id) => e.deltas[id] != null));

  const rows: { label: string; cell: (id: string) => ReactNode }[] = [
    { label: '参数（目标报价/比率区间）', cell: (id) => paramsCell(id) },
    { label: '是否已计算', cell: (id) => (get(id, 'computed') ? '✓' : '未计算') },
    { label: '优化项数', cell: (id) => String(get(id, 'item_count') ?? '—') },
    {
      label: '总利润（结算调整后·不含增值税）',
      cell: (id) => (get(id, 'computed') ? fmt(get(id, 'objective')) : '未计算'),
    },
    { label: '亏损项（单项毛利<0）', cell: (id) => { const p = (get(id, 'loss_items') as unknown[]) || []; return p.length ? `${lossCell(id)}（${p.length}项）` : '—'; } },
    { label: '风险项（报价比率<50%）', cell: (id) => { const p = (get(id, 'risk_items') as unknown[]) || []; return p.length ? `${riskCell(id)}（${p.length}项）` : '—'; } },
    { label: '单价 vs 基准 |Δ| 平均', cell: (id) => (get(id, 'avg_abs_price_delta') == null ? '—' : fmt(get(id, 'avg_abs_price_delta'))) },
  ];

  return (
    <div className={`cmp-modal${open ? ' open' : ''}`} id="cmpModal" role="dialog" aria-modal="true" aria-label="方案对比结果" aria-hidden={!open}>
      <div className="cmp-mask" id="cmpModalMask" data-close onClick={onClose} />
      <div className="cmp-panel" role="document">
        <div className="cmp-head">
          <h3>方案对比结果</h3>
          <button type="button" className="ph-close" id="cmpModalCloseBtn" aria-label="关闭对比结果" onClick={onClose}>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" width={14} height={14} aria-hidden="true"><path d="M6 6l12 12M18 6L6 18" /></svg>
          </button>
        </div>
        <div className="cmp-body" id="cmpModalBody" aria-live="polite">
          <div className="result-head">
            <div>
              <h3>同一项目方案对比：{res.project || ''}{baseMark}</h3>
              <p>共 {ids.length} 个同项目方案并列：总利润、亏损项、风险项、单价差异；是否构成废标以招标文件为准。</p>
            </div>
          </div>
          <div className="table-wrap">
            <table>
              <thead><tr><th>指标</th>{headers.map((h) => <th key={h}>{h}</th>)}</tr></thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.label}>
                    <td><b>{r.label}</b></td>
                    {ids.map((id) => <td key={id}>{r.cell(id)}</td>)}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {diffEntries.length > 0 && (
            <>
              <div className="result-head" style={{ marginTop: 16 }}>
                <div><h3>单价差异明细（相对基准）</h3><p>仅列出基准中存在报价的项目；空表示该方案未含此项目。</p></div>
              </div>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr><th>项目编码</th><th>项目名称</th><th className="num">基准单价</th>
                      {ids.map((id, i) => <th key={id}>{headers[i]} 差异</th>)}</tr>
                  </thead>
                  <tbody>
                    {diffEntries.map(([code, e]) => (
                      <tr key={code}>
                        <td>{code}</td>
                        <td>{e.item_name || '—'}</td>
                        <td className="num">{fmt(e.base_price, 4)}</td>
                        {ids.map((id) => {
                          const d = e.deltas[id];
                          const cls = d !== null && d < -1e-9 ? 'loss-cell' : d !== null && d > 1e-9 ? 'gain-cell' : '';
                          return <td className={`num ${cls}`} key={id}>{d === null ? '—' : fmt(d, 4)}</td>;
                        })}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
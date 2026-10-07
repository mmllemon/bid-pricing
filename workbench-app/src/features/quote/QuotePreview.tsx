import type { ReactNode, CSSProperties } from 'react';
import type { QuotePreviewResult } from './quoteApi';

/**
 * 报价页面板卡：导入资料预览（P3 块2：由 app.js renderPreview 迁入 React）
 * 结构逐字对齐原生（行数 / 字段 / 匹配覆盖 / 异常 / 文件哈希）。
 */
const box: CSSProperties = {
  padding: 10, background: 'var(--surface-nested)', border: '1px solid var(--border)', borderRadius: 8,
};

export function QuotePreview({ res }: { res: QuotePreviewResult }) {
  const uw = (ws: Record<string, number>): string => Object.entries(ws).map(([k, v]) => `${k}(${v}行)`).join('、') || '—';
  const chip = (k: string, label: string): ReactNode => (
    <span style={{ color: res.fields[k] ? 'var(--success)' : 'var(--warn)', fontWeight: 600 }}>
      {label}{res.fields[k] ? '✓' : '−'}
    </span>
  );
  const m = res.match;

  return (
    <div className="card preview-stage" id="previewStage">
      <div className="result-head">
        <div>
          <h3>导入资料预览</h3>
          <p>项目：{res.project_id} ｜ 优化前核对：行数 / 字段 / 匹配覆盖 / 异常 / 文件哈希</p>
        </div>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(280px,1fr))', gap: 10 }}>
        <div style={box}><b>限价清单</b><br />{res.cap.rows} 行 ｜ {uw(res.cap.unit_works)}<br />
          <small style={{ color: 'var(--text-tertiary)' }}>哈希 {res.cap.hash_sha256 || '—'}</small></div>
        <div style={box}><b>成本清单</b><br />{res.cost.rows} 行 ｜ {uw(res.cost.unit_works)}<br />
          <small style={{ color: 'var(--text-tertiary)' }}>哈希 {res.cost.hash_sha256 || '—'}</small></div>
        <div style={box}><b>匹配覆盖</b><br />
          master {m.master_keys} 键：匹配 {m.matched}、仅限价 {m.only_cap}、仅成本 {m.only_cost}
          {m.blocked && <><br /><strong style={{ color: 'var(--danger)' }}>重复 key 已阻断，禁止自动合并</strong></>}</div>
        <div style={box}><b>可优化 / 人工</b><br />
          可优化 {res.optimizable_count} 项 ｜ 人工 {res.manual_count} 项
          {res.missing_cap_ids.length > 0 && <><br /><small style={{ color: 'var(--warn)' }}>无最高限价：{res.missing_cap_ids.join('、')}</small></>}
          {res.missing_cost_ids.length > 0 && <><br /><small style={{ color: 'var(--warn)' }}>缺成本锚点：{res.missing_cost_ids.join('、')}</small></>}
          {res.duplicate_item_id_across_unit_work.length > 0 && <><br /><strong style={{ color: 'var(--danger)' }}>跨单位工程重复编码：{res.duplicate_item_id_across_unit_work.join('、')}（优化将被阻断）</strong></>}</div>
        <div style={box}><b>字段适配</b><br />
          {chip('item_id', '编码')} {chip('item_name', '名称')} {chip('unit', '单位')} {chip('q0', '工程量')}{' '}
          {chip('cap', '限价')} {chip('q1_point', '结算量')} {chip('c_i', '成本')}</div>
        <div style={box}><b>异常</b> {res.anomaly_count} 条
          {res.anomalies.length > 0 && <>：{res.anomalies.map((a) => `${a.kind}@${a.item_id}`).join('、')}</>}
          <br /><small style={{ color: 'var(--text-tertiary)' }}>仅限价侧 {m.only_cap_ids?.length ? '：' + m.only_cap_ids.join('、') : '—'}</small></div>
      </div>
    </div>
  );
}

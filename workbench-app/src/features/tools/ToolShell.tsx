import type { ReactNode } from 'react';
import PageHead from '../../components/PageHead';

/**
 * 工具页共用布局件（P2 前端整合）。
 * 沿用原生工具页的类名（tools.css 已并入 global.css），不改样式契约。
 */

/** 工具页外壳：PageHead 页头 + 卡片（标题/副标题 + 内容）。 */
export function ToolShell({
  title, subtitle, children, id, en,
}: {
  title: string; subtitle: string; children: ReactNode; id: string;
  /** 英文名，用于页头 eyebrow，如 "Cable" */
  en: string;
}) {
  return (
    <>
      <PageHead zh={title} en={en} sub={title} subEn={subtitle} />
      <section className="card tool-card" id={id}>
        {children}
      </section>
      <p className="hint" style={{ margin: '6px 0 30px' }}>
        本页为速算参考，不替代工程量清单计价规范（GB 50500）的正式算量与组价流程；工程量以施工图与现场计量为准。
      </p>
    </>
  );
}

/** 数字字段：label + input + 单位后缀。 */
export function NumField({
  id, label, value, onChange, tip, step = 1, min = 0, suffix,
}: {
  id: string; label: string; value: number | string; onChange: (v: number) => void;
  tip?: string; step?: number; min?: number; suffix?: string;
}) {
  return (
    <label className="field" data-tip={tip}>
      <span className="field-label">{label}</span>
      <input
        id={id}
        className="tabular"
        type="number"
        min={min}
        step={step}
        value={value}
        onChange={(e) => onChange(e.target.value === '' ? 0 : Number(e.target.value))}
      />
      {suffix && <span className="unit-suffix">{suffix}</span>}
    </label>
  );
}

/** 结果条：一组「标签 + 数值」指标。 */
export function ResultStrip({ items }: { items: { label: string; value: ReactNode }[] }) {
  return (
    <div className="result-strip">
      {items.map((it) => (
        <div className="metric" key={it.label}>
          <span className="metric-label">{it.label}</span>
          <strong>{it.value}</strong>
        </div>
      ))}
    </div>
  );
}

/** 千分位格式化（与原生 toolFmt 一致，2 位小数）。 */
export const fmt = (v: number, d = 2): string =>
  isFinite(v) ? v.toLocaleString('zh-CN', { minimumFractionDigits: d, maximumFractionDigits: d }) : '—';

/** 项目经营共享：API 基地址、数字格式化、项目类型（Biz 与 BizDetail 共用）。 */
export const API_BASE =
  (window as unknown as { __API_BASE__?: string }).__API_BASE__
  || (location.hostname ? location.protocol + '//' + location.hostname + ':8000' : 'http://localhost:8000');

export interface ProjectOverview {
  id: string;
  name?: string | null;
  short_name?: string | null;
  stage?: string | null;
  limit_total?: number | string | null;
  bid_open_date?: string | null;
  bid_amount?: number | string | null;
  bid_cost?: number | string | null;
  actual_cost?: number | string | null;
  actual_revenue?: number | string | null;
  settle_amount?: number | string | null;
  completed_at?: string | null;
  gross_profit?: number | null;
  gross_margin?: number | null;
  actual_yield?: number | null;
}

export function toNum(v: unknown): number | null {
  if (v == null || v === '') return null;
  const n = Number(v);
  return Number.isNaN(n) ? null : n;
}

/** 金额：千分位 + 2 位小数；空值显示「—」。 */
export function yf(v: unknown): string {
  const n = toNum(v);
  if (n == null) return '—';
  return n.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

/** 百分比：内部存 0-1 小数，转百分比保留 2 位。 */
export function pct(v: unknown): string {
  const n = toNum(v);
  if (n == null) return '—';
  return (n * 100).toFixed(2) + '%';
}

export interface ExecSummary {
  project_id: string | null;
  contract_total: number;
  received_total: number;
  receivable: number;
  fund_pressure: number | null;
  cost_target: number;
  cost_actual: number;
  cost_variance: number;
  visa_approved: number;
  visa_pending: number;
  settle_submit: number;
  settle_approved: number;
  settle_reduction: number;
}

/**
 * 投标报价 · 派生计算内核（P3-0 前端整合）
 *
 * 由 frontend/app.js 抽出，逐字保留口径。这些都是**数值关键路径**：
 * 合规评分、进项抵扣、明细筛选/排序/分页、报价比率分档、税口径汇总。
 * 抽成纯函数后可用判据锁住（quoteCalc.test.ts），React 重写时据此对照。
 * 后端实现不变，此处只镜像前端派生值。
 */

/* ============================ 合规评分（app.js computeCompliance） ============================ */

export interface QuoteItem { [k: string]: unknown }
export interface QuoteResult {
  status?: string;
  items?: QuoteItem[];
  violations?: unknown[];
  anomalies?: unknown[];
  low_ratio_items?: unknown[];
  low_ratio_review_required?: boolean;
  target_total?: number;
  objective?: number;
  competitive_budget?: number;
  cost_input_tax?: { multiplier?: number; credit_ratio?: number };
  [k: string]: unknown;
}

export interface Compliance {
  score: number; grade: string; audit: string; badge: string;
  maxDev: string; safe: number; early: number; risk: number;
}

/** 单项是否风险：比率 <0.5 / 人工复核 / 毛利为负。 */
export const isRiskRow = (r: QuoteItem): boolean =>
  Number(r['报价比率'] ?? 1) < 0.5 || r['报价状态'] === 'MANUAL_REVIEW' || Number(r['单项毛利'] ?? 0) < 0;

export function computeCompliance(result: QuoteResult | null | undefined): Compliance {
  let score = 100;
  if (!result || result.status !== 'PASS') {
    return { score: 0, grade: '—', audit: (result && result.status) || '未通过', badge: 'warn', maxDev: '—', safe: 0, early: 0, risk: 100 };
  }
  const items = result.items || [];
  const riskRows = items.filter(isRiskRow);
  // 三桶互斥：有意提前回笼（≥92%）的项若已属风险桶则不重复计入 early
  const earlyRows = items.filter((r) => Number(r['报价比率'] ?? 0) >= 0.92 && !isRiskRow(r));
  const n = items.length || 1;
  const failCount = [].concat(result.violations || [], result.anomalies || [], result.low_ratio_items || []).length;
  score -= Math.min(40, failCount * 8);
  score -= Math.min(25, riskRows.length * 5);
  if (result.low_ratio_review_required) score -= 12;
  score = Math.max(0, Math.min(100, Math.round(score)));

  let grade: string, badge: string;
  if (score >= 90) { grade = 'AA+'; badge = 'gain'; }
  else if (score >= 75) { grade = 'A'; badge = 'neutral'; }
  else if (score >= 60) { grade = 'B'; badge = 'warn'; }
  else { grade = 'C'; badge = 'warn'; }
  const audit = result.status === 'PASS' ? (score >= 90 ? '合规闸门通过' : (score >= 60 ? '合规待关注' : '需人工复核')) : '闸门未通过';
  const maxDev = items.reduce((m, r) => Math.max(m, Math.abs((Number(r['报价比率'] ?? 1) || 0) - 1)), 0);

  const safe = Math.round(((n - (earlyRows.length + riskRows.length)) / n) * 100);
  const early = Math.round((earlyRows.length / n) * 100);
  return {
    score, grade, audit, badge,
    maxDev: (maxDev * 100).toFixed(1) + '%',
    safe, early,
    // risk 取余数，保证三段恒为 100%（避免分段各自四舍五入造成 >100% 溢出）
    risk: Math.max(0, 100 - safe - early),
  };
}

/* ============================ 进项抵扣（app.js computeInputVat） ============================ */

export interface InputVat { vat: number; share: string; k: string; status: string }

/**
 * k = 1 − Σpⱼrⱼ/(1+rⱼ)，抵扣占比 = 1 − k，抵扣额 = Σ含税成本 × (1 − k)。
 * 直接消费后端 cost_input_tax.multiplier(k)，避免用单一 credit_ratio 加权近似。
 */
export function computeInputVat(result: QuoteResult | null | undefined): InputVat {
  const tax = (result && result.cost_input_tax) || {};
  const k = tax.multiplier != null && isFinite(Number(tax.multiplier)) ? Number(tax.multiplier) : null;
  const credit = k != null
    ? Math.max(0, 1 - k)
    : Math.max(0, Number(tax.credit_ratio == null ? 0 : tax.credit_ratio)) || 0;
  const raw = (result?.items || []).reduce((s, r) => s + Number(r['含税成本单价'] ?? 0) * Number(r['工程量'] ?? 0), 0);
  const vat = Math.max(0, credit * raw);
  return { vat, share: (credit * 100).toFixed(1) + '%', k: k != null ? k.toFixed(4) : '—', status: credit > 0 ? '抵扣达标' : '不可抵扣' };
}

/* ============================ 明细筛选 / 排序 / 分页（app.js renderDashTable + _renderDashPager） ============================ */

export const DASH_PAGE_SIZE = 50;
export type DashFilter = 'all' | 'risk' | 'early';

/** 按筛选条件过滤（risk 与 renderDashTable 逐字一致；early 额外排除人工复核）。 */
export function filterDashItems(items: QuoteItem[], filter: DashFilter): QuoteItem[] {
  if (filter === 'risk') return items.filter(isRiskRow);
  if (filter === 'early') return items.filter((r) => Number(r['报价比率'] ?? 0) >= 0.92 && r['报价状态'] !== 'MANUAL_REVIEW');
  return items.slice();
}

/** 排序：按单项毛利降序（可选）。 */
export function sortDashItems(items: QuoteItem[], sortMargin: boolean): QuoteItem[] {
  return sortMargin ? items.slice().sort((a, b) => Number(b['单项毛利'] ?? 0) - Number(a['单项毛利'] ?? 0)) : items;
}

/** 分页：越界保护（筛选后总行数变少 → 夹回 0 页），与原实现一致。 */
export function pageDashItems(items: QuoteItem[], page: number): { rows: QuoteItem[]; page: number; pageCount: number } {
  const pageCount = Math.max(1, Math.ceil(items.length / DASH_PAGE_SIZE));
  const p = page >= pageCount ? 0 : page;
  return { rows: items.slice(p * DASH_PAGE_SIZE, (p + 1) * DASH_PAGE_SIZE), page: p, pageCount };
}

/** 报价比率分档标签（renderDashTable 的 tag 逻辑）。 */
export function ratioTagClass(row: QuoteItem): 'safe' | 'risk' | 'early' {
  const ratio = Number(row['报价比率']);
  if (row['报价状态'] === 'MANUAL_REVIEW') return 'risk';
  if (Number(row['单项毛利'] ?? 0) < 0 || ratio < 0.5) return 'risk';
  if (Number.isFinite(ratio) && ratio >= 0.92) return 'early';
  return 'safe';
}

/* ============================ 税口径汇总（app.js readTaxOverride 的纯计算部分） ============================ */

export interface TaxComp { key: string; label: string; proportion: number; input_vat_rate: number }
export interface TaxOverride { mode: string; creditRatio: number; compositionJson: string }

/**
 * 汇总税口径覆盖：creditRatio = Σ(可抵扣项占比)（仅 input_vat_rate > 0 的项）。
 * 与原 readTaxOverride 的算法一致（DOM 读取部分留给组件）。
 */
export function buildTaxOverride(mode: string, comp: TaxComp[]): TaxOverride {
  if (mode === 'NONE') return { mode, creditRatio: 0, compositionJson: '' };
  let credit = 0;
  comp.forEach((c) => { if (c.input_vat_rate > 0) credit += c.proportion; });
  return { mode, creditRatio: credit, compositionJson: JSON.stringify(comp) };
}

/* ============================ 毛利与比率（renderKpi 的派生） ============================ */

/** 毛利率 = objective / target_total × 100（百分比数值）。 */
export function marginRatePercent(result: QuoteResult | null | undefined): number {
  const total = Number(result?.target_total ?? 0);
  const objective = Number(result?.objective ?? 0);
  return total > 0 ? (objective / total) * 100 : 0;
}

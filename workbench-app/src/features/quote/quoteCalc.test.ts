/**
 * 投标报价派生计算判据（P3-0 前端整合）
 *
 * 期望值按公式手算并写明推导（原生页无接口喂任意 result，故用推导式而非实测；
 * 口径逐字搬自 app.js，用例即口径的可读规格）。
 */
import { describe, it, expect } from 'vitest';
import {
  computeCompliance, computeInputVat, filterDashItems, sortDashItems, pageDashItems,
  ratioTagClass, buildTaxOverride, marginRatePercent, DASH_PAGE_SIZE,
  type QuoteItem, type QuoteResult,
} from './quoteCalc';

// 默认 0.8：既非风险（<0.5）又非早结倾斜（≥0.92），即平准档
const item = (over: Partial<Record<string, unknown>> = {}): QuoteItem => ({
  '报价比率': 0.8, '报价状态': 'OK', '单项毛利': 10, '含税成本单价': 100, '工程量': 2, ...over,
});

describe('合规评分 computeCompliance', () => {
  it('非 PASS → 0 分 / — / 未通过 / risk 100', () => {
    const c = computeCompliance({ status: 'BLOCKED' } as QuoteResult);
    expect(c.score).toBe(0);
    expect(c.grade).toBe('—');
    expect(c.audit).toBe('BLOCKED');
    expect(c.risk).toBe(100);
  });

  it('全清项（比率 0.8 平准、毛利正）→ 100 分 AA+；三桶合计 100', () => {
    const items = [item(), item(), item()];
    const c = computeCompliance({ status: 'PASS', items });
    expect(c.score).toBe(100);
    expect(c.grade).toBe('AA+');
    expect(c.audit).toBe('合规闸门通过');
    expect(c.badge).toBe('gain');
    expect(c.safe + c.early + c.risk).toBe(100);
    expect(c.safe).toBe(100);
  });

  it('比率 ≥0.92 计入 early（早结倾斜），不计安全', () => {
    const c = computeCompliance({ status: 'PASS', items: [item({ '报价比率': 1.0 }), item()] });
    expect(c.safe).toBe(50);
    expect(c.early).toBe(50);
    expect(c.risk).toBe(0);
  });

  it('每条 violation/anomaly/low_ratio_item 扣 8，封顶 40；每个风险项扣 5，封顶 25', () => {
    // 6 条 failCount → 6*8=48，封顶 40；2 个风险项 → 10 → 100-40-10 = 50（<60 → C）
    const items = [item(), item({ '报价比率': 0.4 }), item({ '报价状态': 'MANUAL_REVIEW' }), item(), item(), item()];
    const c = computeCompliance({
      status: 'PASS', items,
      violations: [1, 2, 3], anomalies: [1, 2, 3], low_ratio_items: [],
    } as QuoteResult);
    expect(c.score).toBe(50);
    expect(c.grade).toBe('C');
  });

  it('low_ratio_review_required 额外扣 12', () => {
    const c = computeCompliance({ status: 'PASS', items: [item()], low_ratio_review_required: true } as QuoteResult);
    expect(c.score).toBe(88);
    expect(c.grade).toBe('A');
  });

  it('grade 四档：≥90→AA+ / ≥75→A / ≥60→B / <60→C', () => {
    // 每条 violation 扣 8（封顶 40）：0→100、2→84、5→60、5+low_ratio(12)→48
    const g = (extra: Partial<QuoteResult>) => computeCompliance({ status: 'PASS', items: [item()], ...extra } as QuoteResult).grade;
    expect(g({})).toBe('AA+');
    expect(g({ violations: [1, 2] })).toBe('A');
    expect(g({ violations: [1, 2, 3, 4, 5] })).toBe('B');
    expect(g({ violations: [1, 2, 3, 4, 5], low_ratio_review_required: true })).toBe('C');
  });
});

describe('进项抵扣 computeInputVat', () => {
  it('k 存在 → 抵扣占比 = 1-k，抵扣额 = Σ含税成本×工程量×(1-k)', () => {
    // k=0.9 → credit 0.1；两项：100×2 + 50×4 = 400 → vat 40
    const r: QuoteResult = {
      cost_input_tax: { multiplier: 0.9 },
      items: [item({ '含税成本单价': 100, '工程量': 2 }), item({ '含税成本单价': 50, '工程量': 4 })],
    };
    const v = computeInputVat(r);
    expect(v.vat).toBeCloseTo(40, 6);
    expect(v.share).toBe('10.0%');
    expect(v.k).toBe('0.9000');
    expect(v.status).toBe('抵扣达标');
  });

  it('k 缺失 → 回退 credit_ratio', () => {
    const r: QuoteResult = { cost_input_tax: { credit_ratio: 0.13 }, items: [item({ '含税成本单价': 100, '工程量': 1 })] };
    const v = computeInputVat(r);
    expect(v.vat).toBeCloseTo(13, 6);
    expect(v.share).toBe('13.0%');
    expect(v.k).toBe('—');
  });

  it('无可抵扣 → vat 0 / 不可抵扣 / 0.0%', () => {
    const v = computeInputVat({ cost_input_tax: { multiplier: 1 }, items: [item()] } as QuoteResult);
    expect(v.vat).toBe(0);
    expect(v.status).toBe('不可抵扣');
    expect(v.share).toBe('0.0%');
  });
});

describe('明细筛选 / 排序 / 分页', () => {
  const rows: QuoteItem[] = [
    item({ '报价比率': 1.0, '单项毛利': 5 }),          // early（≥0.92）
    item({ '报价比率': 0.4, '单项毛利': 9 }),          // risk（比率<0.5）
    item({ '报价比率': 0.95, '单项毛利': 1 }),          // early
    item({ '报价状态': 'MANUAL_REVIEW', '报价比率': 0.95 }), // 人工复核：risk，不算 early
  ];

  it('filter：risk 抓比率<0.5 / 人工复核 / 负毛利', () => {
    expect(filterDashItems(rows, 'risk')).toHaveLength(2);
  });

  it('filter：early 抓 ≥0.92 且非人工复核', () => {
    expect(filterDashItems(rows, 'early')).toHaveLength(2);
  });

  it('sort：按单项毛利降序', () => {
    const s = sortDashItems(rows, true);
    // 四行毛利：5 / 9 / 1 / 10（人工复核行未覆盖单项毛利，继承默认 10）→ 首项应为 10
    expect(Number(s[0]['单项毛利'])).toBe(10);
    expect(Number(s[3]['单项毛利'])).toBe(1);
  });

  it('page：越界夹回第 0 页；页大小 50', () => {
    expect(DASH_PAGE_SIZE).toBe(50);
    const many = Array.from({ length: 60 }, () => item());
    expect(pageDashItems(many, 0).pageCount).toBe(2);
    expect(pageDashItems(many, 5).page).toBe(0);          // 越界 → 0
    expect(pageDashItems(many, 1).rows).toHaveLength(10);
  });

  it('ratioTagClass 四档', () => {
    expect(ratioTagClass(item({ '报价比率': 0.8, '单项毛利': 1 }))).toBe('safe');   // 平准
    expect(ratioTagClass(item({ '报价比率': 0.4 }))).toBe('risk');
    expect(ratioTagClass(item({ '报价状态': 'MANUAL_REVIEW' }))).toBe('risk');
    expect(ratioTagClass(item({ '报价比率': 0.95, '单项毛利': 1 }))).toBe('early');  // 早结倾斜
  });
});

describe('税口径汇总 buildTaxOverride', () => {
  const comp = [
    { key: 'steel', label: '钢材', proportion: 0.5, input_vat_rate: 0.13 },
    { key: 'labor', label: '人工', proportion: 0.3, input_vat_rate: 0 },      // 0% 不计入 credit
    { key: 'cable', label: '电缆', proportion: 0.2, input_vat_rate: 0.13 },
  ];

  it('creditRatio = 仅 rate>0 的占比之和 = 0.7', () => {
    const t = buildTaxOverride('PARTIAL', comp);
    expect(t.creditRatio).toBeCloseTo(0.7, 6);
    expect(JSON.parse(t.compositionJson)).toHaveLength(3);
  });

  it('NONE → credit 0、composition 空串', () => {
    const t = buildTaxOverride('NONE', comp);
    expect(t.creditRatio).toBe(0);
    expect(t.compositionJson).toBe('');
  });
});

describe('毛利率', () => {
  it('objective / target_total × 100', () => {
    expect(marginRatePercent({ target_total: 1000, objective: 120 } as QuoteResult)).toBeCloseTo(12, 6);
    expect(marginRatePercent({ target_total: 0, objective: 120 } as QuoteResult)).toBe(0);
  });
});

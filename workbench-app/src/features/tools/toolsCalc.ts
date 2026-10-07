/**
 * 速算工具箱 · 计算内核（P2 前端整合）
 *
 * 设计：把 4 个工具页的**计算**从 DOM 里剥出来，做成纯函数。
 * 这样既可被 React 组件调用，又能直接写「输入→期望输出」判据（toolsCalc.test.ts）。
 * 期望值来自原生页 :8000 的实测输出（.trae 一次性取证），逐字段比对。
 *
 * 口径与原生版逐字一致（见各函数头注释中引用的原文件）。
 */

/* ============================ 排管断面（tool-duct.js） ============================ */

export interface DuctInput {
  circuits: number;      // 回路数 n
  perCircuit: number;    // 每回路孔数
  spare: number;         // 备用孔
  layout: 'auto' | 'manual';
  rows: number;          // 手动排列行数
  cols: number;          // 手动排列列数
  D: number;             // 管外径 mm
  gap: number;           // 管净距 mm
  cover: number;         // 包封保护层 mm
  work: number;          // 每侧工作面 mm
}

export interface DuctResult {
  used: number; total: number; cap: number;
  rows: number; cols: number;
  Wd: number; Hd: number; W: number; H: number;
  conc: number; a: number;
  spareShown: number;
  note: string;
}

/** 标准排列（行, 列），容量递增 —— T/SDL 4-2022。 */
const STD_LAYOUTS: [number, number][] = [[1, 2], [2, 2], [2, 3], [2, 4], [3, 4], [4, 4], [4, 6]];

function autoLayout(total: number): { rows: number; cols: number; std: boolean } {
  for (const [r, c] of STD_LAYOUTS) if (r * c >= total) return { rows: r, cols: c, std: true };
  return { rows: 4, cols: Math.ceil(total / 4), std: false };
}

export function calcDuct(p: DuctInput): DuctResult {
  const n = Math.max(1, Math.round(p.circuits));
  const per = Math.max(1, Math.round(p.perCircuit));
  const spare = Math.max(0, Math.round(p.spare));
  const used = n * per;
  const D = Math.max(0, p.D);
  const gap = Math.max(0, p.gap);
  const cover = Math.max(0, p.cover);
  const work = Math.max(0, p.work);

  let rows: number, cols: number, note = '';
  if (p.layout === 'manual') {
    rows = Math.max(1, Math.round(p.rows));
    cols = Math.max(1, Math.round(p.cols));
    if (rows * cols < used) note = `※ 孔位不足：已用 ${used} 孔，当前 ${rows}×${cols} 仅 ${rows * cols} 孔`;
  } else {
    const L = autoLayout(Math.max(used + spare, 2));
    rows = L.rows; cols = L.cols;
    if (!L.std) note = '已超出标准表（24 孔），按 4 层向上取整列数，请按设计复核';
  }

  const cap = rows * cols;
  const Wd = cols * D + (cols - 1) * gap;      // 管束宽
  const Hd = rows * D + (rows - 1) * gap;      // 管束高
  const W = Wd + 2 * cover;                    // 包封宽
  const H = Hd + 2 * cover;                    // 包封高
  const conc = Math.max(0, (W * H - cap * Math.PI * Math.pow(D / 2, 2)) / 1e6);  // m³/m
  const a = (W + 2 * work) / 1000;             // 沟底宽建议 m
  return { used, total: used + spare, cap, rows, cols, Wd, Hd, W, H, conc, a, spareShown: Math.max(0, cap - used), note };
}

/* ============================ 挖方与回填（tool-earth.js） ============================ */

export interface EarthRule { m: number; start: number }
export type EarthMode = 'spec' | 'none' | 'custom';

export interface EarthRow {
  name?: string;
  len: number; a: number; h: number;
  soil: number;        // 0/1/2
  mode: EarthMode;
  mCustom: number;
  deduct: number;
}

export interface EarthRowResult {
  mEff: number; note: string;
  dig: number; back: number; surplus: number;
}

/** 放坡口径预设（三套同值；电力/市政为建筑定额占位值，须核对）。 */
export const EARTH_RULE_PRESETS: Record<string, EarthRule[]> = {
  arch:  [{ m: 0.50, start: 1.2 }, { m: 0.33, start: 1.5 }, { m: 0.25, start: 2.0 }],
  power: [{ m: 0.50, start: 1.2 }, { m: 0.33, start: 1.5 }, { m: 0.25, start: 2.0 }],
  muni:  [{ m: 0.50, start: 1.2 }, { m: 0.33, start: 1.5 }, { m: 0.25, start: 2.0 }],
};

/** 单段：挖方 V = L × (a + m·h) × h；回填 = 挖方 − 管位占置；余方 = 挖方 − 回填。 */
export function calcEarthRow(row: EarthRow, rules: EarthRule[]): EarthRowResult {
  const len = Math.max(0, row.len), a = Math.max(0, row.a), h = Math.max(0, row.h), deduct = Math.max(0, row.deduct);
  const rule = rules[row.soil] || rules[0];

  let mEff = 0, note = '';
  if (row.mode === 'none') { mEff = 0; note = '直槽'; }
  else if (row.mode === 'custom') { mEff = Math.max(0, row.mCustom); note = '自定'; }
  else {
    mEff = h > rule.start ? rule.m : 0;
    note = h > rule.start ? '' : `未达 ${rule.start}m`;
  }

  const dig = len * (a + mEff * h) * h;
  const back = Math.max(0, dig - len * deduct);
  const surplus = dig - back;
  return { mEff, note, dig, back, surplus };
}

export interface EarthTotals { dig: number; back: number; surplus: number; surplusLoose: number; cost: number }

export function calcEarth(rows: EarthRow[], rules: EarthRule[], prices: { dig: number; back: number; haul: number }, loose: number): { rows: EarthRowResult[]; totals: EarthTotals } {
  const L = loose || 1;
  const out = rows.map((r) => calcEarthRow(r, rules));
  let tDig = 0, tBack = 0, tSur = 0, cost = 0;
  out.forEach((r) => {
    const haulVol = r.surplus >= 0 ? r.surplus * L : Math.abs(r.surplus);  // 外运按虚方，借方按天然方
    cost += r.dig * prices.dig + r.back * prices.back + haulVol * prices.haul;
    tDig += r.dig; tBack += r.back; tSur += r.surplus;
  });
  return {
    rows: out,
    totals: { dig: tDig, back: tBack, surplus: tSur, surplusLoose: tSur > 0 ? tSur * L : 0, cost },
  };
}

/* ============================ 电缆价格速算（tool-cable.js） ============================ */

export const METAL_DENSITY: Record<string, number> = { cu: 8.89, al: 2.70 };
export const VOLT_MAT: Record<string, number> = { lv: 0.30, mv: 0.40, hv: 0.50 };

/** 「3×240」「3×240+2×120」→ Σ(芯数×截面)。 */
export function parseSpec(text: string): number {
  let sum = 0;
  const re = /(\d+)\s*[×xX*]\s*(\d+(?:\.\d+)?)/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(String(text || ''))) !== null) sum += +m[1] * +m[2];
  return sum;
}

export interface CableRow {
  model?: string;
  metal: 'cu' | 'al'; spec: string;
  len: number; pullPts: number; pullLen: number; qty: number; loss: number; matRatio: number | '';
}

export interface CableRowResult { cuCost: number; pNex: number; pTax: number; total: number; nexTotal: number; ok: boolean }

export function calcCableRow(row: CableRow, prices: { cu: number; al: number }, k: number, mgrPct: number, vatPct: number, voltKey: string): CableRowResult {
  const areaSum = parseSpec(row.spec);
  const density = METAL_DENSITY[row.metal];
  const metalPrice = row.metal === 'cu' ? prices.cu : prices.al;
  const mgr = mgrPct / 100, vat = vatPct / 100;
  const kk = k || 1;

  const cuCost = (areaSum * density * metalPrice) / 1e6 * kk;   // 导体成本 元/m
  const matRatio = row.matRatio === '' || row.matRatio == null ? (VOLT_MAT[voltKey] ?? 0.30) : row.matRatio;
  const pNex = cuCost * (1 + matRatio) * (1 + mgr);
  const pTax = pNex * (1 + vat);
  const calcLen = (row.len + row.pullPts * row.pullLen) * row.qty;
  const total = pTax * calcLen * (1 + row.loss / 100);
  const nexTotal = pNex * calcLen * (1 + row.loss / 100);
  const ok = areaSum > 0;
  return { cuCost, pNex, pTax, total, nexTotal, ok };
}

/** 整表合计（含税 total / 不含税 nexTotal）。 */
export function calcCableRows(rows: CableRow[], prices: { cu: number; al: number }, k: number, mgrPct: number, vatPct: number, voltKey: string) {
  const out = rows.map((r) => calcCableRow(r, prices, k, mgrPct, vatPct, voltKey));
  let total = 0, nexTotal = 0;
  out.forEach((r) => { total += r.total; nexTotal += r.nexTotal; });
  return { rows: out, total, nexTotal };
}

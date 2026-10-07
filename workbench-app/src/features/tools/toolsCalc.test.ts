/**
 * 速算工具箱计算内核判据（P2 前端整合）
 *
 * 期望值来源：原生页 :8000 的实测输出（一次性 Playwright 取证，见 docs/FRONTEND_UNIFY_PLAN.md）。
 * 目的：React 重写不得改变任何数值——这些用例是「数值不回归」的机械判据。
 */
import { describe, it, expect } from 'vitest';
import { calcDuct } from './toolsCalc';
import { calcEarth, EARTH_RULE_PRESETS } from './toolsCalc';
import { calcCableRows, parseSpec } from './toolsCalc';
import { calcWell, WELL_UNITS } from './wellCalc';

describe('排管断面 calcDuct（对照原生实测）', () => {
  it('2×3 回路 + 4 备用 + D160/净距20/保护50/工作面300 → 3×4/12孔 700×520 800×620 conc0.255 a1.40', () => {
    const r = calcDuct({ circuits: 2, perCircuit: 3, spare: 4, layout: 'auto', rows: 2, cols: 4, D: 160, gap: 20, cover: 50, work: 300 });
    expect(`${r.rows}×${r.cols} / ${r.cap} 孔`).toBe('3×4 / 12 孔');
    expect(`${Math.round(r.Wd)}×${Math.round(r.Hd)}`).toBe('700×520');
    expect(`${Math.round(r.W)}×${Math.round(r.H)}`).toBe('800×620');
    expect(r.conc.toFixed(3)).toBe('0.255');
    expect(r.a.toFixed(2)).toBe('1.40');
  });

  it('4×3 回路 + 6 备用 + D200/净距25/保护60/工作面400 → 4×6/24孔 1325×875 1445×995 conc0.684 a2.25', () => {
    const r = calcDuct({ circuits: 4, perCircuit: 3, spare: 6, layout: 'auto', rows: 4, cols: 6, D: 200, gap: 25, cover: 60, work: 400 });
    expect(`${r.rows}×${r.cols} / ${r.cap} 孔`).toBe('4×6 / 24 孔');
    expect(`${Math.round(r.Wd)}×${Math.round(r.Hd)}`).toBe('1325×875');
    expect(`${Math.round(r.W)}×${Math.round(r.H)}`).toBe('1445×995');
    expect(r.conc.toFixed(3)).toBe('0.684');
    expect(r.a.toFixed(2)).toBe('2.25');
  });

  it('1×1 回路 + 1 备用 + D110 → 1×2/2孔 240×110 340×210 conc0.052 a0.94', () => {
    const r = calcDuct({ circuits: 1, perCircuit: 1, spare: 1, layout: 'auto', rows: 1, cols: 2, D: 110, gap: 20, cover: 50, work: 300 });
    expect(`${r.rows}×${r.cols} / ${r.cap} 孔`).toBe('1×2 / 2 孔');
    expect(`${Math.round(r.Wd)}×${Math.round(r.Hd)}`).toBe('240×110');
    expect(`${Math.round(r.W)}×${Math.round(r.H)}`).toBe('340×210');
    expect(r.conc.toFixed(3)).toBe('0.052');
    expect(r.a.toFixed(2)).toBe('0.94');
  });
});

describe('挖方与回填 calcEarth（对照原生实测）', () => {
  it('L100/a1.2/h2.5/一二类土/deduct0.5/虚方1.30 → dig612.5 back562.5 surplus50.0 合价30125.00', () => {
    const { rows, totals } = calcEarth(
      [{ len: 100, a: 1.2, h: 2.5, soil: 0, mode: 'spec', mCustom: 0.5, deduct: 0.5 }],
      EARTH_RULE_PRESETS.arch,
      { dig: 30, back: 18, haul: 25 },
      1.30,   // 原生 #eLoose 默认 1.30（实测时未改），外运按虚方
    );
    expect(rows[0].dig.toFixed(1)).toBe('612.5');
    expect(rows[0].back.toFixed(1)).toBe('562.5');
    expect(rows[0].surplus.toFixed(1)).toBe('50.0');
    expect(totals.dig.toFixed(1)).toBe('612.5');
    // 612.5×30 + 562.5×18 + 50×1.3×25 = 18375+10125+1625 = 30125
    expect(totals.cost.toFixed(2)).toBe('30125.00');
  });
});

describe('电缆价格 calcCableRows（对照原生实测）', () => {
  it('铜78000/3×240/100m/2根/损耗1.5%/系数1.05/管理8%/增值税13% → 行合价 181821.16', () => {
    expect(parseSpec('3×240')).toBe(720);
    const { rows, total, nexTotal } = calcCableRows(
      [{ metal: 'cu', spec: '3×240', len: 100, pullPts: 0, pullLen: 0, qty: 2, loss: 1.5, matRatio: '' }],   // 空串→电压建议值（mv=0.40）
      { cu: 78000, al: 21000 },
      1.05, 8, 13, 'mv',   // 原生 #cVolt 默认 mv（8.7/15kV，系数 0.40）
    );
    expect(rows[0].cuCost.toFixed(2)).toBe('524.23');
    expect(rows[0].pNex.toFixed(2)).toBe('792.63');
    expect(rows[0].pTax.toFixed(2)).toBe('895.67');
    expect(rows[0].total.toFixed(2)).toBe('181821.16');
    expect(total.toFixed(2)).toBe('181821.16');
    expect(nexTotal.toFixed(2)).toBe('160903.68');
  });

  it('parseSpec 支持多规格 3×240+2×120 = 960', () => {
    expect(parseSpec('3×240+2×120')).toBe(960);
    expect(parseSpec('5×16')).toBe(80);
    expect(parseSpec('')).toBe(0);
  });
});

describe('电缆井 calcWell 结构性判据（无原生实测，先锁不变量）', () => {
  const base = {
    L: 2, W: 1.5, D: 2, t: 0.2, nB: 0,
    Lb: 0, Wb: 0, baseT: 0.2, padT: 0.1, topT: 0.2, padOut: 0.1,
    lipW: 0, lipH: 0, conc: true,
    rebarBase: 60, rebarWall: 50, rebarTop: 50,
    count: 1, coverCount: 1, coverL: 1, coverW: 1, coverT: 0.1,
    coverMainN: 0, coverMainL: 0, coverDistN: 0, coverDistL: 0, coverEdgeL: 0,
    shaft: { on: false, sD: 0, sH: 0, sT: 0 },
  };

  it('15 行单位表，默认价与该表 defaultPrice 一致', () => {
    expect(WELL_UNITS).toHaveLength(15);
    const r = calcWell(base, WELL_UNITS.map((u) => u.defaultPrice));
    expect(r.quantities).toHaveLength(15);
    expect(r.total).toBeGreaterThan(0);
  });

  it('砖砌时井壁钢筋为 0，混凝土时 >0', () => {
    const conc = calcWell(base, WELL_UNITS.map((u) => u.defaultPrice));
    const brick = calcWell({ ...base, conc: false }, WELL_UNITS.map((u) => u.defaultPrice));
    const idx = WELL_UNITS.findIndex((u) => u.key === 'wallRebar');
    expect(conc.qtyPerWell[idx]).toBeGreaterThan(0);
    expect(brick.qtyPerWell[idx]).toBe(0);
  });

  it('count 线性放大合价', () => {
    const r1 = calcWell(base, WELL_UNITS.map((u) => u.defaultPrice));
    const r3 = calcWell({ ...base, count: 3 }, WELL_UNITS.map((u) => u.defaultPrice));
    expect(r3.total).toBeCloseTo(r1.total * 3, 6);
  });
});

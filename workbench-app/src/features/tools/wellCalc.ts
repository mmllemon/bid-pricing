/**
 * 速算工具箱 · 电缆井工程量内核（P2 前端整合）
 *
 * 由 frontend/js/tool-well.js 的 recalcWell 抽出，口径逐字保留。
 * 范围：主体工程量（15 行单位工程表）+ 合价。钢筋逐根表与 SVG 示意留在组件层。
 *
 * 井体 = 主井室（净空 L×W×D）＋ n 个支井室（净空 Lb×Wb，同深同壁厚）。
 * 中心线净长 clNet = 2(L+t) + 2(W+t) + nB(2Lb + t)
 * 底板/顶板面积 slabA = (L+2t)(W+2t) + nB(Wb+2t)(Lb + t/2)
 * 井壁 V = clNet × D × t（+ 井座体积 lipV）
 * 模板 = 混凝土井壁: 2×clNet×D ＋ outerP×baseT ＋ 井座外侧 ＋ 现浇顶板底；砖砌仅底板侧模＋顶板底模
 */

export interface WellInput {
  L: number; W: number; D: number; t: number;   // 主井室净空与壁厚
  nB: number; Lb: number; Wb: number;           // 支井室
  baseT: number; padT: number; topT: number;    // 底板/垫层/顶板厚
  padOut: number;                               // 垫层外挑
  lipW: number; lipH: number;                   // 井座宽/高
  conc: boolean;                                // true=混凝土井壁, false=砖砌
  rebarBase: number; rebarWall: number; rebarTop: number;  // 含钢量 kg/m³
  count: number;                                // 井数
  coverCount: number; coverL: number; coverW: number; coverT: number;   // 盖板
  coverMainN: number; coverMainL: number; coverDistN: number; coverDistL: number; coverEdgeL: number;
  shaft: { on: boolean; sD: number; sH: number; sT: number };
}

export interface WellRowUnit { key: string; label: string; unit: string; dec: number; defaultPrice: number }

/** 15 行单位工程表（顺序即表格行序）。 */
export const WELL_UNITS: WellRowUnit[] = [
  { key: 'pad', label: '混凝土垫层 C15', unit: 'm³', dec: 3, defaultPrice: 420 },
  { key: 'base', label: '混凝土底板 C30', unit: 'm³', dec: 3, defaultPrice: 520 },
  { key: 'baseRebar', label: '├ 底板钢筋', unit: 'kg', dec: 1, defaultPrice: 5.0 },
  { key: 'wall', label: '井壁', unit: 'm³', dec: 3, defaultPrice: 420 },
  { key: 'wallRebar', label: '├ 井壁钢筋', unit: 'kg', dec: 1, defaultPrice: 5.0 },
  { key: 'top', label: '混凝土顶板 C30', unit: 'm³', dec: 3, defaultPrice: 560 },
  { key: 'topRebar', label: '├ 顶板钢筋', unit: 'kg', dec: 1, defaultPrice: 5.0 },
  { key: 'shaft', label: '井筒砖砌', unit: 'm³', dec: 3, defaultPrice: 420 },
  { key: 'form', label: '模板（井壁内＋外、底板外侧、井座外侧）', unit: 'm²', dec: 2, defaultPrice: 65 },
  { key: 'render', label: '抹面（内＋外壁）', unit: 'm²', dec: 2, defaultPrice: 25 },
  { key: 'coverSlab', label: '盖板混凝土 C30（预制）', unit: 'm³', dec: 3, defaultPrice: 620 },
  { key: 'coverAngle', label: '盖板包边角钢 L50×5（每块）', unit: 'm', dec: 2, defaultPrice: 38 },
  { key: 'jkAngle', label: '接口角钢 L50×5（井座内侧上＋下两圈）', unit: 'm', dec: 2, defaultPrice: 38 },
  { key: 'cover', label: '井盖（重型球墨）', unit: '套', dec: 0, defaultPrice: 850 },
  { key: 'ladder', label: '爬梯', unit: '副', dec: 0, defaultPrice: 160 },
];

const REBAR_OF: Record<string, 'base' | 'wall' | 'top' | undefined> = {
  baseRebar: 'base', wallRebar: 'wall', topRebar: 'top',
};

export interface WellResult {
  /** 每行：单井工程量（未乘 count）。 */
  qtyPerWell: number[];
  /** 每行：总量 × 单价（已乘 count 与单价）。 */
  sums: number[];
  /** 每行：合价（count × 单价）。 */
  quantities: number[];
  total: number;
  steelEstKg: number;
  labels: Record<string, string>;
}

export function calcWell(p: WellInput, unitPrices: number[]): WellResult {
  const { L, W, D, t } = p;
  const nB = p.nB;
  const isConc = p.conc;

  const clNet = 2 * (L + t) + 2 * (W + t) + nB * (2 * p.Lb + t);
  const slabA = (L + 2 * t) * (W + 2 * t) + nB * (p.Wb + 2 * t) * (p.Lb + t / 2);
  const po = p.padOut;
  const padA = (L + 2 * t + 2 * po) * (W + 2 * t + 2 * po) + nB * (p.Wb + 2 * t + 2 * po) * (p.Lb + t / 2 + po);
  const outerP = 2 * (L + 2 * t) + 2 * (W + 2 * t) + nB * (2 * p.Lb + t);
  const innerP = 2 * (L + W) + nB * 2 * p.Lb;

  const lipW = p.lipW, lipH = p.lipH;
  const lipV = outerP * lipW * lipH;
  const jkIn = Math.max(0, 2 * (L + 2 * t - 2 * lipW) + 2 * (W + 2 * t - 2 * lipW)) + nB * Math.max(0, 2 * p.Lb + t - 4 * lipW);
  const lipOuterP = 2 * (L + 2 * t + 2 * lipW) + 2 * (W + 2 * t + 2 * lipW) + nB * (2 * p.Lb + t + 4 * lipW);
  const lipForm = lipW > 0 && lipH > 0 ? lipOuterP * lipH : 0;

  const concQty = { base: slabA * p.baseT, wall: clNet * D * t + lipV, top: slabA * p.topT };
  const rebarRatio = { base: p.rebarBase, wall: isConc ? p.rebarWall : 0, top: p.rebarTop };
  const shaftQ = Math.PI * (p.shaft.sD + p.shaft.sT) * p.shaft.sH * p.shaft.sT;

  const qtyPerWell = WELL_UNITS.map((u) => {
    const rb = REBAR_OF[u.key];
    if (rb) return (concQty as Record<string, number>)[rb] * (rebarRatio as Record<string, number>)[rb];
    switch (u.key) {
      case 'pad': return padA * p.padT;
      case 'base': return concQty.base;
      case 'wall': return concQty.wall;
      case 'top': return concQty.top;
      case 'shaft': return shaftQ;
      case 'form': return (isConc ? 2 * clNet * D : 0) + outerP * p.baseT + lipForm + (p.topT > 0 ? slabA : 0);
      case 'render': return (innerP + outerP) * D;
      case 'coverSlab': return p.coverCount * p.coverL * p.coverW * p.coverT;
      case 'coverAngle': return (p.coverCount * p.coverEdgeL) / 1000;
      case 'jkAngle': return lipW > 0 && lipH > 0 ? jkIn + jkIn : 0;
      case 'cover':
      case 'ladder': return 1;
      default: return 0;
    }
  });

  const count = Math.max(1, p.count || 1);
  let total = 0, steelEstKg = 0;
  const quantities: number[] = [];
  const sums: number[] = [];
  qtyPerWell.forEach((q0, i) => {
    const q = q0 * count;
    const price = unitPrices[i] ?? WELL_UNITS[i].defaultPrice;
    const sum = q * price;
    quantities.push(q);
    sums.push(sum);
    total += sum;
    if (REBAR_OF[WELL_UNITS[i].key]) steelEstKg += q;
  });

  // 井壁行的动态标签（砖砌/混凝土）+ 井壁钢筋适用性
  const labels: Record<string, string> = {
    wall: `井壁${isConc ? '（C30）' : '（砖砌 M10）'}`,
    wallRebar: `├ 井壁钢筋${isConc ? '' : '（砖砌不计）'}`,
  };

  return { qtyPerWell, sums, quantities, total, steelEstKg, labels };
}

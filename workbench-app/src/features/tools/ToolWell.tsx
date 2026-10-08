import { useMemo, useState } from 'react';
import { calcWell, WELL_UNITS, type WellInput } from './wellCalc';
import { ToolShell, ResultStrip, fmt } from './ToolShell';

/**
 * 电缆井工程量速算（P2 前端整合：由 frontend/tool-well.html + tool-well.js 迁入 React）
 * 主体工程量走 wellCalc.calcWell（纯函数，有判据）；平面/剖面 SVG 与钢筋逐根表随参数实时重绘。
 * 井库（后端持久化 /api/well-library/*）本轮保留接口，待与后端联调后接入。
 */

const PRESETS = [
  { key: 'straight', name: '直线井', L: 2.0, W: 1.5, D: 2.0, nB: 0, Lb: 0, Wb: 0 },
  { key: 'corner', name: '转角井', L: 2.5, W: 2.0, D: 2.0, nB: 1, Lb: 2.0, Wb: 2.0 },
  { key: 'tee', name: '三通井', L: 3.0, W: 2.0, D: 2.0, nB: 1, Lb: 1.8, Wb: 2.0 },
  { key: 'cross', name: '四通井', L: 3.0, W: 2.5, D: 2.0, nB: 2, Lb: 1.8, Wb: 2.0 },
];

const DEFAULT_WELL: WellInput = {
  // 默认值与 tool-well.html 逐字对齐（否则用户打开页面看到的数字会与原生版不同）
  L: 2.0, W: 1.5, D: 2.0, t: 0.24, nB: 0, Lb: 1.8, Wb: 2.0,
  baseT: 0.20, padT: 0.10, topT: 0.15, padOut: 0.1,
  lipW: 0, lipH: 0, conc: false,          // wMat 默认砖砌
  rebarBase: 90, rebarWall: 100, rebarTop: 95,
  count: 1, coverCount: 0, coverL: 1.8, coverW: 0.5, coverT: 0.12,
  coverMainN: 5, coverMainL: 1900, coverDistN: 18, coverDistL: 460, coverEdgeL: 1000,
  shaft: { on: false, sD: 0.70, sH: 0.60, sT: 0.115 },
};

const COVER_REBAR_D = 14;
const rebarUnitKgPerM = (d: number) => 0.00617 * d * d;
const fnum = (v: number) => (+v).toFixed(2);

interface RebarRow { no: string; d: number; len: number; span: number; sp: number; n: number; note: string }

/** A-5 工作井图二 ①~⑧（根数按 @间距 推导，④按内外圈分列，⑤为拉筋）。 */
const A5_PRESET: RebarRow[] = [
  { no: '①', d: 14, len: 6400, span: 3200, sp: 150, n: 22, note: '底板下层+短墙外侧U形通高' },
  { no: '⑥', d: 14, len: 7600, span: 2000, sp: 150, n: 14, note: '底板下层+长墙外侧U形通高' },
  { no: '②', d: 14, len: 1960, span: 3200, sp: 150, n: 22, note: '底板下层短向直筋' },
  { no: '⑦', d: 14, len: 3160, span: 2000, sp: 150, n: 14, note: '底板上层长向直筋' },
  { no: '③', d: 14, len: 2185, span: 1800, sp: 150, n: 26, note: '短墙内侧竖向（2道墙）' },
  { no: '⑧', d: 14, len: 2185, span: 3000, sp: 150, n: 42, note: '长墙内侧竖向（2道墙）' },
  { no: '④内', d: 8, len: 8800, span: 1865, sp: 150, n: 13, note: '水平分布·内圈' },
  { no: '④外', d: 8, len: 10400, span: 1865, sp: 150, n: 13, note: '水平分布·外圈' },
  { no: '⑤', d: 8, len: 210, span: 1865, sp: 450, n: 88, note: '拉筋@450×450' },
  { no: '锚筋', d: 6, len: 180, span: 8800, sp: 300, n: 29, note: '锚固接口角钢，沿墙顶一圈' },
];

const emptyRebar = (): RebarRow => ({ no: '', d: 14, len: 1000, span: 0, sp: 150, n: 1, note: '' });

/** 井库后端基地址（与原生工具页同口径）。 */
const API_BASE = (window as unknown as { __API_BASE__?: string }).__API_BASE__
  || (typeof location !== 'undefined' && location.hostname ? `${location.protocol}//${location.hostname}:8000` : 'http://localhost:8000');

/** 单根重 kg = 根数 × 单根长(mm)/1000 × (d²×0.00617)。 */
const rebarKg = (r: RebarRow) => r.n * (r.len / 1000) * rebarUnitKgPerM(r.d);

function svgDim(x1: number, y1: number, x2: number, y2: number, label: string, focus: string) {
  const hor = Math.abs(y2 - y1) < 0.01;
  const t1 = hor ? `${x1},${y1 - 4} ${x1},${y1 + 4}` : `${x1 - 4},${y1} ${x1 + 4},${y1}`;
  const t2 = hor ? `${x2},${y2 - 4} ${x2},${y2 + 4}` : `${x2 - 4},${y2} ${x2 + 4},${y2}`;
  const mx = (x1 + x2) / 2, my = (y1 + y2) / 2;
  const dx = hor ? 0 : 10, dy = hor ? -6 : 0;
  return `<g class="wv-dim" data-focus="${focus}"><line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}"/>`
    + `<polygon points="${t1}"/><polygon points="${t2}"/><text x="${mx + dx}" y="${my + dy}">${label}</text></g>`;
}

export default function ToolWell() {
  const [p, setP] = useState<WellInput>(DEFAULT_WELL);
  const [prices, setPrices] = useState<number[]>(() => WELL_UNITS.map((u) => u.defaultPrice));
  const [presetOn, setPresetOn] = useState<string | null>(null);
  const [rebarRows, setRebarRows] = useState<RebarRow[]>(() => A5_PRESET.map((r) => ({ ...r })));
  const [saveName, setSaveName] = useState('');
  const [wellName, setWellName] = useState('电缆井');
  const [libMsg, setLibMsg] = useState('');

  const result = useMemo(() => calcWell(p, prices), [p, prices]);
  const shaft = p.shaft.on ? p.shaft : { on: false, sD: 0, sH: 0, sT: 0 };
  const upd = (patch: Partial<WellInput>) => setP((s) => ({ ...s, ...patch }));

  // 钢筋逐根表：主体布筋 + 盖板组（盖板随 c* 参数自动生成）
  const rebarMainTotal = useMemo(() => rebarRows.reduce((s, r) => s + rebarKg(r), 0), [rebarRows]);
  const coverRebarRows = useMemo(() => {
    const w = rebarUnitKgPerM(COVER_REBAR_D);
    return [
      { no: '盖①', lenMm: p.coverMainL, n: p.coverCount * p.coverMainN, note: `块数 ${p.coverCount || 0} × 每块主筋 ${p.coverMainN || 0} 根` },
      { no: '盖②', lenMm: p.coverDistL, n: p.coverCount * p.coverDistN, note: `块数 ${p.coverCount || 0} × 每块分布筋 ${p.coverDistN || 0} 根` },
    ].map((x) => ({ ...x, tw: w, kg: (x.n * (x.lenMm || 0)) / 1000 * w }));
  }, [p.coverMainL, p.coverMainN, p.coverDistL, p.coverDistN, p.coverCount]);
  const coverRebarTotal = coverRebarRows.reduce((s, r) => s + r.kg, 0);
  const count = Math.max(1, p.count || 1);

  const updRebar = (i: number, patch: Partial<RebarRow>) => setRebarRows((rs) => rs.map((r, k) => (k === i ? { ...r, ...patch } : r)));

  /** 保存当前井到后端井库（/api/well-library/save）；失败给可见提示。 */
  const saveWell = async () => {
    const now = new Date();
    const ts = `${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')} ${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}`;
    const matName = p.conc ? '混凝土' : '砖砌';
    const digest = `${matName} ${p.L}×${p.W}×${p.D}` + (p.nB > 0 ? ` ＋支${p.nB}×${p.Lb}×${p.Wb}` : '') + ` · ${count} 座`;
    const rec = {
      id: 'w' + Date.now().toString(36) + Math.random().toString(36).slice(2, 6),
      name: saveName.trim() || `${wellName.trim() || '井'} ${ts}`,
      savedAt: ts,
      params: { ...p, wShaftOn: p.shaft.on },
      prices,
      rebar: rebarRows,
      summary: {
        digest,
        total: result.total,
        rows: WELL_UNITS.map((u, i) => ({ label: result.labels[u.key] ?? u.label, qty: fmt(result.quantities[i], u.dec), unit: u.unit, price: prices[i], sum: fmt(result.sums[i]) })),
      },
    };
    try {
      const listRes = await fetch(`${API_BASE}/api/well-library/list`);
      const listJson = await listRes.json().catch(() => ({}));
      const list = Array.isArray(listJson?.items) ? listJson.items : [];
      list.unshift(rec);
      const r = await fetch(`${API_BASE}/api/well-library/save`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ items: list }),
      });
      const j = await r.json().catch(() => ({}));
      if (!r.ok || j.status !== 'PASS') throw new Error(j?.reason || ('HTTP ' + r.status));
      setLibMsg(`已保存「${rec.name}」`);
      setSaveName('');
    } catch (e) {
      setLibMsg('保存失败：' + (e as Error).message + '（需后端 :8000 运行中）');
    }
  };

  /** 按井参数推导典型配筋（保护层 20mm；U 形筋单根长为近似值，须按图核对）。 */
  const deriveRebar = () => {
    const L = p.L * 1000, W = p.W * 1000, D = p.D * 1000;
    const t = p.t * 1000, baseT = p.baseT * 1000;
    const Lb = p.Lb * 1000;
    const c = 20;
    const leg = baseT + D + p.topT * 1000 - 2 * c;
    const innerP = 2 * (L + W) + p.nB * 2 * Lb;
    const outerP = 2 * (L + 2 * t) + 2 * (W + 2 * t) + p.nB * (2 * Lb + t);
    const cl = 2 * (L + t) + 2 * (W + t) + p.nB * (2 * Lb + t);
    const nAlongL = Math.floor((L + 2 * t) / 150) + 1;
    const nAlongW = Math.floor((W + 2 * t) / 150) + 1;
    const rows: RebarRow[] = [
      { no: '底下短', d: 14, len: W + 2 * t - 2 * c, span: L + 2 * t, sp: 150, n: nAlongL, note: '底板下层·短向直筋' },
      { no: '底下长', d: 14, len: L + 2 * t - 2 * c, span: W + 2 * t, sp: 150, n: nAlongW, note: '底板下层·长向直筋' },
      { no: '底上短', d: 14, len: W + 2 * t - 2 * c, span: L + 2 * t, sp: 150, n: nAlongL, note: '底板上层·短向直筋' },
      { no: '底上长', d: 14, len: L + 2 * t - 2 * c, span: W + 2 * t, sp: 150, n: nAlongW, note: '底板上层·长向直筋' },
    ];
    if (p.conc) {
      rows.push(
        { no: '墙内短', d: 14, len: D + baseT - c, span: W + t, sp: 150, n: (Math.floor((W + t) / 150) + 1) * 2, note: '短墙内侧竖向（2道墙）' },
        { no: '墙内长', d: 14, len: D + baseT - c, span: L + t, sp: 150, n: (Math.floor((L + t) / 150) + 1) * 2, note: '长墙内侧竖向（2道墙）' },
        { no: '外U短', d: 14, len: 2 * leg + (W + 2 * t - 2 * c), span: L + 2 * t, sp: 150, n: nAlongL, note: '※ 底板下层+短墙外侧U形，单根长按图核对' },
        { no: '外U长', d: 14, len: 2 * leg + (L + 2 * t - 2 * c), span: W + 2 * t, sp: 150, n: nAlongW, note: '※ 底板下层+长墙外侧U形，单根长按图核对' },
        { no: '水平内', d: 8, len: innerP, span: D, sp: 150, n: Math.floor(D / 150) + 1, note: '水平分布筋·内圈' },
        { no: '水平外', d: 8, len: outerP, span: D, sp: 150, n: Math.floor(D / 150) + 1, note: '水平分布筋·外圈' },
        { no: '拉筋', d: 8, len: t + 10, span: D, sp: 450, n: Math.round((cl * D) / (450 * 450)), note: '拉筋@450×450' },
      );
    } else {
      rows.push({ no: '备注', d: 8, len: 0, span: 0, sp: 150, n: 0, note: '砖砌井壁无墙筋——墙竖向/水平/拉筋行请按图集另计' });
    }
    setRebarRows(rows);
  };

  // ---------- 平面示意 ----------
  const planSvg = useMemo(() => {
    const { L, W, t } = p; const nB = p.nB; const Lb = p.Lb, Wb = p.Wb;
    const { sD, sH, sT } = shaft;
    const footW = L + 2 * t, footH = W + 2 * t;
    const botD = nB > 0 ? Lb + t : 0, topD = nB === 2 ? Lb + t : 0;
    const contW = footW, contH = footH + botD + topD;
    const s = Math.min(340 / Math.max(contW, 0.1), 250 / Math.max(contH, 0.1), 110);
    const ox = 70, oy = 40 + topD * s;
    const bx = (L - Wb) / 2;
    const VW = 420, VH = 330;
    let g = '';
    g += `<rect class="wv-wall" data-focus="wT" x="${ox}" y="${oy}" width="${footW * s}" height="${footH * s}"/>`;
    if (nB > 0) g += `<rect class="wv-wall" data-focus="wT" x="${ox + bx * s}" y="${oy + (W + t) * s}" width="${(Wb + 2 * t) * s}" height="${(Lb + t) * s}"/>`;
    if (nB === 2) g += `<rect class="wv-wall" data-focus="wT" x="${ox + bx * s}" y="${oy - Lb * s}" width="${(Wb + 2 * t) * s}" height="${(Lb + t) * s}"/>`;
    g += `<rect class="wv-void" x="${ox + t * s}" y="${oy + t * s}" width="${L * s}" height="${W * s}"/>`;
    if (nB > 0) g += `<rect class="wv-void" data-focus="wLb" x="${ox + (t + bx) * s}" y="${oy + (W + t) * s}" width="${Wb * s}" height="${Lb * s}"/>`;
    if (nB === 2) g += `<rect class="wv-void" data-focus="wLb" x="${ox + (t + bx) * s}" y="${oy - Lb * s}" width="${Wb * s}" height="${Lb * s}"/>`;
    if (sD > 0 && sH > 0) {
      const r = (sD / 2 + sT) * s;
      const ccx = ox + (footW * s) / 2, ccy = oy + (footH * s) / 2;
      g += `<circle class="wv-dashed" data-focus="wShaftD" cx="${ccx}" cy="${ccy}" r="${r}"/>`;
      g += `<text class="wv-label" data-focus="wShaftD" x="${ccx}" y="${ccy - r - 5}">φ${fnum(sD)}</text>`;
    }
    const dimY = oy - 12 - (nB === 2 ? Lb * s : 0);
    g += svgDim(ox + t * s, dimY, ox + (L + t) * s, dimY, fnum(L), 'wL');
    g += svgDim(ox - 16, oy + t * s, ox - 16, oy + (W + t) * s, fnum(W), 'wW');
    g += `<text class="wv-label" data-focus="wT" x="${ox + 8}" y="${oy + footH * s - 8}">壁 t=${fnum(t)}</text>`;
    if (nB > 0) {
      g += svgDim(ox + (t + bx) * s, oy + (W + t + Lb) * s + 14, ox + (t + bx + Wb) * s, oy + (W + t + Lb) * s + 14, fnum(Wb), 'wWb');
      g += svgDim(ox + (bx + Wb + 2 * t) * s + 12, oy + (W + t) * s, ox + (bx + Wb + 2 * t) * s + 12, oy + (W + t + Lb) * s, fnum(Lb), 'wLb');
    }
    return `<svg viewBox="0 0 ${VW} ${VH}" role="img" aria-label="井体平面示意">${g}</svg>`;
  }, [p, shaft]);

  // ---------- 剖面示意 ----------
  const sectSvg = useMemo(() => {
    const { W, t, D, baseT, padT, topT, lipW, lipH } = p;
    const { sD, sH, sT } = shaft;
    const rW = p.rebarWall, rT = p.rebarTop;
    const isConc = p.conc;
    const footW = W + 2 * t, padW = footW + 0.2;
    const stackH = topT + 0.015 + D + baseT + padT + sH;
    const s = Math.min(300 / Math.max(footW, 0.1), 240 / Math.max(stackH, 0.1), 110);
    const cx = 210, ox = cx - (footW * s) / 2, pox = cx - (padW * s) / 2;
    const yG = 28 + sH * s;
    const yCoverBot = yG + topT * s;
    const ySeat = yCoverBot + Math.max(0, lipH - topT) * s;
    const yBot = ySeat + D * s;
    const yBaseBot = yBot + baseT * s, yPadBot = yBaseBot + padT * s;
    const covX = ox + lipW * s, covW = footW * s - 2 * lipW * s;
    let g = '';
    if (sD > 0 && sH > 0) g += `<rect class="wv-dashed" data-focus="wShaftH" x="${cx - (sD / 2 + sT) * s}" y="${yG - sH * s}" width="${(sD + 2 * sT) * s}" height="${sH * s}"/>`;
    g += `<rect class="wv-conc" data-focus="wTopT" x="${covX}" y="${yG}" width="${covW}" height="${topT * s}"/>`;
    if (rT > 0 && topT > 0) g += `<line class="wv-rebar" x1="${covX + 3}" y1="${yG + (topT * s) / 2}" x2="${covX + covW - 3}" y2="${yG + (topT * s) / 2}"/>`;
    if (topT > 0 && topT * s > 12) g += `<text class="wv-label" data-focus="wTopT" x="${cx}" y="${yG + (topT * s) / 2 + 3}">盖板 ${fnum(topT)}</text>`;
    const yLipBot = Math.max(ySeat, yCoverBot);
    const sitH = Math.max(0, lipH - topT);
    const wallPoly = (pts: string) => `<polygon class="wv-wall" data-focus="wT" points="${pts}"/>`;
    g += wallPoly(`${ox},${yG} ${ox + lipW * s},${yG} ${ox + lipW * s},${yLipBot} ${ox + t * s},${yLipBot} ${ox + t * s},${yBot} ${ox},${yBot}`);
    g += wallPoly(`${ox + footW * s - lipW * s},${yG} ${ox + footW * s},${yG} ${ox + footW * s},${yBot} ${ox + footW * s - t * s},${yBot} ${ox + footW * s - t * s},${yLipBot} ${ox + footW * s - lipW * s},${yLipBot}`);
    if (sitH > 0) {
      g += `<line class="wv-mortar" x1="${covX}" y1="${yCoverBot + (sitH * s) / 2}" x2="${ox + t * s}" y2="${yCoverBot + (sitH * s) / 2}"/>`;
      g += `<line class="wv-mortar" x1="${ox + footW * s - t * s}" y1="${yCoverBot + (sitH * s) / 2}" x2="${covX + covW}" y2="${yCoverBot + (sitH * s) / 2}"/>`;
    }
    if (isConc && rW > 0) {
      [ox + 2, ox + footW * s - 2].forEach((x) => { g += `<line class="wv-rebar" x1="${x}" y1="${yG + 3}" x2="${x}" y2="${yBot - 3}"/>`; });
      [ox + t * s - 2, ox + footW * s - t * s + 2].forEach((x) => { g += `<line class="wv-rebar" x1="${x}" y1="${yLipBot + 3}" x2="${x}" y2="${yBot - 3}"/>`; });
    }
    if (D * s > 18) g += `<text class="wv-label" data-focus="wT" x="${ox + t * s + 4}" y="${(yLipBot + yBot) / 2}" text-anchor="start">井壁</text>`;
    if (lipW > 0 && lipH > 0) g += `<text class="wv-label" data-focus="wLipW" x="${ox + (lipW * s) / 2}" y="${(yG + yLipBot) / 2}">井座</text>`;
    g += svgDim(ox + footW * s + 14, yLipBot, ox + footW * s + 14, yBot, fnum(D), 'wD');
    if (lipH > 0) g += svgDim(ox - 16, yG, ox - 16, yLipBot, fnum(lipH), 'wLipH');
    g += svgDim(pox - 12, yBot, pox - 12, yBaseBot, fnum(baseT), 'wBaseT');
    g += svgDim(pox - 12, yBaseBot, pox - 12, yPadBot, fnum(padT), 'wPadT');
    if (padT > 0) {
      g += `<rect class="wv-pad" data-focus="wPadT" x="${pox}" y="${yBaseBot}" width="${padW * s}" height="${padT * s}"/>`;
      if (padT * s > 12) g += `<text class="wv-label" data-focus="wPadT" x="${cx}" y="${yBaseBot + (padT * s) / 2 + 3}">垫层 ${fnum(padT)}</text>`;
    }
    if (baseT > 0) {
      g += `<rect class="wv-conc" data-focus="wBaseT" x="${ox}" y="${yBot}" width="${footW * s}" height="${baseT * s}"/>`;
      if (baseT * s > 14) g += `<text class="wv-label" data-focus="wBaseT" x="${cx}" y="${yBot + (baseT * s) / 2 + 3}">底板 ${fnum(baseT)}</text>`;
    }
    return `<svg viewBox="0 0 420 ${yPadBot + 26}" role="img" aria-label="井体剖面示意">${g}</svg>`;
  }, [p, shaft]);

  const numF = (id: string, label: string, key: keyof WellInput, step = 0.05, tip?: string) => (
    <label className="field" data-tip={tip} key={id}>
      <span className="field-label">{label}</span>
      <input className="tabular" type="number" step={step} value={p[key] as number}
        onChange={(e) => upd({ [key]: Number(e.target.value) } as Partial<WellInput>)} />
    </label>
  );

  return (
    <ToolShell id="tool-well" en="Manhole" title="电缆井工程量速算" subtitle="垫层、底板、井壁（砖砌/混凝土）、顶板、井筒、钢筋、模板、抹面、井盖、爬梯逐项工程量与合价">
      <div className="chip-row" role="group" aria-label="井型预设">
        {PRESETS.map((pr) => (
          <button key={pr.key} type="button" className={`chip${presetOn === pr.key ? ' on' : ''}`}
            onClick={() => { setPresetOn(pr.key); upd({ L: pr.L, W: pr.W, D: pr.D, nB: pr.nB, Lb: pr.Lb, Wb: pr.Wb }); }}>
            {pr.name}
          </button>
        ))}
        <label className="field" style={{ minWidth: 150 }}>
          <span className="field-label">井位 / 编号</span>
          <input type="text" id="wName" value={wellName} placeholder="如 J1" onChange={(e) => setWellName(e.target.value)} />
        </label>
      </div>

      <div className="tool-grid" style={{ marginBottom: 12 }}>
        <div className="tool-subhead">主井室净空与壁厚</div>
        {numF('wL', '净长 L (m)', 'L')}
        {numF('wW', '净宽 W (m)', 'W')}
        {numF('wD', '净深 D (m)', 'D')}
        {numF('wT', '壁厚 t (m)', 't')}
        <label className="field">
          <span className="field-label">井壁材料</span>
          <select id="wMat" value={p.conc ? 'conc' : 'brick'} onChange={(e) => {
            const conc = e.target.value === 'conc';
            setP((s) => ({ ...s, conc }));
            // 井壁单价随材料切换（砖砌 420 / 混凝土 650）
            setPrices((ps) => ps.map((v, i) => (WELL_UNITS[i].key === 'wall' ? (conc ? 650 : 420) : v)));
          }}>
            <option value="conc">混凝土 C30</option><option value="brick">砖砌 M10</option>
          </select>
        </label>

        <div className="tool-subhead">支井室</div>
        <label className="field">
          <span className="field-label">支室数</span>
          <select id="wBrN" value={p.nB} onChange={(e) => upd({ nB: Number(e.target.value) })}>
            <option value={0}>0（直线井）</option><option value={1}>1（转角/三通）</option><option value={2}>2（四通）</option>
          </select>
        </label>
        {numF('wLb', '支室净长 Lb (m)', 'Lb')}
        {numF('wWb', '支室净宽 Wb (m)', 'Wb')}

        <div className="tool-subhead">板厚与井座</div>
        {numF('wBaseT', '底板厚 (m)', 'baseT')}
        {numF('wPadT', '垫层厚 (m)', 'padT')}
        {numF('wTopT', '顶板厚 (m)', 'topT')}
        {numF('wPadOut', '垫层外挑 (m)', 'padOut')}
        {numF('wLipW', '井座宽 (m)', 'lipW')}
        {numF('wLipH', '井座高 (m)', 'lipH')}
        {numF('wCount', '井数 (座)', 'count', 1)}

        <div className="tool-subhead">井筒（选做）</div>
        <label className="field">
          <span className="field-label">计入井筒</span>
          <input type="checkbox" id="wShaftOn" checked={p.shaft.on} onChange={(e) => upd({ shaft: { ...p.shaft, on: e.target.checked } })} />
        </label>
        {([['wShaftD', '井筒内径 (m)', 'sD'], ['wShaftH', '井筒高 (m)', 'sH'], ['wShaftT', '井筒壁厚 (m)', 'sT']] as const).map(([id, label, key]) => (
          <label className="field" key={id}>
            <span className="field-label">{label}</span>
            <input className="tabular" type="number" step={0.05} value={p.shaft[key]} disabled={!p.shaft.on}
              onChange={(e) => upd({ shaft: { ...p.shaft, [key]: Number(e.target.value) } })} />
          </label>
        ))}

        <div className="tool-subhead">含钢量（kg/m³，含钢量法）</div>
        {numF('wRebarBase', '底板含钢量', 'rebarBase', 1)}
        {numF('wRebarWall', '井壁含钢量', 'rebarWall', 1)}
        {numF('wRebarTop', '顶板含钢量', 'rebarTop', 1)}

        <div className="tool-subhead">预制盖板</div>
        {numF('cCount', '块数', 'coverCount', 1)}
        {numF('cLen', '板长 (m)', 'coverL')}
        {numF('cW', '板宽 (m)', 'coverW')}
        {numF('cT', '板厚 (m)', 'coverT')}
        {numF('cMainN', '每块主筋根数', 'coverMainN', 1)}
        {numF('cMainL', '主筋单根长 (mm)', 'coverMainL', 10)}
        {numF('cDistN', '每块分布筋根数', 'coverDistN', 1)}
        {numF('cDistL', '分布筋单根长 (mm)', 'coverDistL', 10)}
        {numF('cEdgeL', '包边角钢 (mm/块)', 'coverEdgeL', 10)}
      </div>

      <div className="well-viz-head">
        <span className="well-viz-title">井体示意（非施工图，比例自适应，随参数实时重绘）</span>
        <span className="hint" style={{ margin: 0 }}>点击图元或尺寸标注可定位对应参数</span>
      </div>
      <div className="well-viz" style={{ gridTemplateColumns: '1fr 1fr' }}>
        <div className="well-viz-pane">
          <div className="well-viz-title">平面</div>
          <div className="well-viz-svg" dangerouslySetInnerHTML={{ __html: planSvg }} />
        </div>
        <div className="well-viz-pane">
          <div className="well-viz-title">剖面</div>
          <div className="well-viz-svg" dangerouslySetInnerHTML={{ __html: sectSvg }} />
        </div>
      </div>

      <div className="tool-table-wrap">
        <table className="tool-table" id="wellRows">
          <thead>
            <tr><th>构件 / 项目</th><th className="num">工程量</th><th>单位</th><th>计算式</th><th className="num">参考单价 (元)</th><th className="num">合价 (元)</th></tr>
          </thead>
          <tbody>
            {WELL_UNITS.map((u, i) => {
              const label = result.labels[u.key] ?? u.label;
              return (
                <tr key={u.key}>
                  <td>{label}</td>
                  <td className="num">{fmt(result.quantities[i], u.dec)}</td>
                  <td>{u.unit}</td>
                  <td className="fx">—</td>
                  <td>
                    <div className="price-cell">
                      <input className="num" type="number" min={0} step={u.unit === 'kg' ? 0.1 : 1} value={prices[i]}
                        onChange={(e) => setPrices((ps) => ps.map((v, k) => (k === i ? Number(e.target.value) : v)))} />
                      <span className="unit-suffix">元/{u.unit}</span>
                    </div>
                  </td>
                  <td className="num">{fmt(result.sums[i])}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <ResultStrip items={[{ label: '合计', value: <>¥ {fmt(result.total)}</> }]} />

      {/* ===== 钢筋逐根表（按图实算，与含钢量法互对账） ===== */}
      <div className="well-lib-head" style={{ marginTop: 14 }}>
        <span className="card-title"><span className="title-dot" />钢筋逐根表（按图实算）</span>
      </div>
      <details className="spec">
        <summary>口径说明</summary>
        <div className="hint">主体布筋：填直径/单根长/布置范围/间距 → 根数自动推导（可手改）；重量按 d²×0.00617 自动计，与含钢量法互相对账。盖板钢筋：随「预制盖板」参数自动生成两行，与主体布筋分组分列。</div>
      </details>
      <div className="tool-table-wrap">
        <table className="tool-table" id="rebarTable">
          <thead>
            <tr>
              <th style={{ width: 80 }}>编号</th><th style={{ width: 90 }}>直径 (mm)</th><th style={{ width: 110 }}>单根长 (mm)</th>
              <th className="num" style={{ width: 90 }}>理论重 (kg/m)</th><th style={{ width: 110 }}>布置范围 (mm)</th>
              <th style={{ width: 90 }}>间距 (mm)</th><th style={{ width: 80 }}>根数</th><th className="num">重量 (kg)</th>
              <th style={{ minWidth: 150 }}>备注（图面依据）</th><th />
            </tr>
          </thead>
          <tbody id="rebarRows">
            {rebarRows.map((r, i) => (
              <tr key={i}>
                <td><input type="text" value={r.no} placeholder="①" onChange={(e) => updRebar(i, { no: e.target.value })} /></td>
                <td>
                  <select value={r.d} onChange={(e) => updRebar(i, { d: Number(e.target.value) })}>
                    {[6, 8, 10, 12, 14, 16, 18, 20, 22, 25].map((d) => <option key={d} value={d}>{d}</option>)}
                  </select>
                </td>
                <td><input className="num" type="number" min={0} step={10} value={r.len} onChange={(e) => updRebar(i, { len: Number(e.target.value) })} /></td>
                <td className="num row-tw">{fmt(rebarUnitKgPerM(r.d), 3)}</td>
                <td><input className="num" type="number" min={0} step={50} value={r.span} onChange={(e) => {
                  const span = Number(e.target.value);
                  updRebar(i, { span, n: span > 0 && r.sp > 0 ? Math.floor(span / r.sp) + 1 : r.n });
                }} /></td>
                <td><input className="num" type="number" min={0} step={10} value={r.sp} onChange={(e) => {
                  const sp = Number(e.target.value);
                  updRebar(i, { sp, n: r.span > 0 && sp > 0 ? Math.floor(r.span / sp) + 1 : r.n });
                }} /></td>
                <td><input className="num" type="number" min={0} step={1} value={r.n} onChange={(e) => updRebar(i, { n: Number(e.target.value) })} /></td>
                <td className="num row-kg">{fmt(rebarKg(r), 1)}</td>
                <td><input type="text" value={r.note} onChange={(e) => updRebar(i, { note: e.target.value })} /></td>
                <td><button type="button" className="row-del" title="删除本行" onClick={() => setRebarRows((rs) => rs.filter((_, k) => k !== i))}>×</button></td>
              </tr>
            ))}
          </tbody>
          <tbody id="rebarCoverRows">
            <tr className="rebar-grp"><td colSpan={10}>盖板钢筋（预制盖板，随上方参数自动生成 · φ{COVER_REBAR_D}）</td></tr>
            {coverRebarRows.map((r) => (
              <tr className="rebar-cov" key={r.no}>
                <td>{r.no}</td><td>φ{COVER_REBAR_D}</td><td className="num">{r.lenMm || 0}</td>
                <td className="num">{fmt(r.tw, 3)}</td><td className="num off">—</td><td className="num off">—</td>
                <td className="num">{r.n || 0}</td><td className="num row-kg">{fmt(r.kg, 1)}</td>
                <td className="cov-note">{r.note}</td><td />
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr>
              <td colSpan={7}>主体布筋·单座合计</td>
              <td className="num">{fmt(rebarMainTotal, 1)} kg</td>
              <td className="num" style={{ color: 'var(--text-tertiary)', whiteSpace: 'normal' }}>
                {result.steelEstKg > 0 && `含钢量法 ${fmt(result.steelEstKg, 0)} kg vs 主体按图 ${fmt(rebarMainTotal, 0)} kg（${rebarMainTotal - result.steelEstKg >= 0 ? '+' : ''}${fmt(rebarMainTotal - result.steelEstKg, 0)} / ${Math.round(((rebarMainTotal - result.steelEstKg) / result.steelEstKg) * 100)}%）· 未含盖板钢筋 ${fmt(coverRebarTotal, 0)} kg${Math.abs((rebarMainTotal - result.steelEstKg) / result.steelEstKg) >= 0.15 ? ' ※ 差异较大，请以钢筋逐根表为准' : ''}`}
              </td>
              <td />
            </tr>
            <tr><td colSpan={7}>盖板钢筋·单座合计</td><td className="num">{fmt(coverRebarTotal, 1)} kg</td><td /><td /></tr>
            <tr><td colSpan={7}>× 座数合计（主体＋盖板）</td><td className="num">{fmt((rebarMainTotal + coverRebarTotal) * count, 1)} kg</td><td /><td /></tr>
          </tfoot>
        </table>
      </div>
      <div className="action-row">
        <button type="button" className="btn-secondary" onClick={() => setRebarRows((rs) => [...rs, emptyRebar()])}>＋ 加一根</button>
        <button type="button" className="btn-secondary" onClick={() => setRebarRows(A5_PRESET.map((r) => ({ ...r })))}>载入示例：A-5 工作井 ①~⑧（主体布筋）</button>
        <button type="button" className="btn-secondary" onClick={deriveRebar}>按井参数推导典型配筋</button>
        <span className="hint">根数 = 布置范围 ÷ 间距 + 1（自动），可手改；「按井参数推导」按典型配筋模式生成（保护层按 20mm，U 形筋单根长为近似值，须按图纸钢筋表核对）。</span>
      </div>

      <div className="action-row">
        <details className="spec">
          <summary>口径说明</summary>
          <div className="hint">
            井体 = 主井室（净空 L×W×D）＋ n 个支井室（净空 Lb×Wb，同深同壁厚）。中心线净长 clNet = 2(L+t)+2(W+t)+nB(2Lb+t)；
            井壁 V = clNet×D×t（＋井座体积）；底板/顶板面积 = (L+2t)(W+2t)＋nB(Wb+2t)(Lb+t/2)；模板含井壁内＋外、底板外侧、井座外侧、现浇顶板底；
            钢筋按含钢量法估算（kg = 构件体积 × 含钢量），砖砌井壁不计井壁筋。钢筋逐根表按图实算，可与含钢量法对账。
          </div>
        </details>
        <button type="button" className="btn-secondary" onClick={() => {
          const lines = ['电缆井工程量速算', ['构件/项目', '工程量', '单位', '参考单价(元)', '合价(元)'].join('\t')];
          WELL_UNITS.forEach((u, i) => {
            lines.push([result.labels[u.key] ?? u.label, fmt(result.quantities[i], u.dec), u.unit, prices[i], fmt(result.sums[i])].join('\t'));
          });
          lines.push(['合计', '', '', '', fmt(result.total)].join('\t'));
          navigator.clipboard?.writeText(lines.join('\n')).catch(() => { /* ignore */ });
        }}>复制工程量表</button>
      </div>

      {/* ===== 已存井库（后端持久化） ===== */}
      <div className="well-lib">
        <div className="well-lib-head">
          <span className="card-title"><span className="title-dot" />已存井库</span>
          <span className="hint">保存在本机后端（outputs/projects/&lt;user&gt;/well-library.json）；点井名可看当时算出的完整工程量。</span>
        </div>
        <div className="well-lib-save">
          <input type="text" placeholder="井名（留空则取「井位/编号」+ 保存时间）" value={saveName} onChange={(e) => setSaveName(e.target.value)} />
          <button type="button" className="btn-primary" onClick={saveWell}>保存当前井</button>
        </div>
        {libMsg && <div className="hint" style={{ margin: '4px 0 0' }}>{libMsg}</div>}
      </div>
    </ToolShell>
  );
}

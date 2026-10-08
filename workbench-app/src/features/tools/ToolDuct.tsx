import { useMemo, useState } from 'react';
import { calcDuct, type DuctInput } from './toolsCalc';
import { ToolShell, NumField, ResultStrip, fmt } from './ToolShell';

/**
 * 排管断面布置（P2 前端整合：由 frontend/tool-duct.html + tool-duct.js 迁入 React）
 * 计算走 toolsCalc.calcDuct（纯函数，有判据）；断面 SVG 由参数实时重绘。
 */

const DEFAULTS: DuctInput = {
  circuits: 2, perCircuit: 3, spare: 4, layout: 'auto', rows: 2, cols: 4,
  D: 160, gap: 20, cover: 50, work: 300,
};

/** 尺寸标注（横/竖自适应），与原实现逐字一致。 */
function svgDim(x1: number, y1: number, x2: number, y2: number, label: string, focus: string) {
  const hor = Math.abs(y2 - y1) < 0.01;
  const t1 = hor ? `${x1},${y1 - 4} ${x1},${y1 + 4}` : `${x1 - 4},${y1} ${x1 + 4},${y1}`;
  const t2 = hor ? `${x2},${y2 - 4} ${x2},${y2 + 4}` : `${x2 - 4},${y2} ${x2 + 4},${y2}`;
  const mx = (x1 + x2) / 2, my = (y1 + y2) / 2;
  const dx = hor ? 0 : 10, dy = hor ? -6 : 0;
  return `<g class="wv-dim" data-focus="${focus}">`
    + `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}"/>`
    + `<polygon points="${t1}"/><polygon points="${t2}"/>`
    + `<text x="${mx + dx}" y="${my + dy}">${label}</text></g>`;
}

export default function ToolDuct() {
  const [p, setP] = useState<DuctInput>(DEFAULTS);
  // 备用孔被手动改过后不再随回路数联动（与原实现 spareTouched 等价）
  const [spareTouched, setSpareTouched] = useState(false);
  const r = useMemo(() => calcDuct(p), [p]);
  const upd = (k: keyof DuctInput, v: number | string) => setP((s) => ({ ...s, [k]: v }));

  // 断面 SVG（照搬原生 renderSvg）
  const svg = useMemo(() => {
    const W = Math.max(r.W, 1), H = Math.max(r.H, 1);
    const s = Math.min(340 / W, 220 / H);
    const ox = 60, oy = 44;
    const VW = 440, VH = Math.ceil(oy * 2 + H * s) + 8;
    const ex = ox, ey = oy;
    const dx0 = ex + p.cover * s, dy0 = ey + p.cover * s;
    let g = '';
    g += `<rect class="wv-conc" data-focus="dCover" x="${ex}" y="${ey}" width="${W * s}" height="${H * s}"/>`;
    let idx = 0;
    for (let ri = 0; ri < r.rows; ri++) {
      for (let ci = 0; ci < r.cols; ci++) {
        const cx = dx0 + (ci * (p.D + p.gap) + p.D / 2) * s;
        const cy = dy0 + (ri * (p.D + p.gap) + p.D / 2) * s;
        const cls = idx < r.used ? 'dv-duct' : 'dv-spare';
        g += `<circle class="${cls}" cx="${cx.toFixed(1)}" cy="${cy.toFixed(1)}" r="${((p.D / 2) * s).toFixed(1)}"/>`;
        idx++;
      }
    }
    g += svgDim(ex, ey - 14, ex + W * s, ey - 14, `${Math.round(W)}`, 'dCover');
    g += svgDim(ex - 14, ey, ex - 14, ey + H * s, `${Math.round(H)}`, 'dCover');
    g += `<text class="wv-label" x="${ex + (W * s) / 2}" y="${ey + H * s + 18}">备用 ${r.spareShown} 孔（虚线）</text>`;
    return `<svg viewBox="0 0 ${VW} ${VH}" role="img" aria-label="排管断面示意">${g}</svg>`;
  }, [r, p.D, p.gap, p.cover]);

  return (
    <ToolShell id="tool-duct" en="Duct" title="排管断面布置" subtitle="孔数 → 标准排列 → 包封尺寸 → 沟底宽建议，可一键送入土方工具">
      <div className="tool-grid" style={{ marginBottom: 12 }}>
        <div className="tool-subhead">断面孔数</div>
        <NumField id="dCircuits" label="回路数 n" value={p.circuits} onChange={(v) => {
          // 备用孔未被手动改过时跟随 n+2（原生行为：spareTouched 标记）
          setP((s) => ({ ...s, circuits: v, spare: spareTouched ? s.spare : Math.max(1, Math.round(v)) + 2 }));
        }} tip="需要敷设的电缆回路数" />
        <NumField id="dPerCircuit" label="每回路孔数" value={p.perCircuit} onChange={(v) => upd('perCircuit', v)} tip="10kV 三相分管敷设一般取 3" />
        <NumField id="dSpare" label="备用孔" value={p.spare} onChange={(v) => { setSpareTouched(true); upd('spare', v); }} min={0} tip="默认 n+2，可手动改，改后不再随回路数联动" />
        <label className="field">
          <span className="field-label">排列方式</span>
          <select id="dLayout" value={p.layout} onChange={(e) => upd('layout', e.target.value as DuctInput['layout'])}>
            <option value="auto">自动</option>
            <option value="manual">手动</option>
          </select>
        </label>
        {p.layout === 'manual' && (
          <>
            <NumField id="dRows" label="行数（层数）" value={p.rows} onChange={(v) => upd('rows', v)} />
            <NumField id="dCols" label="列数" value={p.cols} onChange={(v) => upd('cols', v)} />
          </>
        )}

        <div className="tool-subhead">管材</div>
        <NumField id="dD" label="管外径 D" value={p.D} onChange={(v) => upd('D', v)} suffix="mm" tip="10kV 保护管常用 CPVC/MPP 外径约 160mm" />

        <div className="tool-subhead">构造尺寸（可按图集调整）</div>
        <NumField id="dGap" label="管净距" value={p.gap} onChange={(v) => upd('gap', v)} suffix="mm" tip="规范要求不小于 20mm" />
        <NumField id="dCover" label="包封保护层" value={p.cover} onChange={(v) => upd('cover', v)} suffix="mm" tip="常见做法 50mm" />
        <NumField id="dWork" label="每侧工作面" value={p.work} onChange={(v) => upd('work', v)} suffix="mm" step={10} tip="常用 300mm" />
      </div>

      {r.note && (
        <p className="hint" style={{ color: 'var(--ui-black)', boxShadow: 'inset 4px 0 0 var(--ui-orange)', paddingLeft: 8 }}>{r.note}</p>
      )}

      <div className="well-viz-head">
        <span className="well-viz-title">断面示意（非施工图，比例自适应，随参数实时重绘）</span>
        <span className="hint" style={{ margin: 0 }}>虚线孔为备用孔；点击尺寸标注可定位对应参数</span>
      </div>
      <div className="well-viz" style={{ gridTemplateColumns: '1fr' }}>
        <div className="well-viz-pane">
          <div className="well-viz-title">排管断面</div>
          <div className="well-viz-svg" dangerouslySetInnerHTML={{ __html: svg }} />
        </div>
      </div>

      <ResultStrip items={[
        { label: '排列（行×列 / 总孔数）', value: `${r.rows}×${r.cols} / ${r.cap} 孔` },
        { label: '管束宽 × 高', value: <>{Math.round(r.Wd)}×{Math.round(r.Hd)} mm</> },
        { label: '包封宽 × 高', value: <>{Math.round(r.W)}×{Math.round(r.H)} mm</> },
        { label: '包封混凝土', value: <>{fmt(r.conc, 3)} m³/m</> },
        { label: '沟底宽建议 a', value: <>{fmt(r.a, 2)} m</> },
      ]} />

      <div className="action-row">
        <details className="spec">
          <summary>口径说明</summary>
          <div className="hint">
            标准排列引自深圳地标 T/SDL 4-2022《电力电缆通道设计规范》：2孔单层、4孔2×2、6孔2×3、8孔2×4、12孔3×4、16孔4×4、24孔4×6；
            20kV 及以下层数不宜超过四层。孔数不足取大一档，超出 24 孔时按 4 层向上取整列数。并列管净距规范要求不小于 20mm。
            包封混凝土按（包封外包络面积 − 管孔面积）/延米估算；沟底宽建议 = 包封宽 + 2 × 每侧工作面。示意图非施工图。
          </div>
        </details>
        <button type="button" className="btn-secondary" onClick={() => {
          try { localStorage.setItem('bidpricing.handoff.v1', JSON.stringify({ kind: 'duct', at: Date.now(), payload: { width: +r.a.toFixed(2), label: `排管断面 ${r.rows}×${r.cols}（${r.cap}孔）` } })); } catch { /* 隐私模式忽略 */ }
        }}>→ 送入土方工具</button>
        <button type="button" className="btn-secondary" onClick={() => {
          const tsv = [
            '排管断面布置',
            ['回路数', p.circuits, '每回路孔数', p.perCircuit, '备用孔', p.spare, '排列', `${r.rows}×${r.cols}`,
              '管外径(mm)', p.D, '管净距(mm)', p.gap, '包封保护层(mm)', p.cover, '每侧工作面(mm)', p.work].join('\t'),
            ['总孔数', '管束宽(mm)', '管束高(mm)', '包封宽(mm)', '包封高(mm)', '包封混凝土(m³/m)', '沟底宽建议a(m)'].join('\t'),
            [r.cap, Math.round(r.Wd), Math.round(r.Hd), Math.round(r.W), Math.round(r.H), r.conc.toFixed(3), r.a.toFixed(2)].join('\t'),
          ].join('\n');
          navigator.clipboard?.writeText(tsv).catch(() => { /* 剪贴板不可用 */ });
        }}>复制结果</button>
      </div>
    </ToolShell>
  );
}

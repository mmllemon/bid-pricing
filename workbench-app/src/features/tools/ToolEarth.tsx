import { useState } from 'react';
import { calcEarth, EARTH_RULE_PRESETS, type EarthRow, type EarthRule } from './toolsCalc';
import { ToolShell, NumField, ResultStrip, fmt } from './ToolShell';

/**
 * 挖方与回填速算（P2 前端整合：由 frontend/tool-earth.html + tool-earth.js 迁入 React）
 * 计算走 toolsCalc.calcEarth（纯函数，有判据）。跨工具交接「排管断面 → 沟底宽」保留。
 */

const RULE_HINT: Record<string, string> = {
  arch: '系数与起点可直接修改，按你实际所套定额核对；未达起点深度按直槽。',
  power: '※ 电力定额各版本/各省差异大，当前为占位值——请按所套定额逐格核对修改。',
  muni: '※ 市政定额各省市差异大，当前为占位值——请按所套定额逐格核对修改。',
};

const emptyRow = (init: Partial<EarthRow> = {}): EarthRow => ({
  len: 0, a: 0, h: 0, soil: 0, mode: 'spec', mCustom: 0.5, deduct: 0, ...init,
});

export default function ToolEarth() {
  const [prices, setPrices] = useState({ dig: 48, back: 38, haul: 42 });
  const [loose, setLoose] = useState(1.30);
  const [ruleSet, setRuleSet] = useState('arch');
  const [rules, setRules] = useState<EarthRule[]>(EARTH_RULE_PRESETS.arch);
  const [rows, setRows] = useState<EarthRow[]>([emptyRow(), emptyRow()]);
  const [handoff, setHandoff] = useState(() => {
    // 读取排管页送来的交接槽（toolHandoff 协议：kind='duct'）
    try {
      const raw = localStorage.getItem('bidpricing.handoff.v1');
      if (!raw) return null;
      const o = JSON.parse(raw);
      if (!o || o.kind !== 'duct') return null;
      if (typeof o.at === 'number' && Date.now() - o.at > 24 * 3600 * 1000) { localStorage.removeItem('bidpricing.handoff.v1'); return null; }
      const w = parseFloat(o.payload?.width);
      return isFinite(w) && w > 0 ? { width: w, label: o.payload?.label || '' } : null;
    } catch { return null; }
  });

  const { rows: out, totals } = calcEarth(rows, rules, prices, loose);
  const updRow = (i: number, patch: Partial<EarthRow>) => setRows((rs) => rs.map((r, k) => (k === i ? { ...r, ...patch } : r)));

  const clearHandoff = () => { try { localStorage.removeItem('bidpricing.handoff.v1'); } catch { /* ignore */ } setHandoff(null); };

  return (
    <ToolShell id="tool-earth" title="挖方与回填速算" subtitle="挖方 V = L × (a + m·h) × h（梯形断面）；回填 = 挖方 − 管位占置">
      <div className="tool-grid" style={{ marginBottom: 12 }}>
        <NumField id="eDig" label="挖方单价" value={prices.dig} onChange={(v) => setPrices((s) => ({ ...s, dig: v }))} step={0.5} suffix="元/m³" tip="全线统一的人工挖沟槽综合单价" />
        <NumField id="eBack" label="回填夯实单价" value={prices.back} onChange={(v) => setPrices((s) => ({ ...s, back: v }))} step={0.5} suffix="元/m³" />
        <NumField id="eHaul" label="余方外运/借方" value={prices.haul} onChange={(v) => setPrices((s) => ({ ...s, haul: v }))} step={0.5} suffix="元/m³" tip="余方外运与借方内运按同一运费口径估算" />
        <NumField id="eLoose" label="虚方换算系数" value={loose} onChange={setLoose} step={0.01} min={1} tip="一、二类土约 1.30；余方外运按虚方计，借方按天然方计" />
      </div>

      <div className="chip-row" role="group" aria-label="放坡口径">
        <label className="field" style={{ minWidth: 210 }}>
          <span className="field-label">放坡口径（规则集）</span>
          <select id="eRuleSet" value={ruleSet} onChange={(e) => {
            const key = e.target.value;
            if (key !== 'arch' && key !== ruleSet) {
              const ok = window.confirm('电力/市政定额各省市差异大，当前载入的是建筑定额占位值——必须按你实际所套定额逐格核对修改。\n\n确定要切换吗？');
              if (!ok) return;
            }
            setRuleSet(key);
            setRules((EARTH_RULE_PRESETS[key] ?? EARTH_RULE_PRESETS.arch).map((r) => ({ ...r })));
          }}>
            <option value="arch">建筑定额（全国统一定额口径）</option>
            <option value="power">电力定额（占位值，请核对）</option>
            <option value="muni">市政定额（占位值，请核对）</option>
          </select>
        </label>
        <div className="tool-table-wrap" style={{ flex: '1 1 100%', minWidth: 0 }}>
          <table className="tool-table" id="ruleTable" style={{ minWidth: 420 }}>
            <thead>
              <tr><th>土壤类别</th><th style={{ width: 110 }}>放坡系数 1:m</th><th style={{ width: 130 }}>放坡起点深度 (m)</th></tr>
            </thead>
            <tbody>
              {rules.map((r, i) => (
                <tr key={i}>
                  <td>{['一、二类土', '三类土', '四类土'][i]}</td>
                  <td><input className="num" type="number" min={0} max={2} step={0.01} value={r.m}
                    onChange={(e) => setRules((rs) => rs.map((x, k) => (k === i ? { ...x, m: Number(e.target.value) } : x)))} /></td>
                  <td><input className="num" type="number" min={0} step={0.1} value={r.start}
                    onChange={(e) => setRules((rs) => rs.map((x, k) => (k === i ? { ...x, start: Number(e.target.value) } : x)))} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <span className="hint" id="eRuleHint">{RULE_HINT[ruleSet] ?? RULE_HINT.arch}</span>
      </div>

      {handoff && (
        <div className="handoff-banner" id="ductBanner">
          <span>⇄ 排管工具推荐沟底宽 <strong>{handoff.width.toFixed(2)} m</strong>（{handoff.label}）</span>
          <button type="button" className="btn-secondary" onClick={() => {
            setRows((rs) => [...rs, emptyRow({ a: Number(handoff.width.toFixed(2)) })]);
            clearHandoff();
          }}>应用：新建一段并填入沟底宽</button>
          <button type="button" className="btn-secondary" onClick={clearHandoff}>忽略</button>
        </div>
      )}

      <div className="tool-table-wrap">
        <table className="tool-table" id="earthTable">
          <thead>
            <tr>
              <th style={{ minWidth: 110 }}>段名 / 桩号</th>
              <th>长度 L (m)</th><th>沟底宽 a (m)</th><th>挖深 h (m)</th>
              <th>土壤类别</th><th>放坡方式</th><th style={{ width: 76 }}>自定 m</th>
              <th>管位占置 (m³/m)</th>
              <th className="num">有效 m</th><th className="num">挖方 (m³)</th><th className="num">回填 (m³)</th><th className="num">余方 (m³)</th>
              <th />
            </tr>
          </thead>
          <tbody id="earthRows">
            {rows.map((row, i) => {
              const o = out[i];
              return (
                <tr key={i}>
                  <td><input type="text" placeholder="如 1# 路 K0+000" value={String(row.name ?? '')} onChange={(e) => updRow(i, { name: e.target.value })} /></td>
                  <td><input className="num" type="number" min={0} step={0.1} value={row.len} onChange={(e) => updRow(i, { len: Number(e.target.value) })} /></td>
                  <td><input className="num" type="number" min={0} step={0.05} value={row.a} onChange={(e) => updRow(i, { a: Number(e.target.value) })} /></td>
                  <td><input className="num" type="number" min={0} step={0.05} value={row.h} onChange={(e) => updRow(i, { h: Number(e.target.value) })} /></td>
                  <td>
                    <select value={row.soil} onChange={(e) => updRow(i, { soil: Number(e.target.value) })}>
                      <option value={0}>一、二类土</option><option value={1}>三类土</option><option value={2}>四类土</option>
                    </select>
                  </td>
                  <td>
                    <select value={row.mode} onChange={(e) => updRow(i, { mode: e.target.value as EarthRow['mode'] })}>
                      <option value="spec">按定额放坡</option><option value="none">直槽不放坡</option><option value="custom">自定系数</option>
                    </select>
                  </td>
                  <td><input className="num" type="number" min={0} step={0.01} value={row.mCustom} disabled={row.mode !== 'custom'} onChange={(e) => updRow(i, { mCustom: Number(e.target.value) })} /></td>
                  <td><input className="num" type="number" min={0} step={0.01} value={row.deduct} onChange={(e) => updRow(i, { deduct: Number(e.target.value) })} /></td>
                  <td className="num eff-m">{o.mEff.toFixed(2)} {o.note && <span className="off">{o.note}</span>}</td>
                  <td className="num v-dig">{fmt(o.dig, 1)}</td>
                  <td className="num v-back">{fmt(o.back, 1)}</td>
                  <td className="num v-surplus">{fmt(o.surplus, 1)}</td>
                  <td><button type="button" className="row-del" title="删除本段" onClick={() => setRows((rs) => rs.filter((_, k) => k !== i))}>×</button></td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <ResultStrip items={[
        { label: '总挖方', value: <>{fmt(totals.dig, 1)} m³</> },
        { label: '总回填（夯实）', value: <>{fmt(totals.back, 1)} m³</> },
        { label: '余方（+外运 / −借方，天然方）', value: <>{fmt(totals.surplus, 1)} m³</> },
        { label: '余方外运（虚方）', value: <>{fmt(totals.surplusLoose, 1)} m³</> },
        { label: '估算合价', value: <>¥ {fmt(totals.cost)}</> },
      ]} />

      <div className="action-row">
        <details className="spec">
          <summary>口径说明</summary>
          <div className="hint">
            每段「管位占置」在本行内以延米体积扣回填；放坡按上方所选口径的系数与起点执行；沟底宽建议 = 管群布置宽 + 2 × 工作面。
            挖方/余方为天然密实方；余方外运按虚方计（余方×虚方换算系数），借方按天然方计；回填按压实方。
          </div>
        </details>
        <button type="button" className="btn-secondary" onClick={() => setRows((rs) => [...rs, emptyRow()])}>＋ 加一段</button>
        <button type="button" className="btn-secondary" onClick={() => {
          const soilNames = ['一、二类土', '三类土', '四类土'];
          const modeNames: Record<string, string> = { spec: '按定额放坡', none: '直槽不放坡', custom: '自定系数' };
          const lines = [
            '挖方与回填速算',
            ['挖方单价(元/m³)', prices.dig, '回填夯实单价(元/m³)', prices.back, '余方外运/借方(元/m³)', prices.haul, '虚方换算系数', loose].join('\t'),
            ['段名/桩号', '长度L(m)', '沟底宽a(m)', '挖深h(m)', '土壤类别', '放坡方式', '自定m', '管位占置(m³/m)', '有效m', '挖方(m³)', '回填(m³)', '余方(m³)'].join('\t'),
          ];
          rows.forEach((rw, i) => {
            const o = out[i];
            if (!rw.len && !rw.a && !rw.h && !rw.name) return;
            lines.push([rw.name ?? '', rw.len, rw.a, rw.h, soilNames[rw.soil], modeNames[rw.mode], rw.mode === 'custom' ? rw.mCustom : '', rw.deduct, `${o.mEff.toFixed(2)} ${o.note}`.trim(), o.dig.toFixed(1), o.back.toFixed(1), o.surplus.toFixed(1)].join('\t'));
          });
          lines.push(['合计', '', '', '', '', '', '', '', '', totals.dig.toFixed(1), totals.back.toFixed(1), totals.surplus.toFixed(1)].join('\t'));
          lines.push(['估算合价(元)', totals.cost.toFixed(2)].join('\t'));
          navigator.clipboard?.writeText(lines.join('\n')).catch(() => { /* ignore */ });
        }}>复制结果</button>
      </div>
    </ToolShell>
  );
}

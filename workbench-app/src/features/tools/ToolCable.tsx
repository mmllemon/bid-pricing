import { useState } from 'react';
import { calcCableRows, VOLT_MAT, type CableRow } from './toolsCalc';
import { ToolShell, NumField, ResultStrip, fmt } from './ToolShell';
import { useConfirm } from '../../components/confirm';

/**
 * 电缆价格速算（P2 前端整合：由 frontend/tool-cable.html + tool-cable.js 迁入 React）
 * 计算走 toolsCalc.calcCableRows（纯函数，有判据）。
 * 保留：电压等级切换覆盖材料系数的 confirm、逐行复制/删除、长江现货拉取。
 */

const API_BASE = (window as unknown as { __API_BASE__?: string }).__API_BASE__ || 'http://localhost:8000';

const emptyCableRow = (matRatio: number | '' = ''): CableRow => ({
  metal: 'cu', spec: '', len: 0, pullPts: 0, pullLen: 0, qty: 1, loss: 1.0, matRatio,
});

export default function ToolCable() {
  const [cu, setCu] = useState(78000);
  const confirm = useConfirm();
  const [al, setAl] = useState(21000);
  const [k, setK] = useState(1.05);
  const [mgr, setMgr] = useState(8);
  const [vat, setVat] = useState(13);
  const [volt, setVolt] = useState('mv');
  const [rows, setRows] = useState<CableRow[]>(() => [emptyCableRow(VOLT_MAT.mv), emptyCableRow(VOLT_MAT.mv)]);
  const [priceStatus, setPriceStatus] = useState('');

  const { rows: out, total, nexTotal } = calcCableRows(rows, { cu, al }, k, mgr, vat, volt);
  const updRow = (i: number, patch: Partial<CableRow>) => setRows((rs) => rs.map((r, k2) => (k2 === i ? { ...r, ...patch } : r)));

  const voltOptions: [string, string][] = [['lv', '0.6/1kV'], ['mv', '8.7/15kV'], ['hv', '26/35kV']];

  return (
    <ToolShell id="tool-cable" title="电缆价格速算" subtitle="导体成本 = Σ(芯数×截面) × 密度 × 金属价 / 1e6；含税 = 不含税 × (1+增值税率)">
      <div className="tool-grid" style={{ marginBottom: 12 }}>
        <NumField id="cCu" label="铜价" value={cu} onChange={setCu} step={100} suffix="元/吨" />
        <NumField id="cAl" label="铝价" value={al} onChange={setAl} step={100} suffix="元/吨" />
        <NumField id="cK" label="导体用量系数" value={k} onChange={setK} step={0.01} tip="考虑绞合/绝缘等对导体用量的放大" />
        <NumField id="cMgr" label="管理及利润率" value={mgr} onChange={setMgr} step={0.5} suffix="%" />
        <NumField id="cVat" label="增值税率" value={vat} onChange={setVat} step={1} suffix="%" />
        <label className="field" data-tip="其他材料系数建议值：0.6/1kV 取 0.30，8.7/15kV 取 0.40，26/35kV 取 0.50；切换后整表该系数同步更新，仍可逐行改">
          <span className="field-label">电压等级</span>
          <select id="cVolt" value={volt} onChange={async (e) => {
            const next = e.target.value;
            const nv = Number((VOLT_MAT[next] ?? 0.30).toFixed(2));
            const ov = Number((VOLT_MAT[volt] ?? 0.30).toFixed(2));
            const dirty = rows.filter((r) => r.matRatio !== '' && Number(r.matRatio) !== ov && Number(r.matRatio) !== nv);
            if (dirty.length > 0 && !(await confirm(`切换电压等级会把 ${dirty.length} 行手工填写的材料系数覆盖为建议值 ${nv}，确定继续吗？`, { title: '切换电压等级', sub: `会覆盖 ${dirty.length} 行手工填写的材料系数`, okLabel: '继续切换', ariaLabel: '切换电压等级确认' }))) return;
            setVolt(next);
            setRows((rs) => rs.map((r) => ({ ...r, matRatio: nv })));
          }}>
            {voltOptions.map(([v, label]) => <option key={v} value={v}>{label}</option>)}
          </select>
        </label>
        <label className="field act" data-tip="经后端代理调用长江有色金属网公开报价接口，写入当日长江现货 1#铜 / A00铝均价；需后端服务运行中">
          <span className="field-label">现货价</span>
          <span>
            <button type="button" className="btn-secondary" onClick={async () => {
              setPriceStatus('拉取中…');
              try {
                const r = await fetch(API_BASE + '/api/metal-prices');
                const d = await r.json().catch(() => ({}));
                if (!r.ok || d.status !== 'PASS') throw new Error(d?.error || ('HTTP ' + r.status));
                if (d.cu) setCu(d.cu);
                if (d.al) setAl(d.al);
                setPriceStatus(`已更新（${d.date || '当日'}长江现货）：1#铜 ${fmt(d.cu, 0)} / A00铝 ${fmt(d.al, 0)} 元/吨`);
              } catch (e) {
                setPriceStatus('拉取失败：' + (e as Error).message + '。请确认后端已启动，或手动输入。');
              }
            }}>↻ 拉取长江现货</button>
          </span>
        </label>
      </div>
      {priceStatus && <div className="hint" style={{ margin: '-6px 0 12px' }}>{priceStatus}</div>}

      <div className="tool-table-wrap">
        <table className="tool-table" id="cableTable">
          <thead>
            <tr>
              <th style={{ minWidth: 150 }}>型号</th><th>材质</th><th style={{ minWidth: 130 }}>规格</th>
              <th>单长(m)</th><th>预留处数</th><th>每处预留(m)</th><th>根数</th><th>损耗率(%)</th>
              <th title="其他材料系数">材料系数</th>
              <th className="num">导体成本</th><th className="num">不含税</th><th className="num">含税</th><th className="num">合价</th><th />
            </tr>
          </thead>
          <tbody id="cableRows">
            {rows.map((row, i) => {
              const o = out[i];
              return (
                <tr key={i}>
                  <td><input type="text" placeholder="如 YJV22-8.7/15kV" value={row.model ?? ''} onChange={(e) => updRow(i, { model: e.target.value })} /></td>
                  <td>
                    <select value={row.metal} onChange={(e) => updRow(i, { metal: e.target.value as CableRow['metal'] })}>
                      <option value="cu">铜</option><option value="al">铝</option>
                    </select>
                  </td>
                  <td><input type="text" placeholder="3×240 或 3×240+2×120" value={row.spec} onChange={(e) => updRow(i, { spec: e.target.value })} /></td>
                  <td><input className="num" type="number" min={0} step={0.1} value={row.len} onChange={(e) => updRow(i, { len: Number(e.target.value) })} /></td>
                  <td><input className="num" type="number" min={0} step={1} value={row.pullPts} onChange={(e) => updRow(i, { pullPts: Number(e.target.value) })} /></td>
                  <td><input className="num" type="number" min={0} step={0.1} value={row.pullLen} onChange={(e) => updRow(i, { pullLen: Number(e.target.value) })} /></td>
                  <td><input className="num" type="number" min={0} step={1} value={row.qty} onChange={(e) => updRow(i, { qty: Number(e.target.value) })} /></td>
                  <td><input className="num" type="number" min={0} step={0.1} value={row.loss} onChange={(e) => updRow(i, { loss: Number(e.target.value) })} /></td>
                  <td><input className="num" type="number" min={0} step={0.05} value={row.matRatio} title="其他材料+制费 ÷ 导体成本" onChange={(e) => updRow(i, { matRatio: e.target.value === '' ? '' : Number(e.target.value) })} /></td>
                  <td className="num row-cu">{o.ok ? fmt(o.cuCost) : '—'}</td>
                  <td className="num row-pnex">{o.ok ? `¥ ${fmt(o.pNex)}` : '—'}</td>
                  <td className="num row-ptax">{o.ok ? `¥ ${fmt(o.pTax)}` : '—'}</td>
                  <td className="num row-total">{`¥ ${fmt(o.total)}`}</td>
                  <td className="row-actions">
                    <button type="button" className="row-copy" title="复制本行" onClick={() => setRows((rs) => { const c = [...rs]; c.splice(i + 1, 0, { ...row }); return c; })}>⧉</button>
                    <button type="button" className="row-del" title="删除本行" onClick={() => setRows((rs) => rs.filter((_, k2) => k2 !== i))}>×</button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <ResultStrip items={[
        { label: '合计（不含税）', value: <>¥ {fmt(nexTotal)}</> },
        { label: '合计（含税）', value: <>¥ {fmt(total)}</> },
      ]} />

      <div className="action-row">
        <details className="spec">
          <summary>口径说明</summary>
          <div className="hint">
            导体成本/m = Σ(芯数×截面) mm² × 密度(g/cm³) / 1000 × 金属价(元/kg)（铜 8.89、铝 2.70 g/cm³）。
            不含税单价 = 导体 × 用量系数 × (1+其他材料系数) × (1+管理及利润率)；含税单价 = 不含税 × (1+增值税率)；
            合价 = 含税单价 × 计算长度 × (1+损耗率)。计算长度 = (单长 + 预留处数×每处预留) × 根数。
          </div>
        </details>
        <button type="button" className="btn-secondary" onClick={() => setRows((rs) => [...rs, emptyCableRow(VOLT_MAT[volt] ?? 0.30)])}>＋ 加一行</button>
        <button type="button" className="btn-secondary" onClick={() => {
          const lines = [
            '电缆价格速算（铜价法）',
            ['铜价(元/吨)', cu, '铝价(元/吨)', al, '导体用量系数', k, '管理及利润率(%)', mgr, '增值税率(%)', vat, '电压等级', voltOptions.find(([v]) => v === volt)?.[1]].join('\t'),
            ['型号规格', '材质', '规格', '单长(m)', '预留处数', '每处预留(m)', '根数', '损耗率(%)', '其他材料系数', '导体成本(元/m)', '不含税(元/m)', '含税(元/m)', '合价(元)'].join('\t'),
          ];
          rows.forEach((rw, i) => {
            const o = out[i];
            if (!rw.spec) return;
            lines.push(['', rw.metal === 'al' ? '铝' : '铜', rw.spec, rw.len, rw.pullPts, rw.pullLen, rw.qty, rw.loss, rw.matRatio, o.cuCost.toFixed(2), o.pNex.toFixed(2), o.pTax.toFixed(2), o.total.toFixed(2)].join('\t'));
          });
          lines.push(['合计（不含税）', '', '', '', '', '', '', '', '', '', nexTotal.toFixed(2), '', ''].join('\t'));
          lines.push(['合计（含税）', '', '', '', '', '', '', '', '', '', '', '', total.toFixed(2)].join('\t'));
          navigator.clipboard?.writeText(lines.join('\n')).catch(() => { /* ignore */ });
        }}>复制结果</button>
      </div>
    </ToolShell>
  );
}

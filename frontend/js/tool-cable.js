/* ===== 电缆价格速算（铜价法） =====
 * 导体成本/m = Σ(芯数×截面) mm² × 密度(g/cm³) / 1000 × 金属价(元/kg)
 *            = Σ(芯数×截面) × 密度 × 金属价(元/吨) / 1e6
 *   （1 mm² × 1 m = 1 cm³；铜 8.89、铝 2.70 g/cm³）
 * 不含税单价 = 导体 × 用量系数 × (1+其他材料系数) × (1+管理及利润率)
 * 含税单价   = 不含税 × (1+增值税率)；合价 = 含税单价 × 计算长度 × (1+损耗率)
 */
(function () {
  'use strict';

  const $ = (sel, root) => (root || document).querySelector(sel);
  const num = window.toolNum, fmt = window.toolFmt;

  const cableBody = $('#cableRows');
  const METAL_DENSITY = { cu: 8.89, al: 2.70 };
  /* 其他材料系数建议值（按电压等级分档；可按厂家询价调整） */
  const VOLT_MAT = { lv: 0.30, mv: 0.40, hv: 0.50 };
  /* 后端基地址：优先 window.__API_BASE__ 覆盖；否则按当前主机名推导（支持局域网 IP 访问），
     file:// 直接打开时回退 localhost */
  const API_BASE = window.__API_BASE__
    || (location.hostname ? location.protocol + '//' + location.hostname + ':8000' : 'http://localhost:8000');

  function parseSpec(text) {
    // 「3×240」「3×240+2×120」「5×16」→ Σ(芯数×截面)；无法解析返回 0
    let sum = 0;
    const re = /(\d+)\s*[×x*]\s*(\d+(?:\.\d+)?)/g;
    let m;
    while ((m = re.exec(String(text || ''))) !== null) {
      sum += (+m[1]) * (+m[2]);
    }
    return sum;
  }

  function cableRowHtml(d) {
    d = d || {};
    const esc = window.toolEsc;
    const metal = d.metal === 'al' ? 'al' : 'cu';
    const matDef = d.matRatio ?? (VOLT_MAT[$('#cVolt').value] ?? 0.30).toFixed(2);
    return `<tr>
      <td><input type="text" data-k="model" placeholder="如 YJV22-8.7/15kV" value="${esc(d.model)}"></td>
      <td><select data-k="metal"><option value="cu"${metal === 'cu' ? ' selected' : ''}>铜</option><option value="al"${metal === 'al' ? ' selected' : ''}>铝</option></select></td>
      <td><input type="text" data-k="spec" placeholder="3×240 或 3×240+2×120" value="${esc(d.spec)}"></td>
      <td><input class="num" data-k="len" type="number" min="0" step="0.1" placeholder="0" value="${esc(d.len ?? '')}"></td>
      <td><input class="num" data-k="pullPts" type="number" min="0" step="1" value="${esc(d.pullPts ?? 0)}"></td>
      <td><input class="num" data-k="pullLen" type="number" min="0" step="0.1" value="${esc(d.pullLen ?? 0)}"></td>
      <td><input class="num" data-k="qty" type="number" min="0" step="1" value="${esc(d.qty ?? 1)}"></td>
      <td><input class="num" data-k="loss" type="number" min="0" step="0.1" value="${esc(d.loss ?? 1.0)}"></td>
      <td><input class="num" data-k="matRatio" type="number" min="0" step="0.05" value="${esc(matDef)}" title="其他材料+制费 ÷ 导体成本"></td>
      <td class="num row-pnex">—</td>
      <td class="num row-ptax">—</td>
      <td class="num row-total">0.00</td>
      <td><button type="button" class="row-del" title="删除本行" aria-label="删除本行">×</button></td>
    </tr>`;
  }

  function recalcCable() {
    const cuPrice = num($('#cCu')), alPrice = num($('#cAl'));
    const k = num($('#cK')) || 1, mgr = num($('#cMgr')) / 100, vat = num($('#cVat')) / 100;
    let total = 0;
    cableBody.querySelectorAll('tr').forEach(tr => {
      const g = k2 => num(tr.querySelector(`[data-k="${k2}"]`));
      const metal = tr.querySelector('[data-k="metal"]').value;
      const areaSum = parseSpec(tr.querySelector('[data-k="spec"]').value);
      const density = METAL_DENSITY[metal];
      const metalPrice = metal === 'cu' ? cuPrice : alPrice;

      const cuCost = areaSum * density * metalPrice / 1e6 * k;   // 导体成本 元/m
      const pNex = cuCost * (1 + g('matRatio')) * (1 + mgr);     // 不含税
      const pTax = pNex * (1 + vat);                             // 含税

      const calcLen = (g('len') + g('pullPts') * g('pullLen')) * g('qty');
      const sum = pTax * calcLen * (1 + g('loss') / 100);
      total += sum;

      tr.querySelector('.row-pnex').textContent = areaSum > 0 ? fmt(pNex) : '—';
      tr.querySelector('.row-ptax').textContent = areaSum > 0 ? fmt(pTax) : '—';
      tr.querySelector('.row-total').textContent = fmt(sum);
    });
    $('#cableTotal').textContent = fmt(total);
  }

  /* ---------- 自动保存 / 恢复（刷新不丢） ---------- */
  const STORE_KEY = 'tool-cable';
  const PARAM_IDS = ['cCu', 'cAl', 'cK', 'cMgr', 'cVat', 'cVolt'];
  function collectState() {
    const params = {};
    PARAM_IDS.forEach(id => { params[id] = $('#' + id).value; });
    const rows = [];
    cableBody.querySelectorAll('tr').forEach(tr => {
      const o = {};
      tr.querySelectorAll('[data-k]').forEach(el => { o[el.dataset.k] = el.value; });
      rows.push(o);
    });
    return { params, rows };
  }
  function applyState(s) {
    if (!s) return false;
    try {
      Object.entries(s.params || {}).forEach(([id, v]) => {
        const el = document.getElementById(id);
        if (el) el.value = v;
      });
      cableBody.innerHTML = '';
      (s.rows && s.rows.length ? s.rows : [{}, {}]).forEach(r => {
        cableBody.insertAdjacentHTML('beforeend', cableRowHtml(r));
      });
      return true;
    } catch (e) { return false; }
  }
  const saveNow = () => window.toolStore.save(STORE_KEY, collectState());
  const saveSoon = window.toolDebounce(saveNow, 500);

  /* ---------- 复制结果（TSV，可直接粘贴到 Excel） ---------- */
  function buildCableTsv() {
    const p = id => $('#' + id).value;
    const lines = [];
    lines.push('电缆价格速算（铜价法）');
    lines.push(['铜价(元/吨)', p('cCu'), '铝价(元/吨)', p('cAl'), '导体用量系数', p('cK'),
      '管理及利润率(%)', p('cMgr'), '增值税率(%)', p('cVat'),
      '电压等级', $('#cVolt').selectedOptions[0].textContent].join('\t'));
    lines.push(['型号规格', '材质', '规格', '单长(m)', '预留处数', '每处预留(m)', '根数',
      '损耗率(%)', '其他材料系数', '不含税(元/m)', '含税(元/m)', '合价(元)'].join('\t'));
    cableBody.querySelectorAll('tr').forEach(tr => {
      const g = k => { const el = tr.querySelector(`[data-k="${k}"]`); return el ? el.value : ''; };
      const t = c => { const el = tr.querySelector(c); return el ? el.textContent.trim() : ''; };
      if (!g('spec') && !g('model')) return;   // 空行不导出
      lines.push([g('model'), g('metal') === 'al' ? '铝' : '铜', g('spec'), g('len'),
        g('pullPts'), g('pullLen'), g('qty'), g('loss'), g('matRatio'),
        t('.row-pnex'), t('.row-ptax'), t('.row-total')].join('\t'));
    });
    lines.push(['合计（含税）', '', '', '', '', '', '', '', '', '', '',
      $('#cableTotal').textContent.trim()].join('\t'));
    return lines.join('\n');
  }
  async function copyCableResult(btn) {
    const ok = await window.toolCopyText(buildCableTsv());
    const old = btn.textContent;
    btn.textContent = ok ? '已复制 ✓' : '复制失败';
    setTimeout(() => { btn.textContent = old; }, 1500);
  }

  /* ---------- 事件 ---------- */
  $('#cableAdd').addEventListener('click', () => {
    cableBody.insertAdjacentHTML('beforeend', cableRowHtml());
    saveSoon();
  });
  $('#cableCopy').addEventListener('click', (e) => copyCableResult(e.currentTarget));
  cableBody.addEventListener('input', () => { recalcCable(); saveSoon(); });
  cableBody.addEventListener('click', (e) => {
    const del = e.target.closest('.row-del');
    if (del) { del.closest('tr').remove(); recalcCable(); saveSoon(); }
  });
  ['cCu', 'cAl', 'cK', 'cMgr', 'cVat'].forEach(id =>
    $('#' + id).addEventListener('input', () => { recalcCable(); saveSoon(); }));
  /* 电压等级切换：其他材料系数按建议值分档，整表同步（仍可逐行改） */
  $('#cVolt').addEventListener('change', () => {
    const v = (VOLT_MAT[$('#cVolt').value] ?? 0.30).toFixed(2);
    cableBody.querySelectorAll('tr').forEach(tr => {
      const inp = tr.querySelector('[data-k="matRatio"]');
      if (inp) inp.value = v;
    });
    recalcCable();
    saveSoon();
  });
  /* 拉取长江现货价：经后端代理 ccmn.cn 公开报价接口，写入铜/铝参数 */
  $('#cFetchPrice').addEventListener('click', async () => {
    const btn = $('#cFetchPrice'), st = $('#cPriceStatus');
    const old = btn.textContent;
    btn.disabled = true; btn.textContent = '拉取中…';
    try {
      const r = await fetch(API_BASE + '/api/metal-prices');
      const d = await r.json().catch(() => ({}));
      if (!r.ok || d.status !== 'PASS') throw new Error((d && d.error) || ('HTTP ' + r.status));
      if (d.cu) $('#cCu').value = d.cu;
      if (d.al) $('#cAl').value = d.al;
      recalcCable();
      saveSoon();
      st.textContent = `已更新（${d.date || '当日'}长江现货）：1#铜 ${fmt(d.cu, 0)} / A00铝 ${fmt(d.al, 0)} 元/吨`;
    } catch (e) {
      st.textContent = '拉取失败：' + e.message + '。请确认后端已启动（run.ps1），或手动输入。';
    } finally {
      btn.disabled = false; btn.textContent = old;
    }
  });
  /* ---------- 启动：恢复存档，无存档则建两个空行 ---------- */
  if (!applyState(window.toolStore.load(STORE_KEY))) {
    cableBody.insertAdjacentHTML('beforeend', cableRowHtml());
    cableBody.insertAdjacentHTML('beforeend', cableRowHtml());
  }
  recalcCable();
  window.addEventListener('pagehide', saveNow);
})();

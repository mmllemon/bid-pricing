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

  function cableRowHtml() {
    const matDef = (VOLT_MAT[$('#cVolt').value] ?? 0.30).toFixed(2);
    return `<tr>
      <td><input type="text" placeholder="如 YJV22-8.7/15kV"></td>
      <td><select data-k="metal"><option value="cu" selected>铜</option><option value="al">铝</option></select></td>
      <td><input type="text" data-k="spec" placeholder="3×240 或 3×240+2×120"></td>
      <td><input class="num" data-k="len" type="number" min="0" step="0.1" placeholder="0"></td>
      <td><input class="num" data-k="pullPts" type="number" min="0" step="1" value="0"></td>
      <td><input class="num" data-k="pullLen" type="number" min="0" step="0.1" value="0"></td>
      <td><input class="num" data-k="qty" type="number" min="0" step="1" value="1"></td>
      <td><input class="num" data-k="loss" type="number" min="0" step="0.1" value="1.0"></td>
      <td><input class="num" data-k="matRatio" type="number" min="0" step="0.05" value="${matDef}" title="其他材料+制费 ÷ 导体成本"></td>
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

  $('#cableAdd').addEventListener('click', () => {
    cableBody.insertAdjacentHTML('beforeend', cableRowHtml());
  });
  cableBody.addEventListener('input', recalcCable);
  cableBody.addEventListener('click', (e) => {
    const del = e.target.closest('.row-del');
    if (del) { del.closest('tr').remove(); recalcCable(); }
  });
  ['cCu', 'cAl', 'cK', 'cMgr', 'cVat'].forEach(id => $('#' + id).addEventListener('input', recalcCable));
  /* 电压等级切换：其他材料系数按建议值分档，整表同步（仍可逐行改） */
  $('#cVolt').addEventListener('change', () => {
    const v = (VOLT_MAT[$('#cVolt').value] ?? 0.30).toFixed(2);
    cableBody.querySelectorAll('tr').forEach(tr => {
      const inp = tr.querySelector('[data-k="matRatio"]');
      if (inp) inp.value = v;
    });
    recalcCable();
  });
  cableBody.insertAdjacentHTML('beforeend', cableRowHtml());
  cableBody.insertAdjacentHTML('beforeend', cableRowHtml());
  recalcCable();
})();

/* ===== 挖方与回填速算 =====
 * 挖方 V = L × (a + m·h) × h（梯形断面，沟槽按平均深度）。
 * 放坡口径可选（建筑定额内置值 / 电力、市政为占位值须核对），系数与起点均可在
 * 口径表内直接改；未达起点深度按直槽。
 * 回填 = 挖方 − 管位占置（延米体积 × 长，下限 0）；余方 = 挖方 − 回填。
 * 未做虚实方折算：回填按压实方、余方按天然方，借方场景请自行乘折算系数。
 */
(function () {
  'use strict';

  const $ = (sel, root) => (root || document).querySelector(sel);
  const num = window.toolNum, fmt = window.toolFmt;

  /* 放坡口径预设：建筑定额为全国统一建筑工程基础定额口径（可信）；
   * 电力/市政各省差异大，先以建筑口径占位——选择后请按所套定额改表。 */
  const RULE_PRESETS = {
    arch:  [{ m: 0.50, start: 1.2 }, { m: 0.33, start: 1.5 }, { m: 0.25, start: 2.0 }],
    power: [{ m: 0.50, start: 1.2 }, { m: 0.33, start: 1.5 }, { m: 0.25, start: 2.0 }],
    muni:  [{ m: 0.50, start: 1.2 }, { m: 0.33, start: 1.5 }, { m: 0.25, start: 2.0 }],
  };
  const RULE_HINT = {
    arch:  '系数与起点可直接修改，按你实际所套定额核对；未达起点深度按直槽。',
    power: '⚠ 电力定额各版本/各省差异大，当前为占位值——请按所套定额逐格核对修改。',
    muni:  '⚠ 市政定额各省市差异大，当前为占位值——请按所套定额逐格核对修改。',
  };

  function readRules() {
    // 口径表 → [{m, start}×3]（行序 = 土类序）
    const rows = [];
    for (let i = 0; i < 3; i++) {
      rows.push({
        m: num($(`#ruleTable input[data-rule="${i}"][data-f="m"]`)),
        start: num($(`#ruleTable input[data-rule="${i}"][data-f="start"]`)),
      });
    }
    return rows;
  }

  const earthBody = $('#earthRows');

  function earthRowHtml() {
    const soilOpts = ['一、二类土', '三类土', '四类土']
      .map((n, i) => `<option value="${i}"${i === 0 ? ' selected' : ''}>${n}</option>`)
      .join('');
    return `<tr>
      <td><input type="text" placeholder="如 1# 路 K0+000"></td>
      <td><input class="num" data-k="len" type="number" min="0" step="0.1" placeholder="0"></td>
      <td><input class="num" data-k="a" type="number" min="0" step="0.05" placeholder="0"></td>
      <td><input class="num" data-k="h" type="number" min="0" step="0.05" placeholder="0"></td>
      <td><select data-k="soil">${soilOpts}</select></td>
      <td><select data-k="mode">
        <option value="spec" selected>按定额放坡</option>
        <option value="none">直槽不放坡</option>
        <option value="custom">自定系数</option>
      </select></td>
      <td><input class="num" data-k="mCustom" type="number" min="0" step="0.01" value="0.5" disabled></td>
      <td><input class="num" data-k="deduct" type="number" min="0" step="0.01" value="0" title="管位/基础占置体积（延米），从本段回填中扣减"></td>
      <td class="num eff-m">—</td>
      <td class="num v-dig">0.0</td>
      <td class="num v-back">0.0</td>
      <td class="num v-surplus">0.0</td>
      <td><button type="button" class="row-del" title="删除本段" aria-label="删除本段">×</button></td>
    </tr>`;
  }

  function recalcEarth() {
    const pDig = num($('#eDig')), pBack = num($('#eBack')), pHaul = num($('#eHaul'));
    const loose = num($('#eLoose')) || 1;   // 天然密实方→虚方换算系数
    let tDig = 0, tBack = 0, tSur = 0, total = 0;
    earthBody.querySelectorAll('tr').forEach(tr => {
      const g = k => num(tr.querySelector(`[data-k="${k}"]`));
      const len = g('len'), a = g('a'), h = g('h');
      const rule = readRules()[+tr.querySelector('[data-k="soil"]').value] || readRules()[0];
      const mode = tr.querySelector('[data-k="mode"]').value;
      const custom = tr.querySelector('[data-k="mCustom"]');

      let mEff = 0, mNote = '';
      if (mode === 'none') {
        mEff = 0; mNote = '<span class="off">直槽</span>';
      } else if (mode === 'custom') {
        mEff = num(custom); mNote = '<span class="off">自定</span>';
      } else {
        mEff = h > rule.start ? rule.m : 0;
        mNote = h > rule.start ? '' : `<span class="off">未达 ${rule.start}m</span>`;
      }
      tr.querySelector('.eff-m').innerHTML = `${mEff.toFixed(2)} ${mNote}`;

      const dig = len * (a + mEff * h) * h;
      const back = Math.max(0, dig - len * g('deduct'));
      const surplus = dig - back;             // + 余方外运 / − 借方（天然方）
      const haulVol = surplus >= 0 ? surplus * loose : Math.abs(surplus);  // 外运按虚方，借方按天然方
      total += dig * pDig + back * pBack + haulVol * pHaul;
      tDig += dig; tBack += back; tSur += surplus;
      tr.querySelector('.v-dig').textContent = fmt(dig, 1);
      tr.querySelector('.v-back').textContent = fmt(back, 1);
      tr.querySelector('.v-surplus').textContent = fmt(surplus, 1);
    });
    $('#earthDig').textContent = fmt(tDig, 1);
    $('#earthBack').textContent = fmt(tBack, 1);
    $('#earthSurplus').textContent = fmt(tSur, 1);
    $('#mDig').textContent = fmt(tDig, 1);
    $('#mBack').textContent = fmt(tBack, 1);
    $('#mSurplus').textContent = fmt(tSur, 1);
    $('#mSurplusLoose').textContent = fmt(tSur > 0 ? tSur * loose : 0, 1);
    $('#mTotal').textContent = fmt(total);
  }

  // 口径切换：把预设值载入口径表（载入后仍可逐格改）
  // 电力/市政为建筑定额占位值，切换时强制确认，防止直接套用
  let lastRuleKey = 'arch';
  $('#eRuleSet').addEventListener('change', () => {
    const sel = $('#eRuleSet');
    const key = sel.value;
    if (key !== 'arch' && key !== lastRuleKey) {
      const ok = window.confirm('电力/市政定额各省市差异大，当前载入的是建筑定额占位值——必须按你实际所套定额逐格核对修改。\n\n确定要切换吗？');
      if (!ok) { sel.value = lastRuleKey; if (sel.__cs) sel.__cs.refresh(); return; }
    }
    lastRuleKey = key;
    const rs = RULE_PRESETS[key] || RULE_PRESETS.arch;
    rs.forEach((r, i) => {
      $(`#ruleTable input[data-rule="${i}"][data-f="m"]`).value = r.m;
      $(`#ruleTable input[data-rule="${i}"][data-f="start"]`).value = r.start;
    });
    $('#eRuleHint').textContent = RULE_HINT[key] || RULE_HINT.arch;
    recalcEarth();
  });
  $('#ruleTable').addEventListener('input', recalcEarth);
  $('#earthAdd').addEventListener('click', () => {
    earthBody.insertAdjacentHTML('beforeend', earthRowHtml());
  });
  earthBody.addEventListener('input', (e) => {
    if (e.target.matches('[data-k="mode"]')) {
      const row = e.target.closest('tr');
      row.querySelector('[data-k="mCustom"]').disabled = e.target.value !== 'custom';
    }
    recalcEarth();
  });
  earthBody.addEventListener('click', (e) => {
    const del = e.target.closest('.row-del');
    if (del) { del.closest('tr').remove(); recalcEarth(); }
  });
  ['eDig', 'eBack', 'eHaul', 'eLoose'].forEach(id => $('#' + id).addEventListener('input', recalcEarth));
  earthBody.insertAdjacentHTML('beforeend', earthRowHtml());
  earthBody.insertAdjacentHTML('beforeend', earthRowHtml());
  recalcEarth();
  // 放坡口径接项目自定义下拉（毛玻璃组件）；行内土类/放坡方式保持原生+统一箭头
  if (typeof initCustomSelect === 'function') {
    initCustomSelect('#eRuleSet');
  }
})();

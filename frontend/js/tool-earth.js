/* ===== 挖方与回填速算 =====
 * 挖方 V = L × (a + m·h) × h（梯形断面，沟槽按平均深度）。
 * 放坡口径可选（建筑定额内置值 / 电力、市政为占位值须核对），系数与起点均可在
 * 口径表内直接改；未达起点深度按直槽。
 * 回填 = 挖方 − 管位占置（延米体积 × 长，下限 0）；余方 = 挖方 − 回填。
 * 未做虚实方折算：回填按压实方、余方按天然方，借方场景请自行乘折算系数。
 */
(function () {
  'use strict';

  /* P1: tool-common.js 加载失败时整页静默死亡 → 断言加载标记 + 可见提示后提前返回 */
  if (!window.__toolCommonLoaded) {
    document.addEventListener('DOMContentLoaded', () => {
      const host = document.querySelector('.tool-page') || document.body;
      const bar = document.createElement('div');
      bar.style.cssText = 'margin:12px;padding:12px 16px;border:2px solid #c00;border-radius:8px;background:#fff5f5;color:#a00;font-size:14px;line-height:1.7;';
      bar.textContent = '页面初始化失败：公共脚本 tool-common.js 未加载（可能 404 或被拦截），后续计算全部不可用。请确认文件存在后刷新重试。';
      host.prepend(bar);
    });
    return;
  }


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
    power: '※ 电力定额各版本/各省差异大，当前为占位值——请按所套定额逐格核对修改。',
    muni:  '※ 市政定额各省市差异大，当前为占位值——请按所套定额逐格核对修改。',
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

  function earthRowHtml(d) {
    d = d || {};
    const esc = window.toolEsc;
    const soilIdx = ['0', '1', '2'].includes(String(d.soil)) ? String(d.soil) : '0';
    const mode = ['spec', 'none', 'custom'].includes(d.mode) ? d.mode : 'spec';
    const soilOpts = ['一、二类土', '三类土', '四类土']
      .map((n, i) => `<option value="${i}"${String(i) === soilIdx ? ' selected' : ''}>${n}</option>`)
      .join('');
    const modeOpts = [['spec', '按定额放坡'], ['none', '直槽不放坡'], ['custom', '自定系数']]
      .map(([v, n]) => `<option value="${v}"${v === mode ? ' selected' : ''}>${n}</option>`)
      .join('');
    return `<tr>
      <td><input type="text" data-k="name" placeholder="如 1# 路 K0+000" value="${esc(d.name)}"></td>
      <td><input class="num" data-k="len" type="number" min="0" step="0.1" placeholder="0" value="${esc(d.len ?? '')}"></td>
      <td><input class="num" data-k="a" type="number" min="0" step="0.05" placeholder="0" value="${esc(d.a ?? '')}"></td>
      <td><input class="num" data-k="h" type="number" min="0" step="0.05" placeholder="0" value="${esc(d.h ?? '')}"></td>
      <td><select data-k="soil">${soilOpts}</select></td>
      <td><select data-k="mode">${modeOpts}</select></td>
      <td><input class="num" data-k="mCustom" type="number" min="0" step="0.01" value="${esc(d.mCustom ?? 0.5)}"${mode === 'custom' ? '' : ' disabled'}></td>
      <td><input class="num" data-k="deduct" type="number" min="0" step="0.01" value="${esc(d.deduct ?? 0)}" title="管位/基础占置体积（延米），从本段回填中扣减"></td>
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
      const gn = k => window.toolNonNeg(tr.querySelector(`[data-k="${k}"]`));  // 几何量：负数标红按0算
      const len = gn('len'), a = gn('a'), h = gn('h'), deduct = gn('deduct');
      const rule = readRules()[+tr.querySelector('[data-k="soil"]').value] || readRules()[0];
      const mode = tr.querySelector('[data-k="mode"]').value;
      const custom = tr.querySelector('[data-k="mCustom"]');

      let mEff = 0, mNote = '';
      if (mode === 'none') {
        mEff = 0; mNote = '<span class="off">直槽</span>';
      } else if (mode === 'custom') {
        mEff = window.toolNonNeg(custom); mNote = '<span class="off">自定</span>';
      } else {
        mEff = h > rule.start ? rule.m : 0;
        mNote = h > rule.start ? '' : `<span class="off">未达 ${rule.start}m</span>`;
      }
      tr.querySelector('.eff-m').innerHTML = `${mEff.toFixed(2)} ${mNote}`;

      const dig = len * (a + mEff * h) * h;
      const back = Math.max(0, dig - len * deduct);
      const surplus = dig - back;             // + 余方外运 / − 借方（天然方）
      const haulVol = surplus >= 0 ? surplus * loose : Math.abs(surplus);  // 外运按虚方，借方按天然方
      total += dig * pDig + back * pBack + haulVol * pHaul;
      tDig += dig; tBack += back; tSur += surplus;
      tr.querySelector('.v-dig').textContent = fmt(dig, 1);
      tr.querySelector('.v-back').textContent = fmt(back, 1);
      tr.querySelector('.v-surplus').textContent = fmt(surplus, 1);
    });
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
    saveSoon();
  });
  /* ---------- 自动保存 / 恢复（刷新不丢） ---------- */
  const STORE_KEY = 'tool-earth';
  function collectState() {
    const params = {};
    ['eDig', 'eBack', 'eHaul', 'eLoose'].forEach(id => { params[id] = $('#' + id).value; });
    const rows = [];
    earthBody.querySelectorAll('tr').forEach(tr => {
      const o = {};
      tr.querySelectorAll('[data-k]').forEach(el => { o[el.dataset.k] = el.value; });
      rows.push(o);
    });
    return { params, ruleSet: $('#eRuleSet').value, rules: readRules(), rows };
  }
  function applyState(s) {
    if (!s) return false;
    try {
      Object.entries(s.params || {}).forEach(([id, v]) => {
        const el = document.getElementById(id);
        if (el) el.value = v;
      });
      /* 放坡口径：恢复规则集选择 + 口径表逐格值（恢复在自定义下拉初始化之前） */
      const key = (s.ruleSet && RULE_PRESETS[s.ruleSet]) ? s.ruleSet : 'arch';
      $('#eRuleSet').value = key;
      lastRuleKey = key;
      (RULE_PRESETS[key] || RULE_PRESETS.arch).forEach((r, i) => {
        const saved = s.rules && s.rules[i];
        $(`#ruleTable input[data-rule="${i}"][data-f="m"]`).value = saved ? saved.m : r.m;
        $(`#ruleTable input[data-rule="${i}"][data-f="start"]`).value = saved ? saved.start : r.start;
      });
      $('#eRuleHint').textContent = RULE_HINT[key] || RULE_HINT.arch;
      earthBody.innerHTML = '';
      (s.rows && s.rows.length ? s.rows : [{}, {}]).forEach(r => {
        earthBody.insertAdjacentHTML('beforeend', earthRowHtml(r));
      });
      return true;
    } catch (e) { return false; }
  }
  const saveNow = () => window.toolStore.save(STORE_KEY, collectState());
  const saveSoon = window.toolDebounce(saveNow, 500);

  /* ---------- 复制结果（TSV，可直接粘贴到 Excel） ---------- */
  function buildEarthTsv() {
    const p = id => $('#' + id).value;
    const soilNames = ['一、二类土', '三类土', '四类土'];
    const modeNames = { spec: '按定额放坡', none: '直槽不放坡', custom: '自定系数' };
    const lines = [];
    lines.push('挖方与回填速算');
    lines.push(['挖方单价(元/m³)', p('eDig'), '回填夯实单价(元/m³)', p('eBack'),
      '余方外运/借方(元/m³)', p('eHaul'), '虚方换算系数', p('eLoose'),
      '放坡口径', $('#eRuleSet').selectedOptions[0].textContent].join('\t'));
    lines.push(['段名/桩号', '长度L(m)', '沟底宽a(m)', '挖深h(m)', '土壤类别', '放坡方式',
      '自定m', '管位占置(m³/m)', '有效m', '挖方(m³)', '回填(m³)', '余方(m³)'].join('\t'));
    earthBody.querySelectorAll('tr').forEach(tr => {
      const g = k => { const el = tr.querySelector(`[data-k="${k}"]`); return el ? el.value : ''; };
      const t = c => { const el = tr.querySelector(c); return el ? el.textContent.replace(/\s+/g, ' ').trim() : ''; };
      if (!g('name') && !g('len') && !g('a') && !g('h')) return;   // 空行不导出
      lines.push([g('name'), g('len'), g('a'), g('h'),
        soilNames[+g('soil')] || '', modeNames[g('mode')] || '',
        g('mode') === 'custom' ? g('mCustom') : '', g('deduct'),
        t('.eff-m'), t('.v-dig'), t('.v-back'), t('.v-surplus')].join('\t'));
    });
    lines.push(['合计', '', '', '', '', '', '', '', '',
      $('#mDig').textContent.trim(), $('#mBack').textContent.trim(),
      $('#mSurplus').textContent.trim()].join('\t'));
    lines.push(['估算合价(元)', $('#mTotal').textContent.trim()].join('\t'));
    return lines.join('\n');
  }
  async function copyEarthResult(btn) {
    const ok = await window.toolCopyText(buildEarthTsv());
    const old = btn.textContent;
    btn.textContent = ok ? '已复制 ✓' : '复制失败';
    setTimeout(() => { btn.textContent = old; }, 1500);
  }

  /* ---------- 事件 ---------- */
  $('#ruleTable').addEventListener('input', () => { recalcEarth(); saveSoon(); });
  $('#earthAdd').addEventListener('click', () => {
    earthBody.insertAdjacentHTML('beforeend', earthRowHtml());
    saveSoon();
  });
  $('#earthCopy').addEventListener('click', (e) => copyEarthResult(e.currentTarget));
  earthBody.addEventListener('input', (e) => {
    if (e.target.matches('[data-k="mode"]')) {
      const row = e.target.closest('tr');
      row.querySelector('[data-k="mCustom"]').disabled = e.target.value !== 'custom';
    }
    recalcEarth();
    saveSoon();
  });
  earthBody.addEventListener('click', (e) => {
    const del = e.target.closest('.row-del');
    if (del) { del.closest('tr').remove(); recalcEarth(); saveSoon(); }
  });
  ['eDig', 'eBack', 'eHaul', 'eLoose'].forEach(id =>
    $('#' + id).addEventListener('input', () => { recalcEarth(); saveSoon(); }));

  /* ---------- 跨工具交接：排管断面 → 沟底宽 ----------
   * 排管页「送入土方工具」后，本页顶部出现横幅；「应用」新建一段并填入沟底宽 a。 */
  (function () {
    const H = window.toolHandoff;
    if (!H) return;
    const h = H.take('duct');
    if (!h || !h.payload) return;
    const banner = $('#ductBanner'), txt = $('#ductBannerText');
    if (!banner || !txt) return;
    const w = parseFloat(h.payload.width);
    if (!isFinite(w) || w <= 0) { H.clear(); return; }
    txt.innerHTML = `排管工具推荐沟底宽 <strong>${w.toFixed(2)} m</strong>（${window.toolEsc(h.payload.label || '')}）`;
    banner.hidden = false;
    const done = () => { banner.hidden = true; H.clear(); };
    $('#ductApply').addEventListener('click', () => {
      earthBody.insertAdjacentHTML('beforeend', earthRowHtml({ name: h.payload.label || '', a: w.toFixed(2) }));
      recalcEarth();
      saveSoon();
      done();
      const last = earthBody.lastElementChild;
      if (last && typeof last.scrollIntoView === 'function') last.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    });
    $('#ductIgnore').addEventListener('click', done);
  })();

  /* ---------- 启动：恢复存档（无存档则建两个空行） ---------- */
  if (!applyState(window.toolStore.load(STORE_KEY))) {
    earthBody.insertAdjacentHTML('beforeend', earthRowHtml());
    earthBody.insertAdjacentHTML('beforeend', earthRowHtml());
  }
  recalcEarth();
  // 放坡口径接项目自定义下拉（毛玻璃组件）；行内土类/放坡方式保持原生+统一箭头
  if (typeof initCustomSelect === 'function') {
    initCustomSelect('#eRuleSet');
  }
  window.addEventListener('pagehide', saveNow);
})();

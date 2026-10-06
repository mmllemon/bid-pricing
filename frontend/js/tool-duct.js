/* ===== 排管断面布置 =====
 * 孔数 = 回路数 × 每回路孔数 + 备用孔（默认 n+2，可手动改；改后不再随回路数联动）。
 * 排列自动匹配标准表（T/SDL 4-2022）：2孔单层、4孔2×2、6孔2×3、8孔2×4、
 * 12孔3×4、16孔4×4、24孔4×6；不足取大一档，超出 24 孔按 4 层向上取整列数。
 * 管束宽 Wd = 列×D + (列−1)×净距；包封宽 W = Wd + 2×保护层；
 * 包封砼/延米 = (W×H − 总孔数×π×(D/2)²)；沟底宽建议 a = (W + 2×工作面)。
 * 「送入土方工具」经 toolHandoff 把沟底宽送到土方页，土方页顶部横幅应用后新建一段。
 */
(function () {
  'use strict';

  const $ = (sel, root) => (root || document).querySelector(sel);
  const num = window.toolNum, fmt = window.toolFmt, nonNeg = window.toolNonNeg;

  /* 标准排列（行, 列），容量递增 */
  const STD_LAYOUTS = [[1, 2], [2, 2], [2, 3], [2, 4], [3, 4], [4, 4], [4, 6]];
  function autoLayout(total) {
    for (const [r, c] of STD_LAYOUTS) {
      if (r * c >= total) return { rows: r, cols: c, std: true };
    }
    return { rows: 4, cols: Math.ceil(total / 4), std: false };  // 超标准表：4 层向上取整
  }

  let spareTouched = false;   // 备用孔被手动改过后，不再随回路数联动
  let lastResult = null;

  function readParams() {
    const n = Math.max(1, Math.round(num($('#dCircuits'))));
    const per = Math.max(1, Math.round(num($('#dPerCircuit'))));
    const spare = Math.max(0, Math.round(num($('#dSpare'))));
    const used = n * per;                       // 已用孔（不含备用）
    const D = nonNeg($('#dD'));
    const gap = nonNeg($('#dGap'));
    const cover = nonNeg($('#dCover'));
    const work = nonNeg($('#dWork'));
    let rows, cols, note = '';
    if ($('#dLayout').value === 'manual') {
      rows = Math.max(1, Math.round(num($('#dRows'))));
      cols = Math.max(1, Math.round(num($('#dCols'))));
      if (rows * cols < used) note = `※ 孔位不足：已用 ${used} 孔，当前 ${rows}×${cols} 仅 ${rows * cols} 孔`;
    } else {
      const L = autoLayout(Math.max(used + spare, 2));
      rows = L.rows; cols = L.cols;
      if (!L.std) note = '已超出标准表（24 孔），按 4 层向上取整列数，请按设计复核';
    }
    return { n, per, spare, used, total: used + spare, D, gap, cover, work, rows, cols, note };
  }

  function calc(p) {
    const cap = p.rows * p.cols;
    const Wd = p.cols * p.D + (p.cols - 1) * p.gap;
    const Hd = p.rows * p.D + (p.rows - 1) * p.gap;
    const W = Wd + 2 * p.cover, H = Hd + 2 * p.cover;
    const conc = Math.max(0, (W * H - cap * Math.PI * Math.pow(p.D / 2, 2)) / 1e6);  // m³/m
    const a = (W + 2 * p.work) / 1000;                                              // m
    return Object.assign({}, p, { cap, Wd, Hd, W, H, conc, a, spareShown: Math.max(0, cap - p.used) });
  }

  /* ---------- SVG 断面图 ---------- */
  function svgDim(x1, y1, x2, y2, label, focus) {
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

  function renderSvg(r) {
    const box = $('#ductSvg');
    if (!box) return;
    const W = Math.max(r.W, 1), H = Math.max(r.H, 1);
    const s = Math.min(340 / W, 220 / H);
    const ox = 60, oy = 44;
    const VW = 440, VH = Math.ceil(oy * 2 + H * s) + 8;
    const ex = ox, ey = oy;                       // 包封左上
    const dx0 = ex + r.cover * s, dy0 = ey + r.cover * s;  // 管束左上
    let g = '';
    g += `<rect class="wv-conc" data-focus="dCover" x="${ex}" y="${ey}" width="${W * s}" height="${H * s}"/>`;
    let idx = 0;
    for (let ri = 0; ri < r.rows; ri++) {
      for (let ci = 0; ci < r.cols; ci++) {
        const cx = dx0 + (ci * (r.D + r.gap) + r.D / 2) * s;
        const cy = dy0 + (ri * (r.D + r.gap) + r.D / 2) * s;
        const cls = idx < r.used ? 'dv-duct' : 'dv-spare';
        g += `<circle class="${cls}" cx="${cx.toFixed(1)}" cy="${cy.toFixed(1)}" r="${(r.D / 2 * s).toFixed(1)}"/>`;
        idx++;
      }
    }
    // 尺寸标注：包封宽（上）、包封高（左）
    g += svgDim(ex, ey - 14, ex + W * s, ey - 14, `${Math.round(W)}`, 'dCover');
    g += svgDim(ex - 14, ey, ex - 14, ey + H * s, `${Math.round(H)}`, 'dCover');
    g += `<text class="wv-label" x="${ex + W * s / 2}" y="${ey + H * s + 18}">备用 ${r.spareShown} 孔（虚线）</text>`;
    box.innerHTML = `<svg viewBox="0 0 ${VW} ${VH}" role="img" aria-label="排管断面示意">${g}</svg>`;
  }

  /* 点击图元/标注 → 定位并高亮对应参数（复用土方/水井页交互） */
  $('#ductSvg').addEventListener('click', (e) => {
    const t = e.target.closest('[data-focus]');
    if (!t) return;
    const el = document.getElementById(t.dataset.focus);
    if (!el) return;
    el.focus();
    el.classList.add('flash');
    setTimeout(() => el.classList.remove('flash'), 1200);
    if (typeof el.scrollIntoView === 'function') el.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  });

  /* ---------- 计算 + 渲染 ---------- */
  function recalc() {
    const r = calc(readParams());
    lastResult = r;
    $('#mHoles').textContent = `${r.rows}×${r.cols} / ${r.cap} 孔`;
    $('#mDuctSize').textContent = `${Math.round(r.Wd)}×${Math.round(r.Hd)}`;
    $('#mEncSize').textContent = `${Math.round(r.W)}×${Math.round(r.H)}`;
    $('#mConc').textContent = fmt(r.conc, 3);
    $('#mWidth').textContent = fmt(r.a, 2);
    const warn = $('#dWarn');
    if (r.note) { warn.textContent = r.note; warn.hidden = false; }
    else warn.hidden = true;
    renderSvg(r);
    saveSoon();
  }

  /* ---------- 自动保存 / 恢复 ---------- */
  const STORE_KEY = 'tool-duct';
  const IDS = ['dCircuits', 'dPerCircuit', 'dSpare', 'dLayout', 'dRows', 'dCols', 'dD', 'dGap', 'dCover', 'dWork'];
  function saveNow() {
    const o = {};
    IDS.forEach(id => { o[id] = $('#' + id).value; });
    window.toolStore.save(STORE_KEY, o);
  }
  const saveSoon = window.toolDebounce(saveNow, 500);
  function applyState(s) {
    if (!s) return false;
    try {
      IDS.forEach(id => { if (s[id] !== undefined && $('#' + id)) $('#' + id).value = s[id]; });
      syncLayoutMode();
      // 恢复的备用孔若 ≠ n+2，视为用户手动改过，不再联动
      const n = Math.max(1, Math.round(num($('#dCircuits'))));
      spareTouched = Math.round(num($('#dSpare'))) !== n + 2;
      return true;
    } catch (e) { return false; }
  }

  function syncLayoutMode() {
    const manual = $('#dLayout').value === 'manual';
    $('#dRowsWrap').hidden = !manual;
    $('#dColsWrap').hidden = !manual;
  }

  /* ---------- 复制结果（TSV） ---------- */
  function buildTsv() {
    const r = lastResult || calc(readParams());
    const lines = [];
    lines.push('排管断面布置');
    lines.push(['回路数', r.n, '每回路孔数', r.per, '备用孔', r.spare,
      '排列', `${r.rows}×${r.cols}`, '管外径(mm)', r.D,
      '管净距(mm)', r.gap, '包封保护层(mm)', r.cover, '每侧工作面(mm)', r.work].join('\t'));
    lines.push(['总孔数', '管束宽(mm)', '管束高(mm)', '包封宽(mm)', '包封高(mm)',
      '包封混凝土(m³/m)', '沟底宽建议a(m)'].join('\t'));
    lines.push([r.cap, Math.round(r.Wd), Math.round(r.Hd), Math.round(r.W), Math.round(r.H),
      r.conc.toFixed(3), r.a.toFixed(2)].join('\t'));
    return lines.join('\n');
  }
  async function copyResult(btn) {
    const ok = await window.toolCopyText(buildTsv());
    const old = btn.textContent;
    btn.textContent = ok ? '已复制 ✓' : '复制失败';
    setTimeout(() => { btn.textContent = old; }, 1500);
  }

  /* ---------- 送入土方工具 ---------- */
  async function sendToEarth(btn) {
    const r = lastResult || calc(readParams());
    window.toolHandoff.send('duct', {
      width: +r.a.toFixed(2),
      label: `排管断面 ${r.rows}×${r.cols}（${r.cap}孔）`,
    });
    const old = btn.textContent;
    btn.textContent = '已送出 ✓（在土方页顶部点「应用」）';
    setTimeout(() => { btn.textContent = old; }, 2600);
  }

  /* ---------- 事件 ---------- */
  $('#dCircuits').addEventListener('input', () => {
    if (!spareTouched) {
      const n = Math.max(1, Math.round(num($('#dCircuits'))));
      $('#dSpare').value = n + 2;
    }
    recalc();
  });
  $('#dSpare').addEventListener('input', () => { spareTouched = true; recalc(); });
  $('#dLayout').addEventListener('change', () => { syncLayoutMode(); recalc(); });
  ['dPerCircuit', 'dRows', 'dCols', 'dD', 'dGap', 'dCover', 'dWork'].forEach(id =>
    $('#' + id).addEventListener('input', recalc));
  $('#ductCopy').addEventListener('click', (e) => copyResult(e.currentTarget));
  $('#ductSend').addEventListener('click', (e) => sendToEarth(e.currentTarget));

  /* ---------- 启动 ---------- */
  applyState(window.toolStore.load(STORE_KEY));
  recalc();
  window.addEventListener('pagehide', saveNow);
})();

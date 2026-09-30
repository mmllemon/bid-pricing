/* ===== 电缆井工程量速算 =====
 * 井体 = 主井室（矩形，净空 L×W×D）＋ n 个支井室（净空 Lb×Wb，同深同壁厚）。
 * 转角井=支室接主室端部、三通井=接侧向、四通井=两侧各一——三者墙体代数相同，
 * 仅支室数与预设尺寸不同，故统一按「主室闭环 − 开口 + 支室 U 形」中心线法：
 *   中心线净长 = 2(L+t)+2(W+t) + n×(2Lb+t)
 *   井壁 V = 中心线净长 × D × t
 *   板面积 = (L+2t)(W+2t) + n×(Wb+2t)(Lb+t/2)      支室板自主室板边外挑
 *   垫层   = 板平面每边外扩 100mm
 *   外缘周长 = 2(L+2t)+2(W+2t) + n×(2Lb+t)
 *   内缘周长 = 2(L+W) + n×2Lb
 *   模板 = 混凝土井壁: 2×中心线净长×D（内+外侧）＋ 外缘×底板厚 ＋ 顶板底模
 *          砖砌井壁: 仅 底板侧模 ＋ 顶板底模
 *   抹面 = (内缘 + 外缘) × D
 *   钢筋 = 混凝土构件 × 含钢量（含钢量法估算）；砖砌井壁不计井壁筋
 */
(function () {
  'use strict';

  const $ = (sel, root) => (root || document).querySelector(sel);
  const num = window.toolNum, fmt = window.toolFmt;

  /* 参考净空（可改）：常见配电电缆井，非图集替代 */
  const WELL_PRESETS = {
    straight: { name: '直线井', L: 2.0, W: 1.5, D: 2.0, nB: 0, Lb: 0,   Wb: 0 },
    corner:   { name: '转角井', L: 2.5, W: 2.0, D: 2.0, nB: 1, Lb: 2.0, Wb: 2.0 },
    tee:      { name: '三通井', L: 3.0, W: 2.0, D: 2.0, nB: 1, Lb: 1.8, Wb: 2.0 },
    cross:    { name: '四通井', L: 3.0, W: 2.5, D: 2.0, nB: 2, Lb: 1.8, Wb: 2.0 },
  };

  /* 行定义：rebar 行的量 = 对应构件量 × 含钢量。dec 为工程量小数位。 */
  const WELL_UNIT = [
    { key: 'pad',       label: '混凝土垫层 C15',   unit: 'm³', price: 420, dec: 3 },
    { key: 'base',      label: '混凝土底板 C30',   unit: 'm³', price: 520, dec: 3 },
    { key: 'baseRebar', label: '├ 底板钢筋',       unit: 'kg', price: 5.0, dec: 1, rebar: 'base' },
    { key: 'wall',      label: '井壁',             unit: 'm³', priceBrick: 420, priceConc: 650, dec: 3 },
    { key: 'wallRebar', label: '├ 井壁钢筋',       unit: 'kg', price: 5.0, dec: 1, rebar: 'wall' },
    { key: 'top',       label: '混凝土顶板 C30',   unit: 'm³', price: 560, dec: 3 },
    { key: 'topRebar',  label: '├ 顶板钢筋',       unit: 'kg', price: 5.0, dec: 1, rebar: 'top' },
    { key: 'shaft',     label: '井筒砖砌',         unit: 'm³', price: 420, dec: 3 },
    { key: 'form',      label: '模板（接触面）',   unit: 'm²', price: 65,  dec: 2 },
    { key: 'render',    label: '抹面（内＋外壁）', unit: 'm²', price: 25,  dec: 2 },
    { key: 'cover',     label: '井盖（重型球墨）', unit: '套', price: 850, dec: 0 },
    { key: 'ladder',    label: '爬梯',             unit: '副', price: 160, dec: 0 },
  ];
  const ROW = {};   // key → 行号（buildWellTable 时填充）
  function rowIdx(key) { return WELL_UNIT.findIndex(u => u.key === key); }

  function buildWellTable() {
    $('#wellRows').innerHTML = WELL_UNIT.map((u, i) => {
      ROW[u.key] = i;
      return `
      <tr>
        <td>${u.label}</td>
        <td class="num" data-qty="${i}">—</td>
        <td>${u.unit}</td>
        <td class="fx" data-fx="${i}">—</td>
        <td><div class="price-cell"><input data-p="${i}" class="num" type="number" min="0" step="${u.unit === 'kg' ? 0.1 : 1}"
                   value="${u.priceBrick !== undefined ? u.priceBrick : u.price}"><span class="unit-suffix">元/${u.unit}</span></div></td>
        <td class="num" data-sum="${i}">0.00</td>
      </tr>`;
    }).join('');
  }

  let lastSteelEstKg = 0;   // 含钢量法三行合计（钢筋逐根表的对账基准）
  const rebarBody = $('#rebarRows');

  function recalcWell() {
    const L = num($('#wL')), W = num($('#wW')), D = num($('#wD')), t = num($('#wT'));
    const nB = parseInt($('#wBrN').value, 10) || 0;
    const Lb = num($('#wLb')), Wb = num($('#wWb'));
    const baseT = num($('#wBaseT')), padT = num($('#wPadT')), topT = num($('#wTopT'));
    const sD = num($('#wShaftD')), sH = num($('#wShaftH')), sT = num($('#wShaftT'));
    const count = Math.max(1, num($('#wCount')) || 1);
    const isConc = $('#wMat').value === 'conc';

    const clNet  = 2 * (L + t) + 2 * (W + t) + nB * (2 * Lb + t);   // 中心线净长
    const slabA  = (L + 2 * t) * (W + 2 * t) + nB * (Wb + 2 * t) * (Lb + t / 2);
    const po = num($('#wPadOut'));   // 垫层每边外挑宽（默认 0.1；与底板平齐填 0）
    const padA   = (L + 2 * t + 2 * po) * (W + 2 * t + 2 * po)
                 + nB * (Wb + 2 * t + 2 * po) * (Lb + t / 2 + po);
    const outerP = 2 * (L + 2 * t) + 2 * (W + 2 * t) + nB * (2 * Lb + t);
    const innerP = 2 * (L + W) + nB * 2 * Lb;

    const ledgeV = innerP * num($('#wLedgeW')) * num($('#wLedgeH'));   // 墙顶内搁置台（异形部分）并入井壁
    const concQty = {
      base: slabA * baseT,
      wall: clNet * D * t + ledgeV,
      top:  slabA * topT,
    };
    const rebarRatio = {
      base: num($('#wRebarBase')),
      wall: isConc ? num($('#wRebarWall')) : 0,   // 砖砌井壁不计井壁筋
      top:  num($('#wRebarTop')),
    };

    // 计算式（数值代入，随参数刷新）
    const f2 = v => fnum(v);
    const lw = num($('#wLedgeW')), lh = num($('#wLedgeH'));
    const brSlab = nB ? `＋${nB}×(${f2(Wb + 2 * t)}×${f2(Lb + t / 2)})` : '';
    const brPad = nB ? `＋${nB}×(${f2(Wb + 2 * t + 2 * po)}×${f2(Lb + t / 2 + po)})` : '';
    const brCL = nB ? `＋${nB}×(${f2(2 * Lb)}＋${f2(t)})` : '';
    const ledgeFx = ledgeV > 0 ? `＋搁置台${f2(innerP)}×${f2(lw)}×${f2(lh)}` : '';
    const fx = [
      `(${f2(L + 2 * t + 2 * po)}×${f2(W + 2 * t + 2 * po)})×${f2(padT)}${brPad}`,
      `(${f2(L + 2 * t)}×${f2(W + 2 * t)})×${f2(baseT)}${brSlab}`,
      `${f2(concQty.base)}×${f2(rebarRatio.base)}`,
      `(${f2(2 * (L + t))}＋${f2(2 * (W + t))}${brCL})×${f2(D)}×${f2(t)}${ledgeFx}`,
      isConc ? `${f2(concQty.wall)}×${f2(rebarRatio.wall)}` : '—（砖砌不计）',
      `(${f2(L + 2 * t)}×${f2(W + 2 * t)})×${f2(topT)}${brSlab}`,
      `${f2(concQty.top)}×${f2(rebarRatio.top)}`,
      `π×(${f2(sD)}＋${f2(sT)})×${f2(sH)}×${f2(sT)}`,
      isConc ? `2×${f2(clNet)}×${f2(D)}＋${f2(outerP)}×${f2(baseT)}＋${f2(slabA)}`
             : `${f2(outerP)}×${f2(baseT)}＋${f2(slabA)}`,
      `(${f2(innerP)}＋${f2(outerP)})×${f2(D)}`,
      `${count} 套`,
      `${count} 副`,
    ];

    const qtyPerWell = WELL_UNIT.map(u => {
      if (u.rebar) return concQty[u.rebar] * rebarRatio[u.rebar];
      switch (u.key) {
        case 'pad':    return padA * padT;
        case 'base':   return concQty.base;
        case 'wall':   return concQty.wall;
        case 'top':    return concQty.top;
        case 'shaft':  return Math.PI * (sD + sT) * sH * sT;
        case 'form':   return (isConc ? 2 * clNet * D : 0) + outerP * baseT + slabA;
        case 'render': return (innerP + outerP) * D;
        case 'cover':
        case 'ladder': return 1;
        default:       return 0;
      }
    });

    let total = 0, steelEst = 0;
    qtyPerWell.forEach((q0, i) => {
      const q = q0 * count;
      const price = num($(`#wellRows input[data-p="${i}"]`));
      const sum = q * price;
      total += sum;
      if (WELL_UNIT[i].rebar) steelEst += q;   // 含钢量法三行合计（kg，逐根表对账基准）
      $(`#wellRows [data-qty="${i}"]`).textContent = fmt(q, WELL_UNIT[i].dec);
      $(`#wellRows [data-sum="${i}"]`).textContent = fmt(sum);
    });
    // 井壁行材料标注 + 井壁钢筋行的适用性说明
    $('#wellRows tr:nth-child(' + (ROW.wall + 1) + ') td:first-child').textContent =
      `井壁${isConc ? '（C30）' : '（砖砌 M10）'}`;
    $('#wellRows tr:nth-child(' + (ROW.wallRebar + 1) + ') td:first-child').textContent =
      `├ 井壁钢筋${isConc ? '' : '（砖砌不计）'}`;
    fx.forEach((s, i) => { $(`#wellRows [data-fx="${i}"]`).textContent = s; });
    $('#wellTotal').textContent = fmt(total);
    lastSteelEstKg = steelEst;
    renderWellPlan();
    renderWellSect();
    recalcRebar();
  }

  /* ==================== 井体示意（SVG 平面 + 剖面） ====================
   * 示意图非施工图：两图比例各自独立，随参数实时重绘。
   * 图元与尺寸标注带 data-focus，点击定位并高亮对应输入框。
   */
  const fnum = v => String(+(+v).toFixed(2));

  function svgDim(x1, y1, x2, y2, label, focus) {
    const hor = Math.abs(y2 - y1) < 0.01;
    const t1 = hor ? `${x1},${y1 - 4} ${x1},${y1 + 4}` : `${x1 - 4},${y1} ${x1 + 4},${y1}`;
    const t2 = hor ? `${x2},${y2 - 4} ${x2},${y2 + 4}` : `${x2 - 4},${y2} ${x2 + 4},${y2}`;
    const mx = (x1 + x2) / 2, my = (y1 + y2) / 2;
    const dx = hor ? 0 : 10, dy = hor ? -6 : 0;
    return `<g class="wv-dim" data-focus="${focus}">
      <line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}"/>
      <polygon points="${t1}"/><polygon points="${t2}"/>
      <text x="${mx + dx}" y="${my + dy}">${label}</text></g>`;
  }

  function renderWellPlan() {
    const L = num($('#wL')), W = num($('#wW')), t = num($('#wT'));
    const nB = parseInt($('#wBrN').value, 10) || 0;
    const Lb = num($('#wLb')), Wb = num($('#wWb'));
    const sD = num($('#wShaftD')), sT = num($('#wShaftT'));
    const footW = L + 2 * t, footH = W + 2 * t;
    const botD = nB > 0 ? Lb + t : 0, topD = nB === 2 ? Lb + t : 0;
    const contW = footW, contH = footH + botD + topD;
    const s = Math.min(340 / Math.max(contW, 0.1), 250 / Math.max(contH, 0.1), 110);
    const ox = 70, oy = 40 + topD * s;
    const bx = (L - Wb) / 2;   // 支室开口左缘（footprint 坐标）
    const VW = 420, VH = 330;
    let g = '';
    // 墙体（footprint 实体）
    g += `<rect class="wv-wall" data-focus="wT" x="${ox}" y="${oy}" width="${footW * s}" height="${footH * s}"/>`;
    if (nB > 0) g += `<rect class="wv-wall" data-focus="wT" x="${ox + bx * s}" y="${oy + (W + t) * s}" width="${(Wb + 2 * t) * s}" height="${(Lb + t) * s}"/>`;
    if (nB === 2) g += `<rect class="wv-wall" data-focus="wT" x="${ox + bx * s}" y="${oy - Lb * s}" width="${(Wb + 2 * t) * s}" height="${(Lb + t) * s}"/>`;
    // 净空（空腔）
    g += `<rect class="wv-void" x="${ox + t * s}" y="${oy + t * s}" width="${L * s}" height="${W * s}"/>`;
    if (nB > 0) g += `<rect class="wv-void" data-focus="wLb" x="${ox + (t + bx) * s}" y="${oy + (W + t) * s}" width="${Wb * s}" height="${Lb * s}"/>`;
    if (nB === 2) g += `<rect class="wv-void" data-focus="wLb" x="${ox + (t + bx) * s}" y="${oy - Lb * s}" width="${Wb * s}" height="${Lb * s}"/>`;
    // 井筒（俯视投影，虚线圆）
    if (sD > 0) {
      const r = (sD / 2 + sT) * s;
      g += `<circle class="wv-dashed" data-focus="wShaftD" cx="${ox + footW * s / 2}" cy="${oy + t * s / 2}" r="${r}"/>`;
      g += `<text class="wv-label" data-focus="wShaftD" x="${ox + footW * s / 2}" y="${oy + t * s / 2 - r - 5}">φ${fnum(sD)}</text>`;
    }
    // 尺寸
    const dimY = oy - 12 - (nB === 2 ? Lb * s : 0);
    g += svgDim(ox, dimY, ox + footW * s, dimY, fnum(L), 'wL');
    g += svgDim(ox - 16, oy, ox - 16, oy + footH * s, fnum(W), 'wW');
    g += `<text class="wv-label" data-focus="wT" x="${ox + 8}" y="${oy + footH * s - 8}">壁 t=${fnum(t)}</text>`;
    if (nB > 0) {
      g += svgDim(ox + (t + bx) * s, oy + (W + t + Lb) * s + 14, ox + (t + bx + Wb) * s, oy + (W + t + Lb) * s + 14, fnum(Wb), 'wWb');
      g += svgDim(ox + (bx + Wb + 2 * t) * s + 12, oy + (W + t) * s, ox + (bx + Wb + 2 * t) * s + 12, oy + (W + t + Lb) * s, fnum(Lb), 'wLb');
    }
    $('#wellPlanSvg').innerHTML =
      `<svg viewBox="0 0 ${VW} ${VH}" role="img" aria-label="井体平面示意">${g}</svg>`;
  }

  function renderWellSect() {
    const W = num($('#wW')), t = num($('#wT'));
    const D = num($('#wD'));
    const baseT = num($('#wBaseT')), padT = num($('#wPadT')), topT = num($('#wTopT'));
    const sD = num($('#wShaftD')), sT = num($('#wShaftT')), sH = num($('#wShaftH'));
    const nB = parseInt($('#wBrN').value, 10) || 0;
    const isConc = $('#wMat').value === 'conc';
    const rB = num($('#wRebarBase')), rW = num($('#wRebarWall')), rT = num($('#wRebarTop'));
    const footW = W + 2 * t, padW = footW + 0.2;
    const stackH = sH + topT + D + baseT + padT;
    const s = Math.min(300 / Math.max(footW, 0.1), 250 / Math.max(stackH, 0.1), 110);
    const cx = 210, ox = cx - footW * s / 2, pox = cx - padW * s / 2;
    const y0 = 30;                    // 井筒顶
    const yTop = y0 + sH * s;         // 顶板顶
    const yBot = yTop + topT * s + D * s;   // 墙底
    const yBase = yBot + baseT * s;
    const VW = 420, VH = 330;
    let g = '';
    // 井筒（虚线）
    if (sD > 0 && sH > 0) {
      g += `<rect class="wv-dashed" data-focus="wShaftH" x="${cx - (sD / 2 + sT) * s}" y="${y0}" width="${(sD + 2 * sT) * s}" height="${sH * s}"/>`;
      g += svgDim(cx + footW * s / 2 + 16, y0, cx + footW * s / 2 + 16, yTop, fnum(sH), 'wShaftH');
    }
    // 顶板
    g += `<rect class="wv-conc" data-focus="wTopT" x="${ox}" y="${yTop}" width="${footW * s}" height="${topT * s}"/>`;
    if (rT > 0) g += `<line class="wv-rebar" x1="${ox + 3}" y1="${yTop + topT * s / 2}" x2="${ox + footW * s - 3}" y2="${yTop + topT * s / 2}"/>`;
    if (topT * s > 16) g += `<text class="wv-label" data-focus="wTopT" x="${cx}" y="${yTop + topT * s / 2 + 3}">顶板 ${fnum(topT)}</text>`;
    // 井壁（左右）
    const wallVis = (x) => `<rect class="wv-wall" data-focus="wT" x="${x}" y="${yTop + topT * s}" width="${t * s}" height="${D * s}"/>`;
    g += wallVis(ox) + wallVis(ox + footW * s - t * s);
    if (isConc && rW > 0) {
      [ox + t * s / 2, ox + footW * s - t * s / 2].forEach(x => {
        g += `<line class="wv-rebar" x1="${x}" y1="${yTop + topT * s + 3}" x2="${x}" y2="${yBot - 3}"/>`;
      });
    }
    if (D * s > 18) g += `<text class="wv-label" data-focus="wT" x="${ox + t * s + 4}" y="${(yTop + topT * s + yBot) / 2}" text-anchor="start">井壁</text>`;
    // 底板
    g += `<rect class="wv-conc" data-focus="wBaseT" x="${ox}" y="${yBot}" width="${footW * s}" height="${baseT * s}"/>`;
    if (rB > 0) g += `<line class="wv-rebar" x1="${ox + 3}" y1="${yBot + baseT * s / 2}" x2="${ox + footW * s - 3}" y2="${yBot + baseT * s / 2}"/>`;
    if (baseT * s > 16) g += `<text class="wv-label" data-focus="wBaseT" x="${cx}" y="${yBot + baseT * s / 2 + 3}">底板 ${fnum(baseT)}</text>`;
    // 垫层
    g += `<rect class="wv-pad" data-focus="wPadT" x="${pox}" y="${yBase}" width="${padW * s}" height="${padT * s}"/>`;
    if (padT * s > 14) g += `<text class="wv-label" data-focus="wPadT" x="${cx}" y="${yBase + padT * s / 2 + 3}">垫层 ${fnum(padT)}</text>`;
    // 尺寸：净深 D（右）、板厚组（左）
    g += svgDim(ox + footW * s + 14, yTop + topT * s, ox + footW * s + 14, yBot, fnum(D), 'wD');
    g += svgDim(pox - 12, yBot, pox - 12, yBase, fnum(baseT), 'wBaseT');
    g += svgDim(pox - 12, yBase, pox - 12, yBase + padT * s, fnum(padT), 'wPadT');
    g += svgDim(pox - 12, yTop, pox - 12, yTop + topT * s, fnum(topT), 'wTopT');
    $('#wellSectSvg').innerHTML =
      `<svg viewBox="0 0 ${VW} ${VH}" role="img" aria-label="井体剖面示意">${g}</svg>`;
  }

  // 点击图元/尺寸 → 定位并高亮对应输入框
  document.querySelectorAll('.well-viz-svg').forEach(box => {
    box.addEventListener('click', (e) => {
      const hit = e.target.closest('[data-focus]');
      if (!hit) return;
      const el = $('#' + hit.dataset.focus);
      if (!el) return;
      el.focus({ preventScroll: false });
      if (el.select) el.select();
      el.classList.remove('flash');
      void el.offsetWidth;              // 重启动画
      el.classList.add('flash');
      setTimeout(() => el.classList.remove('flash'), 1100);
    });
  });

  document.querySelectorAll('.chip[data-well]').forEach(chip => {
    chip.addEventListener('click', () => {
      const p = WELL_PRESETS[chip.dataset.well];
      if (!p) return;
      $('#wName').value = p.name;
      $('#wL').value = p.L; $('#wW').value = p.W; $('#wD').value = p.D;
      $('#wBrN').value = String(p.nB);
      $('#wLb').value = p.Lb; $('#wWb').value = p.Wb;
      syncBranchInputs();
      document.querySelectorAll('.chip[data-well]')
        .forEach(c => c.classList.toggle('on', c === chip));
      recalcWell();
    });
  });
  function syncBranchInputs() {
    const off = $('#wBrN').value === '0';
    $('#wLb').disabled = off; $('#wWb').disabled = off;
  }
  // 几何参数输入 → 只重算文本格，不动表内单价输入框
  ['wL', 'wW', 'wD', 'wT', 'wMat', 'wBrN', 'wLb', 'wWb',
   'wBaseT', 'wPadT', 'wTopT', 'wShaftD', 'wShaftH', 'wShaftT', 'wCount',
   'wRebarBase', 'wRebarWall', 'wRebarTop'].forEach(id => {
    $('#' + id).addEventListener('input', recalcWell);
    $('#' + id).addEventListener('change', recalcWell);
  });
  ['wLedgeW', 'wLedgeH', 'wPadOut'].forEach(id => $('#' + id).addEventListener('input', recalcWell));
  $('#wBrN').addEventListener('change', syncBranchInputs);
  // 材料切换时，井壁单价换到对应那份（用户改过的价分别保留）
  $('#wMat').addEventListener('change', () => {
    const isConc = $('#wMat').value === 'conc';
    const u = WELL_UNIT[rowIdx('wall')];
    $(`input[data-p="${rowIdx('wall')}"]`).value = isConc ? u.priceConc : u.priceBrick;
    recalcWell();
  });
  // 表内改单价 → 只更新该行金额与合计
  $('#wellRows').addEventListener('input', (e) => {
    if (!e.target.matches('input[data-p]')) return;
    const i = +e.target.dataset.p;
    if (WELL_UNIT[i] && WELL_UNIT[i].key === 'wall') {  // 井壁价回存当前材料那份，切换材料不丢
      if ($('#wMat').value === 'conc') WELL_UNIT[i].priceConc = num(e.target);
      else WELL_UNIT[i].priceBrick = num(e.target);
    }
    recalcWell();
  });
  buildWellTable();
  syncBranchInputs();
  recalcWell();
  // 独立字段接项目自定义下拉（毛玻璃组件）；表内 select 保持原生+统一箭头
  if (typeof initCustomSelect === 'function') {
    initCustomSelect('#wMat');
    initCustomSelect('#wBrN');
  }

  /* ==================== 已存井库：保存 / 查看 / 重命名 / 载回 ====================
   * localStorage 永久保存；快照存「当时算出的构件表 + 合计」，点开即看无需重算；
   * 载回则把参数与单价还原进计算器，便于改出「参数类似但不同」的井。
   */
  const LS_KEY = 'gc_well_library_v1';
  const esc = s => String(s ?? '').replace(/[&<>"']/g,
    c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  // 复用项目 ui-confirm 的类与样式（styles.css），本页轻量实现
  function uiConfirm(message) {
    return new Promise(resolve => {
      let ov = document.getElementById('ui-confirm');
      if (ov) ov.remove();
      ov = document.createElement('div');
      ov.id = 'ui-confirm';
      ov.className = 'ui-confirm-overlay open danger';
      ov.innerHTML = `<div class="ui-confirm-box" role="alertdialog" aria-modal="true" aria-label="确认删除">
        <div class="ui-confirm-msg">${esc(message)}</div>
        <div class="ui-confirm-actions">
          <button type="button" class="btn-ghost" data-act="cancel">取消</button>
          <button type="button" class="btn-danger" data-act="ok">确认删除</button>
        </div></div>`;
      document.body.appendChild(ov);
      const done = v => { ov.remove(); resolve(v); };
      ov.querySelector('[data-act="cancel"]').addEventListener('click', () => done(false));
      ov.querySelector('[data-act="ok"]').addEventListener('click', () => done(true));
      ov.addEventListener('mousedown', e => { if (e.target === ov) done(false); });
      ov.addEventListener('keydown', e => { if (e.key === 'Escape') done(false); });
      setTimeout(() => ov.querySelector('[data-act="cancel"]').focus(), 0);
    });
  }

  function loadLib() {
    try { return JSON.parse(localStorage.getItem(LS_KEY)) || []; }
    catch (e) { return []; }
  }
  function saveLib(list) {
    localStorage.setItem(LS_KEY, JSON.stringify(list));
  }

  // 保存时刻的输入快照（载回用）+ 构件表快照（查看用）
  const PARAM_IDS = ['wName', 'wL', 'wW', 'wD', 'wT', 'wMat', 'wBrN', 'wLb', 'wWb',
    'wBaseT', 'wPadT', 'wTopT', 'wShaftD', 'wShaftH', 'wShaftT', 'wCount',
    'wLedgeW', 'wLedgeH', 'wPadOut',
    'wRebarBase', 'wRebarWall', 'wRebarTop'];

  function collectSnapshot() {
    recalcWell();
    const params = {};
    PARAM_IDS.forEach(id => {
      const el = $('#' + id);
      params[id] = el.type === 'number' ? num(el) : el.value;
    });
    const prices = WELL_UNIT.map((u, i) => num($(`#wellRows input[data-p="${i}"]`)));
    const mat = $('#wMat').value;
    if (WELL_UNIT[rowIdx('wall')].priceConc !== undefined) {
      WELL_UNIT[rowIdx('wall')][mat === 'conc' ? 'priceConc' : 'priceBrick'] = prices[rowIdx('wall')];
    }
    const rows = WELL_UNIT.map((u, i) => ({
      label: $(`#wellRows tr:nth-child(${i + 1}) td:first-child`).textContent,
      qty: $(`#wellRows [data-qty="${i}"]`).textContent,
      unit: u.unit,
      price: prices[i],
      sum: $(`#wellRows [data-sum="${i}"]`).textContent,
    }));
    const total = Number(($('#wellTotal').textContent || '0').replace(/,/g, '')) || 0;
    const rebar = readRebarRows();
    const matName = mat === 'conc' ? '混凝土' : '砖砌';
    const nB = parseInt($('#wBrN').value, 10) || 0;
    const digest = `${matName} ${num($('#wL'))}×${num($('#wW'))}×${num($('#wD'))}`
      + (nB > 0 ? ` ＋支${nB}×${num($('#wLb'))}×${num($('#wWb'))}` : '')
      + ` · ${num($('#wCount')) || 1} 座`;
    return { params, prices, rebar, summary: { digest, total, rows } };
  }

  let expandedId = null;   // 当前展开查看的井（内存态）

  function renderLib() {
    const list = loadLib();
    const box = $('#wellLibList');
    if (!list.length) {
      box.innerHTML = '<div class="well-lib-empty">还没有保存过井。调好参数后点「保存当前井」。</div>';
      return;
    }
    box.innerHTML = list.map(rec => `
      <div class="well-item" data-id="${esc(rec.id)}">
        <div class="well-item-row">
          <button type="button" class="well-item-name" data-act="view" title="展开/收起工程量明细">${esc(rec.name)}</button>
          <span class="well-item-digest">${esc(rec.summary.digest)}</span>
          <span class="well-item-total">¥${fmt(rec.summary.total)}</span>
          <span class="well-item-time">${esc(rec.savedAt)}</span>
          <button type="button" class="well-act" data-act="load">载入参数</button>
          <button type="button" class="well-act" data-act="rename">重命名</button>
          <button type="button" class="well-act danger" data-act="del">删除</button>
        </div>
        ${expandedId === rec.id ? `
        <div class="well-detail">
          <table>
            <thead><tr><th>构件 / 项目</th><th class="num">工程量</th><th>单位</th><th class="num">单价 (元)</th><th class="num">合价 (元)</th></tr></thead>
            <tbody>
              ${rec.summary.rows.map(r => `
                <tr><td>${esc(r.label)}</td><td class="num">${esc(r.qty)}</td><td>${esc(r.unit)}</td>
                    <td class="num">${fmt(r.price)}</td><td class="num">${esc(r.sum)}</td></tr>`).join('')}
            </tbody>
          </table>
          <div class="well-detail-foot">
            <span class="well-detail-total">合计 ¥${fmt(rec.summary.total)}</span>
            <button type="button" class="well-act" data-act="load">把参数载入计算器 →</button>
          </div>
        </div>` : ''}
      </div>`).join('');
  }

  $('#wellLibList').addEventListener('click', async (e) => {
    const btn = e.target.closest('[data-act]');
    if (!btn) return;
    const item = btn.closest('.well-item');
    const rec = loadLib().find(r => r.id === item.dataset.id);
    if (!rec) return;
    const act = btn.dataset.act;

    if (act === 'view') {
      expandedId = expandedId === rec.id ? null : rec.id;
      renderLib();
    } else if (act === 'load') {
      loadIntoCalc(rec);
    } else if (act === 'rename') {
      startRename(item, rec);
    } else if (act === 'del') {
      if (await uiConfirm(`删除「${rec.name}」？该井的保存记录将不可恢复。`)) {
        saveLib(loadLib().filter(r => r.id !== rec.id));
        if (expandedId === rec.id) expandedId = null;
        renderLib();
      }
    }
  });

  function loadIntoCalc(rec) {
    PARAM_IDS.forEach(id => {
      const el = $('#' + id);
      if (el.type === 'number') el.value = rec.params[id];
      else el.value = rec.params[id];
    });
    // 单价还原（表内行）；井壁价写回当前材料那份
    rec.prices.forEach((p, i) => {
      const inp = $(`#wellRows input[data-p="${i}"]`);
      if (inp) inp.value = p;
    });
    const wallI = rowIdx('wall');
    if (WELL_UNIT[wallI].priceConc !== undefined) {
      WELL_UNIT[wallI][rec.params.wMat === 'conc' ? 'priceConc' : 'priceBrick'] = rec.prices[wallI];
    }
    // 钢筋逐根表还原
    if (Array.isArray(rec.rebar) && rec.rebar.length) {
      rebarBody.innerHTML = rec.rebar.map(r => rebarRowHtml(r)).join('');
    }
    syncBranchInputs();
    recalcWell();
    expandedId = null;
    renderLib();
    document.querySelector('.tool-card').scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  function startRename(item, rec) {
    const nameBtn = item.querySelector('.well-item-name');
    const input = document.createElement('input');
    input.type = 'text';
    input.className = 'well-rename-input';
    input.maxLength = 40;
    input.value = rec.name;
    nameBtn.replaceWith(input);
    input.focus(); input.select();
    const commit = () => {
      const v = input.value.trim();
      if (v && v !== rec.name) {
        const list = loadLib();
        const hit = list.find(r => r.id === rec.id);
        if (hit) { hit.name = v; saveLib(list); }
      }
      renderLib();
    };
    input.addEventListener('keydown', e => {
      if (e.key === 'Enter') input.blur();
      else if (e.key === 'Escape') { input.value = rec.name; input.blur(); }
    });
    input.addEventListener('blur', commit, { once: true });
  }

  $('#wellSave').addEventListener('click', () => {
    const snap = collectSnapshot();
    const custom = $('#wellSaveName').value.trim();
    const now = new Date();
    const ts = `${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')} `
      + `${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}`;
    const rec = {
      id: 'w' + Date.now().toString(36) + Math.random().toString(36).slice(2, 6),
      name: custom || (($('#wName').value.trim() || '井') + ' ' + ts),
      savedAt: ts,
      params: snap.params,
      prices: snap.prices,
      summary: snap.summary,
    };
    const list = loadLib();
    list.unshift(rec);
    saveLib(list);
    $('#wellSaveName').value = '';
    expandedId = rec.id;          // 保存后直接展开，确认存的就是看到的
    renderLib();
  });
  renderLib();

  /* ==================== 钢筋逐根表（按图实算口径） ====================
   * 依据图纸钢筋表 + 间距标注逐根计：根数 = 布置范围÷间距+1（可手改），
   * 重量 = 根数 × 单根长 × (d²×0.00617)。与含钢量法三行互相对账。
   */
  const rebarUnitKgPerM = d => 0.00617 * d * d;

  function rebarRowHtml(r) {
    r = r || {};
    return `<tr>
      <td><input type="text" data-rf="no" value="${r.no ? esc(r.no) : ''}" placeholder="①"></td>
      <td><select data-rf="d">${[6, 8, 10, 12, 14, 16, 18, 20, 22, 25].map(d =>
        `<option value="${d}"${(+r.d || 14) === d ? ' selected' : ''}>${d}</option>`).join('')}</select></td>
      <td><input class="num" data-rf="len" type="number" min="0" step="10" value="${r.len ?? 1000}"></td>
      <td class="num row-tw">—</td>
      <td><input class="num" data-rf="span" type="number" min="0" step="50" value="${r.span ?? 0}"></td>
      <td><input class="num" data-rf="sp" type="number" min="0" step="10" value="${r.sp ?? 150}"></td>
      <td><input class="num" data-rf="n" type="number" min="0" step="1" value="${r.n ?? 1}"></td>
      <td class="num row-kg">0.0</td>
      <td><input type="text" data-rf="note" value="${r.note ? esc(r.note) : ''}"></td>
      <td><button type="button" class="row-del" title="删除本行" aria-label="删除本行">×</button></td>
    </tr>`;
  }

  function readRebarRows() {
    return Array.from(rebarBody.querySelectorAll('tr')).map(tr => ({
      no: tr.querySelector('[data-rf="no"]').value.trim(),
      d: num(tr.querySelector('[data-rf="d"]')),
      len: num(tr.querySelector('[data-rf="len"]')),
      span: num(tr.querySelector('[data-rf="span"]')),
      sp: num(tr.querySelector('[data-rf="sp"]')),
      n: num(tr.querySelector('[data-rf="n"]')),
      note: tr.querySelector('[data-rf="note"]').value.trim(),
    })).filter(r => r.no || r.len > 0);
  }

  function recalcRebar() {
    if (!rebarBody) return;
    let total = 0;
    rebarBody.querySelectorAll('tr').forEach(tr => {
      const d = num(tr.querySelector('[data-rf="d"]'));
      const len = num(tr.querySelector('[data-rf="len"]'));
      const n = num(tr.querySelector('[data-rf="n"]'));
      const tw = rebarUnitKgPerM(d);
      const kg = n * len / 1000 * tw;
      total += kg;
      tr.querySelector('.row-tw').textContent = fmt(tw, 3);
      tr.querySelector('.row-kg').textContent = fmt(kg, 1);
    });
    const count = Math.max(1, num($('#wCount')) || 1);
    $('#rebarTotal').textContent = fmt(total, 1) + ' kg';
    $('#rebarTotalAll').textContent = fmt(total * count, 1) + ' kg';
    const cmpEl = $('#rebarCmp');
    if (lastSteelEstKg > 0) {
      const diff = total - lastSteelEstKg;
      const pct = (diff / lastSteelEstKg * 100).toFixed(0);
      cmpEl.textContent = `含钢量法 ${fmt(lastSteelEstKg, 0)} kg（按图 ${diff >= 0 ? '+' : ''}${fmt(diff, 0)} / ${pct}%）`;
    } else cmpEl.textContent = '';
  }

  /* A-5 工作井图二 ①~⑧（根数按 @间距 推导，④按内外圈分列，⑤为拉筋） */
  const A5_PRESET = [
    { no: '①', d: 14, len: 6400, span: 3200, sp: 150, n: 22, note: '底板下层+短墙外侧U形通高' },
    { no: '⑥', d: 14, len: 7600, span: 2000, sp: 150, n: 14, note: '底板下层+长墙外侧U形通高' },
    { no: '②', d: 14, len: 1960, span: 3200, sp: 150, n: 22, note: '底板下层短向直筋' },
    { no: '⑦', d: 14, len: 3160, span: 2000, sp: 150, n: 14, note: '底板上层长向直筋' },
    { no: '③', d: 14, len: 2185, span: 1800, sp: 150, n: 26, note: '短墙内侧竖向（2道墙）' },
    { no: '⑧', d: 14, len: 2185, span: 3000, sp: 150, n: 42, note: '长墙内侧竖向（2道墙）' },
    { no: '④内', d: 8, len: 8800, span: 1865, sp: 150, n: 13, note: '水平分布·内圈' },
    { no: '④外', d: 8, len: 10400, span: 1865, sp: 150, n: 13, note: '水平分布·外圈' },
    { no: '⑤', d: 8, len: 210, span: 1865, sp: 450, n: 88, note: '拉筋@450×450' },
  ];

  $('#rebarAdd').addEventListener('click', () => {
    rebarBody.insertAdjacentHTML('beforeend', rebarRowHtml());
    recalcRebar();
  });
  $('#rebarPreset').addEventListener('click', () => {
    rebarBody.innerHTML = A5_PRESET.map(rebarRowHtml).join('');
    recalcRebar();
  });

  /* 按井参数推导典型配筋（保护层按 20mm；U 形筋单根长为近似值，须按图核对） */
  $('#rebarDerive').addEventListener('click', () => {
    const L = num($('#wL')) * 1000, W = num($('#wW')) * 1000, D = num($('#wD')) * 1000;
    const t = num($('#wT')) * 1000, baseT = num($('#wBaseT')) * 1000, topT = num($('#wTopT')) * 1000;
    const nB = parseInt($('#wBrN').value, 10) || 0;
    const Lb = num($('#wLb')) * 1000;
    const isConc = $('#wMat').value === 'conc';
    const c = 20;   // 保护层（mm）
    const leg = baseT + D + topT - 2 * c;               // 墙外侧竖向通高腿长
    const innerP = 2 * (L + W) + nB * 2 * Lb;
    const outerP = 2 * (L + 2 * t) + 2 * (W + 2 * t) + nB * (2 * Lb + t);
    const cl = 2 * (L + t) + 2 * (W + t) + nB * (2 * Lb + t);
    const nAlongL = Math.floor((L + 2 * t) / 150) + 1;  // 沿长向布置的根数
    const nAlongW = Math.floor((W + 2 * t) / 150) + 1;  // 沿短向布置的根数
    const rows = [
      { no: '底下短', d: 14, len: W + 2 * t - 2 * c, span: L + 2 * t, sp: 150, n: nAlongL, note: '底板下层·短向直筋' },
      { no: '底下长', d: 14, len: L + 2 * t - 2 * c, span: W + 2 * t, sp: 150, n: nAlongW, note: '底板下层·长向直筋' },
      { no: '底上短', d: 14, len: W + 2 * t - 2 * c, span: L + 2 * t, sp: 150, n: nAlongL, note: '底板上层·短向直筋' },
      { no: '底上长', d: 14, len: L + 2 * t - 2 * c, span: W + 2 * t, sp: 150, n: nAlongW, note: '底板上层·长向直筋' },
    ];
    if (isConc) {
      rows.push(
        { no: '墙内短', d: 14, len: D + baseT - c, span: W + t, sp: 150,
          n: (Math.floor((W + t) / 150) + 1) * 2, note: '短墙内侧竖向（2道墙）' },
        { no: '墙内长', d: 14, len: D + baseT - c, span: L + t, sp: 150,
          n: (Math.floor((L + t) / 150) + 1) * 2, note: '长墙内侧竖向（2道墙）' },
        { no: '外U短', d: 14, len: 2 * leg + (W + 2 * t - 2 * c), span: L + 2 * t, sp: 150,
          n: nAlongL, note: '⚠ 底板下层+短墙外侧U形，单根长按图核对' },
        { no: '外U长', d: 14, len: 2 * leg + (L + 2 * t - 2 * c), span: W + 2 * t, sp: 150,
          n: nAlongW, note: '⚠ 底板下层+长墙外侧U形，单根长按图核对' },
        { no: '水平内', d: 8, len: innerP, span: D, sp: 150,
          n: Math.floor(D / 150) + 1, note: '水平分布筋·内圈' },
        { no: '水平外', d: 8, len: outerP, span: D, sp: 150,
          n: Math.floor(D / 150) + 1, note: '水平分布筋·外圈' },
        { no: '拉筋', d: 8, len: t + 10, span: D, sp: 450,
          n: Math.round(cl * D / (450 * 450)), note: '拉筋@450×450' },
      );
    } else {
      rows.push({ no: '备注', d: 8, len: 0, span: 0, sp: 150, n: 0, note: '砖砌井壁无墙筋——墙竖向/水平/拉筋行请按图集另计' });
    }
    rebarBody.innerHTML = rows.map(rebarRowHtml).join('');
    recalcRebar();
  });
  rebarBody.addEventListener('input', (e) => {
    const el = e.target;
    if (el.matches('[data-rf="span"], [data-rf="sp"]')) {
      const tr = el.closest('tr');
      const span = num(tr.querySelector('[data-rf="span"]'));
      const sp = num(tr.querySelector('[data-rf="sp"]'));
      if (span > 0 && sp > 0) tr.querySelector('[data-rf="n"]').value = Math.floor(span / sp) + 1;
    }
    recalcRebar();
  });
  rebarBody.addEventListener('click', (e) => {
    const del = e.target.closest('.row-del');
    if (del) { del.closest('tr').remove(); recalcRebar(); }
  });
  buildRebarDefaults();

  function buildRebarDefaults() {
    // 默认载入 A-5 示例（可清空或手改；井库存取会覆盖）
    rebarBody.innerHTML = A5_PRESET.map(rebarRowHtml).join('');
  }
})();

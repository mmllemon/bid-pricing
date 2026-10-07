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
   *   钢筋 = 混凝土构件 × 含钢量（含钢量法估算）；砖砌井壁不计井壁筋；
   *          盖板钢筋按「块数×每块根数」进钢筋逐根表（盖板组），与主体布筋分列
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


  const $ = window.tool$;   // P2: 抽取自 tool-common
  const num = (el) => (window.toolNonNeg || window.toolNum)(el), fmt = window.toolFmt;   // P0-6: 负数钳制（标红+按0算），与 earth/duct 对齐

  /* 参考净空（可改）：常见配电电缆井，非图集替代 */
  const WELL_PRESETS = {
    straight: { name: '直线井', L: 2.0, W: 1.5, D: 2.0, nB: 0, Lb: 0,   Wb: 0 },
    corner:   { name: '转角井', L: 2.5, W: 2.0, D: 2.0, nB: 1, Lb: 2.0, Wb: 2.0 },
    tee:      { name: '三通井', L: 3.0, W: 2.0, D: 2.0, nB: 1, Lb: 1.8, Wb: 2.0 },
    cross:    { name: '四通井', L: 3.0, W: 2.5, D: 2.0, nB: 2, Lb: 1.8, Wb: 2.0 },
  };

  /* 参数 ID 清单（自动保存 + 井库快照共用；提前声明：初始化恢复早于井库段落执行） */
  const PARAM_IDS = ['wName', 'wL', 'wW', 'wD', 'wT', 'wMat', 'wBrN', 'wLb', 'wWb',
    'wBaseT', 'wPadT', 'wTopT', 'wShaftD', 'wShaftH', 'wShaftT', 'wCount',
    'wLipW', 'wLipH', 'wPadOut',
    'cCount', 'cLen', 'cW', 'cT', 'cMainN', 'cMainL', 'cDistN', 'cDistL', 'cEdgeL',
    'wRebarBase', 'wRebarWall', 'wRebarTop'];

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
    { key: 'form',      label: '模板（井壁内＋外、底板外侧、井座外侧）', unit: 'm²', price: 65,  dec: 2 },
    { key: 'render',    label: '抹面（内＋外壁）', unit: 'm²', price: 25,  dec: 2 },
    { key: 'coverSlab', label: '盖板混凝土 C30（预制）', unit: 'm³', price: 620, dec: 3 },
    { key: 'coverAngle', label: '盖板包边角钢 L50×5（每块）', unit: 'm', price: 38, dec: 2 },
    { key: 'jkAngle', label: '接口角钢 L50×5（井座内侧上＋下两圈）', unit: 'm', price: 38, dec: 2 },
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
  /* 盖板钢筋表容器：与 rebarBody 同期取（脚本在 body 末尾，DOM 已就绪）。
     此前它在钢筋段落用 `var` 声明、靠「recalcWell 首调早于赋值」+ 空值守卫兜着——
     那正是同一类初始化顺序隐患，现已按本文件既有约定（DOM 引用集中在头部）处理。 */
  const coverRebarBody = $('#rebarCoverRows');

  function recalcWell() {
    const L = num($('#wL')), W = num($('#wW')), D = num($('#wD')), t = num($('#wT'));
    const nB = parseInt($('#wBrN').value, 10) || 0;
    const Lb = num($('#wLb')), Wb = num($('#wWb'));
    const baseT = num($('#wBaseT')), padT = num($('#wPadT')), topT = num($('#wTopT'));
    const { on: shaftOn, sD, sH, sT } = shaftParams();
    const count = Math.max(1, num($('#wCount')) || 1);
    const isConc = $('#wMat').value === 'conc';

    const clNet  = 2 * (L + t) + 2 * (W + t) + nB * (2 * Lb + t);   // 中心线净长
    const slabA  = (L + 2 * t) * (W + 2 * t) + nB * (Wb + 2 * t) * (Lb + t / 2);
    const po = num($('#wPadOut'));   // 垫层每边外挑宽（默认 0.1；与底板平齐填 0）
    const padA   = (L + 2 * t + 2 * po) * (W + 2 * t + 2 * po)
                 + nB * (Wb + 2 * t + 2 * po) * (Lb + t / 2 + po);
    const outerP = 2 * (L + 2 * t) + 2 * (W + 2 * t) + nB * (2 * Lb + t);
    const innerP = 2 * (L + W) + nB * 2 * Lb;

    // 井座（盖板外侧升至地面的条带，宽=85+15=100，高=板厚+坐浆15）
    const lipW = num($('#wLipW')), lipH = num($('#wLipH'));
    const lipV = outerP * lipW * lipH;
    // 接口角钢（井座内侧、同平面位置两圈）：
    // 上圈=井座内侧上边；下圈=井座与井壁结合处；平面位置相同，
    // 均=井座内侧周界（外缘每边内缩井座宽 lipW，含支室外露段）：
    //   主井室 2(L+2t−2lipW)＋2(W+2t−2lipW)；支室每间 (2Lb+t) 各内缩 4lipW
    const jkIn = Math.max(0, 2 * (L + 2 * t - 2 * lipW) + 2 * (W + 2 * t - 2 * lipW))
        + nB * Math.max(0, 2 * Lb + t - 4 * lipW);
    const jkTop = jkIn;
    const jkLower = jkIn;
    // 井座外侧面积（井座模板）：井座条带外边缘周长（外缘每边外扩 lipW，含支室外露段）× 井座高
    const lipOuterP = 2 * (L + 2 * t + 2 * lipW) + 2 * (W + 2 * t + 2 * lipW)
        + nB * (2 * Lb + t + 4 * lipW);
    const lipForm = (lipW > 0 && lipH > 0) ? lipOuterP * lipH : 0;
    const concQty = {
      base: slabA * baseT,
      wall: clNet * D * t + lipV,
      top:  slabA * topT,
    };
    const rebarRatio = {
      base: num($('#wRebarBase')),
      wall: isConc ? num($('#wRebarWall')) : 0,   // 砖砌井壁不计井壁筋
      top:  num($('#wRebarTop')),
    };

    const cN = num($('#cCount')), cL = num($('#cLen')), cW = num($('#cW')), cT2 = num($('#cT'));
    const cMN = num($('#cMainN')), cML = num($('#cMainL'));
    const cDN = num($('#cDistN')), cDL = num($('#cDistL'));
    const cEL = num($('#cEdgeL'));
    // 计算式（数值代入，随参数刷新）
    const f2 = v => fnum(v);
    const brSlab = nB ? `＋${nB}×(${f2(Wb + 2 * t)}×${f2(Lb + t / 2)})` : '';
    const brPad = nB ? `＋${nB}×(${f2(Wb + 2 * t + 2 * po)}×${f2(Lb + t / 2 + po)})` : '';
    const brCL = nB ? `＋${nB}×(${f2(2 * Lb)}＋${f2(t)})` : '';
    const lipFx = lipV > 0 ? `＋井座${f2(outerP)}×${f2(lipW)}×${f2(lipH)}` : '';
    const lipFormFx = lipForm > 0 ? `＋${f2(lipOuterP)}×${f2(lipH)}（井座外侧）` : '';
    const slabFormFx = topT > 0 ? `＋${f2(slabA)}（现浇顶板底）` : '';
    const fx = [
      `(${f2(L + 2 * t + 2 * po)}×${f2(W + 2 * t + 2 * po)})×${f2(padT)}${brPad}`,   // P0-5: 公式文本与垫层外挑宽 po 联动（原写死 +0.2）
      `(${f2(L + 2 * t)}×${f2(W + 2 * t)})×${f2(baseT)}${brSlab}`,
      `${f2(concQty.base)}×${f2(rebarRatio.base)}`,
      `(${f2(2 * (L + t))}＋${f2(2 * (W + t))}${brCL})×${f2(D)}×${f2(t)}${lipFx}`,
      isConc ? `${f2(concQty.wall)}×${f2(rebarRatio.wall)}` : '—（砖砌不计）',
      (cT2 > 0 && cN > 0 ? '※ 与预制盖板重复？' : '') +
      `(${f2(L + 2 * t)}×${f2(W + 2 * t)})×${f2(topT)}${brSlab}`,
      (cT2 > 0 && cN > 0 ? '※ ' : '') + `${f2(concQty.top)}×${f2(rebarRatio.top)}`,
      shaftOn ? `π×(${f2(sD)}＋${f2(sT)})×${f2(sH)}×${f2(sT)}` : '—（未计入井筒）',
      isConc ? `2×${f2(clNet)}×${f2(D)}${lipFormFx}＋${f2(outerP)}×${f2(baseT)}${slabFormFx}`
             : `${f2(outerP)}×${f2(baseT)}${lipFormFx}${slabFormFx}`,
      `(${f2(innerP)}＋${f2(outerP)})×${f2(D)}`,
      `${f2(cN)}×(${f2(cL)}×${f2(cW)})×${f2(cT2)}`,
      `${f2(cN)}×${f2(cEL / 1000)} m`,
      `${f2(jkTop)}＋${f2(jkLower)} m（上＋下圈同位置=井座内侧周界，外缘内缩${f2(lipW)}）`,
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
        case 'form':   return (isConc ? 2 * clNet * D : 0) + outerP * baseT + lipForm + (topT > 0 ? slabA : 0);   // 接触面积：井壁内＋外（砖砌不支模）＋底板外侧＋井座外侧（lipW>0）＋现浇顶板底
        case 'render': return (innerP + outerP) * D;
        case 'coverSlab':  return cN * cL * cW * cT2;
        case 'coverAngle': return cN * cEL / 1000;
        case 'jkAngle':    return (lipW > 0 && lipH > 0) ? jkTop + jkLower : 0;   // P0-4: 与井座模板同守卫，默认 lipW/lipH=0 时不计入
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
    saveWellSoon();   // P1: 自动保存（500ms 防抖），与其他三工具对齐
  }

  /* ==================== 井体示意（SVG 平面 + 剖面） ====================
   * 示意图非施工图：两图比例各自独立，随参数实时重绘。
   * 图元与尺寸标注带 data-focus，点击定位并高亮对应输入框。
   */
  /* 数值格式化。用**函数声明**而不是 const 箭头函数：声明被提升到作用域顶部，
     首调早于本行也不会踩 TDZ（见下方 recalcWell 的启动路径）。 */
  function fnum(v) { return (+v).toFixed(2); }

  /* 盖板钢筋直径（φ14，与 A-5 口径一致）；定义在头部：recalcWell 首调早于钢筋段落，须可引用 */
  const COVER_REBAR_D = 14;

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
    const { sD, sH, sT } = shaftParams();
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
    // 井筒（俯视投影，虚线圆，位于主井室中心）
    if (sD > 0 && sH > 0) {   // 井筒高 0 = 无井筒，平面不画投影圆
      const r = (sD / 2 + sT) * s;
      const ccx = ox + footW * s / 2, ccy = oy + footH * s / 2;
      g += `<circle class="wv-dashed" data-focus="wShaftD" cx="${ccx}" cy="${ccy}" r="${r}"/>`;
      g += `<text class="wv-label" data-focus="wShaftD" x="${ccx}" y="${ccy - r - 5}">φ${fnum(sD)}</text>`;
    }
    // 尺寸（净长/净宽跨净空起讫，线与数值一致）
    const dimY = oy - 12 - (nB === 2 ? Lb * s : 0);
    g += svgDim(ox + t * s, dimY, ox + (L + t) * s, dimY, fnum(L), 'wL');
    g += svgDim(ox - 16, oy + t * s, ox - 16, oy + (W + t) * s, fnum(W), 'wW');
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
    const { sD, sH, sT } = shaftParams();
    const nB = parseInt($('#wBrN').value, 10) || 0;
    const isConc = $('#wMat').value === 'conc';
    const rW = num($('#wRebarWall')), rT = num($('#wRebarTop'));
    const lipW = num($('#wLipW')), lipH = num($('#wLipH'));
    const footW = W + 2 * t, padW = footW + 0.2;
    const stackH = topT + 0.015 + D + baseT + padT + sH;
    const s = Math.min(300 / Math.max(footW, 0.1), 240 / Math.max(stackH, 0.1), 110);
    const cx = 210, ox = cx - footW * s / 2, pox = cx - padW * s / 2;
    const yG = 28 + sH * s;                        // 地面 = 盖板顶 = 井座顶
    const yCoverBot = yG + topT * s;               // 盖板底
    const ySeat = yCoverBot + Math.max(0, lipH - topT) * s;   // 搁置台顶（坐浆 15 之下）
    const yBot = ySeat + D * s;                    // 底板顶
    const yBaseBot = yBot + baseT * s, yPadBot = yBaseBot + padT * s;
    const covX = ox + lipW * s, covW = footW * s - 2 * lipW * s;
    let g = '';
    if (sD > 0 && sH > 0) {
      g += `<rect class="wv-dashed" data-focus="wShaftH" x="${cx - (sD / 2 + sT) * s}" y="${yG - sH * s}" width="${(sD + 2 * sT) * s}" height="${sH * s}"/>`;
    }
    g += `<rect class="wv-conc" data-focus="wTopT" x="${covX}" y="${yG}" width="${covW}" height="${topT * s}"/>`;
    if (rT > 0 && topT > 0) g += `<line class="wv-rebar" x1="${covX + 3}" y1="${yG + topT * s / 2}" x2="${covX + covW - 3}" y2="${yG + topT * s / 2}"/>`;
    if (topT > 0 && topT * s > 12) g += `<text class="wv-label" data-focus="wTopT" x="${cx}" y="${yG + topT * s / 2 + 3}">盖板 ${fnum(topT)}</text>`;
    const yLipBot = Math.max(ySeat, yCoverBot);   // 井座底（lipH ≤ topT 时不外凸，坐浆消失）
    const sitH = Math.max(0, lipH - topT);      // 坐浆厚 = 井座高出盖板的部分
    const wallPoly = (pts) => `<polygon class="wv-wall" data-focus="wT" points="${pts}"/>`;
    g += wallPoly(`${ox},${yG} ${ox + lipW * s},${yG} ${ox + lipW * s},${yLipBot} ${ox + t * s},${yLipBot} ${ox + t * s},${yBot} ${ox},${yBot}`);
    g += wallPoly(`${ox + footW * s - lipW * s},${yG} ${ox + footW * s},${yG} ${ox + footW * s},${yBot} ${ox + footW * s - t * s},${yBot} ${ox + footW * s - t * s},${yLipBot} ${ox + footW * s - lipW * s},${yLipBot}`);
    if (sitH > 0) {
      g += `<line class="wv-mortar" x1="${covX}" y1="${yCoverBot + sitH * s / 2}" x2="${ox + t * s}" y2="${yCoverBot + sitH * s / 2}"/>`;
      g += `<line class="wv-mortar" x1="${ox + footW * s - t * s}" y1="${yCoverBot + sitH * s / 2}" x2="${covX + covW}" y2="${yCoverBot + sitH * s / 2}"/>`;
    }
    // 接口角钢/锚筋不画示意（工程量在钢筋逐根表与构件表中）
    if (isConc && rW > 0) {
      [ox + 2, ox + footW * s - 2].forEach(x => {
        g += `<line class="wv-rebar" x1="${x}" y1="${yG + 3}" x2="${x}" y2="${yBot - 3}"/>`;
      });
      [ox + t * s - 2, ox + footW * s - t * s + 2].forEach(x => {
        g += `<line class="wv-rebar" x1="${x}" y1="${yLipBot + 3}" x2="${x}" y2="${yBot - 3}"/>`;
      });
    }
    if (D * s > 18) g += `<text class="wv-label" data-focus="wT" x="${ox + t * s + 4}" y="${(yLipBot + yBot) / 2}" text-anchor="start">井壁</text>`;
    if (lipW > 0 && lipH > 0) {
      g += `<text class="wv-label" data-focus="wLipW" x="${ox + lipW * s / 2}" y="${(yG + yLipBot) / 2}">井座</text>`;
    }
    g += svgDim(ox + footW * s + 14, yLipBot, ox + footW * s + 14, yBot, fnum(D), 'wD');
    if (lipH > 0) g += svgDim(ox - 16, yG, ox - 16, yLipBot, fnum(lipH), 'wLipH');
    g += svgDim(pox - 12, yBot, pox - 12, yBaseBot, fnum(baseT), 'wBaseT');
    g += svgDim(pox - 12, yBaseBot, pox - 12, yPadBot, fnum(padT), 'wPadT');
    // 垫层 / 底板实体
    if (padT > 0) {
      g += `<rect class="wv-pad" data-focus="wPadT" x="${pox}" y="${yBaseBot}" width="${padW * s}" height="${padT * s}"/>`;
      if (padT * s > 12) g += `<text class="wv-label" data-focus="wPadT" x="${cx}" y="${yBaseBot + padT * s / 2 + 3}">垫层 ${fnum(padT)}</text>`;
    }
    if (baseT > 0) {
      g += `<rect class="wv-conc" data-focus="wBaseT" x="${ox}" y="${yBot}" width="${footW * s}" height="${baseT * s}"/>`;
      if (baseT * s > 14) g += `<text class="wv-label" data-focus="wBaseT" x="${cx}" y="${yBot + baseT * s / 2 + 3}">底板 ${fnum(baseT)}</text>`;
    }
    $('#wellSectSvg').innerHTML =
      `<svg viewBox="0 0 420 ${yPadBot + 26}" role="img" aria-label="井体剖面示意">${g}</svg>`;
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
      const brSel = $('#wBrN');   // P1: 毛玻璃下拉显示同步（此前只改原生 select，按钮文字不变）
      if (brSel && brSel.__cs) brSel.__cs.refresh();
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
  /* 井筒：选做项。开关关闭时三参数一律按 0 取值（工程量与平面/剖面示意同步归零），
   * 输入框置灰但保留原填值，重新勾上即恢复 —— 省掉"每口井手动填 0"这一步。 */
  function shaftParams() {
    const on = $('#wShaftOn').checked;
    return on
      ? { on, sD: num($('#wShaftD')), sH: num($('#wShaftH')), sT: num($('#wShaftT')) }
      : { on, sD: 0, sH: 0, sT: 0 };
  }
  function syncShaftInputs() {
    const off = !$('#wShaftOn').checked;
    ['wShaftD', 'wShaftH', 'wShaftT'].forEach(id => { $('#' + id).disabled = off; });
    $('#wShaftOn').closest('.tool-group').classList.toggle('off', off);
  }
  // 几何参数输入 → 只重算文本格，不动表内单价输入框
  ['wL', 'wW', 'wD', 'wT', 'wMat', 'wBrN', 'wLb', 'wWb',
   'wBaseT', 'wPadT', 'wTopT', 'wShaftD', 'wShaftH', 'wShaftT', 'wCount',
   'wRebarBase', 'wRebarWall', 'wRebarTop'].forEach(id => {
    $('#' + id).addEventListener('input', recalcWell);
    $('#' + id).addEventListener('change', recalcWell);
  });
  ['wLipW', 'wLipH', 'wPadOut', 'cCount', 'cLen', 'cW', 'cT',
   'cMainN', 'cMainL', 'cDistN', 'cDistL', 'cEdgeL'].forEach(id => $('#' + id).addEventListener('input', recalcWell));
  $('#wBrN').addEventListener('change', syncBranchInputs);
  $('#wShaftOn').addEventListener('change', () => { syncShaftInputs(); recalcWell(); });
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
  /* ---------- 自动保存 / 恢复（P1：与其他三工具对齐，刷新不丢数） ---------- */
  const AUTO_KEY = 'tool-well';
  const canAutosave = Boolean(window.toolStore && window.toolDebounce);
  function saveWellNow() {
    if (!canAutosave) return;
    const o = {};
    PARAM_IDS.forEach(id => {
      const el = $('#' + id);
      if (el) o[id] = el.value;
    });
    o.wShaftOn = $('#wShaftOn').checked;
    window.toolStore.save(AUTO_KEY, o);
  }
  const saveWellSoon = window.toolAutosave(AUTO_KEY, saveWellNow);   // P2: 抽取自 tool-common（内部已含缺失退化）
  function applyWellState(s) {
    if (!s || !canAutosave) return false;
    try {
      PARAM_IDS.forEach(id => {
        const el = $('#' + id);
        if (el && s[id] !== undefined) el.value = s[id];
      });
      if (s.wShaftOn !== undefined) $('#wShaftOn').checked = !!s.wShaftOn;
      // 自定义下拉（毛玻璃）显示同步
      ['wMat', 'wBrN'].forEach(id => {
        const sel = $('#' + id);
        if (sel && sel.__cs) sel.__cs.refresh();
      });
      syncBranchInputs();
      syncShaftInputs();
      return true;
    } catch (e) { return false; }
  }

  buildWellTable();
  syncBranchInputs();
  syncShaftInputs();
  applyWellState(canAutosave ? window.toolStore.load(AUTO_KEY) : null);
  recalcWell();
  window.addEventListener('pagehide', saveWellNow);
  // 独立字段接项目自定义下拉（毛玻璃组件）；表内 select 保持原生+统一箭头
  if (typeof initCustomSelect === 'function') {
    initCustomSelect('#wMat');
    initCustomSelect('#wBrN');
  }

  /* ==================== 已存井库：保存 / 查看 / 重命名 / 载回 ====================
   * 落盘后端 well-library.json（outputs/projects/<user>/），不再走浏览器 localStorage；
   * 快照存「当时算出的构件表 + 合计」，点开即看无需重算；
   * 载回则把参数与单价还原进计算器，便于改出「参数类似但不同」的井。
   */
  const LS_KEY = 'gc_well_library_v1';   // 旧键：仅一次性迁移用，迁完即删
  // 后端基地址：与 tool-cable 同口径（window.__API_BASE__ 覆盖；按主机名推导支持局域网；file:// 回退 localhost）
  const API_BASE = window.__API_BASE__
    || (location.hostname ? location.protocol + '//' + location.hostname + ':8000' : 'http://localhost:8000');
  // 可选鉴权：服务端启用 BIDPRICING_API_TOKEN 时，token 存 sessionStorage（关闭标签即失），随请求自动附带
  // F-P0-2：不再读 localStorage 永久存储；旧存量走 app.js 的 fetch 包装迁移，此处只认 sessionStorage + 内存
  function wellAuthHeaders() {
    let t = '';
    try { t = (sessionStorage.getItem('bidpricingApiToken') || '').trim(); } catch (e) {}
    return t ? { Authorization: 'Bearer ' + t } : {};
  }

  let libCache = null;   // 内存缓存：井库数组（首屏一次 GET，后续走缓存）
  let libDown = false;   // 后端不可用标记（未起 run.ps1 / 网络不通）

  function readLegacyLib() {
    try { return JSON.parse(localStorage.getItem(LS_KEY)) || []; }
    catch (e) { return []; }
  }

  async function postLib(list) {
    const r = await fetch(API_BASE + '/api/well-library/save', {
      method: 'POST',
      headers: Object.assign({ 'Content-Type': 'application/json' }, wellAuthHeaders()),
      body: JSON.stringify({ items: list }),
    });
    if (!r.ok) throw new Error('HTTP ' + r.status);
    const j = await r.json();
    if (!j || j.status !== 'PASS') throw new Error((j && j.reason) || '保存被拒绝');
  }

  async function loadLib() {
    if (libCache) return libCache;
    libDown = false;
    try {
      const r = await fetch(API_BASE + '/api/well-library/list', { headers: wellAuthHeaders() });
      if (!r.ok) throw new Error('HTTP ' + r.status);
      const j = await r.json();
      let items = (j && Array.isArray(j.items)) ? j.items : [];
      // 一次性迁移：后端为空且浏览器有旧数据 → 整表导入，成功后删旧键
      const legacy = readLegacyLib();
      if (!items.length && legacy.length) {
        try {
          await postLib(legacy);
          try { localStorage.removeItem(LS_KEY); } catch (e) {}
          items = legacy;
        } catch (e) { /* 迁移失败则保留旧键，下次再试 */ }
      }
      libCache = items;
      return items;
    } catch (e) {
      libDown = true;
      return [];
    }
  }
  // 井库保存：整表回写后端；失败（后端未起/超限/被拒绝）返回 false，调用方给可见提示
  async function saveLib(list) {
    try {
      await postLib(list);
      libCache = list;
      libDown = false;
      return true;
    } catch (e) {
      libDown = true;
      return false;
    }
  }
  // P1: 井库快照 schema 版本。v1 = 无 schema 字段（2026-10-06 前）；v2 起写入 schema。
  // 迁移规则集中在 migrateSnapshotPrices，下次增删构件行只改这里，不再散落魔数。
  const SCHEMA_WELL_LIB = 2;
  function migrateSnapshotPrices(prices, schema) {
    let p = Array.isArray(prices) ? prices.slice() : [];
    if ((schema || 1) < 2 && p.length > WELL_UNIT.length) {
      p = p.slice(0, 11).concat(p.slice(12));   // v1→v2：剔除已移除的「盖板钢筋 φ14」行（旧 index 11）
    }
    return p;
  }
  // 转义统一走共享助手（tool-common.js 的 toolEsc = escape.js 的 gcEsc）。
  // 与 tool-cable.js:36 / tool-earth.js 同一写法，本文件不再自持第三份副本。
  const esc = window.toolEsc;

  // 确认弹窗：调用统一走 tool-common 的 window.toolConfirm（P2 抽取），
  // 其**实现唯一在 js/confirm.js**（全站唯一创建 #ui-confirm 的地方）；本页无模态栈 → 不参与焦点陷阱。

  // （井库读写已迁后端：见上方 loadLib/saveLib 异步实现）

  // 保存时刻的输入快照（载回用）+ 构件表快照（查看用）
  // 注：PARAM_IDS 已上移至文件头部（自动保存共用）

  function collectSnapshot() {
    recalcWell();
    const params = {};
    PARAM_IDS.forEach(id => {
      const el = $('#' + id);
      params[id] = el.type === 'number' ? num(el) : el.value;
    });
    params.wShaftOn = $('#wShaftOn').checked;   // 复选框 checked 态（el.value 恒为 "on"，不能走上面那套取值）
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
    return { schema: SCHEMA_WELL_LIB, params, prices, rebar, summary: { digest, total, rows } };
  }

  let expandedId = null;   // 当前展开查看的井（内存态）

  async function renderLib() {
    const list = await loadLib();
    const box = $('#wellLibList');
    if (libDown) {
      box.innerHTML = '<div class="well-lib-empty">井库服务不可用：后端未启动（请运行 run.ps1）。已存的井在后端恢复后自动出现，参数自动保存不受影响。</div>';
      return;
    }
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
    const rec = (await loadLib()).find(r => r.id === item.dataset.id);
    if (!rec) return;
    const act = btn.dataset.act;

    if (act === 'view') {
      expandedId = expandedId === rec.id ? null : rec.id;
      await renderLib();
    } else if (act === 'load') {
      await loadIntoCalc(rec);
    } else if (act === 'rename') {
      startRename(item, rec);
    } else if (act === 'del') {
      if (await window.toolConfirm(`删除「${rec.name}」？该井的保存记录将不可恢复。`)) {
        await saveLib((await loadLib()).filter(r => r.id !== rec.id));
        if (expandedId === rec.id) expandedId = null;
        await renderLib();
      }
    }
  });

  async function loadIntoCalc(rec) {
    PARAM_IDS.forEach(id => {
      const el = $('#' + id);
      if (rec.params[id] === undefined) return;   // 旧存档缺新键 → 保留现值
      el.value = rec.params[id];
    });
    // P1: 毛玻璃下拉（wMat/wBrN）显示同步（此前只改原生 select，按钮文字不变）
    ['wMat', 'wBrN'].forEach(id => {
      const sel = $('#' + id);
      if (sel && sel.__cs) sel.__cs.refresh();
    });
    // 井筒开关：旧存档没有该键 → 按"计入"还原，与当时算出的口径一致
    $('#wShaftOn').checked = rec.params.wShaftOn !== false;
    // 单价还原（表内行）；井壁价写回当前材料那份。
    // P1: 快照 schema 集中迁移（migrateSnapshotPrices），替代此前的魔数 slice
    let prices = migrateSnapshotPrices(rec.prices, rec.schema);
    prices.forEach((p, i) => {
      const inp = $(`#wellRows input[data-p="${i}"]`);
      if (inp) inp.value = p;
    });
    const wallI = rowIdx('wall');
    if (WELL_UNIT[wallI].priceConc !== undefined) {
      WELL_UNIT[wallI][rec.params.wMat === 'conc' ? 'priceConc' : 'priceBrick'] = prices[wallI];
    }
    // 钢筋逐根表还原（主体布筋；盖板组由 c* 参数自动重生成）
    if (Array.isArray(rec.rebar) && rec.rebar.length) {
      rebarBody.innerHTML = rec.rebar.map(r => rebarRowHtml(r)).join('');
    }
    syncBranchInputs();
    syncShaftInputs();
    recalcWell();
    expandedId = null;
    await renderLib();
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
    const commit = async () => {
      const v = input.value.trim();
      if (v && v !== rec.name) {
        const list = await loadLib();
        const hit = list.find(r => r.id === rec.id);
        if (hit) { hit.name = v; await saveLib(list); }
      }
      await renderLib();
    };
    input.addEventListener('keydown', e => {
      if (e.key === 'Enter') input.blur();
      else if (e.key === 'Escape') { input.value = rec.name; input.blur(); }
    });
    input.addEventListener('blur', commit, { once: true });
  }

  $('#wellSave').addEventListener('click', async () => {
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
      rebar: snap.rebar,   // 修复：此前 collectSnapshot 采了 rebar 但保存时丢弃，载入的还原分支是死代码
      summary: snap.summary,
    };
    const list = await loadLib();
    list.unshift(rec);
    const saveBtn = $('#wellSave');
    const old = saveBtn.textContent;
    if (!(await saveLib(list))) {
      // 井库落盘后端：失败（后端未起/超限/被拒绝）给可见提示
      saveBtn.textContent = '保存失败（后端不可用或存储空间不足）';
      setTimeout(() => { saveBtn.textContent = old; }, 2000);
      return;
    }
    $('#wellSaveName').value = '';
    expandedId = rec.id;          // 保存后直接展开，确认存的就是看到的
    await renderLib();
  });
  renderLib();

  /* ==================== 钢筋逐根表（按图实算口径） ====================
   * 依据图纸钢筋表 + 间距标注逐根计：根数 = 布置范围÷间距+1（可手改），
   * 重量 = 根数 × 单根长 × (d²×0.00617)。与含钢量法三行互相对账。
   * 盖板钢筋（预制盖板）单列一组：随盖板参数自动重算（kg），与主体布筋分开计。
   */
  /* 钢筋单位重量 kg/m = d²×0.00617。**函数声明**（提升到作用域顶部）：recalcWell 的启动
     路径会先于本行调用 recalcRebar，原先写成 const 箭头函数时全靠「启动瞬间钢筋表为空、
     forEach 体一次都不执行」侥幸不炸——靠数据巧合撑着，不是靠代码性质撑着。
     （另一处同类侥幸：fnum 被 nB>0 的启动路径调用，见文件头部注释。） */
  function rebarUnitKgPerM(d) { return 0.00617 * d * d; }

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

  /* 盖板钢筋（预制盖板 φ14）：随 c* 参数自动生成两行，与主体布筋分组区分 */
  function renderCoverRebarRows() {
    if (!coverRebarBody) return;
    const cN = num($('#cCount')), cMN = num($('#cMainN')), cML = num($('#cMainL'));
    const cDN = num($('#cDistN')), cDL = num($('#cDistL'));
    const w = rebarUnitKgPerM(COVER_REBAR_D);   // 与主体布筋同一公式（唯一实现，不再内联一份）
    const row = (no, lenMm, n, note) => `<tr class="rebar-cov">
      <td>${no}</td>
      <td>φ${COVER_REBAR_D}</td>
      <td class="num">${lenMm || 0}</td>
      <td class="num">${fmt(w, 3)}</td>
      <td class="num off">—</td>
      <td class="num off">—</td>
      <td class="num">${n || 0}</td>
      <td class="num row-kg">${fmt(n * (lenMm || 0) / 1000 * w, 1)}</td>
      <td class="cov-note">${note}</td>
      <td></td>
    </tr>`;
    coverRebarBody.innerHTML =
      `<tr class="rebar-grp"><td colspan="10">盖板钢筋（预制盖板，随上方参数自动生成 · φ${COVER_REBAR_D}）</td></tr>`
      + row('盖①', cML, cN * cMN, `块数 ${cN || 0} × 每块主筋 ${cMN || 0} 根`)
      + row('盖②', cDL, cN * cDN, `块数 ${cN || 0} × 每块分布筋 ${cDN || 0} 根`);
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
    // 盖板钢筋组：随 c* 参数重生成并重算
    renderCoverRebarRows();
    let coverTotal = 0;
    if (coverRebarBody) coverRebarBody.querySelectorAll('tr.rebar-cov').forEach(tr => {
      coverTotal += Number(String(tr.querySelector('.row-kg').textContent).replace(/,/g, '')) || 0;
    });
    const count = Math.max(1, num($('#wCount')) || 1);
    $('#rebarTotal').textContent = fmt(total, 1) + ' kg';
    const covEl = $('#rebarCoverTotal');
    if (covEl) covEl.textContent = fmt(coverTotal, 1) + ' kg';
    $('#rebarTotalAll').textContent = fmt((total + coverTotal) * count, 1) + ' kg';
    const cmpEl = $('#rebarCmp');
    if (lastSteelEstKg > 0) {
      const diff = total - lastSteelEstKg;
      const pct = (diff / lastSteelEstKg * 100).toFixed(0);
      const warn = Math.abs(diff / lastSteelEstKg) >= 0.15 ? ' ※ 差异较大，请以钢筋逐根表为准' : '';
      cmpEl.textContent = `含钢量法 ${fmt(lastSteelEstKg, 0)} kg vs 主体按图 ${fmt(total, 0)} kg（${diff >= 0 ? '+' : ''}${fmt(diff, 0)} / ${pct}%）· 未含盖板钢筋 ${fmt(coverTotal, 0)} kg${warn}`;
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
    { no: '锚筋', d: 6, len: 180, span: 8800, sp: 300, n: 29, note: '锚固接口角钢，沿墙顶一圈' },
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
          n: nAlongL, note: '※ 底板下层+短墙外侧U形，单根长按图核对' },
        { no: '外U长', d: 14, len: 2 * leg + (L + 2 * t - 2 * c), span: W + 2 * t, sp: 150,
          n: nAlongW, note: '※ 底板下层+长墙外侧U形，单根长按图核对' },
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
  /* ---------- 复制工程量表（TSV，可直接粘贴到 Excel） ---------- */
  function buildWellTsv() {
    const lines = [];
    const wName = $('#wName').value.trim();
    lines.push('电缆井工程量速算' + (wName ? '（' + wName + '）' : ''));
    lines.push(['构件/项目', '工程量', '单位', '计算式', '参考单价(元)', '合价(元)'].join('\t'));
    document.querySelectorAll('#wellRows tr').forEach(tr => {
      const cells = tr.querySelectorAll('td');
      if (cells.length < 6) return;
      const priceInput = cells[4].querySelector('input');
      lines.push([
        cells[0].textContent.trim(),
        cells[1].textContent.trim(),
        cells[2].textContent.trim(),
        cells[3].textContent.trim().replace(/\s+/g, ' '),
        priceInput ? priceInput.value : '',
        cells[5].textContent.trim(),
      ].join('\t'));
    });
    lines.push(['合计', '', '', '', '',
      document.querySelector('#wellTotal').textContent.trim()].join('\t'));
    return lines.join('\n');
  }
  $('#wellCopy').addEventListener('click', async (e) => {
    const btn = e.currentTarget;
    const ok = await window.toolCopyText(buildWellTsv());
    const old = btn.textContent;
    btn.textContent = ok ? '已复制 ✓' : '复制失败';
    setTimeout(() => { btn.textContent = old; }, 1500);
  });

  buildRebarDefaults();

  function buildRebarDefaults() {
    // 默认载入 A-5 示例（可清空或手改；井库存取会覆盖）；盖板组随 c* 参数生成
    rebarBody.innerHTML = A5_PRESET.map(rebarRowHtml).join('');
    renderCoverRebarRows();
    recalcRebar();
  }
})();

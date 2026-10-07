/**
 * 工程智算 · 像素神经网络全景大盘引擎 (High-Performance Neural Engine)
 * 1. 级联伞状开花生长：模块主节点 -> 触须生长 -> 二级分支节点 -> 触须依次伞状开花生长 -> 三级业务卡片 -> 深度控制舱
 * 2. 极致性能优化：移除每帧 innerHTML 重绘，改用静态 SVG 节点缓存 + setAttribute('d'/'cx'/'cy') 属性就地更新，彻底消除 DOM 重排
 * 3. 展开态下全模块自由平滑点击切换
 * 4. 项目经营及各板块专属深度控制舱（概况/报价/执行/文档/待办及实时内嵌操作）
 */
(function (global) {
  'use strict';

  var container = null;
  var dustCanvas = null;
  var dustCtx = null;
  var svgThreads = null;
  var nodesLayer = null;
  var branchesLayer = null;
  var fanLayer = null;
  var drawer = null;
  var breadcrumbEl = null;

  var animFrameId = null;
  var lastTime = performance.now();

  // SVG 元素缓存，避免每帧 innerHTML
  var svgCache = {
    orbits: [],
    modThreads: {},
    branchThreads: [],
    leafThreads: []
  };

  // —— 阻尼弹簧物理积分器 (k=62, c=2*sqrt(k)) ——
  function spring(st, target, dt, k) {
    if (k === undefined) k = 62;
    var c = 2 * Math.sqrt(k);
    st.v += (-k * (st.x - target) - c * st.v) * dt;
    st.x += st.v * dt;
    return st.x;
  }
  function sp(x) { return { x: x, v: 0 }; }
  function clamp(v, a, b) { return Math.max(a, Math.min(b, v)); }

  // —— 三次贝塞尔点插值 ——
  function bez(p0, p1, p2, p3, u) {
    var m = 1 - u;
    return m * m * m * p0 + 3 * m * m * u * p1 + 3 * m * u * u * p2 + u * u * u * p3;
  }

  // —— 110 颗星尘微粒 ——
  var DUST = Array.from({ length: 110 }, function (_, i) {
    return {
      a: i * 2.39996,
      v: 0.035 + (i * 37 % 100) / 100 * 0.06,
      o: (i * 0.618034) % 1,
      w: (i % 2 ? 1 : -1) * (0.15 + (i % 7) * 0.05),
      s: 1.2 + (i % 5) * 0.6,
      b: 0.45 + (i % 3) * 0.25,
      c: i % 2 === 0 ? '255, 107, 0' : '229, 160, 0'
    };
  });

  // —— 运行时活体状态 (Live Engine State) ——
  var live = {
    stage: 'hub',       // 'hub' | 'module' | 'item'
    mod: null,          // 当前选中的模块 ID
    branch: null,       // 当前选中的二级分支节点 ID
    item: null,         // 当前选中的三级数据条目 ID
    time: 0,
    branchStart: 0,     // 二级分支节点开花起始时间
    leafStart: 0,       // 三级叶子卡片开花起始时间
    branchState: [],    // 二级分支节点的弹簧数组
    leafState: [],      // 三级叶子卡片的弹簧数组
    size: { w: 1200, h: 800 },
    springs: {
      orb: { x: sp(600), y: sp(400), s: sp(150), o: sp(1) },
      dust: sp(0.4),
      jelly: {}
    }
  };

  // 初始化模块的弹簧状态
  function initModuleSprings() {
    var mods = global.PORTAL_DATA ? global.PORTAL_DATA.modules : [];
    mods.forEach(function (m) {
      live.springs.jelly[m.id] = {
        x: sp(600),
        y: sp(400),
        s: sp(76),
        o: sp(1),
        cur: { x: 600, y: 400, s: 76 }
      };
    });
  }

  // 排序槽位计算（选中的模块平滑滑到列中间位置）
  function slotOf(selId, id) {
    var mods = global.PORTAL_DATA.modules;
    var others = mods.filter(function (m) { return m.id !== selId; }).map(function (m) { return m.id; });
    var half = Math.floor(others.length / 2);
    var order = others.slice(0, half).concat([selId]).concat(others.slice(half));
    var k = order.indexOf(id);
    return k < 0 ? mods.findIndex(function (m) { return m.id === id; }) : k;
  }

  // —— 布局目标计算 (Targets Calculation) ——
  function targets(L, t) {
    var W = L.size.w;
    var H = L.size.h;
    var st = L.stage;
    var narrow = W < 860;
    var res = { orb: {}, jelly: {}, branches: null, leaves: null };
    var mods = global.PORTAL_DATA ? global.PORTAL_DATA.modules : [];

    if (st === 'hub') {
      // 对齐 neural 首页构图：一颗足够大的核心锚定全场，模块均布在扁椭圆上贴向边缘。
      var s = narrow ? clamp(W * 0.34, 150, 210) : clamp(Math.min(W, H) * 0.43, 240, 380);
      var cy = narrow ? H * 0.5 : H * 0.52;
      res.orb = { x: W / 2, y: cy, s: s };

      var rx = narrow ? W * 0.36 : Math.min(W * 0.37, 560);
      var ry = narrow ? H * 0.31 : Math.min(H * 0.31, 272);

      mods.forEach(function (m, i) {
        // 卫星均布在一圈上（从正上方起逆时针），避免角度不均造成两两聚堆
        var base = -90 + (i * 360) / Math.max(mods.length, 1);
        var a = (base + 5 * Math.sin(t * 0.16 + i * 1.6)) * Math.PI / 180;
        var r = 1 + 0.035 * Math.sin(t * 0.2 + i);
        res.jelly[m.id] = {
          x: W / 2 + Math.cos(a) * rx * r,
          y: cy + Math.sin(a) * ry * r + 6 * Math.sin(t * 0.7 + i * 2.1),
          s: narrow ? 78 : clamp(W * 0.099, 104, 124),
          o: 1,
          tilt: 0
        };
      });
    } else {
      // 展开态：核心退左，三列「模块 → 分支 → 卡片」整体居中铺开，列距收敛而不留大片空白。
      var drawerW = L.stage === 'item' ? 420 : 0;   // 抽屉打开时占用的右侧宽度
      var availRight = W - drawerW - 24;            // 三列可用的右边界
      var ox = narrow ? 44 : Math.max(52, W * 0.05);
      var cy2 = H * 0.5;
      res.orb = { x: ox, y: cy2, s: narrow ? 110 : 150 };

      // 模块列：N 个纵向排开，卡片必须小于行距，否则会互相压住
      var step = Math.min(122, (H - 150) / Math.max(mods.length, 1));
      var cardSel = Math.min(104, step - 6);
      var cardOther = Math.min(84, step - 6);

      // 三列宽度与列距（居中铺开）
      var cardW = 120, branchW = 130, leafW = 262;
      var gapA = narrow ? 150 : 200;
      var gapB = narrow ? 170 : 220;
      var totalW = cardW + gapA + branchW + gapB + leafW;
      var startX = Math.max(ox + 96, (availRight - totalW) / 2);
      var col1_x = startX + cardW / 2;
      var col2_x = startX + cardW + gapA;
      var col3_x = startX + cardW + gapA + branchW + gapB;

      mods.forEach(function (m) {
        var sel = m.id === L.mod;
        var k = slotOf(L.mod, m.id);
        res.jelly[m.id] = {
          x: col1_x + (sel ? 16 : 0),
          y: cy2 + (k - (mods.length - 1) / 2) * step,
          s: sel ? cardSel : cardOther,
          o: sel ? 1 : 0.5,
          tilt: 0
        };
      });

      // 第 2 列：二级分支节点 (Branch Nodes)
      var brs = global.PORTAL_DATA.getBranches(L.mod);
      var bn = brs.length;
      var bSpan = Math.max(0, bn - 1) * 76;

      res.branches = {
        x: col2_x,
        y0: cy2 - bSpan / 2,
        gap: bn > 1 ? bSpan / (bn - 1) : 0
      };

      // 第 3 列：三级实体卡片 (Leaf Cards)
      var leafItems = global.PORTAL_DATA.getItems(L.mod, L.branch);
      var ln = leafItems.length;
      var lSpan = Math.min(H - 150, Math.max(0, ln - 1) * 60);

      res.leaves = {
        x: col3_x,
        y0: cy2 - lSpan / 2,
        gap: ln > 1 ? lSpan / (ln - 1) : 0
      };
    }

    return res;
  }

  // —— 静态 SVG 结构初始化 ——
  function initSvgStructure() {
    if (!svgThreads) return;
    svgThreads.innerHTML = '';
    svgCache.orbits = [];
    svgCache.modThreads = {};
    svgCache.branchThreads = [];
    svgCache.leafThreads = [];

    // 1. 同心轨道环（与放大的核心配套）
    [220, 380, 540].forEach(function (cr, cidx) {
      var c = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
      c.setAttribute('class', 'portal-orbit-ring ring-' + cidx);
      svgThreads.appendChild(c);
      svgCache.orbits.push({ el: c, r: cr });
    });

    // 2. 主模块连线与脉冲
    var mods = global.PORTAL_DATA ? global.PORTAL_DATA.modules : [];
    mods.forEach(function (m) {
      var g = document.createElementNS('http://www.w3.org/2000/svg', 'g');

      var glow = document.createElementNS('http://www.w3.org/2000/svg', 'path');
      glow.setAttribute('fill', 'none');
      g.appendChild(glow);

      var core = document.createElementNS('http://www.w3.org/2000/svg', 'path');
      core.setAttribute('fill', 'none');
      g.appendChild(core);

      var pulses = [];
      [0, 1, 2].forEach(function (k) {
        var circle = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
        circle.setAttribute('fill', m.color);
        circle.setAttribute('r', k === 2 ? '3' : '3.8');
        g.appendChild(circle);
        pulses.push(circle);
      });

      svgThreads.appendChild(g);
      svgCache.modThreads[m.id] = { g: g, glow: glow, core: core, pulses: pulses };
    });
  }

  // 重置分支节点 SVG 连线
  function rebuildBranchSvg(mod) {
    if (!svgThreads) return;
    // 移除旧的分支与叶子连线
    svgCache.branchThreads.forEach(function (item) { item.g.remove(); });
    svgCache.branchThreads = [];
    svgCache.leafThreads.forEach(function (item) { item.g.remove(); });
    svgCache.leafThreads = [];

    var brs = mod.branches || [];
    brs.forEach(function () {
      var g = document.createElementNS('http://www.w3.org/2000/svg', 'g');
      var path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
      path.setAttribute('fill', 'none');
      g.appendChild(path);

      var pulse = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
      pulse.setAttribute('fill', mod.color);
      pulse.setAttribute('r', '2.5');
      g.appendChild(pulse);

      svgThreads.appendChild(g);
      svgCache.branchThreads.push({ g: g, path: path, pulse: pulse });
    });
  }

  // 重置三级叶子卡片 SVG 连线
  function rebuildLeafSvg(mod) {
    if (!svgThreads) return;
    svgCache.leafThreads.forEach(function (item) { item.g.remove(); });
    svgCache.leafThreads = [];

    var leafItems = global.PORTAL_DATA.getItems(mod.id, live.branch);
    leafItems.forEach(function () {
      var g = document.createElementNS('http://www.w3.org/2000/svg', 'g');
      var path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
      path.setAttribute('fill', 'none');
      g.appendChild(path);

      var pulses = [];
      [0, 1].forEach(function () {
        var p = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
        p.setAttribute('fill', mod.color);
        p.setAttribute('r', '2.4');
        g.appendChild(p);
        pulses.push(p);
      });

      svgThreads.appendChild(g);
      svgCache.leafThreads.push({ g: g, path: path, pulses: pulses });
    });
  }

  // —— 主步进引擎 (Step Engine) ——
  function step(now) {
    var dt = Math.max(0, Math.min(1 / 30, (now - lastTime) / 1000));
    lastTime = now;
    live.time += dt;

    if (container) {
      var realW = container.clientWidth || window.innerWidth;
      var realH = container.clientHeight || window.innerHeight;
      if (realW > 100 && realH > 100) {
        live.size = { w: realW, h: realH };
      }
    }

    var t = live.time;
    var S = live.springs;
    var T = targets(live, t);

    // 1. 中心核心弹簧
    var ox = spring(S.orb.x, T.orb.x, dt);
    var oy = spring(S.orb.y, T.orb.y, dt);
    var os = spring(S.orb.s, T.orb.s, dt, 40);
    var oo = spring(S.orb.o, 1, dt, 30);

    var orbEl = document.getElementById('portalCoreHub');
    if (orbEl) {
      orbEl.style.transform = 'translate3d(' + (ox - os / 2) + 'px, ' + (oy - os / 2) + 'px, 0) scale(' + (os / 340) + ')';
      orbEl.style.opacity = clamp(oo, 0, 1);
    }

    // 2. 星尘微粒 Canvas 渲染
    if (dustCtx && dustCanvas) {
      dustCtx.clearRect(0, 0, dustCanvas.width, dustCanvas.height);
      var dInt = clamp(spring(S.dust, live.stage === 'hub' ? 0.8 : 0.32, dt, 18), 0, 1);

      if (dInt > 0.02) {
        var cx = ox;
        var cy = oy;
        for (var pi = 0; pi < DUST.length; pi++) {
          var p = DUST[pi];
          var ph = ((t * p.v + p.o) % 1 + 1) % 1;
          var r = (os * 0.45) + ph * (os * 0.95);
          var a = p.a + ph * p.w;
          var px = cx + Math.cos(a) * r;
          var py = cy + Math.sin(a) * r * 0.94;
          var al = dInt * Math.pow(Math.max(0, Math.sin(ph * Math.PI)), 1.3) * p.b;

          dustCtx.fillStyle = 'rgba(' + p.c + ', ' + al + ')';
          dustCtx.fillRect(px - p.s / 2, py - p.s / 2, p.s, p.s);
        }
      }
    }

    // 3. 同心轨道更新 (只改属性)
    svgCache.orbits.forEach(function (item) {
      if (live.stage === 'hub') {
        item.el.setAttribute('cx', ox);
        item.el.setAttribute('cy', oy);
        item.el.style.display = 'block';
      } else {
        item.el.style.display = 'none';
      }
    });

    // 4. 模块卫星节点弹簧与神经光缆
    var mods = global.PORTAL_DATA ? global.PORTAL_DATA.modules : [];
    mods.forEach(function (m, i) {
      var j = S.jelly[m.id];
      var tg = T.jelly[m.id];
      if (!j || !tg) return;

      var x = spring(j.x, tg.x, dt);
      var y = spring(j.y, tg.y, dt);
      var s = spring(j.s, tg.s, dt);
      var o = spring(j.o, tg.o, dt, 40);
      j.cur = { x: x, y: y, s: s };

      var el = document.getElementById('portal-mod-' + m.id);
      if (el) {
        el.style.transform = 'translate3d(' + (x - s / 2) + 'px, ' + (y - s / 2) + 'px, 0) scale(' + (s / 120) + ') rotate(' + tg.tilt + 'deg)';
        el.style.opacity = clamp(o, 0, 1);
        el.classList.toggle('node-active', m.id === live.mod);
        el.classList.toggle('node-dimmed', live.stage !== 'hub' && m.id !== live.mod);
      }

      // —— 中心核心 -> 主模块连线与脉冲 ——
      var tObj = svgCache.modThreads[m.id];
      if (tObj) {
        var dx = x - ox;
        var dy = y - oy;
        var dist = Math.hypot(dx, dy) || 1;
        var ux = dx / dist;
        var uy = dy / dist;

        var x1 = ox + ux * os * 0.35;
        var y1 = oy + uy * os * 0.35;
        var x2 = x - ux * s * 0.4;
        var y2 = y - uy * s * 0.4;

        var bend = live.stage === 'hub' ? 22 * Math.sin(t * 0.5 + i) : 4;
        var c1x = x1 + dx * 0.35 - uy * bend;
        var c1y = y1 + dy * 0.35 + ux * bend;
        var c2x = x1 + dx * 0.7 + uy * bend;
        var c2y = y1 + dy * 0.7 - ux * bend;

        var dPath = 'M' + x1 + ',' + y1 + ' C' + c1x + ',' + c1y + ' ' + c2x + ',' + c2y + ' ' + x2 + ',' + y2;
        var isActive = m.id === live.mod;
        var strokeColor = isActive ? m.color : 'rgba(17, 17, 17, 0.22)';
        var strokeWidth = isActive ? 2.5 : 1.2;

        tObj.glow.setAttribute('d', dPath);
        tObj.glow.setAttribute('stroke', strokeColor);
        tObj.glow.setAttribute('stroke-width', strokeWidth * 2);
        tObj.glow.setAttribute('stroke-opacity', isActive ? '0.3' : '0.08');

        tObj.core.setAttribute('d', dPath);
        tObj.core.setAttribute('stroke', strokeColor);
        tObj.core.setAttribute('stroke-width', strokeWidth);
        tObj.core.setAttribute('stroke-opacity', clamp(o, 0, 1));

        tObj.pulses.forEach(function (circle, k) {
          var inbound = k === 2;
          var u = ((t * (inbound ? 0.24 : 0.32) + k * 0.48 + i * 0.16) % 1);
          if (inbound) u = 1 - u;
          var cx = bez(x1, c1x, c2x, x2, u);
          var cy = bez(y1, c1y, c2y, y2, u);
          circle.setAttribute('cx', cx);
          circle.setAttribute('cy', cy);
          circle.setAttribute('opacity', Math.sin(u * Math.PI) * clamp(o, 0, 1));
        });
      }
    });

    // 5. 级联伞状开花生长：
    // (A) 主模块 -> 二级分支节点 (Branch Nodes)
    if (T.branches && live.mod) {
      var currentMod = global.PORTAL_DATA.getModule(live.mod);
      var branches = global.PORTAL_DATA.getBranches(live.mod);
      var sj = S.jelly[live.mod];

      if (sj) {
        var mOx = sj.cur.x + sj.cur.s * 0.5 + 4;
        var mOy = sj.cur.y;

        branches.forEach(function (b, bi) {
          if (!live.branchState[bi]) {
            live.branchState[bi] = { x: sp(mOx), y: sp(mOy), o: sp(0) };
          }
          var bst = live.branchState[bi];
          var bReady = now - live.branchStart > 60 + bi * 80;
          var bTx = T.branches.x;
          var bTy = T.branches.y0 + bi * T.branches.gap + Math.sin(t * 0.8 + bi) * 2;

          var bX = spring(bst.x, bReady ? bTx : mOx, dt, 70);
          var bY = spring(bst.y, bReady ? bTy : mOy, dt, 70);
          var bO = spring(bst.o, bReady ? 1 : 0, dt, 50);
          bst.cur = { x: bX, y: bY };

          var bEl = document.getElementById('portal-branch-' + b.id);
          if (bEl) {
            bEl.style.transform = 'translate3d(' + bX + 'px, ' + (bY - 19) + 'px, 0)';
            bEl.style.opacity = clamp(bO, 0, 1);
            bEl.classList.toggle('branch-active', b.id === live.branch);
          }

          var bSvgObj = svgCache.branchThreads[bi];
          if (bSvgObj) {
            if (bO > 0.02) {
              var bdx = bX - mOx;
              var bsway = Math.sin(t * 1.0 + bi * 0.8) * 5;
              var bc1x = mOx + bdx * 0.45;
              var bc1y = mOy + bsway;
              var bc2x = bX - bdx * 0.4;
              var bc2y = bY - bsway * 0.5;

              var bp = 'M' + mOx + ',' + mOy + ' C' + bc1x + ',' + bc1y + ' ' + bc2x + ',' + bc2y + ' ' + bX + ',' + bY;
              var isBrSel = b.id === live.branch;
              bSvgObj.path.setAttribute('d', bp);
              bSvgObj.path.setAttribute('stroke', isBrSel ? currentMod.color : 'rgba(17,17,17,0.3)');
              bSvgObj.path.setAttribute('stroke-width', isBrSel ? '2.2' : '1.2');
              bSvgObj.path.setAttribute('stroke-opacity', clamp(bO, 0, 1));

              var bfu = ((t * 0.35 + bi * 0.2) % 1);
              var bfcx = bez(mOx, bc1x, bc2x, bX, bfu);
              var bfcy = bez(mOy, bc1y, bc2y, bY, bfu);
              bSvgObj.pulse.setAttribute('cx', bfcx);
              bSvgObj.pulse.setAttribute('cy', bfcy);
              bSvgObj.pulse.setAttribute('opacity', clamp(bO, 0, 1) * Math.sin(bfu * Math.PI));
              bSvgObj.g.style.display = 'block';
            } else {
              bSvgObj.g.style.display = 'none';
            }
          }
        });
      }
    }

    // (B) 选中的二级分支节点 -> 三级实体卡片 (Leaf Cards) 伞状开花生长
    if (T.leaves && live.mod && live.branch) {
      var currentMod2 = global.PORTAL_DATA.getModule(live.mod);
      var leafItems = global.PORTAL_DATA.getItems(live.mod, live.branch);
      var branches2 = global.PORTAL_DATA.getBranches(live.mod);
      var activeBrIdx = branches2.findIndex(function (b) { return b.id === live.branch; });

      var activeBrState = live.branchState[activeBrIdx];
      if (activeBrState && activeBrState.cur) {
        var brOx = activeBrState.cur.x + 130 + 4;
        var brOy = activeBrState.cur.y;

        leafItems.forEach(function (it, li) {
          if (!live.leafState[li]) {
            live.leafState[li] = { x: sp(brOx), y: sp(brOy), o: sp(0) };
          }
          var lst = live.leafState[li];

          var leafReady = now - live.leafStart > 60 + li * Math.min(70, 700 / Math.max(leafItems.length, 1));
          var lTx = T.leaves.x;
          var lTy = T.leaves.y0 + li * T.leaves.gap + Math.sin(t * 0.75 + li * 0.8) * 2;

          var lx = spring(lst.x, leafReady ? lTx : brOx, dt, 70);
          var ly = spring(lst.y, leafReady ? lTy : brOy, dt, 70);
          var lo = spring(lst.o, leafReady ? 1 : 0, dt, 50);

          var itEl = document.getElementById('portal-item-' + it.id);
          if (itEl) {
            itEl.style.transform = 'translate3d(' + lx + 'px, ' + (ly - 24) + 'px, 0)';
            itEl.style.opacity = clamp(lo, 0, 1);
            itEl.classList.toggle('item-selected', live.item === it.id);
          }

          var lSvgObj = svgCache.leafThreads[li];
          if (lSvgObj) {
            if (lo > 0.02) {
              var ldx = lx - brOx;
              var lsway = Math.sin(t * 1.1 + li * 0.7) * 6;
              var lc1x = brOx + ldx * 0.45;
              var lc1y = brOy + lsway;
              var lc2x = lx - ldx * 0.4;
              var lc2y = ly - lsway * 0.5;

              var lp = 'M' + brOx + ',' + brOy + ' C' + lc1x + ',' + lc1y + ' ' + lc2x + ',' + lc2y + ' ' + lx + ',' + ly;
              var isLeafSel = live.item === it.id;
              lSvgObj.path.setAttribute('d', lp);
              lSvgObj.path.setAttribute('stroke', isLeafSel ? currentMod2.color : 'rgba(17, 17, 17, 0.28)');
              lSvgObj.path.setAttribute('stroke-width', isLeafSel ? '2.2' : '1.2');
              lSvgObj.path.setAttribute('stroke-opacity', clamp(lo, 0, 1));

              lSvgObj.pulses.forEach(function (pCircle, k) {
                var lfu = ((t * (k ? 0.28 : 0.36) + li * 0.14 + k * 0.5) % 1);
                if (k) lfu = 1 - lfu;
                var lfcx = bez(brOx, lc1x, lc2x, lx, lfu);
                var lfcy = bez(brOy, lc1y, lc2y, ly, lfu);
                pCircle.setAttribute('cx', lfcx);
                pCircle.setAttribute('cy', lfcy);
                pCircle.setAttribute('opacity', clamp(lo, 0, 1) * Math.sin(lfu * Math.PI));
              });

              lSvgObj.g.style.display = 'block';
            } else {
              lSvgObj.g.style.display = 'none';
            }
          }
        });
      }
    }
  }

  // —— 动画循环 ——
  function loop(now) {
    if (!container || container.classList.contains('hidden')) {
      animFrameId = requestAnimationFrame(loop);
      return;
    }

    var w = container.clientWidth || window.innerWidth;
    var h = container.clientHeight || window.innerHeight;
    if (dustCanvas && (dustCanvas.width !== w || dustCanvas.height !== h)) {
      dustCanvas.width = w;
      dustCanvas.height = h;
      live.size = { w: w, h: h };
    }

    animFrameId = requestAnimationFrame(loop);
    try {
      step(now);
    } catch (err) {
      console.error('[PortalView] step error:', err);
    }
  }

  // —— 交互分流：选择模块主节点 (第一层 -> 第二层) ——
  function selectModule(modId, targetBranchId) {
    var mod = global.PORTAL_DATA.getModule(modId);
    if (!mod) return;

    var brs = mod.branches || [];
    var brId = targetBranchId;
    if (!brId && brs.length > 0) {
      var def = brs.find(function (b) { return b.isDefault; });
      brId = def ? def.id : brs[0].id;
    }

    live.stage = 'module';
    live.mod = modId;
    live.branch = brId;
    live.item = null;

    var now = performance.now();
    live.branchStart = now;
    live.leafStart = now + 40;

    live.branchState = brs.map(function () { return null; });
    var items = global.PORTAL_DATA.getItems(modId, brId);
    live.leafState = items.map(function () { return null; });

    container.className = 'portal-view stage-module';

    rebuildBranchSvg(mod);
    rebuildLeafSvg(mod);

    updateBreadcrumb();
    renderBranchesDOM(mod);
    renderLeavesDOM(mod);
    closeDrawer();
  }

  // —— 交互分流：点击切换二级分支节点 (Branch Node) ——
  function selectBranch(branchId) {
    if (!live.mod || live.branch === branchId) return;
    var mod = global.PORTAL_DATA.getModule(live.mod);
    if (!mod) return;

    live.branch = branchId;
    live.item = null;
    live.leafStart = performance.now();

    var items = global.PORTAL_DATA.getItems(live.mod, branchId);
    live.leafState = items.map(function () { return null; });

    rebuildLeafSvg(mod);
    updateBreadcrumb();
    renderLeavesDOM(mod);
    closeDrawer();
  }

  // —— 交互分流：点击三级业务实体卡片 (Leaf Card -> 深度控制舱) ——
  function selectItem(itemId) {
    var mod = global.PORTAL_DATA.getModule(live.mod);
    if (!mod) return;
    var it = global.PORTAL_DATA.getItem(live.mod, live.branch, itemId);
    if (!it) return;

    live.stage = 'item';
    live.item = itemId;
    container.className = 'portal-view stage-item';

    updateBreadcrumb();
    openDrawer(mod, it);
  }

  // —— 逐层退回 ——
  function stepBack() {
    if (live.stage === 'item') {
      selectModule(live.mod, live.branch);
    } else if (live.stage === 'module') {
      returnToHub();
    }
  }

  function returnToHub() {
    live.stage = 'hub';
    live.mod = null;
    live.branch = null;
    live.item = null;
    container.className = 'portal-view stage-hub';

    if (svgThreads) {
      svgCache.branchThreads.forEach(function (item) { item.g.remove(); });
      svgCache.branchThreads = [];
      svgCache.leafThreads.forEach(function (item) { item.g.remove(); });
      svgCache.leafThreads = [];
    }

    updateBreadcrumb();
    if (branchesLayer) branchesLayer.innerHTML = '';
    if (fanLayer) fanLayer.innerHTML = '';
    closeDrawer();
  }

  // —— 渲染二级分支节点 DOM (Branch Nodes) ——
  function renderBranchesDOM(mod) {
    if (!branchesLayer) return;
    var brs = mod.branches || [];
    var html = '';

    brs.forEach(function (b) {
      html += '<button type="button" class="portal-branch-node" id="portal-branch-' + b.id + '" data-id="' + b.id + '">';
      html += '  <div class="branch-anchor-in" style="background:' + mod.color + '"></div>';
      html += '  <div class="branch-content">';
      html += '    <div class="branch-code" style="color:' + mod.color + '">' + b.code + '</div>';
      html += '    <div class="branch-title">' + b.label + '</div>';
      html += '  </div>';
      html += '  <div class="branch-anchor-out" style="background:' + mod.color + '"></div>';
      html += '</button>';
    });

    branchesLayer.innerHTML = html;

    brs.forEach(function (b) {
      var btn = document.getElementById('portal-branch-' + b.id);
      if (btn) {
        btn.onclick = function (e) {
          e.stopPropagation();
          selectBranch(b.id);
        };
      }
    });
  }

  // —— 渲染三级实体卡片 DOM (Leaf Cards) ——
  function renderLeavesDOM(mod) {
    if (!fanLayer) return;
    var items = global.PORTAL_DATA.getItems(mod.id, live.branch);
    var html = '<div class="fan-items-list">';

    items.forEach(function (it) {
      html += '<button type="button" class="portal-fan-card" id="portal-item-' + it.id + '" data-id="' + it.id + '">';
      html += '  <div class="card-anchor-dot" style="background:' + mod.color + '"></div>';
      html += '  <div class="card-left"><span class="pixel-num">' + it.code + '</span></div>';
      html += '  <div class="card-mid">';
      html += '    <div class="card-title">' + it.title + '</div>';
      html += '    <div class="card-desc">' + (it.desc || '') + '</div>';
      html += '  </div>';
      if (it.stage) {
        html += '  <div class="card-right"><span class="stage-tag ' + (it.stage === '投标' ? 'tag-bid' : (it.stage === '中标在建' ? 'tag-build' : 'tag-done')) + '">' + it.stage + '</span></div>';
      }
      html += '</button>';
    });

    html += '</div>';
    fanLayer.innerHTML = html;

    items.forEach(function (it) {
      var btn = document.getElementById('portal-item-' + it.id);
      if (btn) {
        btn.onclick = function (e) {
          e.stopPropagation();
          selectItem(it.id);
        };
      }
    });
  }

  // —— 渲染第四层：动态业务深度分析抽屉 (Analysis Drawer) ——
  function openDrawer(mod, it) {
    if (!drawer) return;

    var html = '';

    html += '<div class="ad-head">';
    html += '  <div class="ad-badge-group">';
    html += '    <span class="pixel-tag" style="background:' + mod.color + ';color:#fff">' + mod.code + '</span>';
    html += '    <span class="pixel-badge">' + (mod.group === 'engineering' ? '工程主链' : '经营管理') + '</span>';
    if (it.stage) {
      html += '    <span class="pixel-badge stage-badge">' + it.stage + '</span>';
    }
    html += '  </div>';
    html += '  <button type="button" class="ad-close-btn" id="portalDrawerCloseBtn" aria-label="关闭">&times;</button>';
    html += '</div>';

    html += '<h2 class="ad-title">' + it.title + '</h2>';
    html += '<div class="ad-sub">' + (it.code || '') + ' · 业务要素深度分析与控制舱</div>';

    // 项目经营专属 Tabs 结构
    if (mod.id === 'biz' && it.profile) {
      html += '<div class="ad-tabs-header">';
      html += '  <button type="button" class="ad-tab-btn active" data-tab="tab-overview">概况</button>';
      html += '  <button type="button" class="ad-tab-btn" data-tab="tab-quote">报价</button>';
      html += '  <button type="button" class="ad-tab-btn" data-tab="tab-exec">执行</button>';
      html += '  <button type="button" class="ad-tab-btn" data-tab="tab-docs">文档 (' + (it.docs ? it.docs.length : 0) + ')</button>';
      html += '  <button type="button" class="ad-tab-btn" data-tab="tab-todos">待办 (' + (it.todos ? it.todos.length : 0) + ')</button>';
      html += '</div>';

      // 1. 概况
      html += '<div class="ad-tab-content active" id="tab-overview">';
      html += '  <div class="ad-kv-list">';
      html += '    <div class="kv-item"><span class="k">合同编号</span><strong class="v">' + it.profile.contractNo + '</strong></div>';
      html += '    <div class="kv-item"><span class="k">建设单位</span><strong class="v">' + it.profile.client + '</strong></div>';
      html += '    <div class="kv-item"><span class="k">承建单位</span><strong class="v">' + it.profile.builder + '</strong></div>';
      html += '    <div class="kv-item"><span class="k">开标时间</span><strong class="v">' + it.profile.openDate + '</strong></div>';
      html += '    <div class="kv-item"><span class="k">工程体量</span><strong class="v">' + it.profile.scale + '</strong></div>';
      html += '  </div>';
      html += '  <div class="ad-stage-switcher">';
      html += '    <span class="switcher-label">快速流转阶段：</span>';
      ['投标', '中标在建', '已竣工', '未中标'].forEach(function (st) {
        var isCurrent = it.stage === st;
        html += '    <button type="button" class="btn-stage-switch ' + (isCurrent ? 'active' : '') + '" data-st="' + st + '">' + st + '</button>';
      });
      html += '  </div>';
      html += '</div>';

      // 2. 报价
      html += '<div class="ad-tab-content" id="tab-quote">';
      html += '  <div class="ad-metrics-grid">';
      html += '    <div class="ad-metric-box"><span class="m-label">目标总报价</span><strong class="m-val">¥ ' + it.quote.targetTotal + '</strong></div>';
      html += '    <div class="ad-metric-box"><span class="m-label">下浮率</span><strong class="m-val" style="color:#ff6b00">' + it.quote.rate + '</strong></div>';
      html += '    <div class="ad-metric-box"><span class="m-label">安全防线</span><strong class="m-val">' + it.quote.guardrail + '</strong></div>';
      html += '  </div>';
      html += '  <div class="ad-kv-list" style="margin-top:10px">';
      html += '    <div class="kv-item"><span class="k">固定税前项</span><strong class="v">¥ ' + it.quote.fixedPretax + '</strong></div>';
      html += '    <div class="kv-item"><span class="k">增值税/附加税</span><strong class="v">' + it.quote.vatRate + ' / ' + it.quote.surtaxRate + '</strong></div>';
      html += '  </div>';
      html += '  <button type="button" class="pixel-btn-action" id="btnApplyToQuote">带入此项目进入投标报价沙盘 →</button>';
      html += '</div>';

      // 3. 执行
      html += '<div class="ad-tab-content" id="tab-exec">';
      html += '  <div class="ad-progress-box"><div class="p-head"><span>综合进度</span><strong>' + it.progress + '%</strong></div><div class="p-bar"><div class="p-fill" style="width:' + it.progress + '%"></div></div></div>';
      html += '  <div class="ad-kv-list">';
      html += '    <div class="kv-item"><span class="k">当前状态</span><strong class="v">' + it.execution.status + '</strong></div>';
      html += '    <div class="kv-item"><span class="k">项目团队</span><strong class="v">' + it.execution.team + '</strong></div>';
      html += '    <div class="kv-item"><span class="k">风控评级</span><strong class="v">' + it.execution.riskLevel + '</strong></div>';
      html += '  </div>';
      html += '</div>';

      // 4. 文档
      html += '<div class="ad-tab-content" id="tab-docs">';
      html += '  <div class="ad-doc-list">';
      (it.docs || []).forEach(function (doc) {
        html += '    <div class="doc-row">';
        html += '      <div class="doc-info"><span class="doc-icon">📄</span><span class="doc-name">' + doc.name + '</span><span class="doc-meta">' + doc.size + ' · ' + doc.time + '</span></div>';
        html += '      <button type="button" class="doc-btn-view" data-file="' + doc.name + '">查阅</button>';
        html += '    </div>';
      });
      html += '  </div>';
      html += '</div>';

      // 5. 待办
      html += '<div class="ad-tab-content" id="tab-todos">';
      html += '  <div class="ad-todo-list">';
      (it.todos || []).forEach(function (td) {
        html += '    <label class="todo-check-row">';
        html += '      <input type="checkbox" class="todo-check-box" data-id="' + td.id + '" ' + (td.done ? 'checked' : '') + ' />';
        html += '      <span class="todo-text ' + (td.done ? 'done' : '') + '">' + td.text + '</span>';
        html += '    </label>';
      });
      html += '  </div>';
      html += '  <div class="ad-add-todo-bar"><input type="text" id="newTodoInput" placeholder="输入并新增此项目待办..." /><button type="button" id="btnAddTodo">添加</button></div>';
      html += '</div>';

    } else {
      // 其他板块专属结构
      html += '<p class="ad-desc">' + it.desc + '</p>';

      if (it.metrics && it.metrics.length > 0) {
        html += '<div class="ad-metrics-grid">';
        it.metrics.forEach(function (m) {
          html += '<div class="ad-metric-box"><span class="m-label">' + m[0] + '</span><strong class="m-val">' + m[1] + '</strong></div>';
        });
        html += '</div>';
      }

      if (it.planDetail) {
        html += '<div class="ad-section-title">方案推演控制参数</div>';
        html += '<div class="ad-kv-list">';
        html += '  <div class="kv-item"><span class="k">目标总价</span><strong class="v">¥ ' + it.planDetail.targetTotal + '</strong></div>';
        html += '  <div class="kv-item"><span class="k">预估毛利</span><strong class="v">' + it.planDetail.grossProfit + ' (' + it.planDetail.grossMargin + ')</strong></div>';
        html += '  <div class="kv-item"><span class="k">不平衡项数</span><strong class="v">' + it.planDetail.unbalancedCount + ' 项</strong></div>';
        html += '</div>';
        html += '<button type="button" class="pixel-btn-action" id="btnApplySlot">设为基准对比槽位 →</button>';
      }

      if (it.costDetail) {
        html += '<div class="ad-section-title">责任成本核对凭据</div>';
        html += '<div class="ad-kv-list">';
        html += '  <div class="kv-item"><span class="k">预算额</span><strong class="v">¥ ' + it.costDetail.budget + '</strong></div>';
        html += '  <div class="kv-item"><span class="k">实际发生额</span><strong class="v">¥ ' + it.costDetail.spent + '</strong></div>';
        html += '  <div class="kv-item"><span class="k">预警状态</span><strong class="v">' + it.costDetail.alertLevel + '</strong></div>';
        html += '</div>';
      }

      if (it.finDetail) {
        html += '<div class="ad-section-title">对账单核对凭证</div>';
        html += '<div class="ad-kv-list">';
        html += '  <div class="kv-item"><span class="k">结算账户</span><strong class="v">' + it.finDetail.account + '</strong></div>';
        html += '  <div class="kv-item"><span class="k">发票凭证</span><strong class="v">' + it.finDetail.invoiceStatus + '</strong></div>';
        html += '  <div class="kv-item"><span class="k">往来单位</span><strong class="v">' + it.finDetail.counterparty + '</strong></div>';
        html += '</div>';
        html += '<button type="button" class="pixel-btn-action" id="btnMarkReconciled">已完成线下核对，标记对账通过 ✓</button>';
      }
    }

    html += '<div class="ad-actions">';
    html += '  <button type="button" class="pixel-btn-primary" id="portalEnterBtn" style="background:' + mod.color + ';border-color:#111">穿透进入' + mod.name + '系统 →</button>';
    html += '  <button type="button" class="pixel-btn-secondary" id="portalBackLevelBtn">返回上一层</button>';
    html += '</div>';

    drawer.innerHTML = html;
    drawer.classList.add('open');

    // 绑定内嵌操作
    drawer.querySelectorAll('.ad-tab-btn').forEach(function (tabBtn) {
      tabBtn.onclick = function () {
        drawer.querySelectorAll('.ad-tab-btn').forEach(function (b) { b.classList.remove('active'); });
        drawer.querySelectorAll('.ad-tab-content').forEach(function (c) { c.classList.remove('active'); });
        tabBtn.classList.add('active');
        var targetId = tabBtn.getAttribute('data-tab');
        var targetContent = document.getElementById(targetId);
        if (targetContent) targetContent.classList.add('active');
      };
    });

    drawer.querySelectorAll('.btn-stage-switch').forEach(function (stBtn) {
      stBtn.onclick = function () {
        var newSt = stBtn.getAttribute('data-st');
        it.stage = newSt;
        if (typeof global.showToast === 'function') {
          global.showToast('项目阶段已切换为「' + newSt + '」', 'success');
        }
        openDrawer(mod, it);
        renderLeavesDOM(mod);
      };
    });

    var btnApplyToQuote = document.getElementById('btnApplyToQuote');
    if (btnApplyToQuote) {
      btnApplyToQuote.onclick = function () {
        if (typeof global.selectModule === 'function') {
          global.selectModule('quote');
          setTimeout(function () {
            var sel = document.getElementById('projectId');
            if (sel) {
              sel.value = '30a79195fcf0453bbc56f704c84e0702';
              sel.dispatchEvent(new Event('change'));
            }
          }, 150);
        }
      };
    }

    drawer.querySelectorAll('.todo-check-box').forEach(function (chk) {
      chk.onchange = function () {
        var tdId = chk.getAttribute('data-id');
        var tdItem = (it.todos || []).find(function (t) { return t.id === tdId; });
        if (tdItem) {
          tdItem.done = chk.checked;
          var textSpan = chk.nextElementSibling;
          if (textSpan) textSpan.classList.toggle('done', chk.checked);
          if (typeof global.showToast === 'function') {
            global.showToast(chk.checked ? '待办已标记完成 ✓' : '待办已重置为待办', 'info');
          }
        }
      };
    });

    var btnAddTodo = document.getElementById('btnAddTodo');
    var newTodoInput = document.getElementById('newTodoInput');
    if (btnAddTodo && newTodoInput) {
      btnAddTodo.onclick = function () {
        var val = newTodoInput.value.trim();
        if (!val) return;
        it.todos = it.todos || [];
        it.todos.push({ id: 't-' + Date.now(), text: val, done: false });
        newTodoInput.value = '';
        if (typeof global.showToast === 'function') {
          global.showToast('待办已添加', 'success');
        }
        openDrawer(mod, it);
        renderLeavesDOM(mod);
      };
    }

    drawer.querySelectorAll('.doc-btn-view').forEach(function (docBtn) {
      docBtn.onclick = function () {
        var fName = docBtn.getAttribute('data-file');
        if (typeof global.showToast === 'function') {
          global.showToast('正在打开文档：' + fName, 'info');
        }
      };
    });

    var enterBtn = document.getElementById('portalEnterBtn');
    if (enterBtn) {
      enterBtn.onclick = function () {
        navigateTarget(mod, it);
      };
    }
    var closeBtn = document.getElementById('portalDrawerCloseBtn');
    if (closeBtn) closeBtn.onclick = stepBack;
    var backBtn = document.getElementById('portalBackLevelBtn');
    if (backBtn) backBtn.onclick = stepBack;
  }

  function closeDrawer() {
    if (drawer) drawer.classList.remove('open');
  }

  // 跨端穿透路由
  function navigateTarget(mod, it) {
    if (mod.id === 'quote') {
      if (typeof global.selectModule === 'function') global.selectModule('quote');
      else location.hash = 'quote';
    } else if (mod.id === 'tools') {
      window.location.href = './tools.html';
    } else if (mod.group === 'engineering') {
      if (typeof global.selectModule === 'function') global.selectModule(mod.id);
      else location.hash = mod.id;
    } else {
      var to = '/' + (mod.id === 'today' ? '' : mod.id);
      if (typeof global.selectModule === 'function') global.selectModule('workbench', to);
      else location.hash = 'workbench' + (to === '/' ? '' : to);
    }
  }

  // —— 面包屑更新 ——
  function updateBreadcrumb() {
    if (!breadcrumbEl) return;
    if (live.stage === 'hub') {
      breadcrumbEl.innerHTML = '<span class="crumb-root">数字枢纽</span> <span class="sep">/</span> <strong class="crumb-active">全景神经网络大盘</strong>';
    } else if (live.stage === 'module') {
      var mod = global.PORTAL_DATA.getModule(live.mod);
      var brs = mod ? (mod.branches || []) : [];
      var curBr = brs.find(function (b) { return b.id === live.branch; });
      var brLabel = curBr ? ' · ' + curBr.label : '';
      breadcrumbEl.innerHTML = '<span class="crumb-link" id="pCrumbHub">全景大盘</span> <span class="sep">/</span> <strong class="crumb-active">' + (mod ? mod.code + ' ' + mod.name : '') + brLabel + '</strong>';
      var hubBtn = document.getElementById('pCrumbHub');
      if (hubBtn) hubBtn.onclick = returnToHub;
    } else if (live.stage === 'item') {
      var m = global.PORTAL_DATA.getModule(live.mod);
      var brs2 = m ? (m.branches || []) : [];
      var curBr2 = brs2.find(function (b) { return b.id === live.branch; });
      var it = global.PORTAL_DATA.getItem(live.mod, live.branch, live.item);
      breadcrumbEl.innerHTML = '<span class="crumb-link" id="pCrumbHub2">全景大盘</span> <span class="sep">/</span> <span class="crumb-link" id="pCrumbMod">' + (m ? m.name : '') + '</span> <span class="sep">/</span> <span class="crumb-link" id="pCrumbBranch">' + (curBr2 ? curBr2.label : '') + '</span> <span class="sep">/</span> <strong class="crumb-active">' + (it ? it.title : '') + '</strong>';
      var h2 = document.getElementById('pCrumbHub2');
      if (h2) h2.onclick = returnToHub;
      var m2 = document.getElementById('pCrumbMod');
      if (m2) m2.onclick = function () { selectModule(live.mod); };
      var b2 = document.getElementById('pCrumbBranch');
      if (b2) b2.onclick = function () { selectBranch(live.branch); };
    }
  }

  // —— DOM 结构装载 ——
  function mountPortal(viewContainer) {
    container = viewContainer;
    container.innerHTML = '';
    container.className = 'portal-view stage-hub';

    // 1. 顶栏控制条
    var topBar = document.createElement('div');
    topBar.className = 'portal-top-bar';
    topBar.innerHTML = '<div class="portal-breadcrumb" id="portalBreadcrumb"></div><div class="portal-top-actions"><button type="button" class="pixel-pill-btn" id="portalNavToggle" aria-label="展开侧栏导航">☰ 导航</button><button type="button" class="pixel-pill-btn" id="portalResetBtn">重置大盘视角</button></div>';
    container.appendChild(topBar);
    breadcrumbEl = topBar.querySelector('#portalBreadcrumb');
    var resetBtn = topBar.querySelector('#portalResetBtn');
    if (resetBtn) resetBtn.onclick = returnToHub;
    // 沉浸态下侧栏已收走，留一个可逆的出口：点一下把壳叫回来（再点收起）
    var navToggle = topBar.querySelector('#portalNavToggle');
    if (navToggle) navToggle.onclick = function () {
      var shell = document.querySelector('.app-shell');
      if (!shell) return;
      var immersive = shell.classList.toggle('shell-immersive');
      navToggle.textContent = immersive ? '☰ 导航' : '›› 收起导航';
    };

    // 2. 星尘粒子 Canvas
    dustCanvas = document.createElement('canvas');
    dustCanvas.className = 'portal-dust-canvas';
    container.appendChild(dustCanvas);
    // jsdom 未装 canvas 包：getContext 会返回 null 并向 virtualConsole 抛 jsdomError（try/catch 拦不住），
    // 故先探测全局 CanvasRenderingContext2D；不存在则整个星尘层降级关闭（非必需视觉）。
    // （该错误会让前端冒烟「各页无未捕获错误」判据变红，属真实回归，不可省。）
    dustCtx = typeof CanvasRenderingContext2D !== 'undefined'
      ? dustCanvas.getContext('2d')
      : null;

    // 3. SVG 贝塞尔光纤层
    svgThreads = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svgThreads.setAttribute('class', 'portal-threads');
    container.appendChild(svgThreads);

    // 4. 中心呼吸聚能枢纽 (Core Hub)
    var core = document.createElement('div');
    core.id = 'portalCoreHub';
    core.className = 'portal-core-hub';
    core.innerHTML = '<div class="core-halo"></div><div class="core-ring r0"></div><div class="core-ring r1"></div><div class="core-ring r2"></div><div class="core-radar"></div><div class="core-pixel-box"><div class="core-badge">DIGITAL CORE</div><div class="core-title">工程智算</div><div class="core-sub"><span class="pixel-pulse-dot"></span> 枢纽在线</div></div>';
    core.onclick = returnToHub;
    container.appendChild(core);

    // 5. 模块卫星节点层 (第 1 列)
    nodesLayer = document.createElement('div');
    nodesLayer.className = 'portal-nodes-layer';
    var mods = global.PORTAL_DATA ? global.PORTAL_DATA.modules : [];

    mods.forEach(function (m) {
      var modBtn = document.createElement('button');
      modBtn.type = 'button';
      modBtn.id = 'portal-mod-' + m.id;
      modBtn.className = 'portal-mod-node group-' + m.group;
      modBtn.setAttribute('data-id', m.id);
      modBtn.innerHTML = '<div class="mod-node-head"><span class="mod-code" style="color:' + m.color + '">' + m.code + '</span><span class="mod-icon-badge">' + m.icon + '</span></div><div class="mod-node-name">' + m.name + '</div><div class="mod-node-sub">' + m.subtitle + '</div>';

      modBtn.onclick = function (e) {
        e.stopPropagation();
        selectModule(m.id);
      };
      nodesLayer.appendChild(modBtn);
    });
    container.appendChild(nodesLayer);

    // 6. 二级分支节点层 (第 2 列)
    branchesLayer = document.createElement('div');
    branchesLayer.className = 'portal-branches-layer';
    container.appendChild(branchesLayer);

    // 7. 三级实体卡片展开层 (第 3 列)
    fanLayer = document.createElement('div');
    fanLayer.className = 'portal-fan-layer';
    container.appendChild(fanLayer);

    // 8. 像素深度分析抽屉 (第 4 列)
    drawer = document.createElement('aside');
    drawer.className = 'portal-analysis-drawer';
    container.appendChild(drawer);

    // 全局 Esc 逐层回退
    window.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') {
        stepBack();
      }
    });

    initModuleSprings();
    initSvgStructure();
    updateBreadcrumb();

    lastTime = performance.now();
    cancelAnimationFrame(animFrameId);
    animFrameId = requestAnimationFrame(loop);
  }

  global.PORTAL_VIEW = {
    mount: mountPortal,
    selectModule: selectModule,
    selectBranch: selectBranch,
    selectItem: selectItem,
    returnToHub: returnToHub,
    stepBack: stepBack,
    resume: function () {
      lastTime = performance.now();
      cancelAnimationFrame(animFrameId);
      animFrameId = requestAnimationFrame(loop);
    },
    stop: function () {
      cancelAnimationFrame(animFrameId);
    }
  };
})(window);

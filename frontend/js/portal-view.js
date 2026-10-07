/**
 * 工程智算 · 像素神经舞台引擎 (Pixel Neural Stage)
 *
 * 视觉语言：白底像素（直角 / 硬描边 / 硬阴影 / 点阵脉冲），不发光、不模糊。
 * 动效语言取自 neural-creator-dashboard：
 *   1) hub：中心聚能核 + 模块环绕游动（像素化台阶漂移，不是平滑漂浮）
 *   2) module：核心退左侧 → 模块列队 → 触须一根接一根生长到二级分支 → 再依次开花到三级卡片
 *   3) 展开态可直接点其他模块平滑切换（槽位重排）
 * 性能：SVG 静态节点缓存，每帧只 setAttribute('d'/'cx'/'cy')，不做 innerHTML 重排。
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

  var svgCache = { orbits: [], modThreads: {}, branchThreads: [], leafThreads: [] };

  // —— 阻尼弹簧积分器（dt 夹紧，防后台恢复时发散） ——
  function spring(st, target, dt, k) {
    if (k === undefined) k = 62;
    var c = 2 * Math.sqrt(k);
    st.v += (-k * (st.x - target) - c * st.v) * dt;
    st.x += st.v * dt;
    return st.x;
  }
  function sp(x) { return { x: x, v: 0 }; }
  function clamp(v, a, b) { return Math.max(a, Math.min(b, v)); }

  function bez(p0, p1, p2, p3, u) {
    var m = 1 - u;
    return m * m * m * p0 + 3 * m * m * u * p1 + 3 * m * u * u * p2 + u * u * u * p3;
  }

  // —— 点阵星尘：白底上以墨色/橙色小方点表达「能量」，不用模糊光斑 ——
  var DUST = Array.from({ length: 96 }, function (_, i) {
    return {
      a: i * 2.39996,
      v: 0.03 + (i * 37 % 100) / 100 * 0.05,
      o: (i * 0.618034) % 1,
      w: (i % 2 ? 1 : -1) * (0.12 + (i % 7) * 0.04),
      s: 1 + (i % 4),
      b: 0.35 + (i % 3) * 0.22,
      c: i % 3 === 0 ? '255, 90, 31' : '17, 17, 17'
    };
  });

  var live = {
    stage: 'hub',          // 'hub' | 'module' | 'item'
    mod: null,
    branch: null,
    item: null,
    time: 0,
    branchStart: 0,
    leafStart: 0,
    branchState: [],
    leafState: [],
    size: { w: 1200, h: 800 },
    springs: {
      orb: { x: sp(600), y: sp(400), s: sp(150), o: sp(1) },
      dust: sp(0.3),
      jelly: {}
    }
  };

  function initModuleSprings() {
    var mods = global.PORTAL_DATA ? global.PORTAL_DATA.modules : [];
    mods.forEach(function (m) {
      live.springs.jelly[m.id] = {
        x: sp(600), y: sp(400), s: sp(76), o: sp(1),
        cur: { x: 600, y: 400, s: 76 }
      };
    });
  }

  // 选中模块滑到列中间，其余按原顺序上下对称排开
  function slotOf(selId, id) {
    var mods = global.PORTAL_DATA.modules;
    var others = mods.filter(function (m) { return m.id !== selId; }).map(function (m) { return m.id; });
    var half = Math.floor(others.length / 2);
    var order = others.slice(0, half).concat([selId]).concat(others.slice(half));
    var k = order.indexOf(id);
    return k < 0 ? mods.findIndex(function (m) { return m.id === id; }) : k;
  }

  // —— 布局目标 ——
  function targets(L, t) {
    var W = L.size.w, H = L.size.h, st = L.stage;
    var narrow = W < 900;
    var res = { orb: {}, jelly: {}, branches: null, leaves: null };
    var mods = global.PORTAL_DATA ? global.PORTAL_DATA.modules : [];

    if (st === 'hub') {
      var s = narrow ? clamp(W * 0.34, 120, 170) : clamp(Math.min(W, H) * 0.26, 140, 210);
      var cy = narrow ? H * 0.5 : H * 0.52;
      res.orb = { x: W / 2, y: cy, s: s };

      var rx = narrow ? W * 0.36 : Math.min(W * 0.37, 500);
      var ry = narrow ? H * 0.32 : Math.min(H * 0.36, 300);

      mods.forEach(function (m, i) {
        // 游动：角度与半径都做缓慢正弦扰动；像素化后用较低频率，避免抖动
        var a = (m.angle + 7 * Math.sin(t * 0.16 + i * 1.6)) * Math.PI / 180;
        var r = 1 + 0.05 * Math.sin(t * 0.2 + i);
        res.jelly[m.id] = {
          x: W / 2 + Math.cos(a) * rx * r,
          y: cy + Math.sin(a) * ry * r + 8 * Math.sin(t * 0.7 + i * 2.1),
          s: narrow ? 72 : clamp(W * 0.055, 80, 96),
          o: 1,
          tilt: 0
        };
      });
    } else {
      var ox = narrow ? 40 : Math.max(52, W * 0.05);
      var cy2 = H * 0.5;
      res.orb = { x: ox, y: cy2, s: 96 };

      var col1_x = ox + (narrow ? 60 : 78);
      var gap = Math.min(74, (H - 140) / Math.max(mods.length, 1));

      mods.forEach(function (m, i) {
        var sel = m.id === L.mod;
        var k = slotOf(L.mod, m.id);
        res.jelly[m.id] = {
          x: col1_x + (sel ? 22 : 0),
          y: cy2 + (k - (mods.length - 1) / 2) * gap,
          s: sel ? 96 : 62,
          o: sel ? 1 : 0.5,
          tilt: 0
        };
      });

      var brs = global.PORTAL_DATA.getBranches(L.mod);
      var bn = brs.length;
      var col2_x = col1_x + 22 + 96 * 0.5 + 92;
      var bSpan = Math.max(0, bn - 1) * 76;
      res.branches = { x: col2_x, y0: cy2 - bSpan / 2, gap: bn > 1 ? bSpan / (bn - 1) : 0 };

      var leafItems = global.PORTAL_DATA.getItems(L.mod, L.branch);
      var ln = leafItems.length;
      var col3_x = col2_x + 128 + (narrow ? 40 : 70);
      var lSpan = Math.min(H - 150, Math.max(0, ln - 1) * 60);
      res.leaves = { x: col3_x, y0: cy2 - lSpan / 2, gap: ln > 1 ? lSpan / (ln - 1) : 0 };
    }
    return res;
  }

  // —— 静态 SVG 骨架 ——
  function initSvgStructure() {
    if (!svgThreads) return;
    svgThreads.innerHTML = '';
    svgCache = { orbits: [], modThreads: {}, branchThreads: [], leafThreads: [] };

    [150, 250, 360].forEach(function (cr, cidx) {
      var c = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
      c.setAttribute('class', 'portal-orbit-ring ring-' + cidx);
      c.setAttribute('r', cr);
      svgThreads.appendChild(c);
      svgCache.orbits.push({ el: c, r: cr });
    });

    var mods = global.PORTAL_DATA ? global.PORTAL_DATA.modules : [];
    mods.forEach(function (m) {
      var g = document.createElementNS('http://www.w3.org/2000/svg', 'g');

      var glow = document.createElementNS('http://www.w3.org/2000/svg', 'path');
      glow.setAttribute('class', 'pv-thread-glow');
      g.appendChild(glow);

      var core = document.createElementNS('http://www.w3.org/2000/svg', 'path');
      core.setAttribute('class', 'pv-thread-core');
      core.setAttribute('stroke-dasharray', '1 4');
      g.appendChild(core);

      var pulses = [];
      [0, 1, 2].forEach(function (k) {
        var sq = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
        sq.setAttribute('class', 'pv-pulse');
        sq.setAttribute('r', k === 2 ? '2' : '2.6');
        sq.setAttribute('fill', k === 2 ? '#111111' : m.color);
        g.appendChild(sq);
        pulses.push(sq);
      });

      svgThreads.appendChild(g);
      svgCache.modThreads[m.id] = { g: g, glow: glow, core: core, pulses: pulses };
    });
  }

  function rebuildBranchSvg(mod) {
    if (!svgThreads) return;
    svgCache.branchThreads.forEach(function (it) { it.g.remove(); });
    svgCache.branchThreads = [];
    svgCache.leafThreads.forEach(function (it) { it.g.remove(); });
    svgCache.leafThreads = [];

    (mod.branches || []).forEach(function () {
      var g = document.createElementNS('http://www.w3.org/2000/svg', 'g');
      var path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
      path.setAttribute('class', 'pv-thread-core');
      path.setAttribute('stroke-dasharray', '1 4');
      g.appendChild(path);

      var pulse = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
      pulse.setAttribute('class', 'pv-pulse');
      pulse.setAttribute('r', '2.4');
      pulse.setAttribute('fill', mod.color);
      g.appendChild(pulse);

      svgThreads.appendChild(g);
      svgCache.branchThreads.push({ g: g, path: path, pulse: pulse });
    });
  }

  function rebuildLeafSvg(mod) {
    if (!svgThreads) return;
    svgCache.leafThreads.forEach(function (it) { it.g.remove(); });
    svgCache.leafThreads = [];

    (global.PORTAL_DATA.getItems(mod.id, live.branch) || []).forEach(function () {
      var g = document.createElementNS('http://www.w3.org/2000/svg', 'g');
      var path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
      path.setAttribute('class', 'pv-thread-core');
      path.setAttribute('stroke-dasharray', '1 4');
      g.appendChild(path);

      var pulses = [];
      [0, 1].forEach(function () {
        var p = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
        p.setAttribute('class', 'pv-pulse');
        p.setAttribute('r', '2.2');
        p.setAttribute('fill', mod.color);
        g.appendChild(p);
        pulses.push(p);
      });

      svgThreads.appendChild(g);
      svgCache.leafThreads.push({ g: g, path: path, pulses: pulses });
    });
  }

  // —— 主步进 ——
  function step(now) {
    var dt = Math.max(0, Math.min(1 / 30, (now - lastTime) / 1000));
    lastTime = now;
    live.time += dt;

    if (container) {
      var rw = container.clientWidth || window.innerWidth;
      var rh = container.clientHeight || window.innerHeight;
      if (rw > 100 && rh > 100) live.size = { w: rw, h: rh };
    }

    var t = live.time;
    var S = live.springs;
    var T = targets(live, t);
    var mods = global.PORTAL_DATA ? global.PORTAL_DATA.modules : [];

    // 1. 中心核
    var ox = spring(S.orb.x, T.orb.x, dt);
    var oy = spring(S.orb.y, T.orb.y, dt);
    var os = spring(S.orb.s, T.orb.s, dt, 40);
    var oo = spring(S.orb.o, 1, dt, 30);

    var orbEl = document.getElementById('portalCoreHub');
    if (orbEl) {
      orbEl.style.transform = 'translate3d(' + (ox - os / 2) + 'px,' + (oy - os / 2) + 'px,0) scale(' + (os / 200) + ')';
      orbEl.style.opacity = clamp(oo, 0, 1);
    }

    // 2. 星尘（点阵，白底上用暗点/橙点）
    if (dustCtx && dustCanvas) {
      dustCtx.clearRect(0, 0, dustCanvas.width, dustCanvas.height);
      var dInt = clamp(spring(S.dust, live.stage === 'hub' ? 0.85 : 0.28, dt, 18), 0, 1);
      if (dInt > 0.02) {
        for (var pi = 0; pi < DUST.length; pi++) {
          var p = DUST[pi];
          var ph = ((t * p.v + p.o) % 1 + 1) % 1;
          var r = os * 0.42 + ph * (os * 0.95);
          var a = p.a + ph * p.w;
          var px = ox + Math.cos(a) * r;
          var py = oy + Math.sin(a) * r * 0.94;
          var al = dInt * Math.pow(Math.max(0, Math.sin(ph * Math.PI)), 1.2) * p.b;
          dustCtx.fillStyle = 'rgba(' + p.c + ',' + al.toFixed(3) + ')';
          dustCtx.fillRect(Math.round(px), Math.round(py), p.s, p.s);
        }
      }
    }

    // 3. 轨道环
    svgCache.orbits.forEach(function (it) {
      if (live.stage === 'hub') {
        it.el.setAttribute('cx', ox);
        it.el.setAttribute('cy', oy);
        it.el.style.display = 'block';
      } else {
        it.el.style.display = 'none';
      }
    });

    // 4. 模块节点 + 核心→模块触须
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
        el.style.transform = 'translate3d(' + (x - s / 2) + 'px,' + (y - s / 2) + 'px,0) scale(' + (s / 96) + ')';
        el.style.opacity = clamp(o, 0, 1);
        el.classList.toggle('node-active', m.id === live.mod);
        el.classList.toggle('node-dimmed', live.stage !== 'hub' && m.id !== live.mod);
      }

      var tObj = svgCache.modThreads[m.id];
      if (tObj) {
        var dx = x - ox, dy = y - oy;
        var dist = Math.hypot(dx, dy) || 1;
        var ux = dx / dist, uy = dy / dist;
        var x1 = ox + ux * os * 0.42, y1 = oy + uy * os * 0.42;
        var x2 = x - ux * s * 0.42, y2 = y - uy * s * 0.42;

        var bend = live.stage === 'hub' ? 20 * Math.sin(t * 0.5 + i) : 4;
        var c1x = x1 + dx * 0.35 - uy * bend, c1y = y1 + dy * 0.35 + ux * bend;
        var c2x = x1 + dx * 0.7 + uy * bend, c2y = y1 + dy * 0.7 - ux * bend;
        var dPath = 'M' + x1.toFixed(1) + ',' + y1.toFixed(1) + ' C' + c1x.toFixed(1) + ',' + c1y.toFixed(1) + ' ' + c2x.toFixed(1) + ',' + c2y.toFixed(1) + ' ' + x2.toFixed(1) + ',' + y2.toFixed(1);

        var isActive = m.id === live.mod;
        var strokeColor = isActive ? m.color : 'rgba(17,17,17,0.3)';
        var strokeW = isActive ? 2.4 : 1.1;

        tObj.glow.setAttribute('d', dPath);
        tObj.glow.setAttribute('stroke', m.color);
        tObj.glow.setAttribute('stroke-width', (strokeW * 3).toFixed(1));
        tObj.glow.setAttribute('stroke-opacity', isActive ? '0.22' : '0.05');

        tObj.core.setAttribute('d', dPath);
        tObj.core.setAttribute('stroke', strokeColor);
        tObj.core.setAttribute('stroke-width', strokeW.toFixed(1));
        tObj.core.setAttribute('stroke-opacity', clamp(o, 0, 1).toFixed(2));

        tObj.pulses.forEach(function (sq, k) {
          var inbound = k === 2;
          var u = ((t * (inbound ? 0.22 : 0.3) + k * 0.48 + i * 0.16) % 1);
          if (inbound) u = 1 - u;
          sq.setAttribute('cx', bez(x1, c1x, c2x, x2, u).toFixed(1));
          sq.setAttribute('cy', bez(y1, c1y, c2y, y2, u).toFixed(1));
          sq.setAttribute('opacity', (Math.sin(u * Math.PI) * clamp(o, 0, 1)).toFixed(2));
        });
      }
    });

    // 5. 模块 → 二级分支（依次生长）
    if (T.branches && live.mod) {
      var currentMod = global.PORTAL_DATA.getModule(live.mod);
      var branches = global.PORTAL_DATA.getBranches(live.mod);
      var sj = S.jelly[live.mod];

      if (sj) {
        var mOx = sj.cur.x + sj.cur.s * 0.5 + 4;
        var mOy = sj.cur.y;

        branches.forEach(function (b, bi) {
          if (!live.branchState[bi]) live.branchState[bi] = { x: sp(mOx), y: sp(mOy), o: sp(0) };
          var bst = live.branchState[bi];
          var bReady = now - live.branchStart > 60 + bi * 110;
          var bTx = T.branches.x;
          var bTy = T.branches.y0 + bi * T.branches.gap;

          var bX = spring(bst.x, bReady ? bTx : mOx, dt, 70);
          var bY = spring(bst.y, bReady ? bTy : mOy, dt, 70);
          var bO = spring(bst.o, bReady ? 1 : 0, dt, 50);
          bst.cur = { x: bX, y: bY };

          var bEl = document.getElementById('portal-branch-' + b.id);
          if (bEl) {
            bEl.style.transform = 'translate3d(' + bX.toFixed(1) + 'px,' + (bY - 19).toFixed(1) + 'px,0)';
            bEl.style.opacity = clamp(bO, 0, 1);
            bEl.classList.toggle('branch-active', b.id === live.branch);
          }

          var bSvg = svgCache.branchThreads[bi];
          if (bSvg) {
            if (bO > 0.02) {
              var bdx = bX - mOx;
              var bsway = Math.sin(t * 1.0 + bi * 0.8) * 4;
              var bc1x = mOx + bdx * 0.45, bc1y = mOy + bsway;
              var bc2x = bX - bdx * 0.4, bc2y = bY - bsway * 0.5;
              var bp = 'M' + mOx.toFixed(1) + ',' + mOy.toFixed(1) + ' C' + bc1x.toFixed(1) + ',' + bc1y.toFixed(1) + ' ' + bc2x.toFixed(1) + ',' + bc2y.toFixed(1) + ' ' + bX.toFixed(1) + ',' + bY.toFixed(1);
              var isBrSel = b.id === live.branch;
              bSvg.path.setAttribute('d', bp);
              bSvg.path.setAttribute('stroke', isBrSel ? currentMod.color : 'rgba(17,17,17,0.34)');
              bSvg.path.setAttribute('stroke-width', isBrSel ? '2.2' : '1.1');
              bSvg.path.setAttribute('stroke-opacity', clamp(bO, 0, 1).toFixed(2));

              var bfu = ((t * 0.35 + bi * 0.2) % 1);
              bSvg.pulse.setAttribute('cx', bez(mOx, bc1x, bc2x, bX, bfu).toFixed(1));
              bSvg.pulse.setAttribute('cy', bez(mOy, bc1y, bc2y, bY, bfu).toFixed(1));
              bSvg.pulse.setAttribute('opacity', (clamp(bO, 0, 1) * Math.sin(bfu * Math.PI)).toFixed(2));
              bSvg.g.style.display = 'block';
            } else {
              bSvg.g.style.display = 'none';
            }
          }
        });
      }
    }

    // 6. 二级分支 → 三级卡片（一根接一根依次开花）
    if (T.leaves && live.mod && live.branch) {
      var currentMod2 = global.PORTAL_DATA.getModule(live.mod);
      var leafItems = global.PORTAL_DATA.getItems(live.mod, live.branch);
      var branches2 = global.PORTAL_DATA.getBranches(live.mod);
      var activeBrIdx = branches2.findIndex(function (b) { return b.id === live.branch; });
      var activeBrState = live.branchState[activeBrIdx];

      if (activeBrState && activeBrState.cur) {
        var brOx = activeBrState.cur.x + 128 + 4;
        var brOy = activeBrState.cur.y;

        leafItems.forEach(function (it, li) {
          if (!live.leafState[li]) live.leafState[li] = { x: sp(brOx), y: sp(brOy), o: sp(0) };
          var lst = live.leafState[li];

          var stagger = Math.min(110, 900 / Math.max(leafItems.length, 1));
          var leafReady = now - live.leafStart > 80 + li * stagger;
          var lTx = T.leaves.x;
          var lTy = T.leaves.y0 + li * T.leaves.gap;

          var lx = spring(lst.x, leafReady ? lTx : brOx, dt, 70);
          var ly = spring(lst.y, leafReady ? lTy : brOy, dt, 70);
          var lo = spring(lst.o, leafReady ? 1 : 0, dt, 50);

          var itEl = document.getElementById('portal-item-' + it.id);
          if (itEl) {
            itEl.style.transform = 'translate3d(' + lx.toFixed(1) + 'px,' + (ly - 24).toFixed(1) + 'px,0)';
            itEl.style.opacity = clamp(lo, 0, 1);
            itEl.classList.toggle('item-selected', live.item === it.id);
          }

          var lSvg = svgCache.leafThreads[li];
          if (lSvg) {
            if (lo > 0.02) {
              var ldx = lx - brOx;
              var lsway = Math.sin(t * 1.1 + li * 0.7) * 5;
              var lc1x = brOx + ldx * 0.45, lc1y = brOy + lsway;
              var lc2x = lx - ldx * 0.4, lc2y = ly - lsway * 0.5;
              var lp = 'M' + brOx.toFixed(1) + ',' + brOy.toFixed(1) + ' C' + lc1x.toFixed(1) + ',' + lc1y.toFixed(1) + ' ' + lc2x.toFixed(1) + ',' + lc2y.toFixed(1) + ' ' + lx.toFixed(1) + ',' + ly.toFixed(1);
              var isLeafSel = live.item === it.id;
              lSvg.path.setAttribute('d', lp);
              lSvg.path.setAttribute('stroke', isLeafSel ? currentMod2.color : 'rgba(17,17,17,0.32)');
              lSvg.path.setAttribute('stroke-width', isLeafSel ? '2.2' : '1.1');
              lSvg.path.setAttribute('stroke-opacity', clamp(lo, 0, 1).toFixed(2));
              lSvg.pulses.forEach(function (pc, k) {
                var lfu = ((t * (k ? 0.28 : 0.36) + li * 0.14 + k * 0.5) % 1);
                if (k) lfu = 1 - lfu;
                pc.setAttribute('cx', bez(brOx, lc1x, lc2x, lx, lfu).toFixed(1));
                pc.setAttribute('cy', bez(brOy, lc1y, lc2y, ly, lfu).toFixed(1));
                pc.setAttribute('opacity', (clamp(lo, 0, 1) * Math.sin(lfu * Math.PI)).toFixed(2));
              });
              lSvg.g.style.display = 'block';
            } else {
              lSvg.g.style.display = 'none';
            }
          }
        });
      }
    }
  }

  // —— 动画循环（先排下一帧，再 try 执行本帧） ——
  // 视图隐藏时不重排下一帧（避免后台空转 / jsdom 下进程不退出）；
  // 重新可见由 mount() / resume() 重新启动循环。
  function loop(now) {
    animFrameId = null;
    if (!container || container.classList.contains('hidden')) {
      lastTime = now;
      return;
    }

    animFrameId = requestAnimationFrame(loop);

    var w = container.clientWidth || window.innerWidth;
    var h = container.clientHeight || window.innerHeight;
    if (dustCanvas && (dustCanvas.width !== w || dustCanvas.height !== h)) {
      dustCanvas.width = w;
      dustCanvas.height = h;
      live.size = { w: w, h: h };
    }

    try {
      step(now);
    } catch (err) {
      console.error('[PortalView] step error:', err);
    }
  }

  // —— 交互 ——
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
    live.leafStart = now + 60;

    live.branchState = brs.map(function () { return null; });
    live.leafState = global.PORTAL_DATA.getItems(modId, brId).map(function () { return null; });

    container.className = 'portal-view stage-module';

    rebuildBranchSvg(mod);
    rebuildLeafSvg(mod);

    updateBreadcrumb();
    renderBranchesDOM(mod);
    renderLeavesDOM(mod);
    closeDrawer();
  }

  function selectBranch(branchId) {
    if (!live.mod || live.branch === branchId) return;
    var mod = global.PORTAL_DATA.getModule(live.mod);
    if (!mod) return;

    live.branch = branchId;
    live.item = null;
    live.leafStart = performance.now();

    live.leafState = global.PORTAL_DATA.getItems(live.mod, branchId).map(function () { return null; });

    rebuildLeafSvg(mod);
    updateBreadcrumb();
    renderLeavesDOM(mod);
    closeDrawer();
  }

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

  // 从「卡片」退回「分支层」：只收抽屉，不重放触须生长（位置原地保留，避免视觉倒退）
  function returnToModule() {
    if (live.stage !== 'item') return;
    live.stage = 'module';
    live.item = null;
    container.className = 'portal-view stage-module';
    renderLeavesDOM(global.PORTAL_DATA.getModule(live.mod));
    closeDrawer();
    updateBreadcrumb();
  }

  function stepBack() {
    if (live.stage === 'item') returnToModule();
    else if (live.stage === 'module') returnToHub();
  }

  function returnToHub() {
    live.stage = 'hub';
    live.mod = null;
    live.branch = null;
    live.item = null;
    container.className = 'portal-view stage-hub';

    if (svgThreads) {
      svgCache.branchThreads.forEach(function (it) { it.g.remove(); });
      svgCache.branchThreads = [];
      svgCache.leafThreads.forEach(function (it) { it.g.remove(); });
      svgCache.leafThreads = [];
    }
    live.branchState = [];
    live.leafState = [];

    updateBreadcrumb();
    if (branchesLayer) branchesLayer.innerHTML = '';
    if (fanLayer) fanLayer.innerHTML = '';
    closeDrawer();
  }

  function renderBranchesDOM(mod) {
    if (!branchesLayer) return;
    var brs = mod.branches || [];
    var html = '';
    brs.forEach(function (b) {
      html += '<button type="button" class="portal-branch-node" id="portal-branch-' + b.id + '" data-id="' + b.id + '">';
      html += '  <span class="branch-anchor-in" style="background:' + mod.color + '"></span>';
      html += '  <span class="branch-content">';
      html += '    <span class="branch-code" style="color:' + mod.color + '">' + b.code + '</span>';
      html += '    <span class="branch-title">' + b.label + '</span>';
      html += '  </span>';
      html += '  <span class="branch-anchor-out" style="background:' + mod.color + '"></span>';
      html += '</button>';
    });
    branchesLayer.innerHTML = html;

    brs.forEach(function (b) {
      var btn = document.getElementById('portal-branch-' + b.id);
      if (btn) btn.onclick = function (e) { e.stopPropagation(); selectBranch(b.id); };
    });
  }

  function renderLeavesDOM(mod) {
    if (!fanLayer) return;
    var items = global.PORTAL_DATA.getItems(mod.id, live.branch);
    var html = '<div class="fan-items-list">';
    items.forEach(function (it) {
      var tagClass = it.stage === '投标' ? 'tag-bid' : (it.stage === '中标在建' ? 'tag-build' : 'tag-done');
      html += '<button type="button" class="portal-fan-card" id="portal-item-' + it.id + '" data-id="' + it.id + '">';
      html += '  <span class="card-anchor-dot" style="background:' + mod.color + '"></span>';
      html += '  <span class="card-left"><span class="pixel-num">' + it.code + '</span></span>';
      html += '  <span class="card-mid">';
      html += '    <span class="card-title">' + it.title + '</span>';
      html += '    <span class="card-desc">' + (it.desc || '') + '</span>';
      html += '  </span>';
      if (it.stage) html += '  <span class="card-right"><span class="stage-tag ' + tagClass + '">' + it.stage + '</span></span>';
      html += '</button>';
    });
    html += '</div>';
    fanLayer.innerHTML = html;

    items.forEach(function (it) {
      var btn = document.getElementById('portal-item-' + it.id);
      if (btn) btn.onclick = function (e) { e.stopPropagation(); selectItem(it.id); };
    });
  }

  function closeDrawer() { if (drawer) drawer.classList.remove('open'); }

  // —— 深度分析抽屉 ——
  function openDrawer(mod, it) {
    if (!drawer) return;
    var html = '';

    html += '<div class="ad-head">';
    html += '  <div class="ad-badge-group">';
    html += '    <span class="pixel-tag" style="background:' + mod.color + ';color:#fff">' + mod.code + '</span>';
    html += '    <span class="pixel-badge">' + (mod.group === 'engineering' ? '工程主链' : '经营管理') + '</span>';
    if (it.stage) html += '    <span class="pixel-badge stage-badge">' + it.stage + '</span>';
    html += '  </div>';
    html += '  <button type="button" class="ad-close-btn" id="portalDrawerCloseBtn" aria-label="关闭">&times;</button>';
    html += '</div>';

    html += '<h2 class="ad-title">' + it.title + '</h2>';
    html += '<div class="ad-sub">' + (it.code || '') + ' · 业务要素深度分析与控制舱</div>';

    if (mod.id === 'biz' && it.profile) {
      html += '<div class="ad-tabs-header">';
      html += '  <button type="button" class="ad-tab-btn active" data-tab="tab-overview">概况</button>';
      html += '  <button type="button" class="ad-tab-btn" data-tab="tab-quote">报价</button>';
      html += '  <button type="button" class="ad-tab-btn" data-tab="tab-exec">执行</button>';
      html += '  <button type="button" class="ad-tab-btn" data-tab="tab-docs">文档 (' + (it.docs ? it.docs.length : 0) + ')</button>';
      html += '  <button type="button" class="ad-tab-btn" data-tab="tab-todos">待办 (' + (it.todos ? it.todos.length : 0) + ')</button>';
      html += '</div>';

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
        html += '    <button type="button" class="btn-stage-switch ' + (it.stage === st ? 'active' : '') + '" data-st="' + st + '">' + st + '</button>';
      });
      html += '  </div>';
      html += '</div>';

      html += '<div class="ad-tab-content" id="tab-quote">';
      html += '  <div class="ad-metrics-grid">';
      html += '    <div class="ad-metric-box"><span class="m-label">目标总报价</span><strong class="m-val">¥ ' + it.quote.targetTotal + '</strong></div>';
      html += '    <div class="ad-metric-box"><span class="m-label">下浮率</span><strong class="m-val" style="color:#ff5a1f">' + it.quote.rate + '</strong></div>';
      html += '    <div class="ad-metric-box"><span class="m-label">安全防线</span><strong class="m-val">' + it.quote.guardrail + '</strong></div>';
      html += '  </div>';
      html += '  <div class="ad-kv-list" style="margin-top:10px">';
      html += '    <div class="kv-item"><span class="k">固定税前项</span><strong class="v">¥ ' + it.quote.fixedPretax + '</strong></div>';
      html += '    <div class="kv-item"><span class="k">增值税 / 附加税</span><strong class="v">' + it.quote.vatRate + ' / ' + it.quote.surtaxRate + '</strong></div>';
      html += '  </div>';
      html += '  <button type="button" class="pixel-btn-action" id="btnApplyToQuote">带入此项目进入投标报价沙盘 →</button>';
      html += '</div>';

      html += '<div class="ad-tab-content" id="tab-exec">';
      html += '  <div class="ad-progress-box"><div class="p-head"><span>综合进度</span><strong>' + it.progress + '%</strong></div><div class="p-bar"><div class="p-fill" style="width:' + it.progress + '%"></div></div></div>';
      html += '  <div class="ad-kv-list">';
      html += '    <div class="kv-item"><span class="k">当前状态</span><strong class="v">' + it.execution.status + '</strong></div>';
      html += '    <div class="kv-item"><span class="k">项目团队</span><strong class="v">' + it.execution.team + '</strong></div>';
      html += '    <div class="kv-item"><span class="k">风控评级</span><strong class="v">' + it.execution.riskLevel + '</strong></div>';
      html += '  </div>';
      html += '</div>';

      html += '<div class="ad-tab-content" id="tab-docs">';
      html += '  <div class="ad-doc-list">';
      (it.docs || []).forEach(function (doc) {
        html += '    <div class="doc-row">';
        html += '      <div class="doc-info"><span class="doc-name">' + doc.name + '</span><span class="doc-meta">' + doc.size + ' · ' + doc.time + '</span></div>';
        html += '      <button type="button" class="doc-btn-view" data-file="' + doc.name + '">查阅</button>';
        html += '    </div>';
      });
      html += '  </div>';
      html += '</div>';

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

    drawer.querySelectorAll('.ad-tab-btn').forEach(function (tabBtn) {
      tabBtn.onclick = function () {
        drawer.querySelectorAll('.ad-tab-btn').forEach(function (b) { b.classList.remove('active'); });
        drawer.querySelectorAll('.ad-tab-content').forEach(function (c) { c.classList.remove('active'); });
        tabBtn.classList.add('active');
        var tc = document.getElementById(tabBtn.getAttribute('data-tab'));
        if (tc) tc.classList.add('active');
      };
    });

    drawer.querySelectorAll('.btn-stage-switch').forEach(function (stBtn) {
      stBtn.onclick = function () {
        it.stage = stBtn.getAttribute('data-st');
        if (typeof global.showToast === 'function') global.showToast('项目阶段已切换为「' + it.stage + '」', 'success');
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
            if (sel) { sel.value = '30a79195fcf0453bbc56f704c84e0702'; sel.dispatchEvent(new Event('change')); }
          }, 150);
        }
      };
    }

    drawer.querySelectorAll('.todo-check-box').forEach(function (chk) {
      chk.onchange = function () {
        var tdItem = (it.todos || []).find(function (t) { return t.id === chk.getAttribute('data-id'); });
        if (!tdItem) return;
        tdItem.done = chk.checked;
        var span = chk.nextElementSibling;
        if (span) span.classList.toggle('done', chk.checked);
        if (typeof global.showToast === 'function') global.showToast(chk.checked ? '待办已标记完成 ✓' : '待办已重置为待办', 'info');
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
        if (typeof global.showToast === 'function') global.showToast('待办已添加', 'success');
        openDrawer(mod, it);
        renderLeavesDOM(mod);
      };
    }

    drawer.querySelectorAll('.doc-btn-view').forEach(function (docBtn) {
      docBtn.onclick = function () {
        if (typeof global.showToast === 'function') global.showToast('正在打开文档：' + docBtn.getAttribute('data-file'), 'info');
      };
    });

    var enterBtn = document.getElementById('portalEnterBtn');
    if (enterBtn) enterBtn.onclick = function () { navigateTarget(mod, it); };
    var closeBtn = document.getElementById('portalDrawerCloseBtn');
    if (closeBtn) closeBtn.onclick = returnToModule;
    var backBtn = document.getElementById('portalBackLevelBtn');
    if (backBtn) backBtn.onclick = returnToModule;
  }

  function navigateTarget(mod) {
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

  function updateBreadcrumb() {
    if (!breadcrumbEl) return;
    if (live.stage === 'hub') {
      breadcrumbEl.innerHTML = '<span class="crumb-root">数字枢纽</span> <span class="sep">/</span> <strong class="crumb-active">全景神经舞台</strong>';
    } else if (live.stage === 'module') {
      var mod = global.PORTAL_DATA.getModule(live.mod);
      var brs = mod ? (mod.branches || []) : [];
      var curBr = brs.find(function (b) { return b.id === live.branch; });
      breadcrumbEl.innerHTML = '<button type="button" class="crumb-link" id="pCrumbHub">全景舞台</button> <span class="sep">/</span> <strong class="crumb-active">' + (mod ? mod.code + ' ' + mod.name : '') + (curBr ? ' · ' + curBr.label : '') + '</strong>';
      var hubBtn = document.getElementById('pCrumbHub');
      if (hubBtn) hubBtn.onclick = returnToHub;
    } else {
      var m = global.PORTAL_DATA.getModule(live.mod);
      var brs2 = m ? (m.branches || []) : [];
      var curBr2 = brs2.find(function (b) { return b.id === live.branch; });
      var it = global.PORTAL_DATA.getItem(live.mod, live.branch, live.item);
      breadcrumbEl.innerHTML = '<button type="button" class="crumb-link" id="pCrumbHub2">全景舞台</button> <span class="sep">/</span> <button type="button" class="crumb-link" id="pCrumbMod">' + (m ? m.name : '') + '</button> <span class="sep">/</span> <button type="button" class="crumb-link" id="pCrumbBranch">' + (curBr2 ? curBr2.label : '') + '</button> <span class="sep">/</span> <strong class="crumb-active">' + (it ? it.title : '') + '</strong>';
      var h2 = document.getElementById('pCrumbHub2'); if (h2) h2.onclick = returnToHub;
      var m2 = document.getElementById('pCrumbMod'); if (m2) m2.onclick = function () { selectModule(live.mod); };
      var b2 = document.getElementById('pCrumbBranch'); if (b2) b2.onclick = function () { selectBranch(live.branch); };
    }
  }

  // —— 装载 ——
  function mountPortal(viewContainer) {
    container = viewContainer;
    container.innerHTML = '';
    container.className = 'portal-view stage-hub';

    var topBar = document.createElement('div');
    topBar.className = 'portal-top-bar';
    topBar.innerHTML = '<div class="portal-breadcrumb" id="portalBreadcrumb"></div><div class="portal-top-actions"><button type="button" class="pixel-pill-btn" id="portalResetBtn">重置舞台视角</button></div>';
    container.appendChild(topBar);
    breadcrumbEl = topBar.querySelector('#portalBreadcrumb');
    var resetBtn = topBar.querySelector('#portalResetBtn');
    if (resetBtn) resetBtn.onclick = returnToHub;

    dustCanvas = document.createElement('canvas');
    dustCanvas.className = 'portal-dust-canvas';
    container.appendChild(dustCanvas);
    // jsdom 未装 canvas 包：getContext 会返回 null 并向 virtualConsole 抛 jsdomError（try/catch 拦不住），
    // 故先探测全局 CanvasRenderingContext2D 是否存在；不存在则整个星尘层降级关闭（非必需视觉）。
    dustCtx = typeof global.CanvasRenderingContext2D !== 'undefined'
      ? dustCanvas.getContext('2d')
      : null;

    svgThreads = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svgThreads.setAttribute('class', 'portal-threads');
    container.appendChild(svgThreads);

    var core = document.createElement('div');
    core.id = 'portalCoreHub';
    core.className = 'portal-core-hub';
    core.innerHTML = '<div class="core-halo"></div><div class="core-radar"></div><div class="core-pixel-box"><div class="core-badge">DIGITAL CORE</div><div class="core-title">工程智算</div><div class="core-sub"><span class="pixel-pulse-dot"></span> 枢纽在线</div></div>';
    core.onclick = returnToHub;
    container.appendChild(core);

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
      modBtn.onclick = function (e) { e.stopPropagation(); selectModule(m.id); };
      nodesLayer.appendChild(modBtn);
    });
    container.appendChild(nodesLayer);

    branchesLayer = document.createElement('div');
    branchesLayer.className = 'portal-branches-layer';
    container.appendChild(branchesLayer);

    fanLayer = document.createElement('div');
    fanLayer.className = 'portal-fan-layer';
    container.appendChild(fanLayer);

    drawer = document.createElement('aside');
    drawer.className = 'portal-analysis-drawer';
    container.appendChild(drawer);

    if (!mountPortal._escBound) {
      mountPortal._escBound = true;
      window.addEventListener('keydown', function (e) {
        if (e.key !== 'Escape') return;
        if (!container || container.classList.contains('hidden')) return;
        stepBack();
      });
    }

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
    returnToModule: returnToModule,
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

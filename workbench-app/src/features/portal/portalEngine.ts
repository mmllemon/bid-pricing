/**
 * 全景大盘动画引擎（P1 前端整合：由 frontend/js/portal-view.js 的引擎部分迁入 React）
 *
 * 设计：引擎保持框架无关——只操作 DOM 元素（由 React 通过 ref 交进来），不经 React state。
 * 每帧改属性（transform / SVG path d / canvas）若走 state，会每帧重渲染、必卡；
 * 故沿用原生版的做法：rAF 循环 + 直接改 DOM。
 *
 * 保留原生版全部行为：弹簧布局、贝塞尔触须、脉冲、星尘 canvas、级联开花、暂停/重播。
 * 唯一改动：模块/分支/卡片等元素由 React 渲染并传入 ref map，引擎不再自己建 DOM。
 */
import { MODULES, getBranches, getItems, type PortalModule, type PortalBranch, type PortalItem } from './portalData';

export interface Spring2 { x: number; v: number }

export const spring = (st: Spring2, target: number, dt: number, k = 62): number => {
  const c = 2 * Math.sqrt(k);
  st.v += (-k * (st.x - target) - c * st.v) * dt;
  st.x += st.v * dt;
  return st.x;
};
export const sp = (x: number): Spring2 => ({ x, v: 0 });
export const clamp = (v: number, a: number, b: number) => Math.max(a, Math.min(b, v));
export const bez = (p0: number, p1: number, p2: number, p3: number, u: number) => {
  const m = 1 - u;
  return m * m * m * p0 + 3 * m * m * u * p1 + 3 * m * u * u * p2 + u * u * u * p3;
};

const DUST = Array.from({ length: 110 }, (_, i) => ({
  a: i * 2.39996,
  v: 0.035 + ((i * 37) % 100) / 100 * 0.06,
  o: (i * 0.618034) % 1,
  w: (i % 2 ? 1 : -1) * (0.15 + (i % 7) * 0.05),
  s: 1.2 + (i % 5) * 0.6,
  b: 0.45 + (i % 3) * 0.25,
  c: i % 2 === 0 ? '255, 107, 0' : '229, 160, 0',
}));

export type Stage = 'hub' | 'module' | 'item';

export interface Layout {
  orb: { x: number; y: number; s: number };
  jelly: Record<string, { x: number; y: number; s: number; o: number; tilt: number }>;
  branches: { x: number; y0: number; gap: number } | null;
  leaves: { x: number; y0: number; gap: number } | null;
}

interface Sv {
  orbits: { el: SVGCircleElement }[];
  modThreads: Record<string, { g: SVGGElement; glow: SVGPathElement; core: SVGPathElement; pulses: SVGCircleElement[] }>;
  branchThreads: { g: SVGGElement; path: SVGPathElement; pulse: SVGCircleElement }[];
  leafThreads: { g: SVGGElement; path: SVGPathElement; pulses: SVGCircleElement[] }[];
}

export interface EngineRefs {
  /** 舞台容器（量尺寸）。 */
  stage: HTMLElement;
  /** 滚动容器（返回顶部用）。 */
  scroller: HTMLElement;
  dustCanvas: HTMLCanvasElement | null;
  dustCtx: CanvasRenderingContext2D | null;
  svgThreads: SVGSVGElement;
  core: HTMLElement;
  /** 模块 id → 元素 */
  modNodes: Record<string, HTMLElement>;
  /** 分支 id → 元素（展开态才存在） */
  branchNodes: Record<string, HTMLElement>;
  /** 卡片 id → 元素（展开态才存在） */
  leafCards: Record<string, HTMLElement>;
}

export function slotOf(selId: string | null, id: string): number {
  const others = MODULES.filter((m) => m.id !== selId).map((m) => m.id);
  const half = Math.floor(others.length / 2);
  const order = others.slice(0, half).concat([selId as string]).concat(others.slice(half));
  const k = order.indexOf(id);
  return k < 0 ? MODULES.findIndex((m) => m.id === id) : k;
}

/** 布局目标计算（逐字搬自原生版 targets）。 */
export function targets(
  L: { size: { w: number; h: number }; stage: Stage; mod: string | null; branch: string | null; time: number },
  t: number,
): Layout {
  const W = L.size.w;
  const H = L.size.h;
  const st = L.stage;
  const narrow = W < 1310;
  const res: Layout = { orb: { x: 0, y: 0, s: 0 }, jelly: {}, branches: null, leaves: null };
  const mods = MODULES;

  if (st === 'hub') {
    const s = narrow ? clamp(W * 0.34, 150, 210) : clamp(Math.min(W, H) * 0.43, 240, 380);
    const cy = narrow ? H * 0.48 : H * 0.47;
    res.orb = { x: W / 2, y: cy, s };

    const rx = narrow ? W * 0.36 : Math.min(W * 0.37, 560);
    const ry = narrow ? H * 0.29 : Math.min(H * 0.27, 236);

    mods.forEach((m, i) => {
      const base = -90 + (i * 360) / Math.max(mods.length, 1);
      const a = ((base + 5 * Math.sin(t * 0.16 + i * 1.6)) * Math.PI) / 180;
      const r = 1 + 0.035 * Math.sin(t * 0.2 + i);
      res.jelly[m.id] = {
        x: W / 2 + Math.cos(a) * rx * r,
        y: cy + Math.sin(a) * ry * r + 6 * Math.sin(t * 0.7 + i * 2.1),
        s: narrow ? 78 : clamp(W * 0.099, 104, 124),
        o: 1,
        tilt: 0,
      };
    });
  } else {
    const cy2 = H * 0.52;
    const coreS = narrow ? 112 : 158;
    const coreR = coreS / 2;
    const coreCx = narrow ? 76 : 120;

    const step = Math.min(96, (H - 170) / Math.max(mods.length, 1));
    const cardSel = Math.min(98, step - 6);
    const cardOther = Math.min(78, step - 6);

    const cardW = 120, branchW = 130;
    const coreGap = narrow ? 16 : 24;
    const gapA = narrow ? 70 : 100;
    const gapB = narrow ? 100 : 150;

    const d1 = coreR + coreGap + cardSel / 2;
    const col1_x = coreCx + d1;
    const col2_x = col1_x + cardW / 2 + gapA;
    const col3_x = col2_x + branchW + gapB;

    res.orb = { x: coreCx, y: cy2, s: coreS };

    mods.forEach((m) => {
      const sel = m.id === L.mod;
      const k = slotOf(L.mod, m.id);
      res.jelly[m.id] = {
        x: col1_x + (sel ? 14 : 0),
        y: cy2 + (k - (mods.length - 1) / 2) * step,
        s: sel ? cardSel : cardOther,
        o: sel ? 1 : 0.5,
        tilt: 0,
      };
    });

    const brs = getBranches(L.mod as string);
    const bn = brs.length;
    const bSpan = Math.max(0, bn - 1) * 76;
    res.branches = { x: col2_x, y0: cy2 - bSpan / 2, gap: bn > 1 ? bSpan / (bn - 1) : 0 };

    const leafItems = getItems(L.mod as string, L.branch as string);
    const ln = leafItems.length;
    const lSpan = Math.min(H - 150, Math.max(0, ln - 1) * 60);
    res.leaves = { x: col3_x, y0: cy2 - lSpan / 2, gap: ln > 1 ? lSpan / (ln - 1) : 0 };
  }
  return res;
}

/** 引擎实例：持有全部动画态与 SVG 缓存，由 React 组件创建与销毁。 */
export class PortalEngine {
  private refs: EngineRefs;
  private sv: Sv = { orbits: [], modThreads: {}, branchThreads: [], leafThreads: [] };
  private raf = 0;
  private lastTime = 0;
  private state = {
    stage: 'hub' as Stage,
    mod: null as string | null,
    branch: null as string | null,
    item: null as string | null,
    paused: false,
    time: 0,
    branchStart: 0,
    leafStart: 0,
    branchState: [] as ({ x: Spring2; y: Spring2; o: Spring2; cur?: { x: number; y: number } } | null)[],
    leafState: [] as ({ x: Spring2; y: Spring2; o: Spring2 } | null)[],
    size: { w: 1200, h: 800 },
    springs: {
      orb: { x: sp(600), y: sp(400), s: sp(150), o: sp(1) },
      dust: sp(0.4),
      jelly: {} as Record<string, { x: Spring2; y: Spring2; s: Spring2; o: Spring2; cur: { x: number; y: number; s: number } }>,
    },
  };

  /** 每帧回调：交给 React 做面包屑等低频状态同步用（不每帧调用 setState）。 */
  onFrame?: () => void;

  constructor(refs: EngineRefs) {
    this.refs = refs;
    MODULES.forEach((m) => {
      this.state.springs.jelly[m.id] = {
        x: sp(600), y: sp(400), s: sp(76), o: sp(1), cur: { x: 600, y: 400, s: 76 },
      };
    });
  }

  get current() {
    return this.state;
  }

  /** 重建 SVG 静态层（轨道环 + 模块触须）——随 svg 元素变化（stage 切换）重挂。 */
  buildStaticSvg() {
    const svg = this.refs.svgThreads;
    svg.innerHTML = '';
    this.sv = { orbits: [], modThreads: {}, branchThreads: [], leafThreads: [] };
    const NS = 'http://www.w3.org/2000/svg';

    [220, 380, 540].forEach((_cr, cidx) => {
      const c = document.createElementNS(NS, 'circle');
      c.setAttribute('class', `portal-orbit-ring ring-${cidx}`);
      svg.appendChild(c);
      this.sv.orbits.push({ el: c });
    });

    MODULES.forEach((m) => {
      const g = document.createElementNS(NS, 'g');
      const glow = document.createElementNS(NS, 'path');
      glow.setAttribute('fill', 'none');
      g.appendChild(glow);
      const core = document.createElementNS(NS, 'path');
      core.setAttribute('fill', 'none');
      g.appendChild(core);
      const pulses: SVGCircleElement[] = [];
      [0, 1, 2].forEach((k) => {
        const circle = document.createElementNS(NS, 'circle');
        circle.setAttribute('fill', m.color);
        circle.setAttribute('r', k === 2 ? '3' : '3.8');
        g.appendChild(circle);
        pulses.push(circle);
      });
      svg.appendChild(g);
      this.sv.modThreads[m.id] = { g, glow, core, pulses };
    });
  }

  private rebuildBranchSvg(mod: PortalModule) {
    const NS = 'http://www.w3.org/2000/svg';
    const svg = this.refs.svgThreads;
    this.sv.branchThreads.forEach((it) => it.g.remove());
    this.sv.branchThreads = [];
    this.sv.leafThreads.forEach((it) => it.g.remove());
    this.sv.leafThreads = [];

    (mod.branches || []).forEach(() => {
      const g = document.createElementNS(NS, 'g');
      const path = document.createElementNS(NS, 'path');
      path.setAttribute('fill', 'none');
      g.appendChild(path);
      const pulse = document.createElementNS(NS, 'circle');
      pulse.setAttribute('fill', mod.color);
      pulse.setAttribute('r', '2.5');
      g.appendChild(pulse);
      svg.appendChild(g);
      this.sv.branchThreads.push({ g, path, pulse });
    });
  }

  private rebuildLeafSvg(mod: PortalModule) {
    const NS = 'http://www.w3.org/2000/svg';
    const svg = this.refs.svgThreads;
    this.sv.leafThreads.forEach((it) => it.g.remove());
    this.sv.leafThreads = [];

    getItems(mod.id, this.state.branch as string).forEach(() => {
      const g = document.createElementNS(NS, 'g');
      const path = document.createElementNS(NS, 'path');
      path.setAttribute('fill', 'none');
      g.appendChild(path);
      const pulses: SVGCircleElement[] = [];
      [0, 1].forEach(() => {
        const p = document.createElementNS(NS, 'circle');
        p.setAttribute('fill', mod.color);
        p.setAttribute('r', '2.4');
        g.appendChild(p);
        pulses.push(p);
      });
      svg.appendChild(g);
      this.sv.leafThreads.push({ g, path, pulses });
    });
  }

  /** 切到模块层。 */
  selectModule(modId: string, targetBranchId?: string) {
    const mod = MODULES.find((m) => m.id === modId);
    if (!mod) return;
    const brs: PortalBranch[] = mod.branches || [];
    let brId = targetBranchId;
    if (!brId && brs.length > 0) brId = (brs.find((b) => b.isDefault) ?? brs[0]).id;

    const now = performance.now();
    Object.assign(this.state, {
      stage: 'module' as Stage,
      mod: modId,
      branch: brId ?? null,
      item: null,
      branchStart: now,
      leafStart: now + 40,
      branchState: brs.map(() => null),
      leafState: getItems(modId, brId).map(() => null),
    });
    this.rebuildBranchSvg(mod);
    this.rebuildLeafSvg(mod);
  }

  /** 切到分支（同一模块内换分支）。 */
  selectBranch(branchId: string) {
    if (!this.state.mod || this.state.branch === branchId) return;
    const mod = MODULES.find((m) => m.id === this.state.mod);
    if (!mod) return;
    this.state.branch = branchId;
    this.state.item = null;
    this.state.leafStart = performance.now();
    this.state.leafState = getItems(this.state.mod, branchId).map(() => null);
    this.rebuildLeafSvg(mod);
  }

  /** 切到条目（打开分析抽屉）。 */
  selectItem(itemId: string) {
    if (!this.state.mod || !this.state.branch) return;
    const it = getItems(this.state.mod, this.state.branch).find((x) => x.id === itemId);
    if (!it) return;
    this.state.stage = 'item';
    this.state.item = itemId;
  }

  /** 从条目退回模块层（不重放生长）。 */
  returnToModule() {
    if (this.state.stage !== 'item') return;
    this.state.stage = 'module';
    this.state.item = null;
  }

  returnToHub() {
    Object.assign(this.state, { stage: 'hub' as Stage, mod: null, branch: null, item: null, branchState: [], leafState: [] });
    this.sv.branchThreads.forEach((it) => it.g.remove());
    this.sv.branchThreads = [];
    this.sv.leafThreads.forEach((it) => it.g.remove());
    this.sv.leafThreads = [];
  }

  stepBack() {
    if (this.state.stage === 'item') this.returnToModule();
    else if (this.state.stage === 'module') this.returnToHub();
  }

  get paused() { return this.state.paused; }
  setPaused(v: boolean) { this.state.paused = v; }
  replay() { this.state.time = 0; this.state.paused = false; }

  /** 启动 rAF 循环。React 组件挂载后调用。 */
  start() {
    this.lastTime = performance.now();
    cancelAnimationFrame(this.raf);
    const loop = (now: number) => {
      this.raf = requestAnimationFrame(loop);
      const sz = this.refs.stage;
      if (!sz) return;
      const w = sz.clientWidth || window.innerWidth;
      const h = sz.clientHeight || window.innerHeight;
      if (this.refs.dustCanvas && (this.refs.dustCanvas.width !== w || this.refs.dustCanvas.height !== h)) {
        this.refs.dustCanvas.width = w;
        this.refs.dustCanvas.height = h;
        this.state.size = { w, h };
      }
      try {
        this.step(now);
      } catch (err) {
        // 保留原生版约定：某一帧出错不让整条循环死掉
        console.error('[PortalEngine] step error:', err);
      }
    };
    this.raf = requestAnimationFrame(loop);
  }

  stop() {
    cancelAnimationFrame(this.raf);
  }

  // —— 主步进（逐字搬自原生版 step）——
  private step(now: number) {
    const rawDt = Math.max(0, Math.min(1 / 30, (now - this.lastTime) / 1000));
    this.lastTime = now;
    const L = this.state;
    if (!L.paused) L.time += rawDt;
    const dt = L.paused ? 0 : rawDt;

    const stageEl = this.refs.stage;
    if (stageEl) {
      const realW = stageEl.clientWidth || window.innerWidth;
      const realH = stageEl.clientHeight || window.innerHeight;
      if (realW > 100 && realH > 100) L.size = { w: realW, h: realH };
    }

    const t = L.time;
    const S = L.springs;
    const T = targets(L, t);

    // 1. 中心核心弹簧
    const ox = spring(S.orb.x, T.orb.x, dt);
    const oy = spring(S.orb.y, T.orb.y, dt);
    const os = spring(S.orb.s, T.orb.s, dt, 40);
    const oo = spring(S.orb.o, 1, dt, 30);

    const coreEl = this.refs.core;
    if (coreEl) {
      coreEl.style.transform = `translate3d(${ox - os / 2}px, ${oy - os / 2}px, 0) scale(${os / 340})`;
      coreEl.style.opacity = String(clamp(oo, 0, 1));
    }

    // 2. 星尘 canvas
    const { dustCtx, dustCanvas } = this.refs;
    if (dustCtx && dustCanvas) {
      dustCtx.clearRect(0, 0, dustCanvas.width, dustCanvas.height);
      const dInt = clamp(spring(S.dust, L.stage === 'hub' ? 0.8 : 0.32, dt, 18), 0, 1);
      if (dInt > 0.02) {
        for (const p of DUST) {
          const ph = ((t * p.v + p.o) % 1 + 1) % 1;
          const r = os * 0.45 + ph * (os * 0.95);
          const a = p.a + ph * p.w;
          const px = ox + Math.cos(a) * r;
          const py = oy + Math.sin(a) * r * 0.94;
          const al = dInt * Math.pow(Math.max(0, Math.sin(ph * Math.PI)), 1.3) * p.b;
          dustCtx.fillStyle = `rgba(${p.c}, ${al})`;
          dustCtx.fillRect(px - p.s / 2, py - p.s / 2, p.s, p.s);
        }
      }
    }

    // 3. 轨道环
    this.sv.orbits.forEach((item) => {
      if (L.stage === 'hub') {
        item.el.setAttribute('cx', String(ox));
        item.el.setAttribute('cy', String(oy));
        item.el.style.display = 'block';
      } else {
        item.el.style.display = 'none';
      }
    });

    // 4. 模块节点 + 核心触须
    MODULES.forEach((m, i) => {
      const j = S.jelly[m.id];
      const tg = T.jelly[m.id];
      if (!j || !tg) return;

      const x = spring(j.x, tg.x, dt);
      const y = spring(j.y, tg.y, dt);
      const s = spring(j.s, tg.s, dt);
      const o = spring(j.o, tg.o, dt, 40);
      j.cur = { x, y, s };

      const el = this.refs.modNodes[m.id];
      if (el) {
        el.style.transform = `translate3d(${x - s / 2}px, ${y - s / 2}px, 0) scale(${s / 120}) rotate(${tg.tilt}deg)`;
        el.style.opacity = String(clamp(o, 0, 1));
        el.classList.toggle('node-active', m.id === L.mod);
        el.classList.toggle('node-dimmed', L.stage !== 'hub' && m.id !== L.mod);
      }

      const tObj = this.sv.modThreads[m.id];
      if (tObj) {
        const dx = x - ox, dy = y - oy;
        const dist = Math.hypot(dx, dy) || 1;
        const ux = dx / dist, uy = dy / dist;
        const x1 = ox + ux * os * 0.35, y1 = oy + uy * os * 0.35;
        const x2 = x - ux * s * 0.4, y2 = y - uy * s * 0.4;
        const bend = L.stage === 'hub' ? 22 * Math.sin(t * 0.5 + i) : 4;
        const c1x = x1 + dx * 0.35 - uy * bend, c1y = y1 + dy * 0.35 + ux * bend;
        const c2x = x1 + dx * 0.7 + uy * bend, c2y = y1 + dy * 0.7 - ux * bend;
        const dPath = `M${x1},${y1} C${c1x},${c1y} ${c2x},${c2y} ${x2},${y2}`;
        const isActive = m.id === L.mod;
        const strokeColor = isActive ? m.color : 'rgba(17, 17, 17, 0.22)';
        const strokeWidth = isActive ? 2.5 : 1.2;

        tObj.glow.setAttribute('d', dPath);
        tObj.glow.setAttribute('stroke', strokeColor);
        tObj.glow.setAttribute('stroke-width', String(strokeWidth * 2));
        tObj.glow.setAttribute('stroke-opacity', isActive ? '0.3' : '0.08');
        tObj.core.setAttribute('d', dPath);
        tObj.core.setAttribute('stroke', strokeColor);
        tObj.core.setAttribute('stroke-width', String(strokeWidth));
        tObj.core.setAttribute('stroke-opacity', String(clamp(o, 0, 1)));

        tObj.pulses.forEach((circle, k) => {
          const inbound = k === 2;
          let u = (t * (inbound ? 0.24 : 0.32) + k * 0.48 + i * 0.16) % 1;
          if (inbound) u = 1 - u;
          circle.setAttribute('cx', String(bez(x1, c1x, c2x, x2, u)));
          circle.setAttribute('cy', String(bez(y1, c1y, c2y, y2, u)));
          circle.setAttribute('opacity', String(Math.sin(u * Math.PI) * clamp(o, 0, 1)));
        });
      }
    });

    // 5A. 模块 → 分支（依次开花）
    if (T.branches && L.mod) {
      const currentMod = MODULES.find((m) => m.id === L.mod);
      const branches = getBranches(L.mod);
      const sj = S.jelly[L.mod];
      if (currentMod && sj) {
        const mOx = sj.cur.x + sj.cur.s * 0.5 + 4;
        const mOy = sj.cur.y;

        branches.forEach((b, bi) => {
          if (!L.branchState[bi]) L.branchState[bi] = { x: sp(mOx), y: sp(mOy), o: sp(0) };
          const bst = L.branchState[bi]!;
          const bReady = now - L.branchStart > 60 + bi * 80;
          const bTx = T.branches!.x;
          const bTy = T.branches!.y0 + bi * T.branches!.gap + Math.sin(t * 0.8 + bi) * 2;
          const bX = spring(bst.x, bReady ? bTx : mOx, dt, 70);
          const bY = spring(bst.y, bReady ? bTy : mOy, dt, 70);
          const bO = spring(bst.o, bReady ? 1 : 0, dt, 50);
          bst.cur = { x: bX, y: bY };

          const bEl = this.refs.branchNodes[b.id];
          if (bEl) {
            bEl.style.transform = `translate3d(${bX}px, ${bY - 19}px, 0)`;
            bEl.style.opacity = String(clamp(bO, 0, 1));
            bEl.classList.toggle('branch-active', b.id === L.branch);
          }

          const bSvg = this.sv.branchThreads[bi];
          if (bSvg) {
            if (bO > 0.02) {
              const bdx = bX - mOx;
              const bsway = Math.sin(t * 1.0 + bi * 0.8) * 5;
              const bc1x = mOx + bdx * 0.45, bc1y = mOy + bsway;
              const bc2x = bX - bdx * 0.4, bc2y = bY - bsway * 0.5;
              bSvg.path.setAttribute('d', `M${mOx},${mOy} C${bc1x},${bc1y} ${bc2x},${bc2y} ${bX},${bY}`);
              const isBrSel = b.id === L.branch;
              bSvg.path.setAttribute('stroke', isBrSel ? currentMod.color : 'rgba(17,17,17,0.3)');
              bSvg.path.setAttribute('stroke-width', isBrSel ? '2.2' : '1.2');
              bSvg.path.setAttribute('stroke-opacity', String(clamp(bO, 0, 1)));

              const bfu = (t * 0.35 + bi * 0.2) % 1;
              bSvg.pulse.setAttribute('cx', String(bez(mOx, bc1x, bc2x, bX, bfu)));
              bSvg.pulse.setAttribute('cy', String(bez(mOy, bc1y, bc2y, bY, bfu)));
              bSvg.pulse.setAttribute('opacity', String(clamp(bO, 0, 1) * Math.sin(bfu * Math.PI)));
              bSvg.g.style.display = 'block';
            } else {
              bSvg.g.style.display = 'none';
            }
          }
        });
      }
    }

    // 5B. 分支 → 卡片（伞状开花）
    if (T.leaves && L.mod && L.branch) {
      const currentMod2 = MODULES.find((m) => m.id === L.mod);
      const leafItems = getItems(L.mod, L.branch);
      const branches2 = getBranches(L.mod);
      const activeBrIdx = branches2.findIndex((b) => b.id === L.branch);
      const activeBrState = L.branchState[activeBrIdx];
      if (activeBrState?.cur && currentMod2) {
        const brOx = activeBrState.cur.x + 130 + 4;
        const brOy = activeBrState.cur.y;

        leafItems.forEach((it, li) => {
          if (!L.leafState[li]) L.leafState[li] = { x: sp(brOx), y: sp(brOy), o: sp(0) };
          const lst = L.leafState[li]!;
          const leafReady = now - L.leafStart > 60 + li * Math.min(70, 700 / Math.max(leafItems.length, 1));
          const lTx = T.leaves!.x;
          const lTy = T.leaves!.y0 + li * T.leaves!.gap + Math.sin(t * 0.75 + li * 0.8) * 2;
          const lx = spring(lst.x, leafReady ? lTx : brOx, dt, 70);
          const ly = spring(lst.y, leafReady ? lTy : brOy, dt, 70);
          const lo = spring(lst.o, leafReady ? 1 : 0, dt, 50);

          const itEl = this.refs.leafCards[it.id];
          if (itEl) {
            itEl.style.transform = `translate3d(${lx}px, ${ly - 24}px, 0)`;
            itEl.style.opacity = String(clamp(lo, 0, 1));
            itEl.classList.toggle('item-selected', L.item === it.id);
          }

          const lSvg = this.sv.leafThreads[li];
          if (lSvg) {
            if (lo > 0.02) {
              const ldx = lx - brOx;
              const lsway = Math.sin(t * 1.1 + li * 0.7) * 6;
              const lc1x = brOx + ldx * 0.45, lc1y = brOy + lsway;
              const lc2x = lx - ldx * 0.4, lc2y = ly - lsway * 0.5;
              lSvg.path.setAttribute('d', `M${brOx},${brOy} C${lc1x},${lc1y} ${lc2x},${lc2y} ${lx},${ly}`);
              const isLeafSel = L.item === it.id;
              lSvg.path.setAttribute('stroke', isLeafSel ? currentMod2.color : 'rgba(17, 17, 17, 0.28)');
              lSvg.path.setAttribute('stroke-width', isLeafSel ? '2.2' : '1.2');
              lSvg.path.setAttribute('stroke-opacity', String(clamp(lo, 0, 1)));
              lSvg.pulses.forEach((pCircle, k) => {
                let lfu = (t * (k ? 0.28 : 0.36) + li * 0.14 + k * 0.5) % 1;
                if (k) lfu = 1 - lfu;
                pCircle.setAttribute('cx', String(bez(brOx, lc1x, lc2x, lx, lfu)));
                pCircle.setAttribute('cy', String(bez(brOy, lc1y, lc2y, ly, lfu)));
                pCircle.setAttribute('opacity', String(clamp(lo, 0, 1) * Math.sin(lfu * Math.PI)));
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
}

export type { PortalModule, PortalBranch, PortalItem };

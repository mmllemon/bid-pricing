import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  MODULES, getBranches, getItems, getModule,
  type PortalBranch, type PortalItem,
} from './portalData';
import { PortalEngine, getModuleLevels, type EngineRefs, type Stage } from './portalEngine';
import { PortalSnapshot } from './PortalSnapshot';
import { PortalDrawer } from './PortalDrawer';

/**
 * 全景大盘（P1 前端整合：由 frontend/js/portal-view.js + portal.css 迁入 React）
 *
 * 架构：结构由 React 渲染，每帧动画由 PortalEngine 直接操作 DOM（ref），
 * 不经 React state——否则每帧重渲染会卡。React 只持有低频状态（stage/mod/branch/item/paused）。
 *
 * 样式沿用 portal.css（已并入 workbench-app/src/styles/global.css 的 portal 段）。
 */
export default function PortalPage() {
  // 低频 UI 状态（与引擎同步）
  const [stage, setStage] = useState<Stage>('hub');
  const [mod, setMod] = useState<string | null>(null);
  const [branch, setBranch] = useState<string | null>(null);
  const [item, setItem] = useState<string | null>(null);
  const [paused, setPaused] = useState(false);

  // DOM refs
  const scrollerRef = useRef<HTMLDivElement | null>(null);
  const stageRef = useRef<HTMLDivElement | null>(null);
  const dustRef = useRef<HTMLCanvasElement | null>(null);
  const svgRef = useRef<SVGSVGElement | null>(null);
  const coreRef = useRef<HTMLDivElement | null>(null);
  const modNodeRefs = useRef<Record<string, HTMLButtonElement | null>>({});
  const branchNodeRefs = useRef<Record<string, HTMLButtonElement | null>>({});
  const leafCardRefs = useRef<Record<string, HTMLButtonElement | null>>({});
  const engineRef = useRef<PortalEngine | null>(null);

  const activeModule = mod ? getModule(mod) : undefined;
  const branches = mod ? getBranches(mod) : [];
  // 可变深度（2026-10-08）：levels<=2 且无分支时，用扁平化 items
  const leafItems = (() => {
    if (!mod) return [];
    if (branch) return getItems(mod, branch);
    // flat 模式：从配置读 levels
    try {
      const cfg = getModuleLevels(mod);
      if (cfg <= 2) {
        return getBranches(mod).flatMap((b) => getItems(mod, b.id));
      }
    } catch { /* fallback */ }
    return [];
  })();

  /** 把引擎状态同步到 React 低频状态（交互后调用，非每帧）。 */
  const syncFromEngine = useCallback(() => {
    const s = engineRef.current?.current;
    if (!s) return;
    setStage(s.stage);
    setMod(s.mod);
    setBranch(s.branch);
    setItem(s.item);
    setPaused(s.paused);
  }, []);

  // 建引擎（挂载一次）
  useEffect(() => {
    const r: EngineRefs = {
      stage: stageRef.current as HTMLElement,
      scroller: scrollerRef.current as HTMLElement,
      dustCanvas: dustRef.current,
      dustCtx: typeof CanvasRenderingContext2D !== 'undefined' && dustRef.current
        ? dustRef.current.getContext('2d')
        : null,
      svgThreads: svgRef.current as SVGSVGElement,
      core: coreRef.current as HTMLElement,
      modNodes: modNodeRefs.current as Record<string, HTMLElement>,
      branchNodes: branchNodeRefs.current as Record<string, HTMLElement>,
      leafCards: leafCardRefs.current as Record<string, HTMLElement>,
    };
    const engine = new PortalEngine(r);
    engineRef.current = engine;
    engine.buildStaticSvg();
    engine.start();
    return () => engine.stop();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 分支/卡片元素随 stage 变化重挂，引擎用的是 ref map，天然拿到最新元素。

  const doSelectModule = useCallback((modId: string, targetBranch?: string) => {
    engineRef.current?.selectModule(modId, targetBranch);
    syncFromEngine();
    const el = scrollerRef.current;
    if (el) el.scrollTop = 0;
  }, [syncFromEngine]);

  const doSelectBranch = useCallback((branchId: string) => {
    engineRef.current?.selectBranch(branchId);
    syncFromEngine();
  }, [syncFromEngine]);

  const doSelectItem = useCallback((itemId: string) => {
    engineRef.current?.selectItem(itemId);
    syncFromEngine();
  }, [syncFromEngine]);

  const doReturnToHub = useCallback(() => {
    engineRef.current?.returnToHub();
    syncFromEngine();
  }, [syncFromEngine]);

  const doReturnToModule = useCallback(() => {
    engineRef.current?.returnToModule();
    syncFromEngine();
  }, [syncFromEngine]);

  const doStepBack = useCallback(() => {
    engineRef.current?.stepBack();
    syncFromEngine();
  }, [syncFromEngine]);

  const togglePause = useCallback(() => {
    const e = engineRef.current;
    if (!e) return;
    e.setPaused(!e.paused);
    syncFromEngine();
  }, [syncFromEngine]);

  const replay = useCallback(() => {
    engineRef.current?.replay();
    syncFromEngine();
  }, [syncFromEngine]);

  // Esc 逐层回退
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !e.isComposing) doStepBack();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [doStepBack]);

  const currentBranch = branches.find((b) => b.id === branch);
  const currentItem = leafItems.find((it) => it.id === item);

  const totalItems = useMemo(
    () => MODULES.reduce((s, m) => s + getItems(m.id).length, 0),
    [],
  );

  const stageClass = stage === 'hub' ? 'stage-hub' : stage === 'module' ? 'stage-module' : 'stage-item';

  return (
    <div className={`portal-view ${stageClass}`} ref={scrollerRef}>
      {/* 顶部导航已由 AppShell 的 SiteTopBar 提供（全站统一），本组件不再自带顶栏。 */}
      {/* 舞台：一屏高，动画层都在里面 */}
      <div className="portal-stage" ref={stageRef}>
        {/* 面包屑：仅展开态可见（CSS 按 .portal-view.stage-module/item 控制） */}
        <div className="portal-crumbs">
          {stage === 'module' && (
            <>
              <button type="button" className="crumb-link" onClick={doReturnToHub}>全景大盘</button>
              <span className="sep">/</span>
              <strong className="crumb-active">
                {activeModule ? `${activeModule.code} ${activeModule.name}` : ''}{currentBranch ? ` · ${currentBranch.label}` : ''}
              </strong>
            </>
          )}
          {stage === 'item' && (
            <>
              <button type="button" className="crumb-link" onClick={doReturnToHub}>全景大盘</button>
              <span className="sep">/</span>
              <button type="button" className="crumb-link" onClick={() => doSelectModule(mod as string, branch as string)}>{activeModule?.name}</button>
              <span className="sep">/</span>
              <button type="button" className="crumb-link" onClick={() => doSelectBranch(branch as string)}>{currentBranch?.label}</button>
              <span className="sep">/</span>
              <strong className="crumb-active">{currentItem?.title}</strong>
            </>
          )}
        </div>

        <canvas className="portal-dust-canvas" ref={dustRef} />

        {/* SVG 触须层：引擎在 buildStaticSvg 里填充 */}
        <svg className="portal-threads" ref={svgRef} />

        {/* 四角配件：hub 态可见，展开态由 CSS 淡出 */}
        <div className="portal-chrome">
          <div className="portal-stage-tools">
            <button type="button" className="pixel-pill-btn" onClick={replay}>↻ 重播</button>
            <button type="button" className="pixel-pill-btn" aria-pressed={paused} onClick={togglePause}>
              {paused ? '▶ 继续' : '❚❚ 暂停'}
            </button>
            <button type="button" className="pixel-pill-btn" onClick={doReturnToHub}>重置视角</button>
          </div>

          <div className="portal-hero-copy">
            <p className="hero-eyebrow">ENGINEERING NEURAL SKY <span>工程智算·全景</span></p>
            <h1>让每一个工程，<br />长成一张网络。</h1>
            <p className="hero-hint">点击模块节点，展开它的业务链条 · <em>Tap a module to expand</em></p>
          </div>

          <aside className="portal-legend">
            <h3>图例 <em>Legend</em></h3>
            {MODULES.map((m) => (
              <div className="legend-row" key={m.id}>
                <i style={{ background: m.color }} />{m.name}<b>{getItems(m.id).length}</b>
              </div>
            ))}
            <div className="legend-lines">
              <span><i className="ln one" />触须连线</span>
              <span><i className="ln pulse" />能量脉冲</span>
            </div>
          </aside>

          <div className="portal-dock">
            <div className="dock-kpis">
              <div><span>业务模块 <em>Modules</em></span><strong>{MODULES.length}</strong></div>
              <div><span>实体条目 <em>Records</em></span><strong>{totalItems}</strong></div>
              <div><span>运行进程 <em>Procs</em></span><strong>2</strong></div>
              <div><span>架位 <em>Slots</em></span><strong>—</strong></div>
            </div>
            <p className="dock-hint"><span className="pixel-pulse-dot" /> 本地运行 · 数据仅存本机 <em>Local · nothing leaves this machine</em></p>
          </div>
        </div>

        {/* 中心核心 */}
        <div className="portal-core-hub" ref={coreRef} onClick={doReturnToHub}>
          <div className="core-halo" />
          <div className="core-ring r0" />
          <div className="core-ring r1" />
          <div className="core-ring r2" />
          <div className="core-radar" />
          <div className="core-pixel-box">
            <div className="core-badge">DIGITAL CORE</div>
            <div className="core-title">工程智算</div>
            <div className="core-sub"><span className="pixel-pulse-dot" /> 枢纽在线</div>
          </div>
        </div>

        {/* 模块节点层 */}
        <div className="portal-nodes-layer">
          {MODULES.map((m) => (
            <button
              key={m.id}
              type="button"
              className={`portal-mod-node group-${m.group}`}
              data-id={m.id}
              ref={(el) => { modNodeRefs.current[m.id] = el; }}
              onClick={(e) => { e.stopPropagation(); doSelectModule(m.id); }}
            >
              <div className="mod-node-head">
                <span className="mod-code" style={{ color: m.color }}>{m.code}</span>
                <span className="mod-icon-badge">{m.icon}</span>
              </div>
              <div className="mod-node-name">{m.name}</div>
              <div className="mod-node-sub">{m.subtitle}</div>
            </button>
          ))}
        </div>

        {/* 分支节点层 */}
        <div className="portal-branches-layer">
          {branches.map((b: PortalBranch) => (
            <button
              key={b.id}
              type="button"
              className="portal-branch-node"
              data-id={b.id}
              ref={(el) => { branchNodeRefs.current[b.id] = el; }}
              onClick={(e) => { e.stopPropagation(); doSelectBranch(b.id); }}
            >
              <span className="branch-anchor-in" style={{ background: activeModule?.color }} />
              <span className="branch-content">
                <span className="branch-code" style={{ color: activeModule?.color }}>{b.code}</span>
                <span className="branch-title">{b.label}</span>
              </span>
              <span className="branch-anchor-out" style={{ background: activeModule?.color }} />
            </button>
          ))}
        </div>

        {/* 卡片层 */}
        <div className="portal-fan-layer">
          <div className="fan-items-list">
            {leafItems.map((it: PortalItem) => (
              <button
                key={it.id}
                type="button"
                className="portal-fan-card"
                data-id={it.id}
                ref={(el) => { leafCardRefs.current[it.id] = el; }}
                onClick={(e) => { e.stopPropagation(); doSelectItem(it.id); }}
              >
                <span className="card-anchor-dot" style={{ background: activeModule?.color }} />
                <span className="card-left"><span className="pixel-num">{it.code}</span></span>
                <span className="card-mid">
                  <span className="card-title">{it.title}</span>
                  <span className="card-desc">{it.desc || ''}</span>
                </span>
                {it.stage && (
                  <span className="card-right">
                    <span className={`stage-tag ${it.stage === '投标' ? 'tag-bid' : it.stage === '中标在建' ? 'tag-build' : 'tag-done'}`}>{it.stage}</span>
                  </span>
                )}
              </button>
            ))}
          </div>
        </div>

        {/* 深度分析抽屉 */}
        <PortalDrawer
          open={stage === 'item'}
          module={activeModule}
          item={currentItem}
          onClose={doReturnToModule}
          onEnter={() => {
            if (!activeModule) return;
            if (activeModule.id === 'quote') window.location.href = '/#quote';
            else if (activeModule.id === 'tools') window.location.href = '/tools.html';
            else doSelectModule(activeModule.id);
          }}
        />
      </div>

      {/* 舞台下方的工程快照段 */}
      <PortalSnapshot onGoBiz={() => doSelectModule('biz', 'projects')} onGoTodos={() => doSelectModule('todos', 'p0')} />
    </div>
  );
}

import { useLayoutEffect, useRef, useState } from 'react';
import type { PortalItem, PortalModule } from './portalData';
import { ExpandableCard } from './ExpandableCard';
import { getPortalConfig } from './portalConfig';

/**
 * 深度分析抽屉（P1 迁移：由 portal-view.js openDrawer 迁入 React）。
 * 按模块业务动态渲染：项目经营（biz）走「概况/报价/执行/文档/待办」五 Tab；
 * 其余模块走通用结构（desc + metrics + planDetail/costDetail/finDetail）。
 * 2026-10-08 Step A：配了 summaryFields 的模块走可展开卡片（摘要→详情）。
 */
export function PortalDrawer({
  open,
  module,
  item,
  onClose,
  onEnter,
  onExpandChange,
}: {
  open: boolean;
  module?: PortalModule;
  item?: PortalItem;
  onClose: () => void;
  onEnter: () => void;
  onExpandChange?: (expanded: boolean) => void;
}) {
  const [tab, setTab] = useState('tab-overview');
  const [cardExpanded, setCardExpanded] = useState(false);
  const drawerRef = useRef<HTMLElement>(null);
  const firstRectRef = useRef<DOMRect | null>(null);
  // 跟踪 item 切换以重置展开态（必须在 early return 之前，Hooks 规则）
  const [lastItemId, setLastItemId] = useState<string | null>(null);

  /** FLIP 展开动画（2026-10-08 Step B，重构：useLayoutEffect 保时机） */
  const doExpand = () => {
    const el = drawerRef.current;
    // First: 在 React 提交前记录
    if (el) {
      firstRectRef.current = el.getBoundingClientRect();
    }
    onExpandChange?.(true);
    setCardExpanded(true);
  };

  // React 提交后（DOM 已是 Last 态）再量尺寸、播动画
  useLayoutEffect(() => {
    if (!cardExpanded) return;
    const el = drawerRef.current;
    const first = firstRectRef.current;
    if (!el || !first) return;
    firstRectRef.current = null;

    const last = el.getBoundingClientRect();
    const dx = first.left - last.left;
    const dy = first.top - last.top;
    const sx = first.width / last.width;
    const sy = first.height / last.height;
    // 无变化就不播
    if (dx === 0 && dy === 0 && sx === 1 && sy === 1) return;

    // Invert: 先摆回 First 的样子
    el.style.transformOrigin = 'top left';
    el.style.transition = 'none';
    el.style.transform = `translate(${dx}px, ${dy}px) scale(${sx}, ${sy})`;
    // 强制回流，让 Invert 生效
    void el.offsetWidth;
    // Play: 过渡到 Last
    el.style.transition = 'transform 0.6s cubic-bezier(0.22, 1, 0.36, 1)';
    el.style.transform = 'translate(0, 0) scale(1, 1)';

    const timer = setTimeout(() => {
      el.style.transition = '';
      el.style.transform = '';
      el.style.transformOrigin = '';
    }, 650);
    return () => clearTimeout(timer);
  }, [cardExpanded]);

  if (!module || !item) {
    return <aside className={`portal-analysis-drawer${open ? ' open' : ''}`} />;
  }

  // 可展开卡片优先（2026-10-08）：配了 summaryFields 就走新交互
  const modCfg = getPortalConfig().modules.find((m) => m.id === module.id);
  const useExpandable = Boolean(modCfg?.summaryFields);

  const isBiz = module.id === 'biz' && Boolean(item.profile);

  // 重置展开态（切换卡片时）
  if (lastItemId !== item.id) {
    setLastItemId(item.id);
    setCardExpanded(false);
    onExpandChange?.(false);
  }

  return (
    <aside
      ref={drawerRef}
      className={`portal-analysis-drawer${open ? ' open' : ''}${cardExpanded ? ' expanded' : ''}`}
      role="complementary"
      aria-label="深度分析"
    >
      <div className="ad-head">
        <div className="ad-badge-group">
          <span className="pixel-tag" style={{ background: module.color, color: '#fff' }}>{module.code}</span>
          <span className="pixel-badge">{module.group === 'engineering' ? '工程主链' : '经营管理'}</span>
          {item.stage && <span className="pixel-badge stage-badge">{item.stage}</span>}
        </div>
        <button type="button" className="ad-close-btn" onClick={onClose} aria-label="关闭">&times;</button>
      </div>

      <h2 className="ad-title">{item.title}</h2>
      <div className="ad-sub">{item.code} · 业务要素深度分析与控制舱</div>

      {useExpandable ? (
        <ExpandableCard
          module={module}
          item={item}
          expanded={cardExpanded}
          onExpand={doExpand}
        />
      ) : isBiz ? (
        <>
          <div className="ad-tabs-header">
            {[
              ['tab-overview', '概况'],
              ['tab-quote', '报价'],
              ['tab-exec', '执行'],
              ['tab-docs', `文档 (${item.docs?.length ?? 0})`],
              ['tab-todos', `待办 (${item.todos?.length ?? 0})`],
            ].map(([id, label]) => (
              <button
                key={id}
                type="button"
                className={`ad-tab-btn${tab === id ? ' active' : ''}`}
                onClick={() => setTab(id)}
              >
                {label}
              </button>
            ))}
          </div>

          {tab === 'tab-overview' && (
            <div className="ad-tab-content active">
              <div className="ad-kv-list">
                {[
                  ['合同编号', item.profile?.contractNo],
                  ['建设单位', item.profile?.client],
                  ['承建单位', item.profile?.builder],
                  ['开标时间', item.profile?.openDate],
                  ['工程体量', item.profile?.scale],
                ].map(([k, v]) => (
                  <div className="kv-item" key={k}><span className="k">{k}</span><strong className="v">{v}</strong></div>
                ))}
              </div>
              <div className="ad-stage-switcher">
                <span className="switcher-label">快速流转阶段：</span>
                {['投标', '中标在建', '已竣工', '未中标'].map((st) => (
                  <button key={st} type="button" className={`btn-stage-switch${item.stage === st ? ' active' : ''}`}>{st}</button>
                ))}
              </div>
            </div>
          )}

          {tab === 'tab-quote' && (
            <div className="ad-tab-content active">
              <div className="ad-metrics-grid">
                <div className="ad-metric-box"><span className="m-label">目标总报价</span><strong className="m-val">¥ {item.quote?.targetTotal}</strong></div>
                <div className="ad-metric-box"><span className="m-label">下浮率</span><strong className="m-val" style={{ color: '#ff5a1f' }}>{item.quote?.rate}</strong></div>
                <div className="ad-metric-box"><span className="m-label">安全防线</span><strong className="m-val">{item.quote?.guardrail}</strong></div>
              </div>
              <div className="ad-kv-list" style={{ marginTop: 10 }}>
                <div className="kv-item"><span className="k">固定税前项</span><strong className="v">¥ {item.quote?.fixedPretax}</strong></div>
                <div className="kv-item"><span className="k">增值税/附加税</span><strong className="v">{item.quote?.vatRate} / {item.quote?.surtaxRate}</strong></div>
              </div>
              <button type="button" className="pixel-btn-action" onClick={() => { window.location.href = '/#quote'; }}>带入此项目进入投标报价沙盘 →</button>
            </div>
          )}

          {tab === 'tab-exec' && (
            <div className="ad-tab-content active">
              <div className="ad-progress-box">
                <div className="p-head"><span>综合进度</span><strong>{item.progress}%</strong></div>
                <div className="p-bar"><div className="p-fill" style={{ width: `${item.progress}%` }} /></div>
              </div>
              <div className="ad-kv-list">
                <div className="kv-item"><span className="k">当前状态</span><strong className="v">{item.execution?.status}</strong></div>
                <div className="kv-item"><span className="k">项目团队</span><strong className="v">{item.execution?.team}</strong></div>
                <div className="kv-item"><span className="k">风控评级</span><strong className="v">{item.execution?.riskLevel}</strong></div>
              </div>
            </div>
          )}

          {tab === 'tab-docs' && (
            <div className="ad-tab-content active">
              <div className="ad-doc-list">
                {(item.docs || []).map((doc) => (
                  <div className="doc-row" key={doc.name}>
                    <div className="doc-info">
                      <span className="doc-name">{doc.name}</span>
                      <span className="doc-meta">{doc.size} · {doc.time}</span>
                    </div>
                    <button type="button" className="doc-btn-view">查阅</button>
                  </div>
                ))}
              </div>
            </div>
          )}

          {tab === 'tab-todos' && (
            <div className="ad-tab-content active">
              <div className="ad-todo-list">
                {(item.todos || []).map((td) => (
                  <label className="todo-check-row" key={td.id}>
                    <input type="checkbox" className="todo-check-box" defaultChecked={td.done} />
                    <span className={`todo-text${td.done ? ' done' : ''}`}>{td.text}</span>
                  </label>
                ))}
              </div>
              <div className="ad-add-todo-bar">
                <input type="text" placeholder="输入并新增此项目待办..." />
                <button type="button">添加</button>
              </div>
            </div>
          )}
        </>
      ) : (
        <>
          <p className="ad-desc">{item.desc}</p>
          {item.metrics && item.metrics.length > 0 && (
            <div className="ad-metrics-grid">
              {item.metrics.map((m) => (
                <div className="ad-metric-box" key={m[0]}><span className="m-label">{m[0]}</span><strong className="m-val">{m[1]}</strong></div>
              ))}
            </div>
          )}
          {item.planDetail && (
            <>
              <div className="ad-section-title">方案推演控制参数</div>
              <div className="ad-kv-list">
                <div className="kv-item"><span className="k">目标总价</span><strong className="v">¥ {String(item.planDetail.targetTotal)}</strong></div>
                <div className="kv-item"><span className="k">预估毛利</span><strong className="v">{String(item.planDetail.grossProfit)} ({String(item.planDetail.grossMargin)})</strong></div>
                <div className="kv-item"><span className="k">不平衡项数</span><strong className="v">{String(item.planDetail.unbalancedCount)} 项</strong></div>
              </div>
              <button type="button" className="pixel-btn-action">设为基准对比槽位 →</button>
            </>
          )}
          {item.costDetail && (
            <>
              <div className="ad-section-title">责任成本核对凭据</div>
              <div className="ad-kv-list">
                <div className="kv-item"><span className="k">预算额</span><strong className="v">¥ {item.costDetail.budget}</strong></div>
                <div className="kv-item"><span className="k">实际发生额</span><strong className="v">¥ {item.costDetail.spent}</strong></div>
                <div className="kv-item"><span className="k">预警状态</span><strong className="v">{item.costDetail.alertLevel}</strong></div>
              </div>
            </>
          )}
          {item.finDetail && (
            <>
              <div className="ad-section-title">对账单核对凭证</div>
              <div className="ad-kv-list">
                <div className="kv-item"><span className="k">结算账户</span><strong className="v">{item.finDetail.account}</strong></div>
                <div className="kv-item"><span className="k">发票凭证</span><strong className="v">{item.finDetail.invoiceStatus}</strong></div>
                <div className="kv-item"><span className="k">往来单位</span><strong className="v">{item.finDetail.counterparty}</strong></div>
              </div>
              <button type="button" className="pixel-btn-action">已完成线下核对，标记对账通过 ✓</button>
            </>
          )}
        </>
      )}

      <div className="ad-actions">
        <button type="button" className="pixel-btn-primary" style={{ background: module.color, borderColor: '#111' }} onClick={onEnter}>
          穿透进入{module.name}系统 →
        </button>
        <button type="button" className="pixel-btn-secondary" onClick={onClose}>返回上一层</button>
      </div>
    </aside>
  );
}

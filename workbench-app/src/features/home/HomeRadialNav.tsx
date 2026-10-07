import { useEffect, useState, type CSSProperties } from 'react';
import { useNavigate } from 'react-router-dom';
import { formatMetricValue } from '../../components/widgets';
import { PRESET_GENTLE } from '../../lib/spring';
import { useSpringValue } from '../../lib/useSpringValue';
import { HOME_RADIAL_NAV } from '../nav/workbenchNav';
import type { HomeCoreMetricSlot } from './homeMetrics';

const BLURBS: Record<string, string> = {
  '/biz': '项目台账与经营指标，逐单查看报价与毛利。',
  '/todos': '今天要推进的事项，按优先级与截止时间排布。',
  '/finance': '收支概览与对账，按周期看现金流。',
  '/performance': '笔记与内容表现，定位高收藏与低表现。',
  '/hotspots': '热点雷达，捕捉可跟的选题信号。',
  '/knowledge': '知识大脑，沉淀可复用的方法与素材。',
  '/scan': '扫描报告，查看桌面与本地资料的扫描历史。',
  '/settings': '本地偏好、桥接与数据源设置。',
};

export default function HomeRadialNav({
  slots,
  todoTotal,
  todoStale,
}: {
  slots: HomeCoreMetricSlot[];
  todoTotal: number;
  todoStale: boolean;
}) {
  const navigate = useNavigate();
  const [entered, setEntered] = useState(0);
  const [hovered, setHovered] = useState(-1);
  const [selected, setSelected] = useState(-1);
  const entry = useSpringValue(entered, PRESET_GENTLE);
  const nodes = HOME_RADIAL_NAV;
  const angles = nodes.map((_, index) => -85 + (index * 170) / Math.max(1, nodes.length - 1));
  const focusIndex = selected >= 0 ? selected : hovered;
  const focusAngle = focusIndex >= 0 ? angles[focusIndex] : 0;
  const activeItem = selected >= 0 ? nodes[selected] : null;

  useEffect(() => {
    const id = window.requestAnimationFrame(() => setEntered(1));
    return () => window.cancelAnimationFrame(id);
  }, []);

  useEffect(() => {
    if (selected < 0) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setSelected(-1);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [selected]);

  return (
    <section
      className="home-radial"
      aria-label="模块入口地图"
      style={{ '--pop': entry } as CSSProperties}
    >
      <div
        className={`radial-arm${focusIndex >= 0 ? ' is-pointing' : ''}`}
        aria-hidden="true"
        style={{ '--focus-angle': `${focusAngle}deg` } as CSSProperties}
      />

      <div className="radial-core">
        <div className="ui-page-kicker">H-01 · TODAY</div>
        <h2 className="radial-core-title">今日状态</h2>
        <div className="radial-core-metrics">
          {slots.map((slot) => (
            <div key={slot.key} className="radial-core-metric" data-metric-key={slot.key}>
              <span className="radial-core-metric-label">{slot.label}</span>
              <span className="radial-core-metric-value">
                {slot.missing || !slot.metric ? '—' : formatMetricValue(slot.metric)}
              </span>
            </div>
          ))}
        </div>
        <div className="radial-core-foot">
          <span className="nb-badge">{todoTotal} 待办</span>
          {todoStale && <span className="nb-muted" style={{ fontSize: 12 }}>更新延迟</span>}
        </div>
      </div>

      <ul className="radial-nodes" role="list" onMouseLeave={() => setHovered(-1)}>
        {nodes.map((item, index) => (
          <li
            key={item.to}
            className={`radial-node${hovered === index ? ' is-hover' : ''}${selected === index ? ' is-active' : ''}`}
            style={{ '--d': index } as CSSProperties}
          >
            <button
              type="button"
              className="radial-node-btn"
              onClick={() => setSelected((current) => (current === index ? -1 : index))}
              onMouseEnter={() => setHovered(index)}
              onFocus={() => setHovered(index)}
              aria-pressed={selected === index}
              aria-label={`${item.code} ${item.label}`}
            >
              <span className="radial-node-icon" aria-hidden="true">{item.icon}</span>
              <span className="radial-node-label">{item.label}</span>
              <span className="radial-node-code">{item.code}</span>
            </button>
          </li>
        ))}
      </ul>

      <div className={`radial-detail${activeItem ? ' is-open' : ''}`} role="dialog" aria-label="模块详情">
        {activeItem && (
          <>
            <div className="radial-detail-head">
              <span className="ui-code">{activeItem.code}</span>
              <strong>{activeItem.label}</strong>
            </div>
            <p className="radial-detail-blurb">{BLURBS[activeItem.to] ?? ''}</p>
            <div className="radial-detail-actions">
              <button type="button" className="nb-btn nb-btn--primary" onClick={() => navigate(activeItem.to)}>
                进入
              </button>
              <button type="button" className="nb-btn nb-btn--ghost" onClick={() => setSelected(-1)}>
                关闭
              </button>
            </div>
          </>
        )}
      </div>
    </section>
  );
}

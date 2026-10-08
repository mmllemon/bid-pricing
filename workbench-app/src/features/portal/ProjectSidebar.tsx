import type { PortalItem } from './portalData';

interface ProjectSidebarProps {
  /** 当前项目 */
  current: PortalItem;
  /** 同模块项目列表（含当前） */
  projects: PortalItem[];
  /** 切换项目 */
  onSelect: (id: string) => void;
  /** 收起回抽屉 */
  onCollapse: () => void;
}

/**
 * 展开态左侧项目导航（2026-10-08）：
 * 当前项目（点收起）+ 同模块其他项目（点切换）+ 分节锚点。
 */
export function ProjectSidebar({ current, projects, onSelect, onCollapse }: ProjectSidebarProps) {
  const others = projects.filter((p) => p.id !== current.id);

  const scrollTo = (id: string) => {
    document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  };

  return (
    <nav className="project-sidebar" aria-label="项目导航">
      {/* 当前项目：点收起 */}
      <button type="button" className="ps-current" onClick={onCollapse} title="收起回抽屉">
        <span className="ps-code" data-font="data">{current.code || 'P'}</span>
        <span className="ps-name">{current.title}</span>
        {current.stage && <span className="ps-stage">{current.stage}</span>}
      </button>

      {/* 同模块其他项目 */}
      {others.length > 0 && (
        <div className="ps-section">
          <div className="ps-heading">其他项目</div>
          {others.map((p) => (
            <button
              key={p.id}
              type="button"
              className="ps-item"
              onClick={() => onSelect(p.id)}
              title={p.title}
            >
              <span className="ps-code" data-font="data">{p.code || 'P'}</span>
              <span className="ps-name">{p.title}</span>
            </button>
          ))}
        </div>
      )}

      {/* 分节锚点 */}
      <div className="ps-section">
        <div className="ps-heading">本页</div>
        <button type="button" className="ps-anchor" onClick={() => scrollTo('ec-summary')}>
          摘要指标
        </button>
        <button type="button" className="ps-anchor" onClick={() => scrollTo('ec-units')}>
          关联单位
        </button>
      </div>
    </nav>
  );
}

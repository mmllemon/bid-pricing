import { NavLink, useLocation } from 'react-router-dom';
import { SITE_DOMAINS, DOMAIN_ICONS, type SiteDomain } from '../features/nav/siteNav';

/**
 * 全站顶栏：品牌 + 域级导航 + 工作台域下的二级页条。
 *
 * 形态对齐参考项目（neural-creator-dashboard）：无侧栏，主导航在顶栏。
 * 迁移期：未迁入 React 的域（大盘/报价/工具）暂时以 <a href> 外链回母项目；
 * 迁入后把 SITE_DOMAINS 里该域的 href 换成 to，本组件自动改走 <NavLink>。
 */
export default function SiteTopBar() {
  const location = useLocation();

  const isDomainActive = (d: SiteDomain): boolean => {
    if (d.id === 'workbench') return !location.pathname.startsWith('/portal')
      && !location.pathname.startsWith('/quote')
      && !location.pathname.startsWith('/tools');
    const p = d.to || '';
    return Boolean(p) && (location.pathname === p || location.pathname.startsWith(p + '/'));
  };

  const activeDomain = SITE_DOMAINS.find(isDomainActive);

  return (
    <header className="site-topbar">
      <div className="site-topbar-main">
        <div className="site-brand">
          <span className="site-brand-mark" aria-hidden="true">◈</span>
          <span className="site-brand-text">
            <strong>工程智算</strong>
            <small>工程项目智能决策平台</small>
          </span>
        </div>

        <nav className="site-nav" aria-label="主导航">
          {SITE_DOMAINS.map((d) =>
            d.to ? (
              <NavLink
                key={d.id}
                to={d.to}
                end={d.to === '/'}
                className={({ isActive }) => `site-nav-btn${isActive ? ' site-nav-btn--active' : ''}`}
              >
                <span className="site-nav-icon" aria-hidden="true">{DOMAIN_ICONS[d.id]}</span>
                <span className="site-nav-label">{d.label}</span>
                <span className="site-nav-code">{d.code}</span>
              </NavLink>
            ) : (
              <a
                key={d.id}
                href={d.href}
                className={`site-nav-btn${isDomainActive(d) ? ' site-nav-btn--active' : ''}`}
              >
                <span className="site-nav-icon" aria-hidden="true">{DOMAIN_ICONS[d.id]}</span>
                <span className="site-nav-label">{d.label}</span>
                <span className="site-nav-code">{d.code}</span>
              </a>
            )
          )}
        </nav>

        <div className="site-topbar-actions">
          <span className="site-runtime-badge">SYSTEM OK</span>
        </div>
      </div>

      {/* 二级页条：仅当当前域有 children（工作台）时显示 */}
      {activeDomain?.children?.length ? (
        <nav className="site-subnav" aria-label="工作台页面">
          {activeDomain.children.map((it) => (
            <NavLink
              key={it.to}
              to={it.to}
              end={it.to === '/'}
              className={({ isActive }) => `site-subnav-btn${isActive ? ' site-subnav-btn--active' : ''}`}
            >
              <span aria-hidden="true">{it.icon}</span>
              <span>{it.label}</span>
              <span className="site-subnav-code">{it.code}</span>
            </NavLink>
          ))}
        </nav>
      ) : null}
    </header>
  );
}

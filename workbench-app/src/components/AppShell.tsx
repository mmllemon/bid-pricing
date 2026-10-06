import { useEffect, useRef } from 'react';
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom';
import type { ReactNode } from 'react';
import { IconHome, IconTodo, IconChart, IconScan, IconSettings, IconHotspot, IconBrain, IconBriefcase } from './icons';
import AvatarMascot from './AvatarMascot';
import { Wallet } from 'pixelarticons/react';

/* 独立访问（未内嵌）时的自带侧栏清单。
 *
 * ⚠ 非事实源，仅独立访问使用：内嵌进母项目时下面整块不渲染，导航由母项目外层侧栏
 *   （frontend/js/sidebar.js 消费 frontend/js/workbench-nav.js）提供，全站只有一条竖栏。
 *   因此这里的文案/图标允许与外层漂移；路径集合由 tests/test_workbench_nav.py 守卫。
 *   保留它的唯一目的：直接打开 http://127.0.0.1:3456/#/todos 时仍可导航。 */
const navItems = [
  { to: '/', label: '今日', code: 'H-01', icon: <IconHome /> },
  { to: '/biz', label: '项目经营', code: 'M-01', icon: <IconBriefcase /> },
  { to: '/todos', label: '待办', code: 'T-02', icon: <IconTodo /> },
  { to: '/finance', label: '财务分析', code: 'F-08', icon: <Wallet width={24} height={24} /> },
  { to: '/performance', label: '内容表现', code: 'C-03', icon: <IconChart /> },
  { to: '/hotspots', label: '热点雷达', code: 'R-04', icon: <IconHotspot /> },
  { to: '/knowledge', label: '知识大脑', code: 'K-05', icon: <IconBrain /> },
  { to: '/scan', label: '扫描报告', code: 'S-06', icon: <IconScan /> },
  { to: '/settings', label: '设置', code: 'S-07', icon: <IconSettings /> },
];

// 入站导航消息的白名单：只接受本应用真实存在的路由（挡掉被构造出来的任意跳转）。
const NAV_TOS = new Set(navItems.map((it) => it.to));

/* 内嵌判定与父窗口 origin。
 * iframe 跨源（父 :8080 / 子 :3456），子页读不到父文档，只能用 document.referrer 反推。
 * postMessage 的 targetOrigin 必须是具体 origin，禁用 '*'（见 docs/V3_INTEGRATION_PLAN.md §9.3-2）。 */
const EMBEDDED = typeof window !== 'undefined' && window.self !== window.top;
const PARENT_ORIGIN = (() => {
  if (!EMBEDDED) return '';
  try {
    return document.referrer ? new URL(document.referrer).origin : '';
  } catch {
    return '';
  }
})();

interface NavItemProps {
  to: string;
  label: string;
  code: string;
  icon: ReactNode;
}

function NavItem({ to, label, code, icon }: NavItemProps) {
  return (
    <NavLink
      to={to}
      end={to === '/'}
      className={({ isActive }) => `nav-item${isActive ? ' nav-item--active' : ''}`}
    >
      <span aria-hidden="true">{icon}</span>
      <span>{label}</span>
      <span className="nav-item-code">{code}</span>
    </NavLink>
  );
}

type WbMessage = { __wb?: string; to?: string };

export default function AppShell() {
  const location = useLocation();
  const navigate = useNavigate();
  // 当前路由的快照：消息回调里用它比较，避免把 navigate 塞进依赖后反复解绑/重绑监听
  const pathRef = useRef(location.pathname);
  pathRef.current = location.pathname;

  // 握手 + 接收父侧导航：监听必须在发 ready 之前挂好，否则父侧随后发来的 nav 会丢
  useEffect(() => {
    if (!EMBEDDED || !PARENT_ORIGIN) return;
    const onMessage = (event: MessageEvent) => {
      if (event.source !== window.parent) return;            // 只认父窗口
      const msg = event.data as WbMessage | null;
      if (!msg || msg.__wb !== 'nav' || typeof msg.to !== 'string') return;
      if (!NAV_TOS.has(msg.to)) return;                      // to 必须在真实路由白名单内
      if (msg.to !== pathRef.current) navigate(msg.to);
    };
    window.addEventListener('message', onMessage);
    window.parent.postMessage({ __wb: 'ready' }, PARENT_ORIGIN);
    return () => window.removeEventListener('message', onMessage);
  }, [navigate]);

  // 路由上报（反向通道）：外层据此跟随高亮。
  // 跳过首次渲染——否则会把初始的 '/' 报给父侧，抢跑掉父侧深链（#workbench/todos）的意图；
  // 跳过只影响首帧，之后每次真实换页都会上报。
  const skippedFirst = useRef(false);
  useEffect(() => {
    if (!EMBEDDED || !PARENT_ORIGIN) return;
    if (!skippedFirst.current) {
      skippedFirst.current = true;
      return;
    }
    window.parent.postMessage({ __wb: 'route', to: location.pathname }, PARENT_ORIGIN);
  }, [location.pathname]);

  // 内嵌时不渲染自带侧栏：母项目外层已有一条全高竖栏，否则又变成「两个导航栏」
  if (EMBEDDED) {
    return (
      <div className="shell">
        <main className="main">
          <Outlet />
        </main>
      </div>
    );
  }

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="sidebar-brand">
          <div className="sidebar-logo">
            <AvatarMascot />
          </div>
          <div>
            <div className="sidebar-title">L叔的工作台</div>
            <div className="sidebar-sub">LOCAL COMMAND</div>
          </div>
        </div>
        <nav className="sidebar-nav" aria-label="主导航">
          {navItems.map((it) => (
            <NavItem key={it.to} {...it} />
          ))}
        </nav>
        <div className="sidebar-foot" aria-live="polite">
          <div className="sidebar-foot-badge">SYSTEM OK</div>
          <div className="sidebar-foot-text">本地运行 · 数据仅存本机</div>
        </div>
      </aside>
      <main className="main">
        <Outlet />
      </main>
    </div>
  );
}

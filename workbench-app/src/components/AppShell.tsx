import { useEffect, useRef, useState } from 'react';
import { Outlet, useLocation, useNavigate } from 'react-router-dom';
import { WORKBENCH_NAV as navItems } from '../features/nav/workbenchNav';
import SiteTopBar from './SiteTopBar';
import AgentPanel from '../features/agent/AgentPanel';

/* 导航形态（P0-3 前端整合）：全站主导航改到顶栏（SiteTopBar），不再渲染自带侧栏。
 * 迁移期：内嵌/独立访问都渲染同一套顶栏；未迁入 React 的域以 <a href> 外链回母项目。
 * 工作台 9 页清单唯一事实源为 features/nav/workbenchNav.tsx，路径集合由
 * tests/test_workbench_nav.py 静态守卫。 */

// 入站导航消息的白名单：只接受本应用真实存在的路由（挡掉被构造出来的任意跳转）。
const NAV_TOS = new Set(navItems.map((it) => it.to));

/* 内嵌判定与父窗口 origin。
 * iframe 跨源（父 :8000 / 子 :3456），子页读不到父文档，只能用 document.referrer 反推。
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

type WbMessage = { __wb?: string; to?: string };

export default function AppShell() {
  const location = useLocation();
  const navigate = useNavigate();
  // 当前路由的快照：消息回调里用它比较，避免把 navigate 塞进依赖后反复解绑/重绑监听
  const pathRef = useRef(location.pathname);
  pathRef.current = location.pathname;

  // P2: 握手静默失败提示 —— 内嵌后 8s 没收到父页任何 __wb 消息，挂非阻塞横幅
  const [handshakeFailed, setHandshakeFailed] = useState(false);
  const gotParentMsg = useRef(false);
  // 握手 + 接收父侧导航：监听必须在发 ready 之前挂好，否则父侧随后发来的 nav 会丢
  useEffect(() => {
    if (!EMBEDDED || !PARENT_ORIGIN) return;
    const onMessage = (event: MessageEvent) => {
      if (event.source !== window.parent) return;            // 只认父窗口
      const msg = event.data as WbMessage | null;
      if (!msg || typeof msg.__wb !== 'string') return;
      gotParentMsg.current = true;                           // 收到父页消息即握手成功
      setHandshakeFailed(false);
      if (msg.__wb !== 'nav' || typeof msg.to !== 'string') return;
      if (!NAV_TOS.has(msg.to)) return;                      // to 必须在真实路由白名单内
      if (msg.to !== pathRef.current) navigate(msg.to);
    };
    window.addEventListener('message', onMessage);
    window.parent.postMessage({ __wb: 'ready' }, PARENT_ORIGIN);
    const timer = setTimeout(() => {
      if (!gotParentMsg.current) setHandshakeFailed(true);
    }, 8000);
    return () => {
      window.removeEventListener('message', onMessage);
      clearTimeout(timer);
    };
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

  // 内嵌时不再渲染自带侧栏（母项目外层已有一条全高竖栏），但仍渲染全站顶栏导航：
  // 前端整合后顶栏是唯一的主导航，侧栏最终会退场。
  if (EMBEDDED) {
    return (
      <div className="shell shell--topnav">
        <SiteTopBar />
        {handshakeFailed && (
          <div className="ui-alert ui-alert--error" style={{ margin: '12px 12px 0' }}>
            <p style={{ fontSize: 13, lineHeight: 1.7 }}>
              未收到父页面握手响应，导航联动可能不可用。请检查父页是否正常加载，或刷新父页面重试。
            </p>
            <button
              className="nb-btn nb-btn--ghost"
              style={{ fontSize: 12, padding: '4px 10px', marginTop: 8 }}
              onClick={() => setHandshakeFailed(false)}
            >
              知道了
            </button>
          </div>
        )}
        <main className="main">
          <Outlet />
        </main>
        <AgentPanel />
      </div>
    );
  }

  return (
    <div className="shell shell--topnav">
      <SiteTopBar />
      <main className="main">
        <Outlet />
      </main>
      <AgentPanel />
    </div>
  );
}

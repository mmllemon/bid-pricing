/* ===== 工作台二级导航：唯一事实源 =====
 * React 工作台（workbench-app）的 9 个页面，只在下面的 WB_NAV 数组里维护一份。
 * 外层侧栏（sidebar.js）在「个人工作台」下把它渲染成二级折叠项；
 * React 侧内嵌（iframe）时不再渲染自带侧栏，因此不存在第二份清单。
 *
 * 两个事实源的分工（见 docs/V3_INTEGRATION_PLAN.md §9.3-1）：
 *   - 本文件：9 页的 label / code / icon / to（文案与图标）
 *   - workbench-app/src/App.tsx 的 <Route>：9 页的「路由是否存在」
 * 二者的 to 集合必须相等，由 tests/test_workbench_nav.py 静态守卫。
 *
 * 独立访问 http://127.0.0.1:3456/#/xxx 时 AppShell 会渲染自带侧栏作为开发兜底，
 * 那份清单「非事实源，仅独立访问使用」，文案/图标允许漂移（路径由守卫测试兜住）。
 */
(function () {
  'use strict';

  // 图标沿用外层侧栏风格：24×24、单色线性、stroke 1.7、圆头（与 sidebar.js 的 ICONS 一致）。
  var ICONS = {
    home: '<path d="M4 12l8-8 8 8"/><path d="M6 11v9h12v-9"/><path d="M10 20v-5h4v5"/>',
    briefcase: '<rect x="3" y="8" width="18" height="12" rx="1.5"/><path d="M9 8V5h6v3"/><path d="M3 13h18"/><rect x="10" y="13" width="4" height="3" rx="0.5"/>',
    todo: '<rect x="4" y="4" width="16" height="16" rx="2"/><path d="M8 12l3 3 5-6"/>',
    wallet: '<rect x="3" y="6" width="18" height="13" rx="2"/><path d="M3 10h18"/><circle cx="16.5" cy="14.5" r="1.2"/>',
    chart: '<path d="M4 20V6"/><path d="M4 20h16"/><path d="M8 16v-4"/><path d="M12 16V8"/><path d="M16 16v-6"/>',
    hotspot: '<path d="M12 4l4 8H8z"/><path d="M8 14h8v6H8z"/>',
    brain: '<rect x="7" y="5" width="10" height="14" rx="1.5"/><path d="M7 9H4v6h3"/><path d="M17 9h3v6h-3"/><path d="M10 9h4M10 13h4"/>',
    scan: '<path d="M4 8V4h4"/><path d="M16 4h4v4"/><path d="M20 16v4h-4"/><path d="M8 20H4v-4"/><rect x="9" y="9" width="6" height="6"/>',
    settings: '<rect x="9" y="9" width="6" height="6" rx="1"/><path d="M12 3v4M12 17v4M3 12h4M17 12h4M5 5l3 3M16 16l3 3M19 5l-3 3M8 16l-3 3"/>',
  };

  // to 使用 React Router 的路由路径；父页 hash 由 to 推导：'/' → #workbench，其余 → #workbench/<to 去前导斜杠>。
  var WB_NAV = [
    { to: '/', label: '今日', code: 'H-01', icon: 'home' },
    { to: '/biz', label: '项目经营', code: 'M-01', icon: 'briefcase' },
    { to: '/todos', label: '待办', code: 'T-02', icon: 'todo' },
    { to: '/finance', label: '财务分析', code: 'F-08', icon: 'wallet' },
    { to: '/performance', label: '内容表现', code: 'C-03', icon: 'chart' },
    { to: '/hotspots', label: '热点雷达', code: 'R-04', icon: 'hotspot' },
    { to: '/knowledge', label: '知识大脑', code: 'K-05', icon: 'brain' },
    { to: '/scan', label: '扫描报告', code: 'S-06', icon: 'scan' },
    { to: '/settings', label: '设置', code: 'S-07', icon: 'settings' },
  ];

  window.WB_NAV = WB_NAV;
  window.WB_NAV_ICONS = ICONS;
})();

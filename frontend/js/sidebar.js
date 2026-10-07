/* ===== 侧栏：全站唯一事实源 =====
 * 导航项只在下面的 NAV_GROUPS 数组里维护一份，index.html 与 5 个工具页共用同一套渲染。
 * 此前 index.html 静态侧栏与本文件各存一份，已多次出现漏改（如工具页缺「AI 测算助手」）。
 *
 * 渲染模式按「是否 index 页」分叉：
 *   - index 页：module 项渲染为 <button data-module>，由 app.js 做同页视图切换；
 *   - 工具页：module 项渲染为 <a href="./index.html#mod">，跨页跳转。
 * action 项（data-agent-open，点击唤起全局悬浮面板 agent-panel.js）：预留的通用
 * 渲染分支，目前 NAV_GROUPS 里暂无 action 项（AI 助手入口已收敛为悬浮 FAB）。
 *
 * P-W8 起「个人工作台」不再是一级单项：它折叠为「父行 + 9 个二级项」，使全站只有一条竖栏。
 * 那 9 项的 label/code/icon/to 只在 js/workbench-nav.js 里维护（唯一事实源，与
 * workbench-app/src/App.tsx 的路由集合由 tests/test_workbench_nav.py 守卫）。
 */
(function () {
  'use strict';

  var slot = document.getElementById('sidebarSlot');
  if (!slot) return;

  // index 页独有的视图容器：用它判断当前页是否 index，比字符串比 pathname 更稳（大小写/重定向都不影响）。
  var isIndex = !!document.getElementById('quoteView');
  var here = (location.pathname.split('/').pop() || 'index.html');
  var hash = (location.hash || '').replace(/^#/, '');
  // index 的初始激活项与 app.js initDashboard 的兜底（无 hash → portal）保持一致。
  var currentModule = isIndex ? (hash || 'portal') : '';

  var ICONS = {
    brand: '<path d="M3 3v18h18"/><path d="M7 14l4-4 4 4 5-6"/>',
    portal: '<circle cx="12" cy="12" r="3"/><circle cx="5" cy="12" r="1.5"/><circle cx="19" cy="12" r="1.5"/><circle cx="12" cy="5" r="1.5"/><circle cx="12" cy="19" r="1.5"/><path d="M5 12h4m6 0h4M12 5v4m0 6v4"/>',
    workbench: '<rect x="3" y="3" width="7" height="9" rx="1.5"/><rect x="14" y="3" width="7" height="5" rx="1.5"/><rect x="14" y="12" width="7" height="9" rx="1.5"/><rect x="3" y="16" width="7" height="5" rx="1.5"/>',
    quote: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 9h18M8 14h5M8 17h8"/>',
    cost: '<path d="M12 2v20M5 9l7-7 7 7M5 15l7 7 7-7"/>',
    agent: '<rect x="4" y="7" width="16" height="12" rx="2.5"/><path d="M12 7V4M8 4h8"/><circle cx="9" cy="12" r="1.2" fill="currentColor" stroke="none"/><circle cx="15" cy="12" r="1.2" fill="currentColor" stroke="none"/><path d="M9 16h6"/>',
    ledger: '<path d="M4 4h12l4 4v12H4z"/><path d="M8 9h6M8 13h8M8 17h5"/>',
    settlement: '<path d="M9 11l3 3L22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/>',
    tools: '<rect x="5" y="3" width="14" height="18" rx="2"/><path d="M9 7h6M9 11h.01M12 11h.01M15 11h.01M9 14h.01M12 14h.01M15 14h.01M9 17h6"/>',
  };

  var NAV_GROUPS = [
    {
      title: '数字枢纽',
      items: [
        { module: 'portal', num: 'P-00', label: '全景大盘', icon: 'portal' },
      ],
    },
    {
      title: '工作台',
      items: [
        { module: 'workbench', num: 'W-00', label: '个人工作台', icon: 'workbench' },
      ],
    },
    {
      title: '核心功能',
      items: [
        { module: 'quote', num: 'Q-01', label: '投标报价', icon: 'quote' },
        // soon: 模块只有占位页（无真实数据与操作），导航里灰显并标「建设中」，避免承诺不存在的能力。
        { module: 'cost', num: 'C-02', label: '实施成本', icon: 'cost', soon: true },
        // 2026-10-07 去掉：AI 助手已有全局悬浮 FAB（agent-panel.js），侧栏再摆一个入口纯冗余。
      ],
    },
    {
      title: '项目管理',
      items: [
        { module: 'ledger', num: 'L-04', label: '项目台账', icon: 'ledger', soon: true },
        { module: 'settlement', num: 'S-05', label: '结算管理', icon: 'settlement', soon: true },
      ],
    },
    {
      title: '工具箱',
      items: [
        { href: './tools.html', num: 'T-06', label: '速算工具箱', icon: 'tools', match: /^(tools|tool-.*)\.html$/ },
      ],
    },
  ];

  // ---- 工作台二级导航（清单来自 js/workbench-nav.js：唯一事实源，本文件不复制一份） ----
  var WB_NAV = window.WB_NAV || [];
  var WB_ICONS = window.WB_NAV_ICONS || {};

  // 当前激活的二级路由：'/' 或 '/todos'；非工作台页为空串。
  var wbSub = '';
  if (isIndex && (hash === 'workbench' || hash.indexOf('workbench/') === 0)) {
    wbSub = hash.length > 'workbench/'.length ? '/' + hash.slice('workbench/'.length) : '/';
  }

  // 展开态：宽屏默认展开；≤768px（侧栏本身是抽屉）默认收起，避免二级把首屏撑满。
  // 但停在某个非根二级页时必须展开，否则用户看不到自己在哪。
  var WB_OPEN_KEY = 'bidpricing.wb_nav_open';   // P2: 键命名统一（旧 gc_wb_nav_open 一次性迁移）
  var wbOpen = window.innerWidth > 768;
  if (window.localStorage) {
    var wbStored = localStorage.getItem(WB_OPEN_KEY);
    if (wbStored === null) {   // 一次性迁移旧键
      var wbLegacy = localStorage.getItem('gc_wb_nav_open');
      if (wbLegacy !== null) {
        wbStored = wbLegacy;
        localStorage.setItem(WB_OPEN_KEY, wbLegacy);
        localStorage.removeItem('gc_wb_nav_open');
      }
    }
    if (wbStored === '1') wbOpen = true;
    else if (wbStored === '0') wbOpen = false;
  }
  if (wbSub && wbSub !== '/') wbOpen = true;

  function wbHref(to) {
    var frag = 'workbench' + (to && to !== '/' ? to : '');
    return isIndex ? ('#' + frag) : ('./index.html#' + frag);
  }

  function wbSubHTML(item) {
    var cls = 'nav-item nav-sub' + (wbSub === item.to ? ' active' : '');
    return '<a class="' + cls + '" href="' + wbHref(item.to) + '" data-wb-to="' + item.to + '">' +
      '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">' +
      (WB_ICONS[item.icon] || '') + '</svg>' +
      '<span>' + item.label + '</span><span class="nav-num">' + item.code + '</span></a>';
  }

  // 父行只负责展开/收起（跳转由二级项完成）：一个控件不承担两个动作，避免「想展开却跳走」。
  function wbGroupHTML(item) {
    var cls = 'nav-item nav-parent' + (wbSub ? ' has-active' : '') + (wbOpen ? '' : ' is-collapsed');
    return '<button class="' + cls + '" type="button" id="wbNavParent" aria-expanded="' + (wbOpen ? 'true' : 'false') + '" aria-controls="wbNavSub">' +
      '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">' + ICONS[item.icon] + '</svg>' +
      '<span>' + item.label + '</span><span class="nav-num">' + item.num + '</span>' +
      '<svg class="nav-chev" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M6 9l6 6 6-6"/></svg>' +
      '</button>' +
      '<div class="nav-sublist' + (wbOpen ? '' : ' is-collapsed') + '" id="wbNavSub">' + WB_NAV.map(wbSubHTML).join('') + '</div>';
  }

  function isActive(item) {
    if (item.match) return item.match.test(here);          // 跨页项：按当前文件名判定
    if (!isIndex) return false;                            // 工具页上 module 项一律不激活
    return item.module === currentModule;
  }

  function itemHTML(item) {
    if (item.module === 'workbench') return wbGroupHTML(item);   // 折叠为「父行 + 9 个二级项」
    var cls = 'nav-item' + (isActive(item) ? ' active' : '') + (item.soon ? ' nav-soon' : '');
    var inner =
      '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">' +
      ICONS[item.icon] + '</svg>' +
      '<span>' + item.label + '</span>' +
      // 未上线项把索引位让给「建设中」标记：同一槽位，不改变行高与对齐
      (item.soon ? '<span class="nav-num nav-soon-tag">建设中</span>' : '<span class="nav-num">' + item.num + '</span>');
    if (item.action) return '<button class="' + cls + '" type="button" data-agent-open>' + inner + '</button>';
    if (item.href) return '<a class="' + cls + '" href="' + item.href + '">' + inner + '</a>';
    if (isIndex) return '<button class="' + cls + '" type="button" data-module="' + item.module + '">' + inner + '</button>';
    // 必须带 #hash：index.html 对「无 hash」判的是个人工作台，裸链会先落到工作台再让人二次点击。
    return '<a class="' + cls + '" href="./index.html#' + item.module + '">' + inner + '</a>';
  }

  var navHTML = NAV_GROUPS.map(function (g) {
    return '<div class="nav-group"><div class="nav-group-title">' + g.title + '</div>' +
      g.items.map(itemHTML).join('') + '</div>';
  }).join('');

  slot.outerHTML =
    '<button class="sb-toggle" id="sbToggle" aria-label="打开导航菜单" aria-expanded="false">' +
      '<svg class="ic-burger" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round"><path d="M4 7h16M4 12h16M4 17h16"/></svg>' +
      '<svg class="ic-close" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round"><path d="M6 6l12 12M18 6L6 18"/></svg>' +
    '</button>' +
    '<div class="sb-backdrop" id="sbBackdrop"></div>' +
    '<aside class="sidebar">' +
      '<div class="brand">' +
        '<div class="brand-mark">' +
          '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">' + ICONS.brand + '</svg>' +
        '</div>' +
        '<div class="brand-text"><strong>工程智算</strong><small>工程项目智能决策平台</small></div>' +
      '</div>' +
      '<nav class="nav-scroll" aria-label="功能模块">' + navHTML + '</nav>' +
      '<div class="sidebar-foot">' +
        '<div class="user-block">' +
          '<div class="avatar" id="userAvatar">U</div>' +
          '<div class="user-meta">' +
            '<span class="user-name" id="userName">本机用户</span>' +
            '<span class="user-scope">本地工作台</span>' +
          '</div>' +
        '</div>' +
        '<div class="version-line">v0.1 · 单机版</div>' +
      '</div>' +
    '</aside>';
})();

/* ===== 侧栏交互：窄屏抽屉 + 用户名编辑 =====
 * 完全独立——只碰侧栏 DOM + localStorage。
 */

/* 侧栏收起：窄屏抽屉式（汉堡按钮 + 遮罩），点导航项/遮罩/Esc 均关闭 */
(function () {
  const shell = document.querySelector('.app-shell');
  const toggle = document.getElementById('sbToggle');
  const backdrop = document.getElementById('sbBackdrop');
  if (!shell || !toggle || !backdrop) return;
  const set = (open) => {
    shell.classList.toggle('sb-open', open);
    toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
    toggle.setAttribute('aria-label', open ? '关闭导航菜单' : '打开导航菜单');
  };
  toggle.addEventListener('click', () => set(!shell.classList.contains('sb-open')));
  backdrop.addEventListener('click', () => set(false));
  // 排除折叠父行：它是展开/收起开关，窄屏下点它不应顺手把抽屉关掉
  document.querySelectorAll('.nav-item:not(.nav-parent)').forEach(n => n.addEventListener('click', () => set(false)));
  window.addEventListener('keydown', e => { if (e.key === 'Escape') set(false); });
})();

/* 工作台二级折叠：展开态持久化到 localStorage（键 bidpricing.wb_nav_open，'1' 展开 / '0' 收起） */
(function () {
  const parent = document.getElementById('wbNavParent');
  const list = document.getElementById('wbNavSub');
  if (!parent || !list) return;
  const setOpen = (open, persist) => {
    parent.setAttribute('aria-expanded', open ? 'true' : 'false');
    parent.classList.toggle('is-collapsed', !open);
    list.classList.toggle('is-collapsed', !open);
    if (persist && window.localStorage) localStorage.setItem(WB_OPEN_KEY, open ? '1' : '0');
  };
  parent.addEventListener('click', () => setOpen(parent.getAttribute('aria-expanded') !== 'true', true));
})();

/* 侧栏用户名可自定义：点击后内联编辑，回车/失焦保存（localStorage 持久化，工作台问候同步读取） */
(function () {
  const NAME_KEY = 'bidpricing.user_name';   // P2: 键命名统一（旧 gc_user_name 一次性迁移）
  const el = document.getElementById('userName');
  if (!el || !window.localStorage) return;
  let saved = localStorage.getItem(NAME_KEY);
  if (saved === null) {   // 一次性迁移旧键
    const legacyName = localStorage.getItem('gc_user_name');
    if (legacyName !== null) {
      saved = legacyName;
      localStorage.setItem(NAME_KEY, legacyName);
      localStorage.removeItem('gc_user_name');
    }
  }
  if (saved) el.textContent = saved;
  el.title = '点击修改用户名';
  el.style.cursor = 'text';
  el.onclick = () => {
    const input = document.createElement('input');
    input.type = 'text'; input.maxLength = 20;
    input.value = el.textContent;
    input.className = 'name-input';
    input.style.cssText = 'width:100%;max-width:150px;padding:2px 6px;border:1px solid var(--border-input);border-radius:0;font-size:13px;font-weight:600;color:var(--text);background:var(--surface-card);font-family:var(--font)';
    input.addEventListener('focus', () => input.select());
    const original = el.textContent;   // 取消时恢复，而不是把显示名清成「未命名」
    const commit = () => {
      const v = input.value.trim();
      if (v) localStorage.setItem(NAME_KEY, v);
      el.textContent = v || '未命名';
      input.replaceWith(el);
    };
    const onKey = e => {
      if (e.key === 'Enter') commit();
      else if (e.key === 'Escape') { el.textContent = original; input.replaceWith(el); }
    };
    input.addEventListener('blur', commit);
    input.addEventListener('keydown', onKey);
    el.replaceWith(input);
    input.focus();
  };
})();

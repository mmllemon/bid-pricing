/* ===== 侧栏结构：4 个工具页共用，JS 统一渲染（改一处即全站生效） ===== */
(function () {
  var slot = document.getElementById('sidebarSlot');
  if (!slot) return;   // 非工具页（如 index.html）保持静态侧栏不动
  slot.outerHTML = `
    <button class="sb-toggle" id="sbToggle" aria-label="打开导航菜单" aria-expanded="false">
      <svg class="ic-burger" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round"><path d="M4 7h16M4 12h16M4 17h16"/></svg>
      <svg class="ic-close" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round"><path d="M6 6l12 12M18 6L6 18"/></svg>
    </button>
    <div class="sb-backdrop" id="sbBackdrop"></div>

    <!-- ===== 侧边栏（结构与 index.html 同构；跨页用 <a>） ===== -->
    <aside class="sidebar">
      <div class="brand">
        <div class="brand-mark">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 3v18h18"/><path d="M7 14l4-4 4 4 5-6"/></svg>
        </div>
        <div class="brand-text">
          <strong>工程智算</strong>
          <small>工程项目智能决策平台</small>
        </div>
      </div>

      <nav class="nav-scroll" aria-label="功能模块">
        <div class="nav-group">
          <div class="nav-group-title">工作台</div>
          <a class="nav-item" href="./index.html#workbench">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="7" height="9" rx="1.5"/><rect x="14" y="3" width="7" height="5" rx="1.5"/><rect x="14" y="12" width="7" height="9" rx="1.5"/><rect x="3" y="16" width="7" height="5" rx="1.5"/></svg>
            <span>个人工作台</span><span class="nav-num">W-00</span>
          </a>
        </div>

        <div class="nav-group">
          <div class="nav-group-title">核心功能</div>
          <a class="nav-item" href="./index.html">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 9h18M8 14h5M8 17h8"/></svg>
            <span>投标报价</span><span class="nav-num">Q-01</span>
          </a>
          <a class="nav-item" href="./index.html#cost">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2v20M5 9l7-7 7 7M5 15l7 7 7-7"/></svg>
            <span>实施成本</span><span class="nav-num">C-02</span>
          </a>
        </div>

        <div class="nav-group">
          <div class="nav-group-title">项目管理</div>
          <a class="nav-item" href="./index.html#ledger">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M4 4h12l4 4v12H4z"/><path d="M8 9h6M8 13h8M8 17h5"/></svg>
            <span>项目台账</span><span class="nav-num">L-04</span>
          </a>
          <a class="nav-item" href="./index.html#settlement">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M9 11l3 3L22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/></svg>
            <span>结算管理</span><span class="nav-num">S-05</span>
          </a>
        </div>

        <div class="nav-group">
          <div class="nav-group-title">工具箱</div>
          <a class="nav-item active" href="./tools.html">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><rect x="5" y="3" width="14" height="18" rx="2"/><path d="M9 7h6M9 11h.01M12 11h.01M15 11h.01M9 14h.01M12 14h.01M15 14h.01M9 17h6"/></svg>
            <span>速算工具箱</span><span class="nav-num">T-06</span>
          </a>
        </div>
      </nav>

      <div class="sidebar-foot">
        <div class="user-block">
          <div class="avatar" id="userAvatar">U</div>
          <div class="user-meta">
            <span class="user-name" id="userName">本机用户</span>
            <span class="user-scope">本地工作台</span>
          </div>
        </div>
        <div class="version-line">v0.1 · 单机版</div>
      </div>
    </aside>`;
})();

/* ===== 侧栏交互：窄屏抽屉 + 用户名编辑 =====
 * 从 app.js 拆出，完全独立——只碰侧栏 DOM + localStorage。
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
  document.querySelectorAll('.nav-item').forEach(n => n.addEventListener('click', () => set(false)));
  window.addEventListener('keydown', e => { if (e.key === 'Escape') set(false); });
})();

/* 侧栏用户名可自定义：点击后内联编辑，回车/失焦保存（localStorage 持久化，工作台问候同步读取） */
(function () {
  const NAME_KEY = 'gc_user_name';
  const el = document.getElementById('userName');
  if (!el || !window.localStorage) return;
  const saved = localStorage.getItem(NAME_KEY);
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

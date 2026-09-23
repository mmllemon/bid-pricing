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
    input.style.cssText = 'width:100%;max-width:150px;padding:2px 6px;border:1px solid var(--border-input);border-radius:8px;font-size:13px;font-weight:600;color:var(--text);background:var(--surface-card);font-family:var(--font);outline:none';
    input.addEventListener('focus', () => input.select());
    const commit = () => {
      const v = input.value.trim();
      if (v) localStorage.setItem(NAME_KEY, v);
      el.textContent = v || '未命名';
      input.replaceWith(el);
    };
    const onKey = e => {
      if (e.key === 'Enter') commit();
      else if (e.key === 'Escape') { input.value = ''; commit(); }
    };
    input.addEventListener('blur', commit);
    input.addEventListener('keydown', onKey);
    el.replaceWith(input);
    input.focus();
  };
})();

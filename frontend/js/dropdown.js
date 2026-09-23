/* ===== 自定义下拉：毛玻璃选项面板 =====
 * 从 app.js 拆出。initCustomSelect 是全局函数声明，
 * 被 app.js 方案中心代码调用（通过 window 可见）。
 * 需在 app.js 之前加载。
 */

// ---- 自定义下拉：毛玻璃选项面板，替代原生 select ----
function initCustomSelect(selId) {
  const sel = document.querySelector(selId);
  if (!sel || sel.__cs) return sel;
  sel.classList.add('cs-hidden');                 // 隐藏原生 select，仍保留为 value 载体
  const wrap = document.createElement('div');
  wrap.className = 'cs';
  wrap.innerHTML =
    '<button type="button" class="cs-trigger" aria-haspopup="listbox">' +
    '<span class="cs-label"></span>' +
    '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M6 8l4 4 4-4"/></svg>' +
    '</button>' +
    '<ul class="cs-list hidden" role="listbox"></ul>';
  sel.parentNode.insertBefore(wrap, sel.nextSibling);
  const label = wrap.querySelector('.cs-label');
  const list = wrap.querySelector('.cs-list');
  const trigger = wrap.querySelector('.cs-trigger');
  let data = [];

  function populate() {
    list.innerHTML = '';
    data.forEach((o, i) => {
      const li = document.createElement('li');
      li.className = 'cs-opt' + (o.value === sel.value ? ' cs-selected' : '');
      li.setAttribute('role', 'option');
      li.setAttribute('aria-selected', String(o.value === sel.value));
      li.dataset.i = String(i);
      li.textContent = o.label;                    // textContent：防注入
      list.appendChild(li);
    });
  }
  function render() {
    const hit = data.find(o => o.value === sel.value);
    label.textContent = hit ? hit.label : (sel.value || '— 请选择 —');
  }
  function close() { list.classList.add('hidden'); wrap.classList.remove('open'); document.removeEventListener('click', onDoc); }
  function open() { populate(); render(); list.classList.remove('hidden'); wrap.classList.add('open'); setTimeout(() => document.addEventListener('click', onDoc), 0); }
  function onDoc(e) { if (!wrap.contains(e.target)) close(); }

  trigger.addEventListener('click', e => { e.stopPropagation(); wrap.classList.contains('open') ? close() : open(); });
  list.addEventListener('click', e => {
    const li = e.target.closest('.cs-opt');
    if (!li) return;
    const o = data[+li.dataset.i];
    if (o && o.value !== sel.value) {
      sel.value = o.value; render();
      sel.dispatchEvent(new Event('change', { bubbles: true }));
    }
    close();
  });

  data = Array.from(sel.options).map(o => ({ value: o.value, label: o.textContent }));
  render();
  sel.__cs = {
    setOptions(opts) {
      data = opts || [];
      // 先记住重建前的选中值：清空 sel.innerHTML 会把 sel.value 重置为 ''，
      // 而占位符 option 的 value 也是 ''，会导致『当前值有效』误判、回读丢失。
      const prev = sel.value;
      sel.innerHTML = '';
      data.forEach(o => { const op = document.createElement('option'); op.value = o.value; op.textContent = o.label; sel.appendChild(op); });
      // 新数据里仍在则还原选中，否则落回首个(占位符)选项。
      if (data.some(o => o.value === prev)) sel.value = prev;
      else if (data[0]) sel.value = data[0].value;
      render();
    },
    refresh: render
  };
  return sel;
}
// 注：旧左栏 #planSelect/#baseSelect 已随 P1 重构移除（方案库迁移到底部方案条，使用原生 select）。

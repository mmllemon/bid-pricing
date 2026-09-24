/* ===== 顶部 Toast 气泡 + 即时表单校验 =====
 * 从 app.js 拆出。setMessage 被全局调用（40+ 处），
 * 校验函数 validateParams/clearInvalid/markInvalid/numVal 均在此定义。
 * 需在 app.js 之前加载（app.js 依赖 setMessage 等全局函数）。
 */

// ---- 提示 Toast（堆叠式）----
// setMessage(text, kind) 被全局调用（38 处），签名不变。内部实现为右上角堆叠容器，
// 最多同时显示 3 条；超出时最早一条从顶部滑出。每条独立计时自动消失
// （success 3.5s / error 6s / 其他 4s）。内容经 _safeToastHtml 白名单过滤。
//
// 设计取舍：旧版单例 toast-pill 会在连续操作（如"已保存"+"已删除"）时覆盖前一条，
// 用户看不到中间结果。改堆叠后能完整保留消息序列，最多 3 条堆叠不阻塞交互。
const TOAST_MAX = 3;
const TOAST_LIFE = { success: 3500, error: 6000, warn: 4000, '': 4000 };
function setMessage(text, kind = '') {
  const stack = document.querySelector('#toastStack');
  if (!stack) return;
  // 超限时移除最早一条（立即移除，不留过渡，避免堆叠时动画重叠）
  while (stack.children.length >= TOAST_MAX) {
    stack.removeChild(stack.firstElementChild);
  }
  const pill = document.createElement('div');
  pill.className = 'toast-pill' + (kind ? ' toast-' + kind : '');
  pill.innerHTML = '<span>' + _safeToastHtml(text) + '</span>';
  stack.appendChild(pill);
  // 强制回流，确保 transition 触发（从 opacity:0 → opacity:1）
  void pill.offsetWidth;
  pill.classList.add('show');
  const ms = TOAST_LIFE[kind] ?? TOAST_LIFE[''];
  setTimeout(() => {
    pill.classList.add('leaving');
    setTimeout(() => pill.remove(), 240);
  }, ms);
}
// F-11：setMessage 的 text 参数来自 API 响应与用户输入，此前直接注入 innerHTML 构成 XSS 面。
// 白名单过滤：仅允许 <b>/<strong>/<br> 三种安全标签（现有调用含 <b>已保存</b> 等粗体），
// 其它所有标签一律剥除，防止 <script>/<img onerror>/事件处理器等注入。
//
// 2026-09-24 修正：初版正则只否定匹配白名单**标签名**，白名单标签内的属性原样保留——
// 输入 <b onclick=alert(1)> 仍会穿透并执行。此处把白名单标签的属性一并剥除，
// 只保留标签名本身（<b class="x"> → <b>；<strong onmouseover=...> → <strong>）。
function _safeToastHtml(text) {
  const AMP = '\u0001';  // 内部占位符，保护原始 & 字符（不出现在最终输出）
  return String(text ?? '')
    // ① 剥所有标签：白名单标签保留 tag 名本身（丢掉属性），非白名单标签保留原样
    //    （下一步会被转义成字面文本，浏览器视为文字而非标签）。
    //    例：<b onclick=alert(1)>  →  <b>      （属性剥掉）
    //        <img onerror=x>       →  <img onerror=x>（原样保留，下一步转义）
    //    alternation 顺序 (strong|br|b)：长匹配优先，否则 <br> 会被误识别为 <b>+r。
    .replace(/<(\/?(strong|br|b))([^>]*)>/gi, (m, tag) =>
      tag.startsWith('/') ? `</${tag.slice(1).toLowerCase()}>` : `<${tag.toLowerCase()}>`)
    // ② 保护原始 & 字符（用占位符），防止 step 3 新创建的 &lt; 与原始 &lt; 混淆。
    //    例：&lt;b&gt;（用户预转义）→ \u0001lt;b\u0001gt;（step 5 不会误还原）
    .replace(/&/g, AMP)
    // ③ 转义裸 < 和 >（包括 ① 生成的白名单标签、① 保留的非白名单标签、以及用户输入的裸尖括号）。
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    // ④ 还原白名单标签：&lt;b&gt; → <b>（这些是 step 3 新创建的 &lt;，不含原始 &）。
    //    非白名单标签（如 &lt;img&gt;）不会匹配，保持为字面文本（安全）。
    .replace(/&lt;\/?(strong|br|b)&gt;/gi, (m, tag) =>
      m.startsWith('&lt;/') ? `</${tag.toLowerCase()}>` : `<${tag.toLowerCase()}>`)
    // ⑤ 还原原始 & 字符（step 2 保护的）。
    .replace(/\u0001/g, '&');
}

// 即时校验：比率区间非法在提交前拦截，并给对应输入框加错误态/焦点，避免空跑服务端再 422。
function clearInvalid() { document.querySelectorAll('.invalid').forEach(el => { el.classList.remove('invalid'); el.removeAttribute('aria-invalid'); }); }
function markInvalid(el, msg) { el.classList.add('invalid'); el.setAttribute('aria-invalid', 'true'); el.focus(); setMessage(msg, 'error'); }
function validateParams() {
  clearInvalid();
  const loEl = document.querySelector('#ratioMin'); const hiEl = document.querySelector('#ratioMax');
  const lo = Number(loEl.value); const hi = Number(hiEl.value);
  if (Number.isNaN(lo) || lo < 0 || lo > 1) { markInvalid(loEl, '单项报价比率下限非法：须为 0～1 之间的数值。'); return false; }
  if (Number.isNaN(hi) || hi > 1 || hi < lo) { markInvalid(hiEl, `报价比率区间非法：上限须 ≥ 下限（${lo}）且 ≤ 1.00。`); return false; }
  // 税率采用整数百分比口径（9 = 9%），提交时 /100 转小数（0.09）；须落在 (0, 100]
  const vtEl = document.querySelector('#vatRate'); const stEl = document.querySelector('#surtaxRate');
  const vt = Number(vtEl.value); const st = Number(stEl.value);
  if (Number.isNaN(vt) || vt <= 0 || vt > 100) { markInvalid(vtEl, '增值税率须为 0～100 之间的百分比整数（如 9 表示 9%）。'); return false; }
  if (Number.isNaN(st) || st <= 0 || st > 100) { markInvalid(stEl, '附加税率须为 0～100 之间的百分比整数（如 12 表示 12%）。'); return false; }
  return true;
}
// 比率输入实时校验：输完即标红，不必等提交
document.querySelectorAll('#ratioMin,#ratioMax').forEach(el => el.addEventListener('input', validateParams));
// 读取数字输入：留空时回落到浅灰占位默认值（目标总报价/固定税前项）
function numVal(id) { const el = document.querySelector(`#${id}`); return el.value.trim() !== '' ? el.value : el.placeholder; }

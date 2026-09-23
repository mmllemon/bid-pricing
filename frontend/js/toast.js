/* ===== 顶部 Toast 气泡 + 即时表单校验 =====
 * 从 app.js 拆出。setMessage 被全局调用（40+ 处），
 * 校验函数 validateParams/clearInvalid/markInvalid/numVal 均在此定义。
 * 需在 app.js 之前加载（app.js 依赖 setMessage 等全局函数）。
 */

// ---- 提示 Toast（P0：消息从左栏内联提示改为顶部 Toast 气泡） ----
// 保留 setMessage(text, kind) 签名（40+ 处调用点不动），内部实现为顶部 toast-pill。
// kind ∈ {success,error,warn,''}：success=模块绿、error=赤陶、warn=赭石、默认墨灰；
// 自动消失（success 3.5s / error 6s / 其他 4s）；内容可含 HTML（现有调用含 <b>）。
let toastTimer = null;
function setMessage(text, kind = '') {
  const tp = document.querySelector('#toastPill');
  const tm = document.querySelector('#toastMsg');
  if (!tp || !tm) return;
  tp.className = 'toast-pill' + (kind ? ' toast-' + kind : '');
  tm.innerHTML = _safeToastHtml(text);
  tp.classList.add('show');
  clearTimeout(toastTimer);
  const ms = kind === 'success' ? 3500 : kind === 'error' ? 6000 : 4000;
  toastTimer = setTimeout(() => tp.classList.remove('show'), ms);
}
// F-11：setMessage 的 text 参数来自 API 响应与用户输入，此前直接注入 innerHTML 构成 XSS 面。
// 白名单过滤：仅允许 <b>/<strong>/<br> 三种安全标签（现有调用含 <b>已保存</b> 等粗体），
// 其它所有标签一律剥除，防止 <script>/<img onerror>/事件处理器等注入。
function _safeToastHtml(text) {
  return String(text ?? '').replace(/<(?!\/?(b|strong|br)\b)[^>]*>/g, '');
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

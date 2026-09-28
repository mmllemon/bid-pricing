/* 全站唯一的 HTML 转义实现（frontend/js/escape.js）。
 *
 * 背景：esc() 此前散落 4 份（app.js / workbench.js / workbench.html 内嵌 /
 * toast.js 白名单），其中 workbench 版不转义单引号，属性安全靠「上下文恰好
 * 都用双引号」的隐性约束撑着——一份漏改就开洞。收拢到本模块后：
 *   - 需要转义的页面在各自脚本里把本地 `esc`/`attr` 指向 window.gcEsc，
 *     调用点零改动；
 *   - 转义行为全站唯一，且转义 `'`（属性里单引号也能安全），任何上下文都稳。
 *
 * 必须在所有使用它的业务脚本之前加载（index.html 放在 js/sidebar.js 之前）。
 */
(function () {
  'use strict';
  const MAP = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
  function gcEsc(v) {
    return String(v == null ? '' : v).replace(/[&<>"']/g, c => MAP[c]);
  }
  // 属性值语境：与 gcEsc 同一实现（gcEsc 已转义引号，无需额外处理）。
  window.gcEsc = gcEsc;
  window.gcAttr = gcEsc;
})();

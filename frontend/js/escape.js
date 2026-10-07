/* 全站唯一的 HTML 转义实现（frontend/js/escape.js）。
 *
 * 契约（三页以上都依赖它，改前请读完）：
 *   1. **每个页面都必须在任何业务脚本之前加载本文件**（index.html 放在 js/sidebar.js
 *      之前；五个工具页放在 js/workbench-nav.js 之前）。
 *   2. 业务脚本一律 `const esc = window.gcEsc;` 这类**别名**，**禁止自带实现**。
 *      历史上 esc/escapeHtml/toolEsc 各有副本，共 6 份（app.js 两处、agent-panel.js、
 *      tool-common.js、tool-well.js，其中 app.js 那份还在 renderAudit 里被同名局部
 *      变量遮蔽）——「一份漏改就开洞」正是当初把 esc 收拢到本模块的原因；副本又长回来
 *      等于白收拢。工具页此前不加载本文件，是 agent-panel.js 自带副本的直接原因，
 *      根因已消除。
 *   3. 非转义性质的清洗（如 toast.js 的白名单标签过滤）**不是**本实现，也不该改成本实现：
 *      它要保留 <b>/<br> 语义，与本模块「一律转义」的语义相反。
 *
 * 实现：转义 `& < > " '` 五个字符；String() 化并对 null/undefined 返回空串
 * （调用点因此不必自己判空）。转义 `'` 使属性语境用单引号也安全。
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

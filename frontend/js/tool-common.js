/* ===== 速算工具箱共享助手 ===== */
(function () {
  'use strict';
  window.toolFmt = function (v, d = 2) {
    return (isFinite(v)
      ? v.toLocaleString('zh-CN', { minimumFractionDigits: d, maximumFractionDigits: d })
      : '—');
  };
  window.toolNum = function (el) {
    const v = parseFloat(el && el.value);
    return isFinite(v) ? v : 0;
  };
})();

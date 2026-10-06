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
  /* 非负钳制：几何输入（挖深/沟宽/长度等）填负数时标红并按 0 参与计算，避免负工程量 */
  window.toolNonNeg = function (el) {
    const v = window.toolNum(el);
    if (el && el.classList) el.classList.toggle('invalid', v < 0);
    return v < 0 ? 0 : v;
  };
  /* HTML 转义（把用户输入拼回 value="..." / 文本节点时用） */
  window.toolEsc = function (s) {
    return String(s ?? '').replace(/[&<>"']/g, c => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    })[c]);
  };
  /* 简单防抖 */
  window.toolDebounce = function (fn, ms) {
    let t = 0;
    return function (...args) {
      clearTimeout(t);
      t = setTimeout(() => fn.apply(this, args), ms || 400);
    };
  };
  /* 本地持久化：各工具自动保存输入，刷新不丢（key 如 'tool-cable'） */
  window.toolStore = {
    save(key, obj) {
      try { localStorage.setItem('bidpricing.' + key + '.v1', JSON.stringify(obj)); }
      catch (e) { /* 隐私模式等写失败时静默跳过 */ }
    },
    load(key) {
      try {
        const raw = localStorage.getItem('bidpricing.' + key + '.v1');
        return raw ? JSON.parse(raw) : null;
      } catch (e) { return null; }
    },
    clear(key) {
      try { localStorage.removeItem('bidpricing.' + key + '.v1'); } catch (e) {}
    }
  };
  /* 复制文本：优先 Clipboard API，降级用 textarea+execCommand */
  window.toolCopyText = async function (text) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch (e) {
      try {
        const ta = document.createElement('textarea');
        ta.value = text;
        ta.style.cssText = 'position:fixed;opacity:0;';
        document.body.appendChild(ta);
        ta.select();
        const ok = document.execCommand('copy');
        ta.remove();
        return ok;
      } catch (e2) { return false; }
    }
  };
  /* 跨工具交接：单槽位 localStorage（如排管断面 → 土方工具的沟底宽）。
   * 发送方 toolHandoff.send(kind, payload)，接收方 take(kind) 读取，
   * 应用/忽略后 clear()。kind 冲突时后发覆盖先发。 */
  window.toolHandoff = {
    KEY: 'bidpricing.handoff.v1',
    TTL: 24 * 3600 * 1000,   // 交接槽 24h 过期：跨天残留的旧交接不再被误取
    send(kind, payload) {
      try { localStorage.setItem(this.KEY, JSON.stringify({ kind, at: Date.now(), payload })); }
      catch (e) { /* 隐私模式等写失败时静默跳过 */ }
    },
    take(kind) {
      try {
        const raw = localStorage.getItem(this.KEY);
        if (!raw) return null;
        const o = JSON.parse(raw);
        if (!o || o.kind !== kind) return null;
        if (typeof o.at === 'number' && Date.now() - o.at > this.TTL) { this.clear(); return null; }
        return o;
      } catch (e) { return null; }
    },
    clear() {
      try { localStorage.removeItem(this.KEY); } catch (e) {}
    }
  };
})();

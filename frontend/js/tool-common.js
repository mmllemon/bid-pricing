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
  /* ---------- P2 代码抽取：四工具页共享样板 ---------- */
  /* $ 选择器（四页原各一份） */
  window.tool$ = function (sel, root) { return (root || document).querySelector(sel); };

  /* 自动保存：防抖写 toolStore；公共方法缺失时退化为空操作 */
  window.toolAutosave = function (key, collectState, ms) {
    if (!window.toolStore || !window.toolDebounce) return function () {};
    const saveNow = () => window.toolStore.save(key, collectState());
    return window.toolDebounce(saveNow, ms || 500);
  };

  /* 复制按钮：点后「已复制 ✓ / 复制失败」1.5s 回显 */
  window.toolBindCopyButton = function (btn, buildTsv) {
    const el = typeof btn === 'string' ? document.querySelector(btn) : btn;
    if (!el || typeof buildTsv !== 'function') return;
    el.addEventListener('click', async () => {
      const ok = await window.toolCopyText(buildTsv());
      const old = el.textContent;
      el.textContent = ok ? '已复制 ✓' : '复制失败';
      setTimeout(() => { el.textContent = old; }, 1500);
    });
  };

  /* 确认弹窗（well 页 uiConfirm 上移；与 app.js 的 uiConfirm 同样式类，
     app.js 保留带焦点陷阱的完整版供报价页用） */
  window.toolConfirm = function (message, options) {
    options = options || {};
    const danger = options.danger !== false;
    return new Promise(resolve => {
      const esc = window.toolEsc || (t => String(t ?? ''));
      let ov = document.getElementById('ui-confirm');
      if (ov) ov.remove();
      ov = document.createElement('div');
      ov.id = 'ui-confirm';
      ov.className = 'ui-confirm-overlay open' + (danger ? ' danger' : '');
      ov.innerHTML = `<div class="ui-confirm-box" role="alertdialog" aria-modal="true" aria-label="确认">`
        + `<div class="ui-confirm-msg">${esc(message)}</div>`
        + `<div class="ui-confirm-actions">`
        + `<button type="button" class="btn-ghost" data-act="cancel">取消</button>`
        + `<button type="button" class="btn-danger" data-act="ok">${esc(options.okText || '确认删除')}</button>`
        + `</div></div>`;
      document.body.appendChild(ov);
      const done = v => { ov.remove(); resolve(v); };
      ov.querySelector('[data-act="cancel"]').addEventListener('click', () => done(false));
      ov.querySelector('[data-act="ok"]').addEventListener('click', () => done(true));
      ov.addEventListener('mousedown', e => { if (e.target === ov) done(false); });
      // P2: Esc 只关本弹窗 —— stopPropagation，避免冒泡到 agent-panel/sidebar 的全局 Esc 把面板也关掉（双重绑定）
      ov.addEventListener('keydown', e => { if (e.key === 'Escape') { e.stopPropagation(); done(false); } });
      setTimeout(() => { const c = ov.querySelector('[data-act="cancel"]'); if (c) c.focus(); }, 0);
    });
  };

  window.__toolCommonLoaded = true;
})();

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
  /* HTML 转义（把用户输入拼回 value="..." / 文本节点时用）。
     与全站唯一实现 gcEsc（js/escape.js）**同一实现**，此处不重写公式。
     各工具页已在 tool-common.js 之前加载 escape.js；顺序一旦被改坏，
     这里立刻抛可读错误，而不是静默留下第二份会各自漂移的副本。 */
  if (typeof window.gcEsc !== 'function') {
    throw new Error('tool-common.js 需要先加载 ./js/escape.js（全站唯一转义实现）');
  }
  window.toolEsc = window.gcEsc;
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

  /* 确认弹窗：**实现唯一在 js/confirm.js**（各工具页已在 tool-common.js 之前加载它）。
     这里保留 P2 的 window.toolConfirm 名字与签名，使各工具页调用点零改动。
     合并说明：P2 曾把 well 页的 uiConfirm 上移到此处，与 app.js 的 uiConfirm 形成
     **两份各自 createElement `#ui-confirm` 的实现**；两条并行方案已合为一份——
     报价页（app.js 的 uiConfirm）与工具页（本函数）都只做委托。 */
  if (typeof window.gcConfirm !== 'function') {
    throw new Error('tool-common.js 的 toolConfirm 需要先加载 ./js/confirm.js');
  }
  window.toolConfirm = function (message, options) {
    options = options || {};
    return window.gcConfirm(message, {
      danger: options.danger !== false,               // P2 口径：默认按 danger 呈现
      okLabel: options.okText || '确认删除',
      ariaLabel: options.ariaLabel || '确认',
      trap: false,                                    // 工具页没有模态栈
    });
  };

  window.__toolCommonLoaded = true;
})();

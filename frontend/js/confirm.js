/* 全站唯一的应用内确认框（frontend/js/confirm.js）。
 *
 * 背景：`#ui-confirm` 此前有**两份独立实现**——app.js 的 uiConfirm（方案/方案组删除，
 * 带 danger 标题与副文案、接报价页的模态焦点陷阱）与 js/tool-well.js 的轻量版（井库删除）。
 * 两者各自 createElement 出同一个 id，靠「永不同页加载」侥幸不冲突；一旦同页共存就会
 * 互相抢同一个 id（后建者会把先建者 remove 掉）。收拢到本模块：一处创建、一处键盘处理。
 *
 * 契约：
 *   1. 必须在任何调用它的脚本之前加载（escape.js 之后、业务脚本之前）。
 *   2. **业务文案不写进本模块**——标题/副文案/按钮文案由调用方经 options 传入；
 *      本模块只负责结构、焦点位置与「取消优先」的键盘行为。
 *   3. 返回值恒为 Promise<boolean>：确认 true；取消 / 点遮罩 / Escape 为 false。
 *      内部对「重复收尾」做了幂等保护——否则 Escape 与 click 竞态会二次弹焦点陷阱栈。
 *
 * 为什么不用原生 confirm：某些环境下原生 confirm 会被浏览器静默拦截/自动放行，
 * 造成「还没点确定就删了」的误删（原 app.js 注释即为此）。
 */
(function () {
  'use strict';
  if (typeof window.gcEsc !== 'function') {
    throw new Error('confirm.js 需要先加载 ./js/escape.js（全站唯一转义实现）');
  }

  function gcConfirm(message, options = {}) {
    const {
      danger = false,
      title = '',
      sub = '',
      okLabel = '确认删除',
      ariaLabel = danger ? '删除已定稿方案' : '确认删除',
      trap = false,
    } = options;

    return new Promise((resolve) => {
      const prior = document.getElementById('ui-confirm');
      if (prior) prior.remove();                     // 同一时刻只允许一个确认框

      const ov = document.createElement('div');
      ov.id = 'ui-confirm';
      ov.className = 'ui-confirm-overlay open' + (danger ? ' danger' : '');
      const head = title
        ? `<div class="ui-confirm-title">${gcEsc(title)}</div>`
          + (sub ? `<div class="ui-confirm-sub">${gcEsc(sub)}</div>` : '')
        : '';
      ov.innerHTML = `<div class="ui-confirm-box" role="alertdialog" aria-modal="true" aria-label="${gcEsc(ariaLabel)}">
        ${head}
        <div class="ui-confirm-msg">${gcEsc(message)}</div>
        <div class="ui-confirm-actions">
          <button type="button" class="btn-ghost" data-act="cancel">取消</button>
          <button type="button" class="btn-danger" data-act="ok">${gcEsc(okLabel)}</button>
        </div></div>`;
      document.body.appendChild(ov);

      // 焦点陷阱只有报价页有（app.js 的 trapModal/releaseTrap）；工具页没有模态栈，传 trap:false。
      const useTrap = trap
        && typeof window.trapModal === 'function'
        && typeof window.releaseTrap === 'function';
      if (useTrap) window.trapModal();

      let finished = false;
      const onKey = (e) => { if (e.key === 'Escape') { e.stopPropagation(); done(false); } };
      const done = (val) => {
        if (finished) return;                        // 竞态下只收尾一次（否则焦点陷阱栈会被弹两次）
        finished = true;
        if (useTrap) window.releaseTrap();
        document.removeEventListener('keydown', onKey, true);
        ov.remove();
        resolve(val);
      };

      ov.querySelector('[data-act="cancel"]').addEventListener('click', () => done(false));
      ov.querySelector('[data-act="ok"]').addEventListener('click', () => done(true));
      ov.addEventListener('mousedown', (e) => { if (e.target === ov) done(false); });
      // trap 模式挂文档级捕获（焦点在面板外也关得掉）；非 trap 模式挂覆盖层（与原件一致）
      if (useTrap) document.addEventListener('keydown', onKey, true);
      else ov.addEventListener('keydown', onKey);
      // 默认焦点落在「取消」上：删除类操作里最安全的那一个
      setTimeout(() => { const c = ov.querySelector('[data-act="cancel"]'); if (c) c.focus(); }, 0);
    });
  }

  window.gcConfirm = gcConfirm;
})();

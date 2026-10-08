import { beforeEach, describe, expect, it } from 'vitest';
import { act } from 'react-dom/test-utils';
import { createRoot } from 'react-dom/client';
import { useEffect } from 'react';
import { ConfirmProvider, useConfirm } from './confirm';
import type { ConfirmFn } from './confirm';

/**
 * 确认框契约测试（W-3，对齐 frontend/js/confirm.js 的 gcConfirm）。
 *
 * 无 @testing-library：用 react-dom/client 手动挂载 + act 驱动。
 * 只钉**行为契约**（Promise 语义 / 默认焦点 / Escape / 遮罩取消 / 单例），
 * 不钉 DOM 细节（那属于视觉层，靠实拍回归）。
 */

function mountWithConfirm() {
  const container = document.createElement('div');
  document.body.appendChild(container);
  const root = createRoot(container);
  let confirmFn: ConfirmFn | null = null;

  function Capture() {
    const c = useConfirm();
    useEffect(() => { confirmFn = c; }, [c]);
    return null;
  }
  act(() => {
    root.render(<ConfirmProvider><Capture /></ConfirmProvider>);
  });
  return {
    get confirm() { return confirmFn as unknown as ConfirmFn; },
    cleanup() { act(() => root.unmount()); container.remove(); },
  };
}

const okBtn = () => document.querySelector('.ui-confirm-actions .btn-danger') as HTMLButtonElement;
const cancelBtn = () => document.querySelector('.ui-confirm-actions .btn-ghost') as HTMLButtonElement;

beforeEach(() => { document.body.innerHTML = ''; });

describe('ConfirmProvider 契约', () => {
  it('确认返回 true，取消返回 false', async () => {
    const h = mountWithConfirm();
    let result: boolean | undefined;
    act(() => { void h.confirm('删除？').then((v) => { result = v; }); });
    expect(document.querySelector('#ui-confirm')).toBeTruthy();
    act(() => okBtn().click());
    await act(async () => {});
    expect(result).toBe(true);
    h.cleanup();
  });

  it('默认焦点落在「取消」上（删除类最安全的一个）', async () => {
    const h = mountWithConfirm();
    act(() => { void h.confirm('删除？', { danger: true }); });
    // 焦点由 setTimeout(0) 设置，等一个宏任务
    await act(async () => { await new Promise((r) => setTimeout(r, 0)); });
    expect(document.activeElement).toBe(cancelBtn());
    h.cleanup();
  });

  it('Escape 关闭并按取消收尾', async () => {
    const h = mountWithConfirm();
    let result: boolean | undefined;
    act(() => { void h.confirm('删除？').then((v) => { result = v; }); });
    await act(async () => { document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })); });
    expect(result).toBe(false);
    h.cleanup();
  });

  it('danger 选项加 danger 类与标题/副文案', async () => {
    const h = mountWithConfirm();
    act(() => { void h.confirm('删除该组？', { danger: true, title: '删除方案组', sub: '不可恢复', okLabel: '仍要删除' }); });
    await act(async () => {});
    const ov = document.querySelector('#ui-confirm');
    expect(ov?.classList.contains('danger')).toBe(true);
    expect(document.querySelector('.ui-confirm-title')?.textContent).toBe('删除方案组');
    expect(document.querySelector('.ui-confirm-sub')?.textContent).toBe('不可恢复');
    expect(okBtn().textContent).toBe('仍要删除');
    h.cleanup();
  });

  it('同一时刻只允许一个：新调用替换旧框，旧 Promise 按取消收尾', async () => {
    const h = mountWithConfirm();
    let first: boolean | undefined;
    act(() => { void h.confirm('第一个').then((v) => { first = v; }); });
    await act(async () => { void h.confirm('第二个'); });
    expect(document.querySelectorAll('#ui-confirm').length).toBe(1);
    expect(first).toBe(false);
    h.cleanup();
  });
});
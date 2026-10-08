import { beforeEach, describe, expect, it, vi } from 'vitest';
import { act } from 'react-dom/test-utils';
import { createRoot } from 'react-dom/client';
import { useEffect } from 'react';
import { ToastProvider, useToast } from './toast';
import type { ToastKind } from './toast';

/**
 * Toast 契约测试（W-3，对齐 frontend/js/toast.js 的 setMessage）。
 * 只钉数量上限与类型类名；自动消失的定时用假计时器验证。
 */

type ToastFn = (message: string, kind?: ToastKind) => void;

function mountWithToast() {
  const container = document.createElement('div');
  document.body.appendChild(container);
  const root = createRoot(container);
  let fn: ToastFn | null = null;
  function Capture() {
    const t = useToast();
    useEffect(() => { fn = t; }, [t]);
    return null;
  }
  act(() => { root.render(<ToastProvider><Capture /></ToastProvider>); });
  return { get toast() { return fn as unknown as ToastFn; }, cleanup() { act(() => root.unmount()); container.remove(); } };
}

beforeEach(() => { document.body.innerHTML = ''; });

describe('ToastProvider 契约', () => {
  it('堆叠最多 3 条，超限移出最早一条', async () => {
    const h = mountWithToast();
    act(() => { h.toast('A'); h.toast('B'); h.toast('C'); h.toast('D'); });
    await act(async () => {});
    const pills = document.querySelectorAll('.toast-pill');
    expect(pills.length).toBe(3);
    // 最早的 A 应已不在
    expect([...pills].map((p) => p.textContent)).toEqual(['B', 'C', 'D']);
    h.cleanup();
  });

  it('类型映射到 toast-success / toast-error / toast-warn', async () => {
    const h = mountWithToast();
    act(() => { h.toast('ok', 'success'); h.toast('bad', 'error'); h.toast('warn', 'warn'); });
    await act(async () => {});
    expect(document.querySelector('.toast-pill.toast-success')?.textContent).toBe('ok');
    expect(document.querySelector('.toast-pill.toast-error')?.textContent).toBe('bad');
    expect(document.querySelector('.toast-pill.toast-warn')?.textContent).toBe('warn');
    h.cleanup();
  });

  it('按生命周期自动消失（success 3.5s）', async () => {
    vi.useFakeTimers();
    const h = mountWithToast();
    act(() => { h.toast('走了', 'success'); });
    act(() => { vi.advanceTimersByTime(12); });  // show 帧
    expect(document.querySelectorAll('.toast-pill').length).toBe(1);
    act(() => { vi.advanceTimersByTime(3500 + 240 + 10); });
    expect(document.querySelectorAll('.toast-pill').length).toBe(0);
    h.cleanup();
    vi.useRealTimers();
  });
});
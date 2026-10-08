import { createContext, useCallback, useContext, useRef, useState } from 'react';
import type { ReactNode } from 'react';

/**
 * 顶部 Toast 堆叠（W-3：由 frontend/js/toast.js 的 setMessage 迁入 React）。
 *
 * 契约对齐原实现：
 *   - 右上角堆叠，最多同时 3 条；超限移出最早一条。
 *   - 按类型自动消失：success 3.5s / error 6s / warn 4s / 默认 4s。
 *   - 语义由左侧色条 + 文案承载（CSS 已有 .toast-success/error/warn）。
 *
 * 与原生实现的一处**有意差异**：原生 innerHTML + 白名单正则过滤 <b>/<strong>/<br>
 * （因为它要注入富文本）。React 侧改用纯文本 children，由 React 自动转义——
 * 不存在 XSS 面，也就不需要白名单过滤器。调用方要粗体请传 ReactNode。
 *
 * 用法：const toast = useToast(); toast('已保存', 'success');
 */

export type ToastKind = 'success' | 'error' | 'warn' | '';
type ToastFn = (message: ReactNode, kind?: ToastKind) => void;

interface ToastItem { id: number; message: ReactNode; kind: ToastKind; show: boolean; leaving: boolean }

const ToastContext = createContext<ToastFn | null>(null);

const TOAST_MAX = 3;
const TOAST_LIFE: Record<string, number> = { success: 3500, error: 6000, warn: 4000, '': 4000 };

export function useToast(): ToastFn {
  const fn = useContext(ToastContext);
  if (!fn) throw new Error('useToast 必须在 <ToastProvider> 内使用');
  return fn;
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const idRef = useRef(0);

  const push = useCallback<ToastFn>((message, kind = '') => {
    const id = ++idRef.current;
    setItems((prev) => {
      const next = [...prev, { id, message, kind, show: false, leaving: false }];
      return next.length > TOAST_MAX ? next.slice(next.length - TOAST_MAX) : next;
    });
    // 下一帧加 show，触发 opacity 过渡（对齐原生「强制回流再加 show」）
    window.setTimeout(() => setItems((prev) => prev.map((t) => (t.id === id ? { ...t, show: true } : t))), 12);
    const ms = TOAST_LIFE[kind] ?? TOAST_LIFE[''];
    window.setTimeout(() => setItems((prev) => prev.map((t) => (t.id === id ? { ...t, leaving: true } : t))), ms);
    window.setTimeout(() => setItems((prev) => prev.filter((t) => t.id !== id)), ms + 240);
  }, []);

  return (
    <ToastContext.Provider value={push}>
      {children}
      <div className="toast-stack" id="toastStack" aria-live="polite" aria-atomic="false">
        {items.map((t) => (
          <div key={t.id}
            className={`toast-pill${t.kind ? ` toast-${t.kind}` : ''}${t.show ? ' show' : ''}${t.leaving ? ' leaving' : ''}`}>
            <span>{t.message}</span>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}
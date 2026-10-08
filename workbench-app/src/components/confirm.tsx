import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react';
import type { ReactNode } from 'react';

/**
 * 应用内确认框（W-3：由 frontend/js/confirm.js 的 gcConfirm 迁入 React）。
 *
 * 契约与原实现一致（逐条对齐，勿简化）：
 *   1. 返回值是 Promise<boolean>：确认 true；取消 / 点遮罩 / Escape 均 false。
 *   2. 同一时刻只允许一个确认框（新调用替换旧的）。
 *   3. 默认焦点落在「取消」上——删除类操作里最安全的那一个。
 *   4. 收尾幂等：Escape 与 click 竞态下只 resolve 一次。
 *   5. **业务文案不写进本模块**：title/sub/okLabel 由调用方传入。
 *
 * 为什么不用原生 confirm：某些环境下原生 confirm 会被浏览器静默拦截/自动放行，
 * 造成「还没点确定就删了」的误删（原 app.js 注释即为证）。
 *
 * 用法：const confirm = useConfirm(); if (!(await confirm('删除该组？'))) return;
 */

export interface ConfirmOptions {
  danger?: boolean;
  title?: string;
  sub?: string;
  okLabel?: string;
  ariaLabel?: string;
}

type ConfirmFn = (message: string, options?: ConfirmOptions) => Promise<boolean>;

interface PendingState extends ConfirmOptions {
  message: string;
  resolve: (v: boolean) => void;
  open: boolean;
  leaving: boolean;
}

const ConfirmContext = createContext<ConfirmFn | null>(null);

export function useConfirm(): ConfirmFn {
  const fn = useContext(ConfirmContext);
  if (!fn) throw new Error('useConfirm 必须在 <ConfirmProvider> 内使用');
  return fn;
}

export function ConfirmProvider({ children }: { children: ReactNode }) {
  const [pending, setPending] = useState<PendingState | null>(null);
  const cancelRef = useRef<HTMLButtonElement>(null);
  const finishedRef = useRef(false);

  const confirm = useCallback<ConfirmFn>((message, options = {}) => {
    return new Promise<boolean>((resolve) => {
      // 新调用替换旧框：旧框按「取消」收尾，避免悬空 Promise。
      setPending((prev) => {
        if (prev) prev.resolve(false);
        return { ...options, message, resolve, open: true, leaving: false };
      });
    });
  }, []);

  const finish = useCallback((val: boolean) => {
    if (finishedRef.current) return;
    finishedRef.current = true;
    setPending((prev) => {
      if (prev) prev.resolve(val);
      return prev ? { ...prev, open: false, leaving: true } : prev;
    });
  }, []);

  // 重开时复位幂等旗 + 焦点落到「取消」
  useEffect(() => {
    if (!pending || pending.leaving) return;
    finishedRef.current = false;
    const t = window.setTimeout(() => cancelRef.current?.focus(), 0);
    return () => window.clearTimeout(t);
  }, [pending?.open, pending?.leaving]);

  // 关闭后从 DOM 摘除（removal 由 leaving 态触发一次）
  useEffect(() => {
    if (!pending?.leaving) return;
    const t = window.setTimeout(() => setPending(null), 160);
    return () => window.clearTimeout(t);
  }, [pending?.leaving]);

  // Escape 关闭（捕获阶段，与原生 trap 模式一致）
  useEffect(() => {
    if (!pending || pending.leaving) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return;
      e.stopPropagation();
      finish(false);
    };
    document.addEventListener('keydown', onKey, true);
    return () => document.removeEventListener('keydown', onKey, true);
  }, [pending, finish]);

  const danger = Boolean(pending?.danger);

  return (
    <ConfirmContext.Provider value={confirm}>
      {children}
      {pending && (
        <div
          id="ui-confirm"
          className={`ui-confirm-overlay${pending.open && !pending.leaving ? ' open' : ''}${danger ? ' danger' : ''}`}
          onMouseDown={(e) => { if (e.target === e.currentTarget) finish(false); }}
        >
          <div className="ui-confirm-box" role="alertdialog" aria-modal="true"
            aria-label={pending.ariaLabel || (danger ? '危险操作确认' : '确认')}>
            {pending.title && <div className="ui-confirm-title">{pending.title}</div>}
            {pending.sub && <div className="ui-confirm-sub">{pending.sub}</div>}
            <div className="ui-confirm-msg">{pending.message}</div>
            <div className="ui-confirm-actions">
              <button type="button" className="btn-ghost" ref={cancelRef} onClick={() => finish(false)}>取消</button>
              <button type="button" className="btn-danger" onClick={() => finish(true)}>{pending.okLabel || '确认'}</button>
            </div>
          </div>
        </div>
      )}
    </ConfirmContext.Provider>
  );
}
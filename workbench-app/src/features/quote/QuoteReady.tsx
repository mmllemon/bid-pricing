import type { QuoteParamsState } from './Quote';

/**
 * 报价页右栏就绪态（P3 块3：由 frontend/index.html 的 #preparePanel 迁入 React）
 * 三态：就绪清单（未计算）→ 计算中 → 结果态（KPI + 明细表，由 Quote.tsx 切换）。
 */
export interface ReadyState {
  project: boolean;   // 已选关联项目 或 已填目标总报价
  files: boolean;     // 两个清单都已导入
  tax: boolean;       // 税口径闭环（占比合计 100% 或 不可抵扣）
}

export function QuoteReady({
  ready, onCalculate, calculating, balanceText,
}: {
  ready: ReadyState;
  onCalculate: () => void;
  calculating: boolean;
  balanceText: string;
}) {
  const set = (on: boolean, okText: string, pendingText: string, alert = false) => ({
    state: on ? 'ok' : alert ? 'alert' : 'pending',
    text: on ? okText : pendingText,
  });
  const items = [
    { id: 'prepProject', ...set(ready.project, '已完成：已选择关联项目（或已填写目标总报价与固定税前项）', '待完成：请选择关联项目，或填写目标总报价与固定税前项') },
    { id: 'prepFiles', ...set(ready.files, '已完成：限价清单与成本清单均已导入（支持拖拽）', '待完成：请导入限价清单与成本清单（支持拖拽）') },
    { id: 'prepTax', ...set(ready.tax, '已完成：成本进项抵扣已声明且占比合计 100%', '待完成：请声明成本进项抵扣构成（或选不可抵扣）') },
  ];
  const allReady = ready.project && ready.files && ready.tax;

  return (
    <div className="card prepare-panel" id="preparePanel">
      <div className="card-head">
        <span className="card-title"><span className="title-dot" />测算准备就绪度检查清单</span>
        <span className="card-subtitle">就绪即可推演</span>
      </div>
      {items.map((it) => (
        <div className="prep-item" id={it.id} data-state={it.state} key={it.id}>
          <span className="prep-dot" /><span className="prep-text">{it.text}</span>
        </div>
      ))}
      <div className="prep-actions">
        <button className="btn-secondary" id="previewBtn" disabled>预览导入资料</button>
        <button className={`btn-primary${allReady && !calculating ? ' ready-pulse' : ''}`} id="calculateBtn"
          onClick={onCalculate} disabled={calculating} aria-busy={calculating}>
          {calculating ? '正在计算…' : '识别文件并计算'}
          {!calculating && (
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round"><path d="M5 12h14M13 6l6 6-6 6" /></svg>
          )}
        </button>
      </div>
      {balanceText && <div className="hint" style={{ marginTop: 8 }}>{balanceText}</div>}
    </div>
  );
}

/** 结果态折叠胶囊条（原生 #statusCapsule）。 */
export function StatusCapsule({ text }: { text: string }) {
  return (
    <div className="status-capsule" id="statusCapsule" role="status" aria-live="polite">
      <span className="capsule-dot" aria-hidden="true" />
      <span className="capsule-text" id="statusCapsuleText">{text}</span>
    </div>
  );
}

export function computeReady(params: QuoteParamsState, hasFiles: boolean, taxClosed: boolean): ReadyState {
  return {
    project: Boolean(params.projectId) || (params.targetTotal !== '' && params.fixedPretax !== ''),
    files: hasFiles,
    tax: params.taxMode === 'NONE' || taxClosed,
  };
}

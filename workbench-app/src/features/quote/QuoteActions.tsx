import type { QuoteResult } from './quoteCalc';

/**
 * 报价页结果动作栏（P3 块4a：由 app.js fillResultToolbar 迁入 React）
 * 下载 Excel（超链到后端导出） / 下载 JSON（本地 Blob） / 定稿并回写项目（需已选关联项目）。
 */
export function QuoteActions({
  result, savedPlan, canFinalize, onFinalize,
}: {
  result: QuoteResult;
  savedPlan: boolean;
  canFinalize: boolean;
  onFinalize: () => void;
}) {
  // 下载兜底：历史方案 result 可能未带 excel_download_url，按 plan_id 推导
  const dlUrl = (result.excel_download_url as string) || (result.plan_id ? `/api/quote/download/${result.plan_id}` : '');

  const downloadJson = () => {
    const blob = new Blob([JSON.stringify(result, null, 2)], { type: 'application/json' });
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = '报价结果_结算调整版.json';
    link.click();
    URL.revokeObjectURL(link.href);
  };

  return (
    <div className="result-actions" id="resultActions">
      {savedPlan && <span className="plan-saved-pill">方案已保存</span>}
      {dlUrl && (
        <a className="download-button" href={dlUrl} download={String(dlUrl).split('/').pop()}>下载 Excel</a>
      )}
      <button className="btn-secondary" id="downloadResult" onClick={downloadJson}>下载 JSON</button>
      {canFinalize && (
        <button className="btn-primary" id="finalizeBid" onClick={onFinalize}
          title="将目标总报价写回为该项目投标报价金额，竞争性预算写回为投标成本测算">
          定稿并回写项目
        </button>
      )}
    </div>
  );
}

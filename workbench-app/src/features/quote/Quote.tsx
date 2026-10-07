import { useCallback, useMemo, useRef, useState } from 'react';
import { computeCompliance, computeInputVat, marginRatePercent, type QuoteResult } from './quoteCalc';
import { QuoteParams } from './QuoteParams';
import { QuoteKpi } from './QuoteKpi';
import { QuoteTable } from './QuoteTable';
import { QuotePreview } from './QuotePreview';
import { previewQuote } from './quoteApi';
import type { QuotePreviewResult } from './quoteApi';

/**
 * 投标报价沙盘（P3 前端整合：由 frontend/index.html 的 #quoteView + app.js 迁入 React）
 *
 * 迁移分块（每块独立验证，与原生逐字段对照）：
 *   块1（本提交）  参数卡（5 张）+ 右栏 KPI 只读 + 明细表空态
 *   块2 上传舱 + 预览       块3 KPI 派生 + 明细表交互
 *   块4 方案中心 + 对比     块5 审计 + 导出 + 穿透
 *
 * 派生数值走 features/quote/quoteCalc（纯函数，有判据）；后端契约不变。
 */
export interface QuoteParamsState {
  projectId: string;
  targetTotal: string;
  fixedPretax: string;
  vatRate: string;
  surtaxRate: string;
  ratioLow: number;
  ratioHigh: number;
  lowRatioConfirmed: boolean;
  lowPriceConfirmedBy: string;
  lowPriceBasisBy: string;
  taxMode: string;
  clauseEnabled: boolean;
  ubMMin: string;
  ubMMax: string;
  ubKwRules: string;
}

const DEFAULT_PARAMS: QuoteParamsState = {
  projectId: '', targetTotal: '', fixedPretax: '', vatRate: '9', surtaxRate: '12',
  ratioLow: 50, ratioHigh: 80, lowRatioConfirmed: false,
  lowPriceConfirmedBy: '', lowPriceBasisBy: '',
  taxMode: 'PARTIAL', clauseEnabled: false, ubMMin: '', ubMMax: '', ubKwRules: '',
};

export default function QuotePage() {
  const [params, setParams] = useState<QuoteParamsState>(DEFAULT_PARAMS);
  // 结果态：块 1 仅用于渲染 KPI 骨架（无结果时显示「待测算」），API 接入在块 3。
  const [result] = useState<QuoteResult | null>(null);

  // 上传舱：File 对象不进 state（不可序列化），用 ref 持有；仅存展示/摘要所需
  const capFileRef = useRef<File | null>(null);
  const costFileRef = useRef<File | null>(null);
  const [capName, setCapName] = useState<string | null>(null);
  const [costName, setCostName] = useState<string | null>(null);
  const [preview, setPreview] = useState<QuotePreviewResult | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const [message, setMessage] = useState<{ text: string; kind: 'info' | 'error' | 'success' } | null>(null);

  const set = (patch: Partial<QuoteParamsState>) => setParams((s) => ({ ...s, ...patch }));

  const onFile = (kind: 'cap' | 'cost', f: File | null) => {
    if (kind === 'cap') { capFileRef.current = f; setCapName(f?.name ?? null); }
    else { costFileRef.current = f; setCostName(f?.name ?? null); }
    setPreview(null);   // 文件变化即清旧预览，避免「未解析却显示上轮数据」
    setMessage(null);
  };

  const runPreview = useCallback(async () => {
    const cap = capFileRef.current, cost = costFileRef.current;
    if (!cap || !cost) { setMessage({ text: '请先上传限价清单和成本清单。', kind: 'error' }); return; }
    setPreviewing(true);
    setMessage({ text: '正在识别文件并核对导入资料，请稍候。', kind: 'info' });
    try {
      const res = await previewQuote(cap, cost, params.projectId, '');
      if (res.status !== 'PASS') throw new Error(res.reason || '预览未通过');
      setPreview(res);
      setMessage({ text: `预览完成：限价 ${res.cap.rows} 行、成本 ${res.cost.rows} 行，可优化 ${res.optimizable_count} 项。`, kind: 'success' });
    } catch (e) {
      setPreview(null);
      setMessage({ text: `预览失败：${(e as Error).message}`, kind: 'error' });
    } finally {
      setPreviewing(false);
    }
  }, [params.projectId]);

  const compliance = useMemo(() => computeCompliance(result), [result]);
  const vat = useMemo(() => computeInputVat(result), [result]);
  const margin = useMemo(() => marginRatePercent(result), [result]);

  return (
    <div className="page page-quote" id="quoteView">
      <div className="breadcrumb">投标报价 <span>/</span> 优化沙盘</div>

      {message && (
        <div className={`ui-alert ui-alert--${message.kind === 'error' ? 'error' : message.kind === 'success' ? 'success' : 'info'}`} role="status">
          {message.text}
        </div>
      )}

      <div className="workbench-layout">
        <QuoteParams
          params={params}
          set={set}
          capFile={capName}
          costFile={costName}
          onFile={onFile}
          onPreview={runPreview}
          previewing={previewing}
          capStat={preview ? `已解析 ${preview.cap.rows} 行 ｜ 匹配 ${preview.match.matched}` : ''}
          costStat={preview ? `已解析 ${preview.cost.rows} 行` : ''}
        />

        <section className="canvas-column">
          {preview && <QuotePreview res={preview} />}
          <QuoteKpi result={result} compliance={compliance} vat={vat} marginRate={margin} />
          <QuoteTable items={[]} totalCount={0} />
        </section>
      </div>
    </div>
  );
}

import { useMemo, useState } from 'react';
import { computeCompliance, computeInputVat, marginRatePercent, type QuoteResult } from './quoteCalc';
import { QuoteParams } from './QuoteParams';
import { QuoteKpi } from './QuoteKpi';
import { QuoteTable } from './QuoteTable';

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

  const set = (patch: Partial<QuoteParamsState>) => setParams((s) => ({ ...s, ...patch }));

  const compliance = useMemo(() => computeCompliance(result), [result]);
  const vat = useMemo(() => computeInputVat(result), [result]);
  const margin = useMemo(() => marginRatePercent(result), [result]);

  return (
    <div className="page page-quote" id="quoteView">
      <div className="breadcrumb">投标报价 <span>/</span> 优化沙盘</div>

      <div className="workbench-layout">
        <QuoteParams params={params} set={set} />

        <section className="canvas-column">
          <QuoteKpi
            result={result}
            compliance={compliance}
            vat={vat}
            marginRate={margin}
          />
          <QuoteTable items={[]} totalCount={0} />
        </section>
      </div>
    </div>
  );
}

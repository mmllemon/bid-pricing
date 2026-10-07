import type { Compliance, InputVat } from './quoteCalc';
import type { QuoteResult } from './quoteCalc';

/**
 * 报价页右栏 KPI 四联（P3 块1：由 frontend/index.html 的 .kpi-row 迁入 React）
 * 数值全部来自 quoteCalc 的派生函数（有判据）；无结果时显示占位。
 */
const fmtMoney = (v: number) => `¥${Number(v).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

export function QuoteKpi({
  result, compliance, vat, marginRate,
}: {
  result: QuoteResult | null;
  compliance: Compliance;
  vat: InputVat;
  marginRate: number;
}) {
  const has = Boolean(result);
  const total = Number(result?.target_total ?? 0);
  const objective = Number(result?.objective ?? 0);
  const pass = result?.status === 'PASS';

  return (
    <div className="kpi-row">
      {/* 1. 测算总报价 */}
      <div className="kpi-card" id="kpiCardTotal" role="button" tabIndex={0} aria-label="清除筛选，查看全部清单">
        <div className="kpi-label-row">
          <span className="kpi-title">测算总报价 (含税)</span>
          <span className="kpi-drill-hint">看全部清单 →</span>
        </div>
        <div className="kpi-val tabular" id="kpiTotalVal">{has ? fmtMoney(total) : '—'}</div>
        <div className="kpi-vis">
          <svg className="sparkline-svg" viewBox="0 0 160 28" id="sparkTotal" role="img" aria-label="测算总报价轨迹">
            <line x1={10} y1={14} x2={150} y2={14} stroke="var(--text-tertiary)" strokeDasharray="3 3" />
          </svg>
        </div>
        <div className="kpi-foot">
          <span className="delta-badge neutral" id="kpiTotalDelta">{has ? (pass ? '锁定约束' : '未平衡') : '待测算'}</span>
          <span id="kpiTotalCap">
            {result?.competitive_budget ? `竞争预算 ${Number(result.competitive_budget).toLocaleString('zh-CN', { maximumFractionDigits: 0 })}` : '—'}
          </span>
        </div>
      </div>

      {/* 2. 预期毛利额 */}
      <div className="kpi-card kpi-bamboo" id="kpiCardMargin" role="button" tabIndex={0} aria-label="按毛利穿透筛选" aria-pressed={false}>
        <div className="kpi-label-row">
          <span className="kpi-title">预期毛利额</span>
          <span className="kpi-drill-hint">按毛利穿透 →</span>
        </div>
        <div className="kpi-val tabular" id="kpiMarginVal">{has ? fmtMoney(objective) : '—'}</div>
        <div className="kpi-vis">
          <svg className="sparkline-svg" viewBox="0 0 160 28" id="sparkMargin" role="img" aria-label="毛利趋势">
            <line x1={10} y1={23} x2={150} y2={23} stroke="var(--text-tertiary)" strokeDasharray="2 3" />
          </svg>
        </div>
        <div className="kpi-foot">
          <span id="kpiCashflowTag">{pass ? '结算调整后利润 · 不含税' : '待计算'}</span>
          <span id="kpiMarginRate">毛利率 {marginRate.toFixed(1)}%</span>
        </div>
      </div>

      {/* 3. 合规防畸形评分 */}
      <div className="kpi-card kpi-ochre" id="kpiCardScore" role="button" tabIndex={0} aria-label="查看风险项" aria-pressed={false}>
        <div className="kpi-label-row">
          <span className="kpi-title">合规防畸形评分</span>
          <span className="kpi-drill-hint">看风险项 →</span>
        </div>
        <div className="kpi-val tabular" id="kpiScoreVal">
          {has ? compliance.score : '—'} {has && <span className="grade">{compliance.grade}</span>}
        </div>
        <div className="kpi-vis">
          <div className="kpi-scale">
            <i className="seg-safe" id="scaleSafe" style={{ width: `${compliance.safe}%` }} />
            <i className="seg-early" id="scaleEarly" style={{ width: `${compliance.early}%` }} />
            <i className="seg-risk" id="scaleRisk" style={{ width: `${compliance.risk}%` }} />
          </div>
        </div>
        <div className="kpi-foot">
          <span className={`delta-badge ${compliance.badge}`} id="kpiAuditTag">{has ? compliance.audit : '待测算'}</span>
          <span id="kpiMaxDev">{has ? `最大偏离 ${compliance.maxDev}` : '—'}</span>
        </div>
      </div>

      {/* 4. 进项抵扣总额 */}
      <div className="kpi-card kpi-blue">
        <div className="kpi-label-row">
          <span className="kpi-title">测算进项抵扣总额</span>
        </div>
        <div className="kpi-val tabular" id="kpiVatVal">{has ? fmtMoney(vat.vat) : '—'}</div>
        <div className="kpi-vis">
          <svg className="sparkline-svg" viewBox="0 0 160 28" role="img" aria-label="进项抵扣构成">
            <rect x={10} y={8} width={110} height={12} rx={0} fill="var(--module-2)" opacity={0.85} />
            <rect x={124} y={8} width={26} height={12} rx={0} fill="var(--module-2)" opacity={0.15} />
          </svg>
        </div>
        <div className="kpi-foot">
          <span id="kpiVatShare">{has ? `材料抵扣贡献 ${vat.share}` : '—'}</span>
          <span className="kpi-foot-status" id="kpiVatStatus">{has ? vat.status : '待测算'}</span>
        </div>
      </div>
    </div>
  );
}

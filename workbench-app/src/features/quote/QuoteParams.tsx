import { useState } from 'react';
import type { QuoteParamsState } from './Quote';
import { buildTaxOverride, type TaxComp } from './quoteCalc';

/**
 * 报价页左栏参数区（P3 块1：由 frontend/index.html 的 .param-column 迁入 React）
 * 5 张卡：本次测算参数 / 单项报价安全防线（双滑块） / 不平衡报价 / 成本进项税抵扣模型 / 报价资料（上传舱）。
 */

/**
 * 默认成本构成：与 app.js 的 COMP_DEFAULTS 逐字对齐
 * （匹配 config/project_quote_policy.json）；否则 k 与进项抵扣会与原生版不同。
 */
export const VOLT_DEFAULT_COMP: TaxComp[] = [
  { key: 'goods', label: '材料设备', proportion: 0.65, input_vat_rate: 0.13 },
  { key: 'service', label: '劳务及措施', proportion: 0.35, input_vat_rate: 0.09 },
];

export function QuoteParams({ params, set, comp, setComp, projects, capFile, costFile, onFile, onPreview, previewing, capStat, costStat }: {
  params: QuoteParamsState;
  set: (p: Partial<QuoteParamsState>) => void;
  comp: TaxComp[];
  setComp: (fn: (cs: TaxComp[]) => TaxComp[]) => void;
  projects: { id: string; name: string; bid_amount?: string }[];
  capFile: string | null;
  costFile: string | null;
  onFile: (kind: 'cap' | 'cost', f: File | null) => void;
  onPreview: () => void;
  previewing: boolean;
  capStat: string;
  costStat: string;
}) {
  const [riskOpen, setRiskOpen] = useState(false);

  const totalProp = comp.reduce((s, c) => s + (Number.isFinite(c.proportion) ? c.proportion : 0), 0);
  const k = 1 - comp.reduce((s, c) => s + (c.proportion * c.input_vat_rate) / (1 + c.input_vat_rate), 0);
  const override = buildTaxOverride(params.taxMode, comp);
  const creditPct = (override.creditRatio * 100).toFixed(1);

  // 双滑块碰撞锁：低值不得越过高值。
  // 注意：钐制后的值可能与当前 state 相同（如用户把低值拖到 100，而高值-1 已也是当前低值），
  // 此时 React 不重渲染、DOM 会停在用户拖出的非法值 —— 必须显式回写 e.currentTarget。
  const setLow = (v: number, el: HTMLInputElement) => {
    const clamped = Math.min(v, params.ratioHigh - 1);
    el.value = String(clamped);
    set({ ratioLow: clamped });
  };
  const setHigh = (v: number, el: HTMLInputElement) => {
    const clamped = Math.max(v, params.ratioLow + 1);
    el.value = String(clamped);
    set({ ratioHigh: clamped });
  };

  return (
    <aside className="param-column">
      {/* ===== 1. 本次测算参数 ===== */}
      <section className="card">
        <div className="card-head">
          <span className="card-title"><span className="title-dot" />本次测算参数</span>
          <span className="card-subtitle">目标约束反推</span>
        </div>
        <div className="field-group">
          <label className="field" data-tip="从「项目经营概览」选择处于投标阶段的项目">
            <span className="field-label">关联投标项目</span>
            <select id="projectId" value={params.projectId} onChange={(e) => {
              const pid = e.target.value;
              const proj = projects.find((p) => p.id === pid);
              // 选中项目时带入目标总报价（取项目投标报价金额）
              set({ projectId: pid, ...(proj && proj.bid_amount ? { targetTotal: String(proj.bid_amount) } : {}) });
            }}>
              <option value="">— 请先选择关联投标项目 —</option>
              {projects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
          </label>
          <div style={{ display: 'flex', gap: 10 }}>
            <label className="field" style={{ flex: 1 }} data-tip="目标总报价 = 投标报价金额（含税，元）">
              <span className="field-label">目标总报价</span>
              <div className="input-affix">
                <span className="input-prefix">¥</span>
                <input id="targetTotal" className="tabular" type="number" placeholder="0.00" step="0.01"
                  value={params.targetTotal} onChange={(e) => set({ targetTotal: e.target.value })} />
                <span className="input-suffix">元</span>
              </div>
            </label>
            <label className="field" style={{ flex: 1 }} data-tip="措施项目费与规费等固定税前项，不参与单价优化">
              <span className="field-label">固定税前项</span>
              <div className="input-affix">
                <span className="input-prefix">¥</span>
                <input id="fixedPretax" className="tabular" type="number" placeholder="0.00"
                  value={params.fixedPretax} onChange={(e) => set({ fixedPretax: e.target.value })} />
                <span className="input-suffix">元</span>
              </div>
            </label>
          </div>
          <div style={{ display: 'flex', gap: 10 }}>
            <div className="field" style={{ flex: 1 }}>
              <label className="field-label">增值税率</label>
              <div className="input-affix">
                <input id="vatRate" className="tabular" type="number" step={1} min={0} max={100}
                  value={params.vatRate} onChange={(e) => set({ vatRate: e.target.value })} />
                <span className="input-suffix">%</span>
              </div>
            </div>
            <div className="field" style={{ flex: 1 }}>
              <label className="field-label">附加税率</label>
              <div className="input-affix">
                <input id="surtaxRate" className="tabular" type="number" step={1} min={0} max={100}
                  value={params.surtaxRate} onChange={(e) => set({ surtaxRate: e.target.value })} />
                <span className="input-suffix">%</span>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ===== 2. 单项报价安全防线（双滑块） ===== */}
      <section className="card">
        <div className="card-head">
          <span className="card-title"><span className="title-dot" />单项报价安全防线</span>
          <span className="card-subtitle">防畸形风控</span>
        </div>
        <div className="guardrail">
          <div className="range-meta">
            <span style={{ fontSize: 12, color: 'var(--text-secondary)' }}>安全防线区间</span>
            <span className="range-val tabular" id="ratioRangeText">{params.ratioLow}% ~ {params.ratioHigh}%</span>
          </div>
          <div className="guardrail-track">
            <div className="guardrail-zones" aria-hidden="true">
              <span className="gz-serious">0%</span><span className="gz-line">50%</span><span className="gz-safe">100%</span>
            </div>
            <div className="guardrail-fill" id="ratioFill"
              style={{ left: `${params.ratioLow}%`, width: `${Math.max(0, params.ratioHigh - params.ratioLow)}%` }} />
            <input type="range" id="ratioLow" min={0} max={100} step={1} value={params.ratioLow}
              aria-label="比率区间下限" onChange={(e) => setLow(Number(e.target.value), e.currentTarget)} />
            <input type="range" id="ratioHigh" min={0} max={100} step={1} value={params.ratioHigh}
              aria-label="比率区间上限" onChange={(e) => setHigh(Number(e.target.value), e.currentTarget)} />
          </div>
          <input type="hidden" id="ratioMin" value={params.ratioLow / 100} readOnly />
          <input type="hidden" id="ratioMax" value={params.ratioHigh / 100} readOnly />
          <div className="guardrail-legend">
            <span className="gl-red"><i />废标风险区 0–50%</span>
            <span className="gl-safe"><i />合规安全区 50–100%</span>
          </div>
        </div>

        <div className="risk-alert-box" id="riskAlertDrawer" role="alert">
          <button className="risk-summary" id="riskSummaryBtn" type="button" aria-expanded={riskOpen}
            onClick={() => setRiskOpen((v) => !v)}>
            <span className="risk-corner" /> 低价风险确认
            <svg className="risk-chev" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8}><path d="M6 9l6 6 6-6" /></svg>
          </button>
          <div className="risk-fields-wrap" id="riskFieldsWrap" hidden={!riskOpen}>
            <div className="risk-hint">可能触发招标文件低价质询，请在下方留痕确认。</div>
            <div className="risk-fields">
              <label className="field"><span className="field-label">确认人</span>
                <input id="lowPriceConfirmedBy" type="text" value={params.lowPriceConfirmedBy}
                  onChange={(e) => set({ lowPriceConfirmedBy: e.target.value })} /></label>
              <label className="field"><span className="field-label">依据</span>
                <input id="lowPriceBasisBy" type="text" value={params.lowPriceBasisBy}
                  onChange={(e) => set({ lowPriceBasisBy: e.target.value })} /></label>
            </div>
          </div>
        </div>

        <div className="field-group">
          <label className="field check">
            <input id="lowRatioConfirmed" type="checkbox" checked={params.lowRatioConfirmed}
              onChange={(e) => set({ lowRatioConfirmed: e.target.checked })} />
            <span>已确认该设置，允许低于 50% 报价</span>
          </label>
        </div>
        <div className="field-group">
          <label className="field check">
            <input id="clauseEnabled" type="checkbox" checked={params.clauseEnabled}
              onChange={(e) => set({ clauseEnabled: e.target.checked })} />
            <span>启用严重不平衡报价结算修正条款</span>
          </label>
        </div>
      </section>

      {/* ===== 3. 不平衡报价参数（方案 C） ===== */}
      <section className="card">
        <div className="card-head">
          <span className="card-title"><span className="title-dot" />不平衡报价参数</span>
          <span className="card-subtitle">仅方案 C · 策略权重分配</span>
        </div>
        <div className="field-group">
          <div style={{ display: 'flex', gap: 10 }}>
            <label className="field" style={{ flex: 1 }} data-tip="不平衡下浮系数最小值">
              <span className="field-label">m 下限</span>
              <input id="ubMMin" className="tabular" type="number" step={0.05} min={0} value={params.ubMMin}
                onChange={(e) => set({ ubMMin: e.target.value })} />
            </label>
            <label className="field" style={{ flex: 1 }} data-tip="不平衡下浮系数最大值">
              <span className="field-label">m 上限</span>
              <input id="ubMMax" className="tabular" type="number" step={0.05} min={0} value={params.ubMMax}
                onChange={(e) => set({ ubMMax: e.target.value })} />
            </label>
          </div>
          <label className="field" data-tip="按「关键字=系数」逐行填写，命中子目名称即套用">
            <span className="field-label">关键字规则</span>
            <textarea id="ubKwRules" rows={3} placeholder="如：电缆=1.15"
              value={params.ubKwRules} onChange={(e) => set({ ubKwRules: e.target.value })} />
          </label>
        </div>
      </section>

      {/* ===== 4. 成本进项税抵扣模型 ===== */}
      <section className="card">
        <div className="card-head">
          <span className="card-title"><span className="title-dot" />成本进项税抵扣模型</span>
          <span className="card-subtitle">换算有效成本</span>
        </div>
        <div className="field-group">
          <label className="field" data-tip="成本清单综合单价是含税口径，必须先声明进项税抵扣方式">
            <span className="field-label">抵扣方式</span>
            <select id="taxMode" value={params.taxMode} onChange={(e) => set({ taxMode: e.target.value })}>
              <option value="PARTIAL">部分抵扣（推荐）</option>
              <option value="FULL">全额抵扣</option>
              <option value="NONE">不可抵扣</option>
            </select>
          </label>
          <div id="composeWrap" hidden={params.taxMode === 'NONE'}>
            <div className="comp-stack">
              <div className="comp-stack-bar" id="compStackBar" role="img" aria-label="可抵扣进项占比">
                <span className="cs-fill c-credit" id="compStkCredit" style={{ width: `${creditPct}%` }} />
                <span className="cs-fill c-ledger" id="compStkLedger" style={{ width: `${100 - Number(creditPct)}%` }} />
              </div>
              <div className="comp-stack-legend">
                <span className="cl-it"><i className="cs-dot c-credit" />可抵扣进项 <b className="tabular" id="compCreditPct">{creditPct}%</b></span>
                <span className="cl-it"><i className="cs-dot c-ledger" />不可抵扣 <b className="tabular" id="compLedgerPct">{(100 - Number(creditPct)).toFixed(1)}%</b></span>
              </div>
            </div>
            <div className="compose-table">
              <div className="compose-row compose-head">
                <span>构成项</span><span>占比%</span><span>进项税率%</span>
              </div>
              <div id="composeRows">
                {comp.map((c, i) => (
                  <div className="compose-row" key={c.key}>
                    <span className="comp-label">{c.label}</span>
                    <input className="num" type="number" step={1} min={0} data-field="proportion" value={Math.round(c.proportion * 100)}
                      onChange={(e) => setComp((cs) => cs.map((x, k2) => (k2 === i ? { ...x, proportion: Number(e.target.value) / 100 } : x)))} />
                    <input className="num" type="number" step={1} min={0} data-field="rate" value={Math.round(c.input_vat_rate * 100)}
                      onChange={(e) => setComp((cs) => cs.map((x, k2) => (k2 === i ? { ...x, input_vat_rate: Number(e.target.value) / 100 } : x)))} />
                  </div>
                ))}
              </div>
            </div>
            <div className="compose-foot">
              <span id="composeSum" className={`compose-sum ${Math.abs(totalProp - 1) < 1e-6 ? 'ok' : ''}`}>
                占比合计：{(totalProp * 100).toFixed(1)}%
              </span>
              <span className="k-inline" id="kInline">
                <i>k</i><b className="tabular" id="kInlineVal">{k.toFixed(6)}</b>
                <em>k = 1 − Σ p<sub>j</sub>·r<sub>j</sub> / (1 + r<sub>j</sub>)</em>
              </span>
            </div>
          </div>
        </div>
      </section>

      {/* ===== 5. 报价资料（双通道上传舱） ===== */}
      <section className="card">
        <div className="card-head">
          <span className="card-title"><span className="title-dot" />报价资料</span>
          <span className="card-subtitle">限价 + 成本</span>
        </div>
        <div className="intake-grid">
          <label className="intake-slot cap" id="capSlot" tabIndex={0} role="button" aria-label="导入最高限价清单">
            <input id="capFile" type="file" accept=".xlsx" onChange={(e) => onFile('cap', e.target.files?.[0] ?? null)} />
            <div className="intake-head">
              <span className="intake-ic">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8}><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" /><polyline points="14 2 14 8 20 8" /><line x1="16" y1="13" x2="8" y2="13" /><line x1="16" y1="17" x2="8" y2="17" /></svg>
              </span>
              <div className="intake-title"><strong>限价清单</strong><span>综合单价列作为不含税最高限价</span></div>
            </div>
            <div className="intake-body">
              <div className="intake-state" id="capState"><span className="pulse-dot" /><span className="intake-cta" data-for="capFile">{capFile || '选择 Excel 文件'}</span></div>
              <div className="intake-stat" id="capStat">{capStat}</div>
              <button type="button" className="intake-reup" data-reup="capFile">重新上传</button>
            </div>
          </label>
          <label className="intake-slot cost" id="costSlot" tabIndex={0} role="button" aria-label="导入成本清单">
            <input id="costFile" type="file" accept=".xlsx" onChange={(e) => onFile('cost', e.target.files?.[0] ?? null)} />
            <div className="intake-head">
              <span className="intake-ic">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8}><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" /><polyline points="14 2 14 8 20 8" /><line x1="12" y1="18" x2="12" y2="12" /><line x1="9" y1="15" x2="15" y2="15" /></svg>
              </span>
              <div className="intake-title"><strong>成本清单</strong><span>综合单价作为含税成本</span></div>
            </div>
            <div className="intake-body">
              <div className="intake-state" id="costState"><span className="pulse-dot" /><span className="intake-cta" data-for="costFile">{costFile || '选择 Excel 文件'}</span></div>
              <div className="intake-stat" id="costStat">{costStat}</div>
              <button type="button" className="intake-reup" data-reup="costFile">重新上传</button>
            </div>
          </label>
        </div>
        <div className="action-row" style={{ marginTop: 12 }}>
          <button type="button" className="btn-secondary" onClick={onPreview} disabled={previewing || !capFile || !costFile}>
            {previewing ? '预览中…' : '预览导入资料'}
          </button>
        </div>
      </section>
    </aside>
  );
}

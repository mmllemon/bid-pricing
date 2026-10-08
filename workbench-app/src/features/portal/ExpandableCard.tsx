import { useEffect, useState } from 'react';
import { FIELD_DICT } from './portalFields';
import { getPortalConfig } from './portalConfig';
import { api } from '../../api/client';
import type { PortalItem, PortalModule } from './portalData';

/**
 * 可展开卡片（2026-10-08 Step A）
 *
 * 两态：
 * - summary（摘要）：上半=配置字段（合同金额/开工时间/实施成本/利润率），下半=供应商+劳务单位名单
 * - detail（详情）：每个单位的合同金额/已付款/未付款/付款节点
 *
 * 数据：/api/graph/project?id=xxx（真接口）
 * 字段：portal.config.json 的 summaryFields / detailFields（可配置）
 */

interface UnitInfo {
  name: string;
  role: string;
  amount?: number;
  paid?: number;
}

interface GraphProjectData {
  units: UnitInfo[];
}

function formatValue(key: string, val: unknown): string {
  const def = FIELD_DICT[key];
  if (val == null || val === '') return '—';
  if (def?.type === 'money') {
    const n = Number(val);
    return Number.isFinite(n) ? `¥ ${n.toLocaleString('zh-CN', { minimumFractionDigits: 2 })}` : String(val);
  }
  if (def?.type === 'percent') {
    return `${val}%`;
  }
  return String(val);
}

/** 从 item 取字段值，带静态数据 fallback 映射（2026-10-08） */
function getItemField(item: PortalItem, key: string): unknown {
  const rec = item as unknown as Record<string, unknown>;
  if (rec[key] != null && rec[key] !== '') return rec[key];
  // 静态 portalData.ts 的字段名 → 配置字段名
  switch (key) {
    case 'contract_amount': return rec['bidAmount'] ?? rec['limitAmount'];
    case 'start_date': return (rec['profile'] as Record<string, string> | undefined)?.['openDate'];
    case 'exec_cost': return rec['costBudget'];
    case 'profit_margin': {
      const bid = Number(rec['bidAmount']) || 0;
      const cost = Number(rec['costBudget']) || 0;
      return bid > 0 ? (((bid - cost) / bid) * 100).toFixed(1) : null;
    }
    default: return null;
  }
}

export function ExpandableCard({
  module,
  item,
  onExpand,
  expanded,
}: {
  module: PortalModule;
  item: PortalItem;
  onExpand: () => void;
  expanded: boolean;
}) {
  const [graphData, setGraphData] = useState<GraphProjectData | null>(null);
  const [loading, setLoading] = useState(false);

  const cfg = getPortalConfig().modules.find((m) => m.id === module.id);
  const summaryFields = (cfg as { summaryFields?: { top: string[]; units: string[] } } | undefined)?.summaryFields;
  const detailFields = (cfg as { detailFields?: string[] } | undefined)?.detailFields || [];
  const unitDataSource = (cfg as { unitDataSource?: string } | undefined)?.unitDataSource;

  // 取真数据：项目关联单位
  useEffect(() => {
    if (!unitDataSource || !item.id) return;
    const url = unitDataSource.replace('{id}', encodeURIComponent(item.id));
    // 只支持 api: 前缀
    if (!url.startsWith('api:')) return;
    setLoading(true);
    api.request<GraphProjectData>(url.slice(4))
      .then((d: GraphProjectData) => setGraphData(d))
      .catch(() => setGraphData(null))
      .finally(() => setLoading(false));
  }, [unitDataSource, item.id]);

  // 从 item 或 graphData 组装摘要指标
  const topFields = summaryFields?.top || [];
  const unitFields = summaryFields?.units || [];

  // 按角色分组单位
  const suppliers = (graphData?.units || []).filter((u) => u.role === 'supplier' || u.role === '供应商');
  const laborUnits = (graphData?.units || []).filter((u) => u.role === 'labor' || u.role === '劳务' || u.role === 'subcontractor');

  if (!expanded) {
    // ===== 摘要态 =====
    return (
      <div className="expandable-card summary">
        <div className="ec-summary-top">
          {topFields.map((key) => (
            <div className="ec-metric" key={key}>
              <span className="ec-label">{FIELD_DICT[key]?.label || key}</span>
              <strong className="ec-val" data-font="data">
                {formatValue(key, getItemField(item, key))}
              </strong>
            </div>
          ))}
        </div>
        <div className="ec-summary-units">
          {unitFields.includes('suppliers') && (
            <div className="ec-unit-group">
              <div className="ec-group-title">供应商 ({suppliers.length})</div>
              {loading ? (
                <span className="ec-loading">加载中…</span>
              ) : (
                <div className="ec-unit-chips">
                  {suppliers.map((s) => (
                    <span className="ec-chip" key={s.name}>{s.name}</span>
                  ))}
                  {suppliers.length === 0 && <span className="ec-empty">暂无</span>}
                </div>
              )}
            </div>
          )}
          {unitFields.includes('labor_units') && (
            <div className="ec-unit-group">
              <div className="ec-group-title">劳务单位 ({laborUnits.length})</div>
              {loading ? (
                <span className="ec-loading">加载中…</span>
              ) : (
                <div className="ec-unit-chips">
                  {laborUnits.map((s) => (
                    <span className="ec-chip" key={s.name}>{s.name}</span>
                  ))}
                  {laborUnits.length === 0 && <span className="ec-empty">暂无</span>}
                </div>
              )}
            </div>
          )}
        </div>
        <button type="button" className="ec-expand-btn" onClick={onExpand}>
          展开详情 →
        </button>
      </div>
    );
  }

  // ===== 详情态 =====
  const allUnits = [...suppliers, ...laborUnits];
  return (
    <div className="expandable-card detail">
      <div className="ec-detail-list">
        {allUnits.map((u) => {
          const unpaid = (u.amount ?? 0) - (u.paid ?? 0);
          return (
            <div className="ec-unit-detail" key={u.name}>
              <div className="ec-unit-head">
                <strong>{u.name}</strong>
                <span className="ec-role-badge">{u.role}</span>
              </div>
              <div className="ec-kv-list">
                {detailFields.map((key) => {
                  let val: unknown;
                  if (key === 'contract_amount') val = u.amount;
                  else if (key === 'paid') val = u.paid;
                  else if (key === 'unpaid') val = unpaid;
                  else if (key === 'pay_nodes') val = '按进度节点支付'; // TODO: 从付款记录取
                  else val = (u as unknown as Record<string, unknown>)[key];
                  return (
                    <div className="kv-item" key={key}>
                      <span className="k">{FIELD_DICT[key]?.label || key}</span>
                      <strong className="v" data-font={FIELD_DICT[key]?.type === 'money' ? 'data' : undefined}>
                        {formatValue(key, val)}
                      </strong>
                    </div>
                  );
                })}
              </div>
            </div>
          );
        })}
        {allUnits.length === 0 && !loading && (
          <div className="ec-empty">暂无关联单位数据</div>
        )}
      </div>
    </div>
  );
}

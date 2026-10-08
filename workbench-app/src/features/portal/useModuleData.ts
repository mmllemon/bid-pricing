import { useEffect, useState } from 'react';
import { api } from '../../api/client';
import { getPortalConfig } from './portalConfig';
import { getBranches, getItems, type PortalItem } from './portalData';

/**
 * 模块数据接入（2026-10-08 真数据源）
 *
 * 配了 dataSource: "api:/path" 的模块，从接口取数并映射为 PortalItem；
 * 没配或取失败时，回退到 portalData.ts 静态数据。
 */

interface OverviewProject {
  id: string;
  name: string;
  short_name?: string;
  stage?: string;
  limit_total?: string | number;
  bid_amount?: string | number;
  bid_cost?: string | number;
  actual_cost?: string | number;
  bid_open_date?: string;
  created_at?: string;
  profit_margin?: string | number;
}

/** 把经营概览 API 的项目映射为 PortalItem */
function mapOverviewProject(p: OverviewProject, idx: number): PortalItem {
  const bidAmount = Number(p.bid_amount) || 0;
  const bidCost = Number(p.bid_cost) || 0;
  const margin = bidAmount > 0 ? ((bidAmount - bidCost) / bidAmount) * 100 : 0;
  return {
    id: p.id,
    code: `P-${String(idx + 1).padStart(2, '0')}`,
    title: p.name,
    stage: p.stage,
    bidAmount: String(p.bid_amount ?? ''),
    limitAmount: String(p.limit_total ?? ''),
    costBudget: String(p.actual_cost ?? p.bid_cost ?? ''),
    // 摘要字段（给 ExpandableCard 用）
    contract_amount: String(p.bid_amount ?? ''),
    start_date: p.bid_open_date || p.created_at || '',
    exec_cost: String(p.actual_cost ?? p.bid_cost ?? ''),
    profit_margin: margin.toFixed(1),
  } as PortalItem & Record<string, string>;
}

export function useModuleItems(modId: string | null, branchId: string | null) {
  const [items, setItems] = useState<PortalItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [fromApi, setFromApi] = useState(false);

  useEffect(() => {
    if (!modId) {
      setItems([]);
      setFromApi(false);
      return;
    }
    const cfg = getPortalConfig().modules.find((m) => m.id === modId);
    const ds = cfg?.dataSource;

    // 没配数据源：用静态数据
    if (!ds || !ds.startsWith('api:')) {
      setItems(branchId ? getItems(modId, branchId) : []);
      setFromApi(false);
      return;
    }

    // biz 模块：经营概览接口（projects 分支）
    if (modId === 'biz') {
      // overview 分支仍用静态；projects 分支走接口
      const branch = branchId || getBranches(modId)[0]?.id;
      if (branch !== 'projects') {
        setItems(getItems(modId, branch));
        setFromApi(false);
        return;
      }
      setLoading(true);
      api
        .request<{ projects: OverviewProject[] }>(ds.slice(4))
        .then((d) => {
          const list = (d.projects || []).map(mapOverviewProject);
          setItems(list);
          setFromApi(true);
        })
        .catch(() => {
          // 接口失败回退静态
          setItems(getItems(modId, branch));
          setFromApi(false);
        })
        .finally(() => setLoading(false));
      return;
    }

    // 其他模块：暂用静态
    setItems(branchId ? getItems(modId, branchId) : []);
    setFromApi(false);
  }, [modId, branchId]);

  return { items, loading, fromApi };
}

/**
 * 报价域 API 客户端（P3 前端整合）
 * 同源基址：浏览器只访问 :3456，报价域 /api/* 由 workbench-server 反代到 :8000（见 quoteProxy.ts）。
 * 与原生 app.js 的 API_BASE 语义一致，但统一走同源相对路径，不再硬编码端口。
 */
const BASE = '/api';

export interface QuotePreviewResult {
  status: string;
  reason?: string;
  cap: { rows: number; unit_works: Record<string, number>; hash_sha256?: string };
  cost: { rows: number; unit_works: Record<string, number>; hash_sha256?: string };
  match: { master_keys: number; matched: number; only_cap: number; only_cost: number; blocked?: boolean; only_cap_ids?: string[] };
  fields: Record<string, boolean>;
  optimizable_count: number;
  manual_count: number;
  missing_cap_ids: string[];
  missing_cost_ids: string[];
  duplicate_item_id_across_unit_work: string[];
  anomaly_count: number;
  anomalies: { kind: string; item_id: string }[];
  project_id?: string;
}

async function postForm<T>(path: string, form: FormData): Promise<T> {
  const r = await fetch(BASE + path, { method: 'POST', body: form });
  const text = await r.text().catch(() => '');
  let json: unknown = {};
  try { json = text ? JSON.parse(text) : {}; } catch { json = { status: 'ERROR', reason: text }; }
  if (!r.ok) {
    const reason = (json as { reason?: string; detail?: string })?.reason || (json as { detail?: string })?.detail || `HTTP ${r.status}`;
    throw new Error(reason);
  }
  return json as T;
}

/** 预览导入资料（限价 + 成本两个 xlsx）。 */
export function previewQuote(limitFile: File, costFile: File, projectId: string, projectName: string) {
  const data = new FormData();
  data.append('limit_file', limitFile);
  data.append('cost_file', costFile);
  data.append('project_id', projectId);
  data.append('project_name', projectName);
  return postForm<QuotePreviewResult>('/quote/preview', data);
}

/** 额度优化（方案 A/B/C）。返回体即完整 result（字段在顶层，无 result 嵌套）。 */
export function optimizeQuote(form: FormData) {
  return postForm<import('./quoteCalc').QuoteResult & { status: string; reason?: string; cost_input_tax?: { user_hint?: string } }>('/quote/optimize', form);
}

/** 项目经营概览列表（用于「关联投标项目」下拉）。 */
export interface OverviewProject {
  id: string; name: string; short_name?: string; stage?: string; bid_amount?: string; limit_total?: string;
}
export async function listOverviewProjects(): Promise<OverviewProject[]> {
  const r = await fetch(BASE + '/project/overview/list');
  const j = await r.json().catch(() => ({}));
  return Array.isArray(j?.projects) ? j.projects : [];
}

/** 定稿并回写项目经营概览（仅写投标报价金额）。 */
export function finalizeOverview(overviewId: string, bidAmount: string) {
  const data = new FormData();
  data.append('id', overviewId);
  data.append('bid_amount', bidAmount);
  return postForm<{ status: string; reason?: string }>('/project/overview/finalize', data);
}

/** 把当前方案标记为已定稿（write=0：不按方案存储值二次覆盖刚回写的金额）。 */
export async function markPlanFinalized(planId: string): Promise<void> {
  await fetch(`${BASE}/project/mark-finalized?id=${encodeURIComponent(planId)}&write=0`, { method: 'POST' }).catch(() => { /* 标记失败不阻断回写 */ });
}

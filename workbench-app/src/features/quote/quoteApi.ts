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

/* ==================== 方案组（/api/group/*） ==================== */

export interface StrategySlot {
  plan_id?: string | null;
  status?: string;
  summary?: {
    plan_id?: string; strategy?: string; saved_at?: string;
    target_total?: number; objective?: number; item_count?: number; competitive_budget?: number;
  };
}
export interface PlanGroup {
  group_id: string; group_name?: string; project_id?: string; project_name?: string;
  finalized?: boolean; strategy_slots?: Record<string, StrategySlot>;
}

function formData(pairs: Record<string, string>): FormData {
  const fd = new FormData();
  Object.entries(pairs).forEach(([k, v]) => fd.append(k, v));
  return fd;
}

/** 拉当前项目的方案组。 */
export async function listGroups(projectId: string): Promise<PlanGroup[]> {
  const r = await fetch(`${BASE}/group/list?project_id=${encodeURIComponent(projectId)}`);
  const j = await r.json().catch(() => ({}));
  return Array.isArray(j?.groups) ? j.groups : [];
}
export function renameGroup(groupId: string, name: string) { return postForm<{ status: string; reason?: string }>('/group/rename', formData({ group_id: groupId, name })); }
export function copyGroup(groupId: string) { return postForm<{ status: string; reason?: string; group?: { group_name?: string } }>('/group/copy', formData({ group_id: groupId })); }
export function finalizeGroup(groupId: string, on: boolean) { return postForm<{ status: string; reason?: string }>('/group/finalize', formData({ group_id: groupId, finalized: on ? '1' : '0' })); }
export function deleteGroup(groupId: string) { return postForm<{ status: string; reason?: string }>('/group/delete', formData({ group_id: groupId })); }

/** 按 id 取方案（含 params / result / preview）。 */
export interface PlanRecord {
  id: string; name?: string; group_id?: string; project_id?: string;
  params?: Record<string, unknown>; result?: import('./quoteCalc').QuoteResult | null;
  preview?: unknown;
}
export async function getPlan(id: string): Promise<PlanRecord | null> {
  const r = await fetch(`${BASE}/project/get?id=${encodeURIComponent(id)}`);
  const j = await r.json().catch(() => ({}));
  return j?.status === 'PASS' ? j.plan : null;
}

/** 按当前参数重算指定方案。 */
export function recomputePlan(planId: string, form: FormData) {
  return postForm<import('./quoteCalc').QuoteResult & { status: string; reason?: string }>(`/project/recompute?id=${encodeURIComponent(planId)}`, form);
}

/* ==================== 多方案对比（/api/project/compare） ==================== */

export interface CompareResult {
  status: string; reason?: string;
  plan_ids?: string[]; base_id?: string; project?: string;
  summary?: Record<string, unknown>[];
  price_diffs?: Record<string, { item_name?: string; base_price?: number; deltas: Record<string, number | null> }>;
}
export function comparePlans(ids: string[], base?: string) {
  const fd = new FormData();
  fd.append('id', ids.join(','));
  if (base) fd.append('base', base);
  return postForm<CompareResult>('/project/compare', fd);
}

/* ==================== 审计日志（/api/audit/list） ==================== */

export interface AuditRow {
  ts?: string; action?: string; status?: string;
  project_id?: string; plan_id?: string; detail?: unknown;
}
export async function listAudit(limit = 100): Promise<AuditRow[]> {
  const r = await fetch(`${BASE}/audit/list?limit=${limit}`);
  const j = await r.json().catch(() => ({}));
  if (j?.status !== 'PASS') throw new Error(j?.reason || '读取失败');
  return Array.isArray(j.audit) ? j.audit : [];
}

/**
 * bid-pricing agent-service — Pi Durable 边车服务
 *
 * 能力：
 *   · 持久化 agent（SQLite 存储，崩溃重启自动接上）
 *   · 工具：list_projects / list_project_overviews / get_project_detail /
 *     recompute_plan（审批门控）/ run_calculation（审批门控）/ set_reminder / list_reminders
 *   · 审批：副作用工具执行前挂起等待人工批准（SSE 推送 + POST /approve），
 *     决定写进 durable memo，崩溃重跑不会重复问
 *   · 提醒：后台持久任务（重启存活），到点把提醒消息作为 follow-up 投回会话
 *   · 模型：默认跟随 ~/.pi/agent/models.json（PI_PROVIDER/PI_MODEL），
 *     前端可 POST /apply-model 自定义模型（OpenAI 兼容端点），持久化到 agent-model-config.json
 *
 * 环境变量：AGENT_PORT(8010) / BACKEND_URL(http://127.0.0.1:8000) / AGENT_SQLITE(./agent.sqlite)
 */

import http from "node:http";
import path from "node:path";
import fs from "node:fs";
import os from "node:os";
import { fileURLToPath } from "node:url";

import { BACKGROUND_CONTEXT } from "@earendil-works/chord/context";
import { createModels, createProvider } from "@earendil-works/pi-ai/models";
import { openaiProvider } from "@earendil-works/pi-ai/providers/openai";
import { openAICompletionsApi } from "@earendil-works/pi-ai/api/openai-completions.lazy";
import { Type } from "@earendil-works/pi-ai";
import {
  Harness,
  createRegistry,
  defineExtension,
  defineTool,
  defineTask,
  defineDoc,
  section,
  hook,
  ToolTask,
  AssistantEntry,
} from "@earendil-works/pi-durable";
import { openNodeSqliteStorage } from "@earendil-works/pi-durable/storage/sqlite/node";

const ctx = BACKGROUND_CONTEXT;
const PORT = Number(process.env.AGENT_PORT ?? 8010);
// P0-1: 默认只监听回环地址（防局域网/公网直连）；如需对外暴露，用 AGENT_HOST 显式覆盖
const AGENT_HOST = process.env.AGENT_HOST || "127.0.0.1";
const BACKEND = (process.env.BACKEND_URL ?? "http://127.0.0.1:8000").replace(/\/$/, "");
const SQLITE_FILE = path.resolve(process.env.AGENT_SQLITE ?? path.join(path.dirname(fileURLToPath(import.meta.url)), "agent.sqlite"));
const MODEL_CONFIG_FILE = path.join(path.dirname(fileURLToPath(import.meta.url)), "agent-model-config.json");
// P0-1: 边车自身鉴权。AGENT_API_TOKEN 优先，回退 BIDPRICING_API_TOKEN（与 FastAPI 同语义）。
// 未设置时保持本地零配置可用（启动时打印告警）；设置后 /approve、/apply-model、/watch 必须携带。
const AGENT_TOKEN = process.env.AGENT_API_TOKEN || process.env.BIDPRICING_API_TOKEN || "";
// P0-1: CORS 只放行本机来源（localhost/127.0.0.1 任意端口）；无 Origin 的直连（curl/同机脚本）不设 ACAO。
const LOCAL_ORIGIN_RE = /^https?:\/\/(localhost|127\.0\.0\.1)(:\d+)?$/;
function corsAllowOrigin(req) {
  const o = req.headers.origin;
  if (!o) return null;
  return LOCAL_ORIGIN_RE.test(o) ? o : null;
}
function agentTokenOk(req) {
  if (!AGENT_TOKEN) return true;
  const h = req.headers["x-api-token"] || "";
  const az = req.headers["authorization"] || "";
  const q = new URL(req.url, "http://x").searchParams.get("token") || "";
  return h === AGENT_TOKEN || az === `Bearer ${AGENT_TOKEN}` || q === AGENT_TOKEN;
}

// ---------------------------------------------------------------------------
// 模型：models.json 的所有 provider + 前端自定义 provider
// ---------------------------------------------------------------------------
function loadModelsJson() {
  for (const file of [process.env.PI_MODELS_JSON, path.join(os.homedir(), ".pi", "agent", "models.json")]) {
    if (file) { try { const d = JSON.parse(fs.readFileSync(file, "utf8")); if (d?.providers) return d.providers; } catch {} }
  }
  return {};
}

function registerProvider(models, id, def) {
  models.setProvider(createProvider({
    id,
    name: def.name ?? id,
    baseUrl: def.baseUrl,
    auth: { apiKey: { name: `${id} API key`, resolve: async () => ({ auth: { apiKey: def.apiKey }, source: id }) } },
    models: (def.models ?? []).map((m) => ({
      id: m.id,
      name: m.name ?? m.id,
      api: m.api ?? "openai-completions",
      provider: id,
      baseUrl: m.baseUrl ?? def.baseUrl,
      input: m.input ?? ["text"],
      reasoning: Boolean(m.reasoning),
      contextWindow: m.contextWindow ?? 128000,
      maxTokens: m.maxTokens ?? 8192,
      cost: m.cost ?? { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
    })),
    api: { "openai-completions": openAICompletionsApi() },
  }));
}

const modelsJsonProviders = loadModelsJson();
const models = createModels();
models.setProvider(openaiProvider());
for (const [id, def] of Object.entries(modelsJsonProviders)) {
  if (def?.baseUrl && def?.apiKey) registerProvider(models, id, def);
}

// 前端自定义模型（agent-model-config.json）
function loadModelConfig() {
  try { return JSON.parse(fs.readFileSync(MODEL_CONFIG_FILE, "utf8")); } catch { return {}; }
}
function saveModelConfig(cfg) { fs.writeFileSync(MODEL_CONFIG_FILE, JSON.stringify(cfg, null, 2)); }

function applyCustomProvider(cfg) {
  if (!cfg?.custom?.id || !cfg.custom.baseUrl) return;
  registerProvider(models, cfg.custom.id, {
    baseUrl: cfg.custom.baseUrl,
    apiKey: cfg.custom.apiKey,
    models: cfg.custom.models ?? [{ id: cfg.active?.model ?? cfg.custom.id }],
  });
}
applyCustomProvider(loadModelConfig());

// 当前激活模型：config.active > 前端自定义 > PI_PROVIDER/PI_MODEL > models.json 第一个
const modelConfig = loadModelConfig();
const PI_PROVIDER = process.env.PI_PROVIDER ?? "agnes";
const PI_MODEL = process.env.PI_MODEL;
let ACTIVE = { provider: null, model: null };
function pickDefaultModel() {
  for (const [id, def] of Object.entries(modelsJsonProviders)) {
    const m = PI_MODEL && def?.models?.some((x) => x.id === PI_MODEL) ? PI_MODEL : def?.models?.[0]?.id;
    if (id === PI_PROVIDER && m) return { provider: id, model: m };
  }
  const first = Object.keys(modelsJsonProviders)[0];
  if (first && modelsJsonProviders[first]?.models?.[0]?.id) return { provider: first, model: modelsJsonProviders[first].models[0].id };
  return { provider: null, model: null };
}
if (modelConfig.active?.provider && modelConfig.active.model) {
  ACTIVE = { provider: modelConfig.active.provider, model: modelConfig.active.model };
} else {
  ACTIVE = pickDefaultModel();
}

function modelAvailable() {
  if (!ACTIVE.provider || !ACTIVE.model) return false;
  return Boolean(models.getModel(ACTIVE.provider, ACTIVE.model));
}

// ---------------------------------------------------------------------------
// 后端 API 访问
// ---------------------------------------------------------------------------
async function backendFetch(pathname, options) {
  // P0-3: 边车调 FastAPI 时透传 token（与 api/app.py 的 BIDPRICING_API_TOKEN 语义一致）
  const headers = { ...(options && options.headers) };
  if (process.env.BIDPRICING_API_TOKEN && !headers["X-API-Token"] && !headers["x-api-token"]) {
    headers["X-API-Token"] = process.env.BIDPRICING_API_TOKEN;
  }
  const res = await fetch(BACKEND + pathname, { ...options, headers });
  const text = await res.text();
  let body;
  try { body = JSON.parse(text); } catch { body = text; }
  if (!res.ok) throw new Error(`backend ${res.status}: ${String(body).slice(0, 500)}`);
  return body;
}
function trimmed(data, max = 6000) {
  const text = JSON.stringify(data, null, 1);
  return text.length > max ? text.slice(0, max) + `\n…(已截断，完整结果见后端日志)` : text;
}

// ---------------------------------------------------------------------------
// 审批门（副作用工具：run_calculation / recompute_plan）
// ---------------------------------------------------------------------------
const GATED_TOOLS = new Set(["run_calculation", "recompute_plan"]);
const pendingApprovals = new Map(); // key -> { resolve, info, settled }
const approvalSubs = new Set(); // SSE 客户端
const APPROVAL_TIMEOUT_MS = 15 * 60 * 1000;

// key 与 hook 里生成规则一致：`${taskId}:${tool}`；resolver 注册表供 /approve 与超时使用
const approvalResolvers = new Map(); // key -> (allow:boolean) => void

function requestApproval(key, info) {
  return new Promise((resolve) => {
    const entry = { info, settled: false };
    pendingApprovals.set(key, entry);
    approvalResolvers.set(key, (allow) => {
      if (entry.settled) return;
      entry.settled = true;
      pendingApprovals.delete(key);
      approvalResolvers.delete(key);
      resolve(allow);
    });
    for (const client of approvalSubs) {
      try { client.write(`data: ${JSON.stringify({ type: "approval_request", key, ...info })}\n\n`); } catch {}
    }
    setTimeout(() => {
      const finish = approvalResolvers.get(key);
      if (finish) finish(false); // 超时 = 拒绝
    }, APPROVAL_TIMEOUT_MS);
  });
}

function decideApproval(key, allow) {
  const finish = approvalResolvers.get(key);
  if (!finish) return false;
  finish(allow);
  for (const client of approvalSubs) {
    try { client.write(`data: ${JSON.stringify({ type: "approval_decided", key, allow })}\n\n`); } catch {}
  }
  return true;
}

const ApprovalGate = defineExtension({
  name: "approval-gate",
  hooks: [
    hook(ToolTask, {
      beforeTool: async (call, api, context) => {
        if (!GATED_TOOLS.has(call.name)) return undefined;
        // memo 决定持久化在任务上：崩溃重跑直接沿用上次的人工决定
        let decided = await api.memo(`approval:${call.name}`, context);
        if (decided === undefined) {
          const key = `${String(api.taskId)}:${call.name}`;
          decided = await requestApproval(key, {
            tool: call.name,
            args: call.arguments,
            taskId: String(api.taskId),
            at: new Date().toISOString(),
          });
          decided = await api.memo(`approval:${call.name}`, decided, context);
        }
        if (decided) return undefined;
        return { block: `工具 ${call.name} 未获用户批准，本次调用被拦截。请向用户说明该操作需要确认，不要自动重试。` };
      },
    }),
  ],
});

// ---------------------------------------------------------------------------
// 持久提醒（后台任务，重启存活）
// ---------------------------------------------------------------------------
const ReminderTask = defineTask({
  name: "app.reminder",
  version: 1,
  initial: () => ({ phase: "wait" }),
  phases: {
    wait: async (task, runtime, c) => {
      await runtime.sleep(task.input.at, c); // durable 定时器
      await runtime.commit(() => ({ status: "terminal", outcome: { status: "completed", result: task.input.message } }), c);
    },
  },
  abort: (_task, runtime, c) =>
    runtime.commit(() => ({ status: "terminal", outcome: { status: "aborted" } }), c),
});

const ReminderDeliver = defineTask({
  name: "app.reminder-deliver",
  version: 1,
  initial: () => ({ phase: "wait" }),
  phases: {
    wait: async (task, runtime, c) => {
      // 等待提醒任务到点；崩溃重启后从检查点续等
      await runtime.commit(
        () => ({ status: "waiting", checkpoint: { phase: "deliver" }, on: [task.input.reminderId], policy: "allSettled" }),
        c,
      );
    },
    deliver: async (task, runtime, c) => {
      const main = await runtime.conversation(runtime.conversationId, c);
      if (!main) {
        await runtime.commit(() => ({ status: "terminal", outcome: { status: "failed", error: { message: "conversation handle lost after restart" } } }), c);
        return;
      }
      await main.submit(
        {
          type: "input",
          content: `⏰ 提醒：${task.input.message}`,
          requestId: `reminder:${task.id}`,
          whenBusy: "followUp",
        },
        c,
      );
      await runtime.commit(() => ({ status: "terminal", outcome: { status: "completed", result: null } }), c);
    },
  },
  abort: (_task, runtime, c) =>
    runtime.commit(() => ({ status: "terminal", outcome: { status: "aborted" } }), c),
});

const RemindersDoc = defineDoc({
  kind: "app.reminders",
  version: 1,
  scope: "conversation",
  history: "latest",
  fork: "current",
  initial: () => ({ reminders: [] }),
});

// ---------------------------------------------------------------------------
// 工具
// ---------------------------------------------------------------------------
const listProjects = defineTool({
  name: "list_projects",
  description: "List all saved bid-pricing project plan groups (read-only). Returns project ids, names, strategies, targets.",
  parameters: Type.Object({}),
  replay: "safe",
  execute: async () => {
    const data = await backendFetch("/api/project/list", { method: "GET" });
    return { content: [{ type: "text", text: trimmed(data) }] };
  },
});

const listOverviews = defineTool({
  name: "list_project_overviews",
  description: "List saved business overviews (经营概览) with project ids (read-only).",
  parameters: Type.Object({}),
  replay: "safe",
  execute: async () => {
    const data = await backendFetch("/api/project/overview/list", { method: "GET" });
    return { content: [{ type: "text", text: trimmed(data) }] };
  },
});

const getProjectDetail = defineTool({
  name: "get_project_detail",
  description: "Get full details of one saved plan by plan_id: params, items, results, status (read-only).",
  parameters: Type.Object({ plan_id: Type.String({ description: "The plan id (from list_projects)" }) }),
  replay: "safe",
  execute: async (args) => {
    const data = await backendFetch(`/api/project/get?id=${encodeURIComponent(args.plan_id)}`, { method: "GET" });
    if (data.status !== "PASS") {
      return { content: [{ type: "text", text: JSON.stringify(data).slice(0, 1000) }], isError: true };
    }
    const plan = data.plan ?? {};
    const slim = {
      id: plan.id,
      name: plan.name,
      project_name: plan.project_name,
      params: plan.params,
      preview: plan.preview ? { cap: plan.preview.cap?.name ?? null, cost: plan.preview.cost?.name ?? null } : null,
      result: plan.result,
      saved_at: plan.saved_at,
    };
    return { content: [{ type: "text", text: trimmed(slim, 8000) }] };
  },
});

/** 有副作用：写方案库 + 持久化重算结果。审批门控 + 不声明 replay safe。 */
const recomputePlan = defineTool({
  name: "recompute_plan",
  description:
    "Re-run the MILP solve for a saved plan and persist the new result (side effect, needs user approval). " +
    "Keep the plan's stored parameters unless the user explicitly overrides target_total or strategy.",
  parameters: Type.Object({
    plan_id: Type.String({ description: "Plan id to recompute" }),
    target_total: Type.Number({ description: "Target total quote amount in CNY" }),
    strategy: Type.Optional(Type.String({ description: "Quote strategy, e.g. optimal / uniform (default: the plan's stored strategy)" })),
    vat_rate: Type.Optional(Type.Number({ description: "VAT rate, default 0.09" })),
    ratio_min: Type.Optional(Type.Number({ description: "Min scaling ratio, default 0.5" })),
    ratio_max: Type.Optional(Type.Number({ description: "Max scaling ratio, default 1.0" })),
  }),
  execute: async (args, api) => {
    api.output(`recomputing plan ${args.plan_id} ...\n`);
    const form = new URLSearchParams();
    form.append("target_total", String(args.target_total));
    if (args.strategy) form.append("strategy", args.strategy);
    if (args.vat_rate !== undefined) form.append("vat_rate", String(args.vat_rate));
    if (args.ratio_min !== undefined) form.append("ratio_min", String(args.ratio_min));
    if (args.ratio_max !== undefined) form.append("ratio_max", String(args.ratio_max));
    const data = await backendFetch("/api/project/recompute", { method: "POST", body: form });
    if (data.status !== "PASS") {
      return { content: [{ type: "text", text: JSON.stringify(data).slice(0, 2000) }], isError: true };
    }
    return {
      content: [{ type: "text", text: `status=PASS strategy=${data.strategy ?? "optimal"}\n` + trimmed(data, 8000) }],
    };
  },
});

/** 有副作用：提交两个 xlsx 并持久化方案。审批门控 + 不声明 replay safe。 */
const runCalculation = defineTool({
  name: "run_calculation",
  description:
    "Run a new quote optimization on the backend: uploads limit_file + cost_file (xlsx paths on this machine) and persists a plan (side effect, needs user approval).",
  parameters: Type.Object({
    limit_file: Type.String({ description: "Absolute path to the limit/cap (限额) xlsx file" }),
    cost_file: Type.String({ description: "Absolute path to the cost (成本) xlsx file" }),
    target_total: Type.Number({ description: "Target total quote amount in CNY" }),
    project_name: Type.Optional(Type.String({ description: "Project display name" })),
    strategy: Type.Optional(Type.String({ description: "Quote strategy, default 'optimal'" })),
    vat_rate: Type.Optional(Type.Number({ description: "VAT rate, default 0.09" })),
    surtax_rate: Type.Optional(Type.Number({ description: "Surtax rate, default 0.12" })),
    ratio_min: Type.Optional(Type.Number({ description: "Min ratio, default 0.5" })),
    ratio_max: Type.Optional(Type.Number({ description: "Max ratio, default 1.0" })),
  }),
  execute: async (args, api) => {
    api.output(`uploading ${args.limit_file} + ${args.cost_file} ...\n`);
    const form = new FormData();
    form.append("limit_file", new Blob([fs.readFileSync(args.limit_file)]), path.basename(args.limit_file));
    form.append("cost_file", new Blob([fs.readFileSync(args.cost_file)]), path.basename(args.cost_file));
    form.append("target_total", String(args.target_total));
    form.append("project_name", args.project_name ?? "");
    form.append("strategy", args.strategy ?? "optimal");
    form.append("vat_rate", String(args.vat_rate ?? 0.09));
    form.append("surtax_rate", String(args.surtax_rate ?? 0.12));
    form.append("ratio_min", String(args.ratio_min ?? 0.5));
    form.append("ratio_max", String(args.ratio_max ?? 1.0));
    api.output("calculating (MILP solve)...\n");
    const data = await backendFetch("/api/quote/optimize", { method: "POST", body: form });
    if (data.status !== "PASS") {
      return { content: [{ type: "text", text: JSON.stringify(data).slice(0, 2000) }], isError: true };
    }
    return { content: [{ type: "text", text: `status=PASS plan_id=${data.plan_id}\n` + trimmed(data, 8000) }] };
  },
});

const setReminder = defineTool({
  name: "set_reminder",
  description:
    "Set a durable reminder: at the given time a message is posted back into this conversation. " +
    "Survives process restarts. Give either 'at' (ISO time) or 'in_minutes'.",
  parameters: Type.Object({
    message: Type.String({ description: "What to remind about, short" }),
    at: Type.Optional(Type.String({ description: "ISO time, e.g. 2026-10-08T09:00:00" })),
    in_minutes: Type.Optional(Type.Number({ description: "Or a relative delay in minutes" })),
  }),
  replay: "safe",
  execute: async (args, api, c) => {
    let at;
    if (args.at) at = new Date(args.at).getTime();
    else if (args.in_minutes) at = Date.now() + args.in_minutes * 60_000;
    else return { content: [{ type: "text", text: "需要 at（ISO 时间）或 in_minutes" }], isError: true };
    if (Number.isNaN(at) || at < Date.now()) return { content: [{ type: "text", text: "时间无效（须为未来时间）" }], isError: true };
    const ids = await api.commit(async (tx) => {
      const reminderId = await tx.createTask(
        ReminderTask,
        { message: args.message, at },
        { ownership: { kind: "conversation" }, conversationId: api.conversationId, background: true },
      );
      const deliverId = await tx.createTask(
        ReminderDeliver,
        { message: args.message, reminderId },
        { ownership: { kind: "conversation" }, conversationId: api.conversationId, background: true },
      );
      const doc = await tx.doc(RemindersDoc, api.conversationId);
      doc.reminders.push({ id: String(reminderId), message: args.message, at, created_at: new Date().toISOString() });
      return { reminderId, deliverId };
    }, c);
    api.details({ reminder: ids.reminderId, deliver: ids.deliverId }, c);
    return {
      content: [{ type: "text", text: `已设置提醒：${new Date(at).toLocaleString("zh-CN")} —— "${args.message}"（服务重启也不丢失）` }],
    };
  },
});

const listReminders = defineTool({
  name: "list_reminders",
  description: "List durable reminders set in this conversation (read-only).",
  parameters: Type.Object({}),
  replay: "safe",
  execute: async (_args, api, c) => {
    const doc = await api.commit((tx) => tx.doc(RemindersDoc, api.conversationId), c);
    const lines = doc.reminders
      .map((r) => `- ${new Date(r.at).toLocaleString("zh-CN")}  ${r.message}`)
      .join("\n");
    return { content: [{ type: "text", text: lines || "（暂无提醒）" }] };
  },
});

// ---------------------------------------------------------------------------
// 注册扩展
// ---------------------------------------------------------------------------
const BidPricing = defineExtension({
  name: "bid-pricing",
  sections: [
    section("role", () =>
      "你是投标报价测算助手。工具：查询项目方案与经营概览（list_projects / list_project_overviews / get_project_detail）、" +
      "重算已存方案（recompute_plan，需用户批准）、新测算（run_calculation，需用户批准）、" +
      "设置与查询持久提醒（set_reminder / list_reminders）。回答用中文，关键数字（目标总价、报价、利润、税率口径）必须来自工具返回，" +
      "不要凭空编造。需要批准的操作被拦截时，明确告诉用户去界面点批准。",
    ),
  ],
});

const registry = createRegistry();
registry.install(BidPricing);
registry.install(ApprovalGate);
registry.install(defineExtension({
  name: "bid-tools",
  tools: [listProjects, listOverviews, getProjectDetail, recomputePlan, runCalculation, setReminder, listReminders],
}));

// ---------------------------------------------------------------------------
// 打开持久化 harness
// ---------------------------------------------------------------------------
const storage = await openNodeSqliteStorage(SQLITE_FILE);
const harness = await Harness.open(storage, { models, registry }, ctx);
harness.resume(); // 接上上个进程没跑完的工作
const root = await harness.root(ctx, { agent: { model: { provider: ACTIVE.provider, modelId: ACTIVE.model } } });
if (ACTIVE.provider && ACTIVE.model) {
  await root.configure({ model: { provider: ACTIVE.provider, modelId: ACTIVE.model } }, ctx);
}

// ---------------------------------------------------------------------------
// HTTP 接口
// ---------------------------------------------------------------------------
function assistantText(entry) {
  const msg = entry?.model?.[0];
  return (msg?.content ?? []).filter((c) => c.type === "text").map((c) => c.text).join("\n");
}

function readBody(req) {
  return new Promise((resolve, reject) => {
    let data = "";
    req.on("data", (c) => (data += c));
    req.on("end", () => {
      try { resolve(data ? JSON.parse(data) : {}); }
      catch (e) { reject(e); }
    });
    req.on("error", reject);
  });
}

function send(res, code, obj) {
  res.statusCode = code;
  res.setHeader("content-type", "application/json; charset=utf-8");
  res.end(JSON.stringify(obj, null, 2));
}

function listAvailableModels() {
  const out = [];
  for (const p of models.getProviders()) {
    if (!p.getModels()) continue;
    const list = p.getModels().filter((m) => !m.type || m.type === "chat");
    if (list.length) out.push({ provider: p.id, models: list.map((m) => m.id) });
  }
  return out;
}

function summarizeView(view) {
  if (!view) return null;
  const docs = view.docs ?? {};
  return {
    entries: (view.entries ?? []).length,
    live: docs["pi.live"] ?? null,
    inbox: docs["pi.inbox"] ?? null,
    agent: docs["pi.agent"] ?? null,
    usage: docs["pi.usage"] ?? null,
  };
}

const watchClients = new Set();
let watchHandle = null;
let latestView = null;

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, "http://x");
  // P0-1: CORS 收敛到本机白名单（替代原来的 *）；预检需放行 x-api-token / authorization
  const allowOrigin = corsAllowOrigin(req);
  if (allowOrigin) {
    res.setHeader("Access-Control-Allow-Origin", allowOrigin);
    res.setHeader("Vary", "Origin");
  }
  res.setHeader("Access-Control-Allow-Headers", "content-type, x-api-token, authorization");
  if (req.method === "OPTIONS") return res.writeHead(204).end();

  try {
    if (req.method === "GET" && url.pathname === "/health") {
      return send(res, 200, {
        ok: true,
        storage: SQLITE_FILE,
        backend: BACKEND,
        provider: ACTIVE.provider,
        model: ACTIVE.model,
        model_available: modelAvailable(),
        pending_approvals: pendingApprovals.size,
      });
    }

    if (req.method === "GET" && url.pathname === "/usage") {
      return send(res, 200, await harness.usage(ctx));
    }

    // ---- 模型配置（自定义模型设置页）----
    if (req.method === "GET" && url.pathname === "/model-config") {
      return send(res, 200, {
        active: ACTIVE,
        custom: loadModelConfig().custom ?? null,
        available: listAvailableModels(),
      });
    }

    if (req.method === "POST" && url.pathname === "/apply-model") {
      // P0-1: 自定义模型可改 baseUrl（后续请求外泄风险），需鉴权
      if (!agentTokenOk(req)) return send(res, 403, { error: "agent token 缺失或不正确（X-API-Token / Authorization: Bearer / ?token=）" });
      const body = await readBody(req);
      const provider = String(body.provider ?? "").trim();
      const modelId = String(body.model ?? "").trim();
      if (!provider || !modelId) return send(res, 400, { error: "provider 与 model 必填" });
      const cfg = loadModelConfig();
      // 内置/models.json 的 provider 直接可用；自定义 provider 需要 baseUrl+apiKey
      if (!models.getModel(provider, modelId)) {
        const def = modelsJsonProviders[provider] ?? (cfg.custom?.id === provider ? cfg.custom : undefined);
        if (!def?.baseUrl || !def?.apiKey) {
          return send(res, 400, { error: `未知模型 ${provider}/${modelId}：自定义 provider 需要 baseUrl 与 apiKey` });
        }
      }
      // 自定义端点（既不在 models.json 也不是内置 openai）→ 持久化 + 注册
      if (!modelsJsonProviders[provider] && provider !== "openai") {
        const custom = {
          id: provider,
          baseUrl: String(body.baseUrl ?? cfg.custom?.baseUrl ?? "").replace(/\/$/, ""),
          apiKey: String(body.apiKey ?? cfg.custom?.apiKey ?? ""),
          name: String(body.name ?? provider),
          models: [modelId],
        };
        if (!custom.baseUrl || !custom.apiKey) return send(res, 400, { error: "自定义 provider 需要 baseUrl 与 apiKey" });
        cfg.custom = custom;
        applyCustomProvider(cfg);
      }
      cfg.active = { provider, model: modelId };
      saveModelConfig(cfg);
      ACTIVE = { provider, model: modelId };
      await root.configure({ model: { provider, modelId } }, ctx);

      let test = undefined;
      if (body.test) {
        const sub = await root.submit({ type: "input", content: "只回复两个字：好的", requestId: `model-test:${Date.now()}` }, ctx);
        const settled = await sub.wait(ctx);
        test = settled.status === "done" ? "pong" : `failed: ${JSON.stringify(settled.reason ?? settled.status)}`;
      }
      return send(res, 200, { ok: true, active: ACTIVE, test });
    }

    // ---- 审批 ----
    if (req.method === "POST" && url.pathname === "/approve") {
      // P0-1: 审批直接放行副作用工具执行，需鉴权
      if (!agentTokenOk(req)) return send(res, 403, { error: "agent token 缺失或不正确（X-API-Token / Authorization: Bearer）" });
      const body = await readBody(req);
      const ok = decideApproval(String(body.key ?? ""), Boolean(body.allow));
      return send(res, 200, { ok });
    }

    // ---- GET /watch (SSE) ----
    if (req.method === "GET" && url.pathname === "/watch") {
      // P0-1: /watch 会推送 approval_request（含审批 key），嗅探后可伪造审批，需鉴权（SSE 只能用 ?token=）
      if (!agentTokenOk(req)) return send(res, 403, { error: "agent token 缺失或不正确（?token=）" });
      res.writeHead(200, {
        "content-type": "text/event-stream",
        "cache-control": "no-cache",
        connection: "keep-alive",
      });
      approvalSubs.add(res);
      if (!watchHandle) {
        watchHandle = await root.watch(ctx);
        latestView = watchHandle.value;
        watchHandle.start(async (value, ops) => {
          latestView = value;
          for (const client of watchClients) client.write(`data: ${JSON.stringify({ type: "frame", ops })}\n\n`);
        });
      }
      res.write(`data: ${JSON.stringify({ type: "snapshot", value: summarizeView(latestView) })}\n\n`);
      // 补推当前挂起的审批（新接入的客户端也能看到）
      for (const [key, entry] of pendingApprovals) {
        if (!entry.settled) res.write(`data: ${JSON.stringify({ type: "approval_request", key, ...entry.info })}\n\n`);
      }
      watchClients.add(res);
      req.on("close", () => {
        watchClients.delete(res);
        approvalSubs.delete(res);
      });
      return;
    }

    // ---- POST /submit ----
    if (req.method === "POST" && url.pathname === "/submit") {
      const { content, requestId, whenBusy } = await readBody(req);
      if (typeof content !== "string" || !content.trim()) return send(res, 400, { error: "content (string) required" });
      if (!modelAvailable()) {
        return send(res, 503, { error: `模型 ${ACTIVE.provider}/${ACTIVE.model} 不可用：请在设置页选择或配置一个可用模型` });
      }
      const started = Date.now();
      const submission = await root.submit({ type: "input", content: content.trim(), requestId, whenBusy }, ctx);
      const settled = await submission.wait(ctx);
      console.log(`[submit] settled=`, JSON.stringify(settled));
      if (settled.status === "done" && settled.type === "input") {
        const entry = await root.commit((tx) => tx.entry(AssistantEntry, settled.answer), ctx);
        return send(res, 200, {
          status: "done",
          answer: assistantText(entry),
          submission_id: submission.id,
          elapsed_ms: Date.now() - started,
        });
      }
      return send(res, 200, {
        status: settled.status ?? "unanswered",
        reason: settled.reason !== undefined ? JSON.stringify(settled.reason) : String(settled).slice(0, 500),
        submission_id: submission.id,
      });
    }

    // ---- GET /status/<submissionId> ----
    if (req.method === "GET" && url.pathname.startsWith("/status/")) {
      const id = decodeURIComponent(url.pathname.slice("/status/".length));
      const submission = await harness.submission(id, ctx);
      return send(res, 200, { id, found: Boolean(submission), hint: "进度请看 /watch（SSE）" });
    }

    return send(res, 404, { error: `no route: ${req.method} ${url.pathname}` });
  } catch (err) {
    console.error(`[agent-service] ${req.method} ${url.pathname} failed:`, err);
    if (!res.headersSent) return send(res, 500, { error: String(err?.message ?? err) });
    res.end();
  }
});

server.listen(PORT, AGENT_HOST, () => {
  console.log(`[agent-service] listening on ${AGENT_HOST}:${PORT}`);
  console.log(`[agent-service] storage=${SQLITE_FILE}`);
  console.log(`[agent-service] backend=${BACKEND} model=${ACTIVE.provider}/${ACTIVE.model} available=${modelAvailable()}`);
  console.log(`[agent-service] 门控工具：${[...GATED_TOOLS].join(", ")}（执行前需 /approve）`);
  if (!AGENT_TOKEN) {
    console.log("[agent-service] 安全提示：AGENT_API_TOKEN 未设置，/approve、/apply-model、/watch 无鉴权；" +
      "当前仅靠回环监听 + 本机 CORS 白名单保护。如需对外暴露或加固，设置 AGENT_API_TOKEN（前端面板设置里填同一值）。");
  }
});

process.on("SIGINT", async () => {
  console.log("\n[agent-service] shutting down（后台任务与提醒会在下次启动时自动恢复）…");
  try { await harness.close(ctx); } finally { server.close(); process.exit(0); }
});

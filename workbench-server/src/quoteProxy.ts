/**
 * 报价域反代（P0-2 · 前端整合）
 *
 * 背景：本项目现有两个后端进程——
 *   :8000  api/（FastAPI）  报价/项目/方案组/井库/审计  ← 本模块的目标
 *   :3456  workbench-server（Express）待办/财务/热点/知识/扫描/设置 + agent
 * 前端整合后浏览器只访问 :3456，故 :3456 需把报价域的 /api/* 同源反代到 :8000。
 *
 * 分流边界（两边零重叠，已逐条核对）：
 *   报价域前缀：quote / project / group / well-library / audit / metal-prices
 *   工作台前缀：finance / health / hotspots / knowledge / productivity / scan / settings / todos / weather / xhs
 *
 * 实现选择：用 Node 内置 fetch（Node 24 内置），不引入 http-proxy 依赖。
 * 注意：
 *   1) 必须挂在 express.json() 之前 —— 否则 JSON 请求体已被消费，转发时为空。
 *      本模块自行以原始流读取 body 转发（兼容 JSON 与 multipart FormData）。
 *   2) 上游地址由 BIDPRICING_UPSTREAM 覆盖，默认 http://127.0.0.1:8000。
 *   3) 上游不可达时返回 502 并给出可读原因，不吞错。
 */
import type { Request, Response, NextFunction, Express } from 'express';

const UPSTREAM = process.env.BIDPRICING_UPSTREAM || 'http://127.0.0.1:8000';

/** 报价域路径前缀（第一段），命中即转发到上游。 */
const QUOTE_PREFIXES = new Set([
  'quote',
  'project',
  'group',
  'well-library',
  'audit',
  'metal-prices',
]);

/** 判断某个 /api/<seg>/... 是否属于报价域。 */
export function isQuotePath(pathname: string): boolean {
  const m = /^\/api\/([^/?#]+)/.exec(pathname);
  if (!m) return false;
  return QUOTE_PREFIXES.has(m[1]);
}

/** 读取原始请求体为 Buffer（JSON 与 multipart 通用）。 */
function readRawBody(req: Request): Promise<Buffer> {
  return new Promise((resolveBody, reject) => {
    const chunks: Buffer[] = [];
    req.on('data', (c: Buffer) => chunks.push(c));
    req.on('end', () => resolveBody(Buffer.concat(chunks)));
    req.on('error', reject);
  });
}

/**
 * 注册报价域反代。必须在 express.json() 之前调用（见文件头注释 1）。
 */
export function registerQuoteProxy(app: Express): void {
  app.use('/api', async (req: Request, res: Response, next: NextFunction) => {
    // 注意：挂载在 /api 上时 req.path 会去掉挂载前缀（/project/list），
    // 前缀判断必须用 req.originalUrl（含完整 /api/...）。
    const fullPath = req.originalUrl.split('?')[0];
    if (!isQuotePath(fullPath)) return next();

    const query = req.originalUrl.includes('?') ? req.originalUrl.slice(req.originalUrl.indexOf('?')) : '';
    const target = `${UPSTREAM}/api${req.url}${query}`;
    const method = req.method.toUpperCase();

    // GET/HEAD 无 body；其余读原始流转发。
    // Buffer 不满足 fetch 的 BodyInit 类型，故转 Uint8Array。
    const hasBody = method !== 'GET' && method !== 'HEAD';
    let body: Uint8Array | undefined;
    if (hasBody) {
      try {
        const raw = await readRawBody(req);
        body = raw.length ? new Uint8Array(raw) : undefined;
      } catch (err) {
        res.status(400).json({ detail: `读取请求体失败：${(err as Error).message}` });
        return;
      }
    }

    // 转发请求头：剔除 hop-by-hop 与长度（长度由 fetch 依 body 重算）。
    const headers: Record<string, string> = {};
    for (const [k, v] of Object.entries(req.headers)) {
      if (typeof v !== 'string') continue;
      const lk = k.toLowerCase();
      if (lk === 'host' || lk === 'content-length' || lk === 'connection' || lk === 'accept-encoding') continue;
      headers[k] = v;
    }

    try {
      const upstream = await fetch(target, {
        method,
        headers,
        // tsconfig 只加载 node 类型（无 DOM lib），BodyInit 未定义导致 Uint8Array 认不过；
        // 运行时 Node 24 的 undici fetch 完全支持 Uint8Array 作 body，此处局部转型。
        body: body as unknown as undefined,
        redirect: 'manual',
      });

      res.status(upstream.status);
      // 逐条回传上游响应头（保留 content-type / content-disposition 等；跳过长度与分块）。
      upstream.headers.forEach((value, key) => {
        const lk = key.toLowerCase();
        if (lk === 'content-length' || lk === 'transfer-encoding' || lk === 'connection' || lk === 'content-encoding') return;
        res.setHeader(key, value);
      });
      const buf = Buffer.from(await upstream.arrayBuffer());
      res.end(buf);
    } catch (err) {
      // 上游不可达：明确报因，不假装成功。
      res.status(502).json({
        detail: `报价域上游不可达（${UPSTREAM}）：${(err as Error).message}。请确认 :8000 后端已启动。`,
      });
    }
  });
}

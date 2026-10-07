// P0 架构收敛（2026-10-07）：agent-service/server.mjs 的类型垫片。
// 该模块是纯 ESM JS（无 tsc 编译），用通配声明让 index.ts 能 import。
declare module '*agent-service/server.mjs' {
  import type { IncomingMessage, ServerResponse } from 'node:http';
  export function agentRequestHandler(req: IncomingMessage, res: ServerResponse): Promise<void>;
}

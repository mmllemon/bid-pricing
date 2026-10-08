/**
 * 全站 CSP（F-P0-3）。
 *
 * 为什么抽成模块：CSP 是唯一 Web 入口（:3456）的安全响应头，一旦退回「只有
 * frame-ancestors」，点击劫持/内联注入面就重新打开，但功能测试完全测不出来。
 * 抽成纯函数后可在单测里逐条钉住策略要点（tests/v330-csp.test.ts）。
 *
 * 策略依据（P4 前端整合后实测）：
 *   - 静态产物为 Vite 单包，index.html 零内联 script，无外站脚本/样式/图片。
 *   - React 大量使用 style={{}} 内联样式，故 style-src 必须保留 'unsafe-inline'
 *     （去掉会静默掉全部内联样式，属已知可接受残余）。
 *   - select 箭头是 data:image/svg+xml，字体经 Vite 内联为 data:，故 img/font 需放行 data:。
 *   - 报价域走同源 /api/*（:3456 反代），另放行直连 :8000（下载/调试路径）。
 */
export interface CspEnv {
  frameAncestors?: string;
  extra?: string;
}

const DEFAULT_FRAME_ANCESTORS =
  "'self' http://127.0.0.1:8000 http://localhost:8000";

export function buildCsp(env: CspEnv = {}): string {
  const frameAncestors = env.frameAncestors || DEFAULT_FRAME_ANCESTORS;
  const parts = [
    "default-src 'self'",
    "script-src 'self'",
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: blob:",
    "font-src 'self' data:",
    "connect-src 'self' http://127.0.0.1:8000 http://localhost:8000",
    `frame-ancestors ${frameAncestors}`,
  ];
  const extra = (env.extra || '').trim();
  return parts.join('; ') + (extra ? `; ${extra}` : '');
}
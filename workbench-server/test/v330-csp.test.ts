/**
 * 全站 CSP 守卫（F-P0-3）。
 *
 * 为什么需要：CSP 是唯一 Web 入口（:3456）的安全响应头，从「只有 frame-ancestors」
 * 退回或策略被改坏，功能测试完全测不出来（页面照常渲染）。这里逐条钉住策略要点，
 * 退回即红。
 */
import { describe, expect, it } from 'vitest';
import { buildCsp } from '../src/http/csp';

describe('CSP 策略（F-P0-3）', () => {
  const csp = buildCsp();

  it('必须是完整策略，不能只有 frame-ancestors', () => {
    // 回归形态：曾长期只有 frame-ancestors —— 内联注入面完全敞开。
    expect(csp).not.toMatch(/^frame-ancestors/);
    for (const directive of [
      'default-src', 'script-src', 'style-src', 'img-src', 'font-src', 'connect-src', 'frame-ancestors',
    ]) {
      expect(csp, `缺少指令 ${directive}`).toContain(directive);
    }
  });

  it('script-src 收紧到 self（产物零内联脚本）', () => {
    expect(csp).toContain("script-src 'self'");
    expect(csp).not.toMatch(/script-src[^;]*unsafe-inline/);
    expect(csp).not.toMatch(/script-src[^;]*unsafe-eval/);
  });

  it('style-src 保留 unsafe-inline（React 内联样式依赖它）', () => {
    expect(csp).toMatch(/style-src 'self' 'unsafe-inline'/);
  });

  it('frame-ancestors 默认为 self + 本机父页，可被环境覆盖', () => {
    expect(csp).toContain("frame-ancestors 'self'");
    const overridden = buildCsp({ frameAncestors: "'none'" });
    expect(overridden).toContain("frame-ancestors 'none'");
  });

  it('img/font 放行 data:（select 箭头与内联字体）', () => {
    expect(csp).toMatch(/img-src[^;]*data:/);
    expect(csp).toMatch(/font-src[^;]*data:/);
  });

  it('EXTRA 追加源被拼到末尾', () => {
    const withExtra = buildCsp({ extra: "worker-src 'self'" });
    expect(withExtra.endsWith("; worker-src 'self'")).toBe(true);
  });
});
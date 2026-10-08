import { describe, expect, it } from 'vitest';
import { clamp, spring, sp, targets } from './portalEngine';

/**
 * Portal 引擎纯函数单测。
 * targets() 和 spring() 是布局的核心，锁定它们的参数，
 * 以后改布局先跑测试，避免"挤到一起"这类回归。
 */
describe('spring', () => {
  it('收敛到目标值', () => {
    const st = sp(0);
    for (let i = 0; i < 200; i++) spring(st, 100, 1 / 60);
    expect(st.x).toBeCloseTo(100, 0);
  });

  it('NaN 目标不会污染状态（返回 NaN 但不崩）', () => {
    const st = sp(50);
    const r = spring(st, NaN, 1 / 60);
    expect(Number.isNaN(r)).toBe(true);
  });
});

describe('clamp', () => {
  it('钳制范围内', () => {
    expect(clamp(5, 0, 10)).toBe(5);
    expect(clamp(-5, 0, 10)).toBe(0);
    expect(clamp(15, 0, 10)).toBe(10);
  });
});

describe('targets', () => {
  const base = {
    size: { w: 1366, h: 768 },
    stage: 'hub' as const,
    mod: null,
    branch: null,
    time: 0,
  };

  it('hub 态：模块围绕中心分布，不重叠', () => {
    const layout = targets(base, 0);
    const positions = Object.values(layout.jelly);
    expect(positions.length).toBeGreaterThan(0);
    // 所有模块应在视口内
    for (const p of positions) {
      expect(p.x).toBeGreaterThanOrEqual(0);
      expect(p.x).toBeLessThanOrEqual(base.size.w);
      expect(p.y).toBeGreaterThanOrEqual(0);
      expect(p.y).toBeLessThanOrEqual(base.size.h);
    }
  });

  it('hub 态：圆球在中心附近', () => {
    const layout = targets(base, 0);
    expect(layout.orb.x).toBeCloseTo(base.size.w / 2, -1);
    expect(layout.orb.y).toBeCloseTo(base.size.h * 0.47, -1);
  });

  it('窄屏时使用 narrow 布局', () => {
    const narrow = { ...base, size: { w: 800, h: 600 } };
    const layout = targets(narrow, 0);
    const positions = Object.values(layout.jelly);
    for (const p of positions) {
      expect(p.x).toBeGreaterThanOrEqual(0);
      expect(p.x).toBeLessThanOrEqual(800);
    }
  });
});

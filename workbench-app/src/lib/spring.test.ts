import { describe, expect, it } from 'vitest';
import { PRESET_GENTLE, stepSpring } from './spring';

describe('stepSpring', () => {
  it('收敛到目标值并衰减速度', () => {
    let state = { value: 0, velocity: 0 };
    for (let i = 0; i < 900; i++) state = stepSpring(state, 1, 1 / 60, PRESET_GENTLE);
    expect(state.value).toBeCloseTo(1, 2);
    expect(Math.abs(state.velocity)).toBeLessThan(0.01);
  });

  it('钳制超大 dt，不产生 NaN / Infinity', () => {
    const state = stepSpring({ value: 0, velocity: 0 }, 1, 10, PRESET_GENTLE);
    expect(Number.isFinite(state.value)).toBe(true);
    expect(Number.isFinite(state.velocity)).toBe(true);
  });

  it('负 dt 视为 0，状态保持不变', () => {
    const before = { value: 0.3, velocity: 0.2 };
    expect(stepSpring(before, 1, -1, PRESET_GENTLE)).toEqual(before);
  });
});

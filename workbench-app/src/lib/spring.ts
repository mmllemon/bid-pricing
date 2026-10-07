export interface SpringConfig {
  stiffness: number;
  damping: number;
  mass: number;
}

export const PRESET_GENTLE: SpringConfig = { stiffness: 170, damping: 26, mass: 1 };
export const PRESET_POP: SpringConfig = { stiffness: 320, damping: 20, mass: 0.9 };

export interface SpringState {
  value: number;
  velocity: number;
}

const MAX_DT = 1 / 30;

/** 单步阻尼弹簧积分：dt 钳制在 [0, 1/30] 秒，避免后台标签页恢复时 dt 过大导致发散 / NaN。 */
export function stepSpring(
  state: SpringState,
  target: number,
  dtSeconds: number,
  config: SpringConfig,
): SpringState {
  const dt = Math.min(Math.max(dtSeconds, 0), MAX_DT);
  const { stiffness, damping, mass } = config;
  const acceleration = (-stiffness * (state.value - target) - damping * state.velocity) / mass;
  const velocity = state.velocity + acceleration * dt;
  const value = state.value + velocity * dt;
  return { value, velocity };
}

export function prefersReducedMotion(): boolean {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return false;
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

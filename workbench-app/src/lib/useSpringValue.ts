import { useEffect, useRef, useState } from 'react';
import { PRESET_GENTLE, prefersReducedMotion, stepSpring, type SpringConfig } from './spring';

/** 用阻尼弹簧把数值平滑驱动到 target；prefers-reduced-motion 时直接落到目标，不发散。 */
export function useSpringValue(target: number, config: SpringConfig = PRESET_GENTLE): number {
  const [value, setValue] = useState(target);
  const stateRef = useRef({ value: target, velocity: 0 });
  const targetRef = useRef(target);
  targetRef.current = target;

  useEffect(() => {
    if (prefersReducedMotion()) {
      stateRef.current = { value: targetRef.current, velocity: 0 };
      setValue(targetRef.current);
      return;
    }
    let raf = 0;
    let last = performance.now();
    const tick = (now: number) => {
      const dt = (now - last) / 1000;
      last = now;
      const next = stepSpring(stateRef.current, targetRef.current, dt, config);
      stateRef.current = next;
      setValue(next.value);
      if (Math.abs(next.value - targetRef.current) > 0.001 || Math.abs(next.velocity) > 0.001) {
        raf = requestAnimationFrame(tick);
      }
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [target, config]);

  return value;
}

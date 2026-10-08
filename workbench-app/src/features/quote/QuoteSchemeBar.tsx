import type { PlanGroup } from './quoteApi';
import { HUB_SLOT_DEFS } from './QuotePlanHub';

/**
 * 方案切换胶囊条（P3 块4c：由 app.js syncSchemeSwitcher/refreshSchemeTabs/bindSchemeTabs 迁入 React）
 * 组内 A/B/C 槽位轻量切换：切到某槽位的方案并回填参数。
 */
export function QuoteSchemeBar({
  visible, group, activeSlot, balanceText, onSwitch,
}: {
  visible: boolean;
  group: PlanGroup | null;
  activeSlot: string;
  balanceText: string;
  onSwitch: (slot: string, planId: string | null, index: number) => void;
}) {
  if (!visible) return null;
  const slots = group?.strategy_slots || {};
  return (
    <div className="scheme-switcher-bar" role="tablist" aria-label="方案切换">
      <div className="scheme-tabs">
        {HUB_SLOT_DEFS.map((def, i) => {
          const s = slots[def.key] || {};
          const pid = s.plan_id || s.summary?.plan_id || null;
          const isActive = activeSlot === def.key;
          const disabled = def.key === 'C' && !pid;
          return (
            <button key={def.key} type="button" className={`scheme-tab${isActive ? ' active' : ''}`} data-scheme={i}
              role="tab" aria-selected={isActive} disabled={disabled}
              onClick={() => onSwitch(def.key, pid, i)}>
              <span className="tab-indicator" />方案 {def.key}
            </button>
          );
        })}
      </div>
      <div className="scheme-balance">平衡约束: <strong id="schemeBalanceText">{balanceText}</strong></div>
    </div>
  );
}
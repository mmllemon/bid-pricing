import { useState } from 'react';
import type { PlanGroup, StrategySlot } from './quoteApi';

/**
 * 报价页方案中心（P3 块4b：由 app.js renderPlanHub/renderGroupCard/renderSlotRow 等迁入 React）
 * 方案组卡片：组名 / 目标报价 / 已算槽数 / 定稿锁 + 操作（改名·复制整组·定稿·删除）+ 展开 A/B/C 槽位。
 * 槽位：pending → 「未测算·点算」；computed → 利润/竞争预算/项数 + 「打开」+ 勾选对比。
 */
export const HUB_SLOT_DEFS: { key: string; label: string; strategy: string }[] = [
  { key: 'A', label: '逐项最优', strategy: 'optimal' },
  { key: 'B', label: '等比下浮', strategy: 'uniform' },
  { key: 'C', label: '不平衡报价', strategy: 'unbalanced' },
];

const money = (v: unknown) => (v != null && v !== '' ? `¥${Number(v).toLocaleString('zh-CN', { minimumFractionDigits: 2 })}` : '—');

function groupTarget(g: PlanGroup): number | null {
  for (const def of HUB_SLOT_DEFS) {
    const t = g.strategy_slots?.[def.key]?.summary?.target_total;
    if (t != null) return t;
  }
  return null;
}

export function QuotePlanHub({
  open, projectName, groups, selected, expanded, onToggleGroup, onRename, onCopy, onFinalize, onDelete,
  onCalcSlot, onOpenSlot, onToggleSelect, onCompare, onClose,
}: {
  open: boolean;
  projectName: string;
  groups: PlanGroup[];
  selected: Set<string>;
  expanded: Set<string>;
  onToggleGroup: (gid: string) => void;
  onRename: (gid: string, name: string) => void;
  onCopy: (gid: string) => void;
  onFinalize: (gid: string, on: boolean) => void;
  onDelete: (gid: string) => void;
  onCalcSlot: (gid: string, strategy: string) => void;
  onOpenSlot: (planId: string, gid: string) => void;
  onToggleSelect: (planId: string, on: boolean) => void;
  onCompare: () => void;
  onClose: () => void;
}) {
  const [renaming, setRenaming] = useState<{ gid: string; value: string } | null>(null);

  return (
    <div className={`plan-hub${open ? ' open' : ''}`} id="planHub" role="dialog" aria-modal="true" aria-label="方案中心" aria-hidden={!open}>
      <div className="ph-header">
        <h3>方案中心</h3>
        <span className="ph-current" id="planHubCurrent">{projectName || '未选择项目'}</span>
        <button type="button" className="ph-close" id="planHubCloseBtn" aria-label="关闭" onClick={onClose}>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" width={14} height={14} aria-hidden="true"><path d="M6 6l12 12M18 6L6 18" /></svg>
        </button>
      </div>

      <div className="ph-body" id="planHubBody" aria-live="polite">
        {!projectName ? (
          <div className="ph-empty">请先在左侧选择关联投标项目</div>
        ) : groups.length === 0 ? (
          <div className="ph-empty">该项目暂无方案组，请先在上方识别并计算</div>
        ) : groups.map((g) => {
          const computedCount = Object.values(g.strategy_slots || {}).filter((s) => s && (s.plan_id || s.summary?.plan_id)).length;
          const isExpanded = expanded.has(g.group_id);
          return (
            <div className={`phg-card${g.finalized ? ' finalized' : ''}${isExpanded ? ' expanded' : ''}`} data-gid={g.group_id} key={g.group_id}>
              <div className="phg-head">
                <button type="button" className="phg-expand" aria-expanded={isExpanded}
                  title={isExpanded ? '收起槽位' : '展开 A/B/C 槽位'} onClick={() => onToggleGroup(g.group_id)}>
                  <span className="arr">▸</span>
                </button>
                {renaming?.gid === g.group_id ? (
                  <input className="phg-rename-input" maxLength={60} value={renaming.value} autoFocus
                    onChange={(e) => setRenaming({ gid: g.group_id, value: e.target.value })}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') { onRename(g.group_id, renaming.value.trim()); setRenaming(null); }
                      else if (e.key === 'Escape') setRenaming(null);
                    }}
                    onBlur={() => { onRename(g.group_id, renaming.value.trim()); setRenaming(null); }} />
                ) : (
                  <span className="phg-name" title={g.group_name || ''}>{g.group_name || g.group_id || '未命名组'}</span>
                )}
                {g.finalized
                  ? <span className="phg-lock on" title="已定稿，整组锁定"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><rect x={4} y={11} width={16} height={9} rx={2} /><path d="M8 11V7a4 4 0 0 1 8 0v4" /></svg>已定稿</span>
                  : <span className="phg-lock">未定稿</span>}
              </div>

              <div className="phg-meta">
                <span>目标报价 <b className="tabular">{money(groupTarget(g))}</b></span>
                <span>已算 <b className="tabular">{computedCount}/3</b> 槽</span>
              </div>

              <div className="phg-ops">
                <button type="button" className="phg-op" onClick={() => setRenaming({ gid: g.group_id, value: g.group_name || '' })}>改名</button>
                <button type="button" className="phg-op" onClick={() => onCopy(g.group_id)}>复制整组</button>
                <button type="button" className={`phg-op fin${g.finalized ? ' is-on' : ''}`} onClick={() => onFinalize(g.group_id, !g.finalized)}>
                  {g.finalized ? '取消定稿' : '定稿锁定'}
                </button>
                <button type="button" className={`phg-op${g.finalized ? ' is-disabled' : ''}`} disabled={g.finalized} onClick={() => onDelete(g.group_id)}>删除</button>
              </div>

              {isExpanded && (
                <div className="phg-slots">
                  {HUB_SLOT_DEFS.map((def) => {
                    const s: StrategySlot = g.strategy_slots?.[def.key] || { plan_id: null, status: 'pending' };
                    const sm = s.summary || {};
                    const planId = s.plan_id || sm.plan_id;
                    const letter = def.key.toLowerCase();
                    if (!planId) {
                      return (
                        <div className={`phg-slot pending letter-${letter}`} key={def.key}>
                          <span className="letter">{def.key}</span>
                          <div className="phg-slot-info">
                            <div className="phg-slot-title">{def.key} · {def.label}</div>
                            <div className="phg-slot-stat">未测算 · 可点算</div>
                          </div>
                          <button type="button" className="slot-act" onClick={() => onCalcSlot(g.group_id, def.strategy)}>点算</button>
                        </div>
                      );
                    }
                    return (
                      <div className={`phg-slot letter-${letter}`} key={def.key}>
                        <span className="letter">{def.key}</span>
                        <div className="phg-slot-info">
                          <div className="phg-slot-title">{def.key} · {def.label}</div>
                          <div className="phg-slot-stat">
                            利润 <b className="tabular">{money(sm.objective)}</b> ｜ 竞争预算 <b>{money(sm.competitive_budget)}</b> ｜ {sm.item_count != null ? `${sm.item_count} 项` : '—'}
                          </div>
                        </div>
                        <button type="button" className="slot-act" title="打开该槽位方案" onClick={() => onOpenSlot(planId, g.group_id)}>打开</button>
                        <label className="slot-check" title="勾选对比">
                          <input type="checkbox" value={planId} checked={selected.has(planId)} onChange={(e) => onToggleSelect(planId, e.target.checked)} />
                        </label>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {selected.size > 0 && (
        <div className="ph-bar" id="planHubCompareBar">
          <span className="ph-count tabular" id="planHubCount">已选 {selected.size} 个槽位</span>
          <button type="button" className="btn-primary ph-run" id="planHubRunBtn" onClick={onCompare}>开始对比 →</button>
        </div>
      )}
    </div>
  );
}
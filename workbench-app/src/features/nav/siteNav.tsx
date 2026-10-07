import type { ReactNode } from 'react';
import { WORKBENCH_NAV, type WorkbenchNavItem } from './workbenchNav';

/**
 * 全站顶栏导航 · 单一事实源（P0-3 前端整合）
 *
 * 形态对齐参考项目（neural-creator-dashboard 的顶栏胶囊导航）：无侧栏，导航在顶栏。
 * 两级结构：
 *   一级「域」：全景大盘 / 工作台 / 投标报价 / 工具箱
 *   二级「页」：仅工作台域展开（其 9 页复用 features/nav/workbenchNav.tsx 的清单，不复制）
 *
 * 迁移期约定（前端整合计划 P0→P3）：
 *   - `to` 非空 = 本 React 应用内的路由；
 *   - `href` 非空 = 尚未迁入 React 的旧页面，暂时外链到母项目 :8000。
 *   每迁完一个域（P1 大盘、P3 报价），把该域的 href 改成 to 即可，其余不动。
 */
export interface SiteDomain {
  id: string;
  label: string;
  code: string;
  /** 内部路由（React 应用内）；与 href 二选一。 */
  to?: string;
  /** 外部链接（尚未迁入 React 的旧页），暂时指向母项目。 */
  href?: string;
  /** 二级页（仅工作台域有）。 */
  children?: WorkbenchNavItem[];
}

/** 尚未迁入 React 的旧页面所在的母项目入口（临时，迁移完成后删除）。 */
export const LEGACY_ORIGIN =
  (typeof window !== 'undefined' && (window as { __BID?: { legacyOrigin?: string } }).__BID?.legacyOrigin) ||
  'http://127.0.0.1:8000';

export const SITE_DOMAINS: SiteDomain[] = [
  {
    id: 'portal',
    label: '全景大盘',
    code: 'P-00',
    to: '/portal', // P1 已迁入 React
  },
  {
    id: 'workbench',
    label: '工作台',
    code: 'W-00',
    to: '/',
    children: WORKBENCH_NAV,
  },
  {
    id: 'quote',
    label: '投标报价',
    code: 'Q-01',
    to: '/quote', // P3 已迁入 React（只读骨架，交互分块补齐）
  },
  {
    id: 'tools',
    label: '工具箱',
    code: 'T-06',
    to: '/tools', // P2 已迁入 React
  },
];

/** 简易图标（24×24 线性，stroke 1.7，与工作台导航同风格）。 */
export const DOMAIN_ICONS: Record<string, ReactNode> = {
  portal: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <circle cx="12" cy="12" r="3" /><circle cx="5" cy="12" r="1.5" /><circle cx="19" cy="12" r="1.5" />
      <circle cx="12" cy="5" r="1.5" /><circle cx="12" cy="19" r="1.5" /><path d="M5 12h4m6 0h4M12 5v4m0 6v4" />
    </svg>
  ),
  workbench: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <rect x="3" y="3" width="7" height="9" rx="1.5" /><rect x="14" y="3" width="7" height="5" rx="1.5" />
      <rect x="14" y="12" width="7" height="9" rx="1.5" /><rect x="3" y="16" width="7" height="5" rx="1.5" />
    </svg>
  ),
  quote: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <rect x="3" y="4" width="18" height="16" rx="2" /><path d="M3 9h18M8 14h5M8 17h8" />
    </svg>
  ),
  tools: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <rect x="5" y="3" width="14" height="18" rx="2" /><path d="M9 7h6M9 11h.01M12 11h.01M15 11h.01M9 14h.01M12 14h.01M15 14h.01M9 17h6" />
    </svg>
  ),
};

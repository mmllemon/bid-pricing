import type { ReactNode } from 'react';
import { Wallet } from 'pixelarticons/react';
import {
  IconHome,
  IconTodo,
  IconScan,
  IconSettings,
  IconHotspot,
  IconBrain,
  IconBriefcase,
} from '../../components/icons';

export interface WorkbenchNavItem {
  to: string;
  label: string;
  code: string;
  icon: ReactNode;
}

/** React 侧导航唯一数据源：自带侧栏（独立访问）与首页径向地图共用，避免两份清单漂移。 */
export const WORKBENCH_NAV: WorkbenchNavItem[] = [
  { to: '/', label: '今日', code: 'H-01', icon: <IconHome /> },
  { to: '/biz', label: '项目经营', code: 'M-01', icon: <IconBriefcase /> },
  { to: '/graph', label: '关联图谱', code: 'G-09', icon: <IconBrain /> },
  { to: '/todos', label: '待办', code: 'T-02', icon: <IconTodo /> },
  { to: '/finance', label: '财务分析', code: 'F-08', icon: <Wallet width={24} height={24} /> },
  { to: '/hotspots', label: '热点雷达', code: 'R-04', icon: <IconHotspot /> },
  { to: '/knowledge', label: '知识大脑', code: 'K-05', icon: <IconBrain /> },
  { to: '/scan', label: '扫描报告', code: 'S-06', icon: <IconScan /> },
  { to: '/settings', label: '设置', code: 'S-07', icon: <IconSettings /> },
];


/** Portal 配置加载器（2026-10-08 配置化方案 Step5）
 *
 * 默认配置随代码走（portal.config.json），用户修改存 localStorage（UI 偏好）。
 * 启动时合并：用户配置覆盖默认。
 */
import defaultConfig from './portal.config.json';

export interface PortalModuleConfig {
  id: string;
  code: string;
  name: string;
  icon: string;
  color: string;
  levels: number;           // 1-4，按模块独立定
  visible: boolean;        // 用户可隐藏
  dataSource: string;      // "api:/path" 或 "static:"
  cardFields: string[];    // 字段字典的子集
  cardLink?: string;       // 穿透链接，{id}/{name} 占位符
}

export interface PortalConfig {
  modules: PortalModuleConfig[];
}

const STORAGE_KEY = 'portal.config.overrides.v1';

interface Overrides {
  [moduleId: string]: Partial<PortalModuleConfig>;
}

function loadOverrides(): Overrides {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return {};
    const o = JSON.parse(raw);
    return typeof o === 'object' && o !== null ? o : {};
  } catch {
    return {};
  }
}

function saveOverrides(o: Overrides): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(o));
  } catch {
    /* localStorage 满或禁用时静默 */
  }
}

/** 获取合并后的配置 */
export function getPortalConfig(): PortalConfig {
  const overrides = loadOverrides();
  const modules = (defaultConfig as PortalConfig).modules.map((m) => ({
    ...m,
    ...(overrides[m.id] || {}),
  }));
  return { modules };
}

/** 更新单个模块的配置 */
export function updateModuleConfig(id: string, patch: Partial<PortalModuleConfig>): PortalConfig {
  const overrides = loadOverrides();
  overrides[id] = { ...(overrides[id] || {}), ...patch };
  saveOverrides(overrides);
  return getPortalConfig();
}

/** 恢复默认 */
export function resetPortalConfig(): PortalConfig {
  try {
    localStorage.removeItem(STORAGE_KEY);
  } catch { /* ignore */ }
  return getPortalConfig();
}

/** 仅返回可见模块 */
export function getVisibleModules(): PortalModuleConfig[] {
  return getPortalConfig().modules.filter((m) => m.visible);
}

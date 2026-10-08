import { useState } from 'react';
import {
  getPortalConfig,
  updateModuleConfig,
  resetPortalConfig,
  type PortalModuleConfig,
} from './portalConfig';

/** 设置页：Portal 模块开关（2026-10-08 配置化方案 Step9） */
export function PortalModuleSettings() {
  const [modules, setModules] = useState<PortalModuleConfig[]>(() => getPortalConfig().modules);

  const toggle = (id: string, visible: boolean) => {
    const cfg = updateModuleConfig(id, { visible });
    setModules(cfg.modules);
  };

  const reset = () => {
    const cfg = resetPortalConfig();
    setModules(cfg.modules);
  };

  return (
    <div className="portal-settings">
      <div className="nb-muted portal-settings-desc">
        控制大盘上显示哪些模块。关闭后模块从导航和首页隐藏，数据不受影响。
      </div>
      {modules.map((m) => (
        <label key={m.id} className="portal-settings-row">
          <input
            type="checkbox"
            checked={m.visible}
            onChange={(e) => toggle(m.id, e.target.checked)}
          />
          <span className="portal-settings-name">{m.name}</span>
          <span className="nb-muted portal-settings-meta">
            {m.code} · {m.levels} 级
          </span>
        </label>
      ))}
      <div>
        <button className="nb-btn nb-btn--ghost" onClick={reset}>
          恢复默认
        </button>
      </div>
    </div>
  );
}

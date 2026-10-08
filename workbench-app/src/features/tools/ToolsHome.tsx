import type { ReactNode } from 'react';
import { ToolShell } from './ToolShell';
import PageHead from '../../components/PageHead';

/**
 * 速算工具箱首页（P2 前端整合：由 frontend/tools.html 迁入 React）。
 * 四张工具卡，指向 /tools/{cable,well,earth,duct}。
 */
const CARDS: { to: string; title: string; sub?: string; desc: string; icon: ReactNode }[] = [
  {
    to: '#/tools/cable',
    title: '电缆价格速算', sub: '铜价法',
    desc: '由铜价/铝价反推各型号电缆的出厂单价：导体成本 ＋ 其他材料制费 ＋ 管理利润 ＋ 税。支持不等截面规格（如 3×240+2×120）与多行清单汇总。',
    icon: <path d="M13 2 4.8 12.4H11L9.6 22 19 10.2h-6.2L13 2z" />,
  },
  {
    to: '#/tools/well',
    title: '电缆井工程量速算',
    desc: '参数化矩形/转角/三通/四通井：垫层、底板、井壁（砖砌/混凝土）、顶板、井筒、钢筋（含钢量法）、模板、抹面、井盖、爬梯逐项工程量与合价。',
    icon: <><ellipse cx="12" cy="5" rx="7" ry="2.6" /><path d="M5 5v13c0 1.5 3.1 2.6 7 2.6s7-1.1 7-2.6V5" /><path d="M5 11.5c0 1.5 3.1 2.6 7 2.6s7-1.1 7-2.6" /></>,
  },
  {
    to: '#/tools/earth',
    title: '挖方与回填速算',
    desc: '多段沟槽梯形断面 V = L×(a+m·h)×h：按土壤类别的定额放坡（可自定）、管位占置扣减回填、余方外运/借方自动判定与汇总合价。',
    icon: <><path d="M3 21h18" /><path d="M5 21v-6a7 7 0 0 1 14 0v6" /><path d="M9 21v-4h6v4" /></>,
  },
  {
    to: '#/tools/duct',
    title: '排管断面布置',
    desc: '孔数 → 标准排列 → 包封尺寸 → 沟底宽建议：按 T/SDL 4-2022 标准表自动匹配行×列，断面 SVG 实时重绘，包封混凝土与沟底宽可一键送入土方工具。',
    icon: <><circle cx="7" cy="8" r="2.6" /><circle cx="12" cy="8" r="2.6" /><circle cx="17" cy="8" r="2.6" /><circle cx="7" cy="15.5" r="2.6" /><circle cx="12" cy="15.5" r="2.6" /><circle cx="17" cy="15.5" r="2.6" /></>,
  },
];

export default function ToolsHome() {
  return (
    <>
      <PageHead
        zh="工具箱"
        en="Toolbox"
        sub="配电土建速算，一处搞定。"
        subEn="Quick calculators for power distribution & civil works — all local, no upload."
      />
      <p className="hint" style={{ margin: '0 0 18px' }}>
        纯本地速算，数据不上传。各工具内的构件口径与单价均为<b>可编辑的参考默认值</b>，
        使用前请按当期信息价、施工图与所套定额核对；金额口径（含税/税前）请自行统一。
      </p>

      <div className="tool-cards">
        {CARDS.map((c) => (
          <a className="tool-card-link" href={c.to} key={c.to}>
            <div className="tool-card-icon">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">{c.icon}</svg>
            </div>
            <h2>{c.title} {c.sub && <small>{c.sub}</small>}</h2>
            <p>{c.desc}</p>
            <span className="tool-card-go">进入工具 →</span>
          </a>
        ))}
      </div>

      <p className="hint" style={{ margin: '18px 0 30px' }}>
        本工具箱为速算参考，不替代工程量清单计价规范（GB 50500）的正式算量与组价流程；工程量以施工图与现场计量为准。
      </p>
    </>
  );
}

export { ToolShell };

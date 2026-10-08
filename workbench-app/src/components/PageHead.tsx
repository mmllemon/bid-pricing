import type { ReactNode } from 'react';

/**
 * 子页面统一页头（布局骨架借鉴 neural-creator-dashboard 的 PageHead）。
 *
 * 结构：eyebrow（英文大写 + 中文小字）/ 中文 slogan 大标题 / 英文副标题 / 右侧操作区。
 * 视觉走本站四色 + 浅色 + 裁角语言，不照搬参考项目的深色 glass。
 * 像素字体仅用于 eyebrow 英文与数字装饰，中文正文一律 MiSans（--font）。
 */
export default function PageHead({
  zh,
  en,
  sub,
  subEn,
  children,
}: {
  /** 中文栏目名，如 "项目库" */
  zh: string;
  /** 英文栏目名，如 "Projects" */
  en: string;
  /** 中文 slogan 大标题，如 "每个项目，都是一盘生意。" */
  sub: string;
  /** 英文副标题 */
  subEn?: string;
  /** 右侧操作区（按钮等） */
  children?: ReactNode;
}) {
  return (
    <header className="page-head">
      <div>
        <p className="page-eyebrow">
          {en.toUpperCase()} <span>{zh}</span>
        </p>
        <h1 className="page-title">{sub}</h1>
        {subEn && <p className="page-sub">{subEn}</p>}
      </div>
      {children && <div className="page-head-actions">{children}</div>}
    </header>
  );
}

import { describe, expect, it, vi, beforeEach } from 'vitest';
import { act } from 'react-dom/test-utils';
import { createRoot } from 'react-dom/client';
import BizQuickView from './BizQuickView';
import type { ProjectOverview } from './bizShared';

/**
 * 快览面板契约测试。
 * 无 @testing-library：用 react-dom/client 手动挂载 + act 驱动。
 * 只钉行为契约（渲染/关闭/Escape/进入），不钉 DOM 细节。
 */
const mockProject: ProjectOverview = {
  id: 'test-1',
  name: '西永L分区项目',
  short_name: '西永L',
  stage: '投标',
  limit_total: '120000000',
  bid_open_date: '2026-10-20',
  bid_amount: '98000000',
  bid_cost: '85000000',
  actual_revenue: '30000000',
  gross_profit: 13000000,
  gross_margin: 0.1327,
};

function mount(props: Partial<Parameters<typeof BizQuickView>[0]> = {}) {
  const container = document.createElement('div');
  document.body.appendChild(container);
  const root = createRoot(container);
  const onClose = vi.fn();
  const onEnter = vi.fn();
  act(() => {
    root.render(
      <BizQuickView
        project={mockProject}
        todoCount={3}
        onClose={onClose}
        onEnter={onEnter}
        {...props}
      />
    );
  });
  return { container, root, onClose, onEnter };
}

beforeEach(() => {
  document.body.innerHTML = '';
  vi.restoreAllMocks();
});

describe('BizQuickView', () => {
  it('渲染项目名称与阶段', () => {
    const { container } = mount();
    expect(container.textContent).toContain('西永L');
    expect(container.textContent).toContain('投标');
  });

  it('无项目时渲染空', () => {
    const { container } = mount({ project: null });
    expect(container.innerHTML).toBe('');
  });

  it('Escape 触发 onClose', () => {
    const { onClose } = mount();
    act(() => {
      document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
    });
    expect(onClose).toHaveBeenCalled();
  });

  it('点击进入按钮触发 onEnter', () => {
    const { container, onEnter } = mount();
    const btn = Array.from(container.querySelectorAll('button')).find((b) =>
      b.textContent?.includes('进入项目主页')
    );
    expect(btn).toBeTruthy();
    act(() => { btn!.click(); });
    expect(onEnter).toHaveBeenCalledWith(mockProject);
  });

  it('显示收款进度', () => {
    const { container } = mount();
    // 30000000 / 98000000 ≈ 31%
    expect(container.textContent).toContain('收款 31%');
  });
});

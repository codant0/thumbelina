import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { StatusBarCardGrid } from './StatusBarCardGrid'
import type { StatusBarConfig } from './useStatusBarConfig'
import type { StatusBarCardDef } from './StatusBarCardGrid'

const cards: StatusBarCardDef<keyof StatusBarConfig>[] = [
  {
    key: 'context',
    label: '上下文占用',
    description: '在聊天输入栏右侧显示估算的上下文窗口占用',
  },
]

describe('StatusBarCardGrid', () => {
  it('渲染栏目卡片，关闭态使用 --off 且 aria-pressed=false', () => {
    render(
      <StatusBarCardGrid cards={cards} config={{ context: false, cacheHit: true, git: true }} onToggle={vi.fn()} />,
    )
    const btn = screen.getByTestId('statusbar-card-context')
    expect(btn).toHaveClass('status-card--off')
    expect(btn).toHaveAttribute('aria-pressed', 'false')
    expect(btn).toHaveTextContent('上下文占用')
  })

  it('开启态使用 --on 且 aria-pressed=true，展示勾选图标', () => {
    render(
      <StatusBarCardGrid cards={cards} config={{ context: true, cacheHit: true, git: true }} onToggle={vi.fn()} />,
    )
    const btn = screen.getByTestId('statusbar-card-context')
    expect(btn).toHaveClass('status-card--on')
    expect(btn).toHaveAttribute('aria-pressed', 'true')
    expect(btn.querySelector('.status-card__check')).not.toBeNull()
  })

  it('点击卡片触发 onToggle(key)', () => {
    const onToggle = vi.fn()
    render(<StatusBarCardGrid cards={cards} config={{ context: true, cacheHit: true, git: true }} onToggle={onToggle} />)
    screen.getByTestId('statusbar-card-context').click()
    expect(onToggle).toHaveBeenCalledWith('context')
  })

  it('cards 为空时不渲染', () => {
    const { container } = render(
      <StatusBarCardGrid cards={[]} config={{ context: true, cacheHit: true, git: true }} onToggle={vi.fn()} />,
    )
    expect(container.querySelector('[data-testid="statusbar-card-grid"]')).toBeNull()
  })
})

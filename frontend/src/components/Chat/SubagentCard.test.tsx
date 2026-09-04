import { describe, it, expect, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { SubagentCard } from './SubagentCard'
import { LocaleProvider } from '../../i18n/LocaleContext'
import type { SubagentEventPayload } from '../../types/chat'

function renderWithI18n(ui: React.ReactNode) {
  return render(<LocaleProvider>{ui}</LocaleProvider>)
}

function makeEvent(overrides: Partial<SubagentEventPayload> = {}): SubagentEventPayload {
  return {
    type: 'subagent.started',
    id: 'sub-1',
    task: '审查 src/api/chat.py 的 WS 路由',
    status: 'running',
    started_at: '2024-01-01T00:00:00.000Z',
    finished_at: null,
    result: null,
    error: null,
    ...overrides,
  }
}

describe('SubagentCard', () => {
  it('renders task summary and status badge', () => {
    renderWithI18n(<SubagentCard event={makeEvent({ status: 'running' })} />)
    expect(screen.getByTestId('subagent-card')).toBeInTheDocument()
    expect(screen.getByTestId('subagent-status')).toBeInTheDocument()
    expect(screen.getByText(/审查 src\/api\/chat\.py/)).toBeInTheDocument()
  })

  it('truncates very long task text', () => {
    const longTask = 'a'.repeat(80)
    renderWithI18n(<SubagentCard event={makeEvent({ task: longTask })} />)
    // 头部应展示截断后的版本(≤ 40 字符 + 省略号)
    expect(screen.getAllByText(/^a+…$/).length).toBeGreaterThan(0)
  })

  it('does not expose a chevron expand-toggle', () => {
    renderWithI18n(<SubagentCard event={makeEvent({ result: 'final report' })} />)
    expect(screen.queryByTestId('subagent-card-toggle')).not.toBeInTheDocument()
    // 详情结果不应出现在卡片内部
    expect(screen.queryByText('final report')).not.toBeInTheDocument()
  })

  it('does not expose a view-detail button', () => {
    const onView = vi.fn()
    renderWithI18n(<SubagentCard event={makeEvent()} onViewDetail={onView} />)
    expect(screen.queryByTestId('subagent-view-detail')).not.toBeInTheDocument()
  })

  it('整个卡片可点击触发 onViewDetail', () => {
    const onView = vi.fn()
    renderWithI18n(<SubagentCard event={makeEvent()} onViewDetail={onView} />)
    fireEvent.click(screen.getByTestId('subagent-card'))
    expect(onView).toHaveBeenCalledTimes(1)
    expect(onView.mock.calls[0][0].id).toBe('sub-1')
  })

  it('没有 onViewDetail 时卡片禁用', () => {
    renderWithI18n(<SubagentCard event={makeEvent()} />)
    const card = screen.getByTestId('subagent-card') as HTMLButtonElement
    expect(card.disabled).toBe(true)
  })

  it('completed 状态下展示完成徽章', () => {
    renderWithI18n(
      <SubagentCard
        event={makeEvent({ status: 'completed', finished_at: '2024-01-01T00:00:04.000Z' })}
      />,
    )
    expect(screen.getByTestId('subagent-status').textContent).toMatch(/已完成|Completed/)
  })

  it('failed 状态下展示失败徽章', () => {
    renderWithI18n(
      <SubagentCard
        event={makeEvent({ status: 'failed', error: 'LLM unavailable', finished_at: '2024-01-01T00:00:02.000Z' })}
      />,
    )
    expect(screen.getByTestId('subagent-status').textContent).toMatch(/失败|Failed/)
  })
})
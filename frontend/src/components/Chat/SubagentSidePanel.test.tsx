import { describe, it, expect, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { SubagentSidePanel } from './SubagentSidePanel'
import { LocaleProvider } from '../../i18n/LocaleContext'
import type { SubagentEventPayload } from '../../types/chat'

function renderWithI18n(ui: React.ReactNode) {
  return render(<LocaleProvider>{ui}</LocaleProvider>)
}

function makeEvent(overrides: Partial<SubagentEventPayload> = {}): SubagentEventPayload {
  return {
    type: 'subagent.completed',
    id: 'sub-1',
    task: '审查 src/api/chat.py 的 WS 路由',
    status: 'completed',
    started_at: '2024-01-01T00:00:00.000Z',
    finished_at: '2024-01-01T00:00:04.000Z',
    result: 'All good',
    error: null,
    ...overrides,
  }
}

describe('SubagentSidePanel', () => {
  it('renders hero, status, and result body', () => {
    renderWithI18n(<SubagentSidePanel event={makeEvent()} onClose={() => {}} />)
    expect(screen.getByTestId('subagent-side-panel')).toBeInTheDocument()
    expect(screen.getByTestId('subagent-hero')).toBeInTheDocument()
    expect(screen.getByTestId('subagent-meta-grid')).toBeInTheDocument()
    expect(screen.getByTestId('subagent-detail-body')).toBeInTheDocument()
    expect(screen.getByText(/All good/)).toBeInTheDocument()
  })

  it('clicking the close button invokes onClose', () => {
    const onClose = vi.fn()
    renderWithI18n(<SubagentSidePanel event={makeEvent()} onClose={onClose} />)
    fireEvent.click(screen.getByTestId('subagent-side-panel-close'))
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('renders error block when event has error', () => {
    renderWithI18n(
      <SubagentSidePanel
        event={makeEvent({ status: 'failed', result: null, error: 'LLM unavailable', finished_at: '2024-01-01T00:00:02.000Z' })}
        onClose={() => {}}
      />,
    )
    expect(screen.getByTestId('subagent-error-block')).toBeInTheDocument()
    // 错误块独立于 Markdown 渲染,直接暴露原始文本
    expect(screen.getByTestId('subagent-error-block').textContent).toContain('LLM unavailable')
  })

  it('renders runningHint for running status with no result yet', () => {
    renderWithI18n(
      <SubagentSidePanel
        event={makeEvent({ status: 'running', result: null })}
        onClose={() => {}}
      />,
    )
    expect(screen.getByTestId('subagent-side-panel').getAttribute('data-status')).toBe('running')
  })
})
import { describe, it, expect, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { ToolCallsPanel } from './ToolCallsPanel'
import type { Message } from '../../types/chat'

const message: Message = {
  id: 'a1',
  role: 'assistant',
  content: 'done',
  timestamp: '2024-01-01T00:00:00Z',
  toolCalls: [
    {
      call_id: 'c1', name: 'web_search', args: { query: 'q' },
      status: 'ok', durationMs: 1800, result: 'found 3', resultTruncated: true,
    },
    { call_id: 'c2', name: 'run_shell', args: { cmd: 'ls' }, status: 'running' },
  ],
  toolAnchors: [{ callId: 'c1', offset: 0 }],
}

describe('ToolCallsPanel', () => {
  it('按时间序列出全部调用与状态样式', () => {
    const { container } = render(<ToolCallsPanel message={message} onClose={vi.fn()} />)
    const rows = container.querySelectorAll('[data-testid="tool-calls-row"]')
    expect(rows).toHaveLength(2)
    expect(rows[0]!.className).toContain('status-ok')
    expect(rows[1]!.className).toContain('status-running')
    expect(screen.getByText('web_search')).toBeInTheDocument()
    expect(screen.getByText('run_shell')).toBeInTheDocument()
  })

  it('行展开显示参数与结果(含截断提示)', () => {
    const { container } = render(<ToolCallsPanel message={message} onClose={vi.fn()} />)
    fireEvent.click(container.querySelectorAll('.tool-calls-row__header')[0]!)
    expect(screen.getByText(/"query": "q"/)).toBeInTheDocument()
    expect(screen.getByText('found 3')).toBeInTheDocument()
    expect(screen.getByText('Full content in Trajectory page')).toBeInTheDocument()
  })

  it('再次点击行收起详情', () => {
    const { container } = render(<ToolCallsPanel message={message} onClose={vi.fn()} />)
    const header = container.querySelectorAll('.tool-calls-row__header')[0]!
    fireEvent.click(header)
    expect(container.querySelector('.tool-calls-row__detail')).not.toBeNull()
    fireEvent.click(header)
    expect(container.querySelector('.tool-calls-row__detail')).toBeNull()
  })

  it('运行中的行显示 spinner 且无详情区', () => {
    const { container } = render(<ToolCallsPanel message={message} onClose={vi.fn()} />)
    const rows = container.querySelectorAll('[data-testid="tool-calls-row"]')
    expect(rows[1]!.querySelector('.tool-call__spinner')).toBeTruthy()
    expect(rows[1]!.querySelector('.tool-calls-row__detail')).toBeNull()
  })

  it('close 按钮回调 onClose', () => {
    const onClose = vi.fn()
    const { container } = render(<ToolCallsPanel message={message} onClose={onClose} />)
    fireEvent.click(container.querySelector('[data-testid="tool-calls-panel-close"]')!)
    expect(onClose).toHaveBeenCalledTimes(1)
  })
})

import { describe, it, expect, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { ToolDetailPanel } from './ToolDetailPanel'
import type { ToolCall } from '../../types/chat'

const okCall: ToolCall = {
  call_id: 'c1', name: 'web_search', args: { query: 'hello' },
  result: 'found 3 results', status: 'ok', durationMs: 1800,
}

describe('ToolDetailPanel', () => {
  it('renders tool name, ok status styling and args/result sections', () => {
    const { container } = render(<ToolDetailPanel toolCall={okCall} onClose={vi.fn()} />)
    const panel = container.querySelector('[data-testid="tool-detail-side-panel"]')!
    expect(panel.getAttribute('data-status')).toBe('ok')
    expect(screen.getByText('web_search')).toBeInTheDocument()
    // pretty-print 后的多行 JSON 用正则匹配
    expect(screen.getByText(/"query": "hello"/)).toBeInTheDocument()
    expect(screen.getByText('found 3 results')).toBeInTheDocument()
    expect(screen.getByText('✓ 1800 ms')).toBeInTheDocument()
  })

  it('shows the trajectory hint for truncated results', () => {
    render(<ToolDetailPanel toolCall={{ ...okCall, resultTruncated: true }} onClose={vi.fn()} />)
    expect(screen.getByText('Full content in Trajectory page')).toBeInTheDocument()
  })

  it('shows truncated args verbatim with the hint (no pretty-print)', () => {
    // 契约:args 截断时后端下发 {"_truncated_json": "<json 字符串>"},原样展示
    render(
      <ToolDetailPanel
        toolCall={{
          call_id: 'c2', name: 'big_tool', args: { _truncated_json: '{"blob": "aa…' },
          argsTruncated: true, status: 'ok', durationMs: 5,
        }}
        onClose={vi.fn()}
      />
    )
    expect(screen.getByText('{"blob": "aa…')).toBeInTheDocument()
    expect(screen.getByText('Full content in Trajectory page')).toBeInTheDocument()
  })

  it('running panel shows the running label and no result section', () => {
    render(
      <ToolDetailPanel
        toolCall={{ call_id: 'c3', name: 'run_shell', args: { cmd: 'ls' }, status: 'running' }}
        onClose={vi.fn()}
      />
    )
    expect(screen.getByText('Running…')).toBeInTheDocument()
    expect(screen.queryByText('found 3 results')).toBeNull()
  })

  it('error panel shows the error preview and error status styling', () => {
    const { container } = render(
      <ToolDetailPanel
        toolCall={{
          call_id: 'c4', name: 'web_search', args: {}, status: 'error',
          durationMs: 120, result: "Error executing tool 'web_search': boom",
        }}
        onClose={vi.fn()}
      />
    )
    expect(container.querySelector('[data-testid="tool-detail-side-panel"]')!.getAttribute('data-status')).toBe('error')
    expect(screen.getByText("Error executing tool 'web_search': boom")).toBeInTheDocument()
  })

  it('close button invokes onClose', () => {
    const onClose = vi.fn()
    const { container } = render(<ToolDetailPanel toolCall={okCall} onClose={onClose} />)
    fireEvent.click(container.querySelector('[data-testid="tool-detail-close"]')!)
    expect(onClose).toHaveBeenCalledTimes(1)
  })
})

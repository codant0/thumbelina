import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, act, fireEvent } from '@testing-library/react'
import { TaskDetailModal } from './TaskDetailModal'
import type { ScheduledTaskDetailVO } from '../../api/tasks'

function makeDetail(overrides: Partial<ScheduledTaskDetailVO> = {}): ScheduledTaskDetailVO {
  return {
    id: 't-1',
    description: 'water the plants',
    scheduled_time: '2026-08-30T10:00:00',
    status: 'completed',
    trigger: 'once',
    cron: null,
    next_run: null,
    last_run: '2026-08-30T10:00:00',
    channel: 'web',
    content: 'remember to water the plants',
    mode: 'prompt',
    source: 'web',
    error: null,
    result: 'done',
    created_at: '2026-08-30T09:00:00',
    updated_at: '2026-08-30T10:00:00',
    ...overrides,
  }
}

async function flushAsync(): Promise<void> {
  for (let i = 0; i < 5; i++) await Promise.resolve()
}

describe('TaskDetailModal', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('renders nothing when taskId is null', () => {
    const { container } = render(<TaskDetailModal taskId={null} onClose={() => {}} />)
    expect(container.querySelector('[data-testid="modal"]')).toBeNull()
  })

  it('shows a skeleton while fetching and then renders Markdown content + result', async () => {
    let resolve!: (value: Response) => void
    vi.spyOn(globalThis, 'fetch').mockImplementation(() => new Promise<Response>(r => { resolve = r }))
    render(<TaskDetailModal taskId="t-1" onClose={() => {}} />)
    expect(screen.getByTestId('detail-skeleton')).toBeInTheDocument()

    const detail = makeDetail({
      content: '## heading\n\n- step a\n- step b',
      result: 'reply body',
    })
    await act(async () => {
      resolve(new Response(JSON.stringify(detail), { status: 200 }))
      await flushAsync()
    })

    const body = screen.getByTestId('detail-body')
    expect(body.textContent).toContain('heading')
    expect(body.textContent).toContain('reply body')
  })

  it('shows an error state with a retry button when fetch fails', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ detail: 'boom' }), { status: 500 }),
    )
    render(<TaskDetailModal taskId="t-1" onClose={() => {}} />)
    const err = await screen.findByTestId('detail-error-state')
    expect(err.textContent).toContain('boom')
    fireEvent.click(screen.getByTestId('detail-retry'))
    expect(screen.getByTestId('detail-skeleton')).toBeInTheDocument()
  })

  it('renders an error block when the task has an error', async () => {
    const detail = makeDetail({ error: 'agent run failed', status: 'failed' })
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(detail), { status: 200 }),
    )
    render(<TaskDetailModal taskId="t-1" onClose={() => {}} />)
    expect(await screen.findByText('agent run failed')).toBeInTheDocument()
  })

  it('renders the no-result placeholder when result is null', async () => {
    const detail = makeDetail({ result: null })
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(detail), { status: 200 }),
    )
    render(<TaskDetailModal taskId="t-1" onClose={() => {}} />)
    expect(await screen.findByText('Not run yet')).toBeInTheDocument()
  })
})
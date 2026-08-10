import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { LocaleProvider } from '../../i18n'
import { UploadTaskList } from './UploadTaskList'
import type { UploadTask } from '../../types/rag'

/** 默认 context 的 t 不做参数插值，测试需包裹 LocaleProvider。 */
function renderWithI18n(ui: React.ReactElement) {
  return render(<LocaleProvider>{ui}</LocaleProvider>)
}

function makeTask(overrides: Partial<UploadTask>): UploadTask {
  return {
    id: 't1', kb_id: 'kb1', kind: 'file', label: 'a.md',
    status: 'running', stage: 'embedding',
    total_files: 1, done_files: 0, current_file: 'a.md',
    chunk_done: 48, chunk_total: 320, error: null, result: null,
    created_at: '2026-08-06T12:00:00Z',
    ...overrides,
  }
}

describe('UploadTaskList', () => {
  it('renders nothing when empty', () => {
    const { container } = renderWithI18n(
      <UploadTaskList tasks={[]} onCancel={vi.fn()} onDismiss={vi.fn()} />,
    )
    expect(container.firstChild).toBeNull()
  })

  it('shows progress for running task', () => {
    renderWithI18n(
      <UploadTaskList tasks={[makeTask({})]} onCancel={vi.fn()} onDismiss={vi.fn()} />,
    )
    expect(screen.getByText('a.md')).toBeInTheDocument()
    expect(screen.getByText('Processing')).toBeInTheDocument()
    expect(screen.getByText(/48\/320/)).toBeInTheDocument()
    expect(screen.getByRole('progressbar')).toBeInTheDocument()
  })

  it('shows batch label with file count', () => {
    renderWithI18n(
      <UploadTaskList
        tasks={[makeTask({ kind: 'batch', total_files: 12, done_files: 4, stage: 'loading', chunk_done: 0, chunk_total: 0 })]}
        onCancel={vi.fn()}
        onDismiss={vi.fn()}
      />,
    )
    expect(screen.getByText('a.md and 12 files')).toBeInTheDocument()
  })

  it('shows error for failed task', () => {
    renderWithI18n(
      <UploadTaskList
        tasks={[makeTask({ status: 'failed', error: '加载失败' })]}
        onCancel={vi.fn()}
        onDismiss={vi.fn()}
      />,
    )
    expect(screen.getByText('加载失败')).toBeInTheDocument()
  })

  it('calls onCancel for active task', () => {
    const onCancel = vi.fn()
    renderWithI18n(
      <UploadTaskList tasks={[makeTask({})]} onCancel={onCancel} onDismiss={vi.fn()} />,
    )
    fireEvent.click(screen.getByTitle('Cancel task'))
    expect(onCancel).toHaveBeenCalledWith('t1')
  })

  it('calls onDismiss for terminal task', () => {
    const onDismiss = vi.fn()
    renderWithI18n(
      <UploadTaskList
        tasks={[makeTask({ status: 'completed' })]}
        onCancel={vi.fn()}
        onDismiss={onDismiss}
      />,
    )
    fireEvent.click(screen.getByTitle('Dismiss'))
    expect(onDismiss).toHaveBeenCalledWith('t1')
  })

  it('renders result summary for completed task', () => {
    renderWithI18n(
      <UploadTaskList
        tasks={[makeTask({
          status: 'completed',
          result: { uploaded: [{ id: 'd1', name: 'a.md', chunk_count: 3 }], skipped: [], errors: [] },
        })]}
        onCancel={vi.fn()}
        onDismiss={vi.fn()}
      />,
    )
    expect(screen.getByText('1 uploaded, 0 skipped, 0 failed')).toBeInTheDocument()
  })

  it('shows queued stage for pending task', () => {
    renderWithI18n(
      <UploadTaskList
        tasks={[makeTask({ status: 'pending', stage: 'queued', chunk_total: 0, chunk_done: 0 })]}
        onCancel={vi.fn()}
        onDismiss={vi.fn()}
      />,
    )
    expect(screen.getByText('Waiting')).toBeInTheDocument()
  })
})

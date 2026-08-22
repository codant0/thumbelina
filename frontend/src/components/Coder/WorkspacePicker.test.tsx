import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { WorkspacePicker } from './WorkspacePicker'

describe('WorkspacePicker', () => {
  const onClose = vi.fn()
  const onCreated = vi.fn()

  beforeEach(() => {
    vi.restoreAllMocks()
    onClose.mockClear()
    onCreated.mockClear()
    globalThis.fetch = vi.fn(async () => ({
      ok: true,
      json: async () => ({ id: 'new-coder-id', mode: 'coder', workspace: 'C:\\ws' }),
    })) as unknown as typeof fetch
  })

  it('creates a coder conversation with the workspace path', async () => {
    render(<WorkspacePicker onClose={onClose} onCreated={onCreated} />)
    fireEvent.change(screen.getByTestId('workspace-path-input'), { target: { value: 'C:\\ws' } })
    fireEvent.click(screen.getByTestId('workspace-confirm'))
    await waitFor(() => expect(onCreated).toHaveBeenCalledWith('new-coder-id'))
    const [url, init] = (globalThis.fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0]
    expect(String(url)).toBe('/api/v1/conversations')
    expect(JSON.parse((init as RequestInit).body as string)).toEqual({ mode: 'coder', workspace: 'C:\\ws' })
  })

  it('requires a path before submitting', async () => {
    render(<WorkspacePicker onClose={onClose} onCreated={onCreated} />)
    fireEvent.click(screen.getByTestId('workspace-confirm'))
    expect(await screen.findByTestId('workspace-picker-error')).toBeInTheDocument()
    expect(onCreated).not.toHaveBeenCalled()
  })

  it('shows the server error message when creation fails', async () => {
    globalThis.fetch = vi.fn(async () => ({
      ok: false,
      json: async () => ({ detail: '工作区不是有效目录: C:\\nope' }),
    })) as unknown as typeof fetch
    render(<WorkspacePicker onClose={onClose} onCreated={onCreated} />)
    fireEvent.change(screen.getByTestId('workspace-path-input'), { target: { value: 'C:\\nope' } })
    fireEvent.click(screen.getByTestId('workspace-confirm'))
    expect(await screen.findByTestId('workspace-picker-error')).toHaveTextContent('工作区不是有效目录')
  })

  it('closes on cancel', () => {
    render(<WorkspacePicker onClose={onClose} onCreated={onCreated} />)
    fireEvent.click(screen.getByText('Cancel'))
    expect(onClose).toHaveBeenCalled()
  })

  it('hides the native picker button and shows a hint when the API is unsupported', () => {
    render(<WorkspacePicker onClose={onClose} onCreated={onCreated} />)
    expect(screen.queryByTestId('workspace-pick-native')).not.toBeInTheDocument()
    expect(screen.getByTestId('workspace-dir-unavailable')).toBeInTheDocument()
  })

  it('shows the native picker button when showDirectoryPicker exists', () => {
    const win = window as unknown as Record<string, unknown>
    const original = win.showDirectoryPicker
    win.showDirectoryPicker = vi.fn()
    try {
      render(<WorkspacePicker onClose={onClose} onCreated={onCreated} />)
      expect(screen.getByTestId('workspace-pick-native')).toBeInTheDocument()
      expect(screen.queryByTestId('workspace-dir-unavailable')).not.toBeInTheDocument()
    } finally {
      if (original === undefined) delete win.showDirectoryPicker
      else win.showDirectoryPicker = original
    }
  })

  it('fills the path from a recent workspace chip', () => {
    render(<WorkspacePicker onClose={onClose} onCreated={onCreated} recentWorkspaces={['C:\\proj\\alpha', 'D:\\other']} />)
    const chips = screen.getAllByTestId('workspace-recent-chip')
    expect(chips).toHaveLength(2)
    fireEvent.click(chips[0])
    expect((screen.getByTestId('workspace-path-input') as HTMLInputElement).value).toBe('C:\\proj\\alpha')
  })
})
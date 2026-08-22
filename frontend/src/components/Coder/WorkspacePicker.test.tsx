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
})
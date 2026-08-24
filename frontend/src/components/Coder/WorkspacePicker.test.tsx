import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { WorkspacePicker } from './WorkspacePicker'

interface DirEntry { name: string; path: string }
interface DirListing { path: string | null; parent: string | null; children: DirEntry[]; truncated: boolean }

const listing = (path: string | null, parent: string | null, names: string[], truncated = false): DirListing => ({
  path,
  parent,
  truncated,
  children: names.map(name => ({ name, path: `${path ?? ''}${name}` })),
})

// keyed by the decoded `path` query param; '' = root request
const fsResponses: Record<string, DirListing> = {
  '': listing(null, null, ['C:\\', 'D:\\']),
  'C:\\': listing('C:\\', null, ['proj']),
  'C:\\proj': listing('C:\\proj', 'C:\\', ['alpha', 'beta']),
  'D:\\': listing('D:\\', null, [], true),
}

let fsFail = false
let fsCalls: (string | null)[] = []

const okJson = (body: unknown) => ({ ok: true, json: async () => body })
const errJson = (detail: string) => ({ ok: false, json: async () => ({ detail }) })

function installMockFetch(convDetail?: string) {
  fsCalls = []
  fsFail = false
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input)
    if (url.startsWith('/api/v1/fs/dirs')) {
      const path = new URL(url, 'http://localhost').searchParams.get('path')
      fsCalls.push(path)
      if (fsFail) return errJson('boom')
      return okJson(fsResponses[path ?? ''] ?? listing(path ?? '', null, []))
    }
    if (convDetail) return errJson(convDetail)
    return okJson({ id: 'new-coder-id', mode: 'coder', workspace: 'C:\\ws' })
  }) as unknown as typeof fetch
}

function postCalls(): unknown[] {
  return (globalThis.fetch as unknown as ReturnType<typeof vi.fn>).mock.calls
    .filter(([input]) => String(input) === '/api/v1/conversations')
    .map(([, init]) => JSON.parse((init as RequestInit).body as string))
}

describe('WorkspacePicker', () => {
  const onClose = vi.fn()
  const onCreated = vi.fn()

  beforeEach(() => {
    vi.restoreAllMocks()
    localStorage.clear()
    installMockFetch()
    onClose.mockClear()
    onCreated.mockClear()
  })

  it('creates a coder conversation with the workspace path', async () => {
    render(<WorkspacePicker onClose={onClose} onCreated={onCreated} />)
    fireEvent.change(screen.getByTestId('workspace-path-input'), { target: { value: 'C:\\ws' } })
    fireEvent.click(screen.getByTestId('workspace-confirm'))
    await waitFor(() => expect(onCreated).toHaveBeenCalledWith('new-coder-id'))
    expect(postCalls()).toEqual([{ mode: 'coder', workspace: 'C:\\ws' }])
  })

  it('requires a path before submitting', async () => {
    render(<WorkspacePicker onClose={onClose} onCreated={onCreated} />)
    fireEvent.click(screen.getByTestId('workspace-confirm'))
    expect(await screen.findByTestId('workspace-picker-error')).toBeInTheDocument()
    expect(onCreated).not.toHaveBeenCalled()
  })

  it('shows the server error message when creation fails', async () => {
    installMockFetch('工作区不是有效目录: C:\\nope')
    render(<WorkspacePicker onClose={onClose} onCreated={onCreated} />)
    fireEvent.change(screen.getByTestId('workspace-path-input'), { target: { value: 'C:\\nope' } })
    fireEvent.click(screen.getByTestId('workspace-confirm'))
    expect(await screen.findByTestId('workspace-picker-error')).toHaveTextContent('工作区不是有效目录')
  })

  it('closes on cancel', async () => {
    render(<WorkspacePicker onClose={onClose} onCreated={onCreated} />)
    fireEvent.click(screen.getByText('Cancel'))
    expect(onClose).toHaveBeenCalled()
  })

  it('renders the root directory list on open', async () => {
    render(<WorkspacePicker onClose={onClose} onCreated={onCreated} />)
    const rows = await screen.findAllByTestId('workspace-dir-row')
    expect(rows.map(r => r.textContent)).toEqual(['C:\\', 'D:\\'])
    expect(screen.getByTestId('workspace-pathbar')).toHaveTextContent('Select a drive')
    expect(screen.queryByTestId('workspace-up')).not.toBeInTheDocument()
  })

  it('navigates into a directory and syncs the input', async () => {
    render(<WorkspacePicker onClose={onClose} onCreated={onCreated} />)
    const rows = await screen.findAllByTestId('workspace-dir-row')
    fireEvent.click(rows[0])
    await waitFor(() => expect(fsCalls).toContain('C:\\'))
    expect(fsCalls[0]).toBeNull()
    expect((screen.getByTestId('workspace-path-input') as HTMLInputElement).value).toBe('C:\\')
    const after = await screen.findAllByTestId('workspace-dir-row')
    expect(after.map(r => r.textContent)).toEqual(['proj'])
  })

  it('navigates up to the parent directory', async () => {
    render(<WorkspacePicker onClose={onClose} onCreated={onCreated} />)
    const rows = await screen.findAllByTestId('workspace-dir-row')
    fireEvent.click(rows[0]) // C:\
    await waitFor(() => expect((screen.getByTestId('workspace-path-input') as HTMLInputElement).value).toBe('C:\\'))
    const projRow = (await screen.findAllByTestId('workspace-dir-row'))[0]
    fireEvent.click(projRow) // C:\proj
    await waitFor(() => expect((screen.getByTestId('workspace-path-input') as HTMLInputElement).value).toBe('C:\\proj'))
    fireEvent.click(screen.getByTestId('workspace-up'))
    await waitFor(() => expect((screen.getByTestId('workspace-path-input') as HTMLInputElement).value).toBe('C:\\'))
  })

  it('confirms with the browsed path', async () => {
    render(<WorkspacePicker onClose={onClose} onCreated={onCreated} />)
    const rows = await screen.findAllByTestId('workspace-dir-row')
    fireEvent.click(rows[0]) // C:\
    await waitFor(() => expect((screen.getByTestId('workspace-path-input') as HTMLInputElement).value).toBe('C:\\'))
    const projRow = (await screen.findAllByTestId('workspace-dir-row'))[0]
    fireEvent.click(projRow) // C:\proj
    await waitFor(() => expect((screen.getByTestId('workspace-path-input') as HTMLInputElement).value).toBe('C:\\proj'))
    fireEvent.click(screen.getByTestId('workspace-confirm'))
    await waitFor(() => expect(onCreated).toHaveBeenCalledWith('new-coder-id'))
    expect(postCalls()).toEqual([{ mode: 'coder', workspace: 'C:\\proj' }])
  })

  it('shows empty and truncated hints for an unpopulated directory', async () => {
    render(<WorkspacePicker onClose={onClose} onCreated={onCreated} />)
    const rows = await screen.findAllByTestId('workspace-dir-row')
    fireEvent.click(rows[1]) // D:\
    expect(await screen.findByTestId('workspace-empty')).toBeInTheDocument()
    expect(screen.getByTestId('workspace-truncated')).toBeInTheDocument()
  })

  it('keeps manual entry working when the listing fails', async () => {
    fsFail = true
    render(<WorkspacePicker onClose={onClose} onCreated={onCreated} />)
    expect(await screen.findByTestId('workspace-browse-error')).toHaveTextContent('Failed to list directory: boom')
    fireEvent.change(screen.getByTestId('workspace-path-input'), { target: { value: 'C:\\picked' } })
    fireEvent.click(screen.getByTestId('workspace-confirm'))
    await waitFor(() => expect(onCreated).toHaveBeenCalledWith('new-coder-id'))
    expect(postCalls()).toEqual([{ mode: 'coder', workspace: 'C:\\picked' }])
  })

  it('fills the path from a recent workspace chip without browsing', async () => {
    render(<WorkspacePicker onClose={onClose} onCreated={onCreated} recentWorkspaces={['C:\\proj\\alpha', 'D:\\other']} />)
    const chips = screen.getAllByTestId('workspace-recent-chip')
    expect(chips).toHaveLength(2)
    fireEvent.click(chips[0])
    expect((screen.getByTestId('workspace-path-input') as HTMLInputElement).value).toBe('C:\\proj\\alpha')
    expect(fsCalls).toEqual([null]) // only the initial root listing happened
  })
})
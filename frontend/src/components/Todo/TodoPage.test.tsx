import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, waitFor, within, fireEvent } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { TodoPage } from './TodoPage'

type FetchHandler = (url: string, init?: RequestInit) => Response | Promise<Response>

function jsonResponse(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function mockFetch(handler: FetchHandler) {
  return vi.spyOn(globalThis, 'fetch').mockImplementation(
    async (input: RequestInfo | URL, init?: RequestInit) => handler(String(input), init),
  )
}

const SAMPLE_ITEMS = [{ index: 0, text: 'buy milk', done: false }]
const SAMPLE_NOTES = [
  { index: 0, timestamp: '2026-08-14 10:00', content: 'remember the milk' },
]

/** Default handler: module enabled, one item, one note; write ops echo sensible lists. */
function enabledHandler(
  override?: (url: string, init?: RequestInit) => Response | undefined,
): FetchHandler {
  return (url, init) => {
    const custom = override?.(url, init)
    if (custom) return custom
    const method = init?.method ?? 'GET'
    if (url === '/api/v1/todo/status') return jsonResponse({ enabled: true })
    if (url === '/api/v1/todo/items' && method === 'GET') {
      return jsonResponse({ items: SAMPLE_ITEMS })
    }
    if (url === '/api/v1/todo/notes' && method === 'GET') {
      return jsonResponse({ notes: SAMPLE_NOTES })
    }
    if (url === '/api/v1/todo/items' && method === 'POST') {
      const body = JSON.parse(String(init?.body)) as { text: string }
      return jsonResponse({
        items: [...SAMPLE_ITEMS, { index: SAMPLE_ITEMS.length, text: body.text, done: false }],
      })
    }
    if (url.startsWith('/api/v1/todo/items/') && method === 'PATCH') {
      return jsonResponse({ items: [{ index: 0, text: 'buy milk', done: true }] })
    }
    if (url.startsWith('/api/v1/todo/items/') && method === 'DELETE') {
      return jsonResponse({ items: [] })
    }
    if (url === '/api/v1/todo/notes' && method === 'POST') {
      return jsonResponse({ notes: SAMPLE_NOTES })
    }
    if (url.startsWith('/api/v1/todo/notes/') && method === 'PUT') {
      return jsonResponse({ notes: SAMPLE_NOTES })
    }
    if (url.startsWith('/api/v1/todo/notes/') && method === 'DELETE') {
      return jsonResponse({ notes: [] })
    }
    return jsonResponse({ detail: 'Not Found' }, 404)
  }
}

afterEach(() => {
  vi.restoreAllMocks()
})

describe('TodoPage', () => {
  it('renders todo and notes panels with loaded entries', async () => {
    mockFetch(enabledHandler())
    render(<TodoPage />)

    expect(await screen.findByTestId('todo-page')).toBeInTheDocument()
    expect(screen.getByTestId('todo-items-panel')).toBeInTheDocument()
    expect(screen.getByTestId('todo-notes-panel')).toBeInTheDocument()
    expect(screen.getByText('Todo List')).toBeInTheDocument()
    expect(screen.getByText('Quick Notes')).toBeInTheDocument()
    expect(screen.getByText('buy milk')).toBeInTheDocument()
    expect(screen.getByText('remember the milk')).toBeInTheDocument()
    expect(screen.getByText('2026-08-14 10:00')).toBeInTheDocument()
    // Accessibility: checkbox is labeled with the item text, textarea with its placeholder text
    expect((screen.getByLabelText('buy milk') as HTMLInputElement).type).toBe('checkbox')
    expect(screen.getByLabelText('Write a quick note…').tagName).toBe('TEXTAREA')
  })

  it('shows empty placeholders when both lists are empty', async () => {
    mockFetch(enabledHandler((url, init) => {
      const method = init?.method ?? 'GET'
      if (url === '/api/v1/todo/items' && method === 'GET') return jsonResponse({ items: [] })
      if (url === '/api/v1/todo/notes' && method === 'GET') return jsonResponse({ notes: [] })
      return undefined
    }))
    render(<TodoPage />)

    expect(await screen.findByText('No tasks yet')).toBeInTheDocument()
    expect(screen.getByText('No notes yet')).toBeInTheDocument()
  })

  it('shows degraded message when the todo module is disabled', async () => {
    mockFetch((url) => {
      if (url === '/api/v1/todo/status') return jsonResponse({ enabled: false })
      return jsonResponse({ detail: 'TODO module is not available' }, 503)
    })
    render(<TodoPage />)

    const disabled = await screen.findByTestId('todo-disabled')
    expect(disabled).toHaveTextContent('TODO module is disabled')
    expect(screen.queryByTestId('todo-page')).not.toBeInTheDocument()
  })

  it('adds a todo item via input and add button', async () => {
    const fetchSpy = mockFetch(enabledHandler())
    const user = userEvent.setup()
    render(<TodoPage />)
    await screen.findByText('buy milk')

    const input = screen.getByPlaceholderText('Add a new task…')
    await user.type(input, 'new task')
    await user.click(screen.getByText('Add'))

    await waitFor(() => {
      const post = fetchSpy.mock.calls.find(
        ([url, init]) => String(url) === '/api/v1/todo/items' && init?.method === 'POST',
      )
      expect(post).toBeDefined()
      expect(JSON.parse(String(post?.[1]?.body))).toEqual({ text: 'new task' })
    })
    expect(await screen.findByText('new task')).toBeInTheDocument()
    expect((input as HTMLInputElement).value).toBe('')
  })

  it('submits the new todo item with the Enter key', async () => {
    const fetchSpy = mockFetch(enabledHandler())
    const user = userEvent.setup()
    render(<TodoPage />)
    await screen.findByText('buy milk')

    await user.type(screen.getByPlaceholderText('Add a new task…'), 'typed task{Enter}')

    await waitFor(() => {
      const post = fetchSpy.mock.calls.find(
        ([url, init]) => String(url) === '/api/v1/todo/items' && init?.method === 'POST',
      )
      expect(post).toBeDefined()
      expect(JSON.parse(String(post?.[1]?.body))).toEqual({ text: 'typed task' })
    })
  })

  it('does not submit a blank todo item', async () => {
    const fetchSpy = mockFetch(enabledHandler())
    const user = userEvent.setup()
    render(<TodoPage />)
    await screen.findByText('buy milk')

    await user.type(screen.getByPlaceholderText('Add a new task…'), '   {Enter}')

    const post = fetchSpy.mock.calls.find(
      ([url, init]) => String(url) === '/api/v1/todo/items' && init?.method === 'POST',
    )
    expect(post).toBeUndefined()
  })

  it('sends only one request when the add button is clicked twice rapidly', async () => {
    const fetchSpy = mockFetch(enabledHandler())
    render(<TodoPage />)
    await screen.findByText('buy milk')

    const input = screen.getByPlaceholderText('Add a new task…')
    fireEvent.change(input, { target: { value: 'dup task' } })
    const addButton = screen.getByText('Add')
    fireEvent.click(addButton)
    fireEvent.click(addButton)

    await waitFor(() => {
      const posts = fetchSpy.mock.calls.filter(
        ([url, init]) => String(url) === '/api/v1/todo/items' && init?.method === 'POST',
      )
      expect(posts).toHaveLength(1)
    })
    expect(await screen.findByText('dup task')).toBeInTheDocument()
  })

  it('cancels inline editing when another action refreshes the items list', async () => {
    const refreshed = [
      { index: 0, text: 'task b', done: false },
      { index: 1, text: 'task c', done: false },
    ]
    const fetchSpy = mockFetch(enabledHandler((url, init) => {
      const method = init?.method ?? 'GET'
      if (url === '/api/v1/todo/items' && method === 'GET') {
        return jsonResponse({
          items: [
            { index: 0, text: 'task a', done: false },
            { index: 1, text: 'task b', done: false },
            { index: 2, text: 'task c', done: false },
          ],
        })
      }
      if (url === '/api/v1/todo/items/0' && method === 'DELETE') {
        return jsonResponse({ items: refreshed })
      }
      return undefined
    }))
    const user = userEvent.setup()
    render(<TodoPage />)
    const rows = await screen.findAllByTestId('todo-item')
    expect(rows).toHaveLength(3)

    await user.click(within(rows[1]).getByText('Edit'))
    expect(screen.getByDisplayValue('task b').tagName).toBe('INPUT')

    await user.click(within(rows[0]).getByText('Delete'))

    await waitFor(() => {
      const del = fetchSpy.mock.calls.find(
        ([url, init]) => init?.method === 'DELETE' && String(url) === '/api/v1/todo/items/0',
      )
      expect(del).toBeDefined()
    })
    // The edit box must disappear instead of attaching to the item that
    // shifted into the edited position after server-side re-indexing.
    await waitFor(() => expect(screen.queryByDisplayValue('task b')).toBeNull())
    expect(screen.getByText('task b')).toBeInTheDocument()
    expect(screen.getAllByTestId('todo-item')).toHaveLength(2)
  })

  it('toggles a todo item done via checkbox with PATCH done:true', async () => {
    const fetchSpy = mockFetch(enabledHandler())
    const user = userEvent.setup()
    render(<TodoPage />)

    const checkbox = (await screen.findByRole('checkbox')) as HTMLInputElement
    expect(checkbox.checked).toBe(false)
    await user.click(checkbox)

    await waitFor(() => {
      const patch = fetchSpy.mock.calls.find(([, init]) => init?.method === 'PATCH')
      expect(patch?.[0]).toBe('/api/v1/todo/items/0')
      expect(JSON.parse(String(patch?.[1]?.body))).toEqual({ done: true })
    })
    await waitFor(() => expect(checkbox.checked).toBe(true))
  })

  it('deletes a note via the note card delete button', async () => {
    const fetchSpy = mockFetch(enabledHandler())
    const user = userEvent.setup()
    render(<TodoPage />)

    const note = await screen.findByTestId('todo-note')
    await user.click(within(note).getByTestId('note-delete'))

    await waitFor(() => {
      const del = fetchSpy.mock.calls.find(
        ([url, init]) => init?.method === 'DELETE' && String(url).startsWith('/api/v1/todo/notes/'),
      )
      expect(del?.[0]).toBe('/api/v1/todo/notes/0')
    })
    expect(await screen.findByText('No notes yet')).toBeInTheDocument()
  })

  it('shows an error state when data loading fails with 500', async () => {
    mockFetch((url) => {
      if (url === '/api/v1/todo/status') return jsonResponse({ enabled: true })
      return jsonResponse({ detail: 'boom' }, 500)
    })
    render(<TodoPage />)

    expect(await screen.findByTestId('todo-error')).toBeInTheDocument()
  })

  it('does not crash when the status request rejects', async () => {
    mockFetch(() => Promise.reject(new Error('network down')))
    render(<TodoPage />)

    expect(await screen.findByTestId('todo-error')).toBeInTheDocument()
    expect(screen.queryByTestId('todo-page')).not.toBeInTheDocument()
  })

  it('keeps existing items and shows an error when adding fails', async () => {
    mockFetch(enabledHandler((url, init) => {
      if (url === '/api/v1/todo/items' && init?.method === 'POST') {
        return jsonResponse({ detail: 'storage unavailable' }, 500)
      }
      return undefined
    }))
    const user = userEvent.setup()
    render(<TodoPage />)
    await screen.findByText('buy milk')

    await user.type(screen.getByPlaceholderText('Add a new task…'), 'oops')
    await user.click(screen.getByText('Add'))

    expect(await screen.findByTestId('todo-error')).toBeInTheDocument()
    expect(screen.getByText('buy milk')).toBeInTheDocument()
  })

  it('renders stats bar with correct counts', async () => {
    mockFetch(enabledHandler((url, init) => {
      const method = init?.method ?? 'GET'
      if (url === '/api/v1/todo/items' && method === 'GET') {
        return jsonResponse({
          items: [
            { index: 0, text: 'task a', done: false },
            { index: 1, text: 'task b', done: true },
          ],
        })
      }
      if (url === '/api/v1/todo/notes' && method === 'GET') {
        return jsonResponse({
          notes: [
            { index: 0, timestamp: '2026-08-14 10:00', content: 'note a' },
            { index: 1, timestamp: '2026-08-14 11:00', content: 'note b' },
            { index: 2, timestamp: '2026-08-14 12:00', content: 'note c' },
          ],
        })
      }
      return undefined
    }))
    const { container } = render(<TodoPage />)
    await screen.findByTestId('todo-page')

    const stats = container.querySelector('.todo-stats')
    expect(stats).not.toBeNull()
    expect(stats).toHaveTextContent('1 pending')
    expect(stats).toHaveTextContent('1 completed')
    expect(stats).toHaveTextContent('3 notes')
    const progressbar = screen.getByRole('progressbar')
    expect(progressbar).toHaveAttribute('aria-valuenow', '50')
    expect(progressbar).toHaveAttribute('aria-valuemin', '0')
    expect(progressbar).toHaveAttribute('aria-valuemax', '100')
  })

  it('stats bar shows zero state', async () => {
    mockFetch(enabledHandler((url, init) => {
      const method = init?.method ?? 'GET'
      if (url === '/api/v1/todo/items' && method === 'GET') return jsonResponse({ items: [] })
      if (url === '/api/v1/todo/notes' && method === 'GET') return jsonResponse({ notes: [] })
      return undefined
    }))
    const { container } = render(<TodoPage />)
    await screen.findByTestId('todo-page')

    const stats = container.querySelector('.todo-stats')
    expect(stats).not.toBeNull()
    expect(stats).toHaveTextContent('0 pending')
    expect(stats).toHaveTextContent('0 completed')
    expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '0')
  })

  it('loading renders skeletons', async () => {
    // Fetch never resolves, so the page stays in its loading state.
    mockFetch(() => new Promise<Response>(() => undefined))
    const { container } = render(<TodoPage />)

    await screen.findByTestId('todo-loading')
    expect(container.querySelectorAll('.todo-skeleton').length).toBeGreaterThan(0)
    expect(screen.queryByRole('progressbar')).not.toBeInTheDocument()
  })
})

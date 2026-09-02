import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, act, renderHook } from '@testing-library/react'
import { TaskManager } from './TaskManager'
import { useWebSocket, subscribeTaskEvents, type TaskEventPayload } from '../../hooks/useWebSocket'
import type { ScheduledTaskVO } from '../../api/tasks'

// ---------------------------------------------------------------------------
// fixtures
// ---------------------------------------------------------------------------

function makeTask(overrides: Partial<ScheduledTaskVO> = {}): ScheduledTaskVO {
  return {
    id: 't-1',
    description: 'water the plants',
    scheduled_time: '2026-08-30T10:00:00',
    status: 'pending',
    trigger: 'once',
    cron: null,
    next_run: null,
    last_run: null,
    channel: 'web',
    content: 'remember to water the plants',
    mode: 'notify',
    source: 'agent',
    error: null,
    ...overrides,
  }
}

const CRON_TASK = makeTask({
  id: 't-cron',
  description: 'hourly report',
  scheduled_time: null,
  trigger: 'cron',
  cron: '*/5 * * * *',
  next_run: '2026-08-30T12:00:00',
})

function json(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), { status })
}

interface FetchCall {
  url: string
  init?: RequestInit
}

/** Route mock fetch responses per endpoint and record every call. */
function setupFetch(overrides: {
  subagents?: unknown
  tasks?: unknown
  events?: unknown
  scheduler?: unknown
  /** Per-test GET /tasks/{id} detail; 404 otherwise. */
  taskDetail?: unknown
  /** Per-test POST /tasks/{id}/{action} body; otherwise the action fetch
   *  falls through to the list route (which still returns 200 for POST). */
  actionResult?: unknown
} = {}): FetchCall[] {
  const calls: FetchCall[] = []
  vi.spyOn(globalThis, 'fetch').mockImplementation((url: string | URL | Request, init?: RequestInit) => {
    const urlStr = typeof url === 'string' ? url : url.toString()
    calls.push({ url: urlStr, init })
    if (urlStr.includes('/api/v1/subagents')) {
      return Promise.resolve(json(overrides.subagents ?? []))
    }
    if (urlStr.includes('/api/v1/tasks/scheduler/status')) {
      return Promise.resolve(json(overrides.scheduler ?? { running: false, last_heartbeat_at: null, task_counts: {}, checks: {} }))
    }
    if (urlStr.includes('/api/v1/tasks/events')) {
      return Promise.resolve(json(overrides.events ?? []))
    }
    // GET /api/v1/tasks/{id} → detail view; must come BEFORE the action POST
    // matcher because the action URLs also share the prefix.
    if (init?.method !== 'POST' && /\/api\/v1\/tasks\/[A-Za-z0-9_-]+$/.test(urlStr)) {
      const taskDetail = overrides.taskDetail
      if (taskDetail !== undefined) {
        return Promise.resolve(json(taskDetail))
      }
      return Promise.resolve(json({ detail: 'Task not found' }, 404))
    }
    // POST /api/v1/tasks/{id}/{action} → return the action-specific body.
    if (init?.method === 'POST' && overrides.actionResult !== undefined) {
      return Promise.resolve(json(overrides.actionResult))
    }
    if (urlStr.includes('/api/v1/tasks')) {
      return Promise.resolve(json(overrides.tasks ?? []))
    }
    return Promise.resolve(json([]))
  })
  return calls
}

function listFetchCount(calls: FetchCall[]): number {
  return calls.filter(c => c.url.endsWith('/api/v1/tasks')).length
}

/** Drain the mocked fetch promise chains so setStates land inside act(). */
async function flushAsync(): Promise<void> {
  for (let i = 0; i < 20; i++) await Promise.resolve()
}

// Minimal WebSocket double so a real useWebSocket instance can be driven in
// tests (frames injected via simulateMessage).
class MockWebSocket {
  static instances: MockWebSocket[] = []
  static CONNECTING = 0
  static OPEN = 1
  static CLOSING = 2
  static CLOSED = 3
  onopen: ((event: Event) => void) | null = null
  onmessage: ((event: MessageEvent) => void) | null = null
  onclose: ((event: CloseEvent) => void) | null = null
  onerror: ((event: Event) => void) | null = null
  readyState = 0
  sentMessages: string[] = []
  url: string

  constructor(url: string) {
    this.url = url
    MockWebSocket.instances.push(this)
    setTimeout(() => {
      this.readyState = 1
      this.onopen?.(new Event('open'))
    }, 0)
  }

  send(data: string) {
    this.sentMessages.push(data)
  }

  close() {
    this.readyState = 3
  }

  simulateMessage(data: string) {
    this.onmessage?.(new MessageEvent('message', { data }))
  }
}

describe('TaskManager', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    setupFetch()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('should render task manager', async () => {
    render(<TaskManager />)
    await act(async () => {})
    expect(screen.getByTestId('task-manager')).toBeInTheDocument()
  })

  it('should render subagent list section', async () => {
    render(<TaskManager />)
    await act(async () => {})
    expect(screen.getByTestId('subagent-list')).toBeInTheDocument()
  })

  it('should render task list section', async () => {
    render(<TaskManager />)
    await act(async () => {})
    expect(screen.getByTestId('task-list')).toBeInTheDocument()
  })

  it('should show empty state for subagents', async () => {
    render(<TaskManager />)
    await act(async () => {})
    expect(screen.getByText('No active subagents')).toBeInTheDocument()
  })

  it('should show empty state for tasks', async () => {
    render(<TaskManager />)
    await act(async () => {})
    expect(screen.getByText('No scheduled tasks')).toBeInTheDocument()
  })

  // -----------------------------------------------------------------------
  // trigger / channel / status badges
  // -----------------------------------------------------------------------

  it('renders a cron trigger badge with the expression and next run time', async () => {
    setupFetch({ tasks: [CRON_TASK] })
    render(<TaskManager />)
    await act(async () => {})
    const trigger = screen.getAllByTestId('task-trigger')[0]
    expect(trigger).toHaveTextContent('Cron')
    expect(trigger).toHaveTextContent('*/5 * * * *')
    expect(screen.getByTestId('task-next-run')).toHaveTextContent(
      new Date('2026-08-30T12:00:00').toLocaleString(),
    )
  })

  it('renders a once trigger badge and the channel badge', async () => {
    setupFetch({ tasks: [makeTask()] })
    render(<TaskManager />)
    await act(async () => {})
    expect(screen.getByTestId('task-trigger')).toHaveTextContent('Once')
    expect(screen.getByTestId('task-channel')).toHaveTextContent('web')
  })

  it('keeps full content in the DOM for the detail modal (no 80-char JS slice)', async () => {
    const longContent = 'x'.repeat(200)
    setupFetch({ tasks: [makeTask({ content: longContent })] })
    render(<TaskManager />)
    await act(async () => {})
    const summary = screen.getByTestId('task-content')
    // CSS line-clamp hides the overflow visually but the DOM still carries the
    // full string — the detail modal reads from this text, not a truncated copy.
    expect(summary.textContent).toHaveLength(200)
  })

  it('opens the task detail modal when a row is clicked (and renders the full content)', async () => {
    const full = '## full markdown\n\n- a\n- b\n\n```\ncode\n```'
    const detail = {
      ...makeTask({ content: full }),
      result: 'reply body',
      created_at: '2026-08-30T09:00:00',
      updated_at: '2026-08-30T09:00:00',
    }
    setupFetch({ tasks: [makeTask({ content: full })], taskDetail: detail })
    render(<TaskManager />)
    await act(async () => {})
    await act(async () => { fireEvent.click(screen.getByTestId('task-item')) })
    // Detail modal fetched the full content + result; Markdown renders the
    // heading markup (no 80-char truncation anywhere).
    const body = await screen.findByTestId('detail-body')
    expect(body.textContent).toContain('full markdown')
    expect(body.textContent).toContain('reply body')
  })

  it('shows failed / paused / missed status badges with distinct colors', async () => {
    setupFetch({
      tasks: [
        makeTask({ id: 't-failed', description: 'f', status: 'failed' }),
        makeTask({ id: 't-paused', description: 'p', status: 'paused', trigger: 'cron', cron: '*/5 * * * *' }),
        makeTask({ id: 't-missed', description: 'm', status: 'missed' }),
      ],
    })
    render(<TaskManager />)
    await act(async () => {})
    const badges = screen.getAllByTestId('task-status')
    const failed = badges.find(b => b.textContent === 'failed')
    const paused = badges.find(b => b.textContent === 'paused')
    const missed = badges.find(b => b.textContent === 'missed')
    expect(failed?.className).toContain('badge-error')
    expect(paused?.className).toContain('badge-orange')
    expect(missed?.className).toContain('badge-orange')
  })

  // -----------------------------------------------------------------------
  // actions
  // -----------------------------------------------------------------------

  it('pause button POSTs /tasks/{id}/pause and refreshes', async () => {
    const overrides: { tasks?: unknown } = { tasks: [CRON_TASK] }
    const calls = setupFetch(overrides)
    render(<TaskManager />)
    await act(async () => {})
    overrides.tasks = [{ ...CRON_TASK, status: 'paused' }]
    await act(async () => {
      fireEvent.click(screen.getByTestId('pause-task'))
      await flushAsync()
    })
    const pauseIdx = calls.findIndex(c => c.url === '/api/v1/tasks/t-cron/pause')
    expect(pauseIdx).toBeGreaterThanOrEqual(0)
    expect(calls[pauseIdx].init?.method).toBe('POST')
    // refresh after the action (POST → list refetch lands asynchronously).
    await act(async () => {})
    expect(calls.slice(pauseIdx + 1).some(c => c.url === '/api/v1/tasks')).toBe(true)
  })

  it('resume button POSTs /tasks/{id}/resume and refreshes', async () => {
    const overrides: { tasks?: unknown } = {
      tasks: [makeTask({ trigger: 'cron', cron: '*/5 * * * *', status: 'paused' })],
    }
    const calls = setupFetch(overrides)
    render(<TaskManager />)
    await act(async () => {})
    overrides.tasks = [CRON_TASK]
    await act(async () => {
      fireEvent.click(screen.getByTestId('resume-task'))
      await flushAsync()
    })
    const resumeIdx = calls.findIndex(c => c.url === '/api/v1/tasks/t-1/resume')
    expect(resumeIdx).toBeGreaterThanOrEqual(0)
    expect(calls[resumeIdx].init?.method).toBe('POST')
    await act(async () => {})
    expect(calls.slice(resumeIdx + 1).some(c => c.url === '/api/v1/tasks')).toBe(true)
  })

  it('cancel button POSTs /tasks/{id}/cancel for pending tasks', async () => {
    const calls = setupFetch({ tasks: [makeTask()] })
    render(<TaskManager />)
    await act(async () => {})
    await act(async () => { fireEvent.click(screen.getByTestId('cancel-task')) })
    const cancel = calls.find(c => c.url === '/api/v1/tasks/t-1/cancel')
    expect(cancel?.init?.method).toBe('POST')
  })

  it('hides action buttons for terminal states', async () => {
    setupFetch({ tasks: [makeTask({ status: 'completed' })] })
    render(<TaskManager />)
    await act(async () => {})
    expect(screen.queryByTestId('cancel-task')).not.toBeInTheDocument()
    expect(screen.queryByTestId('pause-task')).not.toBeInTheDocument()
    expect(screen.queryByTestId('resume-task')).not.toBeInTheDocument()
  })

  // -----------------------------------------------------------------------
  // scheduler aliveness indicator
  // -----------------------------------------------------------------------

  it('shows a green scheduler pill when the heartbeat is running', async () => {
    setupFetch({ scheduler: { running: true, last_heartbeat_at: null, task_counts: {}, checks: {} } })
    render(<TaskManager />)
    await act(async () => {})
    const pill = screen.getByTestId('scheduler-status')
    expect(pill.getAttribute('title')).toBe('Scheduler running')
    expect(pill.className).toContain('scheduler-pill--alive')
    expect(pill.textContent).toContain('Scheduler running')
  })

  it('shows a neutral scheduler pill when the heartbeat is down', async () => {
    setupFetch({ scheduler: { running: false, last_heartbeat_at: null, task_counts: {}, checks: {} } })
    render(<TaskManager />)
    await act(async () => {})
    const pill = screen.getByTestId('scheduler-status')
    expect(pill.getAttribute('title')).toBe('Scheduler offline')
    expect(pill.className).not.toContain('scheduler-pill--alive')
    expect(pill.textContent).toContain('Scheduler offline')
  })

  it('opens the task detail modal when a row is activated with the keyboard', async () => {
    const detail = {
      ...makeTask(),
      result: 'reply body',
      created_at: '2026-08-30T09:00:00',
      updated_at: '2026-08-30T09:00:00',
    }
    setupFetch({ tasks: [makeTask()], taskDetail: detail })
    render(<TaskManager />)
    await act(async () => {})
    await act(async () => { fireEvent.keyDown(screen.getByTestId('task-item'), { key: 'Enter' }) })
    expect(await screen.findByTestId('detail-body')).toBeInTheDocument()
  })

  it('filters the task list by status chips', async () => {
    setupFetch({
      tasks: [
        makeTask({ id: 't-pending', description: 'p', status: 'pending' }),
        makeTask({ id: 't-completed', description: 'c', status: 'completed' }),
        makeTask({ id: 't-failed', description: 'f', status: 'failed' }),
      ],
    })
    render(<TaskManager />)
    await act(async () => {})
    expect(screen.getAllByTestId('task-item')).toHaveLength(3)

    await act(async () => { fireEvent.click(screen.getByTestId('task-filter-completed')) })
    const items = screen.getAllByTestId('task-item')
    expect(items).toHaveLength(1)
    expect(items[0]).toHaveTextContent('c')

    await act(async () => { fireEvent.click(screen.getByTestId('task-filter-all')) })
    expect(screen.getAllByTestId('task-item')).toHaveLength(3)
  })

  it('opens the subagent result modal when the row has a result', async () => {
    setupFetch({
      subagents: [{
        id: 'a-1',
        task: 'summarize this article',
        status: 'completed',
        result: '## summary\n\n- key point 1\n- key point 2',
      }],
    })
    render(<TaskManager />)
    await act(async () => {})
    await act(async () => { fireEvent.click(screen.getByTestId('view-subagent-result')) })
    expect(await screen.findByTestId('modal')).toBeInTheDocument()
    // Markdown rendering of the full result (no 80-char slice).
    const modal = screen.getByTestId('modal')
    expect(modal.textContent).toContain('key point 1')
    expect(modal.textContent).toContain('key point 2')
  })

  // -----------------------------------------------------------------------
  // WebSocket task_event driven refresh
  // -----------------------------------------------------------------------

  it('refreshes the task list when a task_event WS frame arrives (throttled to 500ms)', async () => {
    vi.useFakeTimers()
    const originalWS = globalThis.WebSocket
    globalThis.WebSocket = MockWebSocket as unknown as typeof WebSocket
    MockWebSocket.instances = []
    const calls = setupFetch({ tasks: [makeTask()] })
    try {
      render(<TaskManager />)
      renderHook(() => useWebSocket('ws://localhost/ws/chat'))
      await act(async () => { vi.advanceTimersByTime(10) }) // open the socket
      await act(async () => {}) // flush initial fetches
      const before = listFetchCount(calls)

      const frame: TaskEventPayload = {
        id: 'e-1',
        type: 'task.completed',
        task_id: 't-1',
        fired_at: '2026-08-30T12:00:00',
        trigger: 'once',
        channel: 'web',
        content: 'hello',
        payload: null,
      }
      // Leading edge: the first frame refreshes immediately.
      await act(async () => {
        MockWebSocket.instances[0].simulateMessage(JSON.stringify({ task_event: frame }))
        await flushAsync()
      })
      expect(listFetchCount(calls)).toBe(before + 1)

      // Burst within the throttle window collapses into one trailing refresh.
      await act(async () => {
        MockWebSocket.instances[0].simulateMessage(JSON.stringify({ task_event: { ...frame, id: 'e-2' } }))
        MockWebSocket.instances[0].simulateMessage(JSON.stringify({ task_event: { ...frame, id: 'e-3' } }))
        vi.advanceTimersByTime(500)
        await flushAsync()
      })
      expect(listFetchCount(calls)).toBe(before + 2)
    } finally {
      globalThis.WebSocket = originalWS
      vi.useRealTimers()
    }
  })

  it('isolates listener exceptions when dispatching task_event frames', async () => {
    vi.useFakeTimers()
    const originalWS = globalThis.WebSocket
    globalThis.WebSocket = MockWebSocket as unknown as typeof WebSocket
    MockWebSocket.instances = []
    const calls = setupFetch({ tasks: [makeTask()] })
    const unsub = subscribeTaskEvents(() => { throw new Error('listener boom') })
    try {
      render(<TaskManager />)
      renderHook(() => useWebSocket('ws://localhost/ws/chat'))
      await act(async () => { vi.advanceTimersByTime(10) })
      await act(async () => {})
      const before = listFetchCount(calls)

      const frame: TaskEventPayload = {
        id: 'e-9',
        type: 'task.due',
        task_id: 't-1',
        fired_at: '2026-08-30T12:00:00',
        trigger: 'once',
        channel: 'web',
        content: 'hello',
        payload: null,
      }
      // A throwing listener must not break the dispatch to other listeners:
      // the frame dispatch completes and TaskManager still refreshes.
      await act(async () => {
        MockWebSocket.instances[0].simulateMessage(JSON.stringify({ task_event: frame }))
        await flushAsync()
      })
      expect(listFetchCount(calls)).toBe(before + 1)
    } finally {
      unsub()
      globalThis.WebSocket = originalWS
      vi.useRealTimers()
    }
  })
})

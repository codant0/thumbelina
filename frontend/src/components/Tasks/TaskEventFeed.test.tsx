import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, act, renderHook } from '@testing-library/react'
import { TaskEventFeed } from './TaskEventFeed'
import { useWebSocket, type TaskEventPayload } from '../../hooks/useWebSocket'
import type { TaskEventVO } from '../../api/tasks'

const EVENTS: TaskEventVO[] = [
  {
    id: 'e-1',
    type: 'task.completed',
    task_id: 't-1',
    fired_at: '2026-08-30T12:00:05',
    trigger: 'cron',
    channel: 'web',
    content: 'hourly report delivered',
    payload: null,
  },
  {
    id: 'e-2',
    type: 'task.failed',
    task_id: 't-2',
    fired_at: '2026-08-30T11:00:05',
    trigger: 'once',
    channel: 'wechat',
    content: 'one-shot reminder',
    payload: { error: 'channel not configured' },
  },
]

function json(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), { status })
}

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

function frame(overrides: Partial<TaskEventPayload> = {}): TaskEventPayload {
  return {
    id: `e-${Math.random().toString(36).slice(2)}`,
    type: 'task.due',
    task_id: 't-1',
    fired_at: '2026-08-30T12:00:00',
    trigger: 'cron',
    channel: 'web',
    content: 'live frame',
    payload: null,
    ...overrides,
  }
}

describe('TaskEventFeed', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('fetches the last 50 events and renders rows', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(json(EVENTS))
    render(<TaskEventFeed />)
    await act(async () => {})
    expect(fetchSpy.mock.calls[0][0]).toBe('/api/v1/tasks/events?limit=50')
    expect(screen.getByTestId('event-feed')).toBeInTheDocument()
    const items = screen.getAllByTestId('event-item')
    expect(items).toHaveLength(2)
    expect(screen.getByText('hourly report delivered')).toBeInTheDocument()
    expect(screen.getByText('one-shot reminder')).toBeInTheDocument()
    const typeBadges = screen.getAllByTestId('event-type')
    expect(typeBadges[0]).toHaveTextContent('task.completed')
    expect(typeBadges[1]).toHaveTextContent('task.failed')
    const channels = screen.getAllByTestId('event-channel')
    expect(channels[0]).toHaveTextContent('web')
    expect(channels[1]).toHaveTextContent('wechat')
    // newest first (backend returns descending order)
    expect(items[0]).toHaveTextContent('hourly report delivered')
    // localized timestamps rendered
    expect(screen.getByText(new Date('2026-08-30T12:00:05').toLocaleString())).toBeInTheDocument()
  })

  it('renders payload error in red', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(json(EVENTS))
    render(<TaskEventFeed />)
    await act(async () => {})
    const err = screen.getByTestId('event-error')
    expect(err).toHaveTextContent('channel not configured')
    expect(err.style.color).toContain('--error')
  })

  it('renders the payload result summary in the success color', async () => {
    const withResult: TaskEventVO[] = [
      {
        id: 'e-3',
        type: 'task.completed',
        task_id: 't-3',
        fired_at: '2026-08-30T12:00:05',
        trigger: 'once',
        channel: 'web',
        content: 'briefing',
        payload: { result: '早安简报已生成，今日天气晴，气温 20–28℃。' },
      },
    ]
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(json(withResult))
    render(<TaskEventFeed />)
    await act(async () => {})
    const result = screen.getByTestId('event-result')
    expect(result).toHaveTextContent('早安简报已生成，今日天气晴，气温 20–28℃。')
    expect(result.style.color).toContain('--success')
    expect(screen.queryByTestId('event-error')).toBeNull()
  })

  it('truncates a long payload result at 80 characters', async () => {
    const longResult = 'x'.repeat(200)
    const withLongResult: TaskEventVO[] = [
      {
        id: 'e-4',
        type: 'task.completed',
        task_id: 't-4',
        fired_at: '2026-08-30T12:00:05',
        trigger: 'once',
        channel: 'web',
        content: 'long briefing',
        payload: { result: longResult },
      },
    ]
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(json(withLongResult))
    render(<TaskEventFeed />)
    await act(async () => {})
    const result = screen.getByTestId('event-result')
    const text = result.textContent ?? ''
    expect(text.length).toBeLessThanOrEqual(80)
    // 80 字符含省略号:截断到 max-1 个字符 + '…'。
    expect(text).toBe(`${'x'.repeat(79)}…`)
  })

  it('shows the empty state when there are no events', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(json([]))
    render(<TaskEventFeed />)
    await act(async () => {})
    expect(screen.getByText('No events yet')).toBeInTheDocument()
  })

  it('prepends live task_event frames at the head and caps the list at 50', async () => {
    vi.useFakeTimers()
    const originalWS = globalThis.WebSocket
    globalThis.WebSocket = MockWebSocket as unknown as typeof WebSocket
    MockWebSocket.instances = []
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(json([]))
    try {
      render(<TaskEventFeed />)
      renderHook(() => useWebSocket('ws://localhost/ws/chat'))
      await act(async () => { vi.advanceTimersByTime(10) })
      await act(async () => {})

      const push = (f: TaskEventPayload) => {
        act(() => { MockWebSocket.instances[0].simulateMessage(JSON.stringify({ task_event: f })) })
      }
      for (let i = 0; i < 55; i++) {
        push(frame({ id: `live-${i}`, content: `live ${i}` }))
      }
      await act(async () => {})

      const items = screen.getAllByTestId('event-item')
      expect(items).toHaveLength(50)
      // newest frame first
      expect(items[0]).toHaveTextContent('live 54')
      expect(items[49]).toHaveTextContent('live 5')
    } finally {
      globalThis.WebSocket = originalWS
      vi.useRealTimers()
    }
  })

  it('prepends a live frame above previously fetched events', async () => {
    vi.useFakeTimers()
    const originalWS = globalThis.WebSocket
    globalThis.WebSocket = MockWebSocket as unknown as typeof WebSocket
    MockWebSocket.instances = []
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(json(EVENTS))
    try {
      render(<TaskEventFeed />)
      renderHook(() => useWebSocket('ws://localhost/ws/chat'))
      await act(async () => { vi.advanceTimersByTime(10) })
      await act(async () => {})

      act(() => {
        MockWebSocket.instances[0].simulateMessage(
          JSON.stringify({ task_event: frame({ id: 'live-1', content: 'fresh frame' }) }),
        )
      })
      await act(async () => {})

      const items = screen.getAllByTestId('event-item')
      expect(items).toHaveLength(3)
      expect(items[0]).toHaveTextContent('fresh frame')
      expect(screen.queryByTestId('event-error')).toBeInTheDocument() // from fixture e-2
    } finally {
      globalThis.WebSocket = originalWS
      vi.useRealTimers()
    }
  })
})

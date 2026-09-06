import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { useWebSocket } from './useWebSocket'
import type { Message } from '../types/chat'

// Mock WebSocket
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
  readyState = 0 // CONNECTING
  sentMessages: string[] = []
  url: string

  constructor(url: string) {
    this.url = url
    MockWebSocket.instances.push(this)
    setTimeout(() => {
      this.readyState = 1 // OPEN
      this.onopen?.(new Event('open'))
    }, 0)
  }

  send(data: string) {
    this.sentMessages.push(data)
  }

  close() {
    this.readyState = 3 // CLOSED
    this.onclose?.(new CloseEvent('close'))
  }

  simulateMessage(data: string) {
    this.onmessage?.(new MessageEvent('message', { data }))
  }

  simulateError() {
    this.onerror?.(new Event('error'))
  }
}

describe('useWebSocket', () => {
  let originalWebSocket: typeof globalThis.WebSocket
  let originalFetch: typeof globalThis.fetch

  beforeEach(() => {
    originalWebSocket = globalThis.WebSocket
    globalThis.WebSocket = MockWebSocket as unknown as typeof WebSocket
    originalFetch = globalThis.fetch
    MockWebSocket.instances = []
  })

  afterEach(() => {
    globalThis.WebSocket = originalWebSocket
    globalThis.fetch = originalFetch
    vi.useRealTimers()
  })

  it('should connect to WebSocket on mount', () => {
    renderHook(() => useWebSocket('ws://localhost:8000/ws/chat'))

    expect(MockWebSocket.instances).toHaveLength(1)
    expect(MockWebSocket.instances[0].url).toBe('ws://localhost:8000/ws/chat')
  })

  it('should set isConnected to true when connected', async () => {
    const { result } = renderHook(() => useWebSocket('ws://localhost:8000/ws/chat'))

    expect(result.current.isConnected).toBe(false)

    await act(async () => {
      await new Promise(resolve => setTimeout(resolve, 10))
    })

    expect(result.current.isConnected).toBe(true)
  })

  it('should send messages through WebSocket as JSON', async () => {
    const { result } = renderHook(() => useWebSocket('ws://localhost:8000/ws/chat'))

    await act(async () => {
      await new Promise(resolve => setTimeout(resolve, 50))
    })

    expect(result.current.isConnected).toBe(true)

    await act(async () => {
      result.current.sendMessage('Hello')
    })

    const sent = JSON.parse(MockWebSocket.instances[0].sentMessages[0])
    expect(sent.message).toBe('Hello')
  })

  it('should receive streaming chunks and display via typewriter', async () => {
    vi.useFakeTimers()
    const { result } = renderHook(() => useWebSocket('ws://localhost:8000/ws/chat'))

    await act(async () => {
      vi.advanceTimersByTime(10)
    })

    act(() => {
      MockWebSocket.instances[0].simulateMessage(JSON.stringify({ chunk: 'Hello world' }))
    })

    expect(result.current.messages).toHaveLength(1)
    expect(result.current.messages[0].role).toBe('assistant')

    // Advance typewriter to reveal all characters
    await act(async () => {
      vi.advanceTimersByTime(500)
    })
    expect(result.current.messages[0].content).toBe('Hello world')

    // Send done
    act(() => {
      MockWebSocket.instances[0].simulateMessage(JSON.stringify({ done: true }))
    })
    await act(async () => {
      vi.advanceTimersByTime(100)
    })
    expect(result.current.isStreaming).toBe(false)
  })

  it('typewriter accelerates: 11-char chunk fully revealed within 150ms (was ~120-150ms at the old 30ms/3-chars cadence)', async () => {
    vi.useFakeTimers()
    const { result } = renderHook(() => useWebSocket('ws://localhost:8000/ws/chat'))

    await act(async () => {
      vi.advanceTimersByTime(10)
    })

    act(() => {
      MockWebSocket.instances[0].simulateMessage(JSON.stringify({ chunk: 'Hello world' }))
    })

    // Old cadence (3 chars / 30ms) would need ~120ms; new staircase (5/6/3 at 18ms)
    // reaches 11 chars well within 150ms. Use a tight window to catch regressions.
    await act(async () => {
      vi.advanceTimersByTime(150)
    })
    expect(result.current.messages[0].content).toBe('Hello world')
  })

  it('should handle non-streaming response immediately', async () => {
    const { result } = renderHook(() => useWebSocket('ws://localhost:8000/ws/chat'))

    await act(async () => {
      await new Promise(resolve => setTimeout(resolve, 50))
    })

    act(() => {
      MockWebSocket.instances[0].simulateMessage(JSON.stringify({ response: 'Hello' }))
    })

    expect(result.current.messages).toHaveLength(1)
    expect(result.current.messages[0].role).toBe('assistant')
    expect(result.current.messages[0].content).toBe('Hello')
  })

  it('should handle error messages', async () => {
    const { result } = renderHook(() => useWebSocket('ws://localhost:8000/ws/chat'))

    await act(async () => {
      await new Promise(resolve => setTimeout(resolve, 50))
    })

    act(() => {
      MockWebSocket.instances[0].simulateMessage(JSON.stringify({ error: 'Something went wrong' }))
    })

    expect(result.current.messages).toHaveLength(1)
    expect(result.current.messages[0].role).toBe('system')
    expect(result.current.messages[0].content).toContain('Something went wrong')
  })

  it('should clean up WebSocket on unmount', async () => {
    const { unmount } = renderHook(() => useWebSocket('ws://localhost:8000/ws/chat'))

    await act(async () => {
      await new Promise(resolve => setTimeout(resolve, 50))
    })

    unmount()

    expect(MockWebSocket.instances[0].readyState).toBe(3) // CLOSED
  })

  it('should not lock other conversations while one is streaming', async () => {
    vi.useFakeTimers()
    const { result, rerender } = renderHook(
      ({ conv }: { conv?: string }) => useWebSocket('ws://localhost:8000/ws/chat', conv),
      { initialProps: { conv: 'A' as string | undefined } },
    )

    await act(async () => {
      vi.advanceTimersByTime(10)
    })

    // Send and start streaming in conversation A
    act(() => {
      result.current.sendMessage('hello A', 'A')
    })
    expect(result.current.waitingForReply).toBe(true)

    act(() => {
      MockWebSocket.instances[0].simulateMessage(
        JSON.stringify({ chunk: 'answering A...', conversation_id: 'A' }),
      )
    })
    expect(result.current.isStreaming).toBe(true)

    // Switch to conversation B — it must not be locked
    act(() => {
      rerender({ conv: 'B' })
    })
    expect(result.current.isStreaming).toBe(false)
    expect(result.current.waitingForReply).toBe(false)

    // More chunks for A must not pollute B's view
    const before = result.current.messages.length
    act(() => {
      MockWebSocket.instances[0].simulateMessage(
        JSON.stringify({ chunk: 'more of A', conversation_id: 'A' }),
      )
    })
    expect(result.current.messages.length).toBe(before)

    // Sending in B while A is busy queues the message without breaking A
    act(() => {
      result.current.sendMessage('hello B', 'B')
    })
    expect(result.current.waitingForReply).toBe(true)
    expect(MockWebSocket.instances[0].sentMessages).toHaveLength(2)

    // Finish A, then B's reply starts — B streams in its own view
    act(() => {
      MockWebSocket.instances[0].simulateMessage(JSON.stringify({ done: true, conversation_id: 'A' }))
    })
    await act(async () => {
      vi.advanceTimersByTime(500)
    })

    act(() => {
      MockWebSocket.instances[0].simulateMessage(
        JSON.stringify({ chunk: 'answering B', conversation_id: 'B' }),
      )
    })
    expect(result.current.isStreaming).toBe(true)

    act(() => {
      MockWebSocket.instances[0].simulateMessage(JSON.stringify({ done: true, conversation_id: 'B' }))
    })
    await act(async () => {
      vi.advanceTimersByTime(500)
    })
    expect(result.current.isStreaming).toBe(false)
  })

  it('should not render responses of a different conversation', async () => {
    const { result } = renderHook(() => useWebSocket('ws://localhost:8000/ws/chat', 'B'))

    await act(async () => {
      await new Promise(resolve => setTimeout(resolve, 50))
    })

    act(() => {
      MockWebSocket.instances[0].simulateMessage(
        JSON.stringify({ response: 'for A only', conversation_id: 'A' }),
      )
    })

    expect(result.current.messages).toHaveLength(0)
  })

  it('preserves an in-flight response when switching away and back mid-stream', async () => {
    vi.useFakeTimers()
    const fetchMock = vi.fn()
    globalThis.fetch = fetchMock
    const { result, rerender } = renderHook(
      ({ conv }: { conv?: string }) => useWebSocket('ws://localhost:8000/ws/chat', conv),
      { initialProps: { conv: 'A' as string | undefined } },
    )

    await act(async () => {
      vi.advanceTimersByTime(10)
    })

    // Send and stream the first part of a reply in A
    act(() => {
      result.current.sendMessage('hello', 'A')
    })
    act(() => {
      MockWebSocket.instances[0].simulateMessage(
        JSON.stringify({ chunk: 'part one. ', conversation_id: 'A' }),
      )
    })
    await act(async () => {
      vi.advanceTimersByTime(200)
    })
    expect(result.current.messages.find(m => m.role === 'assistant')?.content).toBe('part one. ')

    // Switch away to B (as ChatWindow does: switch + clear + load history)
    act(() => {
      rerender({ conv: 'B' })
    })
    act(() => {
      result.current.clearMessages()
    })
    fetchMock.mockResolvedValueOnce({ ok: true, json: async () => ({ messages: [] }) })
    await act(async () => {
      await result.current.loadHistory('B')
    })

    // More of A streams while we're away — buffered, not rendered on B
    act(() => {
      MockWebSocket.instances[0].simulateMessage(
        JSON.stringify({ chunk: 'part two. ', conversation_id: 'A' }),
      )
    })
    expect(result.current.messages).toHaveLength(0)

    // Switch back to A while still streaming. The DB history does not yet
    // contain the assistant reply (persisted only on done).
    act(() => {
      rerender({ conv: 'A' })
    })
    act(() => {
      result.current.clearMessages()
    })
    fetchMock.mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        messages: [
          { id: 'u1', role: 'user', content: 'hello', created_at: '2024-01-01T00:00:00Z' },
        ],
      }),
    })
    await act(async () => {
      await result.current.loadHistory('A')
    })

    // The preserved buffer is seeded — no truncation
    expect(result.current.messages).toHaveLength(2)
    expect(result.current.messages[1].role).toBe('assistant')
    expect(result.current.messages[1].content).toBe('part one. part two. ')

    // Stream continues and finishes
    act(() => {
      MockWebSocket.instances[0].simulateMessage(
        JSON.stringify({ chunk: 'part three', conversation_id: 'A' }),
      )
    })
    await act(async () => {
      vi.advanceTimersByTime(200)
    })
    expect(result.current.messages[1].content).toBe('part one. part two. part three')

    act(() => {
      MockWebSocket.instances[0].simulateMessage(JSON.stringify({ done: true, conversation_id: 'A' }))
    })
    await act(async () => {
      vi.advanceTimersByTime(500)
    })
    expect(result.current.messages[1].content).toBe('part one. part two. part three')
    expect(result.current.messages[1].id).not.toMatch(/^stream-/)
  })

  it('ignores stale history responses from an earlier conversation switch', async () => {
    const fetchMock = vi.fn()
    globalThis.fetch = fetchMock
    const { result } = renderHook(() => useWebSocket('ws://localhost:8000/ws/chat', 'B'))

    await act(async () => {
      await new Promise(resolve => setTimeout(resolve, 10))
    })

    // The response for A is requested first but resolves last.
    let resolveA!: (value: {
      ok: boolean
      json: () => Promise<{ messages: { id: string; role: string; content: string; created_at: string }[] }>
    }) => void
    fetchMock.mockImplementationOnce(() => new Promise(res => { resolveA = res }))
    fetchMock.mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        messages: [
          { id: 'b1', role: 'user', content: 'B history', created_at: '2024-01-01T00:00:00Z' },
        ],
      }),
    })

    let pA!: Promise<void>
    let pB!: Promise<void>
    act(() => {
      pA = result.current.loadHistory('A')
      pB = result.current.loadHistory('B')
    })
    await act(async () => {
      resolveA({
        ok: true,
        json: async () => ({
          messages: [
            { id: 'a1', role: 'user', content: 'A history', created_at: '2024-01-01T00:00:00Z' },
          ],
        }),
      })
      await pA
      await pB
    })

    // A's late response must not overwrite the view of B.
    expect(result.current.messages.map(m => m.content)).toEqual(['B history'])
  })

  it('stopGeneration sends { stop: true } with the active conversation id', async () => {
    const { result } = renderHook(() => useWebSocket('ws://localhost:8000/ws/chat', 'conv-1'))

    await act(async () => {
      await new Promise(resolve => setTimeout(resolve, 10))
    })

    act(() => {
      result.current.stopGeneration()
    })

    const sent = JSON.parse(MockWebSocket.instances[0].sentMessages[0])
    expect(sent.stop).toBe(true)
    expect(sent.conversation_id).toBe('conv-1')
  })

  it('stopGeneration omits conversation_id when there is no active conversation', async () => {
    const { result } = renderHook(() => useWebSocket('ws://localhost:8000/ws/chat'))

    await act(async () => {
      await new Promise(resolve => setTimeout(resolve, 10))
    })

    act(() => {
      result.current.stopGeneration()
    })

    const sent = JSON.parse(MockWebSocket.instances[0].sentMessages[0])
    expect(sent.stop).toBe(true)
    expect(sent.conversation_id).toBeUndefined()
  })

  it('finalizes the partial reply as a completed message when stopped', async () => {
    vi.useFakeTimers()
    const { result } = renderHook(() => useWebSocket('ws://localhost:8000/ws/chat', 'conv-1'))

    await act(async () => {
      vi.advanceTimersByTime(10)
    })

    act(() => {
      result.current.sendMessage('hello', 'conv-1')
    })
    act(() => {
      MockWebSocket.instances[0].simulateMessage(
        JSON.stringify({ chunk: 'partial ', conversation_id: 'conv-1' }),
      )
    })
    act(() => {
      MockWebSocket.instances[0].simulateMessage(
        JSON.stringify({ chunk: 'answer', conversation_id: 'conv-1' }),
      )
    })
    await act(async () => {
      vi.advanceTimersByTime(500)
    })
    // All buffered content revealed, stream still active.
    expect(result.current.isStreaming).toBe(true)

    // User presses stop → backend replies with { stopped: true }.
    act(() => {
      MockWebSocket.instances[0].simulateMessage(
        JSON.stringify({ stopped: true, conversation_id: 'conv-1' }),
      )
    })

    expect(result.current.isStreaming).toBe(false)
    const assistant = result.current.messages.find(m => m.role === 'assistant')
    expect(assistant?.content).toBe('partial answer')
    expect(assistant?.id).not.toMatch(/^stream-/)
  })

  it('backs off awaitingMoreContent when the typewriter drains before done', async () => {
    vi.useFakeTimers()
    const { result } = renderHook(() => useWebSocket('ws://localhost:8000/ws/chat', 'conv-1'))

    await act(async () => {
      vi.advanceTimersByTime(10)
    })

    act(() => {
      result.current.sendMessage('hello', 'conv-1')
    })
    act(() => {
      MockWebSocket.instances[0].simulateMessage(
        JSON.stringify({ chunk: 'short', conversation_id: 'conv-1' }),
      )
    })
    // Drain the typewriter completely; not done yet → awaiting more content.
    await act(async () => {
      vi.advanceTimersByTime(500)
    })
    expect(result.current.awaitingMoreContent).toBe(true)

    // A new chunk arrives → new content, indicator backs off.
    act(() => {
      MockWebSocket.instances[0].simulateMessage(
        JSON.stringify({ chunk: ' more', conversation_id: 'conv-1' }),
      )
    })
    expect(result.current.awaitingMoreContent).toBe(false)

    // Drains again and still not done → awaiting again.
    await act(async () => {
      vi.advanceTimersByTime(500)
    })
    expect(result.current.awaitingMoreContent).toBe(true)

    // Done → awaiting clears and streaming ends.
    act(() => {
      MockWebSocket.instances[0].simulateMessage(JSON.stringify({ done: true, conversation_id: 'conv-1' }))
    })
    await act(async () => {
      vi.advanceTimersByTime(500)
    })
    expect(result.current.awaitingMoreContent).toBe(false)
    expect(result.current.isStreaming).toBe(false)
  })

  describe('queued messages (流式排队待发)', () => {
    type WsHook = ReturnType<typeof useWebSocket>

    const messageFrames = () =>
      MockWebSocket.instances[0].sentMessages
        .map(s => JSON.parse(s) as Record<string, unknown>)
        .filter(f => typeof f.message === 'string')

    // 进入"conv-1 正在流式回复"的状态(用户消息已发,chunk 已到,打字机进行中)
    const startStream = (result: { current: WsHook }, conv = 'conv-1') => {
      act(() => {
        result.current.sendMessage('first', conv)
      })
      act(() => {
        MockWebSocket.instances[0].simulateMessage(
          JSON.stringify({ chunk: 'answering. ', conversation_id: conv }),
        )
      })
    }

    const finishWithDone = async (conv = 'conv-1') => {
      act(() => {
        MockWebSocket.instances[0].simulateMessage(JSON.stringify({ done: true, conversation_id: conv }))
      })
      await act(async () => {
        vi.advanceTimersByTime(500)
      })
    }

    it('auto-sends the queued message after the current reply finishes', async () => {
      vi.useFakeTimers()
      const { result } = renderHook(() => useWebSocket('ws://localhost:8000/ws/chat', 'conv-1'))
      await act(async () => { vi.advanceTimersByTime(10) })

      startStream(result)
      expect(result.current.isStreaming).toBe(true)

      act(() => {
        result.current.queuePendingMessage('second', 'conv-1')
      })
      expect(result.current.pendingMessage).toBe('second')
      // 排队不立即发送
      expect(messageFrames()).toHaveLength(1)

      await finishWithDone()

      expect(result.current.isStreaming).toBe(false)
      expect(result.current.pendingMessage).toBeNull()
      const frames = messageFrames()
      expect(frames).toHaveLength(2)
      expect(frames[1].message).toBe('second')
      expect(frames[1].conversation_id).toBe('conv-1')
      // 第二条用户消息已入列(排在助手回复之后)
      const roles = result.current.messages.map(m => m.role)
      expect(roles.filter(r => r === 'user')).toHaveLength(2)
      expect(roles[roles.length - 1]).toBe('user')
    })

    it('sends the queued message exactly once when done and stopped frames both arrive', async () => {
      vi.useFakeTimers()
      const { result } = renderHook(() => useWebSocket('ws://localhost:8000/ws/chat', 'conv-1'))
      await act(async () => { vi.advanceTimersByTime(10) })

      startStream(result)
      act(() => { result.current.queuePendingMessage('second', 'conv-1') })
      await finishWithDone()
      expect(messageFrames()).toHaveLength(2)

      // 立即执行/停止的 stopped 帧随后到达(幂等回复)——不得重复发送
      act(() => {
        MockWebSocket.instances[0].simulateMessage(
          JSON.stringify({ stopped: true, conversation_id: 'conv-1' }),
        )
      })
      await act(async () => { vi.advanceTimersByTime(100) })
      expect(messageFrames()).toHaveLength(2)
      expect(result.current.pendingMessage).toBeNull()
    })

    it('sendPendingNow stops the running reply and sends the queued message after stopped', async () => {
      vi.useFakeTimers()
      const { result } = renderHook(() => useWebSocket('ws://localhost:8000/ws/chat', 'conv-1'))
      await act(async () => { vi.advanceTimersByTime(10) })

      startStream(result)
      act(() => { result.current.queuePendingMessage('second', 'conv-1') })

      act(() => { result.current.sendPendingNow('conv-1') })
      const stopFrames = MockWebSocket.instances[0].sentMessages
        .map(s => JSON.parse(s) as Record<string, unknown>)
        .filter(f => f.stop === true)
      expect(stopFrames).toHaveLength(1)
      expect(stopFrames[0].conversation_id).toBe('conv-1')
      // 尚未发送第二条
      expect(messageFrames()).toHaveLength(1)

      act(() => {
        MockWebSocket.instances[0].simulateMessage(
          JSON.stringify({ stopped: true, conversation_id: 'conv-1' }),
        )
      })
      await act(async () => { vi.advanceTimersByTime(100) })

      const frames = messageFrames()
      expect(frames).toHaveLength(2)
      expect(frames[1].message).toBe('second')
      expect(result.current.pendingMessage).toBeNull()
    })

    it('cancelPendingMessage drops the queued message so it is never auto-sent', async () => {
      vi.useFakeTimers()
      const { result } = renderHook(() => useWebSocket('ws://localhost:8000/ws/chat', 'conv-1'))
      await act(async () => { vi.advanceTimersByTime(10) })

      startStream(result)
      act(() => { result.current.queuePendingMessage('second', 'conv-1') })
      act(() => { result.current.cancelPendingMessage('conv-1') })
      expect(result.current.pendingMessage).toBeNull()

      await finishWithDone()
      expect(messageFrames()).toHaveLength(1)
    })

    it('replaces the queued message when queueing again (single slot)', async () => {
      vi.useFakeTimers()
      const { result } = renderHook(() => useWebSocket('ws://localhost:8000/ws/chat', 'conv-1'))
      await act(async () => { vi.advanceTimersByTime(10) })

      startStream(result)
      act(() => { result.current.queuePendingMessage('second', 'conv-1') })
      act(() => { result.current.queuePendingMessage('third', 'conv-1') })
      expect(result.current.pendingMessage).toBe('third')

      await finishWithDone()
      const frames = messageFrames()
      expect(frames).toHaveLength(2)
      expect(frames[1].message).toBe('third')
    })

    it('holds the queued message when the reply errors out instead of auto-sending', async () => {
      vi.useFakeTimers()
      const { result } = renderHook(() => useWebSocket('ws://localhost:8000/ws/chat', 'conv-1'))
      await act(async () => { vi.advanceTimersByTime(10) })

      startStream(result)
      act(() => { result.current.queuePendingMessage('second', 'conv-1') })

      act(() => {
        MockWebSocket.instances[0].simulateMessage(
          JSON.stringify({ error: 'boom', conversation_id: 'conv-1' }),
        )
      })

      // 异常结束:不自动发送,悬浮消息保留并标记挂起
      expect(result.current.isStreaming).toBe(false)
      expect(result.current.pendingMessage).toBe('second')
      expect(result.current.pendingHeld).toBe(true)
      expect(messageFrames()).toHaveLength(1)

      // 用户手动「立即执行」补发
      act(() => { result.current.sendPendingNow('conv-1') })
      const frames = messageFrames()
      expect(frames).toHaveLength(2)
      expect(frames[1].message).toBe('second')
      expect(result.current.pendingMessage).toBeNull()
    })

    it('holds the queued message when the reply times out', async () => {
      vi.useFakeTimers()
      const { result } = renderHook(() => useWebSocket('ws://localhost:8000/ws/chat', 'conv-1'))
      await act(async () => { vi.advanceTimersByTime(10) })

      // 发出消息后无任何响应帧,直接排队第二条
      act(() => { result.current.sendMessage('first', 'conv-1') })
      act(() => { result.current.queuePendingMessage('second', 'conv-1') })
      expect(result.current.pendingMessage).toBe('second')

      await act(async () => { vi.advanceTimersByTime(91_000) })

      // 超时:不自动发送,标记挂起
      expect(result.current.messages.some(m => m.role === 'system' && m.content.includes('timed out'))).toBe(true)
      expect(result.current.pendingMessage).toBe('second')
      expect(result.current.pendingHeld).toBe(true)
      expect(messageFrames()).toHaveLength(1)
    })

    it('keeps the queued message scoped to its conversation', async () => {
      vi.useFakeTimers()
      const { result, rerender } = renderHook(
        ({ conv }: { conv?: string }) => useWebSocket('ws://localhost:8000/ws/chat', conv),
        { initialProps: { conv: 'A' as string | undefined } },
      )
      await act(async () => { vi.advanceTimersByTime(10) })

      startStream(result, 'A')
      act(() => { result.current.queuePendingMessage('second', 'A') })

      // 切到 B:B 没有待发消息
      act(() => { rerender({ conv: 'B' }) })
      expect(result.current.pendingMessage).toBeNull()

      // A 的回复结束:待发消息仍发给 A(即使当前视图在 B)
      await finishWithDone('A')
      const frames = messageFrames()
      expect(frames).toHaveLength(2)
      expect(frames[1].message).toBe('second')
      expect(frames[1].conversation_id).toBe('A')
    })

    it('sends directly when queueing while no reply is in flight', async () => {
      vi.useFakeTimers()
      const { result } = renderHook(() => useWebSocket('ws://localhost:8000/ws/chat', 'conv-1'))
      await act(async () => { vi.advanceTimersByTime(10) })

      act(() => { result.current.queuePendingMessage('direct', 'conv-1') })
      const frames = messageFrames()
      expect(frames).toHaveLength(1)
      expect(frames[0].message).toBe('direct')
      expect(result.current.pendingMessage).toBeNull()
    })

    it('clears pending only on explicit conversation clear, not on view switch', async () => {
      vi.useFakeTimers()
      const { result } = renderHook(() => useWebSocket('ws://localhost:8000/ws/chat', 'conv-1'))
      await act(async () => { vi.advanceTimersByTime(10) })

      startStream(result)
      act(() => { result.current.queuePendingMessage('second', 'conv-1') })

      // 切换会话视图(ChatWindow 走 clearMessages() 无参)不清待发
      act(() => { result.current.clearMessages() })
      expect(result.current.pendingMessage).toBe('second')

      // 显式清空该会话上下文才清待发
      act(() => { result.current.clearMessages('conv-1') })
      expect(result.current.pendingMessage).toBeNull()
    })
  })

  describe('attachment protocol (F1 附件协议)', () => {
    it('sendMessage 携带附件时,WS 帧包含 {id, alt} 列表且乐观用户消息带 attachments', async () => {
      const { result } = renderHook(() => useWebSocket('ws://localhost:8000/ws/chat', 'conv-1'))
      await act(async () => {
        await new Promise(resolve => setTimeout(resolve, 10))
      })

      act(() => {
        result.current.sendMessage('看图', 'conv-1', [{ id: 'att_1', alt: '截图' }])
      })

      const frames = MockWebSocket.instances[0].sentMessages.map(
        s => JSON.parse(s) as Record<string, unknown>,
      )
      expect(frames[0].message).toBe('看图')
      expect(frames[0].attachments).toEqual([{ id: 'att_1', alt: '截图' }])
      const userMsg = result.current.messages.find(m => m.role === 'user')
      expect(userMsg?.attachments).toEqual([{ id: 'att_1', alt: '截图' }])
    })

    it('sendMessage 不带附件时不出现 attachments 键(老调用点零回退)', async () => {
      const { result } = renderHook(() => useWebSocket('ws://localhost:8000/ws/chat', 'conv-1'))
      await act(async () => {
        await new Promise(resolve => setTimeout(resolve, 10))
      })

      act(() => {
        result.current.sendMessage('Hello')
      })

      const sent = JSON.parse(MockWebSocket.instances[0].sentMessages[0]) as Record<string, unknown>
      expect('attachments' in sent).toBe(false)
    })

    it('queuePendingMessage 排队附件,回复结束后随消息一起自动发送', async () => {
      vi.useFakeTimers()
      const { result } = renderHook(() => useWebSocket('ws://localhost:8000/ws/chat', 'conv-1'))
      await act(async () => { vi.advanceTimersByTime(10) })

      // 进入流式回复状态
      act(() => { result.current.sendMessage('first', 'conv-1') })
      act(() => {
        MockWebSocket.instances[0].simulateMessage(
          JSON.stringify({ chunk: 'answering. ', conversation_id: 'conv-1' }),
        )
      })

      act(() => { result.current.queuePendingMessage('second', 'conv-1', [{ id: 'att_9' }]) })
      expect(result.current.pendingMessage).toBe('second')
      expect(result.current.pendingAttachments).toEqual([{ id: 'att_9' }])
      // 排队不立即发送
      expect(MockWebSocket.instances[0].sentMessages).toHaveLength(1)

      act(() => {
        MockWebSocket.instances[0].simulateMessage(
          JSON.stringify({ done: true, conversation_id: 'conv-1' }),
        )
      })
      await act(async () => { vi.advanceTimersByTime(500) })

      const frames = MockWebSocket.instances[0].sentMessages
        .map(s => JSON.parse(s) as Record<string, unknown>)
        .filter(f => typeof f.message === 'string')
      expect(frames).toHaveLength(2)
      expect(frames[1].attachments).toEqual([{ id: 'att_9' }])
      expect(result.current.pendingAttachments).toBeUndefined()
    })

    it('纯图片排队(text 为空)暴露 pendingActive=true 且 pendingMessage 为空串', async () => {
      vi.useFakeTimers()
      const { result } = renderHook(() => useWebSocket('ws://localhost:8000/ws/chat', 'conv-1'))
      await act(async () => { vi.advanceTimersByTime(10) })

      // 进入流式回复状态
      act(() => { result.current.sendMessage('first', 'conv-1') })
      act(() => {
        MockWebSocket.instances[0].simulateMessage(
          JSON.stringify({ chunk: 'answering. ', conversation_id: 'conv-1' }),
        )
      })

      // Finding 3 回归:纯图片排队 text 为 '' → pendingMessage 是假值,
      // 悬浮条必须以 pendingActive 为准渲染,否则用户零反馈、会重复发送。
      act(() => {
        result.current.queuePendingMessage('', 'conv-1', [{ id: 'att_9', mime: 'image/png' }])
      })
      expect(result.current.pendingActive).toBe(true)
      expect(result.current.pendingMessage).toBe('')
      expect(result.current.pendingAttachments).toEqual([{ id: 'att_9', mime: 'image/png' }])

      // 回复结束 → 待发条目自动发送,排队态复位
      act(() => {
        MockWebSocket.instances[0].simulateMessage(
          JSON.stringify({ done: true, conversation_id: 'conv-1' }),
        )
      })
      await act(async () => { vi.advanceTimersByTime(500) })

      expect(result.current.pendingActive).toBe(false)
      expect(result.current.pendingMessage).toBeNull()
    })

    it('loadHistory 把后端 attachments 字段容错映射进 Message.attachments', async () => {
      const fetchMock = vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({
          messages: [
            {
              id: 'u1',
              role: 'user',
              content: '看图',
              created_at: '2024-01-01T00:00:00Z',
              attachments: [{ id: 'att_1', mime: 'image/png', width: 1280, height: 720, alt: '首页' }],
            },
            // 老消息 attachments 为 null → 无附件
            { id: 'u2', role: 'user', content: '纯文本老消息', created_at: '2024-01-01T00:01:00Z', attachments: null },
            // 缺 id / 非对象元素被过滤,过滤后为空 → 视为无附件
            {
              id: 'u3',
              role: 'user',
              content: '坏附件',
              created_at: '2024-01-01T00:02:00Z',
              attachments: [{ mime: 'image/png' }, 'junk'],
            },
          ],
        }),
      })
      globalThis.fetch = fetchMock
      const { result } = renderHook(() => useWebSocket('ws://localhost:8000/ws/chat', 'conv-1'))

      await act(async () => {
        await result.current.loadHistory('conv-1')
      })

      expect(result.current.messages[0].attachments).toEqual([
        { id: 'att_1', mime: 'image/png', width: 1280, height: 720, alt: '首页' },
      ])
      expect(result.current.messages[1].attachments).toBeUndefined()
      expect(result.current.messages[2].attachments).toBeUndefined()
    })

    it('inbound wechat channel_message with image appears as user message carrying attachments', async () => {
      const { result } = renderHook(() => useWebSocket('ws://localhost:8000/ws/chat', 'conv-9'))

      await act(async () => {
        await new Promise(resolve => setTimeout(resolve, 10))
      })

      await act(async () => {
        MockWebSocket.instances[0].simulateMessage(
          JSON.stringify({
            channel_message: {
              channel: 'wechat',
              conversation_id: 'conv-9',
              user_message: '',
              response: '这是你发的图片',
              source: 'wechat',
              attachments: [{ id: 'att_wx', mime: 'image/jpeg', width: 640, height: 480 }],
            },
          }),
        )
      })

      // 纯图片入站:user_message 为空但仍生成用户气泡并携带附件 refs
      const userMsg = result.current.messages.find(m => m.role === 'user')
      expect(userMsg).toBeDefined()
      expect(userMsg!.attachments).toEqual([
        { id: 'att_wx', mime: 'image/jpeg', width: 640, height: 480 },
      ])
      const assistantMsg = result.current.messages.find(m => m.role === 'assistant')
      expect(assistantMsg?.content).toBe('这是你发的图片')
    })
  })

  describe('tool_event 实时工具卡', () => {
    const toolStart = (callId = 'c1', conv = 'conv-1') =>
      JSON.stringify({
        tool_event: {
          phase: 'start', call_id: callId, name: 'web_search',
          args: { query: 'q' }, args_truncated: false,
        },
        conversation_id: conv,
      })
    const toolEnd = (callId = 'c1', conv = 'conv-1') =>
      JSON.stringify({
        tool_event: {
          phase: 'end', call_id: callId, duration_ms: 1800, is_error: false,
          result_preview: 'found 3', result_truncated: true,
        },
        conversation_id: conv,
      })

    const assistantsOf = (result: { current: { messages: Message[] } }) =>
      result.current.messages.filter(m => m.role === 'assistant')

    it('start 创建占位 assistant 消息并带 running 卡,end 原地更新为 ok', async () => {
      vi.useFakeTimers()
      const { result } = renderHook(() => useWebSocket('ws://localhost:8000/ws/chat', 'conv-1'))
      await act(async () => { vi.advanceTimersByTime(10) })

      act(() => { MockWebSocket.instances[0].simulateMessage(toolStart()) })
      const placeholder = assistantsOf(result)[0]
      expect(placeholder).toBeDefined()
      expect(placeholder.content).toBe('')
      expect(placeholder.toolCalls).toEqual([
        { call_id: 'c1', name: 'web_search', args: { query: 'q' }, argsTruncated: false, status: 'running' },
      ])

      act(() => { MockWebSocket.instances[0].simulateMessage(toolEnd()) })
      const assistants = assistantsOf(result)
      // 占位消息被复用,不追加第二条
      expect(assistants).toHaveLength(1)
      expect(assistants[0].toolCalls![0]).toMatchObject({
        call_id: 'c1', status: 'ok', durationMs: 1800, resultTruncated: true,
      })
    })

    it('工具卡与后续 chunk 落在同一条消息,done 后终结', async () => {
      vi.useFakeTimers()
      const { result } = renderHook(() => useWebSocket('ws://localhost:8000/ws/chat', 'conv-1'))
      await act(async () => { vi.advanceTimersByTime(10) })

      act(() => { MockWebSocket.instances[0].simulateMessage(toolStart()) })
      act(() => {
        MockWebSocket.instances[0].simulateMessage(
          JSON.stringify({ chunk: 'answer ', conversation_id: 'conv-1' }),
        )
      })
      await act(async () => { vi.advanceTimersByTime(500) })
      act(() => { MockWebSocket.instances[0].simulateMessage(toolEnd()) })
      act(() => {
        MockWebSocket.instances[0].simulateMessage(
          JSON.stringify({ done: true, conversation_id: 'conv-1' }),
        )
      })
      await act(async () => { vi.advanceTimersByTime(500) })

      const assistants = assistantsOf(result)
      expect(assistants).toHaveLength(1)
      expect(assistants[0].content).toBe('answer ')
      expect(assistants[0].toolCalls![0].status).toBe('ok')
      expect(assistants[0].id).not.toMatch(/^stream-/)
      expect(result.current.isStreaming).toBe(false)
    })

    it('stopped 把残留 running 卡标为 interrupted', async () => {
      vi.useFakeTimers()
      const { result } = renderHook(() => useWebSocket('ws://localhost:8000/ws/chat', 'conv-1'))
      await act(async () => { vi.advanceTimersByTime(10) })

      act(() => { result.current.sendMessage('hello', 'conv-1') })
      act(() => { MockWebSocket.instances[0].simulateMessage(toolStart()) })
      act(() => {
        MockWebSocket.instances[0].simulateMessage(
          JSON.stringify({ stopped: true, conversation_id: 'conv-1' }),
        )
      })

      const assistants = assistantsOf(result)
      expect(assistants).toHaveLength(1)
      expect(assistants[0].toolCalls![0].status).toBe('interrupted')
      expect(assistants[0].id).not.toMatch(/^stream-/)
      expect(result.current.isStreaming).toBe(false)
    })

    it('done 兜底:未收到 tool_end 的 running 卡标记为 interrupted', async () => {
      vi.useFakeTimers()
      const { result } = renderHook(() => useWebSocket('ws://localhost:8000/ws/chat', 'conv-1'))
      await act(async () => { vi.advanceTimersByTime(10) })

      act(() => { MockWebSocket.instances[0].simulateMessage(toolStart()) })
      act(() => {
        MockWebSocket.instances[0].simulateMessage(
          JSON.stringify({ done: true, conversation_id: 'conv-1' }),
        )
      })
      await act(async () => { vi.advanceTimersByTime(500) })

      expect(assistantsOf(result)[0].toolCalls![0].status).toBe('interrupted')
      expect(result.current.isStreaming).toBe(false)
    })

    it('error 收尾:残留 running 卡标为 interrupted', async () => {
      vi.useFakeTimers()
      const { result } = renderHook(() => useWebSocket('ws://localhost:8000/ws/chat', 'conv-1'))
      await act(async () => { vi.advanceTimersByTime(10) })

      act(() => { MockWebSocket.instances[0].simulateMessage(toolStart()) })
      act(() => {
        MockWebSocket.instances[0].simulateMessage(
          JSON.stringify({ error: 'boom', conversation_id: 'conv-1' }),
        )
      })

      expect(assistantsOf(result)[0].toolCalls![0].status).toBe('interrupted')
      expect(result.current.isStreaming).toBe(false)
    })

    it('忽略其它会话的 tool_event,不串话', async () => {
      vi.useFakeTimers()
      const { result } = renderHook(() => useWebSocket('ws://localhost:8000/ws/chat', 'B'))
      await act(async () => { vi.advanceTimersByTime(10) })

      act(() => { MockWebSocket.instances[0].simulateMessage(toolStart('c1', 'A')) })
      act(() => { MockWebSocket.instances[0].simulateMessage(toolEnd('c1', 'A')) })

      expect(result.current.messages).toHaveLength(0)
    })

    it('非流式:response 帧并入占位消息并保留工具卡,不留空气泡', async () => {
      vi.useFakeTimers()
      const { result } = renderHook(() => useWebSocket('ws://localhost:8000/ws/chat', 'conv-1'))
      await act(async () => { vi.advanceTimersByTime(10) })

      act(() => { MockWebSocket.instances[0].simulateMessage(toolStart()) })
      act(() => { MockWebSocket.instances[0].simulateMessage(toolEnd()) })
      act(() => {
        MockWebSocket.instances[0].simulateMessage(
          JSON.stringify({ response: 'final answer', conversation_id: 'conv-1' }),
        )
      })

      const assistants = assistantsOf(result)
      expect(assistants).toHaveLength(1)
      expect(assistants[0].content).toBe('final answer')
      expect(assistants[0].toolCalls![0].status).toBe('ok')
      expect(assistants[0].id).not.toMatch(/^stream-/)
      expect(result.current.isStreaming).toBe(false)
      expect(result.current.awaitingMoreContent).toBe(false)
    })
  })

  describe('tool_anchors 内容锚点（穿插布局）', () => {
    const toolStart = (callId = 'c1', conv = 'conv-1') =>
      JSON.stringify({
        tool_event: { phase: 'start', call_id: callId, name: 'web_search', args: { query: 'q' } },
        conversation_id: conv,
      })
    const chunk = (text: string, conv = 'conv-1') =>
      JSON.stringify({ chunk: text, conversation_id: conv })
    const assistantsOf = (result: { current: { messages: Message[] } }) =>
      result.current.messages.filter(m => m.role === 'assistant')

    it('tool_start 以当时已接收内容长度记录锚点并随消息携带', async () => {
      vi.useFakeTimers()
      const { result } = renderHook(() => useWebSocket('ws://localhost:8000/ws/chat', 'conv-1'))
      await act(async () => { vi.advanceTimersByTime(10) })

      act(() => { MockWebSocket.instances[0].simulateMessage(chunk('hello ')) })
      act(() => { MockWebSocket.instances[0].simulateMessage(toolStart()) })
      act(() => { MockWebSocket.instances[0].simulateMessage(chunk('world')) })

      const assistants = assistantsOf(result)
      expect(assistants).toHaveLength(1)
      expect(assistants[0].toolAnchors).toEqual([{ callId: 'c1', offset: 6 }])
    })

    it('done 后锚点保留在消息上,新一轮工具锚点从 0 重新计', async () => {
      vi.useFakeTimers()
      const { result } = renderHook(() => useWebSocket('ws://localhost:8000/ws/chat', 'conv-1'))
      await act(async () => { vi.advanceTimersByTime(10) })

      act(() => { MockWebSocket.instances[0].simulateMessage(chunk('hello ')) })
      act(() => { MockWebSocket.instances[0].simulateMessage(toolStart('c1')) })
      act(() => {
        MockWebSocket.instances[0].simulateMessage(
          JSON.stringify({ done: true, conversation_id: 'conv-1' }),
        )
      })
      await act(async () => { vi.advanceTimersByTime(500) })

      const first = assistantsOf(result)[0]
      expect(first.toolAnchors).toEqual([{ callId: 'c1', offset: 6 }])
      expect(first.id).not.toMatch(/^stream-/)

      // 第二轮:refs 已作废,新 tool_start 的锚点从 0 开始
      act(() => { result.current.sendMessage('again', 'conv-1') })
      act(() => { MockWebSocket.instances[0].simulateMessage(toolStart('c2')) })
      const second = assistantsOf(result).at(-1)
      expect(second).toBeDefined()
      expect(second!.id).not.toBe(first.id)
      expect(second!.toolAnchors).toEqual([{ callId: 'c2', offset: 0 }])
    })
  })
})

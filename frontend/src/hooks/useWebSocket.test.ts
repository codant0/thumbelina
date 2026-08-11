import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { useWebSocket } from './useWebSocket'

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

  beforeEach(() => {
    originalWebSocket = globalThis.WebSocket
    globalThis.WebSocket = MockWebSocket as unknown as typeof WebSocket
    MockWebSocket.instances = []
  })

  afterEach(() => {
    globalThis.WebSocket = originalWebSocket
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
})

import { describe, it, expect, beforeEach, afterEach } from 'vitest'
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

  it('should send messages through WebSocket', async () => {
    const { result } = renderHook(() => useWebSocket('ws://localhost:8000/ws/chat'))

    await act(async () => {
      await new Promise(resolve => setTimeout(resolve, 50))
    })

    expect(result.current.isConnected).toBe(true)

    await act(async () => {
      result.current.sendMessage('Hello')
    })

    expect(MockWebSocket.instances[0].sentMessages).toContain('Hello')
  })

  it('should receive messages from WebSocket', async () => {
    const { result } = renderHook(() => useWebSocket('ws://localhost:8000/ws/chat'))

    await act(async () => {
      await new Promise(resolve => setTimeout(resolve, 10))
    })

    act(() => {
      MockWebSocket.instances[0].simulateMessage('Response message')
    })

    expect(result.current.messages).toContain('Response message')
  })

  it('should clean up WebSocket on unmount', async () => {
    const { unmount } = renderHook(() => useWebSocket('ws://localhost:8000/ws/chat'))

    await act(async () => {
      await new Promise(resolve => setTimeout(resolve, 10))
    })

    unmount()

    expect(MockWebSocket.instances[0].readyState).toBe(3) // CLOSED
  })
})

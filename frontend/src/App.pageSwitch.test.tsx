import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import App from './App'

// Regression test: switching to another page must NOT close the chat
// WebSocket (backend cancels the in-flight generation on disconnect, which
// used to lose the LLM response). The hook lives in App now, so the
// connection must survive ChatWindow unmounting.
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
    this.onclose?.(new CloseEvent('close'))
  }

  simulateMessage(data: string) {
    this.onmessage?.(new MessageEvent('message', { data }))
  }
}

const userHistory = [
  { id: 'u1', role: 'user', content: 'hello', created_at: '2024-01-01T00:00:00Z' },
]

describe('App page switching', () => {
  let originalWebSocket: typeof globalThis.WebSocket
  let originalFetch: typeof globalThis.fetch

  beforeEach(() => {
    originalWebSocket = globalThis.WebSocket
    globalThis.WebSocket = MockWebSocket as unknown as typeof WebSocket
    MockWebSocket.instances = []
    originalFetch = globalThis.fetch
    globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('/api/v1/conversations/')) {
        return { ok: true, json: async () => ({ messages: userHistory }) } as Response
      }
      if (url.endsWith('/api/v1/config')) {
        return { ok: true, json: async () => ({}) } as Response
      }
      return { ok: true, json: async () => [] } as Response
    }) as unknown as typeof fetch
  })

  afterEach(() => {
    globalThis.WebSocket = originalWebSocket
    globalThis.fetch = originalFetch
  })

  it('keeps the WebSocket alive across page switches and shows the response on return', async () => {
    render(<App />)

    await waitFor(() => expect(MockWebSocket.instances).toHaveLength(1))
    const ws = MockWebSocket.instances[0]
    await waitFor(() => expect(ws.readyState).toBe(MockWebSocket.OPEN))

    // Send a message with no conversation selected yet (lazy creation path)
    const input = screen.getByPlaceholderText(/Type a message/i)
    fireEvent.change(input, { target: { value: 'hello' } })
    fireEvent.submit(input.closest('form')!)

    // Backend creates the conversation lazily, then starts streaming
    ws.simulateMessage(JSON.stringify({ conversation_created: 'conv-1' }))
    ws.simulateMessage(JSON.stringify({ chunk: 'Answer: ', conversation_id: 'conv-1' }))

    await waitFor(() => expect(screen.getByText(/Answer/)).toBeInTheDocument())

    // Switch to another page — ChatWindow unmounts, but the WS must survive
    fireEvent.click(screen.getByTestId('nav-tasks'))
    expect(ws.readyState).toBe(MockWebSocket.OPEN)
    expect(MockWebSocket.instances).toHaveLength(1)

    // The reply keeps streaming while the user is on another page
    ws.simulateMessage(JSON.stringify({ chunk: '123', conversation_id: 'conv-1' }))
    ws.simulateMessage(JSON.stringify({ done: true, conversation_id: 'conv-1' }))

    // Return to the chat page — history fetch only has the user message
    // (assistant reply is snapshotted in the hook), the full response must show
    fireEvent.click(screen.getByTestId('nav-chat'))
    await waitFor(() => {
      expect(screen.getByText(/Answer: 123/)).toBeInTheDocument()
    })
  })

  it('switches to the coder page and shows the coder sidebar', async () => {
    render(<App />)
    await waitFor(() => expect(MockWebSocket.instances).toHaveLength(1))
    fireEvent.click(screen.getByTestId('nav-coder'))
    expect(await screen.findByTestId('coder-sidebar')).toBeInTheDocument()
    expect(screen.getByTestId('coder-sidebar-empty')).toBeInTheDocument()
  })
})

import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import App from './App'

// Mock the WebSocket hook
vi.mock('./hooks/useWebSocket', () => ({
  useWebSocket: vi.fn(() => ({
    messages: [],
    isConnected: true,
    isStreaming: false,
    streamingMode: true,
    waitingForReply: false,
    awaitingMoreContent: false,
    lastConversationId: null,
    newConversationId: null,
    clearNewConversation: vi.fn(),
    sendMessage: vi.fn(),
    stopGeneration: vi.fn(),
    clearMessages: vi.fn(),
    switchConversation: vi.fn(),
    loadHistory: vi.fn(),
  })),
  // ChatWindow 订阅子 Agent 事件;在测试里提供 noop 退订函数。
  subscribeSubagentEvents: vi.fn(() => () => {}),
}))

describe('App', () => {
  it('should render the app', () => {
    render(<App />)
    expect(screen.getByText('Thumbelina')).toBeInTheDocument()
  })

  it('should render sidebar on chat page', () => {
    render(<App />)
    expect(screen.getByTestId('sidebar')).toBeInTheDocument()
  })

  it('should render chat window on chat page', () => {
    render(<App />)
    expect(screen.getByTestId('chat-window')).toBeInTheDocument()
  })

  it('should render navigation links', () => {
    render(<App />)
    expect(screen.getByTestId('nav-chat')).toBeInTheDocument()
    expect(screen.getByTestId('nav-tasks')).toBeInTheDocument()
    expect(screen.getByTestId('nav-memory')).toBeInTheDocument()
    expect(screen.getByTestId('nav-dream')).toBeInTheDocument()
    expect(screen.getByTestId('nav-settings')).toBeInTheDocument()
  })

  it('switches to trajectory page from nav', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify([]), { status: 200 }))
    render(<App />)
    fireEvent.click(screen.getByTestId('nav-trajectory'))
    expect(await screen.findByTestId('trajectory-page')).toBeInTheDocument()
  })
})

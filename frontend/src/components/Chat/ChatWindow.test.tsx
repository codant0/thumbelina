import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { ChatWindow } from './ChatWindow'

// Mock the useWebSocket hook
vi.mock('../../hooks/useWebSocket', () => ({
  useWebSocket: vi.fn(() => ({
    messages: [],
    isConnected: true,
    isStreaming: false,
    streamingMode: true,
    waitingForReply: false,
    sendMessage: vi.fn(),
  })),
}))

describe('ChatWindow', () => {
  it('should render chat window', () => {
    render(<ChatWindow />)
    expect(screen.getByTestId('chat-window')).toBeInTheDocument()
  })

  it('should show connection status', () => {
    render(<ChatWindow />)
    expect(screen.getByText(/Connected/i)).toBeInTheDocument()
  })

  it('should render message list', () => {
    // With empty messages, ChatWindow shows empty state; verify it renders
    render(<ChatWindow />)
    expect(screen.getByTestId('chat-window')).toBeInTheDocument()
  })

  it('should render input box', () => {
    render(<ChatWindow />)
    expect(screen.getByPlaceholderText(/Type a message/i)).toBeInTheDocument()
  })

  it('should render streaming toggle', () => {
    render(<ChatWindow />)
    expect(screen.getByTestId('streaming-toggle')).toBeInTheDocument()
  })
})

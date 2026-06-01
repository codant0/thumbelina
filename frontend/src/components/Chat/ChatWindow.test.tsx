import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { ChatWindow } from './ChatWindow'

// Mock the useWebSocket hook
vi.mock('../../hooks/useWebSocket', () => ({
  useWebSocket: vi.fn(() => ({
    messages: [],
    isConnected: true,
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
    expect(screen.getByText(/已连接/i)).toBeInTheDocument()
  })

  it('should render message list', () => {
    render(<ChatWindow />)
    expect(screen.getByTestId('message-list')).toBeInTheDocument()
  })

  it('should render input box', () => {
    render(<ChatWindow />)
    expect(screen.getByPlaceholderText(/输入消息/i)).toBeInTheDocument()
  })
})

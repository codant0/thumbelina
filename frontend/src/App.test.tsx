import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import App from './App'

// Mock the WebSocket hook
vi.mock('./hooks/useWebSocket', () => ({
  useWebSocket: vi.fn(() => ({
    messages: [],
    isConnected: true,
    sendMessage: vi.fn(),
  })),
}))

describe('App', () => {
  it('should render the app', () => {
    render(<App />)
    expect(screen.getByText('Thumbelina')).toBeInTheDocument()
  })

  it('should render sidebar', () => {
    render(<App />)
    expect(screen.getByTestId('sidebar')).toBeInTheDocument()
  })

  it('should render chat window', () => {
    render(<App />)
    expect(screen.getByTestId('chat-window')).toBeInTheDocument()
  })
})

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { ChatWindow } from './ChatWindow'

// Mock the useWebSocket hook — ChatWindow tests focus on rendering/behavior
// driven by the exposed state, not the WS protocol itself.
const mockUseWebSocket = vi.fn()
vi.mock('../../hooks/useWebSocket', () => ({
  useWebSocket: (...args: unknown[]) => mockUseWebSocket(...args),
}))

const mockCompress = vi.fn()
vi.mock('../../api/conversations', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../api/conversations')>()
  return {
    ...actual,
    compressConversation: (...args: unknown[]) => mockCompress(...args),
  }
})

const baseState = {
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
}

beforeEach(() => {
  vi.clearAllMocks()
  mockUseWebSocket.mockReturnValue(baseState)
})

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

  it('should not render compress button without a conversation', () => {
    render(<ChatWindow />)
    expect(screen.queryByTestId('compress-context')).not.toBeInTheDocument()
  })

  it('should render compress button when a conversation is active', () => {
    mockUseWebSocket.mockReturnValue({
      ...baseState,
      messages: [{ id: '1', role: 'user', content: 'hi', timestamp: '' }],
    })
    render(<ChatWindow conversationId="conv-1" />)
    expect(screen.getByTestId('compress-context')).toBeInTheDocument()
  })

  it('should call the compress API and show a success notice', async () => {
    mockUseWebSocket.mockReturnValue({
      ...baseState,
      messages: [{ id: '1', role: 'user', content: 'hi', timestamp: '' }],
    })
    mockCompress.mockResolvedValueOnce({ compressed: true })
    render(<ChatWindow conversationId="conv-1" />)
    fireEvent.click(screen.getByTestId('compress-context'))
    await waitFor(() => {
      expect(mockCompress).toHaveBeenCalledWith('conv-1')
      expect(screen.getByText(/Context compressed/i)).toBeInTheDocument()
    })
  })

  it('should show a failure notice when compression throws', async () => {
    mockUseWebSocket.mockReturnValue({
      ...baseState,
      messages: [{ id: '1', role: 'user', content: 'hi', timestamp: '' }],
    })
    mockCompress.mockRejectedValueOnce(new Error('boom'))
    render(<ChatWindow conversationId="conv-1" />)
    fireEvent.click(screen.getByTestId('compress-context'))
    await waitFor(() => {
      expect(screen.getByText(/Failed to compress context/i)).toBeInTheDocument()
    })
  })

  it('does not render the stop button when not streaming', () => {
    render(<ChatWindow conversationId="conv-1" />)
    expect(screen.queryByTestId('stop-generation')).not.toBeInTheDocument()
  })

  it('renders the stop button while streaming and stops on click', () => {
    mockUseWebSocket.mockReturnValue({
      ...baseState,
      isStreaming: true,
      messages: [
        { id: '1', role: 'user', content: 'hi', timestamp: '' },
        { id: 'stream-2', role: 'assistant', content: 'answ', timestamp: '' },
      ],
    })
    render(<ChatWindow conversationId="conv-1" />)
    const stop = screen.getByTestId('stop-generation')
    expect(stop).toBeInTheDocument()
    fireEvent.click(stop)
    expect(baseState.stopGeneration).toHaveBeenCalled()
  })

  it('keeps the input enabled while streaming (only disabled offline)', () => {
    mockUseWebSocket.mockReturnValue({
      ...baseState,
      isStreaming: true,
      messages: [
        { id: '1', role: 'user', content: 'hi', timestamp: '' },
        { id: 'stream-2', role: 'assistant', content: 'answ', timestamp: '' },
      ],
    })
    render(<ChatWindow conversationId="conv-1" />)
    expect(screen.getByPlaceholderText(/Type a message/i)).toBeEnabled()
  })

  it('disables the input when disconnected', () => {
    mockUseWebSocket.mockReturnValue({ ...baseState, isConnected: false })
    render(<ChatWindow />)
    expect(screen.getByPlaceholderText(/Type a message/i)).toBeDisabled()
  })

  it('disables the compress button while a stream is in progress', () => {
    mockUseWebSocket.mockReturnValue({
      ...baseState,
      isStreaming: true,
      messages: [{ id: '1', role: 'user', content: 'hi', timestamp: '' }],
    })
    render(<ChatWindow conversationId="conv-1" />)
    expect(screen.getByTestId('compress-context')).toBeDisabled()
  })
})

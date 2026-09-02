import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { ChatWindow } from './ChatWindow'
import type { ChatSocket } from '../../hooks/useWebSocket'

// ChatWindow receives the lifted WebSocket state via the `ws` prop — tests
// focus on rendering/behavior driven by that state, not the WS protocol.
const mockCompress = vi.fn()
vi.mock('../../api/conversations', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../api/conversations')>()
  return {
    ...actual,
    compressConversation: (...args: unknown[]) => mockCompress(...args),
  }
})

const baseState: ChatSocket = {
  messages: [],
  isConnected: true,
  isStreaming: false,
  streamingMode: true,
  waitingForReply: false,
  awaitingMoreContent: false,
  lastConversationId: null,
  newConversationId: null,
  clearNewConversation: vi.fn(),
  pendingMessage: null,
  pendingHeld: false,
  queuePendingMessage: vi.fn(),
  sendPendingNow: vi.fn(),
  cancelPendingMessage: vi.fn(),
  sendMessage: vi.fn(),
  stopGeneration: vi.fn(),
  clearMessages: vi.fn(),
  switchConversation: vi.fn(),
  loadHistory: vi.fn(),
  subscribe: vi.fn(() => () => {}),
}

let wsState = baseState
const renderWindow = (props: Record<string, unknown> = {}) =>
  render(<ChatWindow ws={wsState} {...props} />)

beforeEach(() => {
  vi.clearAllMocks()
  wsState = baseState
})

describe('ChatWindow', () => {
  it('should render chat window', () => {
    renderWindow()
    expect(screen.getByTestId('chat-window')).toBeInTheDocument()
  })

  it('should show connection status', () => {
    renderWindow()
    expect(screen.getByText(/Connected/i)).toBeInTheDocument()
  })

  it('should render message list', () => {
    // With empty messages, ChatWindow shows empty state; verify it renders
    renderWindow()
    expect(screen.getByTestId('chat-window')).toBeInTheDocument()
  })

  it('should render input box', () => {
    renderWindow()
    expect(screen.getByPlaceholderText(/Type a message/i)).toBeInTheDocument()
  })

  it('should render streaming toggle', () => {
    renderWindow()
    expect(screen.getByTestId('streaming-toggle')).toBeInTheDocument()
  })

  it('should not render compress button without a conversation', () => {
    renderWindow()
    expect(screen.queryByTestId('compress-context')).not.toBeInTheDocument()
  })

  it('should render compress button when a conversation is active', () => {
    wsState = {
      ...baseState,
      messages: [{ id: '1', role: 'user', content: 'hi', timestamp: '' }],
    }
    renderWindow({ conversationId: 'conv-1' })
    expect(screen.getByTestId('compress-context')).toBeInTheDocument()
  })

  it('should call the compress API and show a success notice', async () => {
    wsState = {
      ...baseState,
      messages: [{ id: '1', role: 'user', content: 'hi', timestamp: '' }],
    }
    mockCompress.mockResolvedValueOnce({ compressed: true })
    renderWindow({ conversationId: 'conv-1' })
    fireEvent.click(screen.getByTestId('compress-context'))
    await waitFor(() => {
      expect(mockCompress).toHaveBeenCalledWith('conv-1')
      expect(screen.getByText(/Context compressed/i)).toBeInTheDocument()
    })
  })

  it('should show a failure notice when compression throws', async () => {
    wsState = {
      ...baseState,
      messages: [{ id: '1', role: 'user', content: 'hi', timestamp: '' }],
    }
    mockCompress.mockRejectedValueOnce(new Error('boom'))
    renderWindow({ conversationId: 'conv-1' })
    fireEvent.click(screen.getByTestId('compress-context'))
    await waitFor(() => {
      expect(screen.getByText(/Failed to compress context/i)).toBeInTheDocument()
    })
  })

  it('does not render the stop button when not streaming', () => {
    renderWindow({ conversationId: 'conv-1' })
    expect(screen.queryByTestId('stop-generation')).not.toBeInTheDocument()
  })

  it('renders the stop button while streaming and stops on click', () => {
    wsState = {
      ...baseState,
      isStreaming: true,
      messages: [
        { id: '1', role: 'user', content: 'hi', timestamp: '' },
        { id: 'stream-2', role: 'assistant', content: 'answ', timestamp: '' },
      ],
    }
    renderWindow({ conversationId: 'conv-1' })
    const stop = screen.getByTestId('stop-generation')
    expect(stop).toBeInTheDocument()
    fireEvent.click(stop)
    expect(baseState.stopGeneration).toHaveBeenCalled()
  })

  it('keeps the input enabled while streaming (only disabled offline)', () => {
    wsState = {
      ...baseState,
      isStreaming: true,
      messages: [
        { id: '1', role: 'user', content: 'hi', timestamp: '' },
        { id: 'stream-2', role: 'assistant', content: 'answ', timestamp: '' },
      ],
    }
    renderWindow({ conversationId: 'conv-1' })
    expect(screen.getByPlaceholderText(/Type a message/i)).toBeEnabled()
  })

  it('disables the input when disconnected', () => {
    wsState = { ...baseState, isConnected: false }
    renderWindow()
    expect(screen.getByPlaceholderText(/Type a message/i)).toBeDisabled()
  })

  it('disables the compress button while a stream is in progress', () => {
    wsState = {
      ...baseState,
      isStreaming: true,
      messages: [{ id: '1', role: 'user', content: 'hi', timestamp: '' }],
    }
    renderWindow({ conversationId: 'conv-1' })
    expect(screen.getByTestId('compress-context')).toBeDisabled()
  })

  it('view trajectory button navigates with current conversation', () => {
    const onViewTrajectory = vi.fn()
    renderWindow({ conversationId: 'conv-1', onViewTrajectory })
    fireEvent.click(screen.getByTestId('view-trajectory'))
    expect(onViewTrajectory).toHaveBeenCalledWith('conv-1')
  })

  it('queues a message submitted while streaming for the active conversation', () => {
    wsState = {
      ...baseState,
      isStreaming: true,
      messages: [
        { id: '1', role: 'user', content: 'hi', timestamp: '' },
        { id: 'stream-2', role: 'assistant', content: 'answ', timestamp: '' },
      ],
    }
    renderWindow({ conversationId: 'conv-1' })

    fireEvent.change(screen.getByPlaceholderText(/Type a message/i), {
      target: { value: 'next question' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Send' }))

    expect(baseState.queuePendingMessage).toHaveBeenCalledWith('next question', 'conv-1')
    expect(baseState.sendMessage).not.toHaveBeenCalled()
  })

  it('renders the queued message floating bar wired to send-now and cancel', () => {
    wsState = { ...baseState, pendingMessage: 'queued text' }
    renderWindow({ conversationId: 'conv-1' })

    expect(screen.getByTestId('pending-message')).toHaveTextContent('queued text')

    fireEvent.click(screen.getByTestId('pending-send-now'))
    expect(baseState.sendPendingNow).toHaveBeenCalledWith('conv-1')

    fireEvent.click(screen.getByTestId('pending-cancel'))
    expect(baseState.cancelPendingMessage).toHaveBeenCalledWith('conv-1')
  })

  it('marks the queued bar as held after an abnormal reply end', () => {
    wsState = { ...baseState, pendingMessage: 'queued text', pendingHeld: true }
    renderWindow({ conversationId: 'conv-1' })
    expect(screen.getByText(/auto-send paused/i)).toBeInTheDocument()
  })
})

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

// 附件上传 mock:拖放冒烟测试需要真实的添加管道跑通(走 useAttachments)。
const mockUploadAttachment = vi.fn()
vi.mock('../../api/attachments', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../api/attachments')>()
  return {
    ...actual,
    uploadAttachment: (...args: unknown[]) => mockUploadAttachment(...args),
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
  pendingAttachments: undefined,
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
  mockUploadAttachment.mockResolvedValue({ id: 'att-1', mime: 'image/png', size: 1, width: 10, height: 10, sha256: null })
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

  it('shows the pending-image badge when the queued message carries attachments', () => {
    wsState = {
      ...baseState,
      pendingMessage: 'queued text',
      pendingAttachments: [{ id: 'a1' }, { id: 'a2' }],
    }
    renderWindow({ conversationId: 'conv-1' })
    expect(screen.getByTestId('pending-attach-badge')).toHaveTextContent('+ 2 张图片')
  })

  it('drops image files into the shared pipeline and sends them with the message', async () => {
    renderWindow({ conversationId: 'conv-1' })
    // 文档级拖放:dataTransfer.types 含 Files 才触发
    fireEvent.dragEnter(document, { dataTransfer: { types: ['Files'], files: [] } })
    expect(screen.getByTestId('drop-overlay')).toBeInTheDocument()
    const file = new File(['x'], 'shot.png', { type: 'image/png' })
    fireEvent.drop(document, { dataTransfer: { types: ['Files'], files: [file] } })
    await waitFor(() => {
      expect(screen.getByTestId('attachments-strip')).toBeInTheDocument()
    })
    await waitFor(() => {
      expect(screen.getByTestId('attachments-strip').querySelector('[data-status="ready"]')).toBeTruthy()
    })

    fireEvent.change(screen.getByPlaceholderText(/Type a message/i), { target: { value: '看图' } })
    fireEvent.click(screen.getByRole('button', { name: 'Send' }))
    await waitFor(() => {
      expect(baseState.sendMessage).toHaveBeenCalledWith('看图', 'conv-1', [{ id: 'att-1' }])
    })
    // 发送成功后清空附件草稿
    expect(screen.queryByTestId('attachments-strip')).not.toBeInTheDocument()
  })

  it('does not trigger the drop overlay for non-file drags (coder code-drag)', () => {
    renderWindow({ conversationId: 'conv-1' })
    fireEvent.dragEnter(document, { dataTransfer: { types: ['text/plain'], files: [] } })
    expect(screen.queryByTestId('drop-overlay')).not.toBeInTheDocument()
  })
})

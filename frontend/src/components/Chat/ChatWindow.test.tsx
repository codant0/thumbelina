import { describe, it, expect, vi, beforeEach } from 'vitest'
import { act, render, screen, fireEvent, waitFor } from '@testing-library/react'
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
  pendingActive: false,
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
  // ── 工具详情侧边面板(点击芯片打开,遮罩/X 关闭,内容实时跟随)──────────

  const toolMessages = (status: 'running' | 'ok', result?: string) => [
    {
      id: 'a1',
      role: 'assistant' as const,
      content: 'done',
      timestamp: '2024-01-01T00:00:00Z',
      toolCalls: [
        { call_id: 'c1', name: 'web_search', args: { query: 'hi' }, status, ...(result ? { result, durationMs: 42 } : {}) },
      ],
    },
  ]

  it('opens the tool detail side panel from a tool chip and closes via backdrop', () => {
    wsState = { ...baseState, messages: toolMessages('ok', 'found 3 results') as never }
    const { container } = renderWindow()
    expect(container.querySelector('[data-testid="tool-detail-side-panel"]')).toBeNull()
    fireEvent.click(container.querySelector('.tool-call__summary')!)
    const panel = container.querySelector('[data-testid="tool-detail-side-panel"]')
    expect(panel).not.toBeNull()
    expect(panel!.textContent).toContain('web_search')
    expect(panel!.textContent).toContain('found 3 results')
    fireEvent.click(container.querySelector('[data-testid="tool-detail-backdrop"]')!)
    expect(container.querySelector('[data-testid="tool-detail-side-panel"]')).toBeNull()
  })

  it('keeps the panel content in sync with the latest tool state while streaming', () => {
    wsState = { ...baseState, messages: toolMessages('running') as never }
    const { container, rerender } = renderWindow()
    fireEvent.click(container.querySelector('.tool-call__summary')!)
    expect(container.querySelector('[data-testid="tool-detail-side-panel"]')!.textContent).not.toContain('found 3 results')
    // running → ok 的 upsert 发生在消息树后面板上实时跟随(按 msgId+call_id 解析)
    wsState = { ...baseState, messages: toolMessages('ok', 'found 3 results') as never }
    rerender(<ChatWindow ws={wsState} />)
    expect(container.querySelector('[data-testid="tool-detail-side-panel"]')!.textContent).toContain('found 3 results')
  })

  it('switches panel content when clicking another tool chip', () => {
    wsState = {
      ...baseState,
      messages: [
        {
          id: 'a1',
          role: 'assistant' as const,
          content: 'done',
          timestamp: '2024-01-01T00:00:00Z',
          toolCalls: [
            { call_id: 'c1', name: 'web_search', args: {}, status: 'ok' as const, durationMs: 10 },
            { call_id: 'c2', name: 'read_file', args: {}, status: 'ok' as const, durationMs: 20 },
          ],
        },
      ],
    }
    const { container } = renderWindow()
    const chips = container.querySelectorAll('.tool-call__summary')
    fireEvent.click(chips[0]!)
    expect(container.querySelector('[data-testid="tool-detail-side-panel"]')!.textContent).toContain('web_search')
    fireEvent.click(chips[1]!)
    expect(container.querySelector('[data-testid="tool-detail-side-panel"]')!.textContent).toContain('read_file')
  })

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
    wsState = { ...baseState, pendingActive: true, pendingMessage: 'queued text' }
    renderWindow({ conversationId: 'conv-1' })

    expect(screen.getByTestId('pending-message')).toHaveTextContent('queued text')

    fireEvent.click(screen.getByTestId('pending-send-now'))
    expect(baseState.sendPendingNow).toHaveBeenCalledWith('conv-1')

    fireEvent.click(screen.getByTestId('pending-cancel'))
    expect(baseState.cancelPendingMessage).toHaveBeenCalledWith('conv-1')
  })

  it('marks the queued bar as held after an abnormal reply end', () => {
    wsState = { ...baseState, pendingActive: true, pendingMessage: 'queued text', pendingHeld: true }
    renderWindow({ conversationId: 'conv-1' })
    expect(screen.getByText(/auto-send paused/i)).toBeInTheDocument()
  })

  it('shows the pending-image badge when the queued message carries attachments', () => {
    wsState = {
      ...baseState,
      pendingActive: true,
      pendingMessage: 'queued text',
      pendingAttachments: [{ id: 'a1' }, { id: 'a2' }],
    }
    renderWindow({ conversationId: 'conv-1' })
    expect(screen.getByTestId('pending-attach-badge')).toHaveTextContent('+ 2 image(s)')
  })

  it('renders the queued bar for an image-only queue (empty text) with the badge text', () => {
    // Finding 3 回归:hook 对纯图片排队暴露 pendingActive=true 而 pendingMessage
    // 为 ''(假值);ChatWindow 原样透传,悬浮条照常渲染并以徽标为正文。
    wsState = {
      ...baseState,
      pendingActive: true,
      pendingMessage: '',
      pendingAttachments: [{ id: 'a1' }],
    }
    renderWindow({ conversationId: 'conv-1' })
    expect(screen.getByTestId('pending-message')).toBeInTheDocument()
    expect(screen.getByTestId('pending-attach-badge')).toHaveTextContent('+ 1 image(s)')
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
      expect(baseState.sendMessage).toHaveBeenCalledWith('看图', 'conv-1', [
        { id: 'att-1', mime: 'image/png', width: 10, height: 10 },
      ])
    })
    // 发送成功后清空附件草稿
    expect(screen.queryByTestId('attachments-strip')).not.toBeInTheDocument()
  })

  it('does not trigger the drop overlay for non-file drags (coder code-drag)', () => {
    renderWindow({ conversationId: 'conv-1' })
    fireEvent.dragEnter(document, { dataTransfer: { types: ['text/plain'], files: [] } })
    expect(screen.queryByTestId('drop-overlay')).not.toBeInTheDocument()
  })

  it('keeps every dropped attachment ready when uploads resolve individually (race regression)', async () => {
    // 拖放多文件的竞态回归(与 InputBox 📎 路径共用管道,覆盖 ChatWindow 侧的
    // 函数式 ctx):后一张的上传补丁不得用过期快照覆盖前一张刚落地的 ready。
    const resolveUpload: Array<(v: unknown) => void> = []
    mockUploadAttachment
      .mockImplementationOnce(() => new Promise(resolve => { resolveUpload.push(resolve) }))
      .mockImplementationOnce(() => new Promise(resolve => { resolveUpload.push(resolve) }))
    renderWindow({ conversationId: 'conv-1' })
    fireEvent.dragEnter(document, { dataTransfer: { types: ['Files'], files: [] } })
    fireEvent.drop(document, {
      dataTransfer: {
        types: ['Files'],
        files: [
          new File(['x'], 'first.png', { type: 'image/png' }),
          new File(['x'], 'second.png', { type: 'image/png' }),
        ],
      },
    })
    await waitFor(() => expect(mockUploadAttachment).toHaveBeenCalledTimes(1))

    // 同一 act 域内先后 resolve 两张的上传(仅冲微任务,React 不提交任何 ready)
    await act(async () => {
      resolveUpload[0]({ id: 'att-drop-a', mime: 'image/png', size: 1, width: 10, height: 10, sha256: null })
      for (let i = 0; i < 20; i++) await Promise.resolve()
      expect(mockUploadAttachment).toHaveBeenCalledTimes(2)
      resolveUpload[1]({ id: 'att-drop-b', mime: 'image/png', size: 1, width: 10, height: 10, sha256: null })
      for (let i = 0; i < 5; i++) await Promise.resolve()
    })

    await waitFor(() => {
      const thumbs = [...screen.getByTestId('attachments-strip').children]
      expect(thumbs.map(t => t.getAttribute('data-status'))).toEqual(['ready', 'ready'])
    })

    fireEvent.change(screen.getByPlaceholderText(/Type a message/i), { target: { value: '看图' } })
    fireEvent.click(screen.getByRole('button', { name: 'Send' }))
    await waitFor(() => {
      expect(baseState.sendMessage).toHaveBeenCalledWith('看图', 'conv-1', [
        { id: 'att-drop-a', mime: 'image/png', width: 10, height: 10 },
        { id: 'att-drop-b', mime: 'image/png', width: 10, height: 10 },
      ])
    })
  })

  // ── 重新生成携带附件(设计 §5.4 / F8)────────────────────────────────────────

  it('regenerate resends the last user message with its attachment refs', () => {
    wsState = {
      ...baseState,
      messages: [
        { id: '1', role: 'user', content: '看图', timestamp: '', attachments: [{ id: 'att-1', mime: 'image/png', alt: '首页截图' }, { id: 'att-2', mime: 'image/png' }] },
        { id: '2', role: 'assistant', content: 'answer', timestamp: '' },
      ],
    }
    renderWindow({ conversationId: 'conv-1' })

    fireEvent.click(screen.getByTestId('regenerate'))
    expect(baseState.sendMessage).toHaveBeenCalledTimes(1)
    expect(baseState.sendMessage).toHaveBeenCalledWith('看图', 'conv-1', [
      { id: 'att-1', alt: '首页截图' },
      { id: 'att-2' },
    ])
  })

  it('regenerate keeps the two-argument sendMessage call for a text-only message', () => {
    // 回归:无附件的历史消息重新生成时保持旧调用形状(第三参不出现)。
    wsState = {
      ...baseState,
      messages: [
        { id: '1', role: 'user', content: 'hi', timestamp: '' },
        { id: '2', role: 'assistant', content: 'yo', timestamp: '' },
      ],
    }
    renderWindow({ conversationId: 'conv-1' })

    fireEvent.click(screen.getByTestId('regenerate'))
    expect(baseState.sendMessage).toHaveBeenCalledTimes(1)
    expect(baseState.sendMessage).toHaveBeenCalledWith('hi', 'conv-1')
    expect(vi.mocked(baseState.sendMessage).mock.calls[0]).toHaveLength(2)
  })

  it('regenerate respects the streaming guard (no resend mid-reply)', () => {
    wsState = {
      ...baseState,
      isStreaming: true,
      messages: [
        { id: '1', role: 'user', content: 'hi', timestamp: '', attachments: [{ id: 'att-1', mime: 'image/png' }] },
        { id: 'stream-2', role: 'assistant', content: 'partial', timestamp: '' },
      ],
    }
    renderWindow({ conversationId: 'conv-1' })

    // 流式中 MessageList 不渲染 regenerate 按钮;守卫本身在 ChatWindow 内兜底。
    expect(screen.queryByTestId('regenerate')).not.toBeInTheDocument()
    expect(baseState.sendMessage).not.toHaveBeenCalled()
  })

  it('queues a message with attachment refs while streaming (three-argument queuePendingMessage)', async () => {
    wsState = {
      ...baseState,
      isStreaming: true,
      messages: [
        { id: '1', role: 'user', content: 'hi', timestamp: '' },
        { id: 'stream-2', role: 'assistant', content: 'answ', timestamp: '' },
      ],
    }
    renderWindow({ conversationId: 'conv-1' })

    fireEvent.dragEnter(document, { dataTransfer: { types: ['Files'], files: [] } })
    fireEvent.drop(document, { dataTransfer: { types: ['Files'], files: [new File(['x'], 'shot.png', { type: 'image/png' })] } })
    await waitFor(() => {
      expect(screen.getByTestId('attachments-strip').querySelector('[data-status="ready"]')).toBeTruthy()
    })

    fireEvent.change(screen.getByPlaceholderText(/Type a message/i), { target: { value: '排队看图' } })
    fireEvent.click(screen.getByRole('button', { name: 'Send' }))
    await waitFor(() => {
      expect(baseState.queuePendingMessage).toHaveBeenCalledWith('排队看图', 'conv-1', [
        { id: 'att-1', mime: 'image/png', width: 10, height: 10 },
      ])
    })
    expect(baseState.sendMessage).not.toHaveBeenCalled()
  })

  it('clears the attachment draft when the conversation switches (workspace semantics)', async () => {
    // 验收 §9:码农页切换 WorkspacePicker 后 attachments 清空 —— 附件草稿
    // 归会话持有,切会话(切 workspace 同语义)时随状态一起清掉,且不补发上传。
    const { rerender } = renderWindow({ conversationId: 'conv-1' })

    fireEvent.dragEnter(document, { dataTransfer: { types: ['Files'], files: [] } })
    fireEvent.drop(document, { dataTransfer: { types: ['Files'], files: [new File(['x'], 'shot.png', { type: 'image/png' })] } })
    await waitFor(() => {
      expect(screen.getByTestId('attachments-strip').querySelector('[data-status="ready"]')).toBeTruthy()
    })

    const uploadsBefore = mockUploadAttachment.mock.calls.length
    rerender(<ChatWindow ws={wsState} conversationId="conv-2" />)
    await waitFor(() => {
      expect(screen.queryByTestId('attachments-strip')).not.toBeInTheDocument()
    })
    expect(mockUploadAttachment).toHaveBeenCalledTimes(uploadsBefore)
  })
})

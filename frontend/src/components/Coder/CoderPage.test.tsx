import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { CoderPage } from './CoderPage'
import { LocaleProvider } from '../../i18n'
import type { ChatSocket } from '../../hooks/useWebSocket'
import type { Conversation } from '../../types/chat'

// The coder page receives the lifted WebSocket state via the `ws` prop —
// same stub shape used by ChatWindow tests.
const ws = {
  messages: [],
  isConnected: true,
  isReconnecting: false,
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
} as ChatSocket

const conv = (id: string, mode: 'chat' | 'coder'): Conversation => ({
  id,
  name: null,
  mode,
  workspace: mode === 'coder' ? 'C:\\proj\\alpha' : undefined,
  created_at: '2026-08-22T10:00:00Z',
  updated_at: '2026-08-22T10:00:00Z',
})

const renderPage = (props: Record<string, unknown> = {}) =>
  render(
    <LocaleProvider>
      <CoderPage
        ws={ws}
        conversations={[conv('chat1', 'chat'), conv('coder1', 'coder')]}
        onSelect={vi.fn()}
        onCreated={vi.fn()}
        onRefresh={vi.fn()}
        {...props}
      />
    </LocaleProvider>,
  )

describe('CoderPage', () => {
  it('shows the placeholder and no message input when a chat-mode conversation is selected', () => {
    renderPage({ selectedId: 'chat1' })
    expect(screen.getByTestId('coder-no-selection')).toBeInTheDocument()
    expect(screen.queryByTestId('chat-window')).not.toBeInTheDocument()
    expect(screen.queryByPlaceholderText(/Type a message/i)).not.toBeInTheDocument()
  })

  it('shows the placeholder and no message input when no conversation is selected', () => {
    renderPage({ selectedId: undefined })
    expect(screen.getByTestId('coder-no-selection')).toBeInTheDocument()
    expect(screen.queryByTestId('chat-window')).not.toBeInTheDocument()
    expect(screen.queryByPlaceholderText(/Type a message/i)).not.toBeInTheDocument()
  })

  it('shows the placeholder when the selected conversation does not exist', () => {
    renderPage({ selectedId: 'ghost' })
    expect(screen.getByTestId('coder-no-selection')).toBeInTheDocument()
    expect(screen.queryByTestId('chat-window')).not.toBeInTheDocument()
  })

  it('renders the chat window when a coder-mode conversation is selected', () => {
    renderPage({ selectedId: 'coder1' })
    expect(screen.queryByTestId('coder-no-selection')).not.toBeInTheDocument()
    expect(screen.getByTestId('chat-window')).toBeInTheDocument()
    expect(screen.getByPlaceholderText(/Type a message/i)).toBeInTheDocument()
  })

  it('exposes the attachment entry and file drop overlay in the coder chat window', () => {
    // 码农页复用 ChatWindow(验收 §9):📎 附件按钮 + 隐藏 file input 存在,
    // 拖文件进窗口同样弹出蒙层(拖代码块不带 Files 不触发,已在 ChatWindow 侧覆盖)。
    renderPage({ selectedId: 'coder1' })
    expect(screen.getByRole('button', { name: 'Add image' })).toBeInTheDocument()
    expect(screen.getByTestId('attach-input')).toBeInTheDocument()
    fireEvent.dragEnter(document, { dataTransfer: { types: ['Files'], files: [] } })
    expect(screen.getByTestId('drop-overlay')).toBeInTheDocument()
    fireEvent.dragLeave(document, { dataTransfer: { types: ['Files'], files: [] } })
    expect(screen.queryByTestId('drop-overlay')).not.toBeInTheDocument()
  })

  it('shows the hero empty state and opens the picker via its CTA', () => {
    renderPage({ conversations: [] })
    expect(screen.getByTestId('coder-hero-empty')).toBeInTheDocument()
    fireEvent.click(screen.getByTestId('coder-hero-cta'))
    expect(screen.getByTestId('workspace-picker')).toBeInTheDocument()
  })

  it('opens the picker with the N shortcut from the empty state', () => {
    renderPage({ conversations: [] })
    fireEvent.keyDown(window, { key: 'n' })
    expect(screen.getByTestId('workspace-picker')).toBeInTheDocument()
  })

  it('shows loading state without the hero', () => {
    renderPage({ conversations: [], coderLoading: true })
    expect(screen.queryByTestId('coder-hero-empty')).not.toBeInTheDocument()
    expect(screen.getByTestId('coder-sidebar-loading')).toBeInTheDocument()
  })

  it('shows the load error with a retry button', () => {
    const onRefresh = vi.fn()
    renderPage({ conversations: [], coderError: true, onRefresh })
    expect(screen.getByTestId('coder-load-error')).toBeInTheDocument()
    fireEvent.click(screen.getByTestId('coder-retry'))
    expect(onRefresh).toHaveBeenCalled()
  })
})
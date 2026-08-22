import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { CoderPage } from './CoderPage'
import { LocaleProvider } from '../../i18n'
import type { ChatSocket } from '../../hooks/useWebSocket'
import type { Conversation } from '../../types/chat'

// The coder page receives the lifted WebSocket state via the `ws` prop —
// same stub shape used by ChatWindow tests.
const ws = {
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
})
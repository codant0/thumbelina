import { useState, useCallback, useEffect, useMemo } from 'react'
import { useWebSocket } from '../../hooks/useWebSocket'
import { MessageList } from './MessageList'
import { InputBox } from './InputBox'
import { ConversationModelSelector } from './ConversationModelSelector'
import { KnowledgeBaseSelector } from './KnowledgeBaseSelector'
import { RoleSelector } from './RoleSelector'
import { ThinkingSelector } from './ThinkingSelector'
import { Mail, Eraser } from 'lucide-react'
import type { Conversation, ThinkingEffort } from '../../types/chat'
import { useTranslation } from '../../i18n'
import { clearConversationMessages } from '../../api/conversations'

interface ChatWindowProps {
  conversationId?: string
  conversations?: Conversation[]
  onConversationCreated?: () => void
  onDefaultConversation?: (id: string) => void
  onSetEndpoint?: (id: string, endpointId: string | null, model: string | null) => void
  onSetKnowledgeBase?: (id: string, knowledgeBaseId: string | null) => void
  onSetRole?: (id: string, role: string | null) => void
  onSetThinking?: (id: string, enabled: boolean, effort: ThinkingEffort) => void
}

export function ChatWindow({ conversationId, conversations, onConversationCreated, onDefaultConversation, onSetEndpoint, onSetKnowledgeBase, onSetRole, onSetThinking }: ChatWindowProps) {
  const wsUrl = useMemo(() => {
    const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    return `${wsProtocol}//${window.location.host}/ws/chat`
  }, [])

  const { messages, isConnected, isStreaming, streamingMode: wsStreamingMode, waitingForReply, newConversationId, clearNewConversation, sendMessage, clearMessages, switchConversation, loadHistory } = useWebSocket(wsUrl, conversationId)
  const [streamingMode, setStreamingMode] = useState(true)
  const [toggling, setToggling] = useState(false)
  const [clearing, setClearing] = useState(false)
  const { t } = useTranslation()

  // Sync from WebSocket when backend reports mode
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setStreamingMode(wsStreamingMode)
  }, [wsStreamingMode])

  // Load history and notify backend when switching to an existing conversation
  useEffect(() => {
    if (conversationId) {
      switchConversation(conversationId)
      clearMessages()
      loadHistory(conversationId)
    }
  }, [conversationId, switchConversation, clearMessages, loadHistory])

  // Fetch initial config
  useEffect(() => {
    fetch('/api/v1/config')
      .then(res => res.ok ? res.json() : null)
      .then(data => { if (data?.streaming_enabled !== undefined) setStreamingMode(data.streaming_enabled) })
      .catch(() => {})
  }, [])

  // Refresh sidebar and auto-select when a genuinely new conversation is created
  useEffect(() => {
    if (newConversationId) {
      onConversationCreated?.()
      onDefaultConversation?.(newConversationId)
      clearNewConversation()
    }
  }, [newConversationId, onConversationCreated, onDefaultConversation, clearNewConversation])

  const handleSend = (text: string) => {
    sendMessage(text, conversationId)
  }

  const handleClearContext = useCallback(async () => {
    if (!conversationId || clearing) return
    if (!window.confirm(t('chat.clearContextConfirm'))) return
    setClearing(true)
    try {
      await clearConversationMessages(conversationId)
      clearMessages()
    } catch {
      // keep messages on failure
    } finally {
      setClearing(false)
    }
  }, [conversationId, clearing, clearMessages, t])

  const toggleStreaming = useCallback(async () => {
    const next = !streamingMode
    setToggling(true)
    try {
      await fetch('/api/v1/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ llm: { streaming_enabled: next } }),
      })
      setStreamingMode(next)
    } catch {
      // keep current state on failure
    } finally {
      setToggling(false)
    }
  }, [streamingMode])

  const statusText = isConnected
    ? isStreaming
      ? t('common.generating')
      : t('common.connected')
    : t('common.disconnected')

  const statusClass = isConnected
    ? isStreaming
      ? 'streaming'
      : 'connected'
    : 'disconnected'

  const activeConversation = useMemo(
    () => (Array.isArray(conversations) ? conversations.find(c => c.id === conversationId) : undefined),
    [conversations, conversationId],
  )

  return (
    <div className="chat-area" data-testid="chat-window">
      <div className="chat-status">
        <span className={`dot ${statusClass}`} />
        <span>{statusText}</span>
        <button
          className="streaming-toggle"
          data-testid="streaming-toggle"
          onClick={toggleStreaming}
          disabled={isStreaming || toggling}
          title={streamingMode ? t('chat.streamOnTitle') : t('chat.streamOffTitle')}
        >
          <span className={`toggle-dot ${streamingMode ? 'on' : 'off'}`} />
          <span>{t('chat.streamLabel')}</span>
        </button>
        {onSetEndpoint && conversationId && (
          <ConversationModelSelector
            conversationId={conversationId}
            selectedEndpointId={activeConversation?.endpoint_id ?? null}
            selectedModel={activeConversation?.model ?? null}
            onChange={(endpointId, model) => onSetEndpoint(conversationId, endpointId, model)}
          />
        )}
        {conversationId && (
          <button
            type="button"
            className="clear-context-btn"
            data-testid="clear-context"
            title={t('chat.clearContext')}
            aria-label={t('chat.clearContext')}
            onClick={() => void handleClearContext()}
            disabled={clearing || isStreaming || messages.length === 0}
          >
            <Eraser size={14} />
            <span>{t('chat.clearContext')}</span>
          </button>
        )}
      </div>
      {messages.length === 0 ? (
        <div className="empty-state">
          <div className="empty-icon"><Mail size={24} /></div>
          <p>{t('chat.startPrompt')}</p>
          <p className="empty-hint">{t('chat.startHint')}</p>
        </div>
      ) : (
        <MessageList messages={messages} waitingForReply={waitingForReply} isStreaming={isStreaming} />
      )}
      <InputBox
        onSend={handleSend}
        disabled={!isConnected || isStreaming}
        toolbar={
          conversationId ? (
            <>
              {onSetThinking && (
                <ThinkingSelector
                  conversationId={conversationId}
                  enabled={activeConversation?.thinking_enabled ?? false}
                  effort={activeConversation?.thinking_effort ?? 'medium'}
                  onChange={(enabled, effort) => onSetThinking(conversationId, enabled, effort)}
                />
              )}
              {onSetRole && (
                <RoleSelector
                  conversationId={conversationId}
                  selectedRole={activeConversation?.role ?? null}
                  onChange={(role) => onSetRole(conversationId, role)}
                />
              )}
              {onSetKnowledgeBase && (
                <KnowledgeBaseSelector
                  conversationId={conversationId}
                  selectedKnowledgeBaseId={activeConversation?.knowledge_base_id ?? null}
                  onChange={(kbId) => onSetKnowledgeBase(conversationId, kbId)}
                />
              )}
            </>
          ) : undefined
        }
      />
    </div>
  )
}

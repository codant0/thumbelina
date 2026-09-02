import { useState, useCallback, useEffect, useMemo } from 'react'
import type { ChatSocket } from '../../hooks/useWebSocket'
import { MessageList } from './MessageList'
import { InputBox } from './InputBox'
import { ConversationModelSelector } from './ConversationModelSelector'
import { KnowledgeBaseSelector } from './KnowledgeBaseSelector'
import { RoleSelector } from './RoleSelector'
import { ThinkingSelector } from './ThinkingSelector'
import { ContextUsageItem } from '../StatusBar/ContextUsageItem'
import { CacheHitRateItem } from '../StatusBar/CacheHitRateItem'
import { GitBranchSelector } from '../StatusBar/GitBranchSelector'
import { Toast } from '../Settings/Toast'
import { Mail, Eraser, Shrink, Route } from 'lucide-react'
import type { Conversation, ThinkingEffort } from '../../types/chat'
import { useTranslation } from '../../i18n'
import { clearConversationMessages, compressConversation } from '../../api/conversations'
import { ConfirmDialog } from '../common/ConfirmDialog'

interface ChatWindowProps {
  /** WebSocket state lifted to App so the connection survives page switches. */
  ws: ChatSocket
  conversationId?: string
  conversations?: Conversation[]
  onConversationCreated?: () => void
  onDefaultConversation?: (id: string) => void
  onSetEndpoint?: (id: string, endpointId: string | null, model: string | null) => void
  onSetKnowledgeBase?: (id: string, knowledgeBaseId: string | null) => void
  onSetRole?: (id: string, role: string | null) => void
  onSetThinking?: (id: string, enabled: boolean, effort: ThinkingEffort) => void
  onViewTrajectory?: (id: string) => void
}

export function ChatWindow({ ws, conversationId, conversations, onConversationCreated, onDefaultConversation, onSetEndpoint, onSetKnowledgeBase, onSetRole, onSetThinking, onViewTrajectory }: ChatWindowProps) {
  const { messages, isConnected, isStreaming, streamingMode: wsStreamingMode, waitingForReply, awaitingMoreContent, newConversationId, clearNewConversation, pendingMessage, pendingHeld, queuePendingMessage, sendPendingNow, cancelPendingMessage, sendMessage, stopGeneration, clearMessages, switchConversation, loadHistory } = ws
  const [streamingMode, setStreamingMode] = useState(true)
  const [toggling, setToggling] = useState(false)
  const [clearing, setClearing] = useState(false)
  const [confirmClear, setConfirmClear] = useState(false)
  const [compressing, setCompressing] = useState(false)
  // Local inline feedback for the compress action (quiet success/failure hint).
  const [compressNotice, setCompressNotice] = useState<{ message: string; isError: boolean } | null>(null)
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
    setConfirmClear(false)
    setClearing(true)
    try {
      await clearConversationMessages(conversationId)
      clearMessages(conversationId)
    } catch {
      // keep messages on failure
    } finally {
      setClearing(false)
    }
  }, [conversationId, clearing, clearMessages])

  const handleCompress = useCallback(async () => {
    if (!conversationId || compressing) return
    setCompressing(true)
    setCompressNotice(null)
    try {
      const result = await compressConversation(conversationId)
      if (result.compressed) {
        setCompressNotice({ message: t('chat.compressSuccess'), isError: false })
      } else {
        // Backend reported it was not needed/unavailable — quiet, non-blocking notice.
        setCompressNotice({ message: result.reason ?? t('chat.compressSkipped'), isError: false })
      }
    } catch {
      setCompressNotice({ message: t('chat.compressFailed'), isError: true })
    } finally {
      setCompressing(false)
    }
  }, [conversationId, compressing, t])

  const handleStop = useCallback(() => {
    // Fire-and-forget over WS; the backend cancels the reply and replies with
    // { stopped: true }, at which point the hook clears isStreaming and this
    // button disappears.
    stopGeneration()
  }, [stopGeneration])

  const handleRegenerate = useCallback(() => {
    if (isStreaming || !isConnected) return
    const lastUser = [...messages].reverse().find(m => m.role === 'user')
    if (lastUser) sendMessage(lastUser.content, conversationId)
  }, [messages, isStreaming, isConnected, conversationId, sendMessage])

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
        {conversationId && onViewTrajectory && (
          <button
            type="button"
            className="clear-context-btn"
            data-testid="view-trajectory"
            title={t('chat.viewTrajectoryTitle')}
            aria-label={t('chat.viewTrajectoryTitle')}
            onClick={() => onViewTrajectory(conversationId)}
          >
            <Route size={14} />
            <span>{t('chat.viewTrajectory')}</span>
          </button>
        )}
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
            onClick={() => setConfirmClear(true)}
            disabled={clearing || isStreaming || messages.length === 0}
          >
            <Eraser size={14} />
            <span>{t('chat.clearContext')}</span>
          </button>
        )}
        {conversationId && (
          <button
            type="button"
            className="clear-context-btn compress-btn"
            data-testid="compress-context"
            title={t('chat.compressTitle')}
            aria-label={t('chat.compressTitle')}
            onClick={() => void handleCompress()}
            disabled={compressing || isStreaming || messages.length === 0}
          >
            <Shrink size={14} />
            <span>{compressing ? t('chat.compressInProgress') : t('chat.compress')}</span>
          </button>
        )}
      </div>
      <Toast
        message={compressNotice?.message ?? ''}
        isError={compressNotice?.isError}
        onClose={() => setCompressNotice(null)}
      />
      {confirmClear && (
        <ConfirmDialog
          title={t('chat.clearContext')}
          message={t('chat.clearContextConfirm')}
          danger
          onConfirm={() => void handleClearContext()}
          onCancel={() => setConfirmClear(false)}
        />
      )}
      {messages.length === 0 ? (
        <div className="empty-state">
          <div className="empty-icon"><Mail size={24} /></div>
          <p>{t('chat.startPrompt')}</p>
          <p className="empty-hint">{t('chat.startHint')}</p>
        </div>
      ) : (
        <MessageList messages={messages} waitingForReply={waitingForReply} isStreaming={isStreaming} awaitingMoreContent={awaitingMoreContent} onRegenerate={handleRegenerate} />
      )}
      <InputBox
        onSend={handleSend}
        disabled={!isConnected}
        isStreaming={isStreaming}
        onStop={handleStop}
        pendingMessage={pendingMessage}
        pendingHeld={pendingHeld}
        onQueueSend={text => queuePendingMessage(text, conversationId)}
        onSendPendingNow={() => sendPendingNow(conversationId)}
        onCancelPending={() => cancelPendingMessage(conversationId)}
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
              {/* 状态栏分组：上下文占用 + KV 缓存命中率（只读展示，不触发 LLM 调用） */}
              <div className="statusbar-group">
                <ContextUsageItem
                  messages={messages}
                  endpointId={activeConversation?.endpoint_id ?? null}
                />
                <CacheHitRateItem conversationId={conversationId} />
                <GitBranchSelector ws={ws} workspace={activeConversation?.workspace ?? null} />
              </div>
            </>
          ) : undefined
        }
      />
    </div>
  )
}

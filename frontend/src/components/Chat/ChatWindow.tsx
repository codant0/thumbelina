import { useState, useCallback, useEffect, useMemo } from 'react'
import { useWebSocket } from '../../hooks/useWebSocket'
import { MessageList } from './MessageList'
import { InputBox } from './InputBox'

interface ChatWindowProps {
  conversationId?: string
  onConversationCreated?: () => void
  onDefaultConversation?: (id: string) => void
}

export function ChatWindow({ conversationId, onConversationCreated, onDefaultConversation }: ChatWindowProps) {
  const wsUrl = useMemo(() => {
    const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    return `${wsProtocol}//${window.location.host}/ws/chat`
  }, [])

  const { messages, isConnected, isStreaming, streamingMode: wsStreamingMode, waitingForReply, lastConversationId, newConversationId, clearNewConversation, sendMessage, clearMessages, switchConversation, loadHistory } = useWebSocket(wsUrl, conversationId)
  const [streamingMode, setStreamingMode] = useState(true)
  const [toggling, setToggling] = useState(false)

  // Sync from WebSocket when backend reports mode
  useEffect(() => {
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
      ? 'Generating...'
      : 'Connected'
    : 'Disconnected'

  const statusClass = isConnected
    ? isStreaming
      ? 'streaming'
      : 'connected'
    : 'disconnected'

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
          title={streamingMode ? 'Streaming on — typewriter effect' : 'Streaming off — instant reply'}
        >
          <span className={`toggle-dot ${streamingMode ? 'on' : 'off'}`} />
          <span>Stream</span>
        </button>
      </div>
      {messages.length === 0 ? (
        <div className="empty-state">
          <div className="empty-icon">&#9993;</div>
          <p>Start a conversation</p>
          <p className="empty-hint">Type a message below to begin</p>
        </div>
      ) : (
        <MessageList messages={messages} waitingForReply={waitingForReply} conversationId={conversationId ?? lastConversationId ?? undefined} />
      )}
      <InputBox onSend={handleSend} disabled={!isConnected || isStreaming} />
    </div>
  )
}

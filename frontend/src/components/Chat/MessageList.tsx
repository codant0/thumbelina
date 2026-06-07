import { useEffect, useRef, useState, useCallback } from 'react'
import type { Message } from '../../types/chat'

interface MessageListProps {
  messages: Message[]
  waitingForReply?: boolean
  conversationId?: string
}

export function MessageList({ messages, waitingForReply, conversationId }: MessageListProps) {
  const listRef = useRef<HTMLDivElement>(null)
  const [ratings, setRatings] = useState<Record<number, number>>({})

  useEffect(() => {
    const el = listRef.current
    if (el) {
      el.scrollTop = el.scrollHeight
    }
  }, [messages, waitingForReply])

  const handleRate = useCallback(async (messageIndex: number, rating: number) => {
    if (!conversationId || ratings[messageIndex] !== undefined) return
    setRatings(prev => ({ ...prev, [messageIndex]: rating }))
    try {
      await fetch('/api/v1/feedback', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          conversation_id: conversationId,
          message_index: messageIndex,
          rating,
        }),
      })
    } catch {
      // revert on failure
      setRatings(prev => {
        const next = { ...prev }
        delete next[messageIndex]
        return next
      })
    }
  }, [conversationId, ratings])

  return (
    <div className="message-list" data-testid="message-list" ref={listRef}>
      {messages.map((msg, idx) => (
        <div key={msg.id} data-testid="message-item" className={`message ${msg.role}`}>
          <span className="msg-role">
            {msg.role === 'user' ? 'You' : msg.role === 'system' ? 'System' : 'Assistant'}
          </span>
          <div className="msg-content">{msg.content}</div>
          {msg.toolCalls && msg.toolCalls.length > 0 && (
            <div className="tool-calls" data-testid="tool-calls">
              {msg.toolCalls.map((tc, i) => (
                <div key={i} className="tool-call" data-testid="tool-call">
                  <span className="tool-name">{tc.name}</span>
                  <div className="tool-args">{JSON.stringify(tc.args, null, 2)}</div>
                  {tc.result && <div className="tool-result">{tc.result}</div>}
                </div>
              ))}
            </div>
          )}
          {msg.role === 'assistant' && conversationId && (
            <div className="feedback-row" data-testid="feedback-row">
              {[1, 2, 3, 4, 5].map(star => (
                <button
                  key={star}
                  className={`star-btn${ratings[idx] !== undefined ? (star <= ratings[idx] ? ' filled' : '') : ''}`}
                  data-testid={`star-${star}`}
                  disabled={ratings[idx] !== undefined}
                  onClick={() => void handleRate(idx, star)}
                  aria-label={`Rate ${star} star${star > 1 ? 's' : ''}`}
                >
                  {star <= (ratings[idx] ?? 0) ? '★' : '☆'}
                </button>
              ))}
              {ratings[idx] !== undefined && (
                <span className="feedback-thanks" data-testid="feedback-thanks">Thanks!</span>
              )}
            </div>
          )}
        </div>
      ))}
      {waitingForReply && (
        <div className="message assistant typing-indicator" data-testid="typing-indicator">
          <span className="msg-role">Assistant</span>
          <div className="typing-dots">
            <span className="typing-dot" />
            <span className="typing-dot" />
            <span className="typing-dot" />
          </div>
        </div>
      )}
    </div>
  )
}

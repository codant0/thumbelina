import { useEffect, useRef } from 'react'
import type { Message } from '../../types/chat'

interface MessageListProps {
  messages: Message[]
  waitingForReply?: boolean
}

export function MessageList({ messages, waitingForReply }: MessageListProps) {
  const listRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const el = listRef.current
    if (el) {
      el.scrollTop = el.scrollHeight
    }
  }, [messages, waitingForReply])

  return (
    <div className="message-list" data-testid="message-list" ref={listRef}>
      {messages.map(msg => (
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

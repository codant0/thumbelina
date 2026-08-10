import { useEffect, useRef, useState } from 'react'
import type { Message } from '../../types/chat'
import { Brain, ChevronDown, Wrench } from 'lucide-react'
import { useTranslation } from '../../i18n'
import { MarkdownContent } from './MarkdownContent'

interface MessageListProps {
  messages: Message[]
  waitingForReply?: boolean
  isStreaming?: boolean
}

interface ThinkingBlockProps {
  thinking: string
  active: boolean
}

function ThinkingBlock({ thinking, active }: ThinkingBlockProps) {
  const [userOverride, setUserOverride] = useState<boolean | null>(null)
  const { t } = useTranslation()

  // Auto-expand while the model is still thinking, auto-collapse when done,
  // unless the user explicitly toggled the block for this message.
  const open = userOverride ?? active

  return (
    <div className={`msg-thinking${active ? ' is-active' : ''}`} data-testid="thinking-block">
      <button
        type="button"
        className="msg-thinking__header"
        aria-expanded={open}
        onClick={() => setUserOverride(!open)}
      >
        <Brain size={13} className="msg-thinking__icon" />
        <span className="msg-thinking__label">{t('chat.thinkingProcess')}</span>
        {active && <span className="msg-thinking__pulse" aria-hidden="true" />}
        <ChevronDown size={13} className={`msg-thinking__caret${open ? ' is-open' : ''}`} />
      </button>
      {open && (
        <div className="msg-thinking__body" data-testid="thinking-body">
          <MarkdownContent content={thinking} />
        </div>
      )}
    </div>
  )
}

export function MessageList({ messages, waitingForReply, isStreaming }: MessageListProps) {
  const listRef = useRef<HTMLDivElement>(null)
  const { t } = useTranslation()

  useEffect(() => {
    const el = listRef.current
    if (el) {
      el.scrollTop = el.scrollHeight
    }
  }, [messages, waitingForReply])

  const streamingMsgId = isStreaming
    ? [...messages].reverse().find(m => m.role === 'assistant' && m.id.startsWith('stream-'))?.id
    : undefined

  return (
    <div className="message-list" data-testid="message-list" ref={listRef}>
      {messages.map(msg => (
        <div key={msg.id} data-testid="message-item" className={`message ${msg.role}`}>
          <span className="msg-role">
            {msg.role === 'user' ? t('chat.roleYou') : msg.role === 'system' ? t('chat.roleSystem') : t('chat.roleAssistant')}
          </span>
          {msg.thinking && msg.role === 'assistant' && (
            <ThinkingBlock thinking={msg.thinking} active={msg.id === streamingMsgId} />
          )}
          <div className="msg-content">
            {msg.role === 'assistant' ? (
              <MarkdownContent content={msg.content} />
            ) : (
              msg.content
            )}
          </div>
          {msg.toolCalls && msg.toolCalls.length > 0 && (
            <div className="tool-calls" data-testid="tool-calls">
              {msg.toolCalls.map((tc, i) => (
                <div key={i} className="tool-call" data-testid="tool-call">
                  <span className="tool-name"><Wrench size={14} />{tc.name}</span>
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
          <span className="msg-role">{t('chat.roleAssistant')}</span>
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

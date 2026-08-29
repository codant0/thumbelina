import { memo, useEffect, useMemo, useRef, useState } from 'react'
import type { Message, ToolCall } from '../../types/chat'
import { ArrowDown, Brain, Check, ChevronDown, Copy, RefreshCcw, Wrench } from 'lucide-react'
import { useTranslation } from '../../i18n'
import { MarkdownContent } from './MarkdownContent'
import { JsonBlock } from './CodeBlock'
import { splitLeadingJson } from '../../lib/codeUtils'
import { useCopy } from '../../hooks/useCopy'

interface MessageListProps {
  messages: Message[]
  waitingForReply?: boolean
  isStreaming?: boolean
  /** Stream is active but has no *new* text to reveal (e.g. waiting for the
   *  next chunk or the model to finish) — drives the "generating…" pulse. */
  awaitingMoreContent?: boolean
  /** Re-send the latest user turn (offered on the last assistant message). */
  onRegenerate?: () => void
}

interface ThinkingBlockProps {
  thinking: string
  active: boolean
}

function ThinkingBlock({ thinking, active }: ThinkingBlockProps) {
  const [userOverride, setUserOverride] = useState<boolean | null>(null)
  const bodyRef = useRef<HTMLDivElement>(null)
  const { t } = useTranslation()

  // Auto-expand while the model is still thinking, auto-collapse when done,
  // unless the user explicitly toggled the block for this message.
  const open = userOverride ?? active

  // The body has its own scroll area (max-height in CSS). Follow the
  // newest thinking content unless the user has scrolled up to read.
  useEffect(() => {
    const el = bodyRef.current
    if (!el) return
    const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 24
    if (nearBottom) el.scrollTop = el.scrollHeight
  }, [thinking, open])

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
        <div className="msg-thinking__body" data-testid="thinking-body" ref={bodyRef}>
          <MarkdownContent content={thinking} />
        </div>
      )}
    </div>
  )
}

/** One tool call rendered as a collapsed summary card. */
function ToolCallItem({ tc }: { tc: ToolCall }) {
  const [open, setOpen] = useState(false)
  const { t } = useTranslation()
  const argsText = useMemo(() => {
    try {
      return JSON.stringify(tc.args, null, 2)
    } catch {
      return String(tc.args)
    }
  }, [tc.args])
  return (
    <div className="tool-call" data-testid="tool-call">
      <button type="button" className="tool-call__summary" aria-expanded={open} onClick={() => setOpen(o => !o)}>
        <span className="tool-call__name"><Wrench size={13} /><span>{tc.name}</span></span>
        <span className="tool-call__meta">
          {tc.result ? t('toolCalls.hasResult') : t('toolCalls.arguments')}
        </span>
        <ChevronDown size={14} className={`tool-call__caret${open ? ' is-open' : ''}`} />
      </button>
      {open && (
        <div className="tool-call__detail">
          <div className="tool-call__section-label">{t('toolCalls.arguments')}</div>
          <pre>{argsText}</pre>
          {tc.result && (
            <>
              <div className="tool-call__section-label">{t('toolCalls.result')}</div>
              <pre>{tc.result}</pre>
            </>
          )}
        </div>
      )}
    </div>
  )
}

/** Copy (and, for the last assistant turn, regenerate) actions on hover. */
function MessageActions({ text, onRegenerate }: { text: string; onRegenerate?: () => void }) {
  const { copied, copy } = useCopy()
  const { t } = useTranslation()
  return (
    <div className="msg-actions">
      <button
        type="button"
        className={`msg-actions__btn${copied ? ' is-done' : ''}`}
        onClick={() => void copy(text)}
        title={copied ? t('chat.copied') : t('chat.copy')}
        aria-label={t('chat.copy')}
      >
        {copied ? <Check size={13} /> : <Copy size={13} />}
      </button>
      {onRegenerate && (
        <button
          type="button"
          className="msg-actions__btn"
          data-testid="regenerate"
          onClick={onRegenerate}
          title={t('chat.regenerate')}
          aria-label={t('chat.regenerate')}
        >
          <RefreshCcw size={13} />
        </button>
      )}
    </div>
  )
}

/** Assistant content with a leading raw-JSON payload lifted into a card. */
function AssistantContent({ content }: { content: string }) {
  const split = useMemo(() => splitLeadingJson(content), [content])
  if (!split) return <MarkdownContent content={content} />
  return (
    <>
      <JsonBlock text={split.json} />
      {split.rest && <MarkdownContent content={split.rest} />}
    </>
  )
}

const MessageItem = memo(function MessageItem({
  msg,
  isStreamingMsg,
  canRegenerate,
  onRegenerate,
}: {
  msg: Message
  isStreamingMsg: boolean
  canRegenerate: boolean
  onRegenerate?: () => void
}) {
  const { t } = useTranslation()
  return (
    <div
      data-testid="message-item"
      className={`message ${msg.role}`}
      {...(isStreamingMsg ? { 'data-streaming': 'true' } : {})}
    >
      <span className="msg-role">
        {msg.role === 'user' ? t('chat.roleYou') : msg.role === 'system' ? t('chat.roleSystem') : t('chat.roleAssistant')}
      </span>
      {msg.thinking && msg.role === 'assistant' && (
        <ThinkingBlock thinking={msg.thinking} active={isStreamingMsg} />
      )}
      <div className="msg-content">
        {msg.role === 'assistant' ? (
          <AssistantContent content={msg.content} />
        ) : (
          msg.content
        )}
      </div>
      {msg.toolCalls && msg.toolCalls.length > 0 && (
        <div className="tool-calls" data-testid="tool-calls">
          {msg.toolCalls.map((tc, i) => (
            <ToolCallItem key={i} tc={tc} />
          ))}
        </div>
      )}
      {msg.content && (
        <MessageActions
          text={msg.content}
          onRegenerate={canRegenerate ? onRegenerate : undefined}
        />
      )}
    </div>
  )
})

function MessageListInner({ messages, waitingForReply, isStreaming, awaitingMoreContent, onRegenerate }: MessageListProps) {
  const listRef = useRef<HTMLDivElement>(null)
  // Whether to keep following new content. False once the user scrolls up to read.
  const stickToBottomRef = useRef(true)
  const firstMsgIdRef = useRef<string | undefined>(undefined)
  const { t } = useTranslation()
  const [showGenerating, setShowGenerating] = useState(Boolean(isStreaming && awaitingMoreContent))
  const [showJump, setShowJump] = useState(false)

  // 流式块之间的停顿极短（毫秒级），直接跟随 awaitingMoreContent 会让"生成中"
  // 提示随每个块高频挂载/卸载而闪烁；延迟隐藏把短暂间隙合并成连续显示。
  useEffect(() => {
    if (isStreaming && awaitingMoreContent) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setShowGenerating(true)
      return
    }
    const timer = setTimeout(() => setShowGenerating(false), 500)
    return () => clearTimeout(timer)
  }, [isStreaming, awaitingMoreContent])

  const handleScroll = () => {
    const el = listRef.current
    if (!el) return
    // Consider "at bottom" within a small threshold to tolerate rounding.
    const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight
    stickToBottomRef.current = distanceFromBottom < 40
    setShowJump(distanceFromBottom > 320)
  }

  useEffect(() => {
    const el = listRef.current
    if (!el) return
    // The list was replaced entirely (conversation switch / history reload) —
    // resume following and jump to the latest message.
    const firstId = messages[0]?.id
    if (firstId !== firstMsgIdRef.current) {
      firstMsgIdRef.current = firstId
      stickToBottomRef.current = true
    }
    // Always jump to the bottom when the newest message is one the user just sent.
    const last = messages[messages.length - 1]
    if (last?.role === 'user') {
      stickToBottomRef.current = true
    }
    if (stickToBottomRef.current) {
      el.scrollTop = el.scrollHeight
    }
  }, [messages, waitingForReply])

  const streamingMsgId = isStreaming
    ? [...messages].reverse().find(m => m.role === 'assistant' && m.id.startsWith('stream-'))?.id
    : undefined

  // Regenerate is offered on the last assistant message of an idle conversation.
  const lastAssistantId = !isStreaming
    ? [...messages].reverse().find(m => m.role === 'assistant')?.id
    : undefined
  const handleRegenerate = onRegenerate

  const scrollToBottom = () => {
    const el = listRef.current
    if (!el) return
    stickToBottomRef.current = true
    el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' })
    setShowJump(false)
  }

  return (
    <div className="message-list-wrap">
      <div
        className="message-list"
        data-testid="message-list"
        ref={listRef}
        onScroll={handleScroll}
        {...(isStreaming ? {} : { 'data-streaming-idle': '' })}
      >
        {messages.map(msg => (
          <MessageItem
            key={msg.id}
            msg={msg}
            isStreamingMsg={msg.id === streamingMsgId}
            canRegenerate={msg.id === lastAssistantId && Boolean(handleRegenerate)}
            onRegenerate={handleRegenerate}
          />
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
        {showGenerating && !waitingForReply && (
          <div className="message assistant generating-indicator" data-testid="generating-indicator">
            <span className="msg-role">{t('chat.roleAssistant')}</span>
            <div className="generating-dots" aria-hidden="true">
              <span className="generating-dot" />
              <span className="generating-dot" />
              <span className="generating-dot" />
            </div>
            <span className="generating-label">{t('chat.generating')}</span>
          </div>
        )}
      </div>
      {showJump && (
        <button
          type="button"
          className="scroll-bottom-btn"
          data-testid="scroll-to-bottom"
          onClick={scrollToBottom}
          title={t('chat.scrollToBottom')}
          aria-label={t('chat.scrollToBottom')}
        >
          <ArrowDown size={16} />
        </button>
      )}
    </div>
  )
}

export const MessageList = memo(MessageListInner)

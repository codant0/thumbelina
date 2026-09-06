import { memo, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import type { AttachmentRef, Message, SubagentEventPayload, ToolCall } from '../../types/chat'
import { ArrowDown, Brain, Check, ChevronDown, Copy, RefreshCcw, Wrench } from 'lucide-react'
import { useTranslation } from '../../i18n'
import { MarkdownContent } from './MarkdownContent'
import { JsonBlock } from './CodeBlock'
import { SubagentCard } from './SubagentCard'
import { AttachmentLightbox } from './AttachmentLightbox'
import { attachmentUrl } from '../../api/attachments'
import { splitLeadingJson } from '../../lib/codeUtils'
import { groupAnchorsByOffset, splitContentByAnchors, summarizeToolCalls } from './toolCallEvents'
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
  /** Subagent 事件按 assistant 消息 id 分组;用于在该消息下方内联展示卡片。 */
  subagentsByMsgId?: Record<string, SubagentEventPayload[]>
  /** 点击 "查看对话详情" 时的回调;由 ChatWindow 提供用于打开详情 Modal。 */
  onViewSubagentDetail?: (event: SubagentEventPayload) => void
  /** 点击聚合工具入口时的回调;由 ChatWindow 提供用于打开侧边统一面板。 */
  onViewToolCalls?: (msgId: string, callIds: string[]) => void
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

/**
 * 聚合工具入口(设计修订):一个批次(同一轮 LLM 响应的并发调用)收拢为
 * 一个按钮,点击由 ChatWindow 打开侧边面板展示本批调用。
 * 状态取聚合语义:任一 running > 任一 error > interrupted > ok。
 */
function ToolCallsEntry({ calls, onOpen }: { calls: ToolCall[]; onOpen?: () => void }) {
  const { t } = useTranslation()
  const s = summarizeToolCalls(calls)
  const status =
    s.running > 0 ? 'running' : s.error > 0 ? 'error' : s.interrupted > 0 ? 'interrupted' : 'ok'
  return (
    <div className={`tool-calls-entry status-${status}`} data-testid="tool-calls-entry">
      <button type="button" className="tool-calls-entry__btn" onClick={onOpen} aria-haspopup="dialog">
        <span className="tool-call__name"><Wrench size={13} /><span>{t('toolCalls.button')}</span></span>
        <span className="tool-calls-entry__count">{s.total}</span>
        {s.running > 0 && <span className="tool-call__spinner" aria-hidden="true" />}
        <span className="tool-calls-entry__meta">
          {s.running > 0 && t('toolCalls.running')}
          {s.running === 0 && s.error > 0 && '✗'}
          {s.running === 0 && s.error === 0 && s.interrupted > 0 && t('toolCalls.interrupted')}
          {s.running === 0 && s.error === 0 && s.interrupted === 0 && '✓'}
        </span>
      </button>
    </div>
  )
}

/**
 * 穿插渲染(设计 §5.3 修订):按锚点 offset 把工具调用**分批**切进文本流 ——
 * 同一轮大模型响应的并发调用(offset 相同)共享一个入口按钮,插在该轮文本
 * 之后;后续轮次的工具是下一个批次按钮。仅实时消息携带 anchors,历史消息
 * 走平铺布局。
 */
function InterleavedContent({
  msg,
  onViewToolCalls,
}: {
  msg: Message
  onViewToolCalls?: (msgId: string, callIds: string[]) => void
}) {
  const batches = useMemo(() => groupAnchorsByOffset(msg.toolAnchors ?? []), [msg.toolAnchors])
  const segments = useMemo(
    () => splitContentByAnchors(msg.content, batches.map(b => ({ callId: b.callIds[0], offset: b.offset }))),
    [msg.content, batches],
  )
  const byCallId = useMemo(
    () => new Map((msg.toolCalls ?? []).map(tc => [tc.call_id, tc])),
    [msg.toolCalls],
  )
  return (
    <>
      {segments.map((seg, i) => {
        if (seg.type === 'text') {
          return seg.text ? <AssistantContent key={`t${i}`} content={seg.text} /> : null
        }
        const batch = batches.find(b => b.callIds[0] === seg.callId)
        if (!batch) return null
        const calls = batch.callIds
          .map(id => byCallId.get(id))
          .filter((tc): tc is ToolCall => Boolean(tc))
        if (!calls.length) return null
        return (
          <ToolCallsEntry
            key={`c${i}`}
            calls={calls}
            onOpen={onViewToolCalls ? () => onViewToolCalls(msg.id, batch.callIds) : undefined}
          />
        )
      })}
    </>
  )
}

/** Copy (and, for the last assistant turn, regenerate) actions on hover. */function MessageActions({ text, onRegenerate }: { text: string; onRegenerate?: () => void }) {
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

/**
 * 用户消息里的单张附件缩略图(设计 §5.2):
 * - URL 由 attachmentUrl(id) 自拼;乐观插入的本地消息 attachments 无 mime,渲染不得依赖 mime;
 * - 加载失败(死链/网络)→ 破图占位 + 「重试加载」文本按钮重设 src;
 * - 点击打开 Lightbox。
 */
function MsgAttachmentThumb({ att, onOpen }: { att: AttachmentRef; onOpen: () => void }) {
  const { t } = useTranslation()
  const [broken, setBroken] = useState(false)
  const [reloadKey, setReloadKey] = useState(0)
  if (broken) {
    return (
      <span className="msg-attachment-thumb--broken" data-broken="true">
        <button
          type="button"
          data-testid="attachment-retry"
          onClick={() => {
            setBroken(false)
            setReloadKey(k => k + 1)
          }}
        >
          {t('chat.attachments.retryLoad')}
        </button>
      </span>
    )
  }
  return (
    <button type="button" className="msg-attachment-thumb-btn" aria-label={t('chat.attachments.lightboxOpen')} onClick={onOpen}>
      <img
        className="msg-attachment-thumb"
        src={reloadKey > 0 ? `${attachmentUrl(att.id)}?r=${reloadKey}` : attachmentUrl(att.id)}
        alt={att.alt ?? ''}
        onError={() => setBroken(true)}
      />
    </button>
  )
}

const MessageItem = memo(function MessageItem({
  msg,
  isStreamingMsg,
  canRegenerate,
  onRegenerate,
  subagents,
  onViewSubagentDetail,
  onViewToolCalls,
}: {
  msg: Message
  isStreamingMsg: boolean
  canRegenerate: boolean
  onRegenerate?: () => void
  subagents?: SubagentEventPayload[]
  onViewSubagentDetail?: (event: SubagentEventPayload) => void
  onViewToolCalls?: (msgId: string, callIds: string[]) => void
}) {
  const { t } = useTranslation()
  // 该消息附件的 Lightbox 下标;null = 关闭。memo 组件内部 state 即可,无需提升。
  const [lightboxIndex, setLightboxIndex] = useState<number | null>(null)
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
      {msg.role === 'user' && msg.attachments && msg.attachments.length > 0 && (
        <div className="msg-attachments" data-testid="msg-attachments">
          {msg.attachments.map((att, i) => (
            <MsgAttachmentThumb key={att.id} att={att} onOpen={() => setLightboxIndex(i)} />
          ))}
        </div>
      )}
      <div className="msg-content">
        {msg.role === 'assistant' ? (
          msg.toolCalls?.length ? (
            msg.toolAnchors?.length ? (
              <InterleavedContent msg={msg} onViewToolCalls={onViewToolCalls} />
            ) : (
              <>
                <AssistantContent content={msg.content} />
                <ToolCallsEntry
                  calls={msg.toolCalls}
                  onOpen={
                    onViewToolCalls
                      ? () => onViewToolCalls(msg.id, msg.toolCalls!.map(tc => tc.call_id ?? ''))
                      : undefined
                  }
                />
              </>
            )
          ) : (
            <AssistantContent content={msg.content} />
          )
        ) : (
          msg.content
        )}
      </div>
      {subagents && subagents.length > 0 && (
        <div className="subagent-cards" data-testid="subagent-cards">
          {subagents.map(sa => (
            <SubagentCard
              key={sa.id}
              event={sa}
              {...(onViewSubagentDetail ? { onViewDetail: onViewSubagentDetail } : {})}
            />
          ))}
        </div>
      )}
      {msg.content && (
        <MessageActions
          text={msg.content}
          onRegenerate={canRegenerate ? onRegenerate : undefined}
        />
      )}
      {lightboxIndex !== null && msg.attachments && msg.attachments.length > 0 && (
        <AttachmentLightbox
          attachments={msg.attachments}
          index={lightboxIndex}
          onClose={() => setLightboxIndex(null)}
          onIndexChange={setLightboxIndex}
        />
      )}
    </div>
  )
})

function MessageListInner({ messages, waitingForReply, isStreaming, awaitingMoreContent, onRegenerate, subagentsByMsgId, onViewSubagentDetail, onViewToolCalls }: MessageListProps) {
  const listRef = useRef<HTMLDivElement>(null)
  const contentRef = useRef<HTMLDivElement>(null)
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

  // Stream / user-sent messages: snap to bottom (one rAF so the browser
  // has measured the freshly appended children). Skipped entirely when
  // the user has scrolled up to read.
  useEffect(() => {
    const el = listRef.current
    if (!el) return
    // The newest message is one the user just sent — force-follow even if
    // they had scrolled up earlier in the session.
    const last = messages[messages.length - 1]
    const userSentNow = last?.role === 'user'
    if (!userSentNow && !stickToBottomRef.current) return

    const raf = requestAnimationFrame(() => {
      const node = listRef.current
      if (node) node.scrollTop = node.scrollHeight
    })
    return () => cancelAnimationFrame(raf)
  }, [messages, waitingForReply])

  // On conversation switch / history reload (first message id changed)
  // jump to the latest message synchronously after layout. Runs only on
  // first mount and on head-of-list changes — independent of the
  // stream-follow effect above, which only fires when already at bottom.
  useLayoutEffect(() => {
    const el = listRef.current
    if (!el) return
    if (firstMsgIdRef.current === undefined) {
      // First mount: place at the bottom.
      firstMsgIdRef.current = messages[0]?.id
      el.scrollTop = el.scrollHeight
    } else if (messages[0]?.id !== firstMsgIdRef.current) {
      // Head of the list was replaced — treat as a new conversation.
      firstMsgIdRef.current = messages[0]?.id
      stickToBottomRef.current = true
      el.scrollTop = el.scrollHeight
    }
  }, [messages])

  // Content-height watchdog: whenever the rendered content changes height
  // (streaming text, async expansion, font swap, native scroll anchoring),
  // clamp to the bottom while the user is following. One-shot rAF passes
  // cannot cover sources that grow AFTER the commit — this observer can.
  useEffect(() => {
    const content = contentRef.current
    if (!content || typeof ResizeObserver === 'undefined') return
    let raf = 0
    const ro = new ResizeObserver(() => {
      if (!stickToBottomRef.current) return
      cancelAnimationFrame(raf)
      raf = requestAnimationFrame(() => {
        const node = listRef.current
        if (node) node.scrollTop = node.scrollHeight
      })
    })
    ro.observe(content)
    return () => {
      ro.disconnect()
      cancelAnimationFrame(raf)
    }
  }, [])

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
        <div className="message-list-content" ref={contentRef}>
          {messages.map(msg => (
            <MessageItem
              key={msg.id}
              msg={msg}
              isStreamingMsg={msg.id === streamingMsgId}
              canRegenerate={msg.id === lastAssistantId && Boolean(handleRegenerate)}
              onRegenerate={handleRegenerate}
              subagents={subagentsByMsgId?.[msg.id]}
              {...(onViewSubagentDetail ? { onViewSubagentDetail } : {})}
              {...(onViewToolCalls ? { onViewToolCalls } : {})}
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

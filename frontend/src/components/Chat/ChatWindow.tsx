import { useState, useCallback, useEffect, useMemo, useRef } from 'react'
import type { ChatSocket } from '../../hooks/useWebSocket'
import { subscribeSubagentEvents } from '../../hooks/useWebSocket'
import { MessageList } from './MessageList'
import { InputBox, type LocalAttachment } from './InputBox'
import { addFilesToAttachments, attachmentHintText, type AttachmentHint } from './useAttachments'
import { DropOverlay } from './DropOverlay'
import { ConversationModelSelector } from './ConversationModelSelector'
import { KnowledgeBaseSelector } from './KnowledgeBaseSelector'
import { RoleSelector } from './RoleSelector'
import { ThinkingSelector } from './ThinkingSelector'
import { ContextUsageItem } from '../StatusBar/ContextUsageItem'
import { CacheHitRateItem } from '../StatusBar/CacheHitRateItem'
import { GitBranchSelector } from '../StatusBar/GitBranchSelector'
import { Toast } from '../Settings/Toast'
import { Mail, Eraser, Shrink, Route } from 'lucide-react'
import type { Conversation, SendAttachmentInput, SubagentEventPayload, ThinkingEffort } from '../../types/chat'
import { useTranslation } from '../../i18n'
import { clearConversationMessages, compressConversation } from '../../api/conversations'
import { ConfirmDialog } from '../common/ConfirmDialog'
import { SubagentSidePanel } from './SubagentSidePanel'

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
  const { messages, isConnected, isStreaming, streamingMode: wsStreamingMode, waitingForReply, awaitingMoreContent, newConversationId, clearNewConversation, pendingMessage, pendingAttachments, pendingHeld, queuePendingMessage, sendPendingNow, cancelPendingMessage, sendMessage, stopGeneration, clearMessages, switchConversation, loadHistory } = ws
  const [streamingMode, setStreamingMode] = useState(true)
  const [toggling, setToggling] = useState(false)
  const [clearing, setClearing] = useState(false)
  const [confirmClear, setConfirmClear] = useState(false)
  const [compressing, setCompressing] = useState(false)
  // 待发附件草稿(设计 §5.1):受控数组在这里持有,InputBox 通过 onAttachmentsChange 同步;
  // 拖放(drop)与 📎 按钮共用 useAttachments 的同一条添加管道。
  const [attachments, setAttachments] = useState<LocalAttachment[]>([])
  // 拖放管道的临时行内提示(超出上限/类型不支持等,2 秒自动消失)。
  const [dropHint, setDropHint] = useState<AttachmentHint | null>(null)
  // 管道 async 续段里要读最新列表 —— ref 镜像,避免闭包过期。
  const attachmentsRef = useRef<LocalAttachment[]>([])
  // Local inline feedback for the compress action (quiet success/failure hint).
  const [compressNotice, setCompressNotice] = useState<{ message: string; isError: boolean } | null>(null)
  // Subagent 事件按 assistant 消息 id 分组:
  //   conv_id -> msg_id -> latest event per subagent id
  // 在 SubagentCard 阶段已用 ref/useState 简化,这里用 useState 让 React 重新渲染。
  const [subagentsByConvId, setSubagentsByConvId] = useState<Record<string, Record<string, Record<string, SubagentEventPayload>>>>({})
  // 右侧详情面板:同时只展示一个 subagent;null 表示收起。
  const [selectedSubagentId, setSelectedSubagentId] = useState<string | null>(null)
  // 当前会话缓存上一次的映射,确保 useEffect 中能读到上一轮的值。
  const lastConvIdRef = useRef<string | undefined>(conversationId)
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

  // 附件 ref 镜像:drop 管道的 async 续段读取最新列表用。
  useEffect(() => {
    attachmentsRef.current = attachments
  }, [attachments])

  // 拖放提示 2 秒自动消失。
  useEffect(() => {
    if (!dropHint) return
    const timer = setTimeout(() => setDropHint(null), 2000)
    return () => clearTimeout(timer)
  }, [dropHint])

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

  // 订阅后端广播的 subagent_event 帧;组件卸载时自动退订。
  // 事件归到"当前正在生成的最后一条 assistant 消息"下:
  // - 优先匹配 stream- 开头的临时消息(流式期间);
  // - 退回匹配最后一条 assistant 消息(流结束后仍能看到卡片)。
  useEffect(() => {
    const unsubscribe = subscribeSubagentEvents((event, convId) => {
      if (!convId) return
      setSubagentsByConvId(prev => {
        const convBucket = { ...(prev[convId] ?? {}) }
        // 找到本轮应该挂载的目标 assistant 消息 id
        const targetMsgId = pickAssistantMsgId(messages)
        if (!targetMsgId) return prev
        const msgBucket = { ...(convBucket[targetMsgId] ?? {}) }
        // 同 id 的事件按 type 覆盖(started 不会被 completed 之外的覆盖)
        const existing = msgBucket[event.id]
        if (!existing || shouldReplace(existing, event)) {
          msgBucket[event.id] = event
        }
        convBucket[targetMsgId] = msgBucket
        return { ...prev, [convId]: convBucket }
      })
    })
    return unsubscribe
  }, [messages])

  // 发送:无就绪附件时保持两参调用(sendMessage(text, conversationId)),
  // 有就绪附件时把 {id, alt} 引用一并带上(协议 §4.1)。
  const handleSend = (text: string, readyRefs?: SendAttachmentInput[]) => {
    if (readyRefs && readyRefs.length > 0) sendMessage(text, conversationId, readyRefs)
    else sendMessage(text, conversationId)
  }

  // 流式进行中提交 → 排队为待发消息,附件引用随文字一起进入待发队列。
  const handleQueueSend = (text: string, readyRefs?: SendAttachmentInput[]) => {
    if (readyRefs && readyRefs.length > 0) queuePendingMessage(text, conversationId, readyRefs)
    else queuePendingMessage(text, conversationId)
  }

  // 拖放落下:与 📎 按钮共用同一条添加管道(useAttachments.addFilesToAttachments),
  // 管道放这里(而非 InputBox 内部)以避免 InputBox 内部状态外泄(设计 §5 / Task F4)。
  const handleDropFiles = useCallback((files: File[]) => {
    void addFilesToAttachments(files, {
      getCurrent: () => attachmentsRef.current,
      onChange: setAttachments,
    }).then(hint => {
      if (hint) setDropHint(hint)
    })
  }, [])

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

  // 把嵌套桶扁平化为 MessageList 期望的 Record<msgId, SubagentEventPayload[]>。
  // 切换会话时丢弃上一会话的桶,避免跨会话泄漏。
  const subagentsByMsgId = useMemo(() => {
    const conv = subagentsByConvId[conversationId ?? ''] ?? {}
    const flat: Record<string, SubagentEventPayload[]> = {}
    for (const [msgId, bySubId] of Object.entries(conv)) {
      flat[msgId] = Object.values(bySubId)
    }
    return flat
  }, [subagentsByConvId, conversationId])

  // 计算所有已打开 subagent 的最新事件快照(供窗口渲染);按 subagent_id 去重。
  const subagentEventsById = useMemo(() => {
    const map: Record<string, SubagentEventPayload> = {}
    for (const byMsgId of Object.values(subagentsByMsgId)) {
      for (const evt of byMsgId) {
        map[evt.id] = evt
      }
    }
    return map
  }, [subagentsByMsgId])

  // 点击 subagent 卡片时打开(同一会话内同一时间只展示一个)。
  const openSubagentDetail = useCallback((event: SubagentEventPayload) => {
    setSelectedSubagentId(event.id)
  }, [])

  // 关闭右侧详情面板(由面板 X 按钮、点外部遮罩、Esc 触发)。
  const closeSubagentDetail = useCallback(() => {
    setSelectedSubagentId(null)
  }, [])

  // Esc 关闭详情面板。仅在面板打开时监听,避免无谓事件。
  useEffect(() => {
    if (!selectedSubagentId) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') closeSubagentDetail()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [selectedSubagentId, closeSubagentDetail])

  // conversation 切换时清理状态,确保下一会话从空桶开始。
  // 附件草稿随会话切换清空(设计 §5.3:跨 Workspace 切换同语义)。
  useEffect(() => {
    if (lastConvIdRef.current !== conversationId) {
      lastConvIdRef.current = conversationId
      setSelectedSubagentId(null)
      setAttachments([])
    }
  }, [conversationId])

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
        <MessageList
          messages={messages}
          waitingForReply={waitingForReply}
          isStreaming={isStreaming}
          awaitingMoreContent={awaitingMoreContent}
          onRegenerate={handleRegenerate}
          subagentsByMsgId={subagentsByMsgId}
          onViewSubagentDetail={openSubagentDetail}
        />
      )}
      {/* 右侧详情面板 + 外部遮罩:点击遮罩或面板 X 即可关闭。
          遮罩覆盖 chat-area 但不覆盖面板本身(面板 z 更高),
          给用户「主对话在背后、面板是浮起的」这一观感。 */}
      {selectedSubagentId && (
        <>
          <button
            type="button"
            className="subagent-side-panel__backdrop"
            data-testid="subagent-side-panel-backdrop"
            aria-label={t('common.close')}
            onClick={closeSubagentDetail}
          />
          {subagentEventsById[selectedSubagentId] && (
            <SubagentSidePanel
              event={subagentEventsById[selectedSubagentId]}
              onClose={closeSubagentDetail}
            />
          )}
        </>
      )}
      {/* 全屏拖放覆盖层:仅当拖入 dataTransfer 含 Files 时出现;drop 与 📎 按钮共用添加管道。 */}
      <DropOverlay onFiles={handleDropFiles} />
      {dropHint && (
        /* 拖放添加管道的临时行内提示(2 秒自动消失;T7 i18n + 样式) */
        <div className="attachment-error-hint" role="status">{attachmentHintText(dropHint)}</div>
      )}
      <InputBox
        onSend={handleSend}
        disabled={!isConnected}
        isStreaming={isStreaming}
        onStop={handleStop}
        pendingMessage={pendingMessage}
        pendingHeld={pendingHeld}
        attachments={attachments}
        onAttachmentsChange={setAttachments}
        pendingAttachmentCount={pendingAttachments?.length ?? 0}
        onQueueSend={handleQueueSend}
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

/** 选择"本轮应该挂载 subagent 卡片的 assistant 消息 id"。 */
function pickAssistantMsgId(messages: ReadonlyArray<{ id: string; role: string }>): string | undefined {
  // 优先匹配正在流式的那条(stream-* 临时 id),否则退回最后一条 assistant。
  for (let i = messages.length - 1; i >= 0; i--) {
    const m = messages[i]
    if (m.role === 'assistant' && m.id.startsWith('stream-')) return m.id
  }
  for (let i = messages.length - 1; i >= 0; i--) {
    const m = messages[i]
    if (m.role === 'assistant') return m.id
  }
  return undefined
}

/** 决定新事件是否覆盖桶内已有事件。started 之后只能被终态覆盖,中间不重置。 */
function shouldReplace(existing: SubagentEventPayload, incoming: SubagentEventPayload): boolean {
  if (incoming.type === 'subagent.started') return existing.type === 'subagent.started'
  // completed/failed/cancelled 都是终态,新事件覆盖旧事件保持单调推进
  return true
}

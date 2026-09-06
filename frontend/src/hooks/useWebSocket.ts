import { useCallback, useEffect, useRef, useState } from 'react'
import type { AttachmentRef, Message, SendAttachmentInput, SubagentEventPayload, ToolAnchor, ToolCall, ToolEventPayload } from '../types/chat'
import { markInterrupted, upsertToolCall } from '../components/Chat/toolCallEvents'

interface WsIncoming {
  chunk?: string
  chunk_type?: 'reasoning' | string
  response?: string
  done?: boolean
  /** Backend finished cancelling a streaming reply after the user pressed stop. */
  stopped?: boolean
  /** 心跳应答:仅作链路活性证明,不参与任何业务状态。 */
  pong?: boolean
  conversation_id?: string
  error?: string
  streaming_mode?: boolean
  connected?: boolean
  conversation_switched?: boolean
  conversation_created?: string
  channel_message?: {
    channel: string
    conversation_id: string
    user_message: string
    response: string
    source?: string
    /** 入站微信图片的附件 refs(设计 §2);纯文本轮为 null。 */
    attachments?: AttachmentRef[] | null
  }
  /** 后端切换 git 分支后广播的事件,携带工作区与当前分支名。 */
  git_branch?: { workspace: string; branch: string }
  /** 任务调度器生命周期事件(设计 §8.2),与 REST 事件视图字节同构。 */
  task_event?: TaskEventPayload
  /** Subagent 生命周期事件(开始/完成/失败/取消),由聊天窗口订阅并内联展示。 */
  subagent_event?: SubagentEventPayload
  /** 实时工具调用事件(设计 §5.2):start/end 成对、按 call_id 配对,先于/交错于
   *  文本 chunk 到达;由当轮 assistant 占位消息按 call_id upsert 工具卡。 */
  tool_event?: ToolEventPayload
}

/** ``{task_event: …}`` 帧体;与 ``GET /tasks/events`` 的条目结构一致。 */
export interface TaskEventPayload {
  id: string
  /** task.created | task.due | task.completed | task.failed | task.missed | task.cancelled */
  type: string
  task_id: string
  fired_at: string
  trigger: string
  channel: string
  content: string
  payload: Record<string, unknown> | null
}

type WsListener = (msg: WsIncoming) => void

type TaskEventListener = (payload: TaskEventPayload) => void

// 任务事件监听器(模块级):TaskManager/TaskEventFeed 挂在聊天路由之外,拿不到
// App 持有的 ChatSocket 实例,通过这里订阅 task_event 帧,避免为任务页另开
// 一条 /ws/chat 连接。
const taskEventListeners = new Set<TaskEventListener>()

/** 订阅后端广播的 task_event 帧;返回退订函数。 */
export function subscribeTaskEvents(fn: TaskEventListener): () => void {
  taskEventListeners.add(fn)
  return () => { taskEventListeners.delete(fn) }
}

// Subagent 生命周期事件监听器(模块级):ChatWindow 卸载/重连时需要重订阅,
// 模块级 Set 让 ChatWindow 挂载即生效,无需关心 ws 实例何时初始化。
type SubagentEventListener = (payload: SubagentEventPayload, conversationId: string | undefined) => void
const subagentEventListeners = new Set<SubagentEventListener>()

/** 订阅后端广播的 subagent_event 帧;返回退订函数。 */
export function subscribeSubagentEvents(fn: SubagentEventListener): () => void {
  subagentEventListeners.add(fn)
  return () => { subagentEventListeners.delete(fn) }
}

// 打字机阶梯式提速:首批字符最快(让"开口"明显),中段最快,长文本末段降到 3/tick
// 避免高频闪烁。整体节奏较旧 3/30 提速约 2.5-3 倍。
const TICK_INTERVAL = 18
const charsPerTick = (revealed: number) => (revealed < 80 ? 5 : revealed < 240 ? 6 : 3)

/** 单个 tick 应推进的字符数:按真实经过时间折算等效 tick 数后逐档累加。
 *  浏览器会把后台标签页的定时器节流到约 1 次/秒,固定字数/tick 会让显示进度
 *  按墙钟大幅落后(切回后从旧进度慢慢补打);折算后单次 tick 按比例补齐,
 *  前台正常 18ms 间隔下 elapsed≈TICK_INTERVAL → ticks=1,与固定步进完全一致。 */
export function advanceFor(revealed: number, elapsedMs: number): number {
  const ticks = Math.max(1, Math.round(elapsedMs / TICK_INTERVAL))
  let advance = 0
  for (let i = 0; i < ticks; i++) advance += charsPerTick(revealed + advance)
  return advance
}
// If no response arrives within this window, clear the waiting state
// and surface a timeout message. Prevents the UI from hanging forever
// when the backend LLM call hangs or the WS frame is silently dropped.
const REPLY_TIMEOUT_MS = 90_000
// 断线自动重连:指数退避 + 抖动,无上限(自托管部署,服务恢复后自动接上)。
// onopen 成功即重置计数;后端断开即取消在途生成,重连后靠 loadHistory 对齐
// 已落库状态,不存在续流。
const RECONNECT_BASE_MS = 1_000
const RECONNECT_MAX_MS = 30_000
// 应用层心跳:每周期发 {ping}(后端回 {pong}),连续 DEAD_MS 未收到任何帧判定
// 死链,主动 close 走 onclose 统一重连。uvicorn 的协议级 ping 只保证
// server→client 方向的活性,这里补上 client→server 方向的检测。
const HEARTBEAT_INTERVAL_MS = 25_000
const HEARTBEAT_DEAD_MS = 70_000

/** 流式进行中排队的待发消息(单条/会话)。held:上次回复异常结束(出错/超时),暂停自动发送。
 *  attachments:随文字一起排队的附件引用(协议 §4.1),自动发送/「立即执行」时原样带出。 */
interface PendingEntry {
  text: string
  attachments?: SendAttachmentInput[]
  held?: boolean
}

/** WS 上行聊天帧(协议 §4.1):message 与 attachments 至少一项非空,后端校验。 */
interface ChatSendPayload {
  message: string
  conversation_id?: string
  attachments?: { id: string; alt?: string }[]
}

/** 发送按钮启用条件(协议 §4.1):有文字或带附件即可发送。纯函数,InputBox 等组件共用。 */
export function canSendMessage(text: string, attachmentCount: number): boolean {
  return text.trim() !== '' || attachmentCount > 0
}

/** 历史回放(协议 §4.2):后端 attachments 为 ``[{id, mime, width?, height?, alt?}]`` 数组。
 *  容错解析——非数组整体忽略,元素缺 id 的丢弃;空结果视为无附件(老消息该字段为 null)。 */
function parseHistoryAttachments(raw: unknown): AttachmentRef[] | undefined {
  if (!Array.isArray(raw)) return undefined
  const list: AttachmentRef[] = []
  for (const item of raw) {
    if (
      typeof item === 'object' && item !== null &&
      typeof (item as { id?: unknown }).id === 'string'
    ) {
      list.push(item as AttachmentRef)
    }
  }
  return list.length > 0 ? list : undefined
}

export function useWebSocket(url: string, activeConversationId?: string) {
  const [messages, setMessages] = useState<Message[]>([])
  const [isConnected, setIsConnected] = useState(false)
  const [isStreaming, setIsStreaming] = useState(false)
  const [streamingMode, setStreamingMode] = useState(true)
  const [lastConversationId, setLastConversationId] = useState<string | null>(null)
  const [newConversationId, setNewConversationId] = useState<string | null>(null)
  const wsRef = useRef<WebSocket | null>(null)
  const knownConversationsRef = useRef<Set<string>>(new Set())
  const activeConversationRef = useRef<string | undefined>(activeConversationId)
  const lastConversationIdRef = useRef<string | null>(null)
  // Conversation the in-flight request belongs to. `@pending` means a request
  // was sent before the backend assigned a conversation id; `null` = no request
  // in flight. The backend serializes replies per connection, so at most one
  // session exists at a time, but it must not block other conversations' UI.
  const sessionConvRef = useRef<string | null>(null)
  const [streamingConvId, setStreamingConvId] = useState<string | null>(null)
  const [waitingConvIds, setWaitingConvIds] = useState<string[]>([])
  // 待发消息按会话隔离;ref 镜像供 onmessage 闭包同步读取。
  const [pendingByConv, setPendingByConv] = useState<Record<string, PendingEntry>>({})
  const pendingRef = useRef<Record<string, PendingEntry>>({})
  const bufferRef = useRef('')
  const reasoningBufferRef = useRef('')
  const displayedRef = useRef(0)
  const msgIdRef = useRef(0)
  const twMsgIdRef = useRef<string | null>(null)
  const twTimerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const streamDoneRef = useRef(false)
  const replyTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  // Conversation the current stream buffer belongs to. Used to decide whether
  // clearing a conversation's context should also drop the preserved buffer.
  const streamConvRef = useRef<string | null>(null)
  // 当轮 in-flight 工具卡的权威状态(设计 §5.2):与 bufferRef 同生命周期。
  // 视图切走再切回时消息可能被重建,工具卡据此回填;流终结(finalize)时清空。
  const toolCallsRef = useRef<ToolCall[] | null>(null)
  // 穿插锚点(设计 §5.3 修订):tool_start 到达时已接收的内容字符数,渲染端
  // 按它把芯片切进文本流。与 toolCallsRef 同生命周期(终结/重置/清理同步)。
  const toolAnchorsRef = useRef<ToolAnchor[] | null>(null)
  // Snapshot of a reply that just finished, so a history fetch that races the
  // DB write can still reconcile the response when the user returns to view.
  const completedContentRef = useRef<{ convId: string; content: string; reasoning: string; toolCalls?: ToolCall[]; toolAnchors?: ToolAnchor[] } | null>(null)
  // Monotonic sequence guarding loadHistory against out-of-order responses.
  const historyFetchRef = useRef(0)
  // Whether a stream is active but has no *new* text to show yet (either the
  // first chunk has not arrived, or the typewriter already revealed everything
  // buffered so far and the model has not finished). Drives the "generating…"
  // indicator in the message list. State mirror guarded by `awaitingMoreRef`.
  const [awaitingMoreContent, setAwaitingMoreContent] = useState(false)
  const awaitingMoreRef = useRef(false)
  // 断线重连:retryEpoch 变化驱动 WS effect 重跑(新建连接);attempt 计数
  // 跨 epoch 保留用于退避,连接成功后清零。everConnected 区分首连与重连
  // (只有重连才提示"重连中"并自动刷新历史)。manualClose 标记 effect
  // cleanup 的主动关闭,避免卸载/换 url 时误调度重连。
  const [retryEpoch, setRetryEpoch] = useState(0)
  const retryAttemptRef = useRef(0)
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const heartbeatRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const everConnectedRef = useRef(false)
  const lastFrameAtRef = useRef(0)
  const manualCloseRef = useRef(false)
  const [isReconnecting, setIsReconnecting] = useState(false)
  // WS effect 声明在 loadHistory 之前,依赖数组不能直接引用它(TDZ);
  // 经 ref 间接调用,重连成功后刷新当前会话历史。
  const loadHistoryRef = useRef<((conversationId: string) => Promise<void>) | null>(null)
  // 广播事件监听器集合:通过 subscribe() 注册,收到 git_branch 等事件时派发。
  const listenersRef = useRef<Set<WsListener>>(new Set())
  const setAwaitingMore = useCallback((value: boolean) => {
    if (awaitingMoreRef.current !== value) {
      awaitingMoreRef.current = value
      setAwaitingMoreContent(value)
    }
  }, [])

  // Keep the active conversation ref in sync with the prop
  useEffect(() => {
    activeConversationRef.current = activeConversationId
  }, [activeConversationId])

  useEffect(() => {
    lastConversationIdRef.current = lastConversationId
  }, [lastConversationId])

  const clearWaitingFor = useCallback((convId: string | null) => {
    if (!convId) return
    setWaitingConvIds(prev => (prev.includes(convId) ? prev.filter(id => id !== convId) : prev))
  }, [])

  // 写入/清除一个会话的待发消息(entry=null 清除)。同步维护 ref 镜像。
  const setPendingFor = useCallback((convId: string, entry: PendingEntry | null) => {
    if (entry) {
      pendingRef.current[convId] = entry
      setPendingByConv(prev => ({ ...prev, [convId]: entry }))
    } else {
      delete pendingRef.current[convId]
      setPendingByConv(prev => {
        if (!(convId in prev)) return prev
        const next = { ...prev }
        delete next[convId]
        return next
      })
    }
  }, [])

  // 回复异常结束(出错/超时):该会话的待发消息不自动发送,挂起等用户处理。
  const markPendingHeld = useCallback((convId: string | null | undefined) => {
    if (!convId) return
    const entry = pendingRef.current[convId]
    if (!entry || entry.held) return
    setPendingFor(convId, { ...entry, held: true })
  }, [setPendingFor])

  const clearReplyTimer = useCallback(() => {
    if (replyTimerRef.current) {
      clearTimeout(replyTimerRef.current)
      replyTimerRef.current = null
    }
  }, [])

  const stopTypewriter = useCallback((finalId?: string) => {
    if (twTimerRef.current) clearInterval(twTimerRef.current)
    twTimerRef.current = null
    const msgId = twMsgIdRef.current
    twMsgIdRef.current = null
    streamDoneRef.current = false
    if (awaitingMoreRef.current) setAwaitingMore(false)
    if (msgId) {
      const content = bufferRef.current
      if (finalId) bufferRef.current = ''
      displayedRef.current = 0
      setMessages(prev => {
        const idx = prev.findIndex(m => m.id === msgId)
        if (idx === -1) return prev
        const updated = [...prev]
        updated[idx] = { ...updated[idx], id: finalId ?? msgId, content }
        return updated
      })
    }
    setIsStreaming(false)
    setStreamingConvId(null)
    // 带终态 id 的终结代表一轮回复结束:当轮工具卡状态已落到消息上,ref 作废。
    if (finalId) {
      toolCallsRef.current = null
      toolAnchorsRef.current = null
    }
  }, [setAwaitingMore])

  const startReplyTimer = useCallback(() => {
    clearReplyTimer()
    replyTimerRef.current = setTimeout(() => {
      replyTimerRef.current = null
      const timedOutConv = sessionConvRef.current
      stopTypewriter()
      sessionConvRef.current = null
      setStreamingConvId(null)
      setWaitingConvIds([])
      if (timedOutConv && timedOutConv !== '@pending') markPendingHeld(timedOutConv)
      setMessages(prev => [
        ...prev,
        {
          id: String(msgIdRef.current++),
          role: 'system',
          content: 'Request timed out. The model may be unresponsive — please try again.',
          timestamp: new Date().toISOString(),
        },
      ])
    }, REPLY_TIMEOUT_MS)
  }, [clearReplyTimer, stopTypewriter, markPendingHeld])

  const sendMessage = useCallback((message: string, conversationId?: string, attachments?: SendAttachmentInput[]) => {
    const targetConv = conversationId ?? lastConversationIdRef.current ?? '@pending'
    const inFlight = sessionConvRef.current !== null
    // Only reset stream buffers when no other conversation's reply is in
    // flight — the backend serializes replies, so this send simply queues.
    if (!inFlight) {
      stopTypewriter()
      bufferRef.current = ''
      reasoningBufferRef.current = ''
      displayedRef.current = 0
      completedContentRef.current = null
      toolCallsRef.current = null
      toolAnchorsRef.current = null
      streamConvRef.current = targetConv
      sessionConvRef.current = targetConv
    }

    if (wsRef.current?.readyState === WebSocket.OPEN) {
      setMessages(prev => [
        ...prev,
        {
          id: String(msgIdRef.current++),
          role: 'user',
          content: message,
          timestamp: new Date().toISOString(),
          // 乐观插入原样携带附件引用(含上传响应带来的 mime/width/height):
          // 本地缩略图渲染即可用,无需等历史回放补全。上行帧构造时仍剥离为
          // {id, alt}(§4.1)。
          attachments,
        },
      ])
      setWaitingConvIds(prev => (prev.includes(targetConv) ? prev : [...prev, targetConv]))
      startReplyTimer()
      const payload: ChatSendPayload = { message }
      if (conversationId) {
        payload.conversation_id = conversationId
      }
      // 协议 §4.1:附件非空才携带,且剥离为 {id, alt}(mime 等元数据只用于
      // 乐观渲染,上行帧形状不变);空数组不发,兼容纯文本旧分支
      if (attachments && attachments.length > 0) {
        payload.attachments = attachments.map(({ id, alt }) => (alt === undefined ? { id } : { id, alt }))
      }
      try {
        wsRef.current.send(JSON.stringify(payload))
      } catch {
        clearReplyTimer()
        setWaitingConvIds(prev => prev.filter(id => id !== targetConv))
        if (sessionConvRef.current === targetConv) {
          sessionConvRef.current = null
        }
        setMessages(prev => [
          ...prev,
          {
            id: String(msgIdRef.current++),
            role: 'system',
            content: 'Failed to send message. Please try again.',
            timestamp: new Date().toISOString(),
          },
        ])
      }
    }
  }, [stopTypewriter, startReplyTimer, clearReplyTimer])

  // 消费并发送一个会话的待发消息(原子取出,保证 done/stopped 先后到达只发一次)。
  // 连接不可用时放回,保留给用户手动处理。
  const firePendingFor = useCallback((convId: string | null | undefined) => {
    if (!convId || convId === '@pending') return
    const entry = pendingRef.current[convId]
    if (!entry) return
    setPendingFor(convId, null)
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      sendMessage(entry.text, convId, entry.attachments)
    } else {
      setPendingFor(convId, entry)
    }
  }, [sendMessage, setPendingFor])

  const startTypewriter = useCallback(() => {
    if (twTimerRef.current) clearInterval(twTimerRef.current)
    // 上次 tick 的墙钟时刻:推进量按真实经过时间折算(见 advanceFor),
    // 后台标签页被节流后单次 tick 按比例补齐;重启时随闭包重新初始化。
    let lastTickAt = Date.now()
    twTimerRef.current = setInterval(() => {
      const now = Date.now()
      const elapsed = now - lastTickAt
      lastTickAt = now
      const total = bufferRef.current.length
      if (displayedRef.current >= total) {
        if (streamDoneRef.current) {
          // 回复已完成且打字机追平 → 终结消息,该会话的流就此结束,
          // 触发该会话待发消息的自动发送(streamConvRef 仍指向刚结束的会话)。
          stopTypewriter(String(msgIdRef.current++))
          firePendingFor(streamConvRef.current)
        } else {
          // Everything buffered so far is on screen, but the reply has not
          // finished — flag "waiting for more content" so the UI can show a
          // generating indicator instead of dead air.
          setAwaitingMore(true)
        }
        return
      }
      // Reveal characters
      displayedRef.current = Math.min(displayedRef.current + advanceFor(displayedRef.current, elapsed), total)
      setAwaitingMore(false)
      const displayed = bufferRef.current.slice(0, displayedRef.current)
      setMessages(prev => {
        const idx = prev.findIndex(m => m.id === twMsgIdRef.current)
        if (idx === -1) {
          // The view switched away and back mid-stream — recreate the
          // streaming message if this conversation is on screen again.
          const owner = sessionConvRef.current
          if (!owner || owner !== activeConversationRef.current) return prev
          return [
            ...prev,
            {
              id: twMsgIdRef.current!,
              role: 'assistant',
              content: displayed,
              thinking: reasoningBufferRef.current || undefined,
              // 视图切走期间收到过工具事件时,消息重建需回填已累积的工具卡
              toolCalls: toolCallsRef.current ?? undefined,
              toolAnchors: toolAnchorsRef.current ?? undefined,
              timestamp: new Date().toISOString(),
            },
          ]
        }
        const updated = [...prev]
        updated[idx] = { ...updated[idx], content: displayed }
        return updated
      })
    }, TICK_INTERVAL)
  }, [stopTypewriter, setAwaitingMore, firePendingFor])

  const stopGeneration = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      const payload: Record<string, string | boolean> = { stop: true }
      if (activeConversationRef.current) {
        payload.conversation_id = activeConversationRef.current
      }
      wsRef.current.send(JSON.stringify(payload))
    }
  }, [])

  // 排队待发消息(流式进行中提交)。该会话已无进行中的回复时直接发送,
  // 避免悬浮条在流结束后死等;否则进入单条队列(覆盖旧的待发内容)。
  const queuePendingMessage = useCallback((message: string, conversationId?: string, attachments?: SendAttachmentInput[]) => {
    const conv = conversationId ?? lastConversationIdRef.current
    if (!conv || sessionConvRef.current !== conv) {
      sendMessage(message, conversationId, attachments)
      return
    }
    setPendingFor(conv, { text: message, attachments })
  }, [sendMessage, setPendingFor])

  // 「立即执行」:回复进行中则停止当前回复(stopped 帧到达后由 firePendingFor
  // 统一发送);否则直接消费并发送。
  const sendPendingNow = useCallback((conversationId?: string) => {
    const conv = conversationId ?? lastConversationIdRef.current
    if (!conv) return
    const entry = pendingRef.current[conv]
    if (!entry) return
    if (sessionConvRef.current === conv) {
      stopGeneration()
      return
    }
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      setPendingFor(conv, null)
      sendMessage(entry.text, conversationId, entry.attachments)
    }
  }, [stopGeneration, sendMessage, setPendingFor])

  const cancelPendingMessage = useCallback((conversationId?: string) => {
    const conv = conversationId ?? lastConversationIdRef.current
    if (!conv) return
    setPendingFor(conv, null)
  }, [setPendingFor])

  useEffect(() => {
    // 新连接开始(含重连 epoch 重跑):清除上一轮 cleanup 留下的主动关闭标记。
    manualCloseRef.current = false
    const ws = new WebSocket(url)
    wsRef.current = ws

    const startHeartbeat = () => {
      if (heartbeatRef.current) clearInterval(heartbeatRef.current)
      heartbeatRef.current = setInterval(() => {
        if (ws.readyState !== WebSocket.OPEN) return
        if (Date.now() - lastFrameAtRef.current > HEARTBEAT_DEAD_MS) {
          // 判定死链:主动断开,统一走 onclose 的重连调度。
          ws.close()
          return
        }
        try {
          ws.send(JSON.stringify({ ping: true }))
        } catch {
          // 发送失败说明连接已坏,close/onclose 会接手重连。
        }
      }, HEARTBEAT_INTERVAL_MS)
    }
    const stopHeartbeat = () => {
      if (heartbeatRef.current) {
        clearInterval(heartbeatRef.current)
        heartbeatRef.current = null
      }
    }

    ws.onopen = () => {
      setIsConnected(true)
      lastFrameAtRef.current = Date.now()
      if (everConnectedRef.current) {
        // 重连成功:复位退避与提示,并刷新当前会话历史——断线期间后端可能
        // 产生了变化(断线在途生成已被取消、其他渠道可能有新消息)。
        retryAttemptRef.current = 0
        setIsReconnecting(false)
        const conv = activeConversationRef.current
        if (conv) void loadHistoryRef.current?.(conv)
      } else {
        everConnectedRef.current = true
      }
      startHeartbeat()
    }

    // 收尾兜底(设计 §6):把当轮 in-flight 消息上残留的 running 工具卡标为
    // interrupted —— 覆盖 done/stopped/error 时后端未再补发 tool_end 的场景。
    const markInFlightInterrupted = () => {
      if (toolCallsRef.current) {
        toolCallsRef.current = markInterrupted(toolCallsRef.current)
      }
      const msgId = twMsgIdRef.current
      if (!msgId) return
      setMessages(prev => {
        const idx = prev.findIndex(m => m.id === msgId)
        if (idx === -1) return prev
        const tc = prev[idx].toolCalls
        if (!tc || !tc.some(t => t.status === 'running')) return prev
        const updated = [...prev]
        updated[idx] = { ...updated[idx], toolCalls: markInterrupted(tc) }
        return updated
      })
    }

    ws.onmessage = (event: MessageEvent) => {
      // 任何帧(含 pong/error)都作为链路活性证据,供心跳判死使用。
      lastFrameAtRef.current = Date.now()
      let data: WsIncoming
      try {
        data = JSON.parse(event.data)
      } catch {
        return
      }
      // 心跳 pong 只证明链路活着,不清回复超时——"连接存活但后端 LLM 挂起"
      // 的场景下,90s 回复超时必须仍能触发。
      if (data.pong) return

      // Any message from the backend means the connection is alive; clear
      // the reply timeout that was started when sendMessage fired.
      clearReplyTimer()

      // 后端广播事件(如 git_branch)派发给订阅者,放在 error 分支之前,
      // 保证消息只含 { git_branch } 时也能正常通知;单个监听者异常不影响主流程。
      if (data.git_branch) {
        for (const fn of listenersRef.current) {
          try { fn(data) } catch { /* 监听者异常不影响主流程 */ }
        }
      }

      // 任务事件帧:与 git_branch 并列派发,notify 语义与异常隔离一致。
      // 除 ws.subscribe() 订阅者外,还通知模块级任务事件监听者(任务页)。
      if (data.task_event) {
        for (const fn of listenersRef.current) {
          try { fn(data) } catch { /* 监听者异常不影响主流程 */ }
        }
        for (const fn of taskEventListeners) {
          try { fn(data.task_event) } catch { /* 监听者异常不影响主流程 */ }
        }
      }

      // Subagent 事件帧:与 task_event 同等派发,通知模块级监听者(ChatWindow)。
      // 由 ChatWindow 维护"按 assistant 消息 id 分组"的事件桶并渲染内联卡片。
      if (data.subagent_event) {
        for (const fn of listenersRef.current) {
          try { fn(data) } catch { /* 监听者异常不影响主流程 */ }
        }
        for (const fn of subagentEventListeners) {
          try { fn(data.subagent_event, data.conversation_id) } catch { /* 监听者异常不影响主流程 */ }
        }
      }

      if (data.error) {
        const conv = data.conversation_id ?? null
        if (conv) {
          setLastConversationId(conv)
          if (!knownConversationsRef.current.has(conv)) {
            knownConversationsRef.current.add(conv)
            setNewConversationId(conv)
          }
        }
        if (sessionConvRef.current === '@pending' && conv) {
          sessionConvRef.current = conv
          setWaitingConvIds(prev => prev.map(id => (id === '@pending' ? conv : id)))
        }
        if (conv) clearWaitingFor(conv)
        if (sessionConvRef.current === conv || sessionConvRef.current === '@pending') {
          // 异常收尾:残留 running 卡标为 interrupted,并作废当轮工具卡 ref。
          markInFlightInterrupted()
          stopTypewriter()
          sessionConvRef.current = null
          setStreamingConvId(null)
          toolCallsRef.current = null
          toolAnchorsRef.current = null
        }
        // 异常结束:待发消息不自动发送,挂起等用户处理
        if (conv) markPendingHeld(conv)
        // Only surface the error in the conversation it belongs to
        if (!conv || conv === activeConversationRef.current) {
          setMessages(prev => [
            ...prev,
            {
              id: String(msgIdRef.current++),
              role: 'system',
              content: `Error: ${data.error}`,
              timestamp: new Date().toISOString(),
            },
          ])
        }
        return
      }

      if (data.streaming_mode !== undefined) {
        setStreamingMode(data.streaming_mode)
      }

      // Backend reports the default conversation created on connect
      if (data.connected && data.conversation_id) {
        knownConversationsRef.current.add(data.conversation_id)
        setLastConversationId(data.conversation_id)
        setNewConversationId(data.conversation_id)
        return
      }

      // Conversation switch acknowledged
      if (data.conversation_switched) {
        return
      }

      // Backend created a conversation lazily (first message, no prior conversation)
      if (data.conversation_created) {
        const created = data.conversation_created
        knownConversationsRef.current.add(created)
        setLastConversationId(created)
        setNewConversationId(created)
        if (sessionConvRef.current === '@pending') {
          sessionConvRef.current = created
          // Chunks for this conversation may arrive before the prop
          // round-trip selects it; treat it as active immediately.
          activeConversationRef.current = created
          setWaitingConvIds(prev => prev.map(id => (id === '@pending' ? created : id)))
        }
        return
      }

      // Cross-channel message (e.g. WeChat) — broadcast to all clients
      if (data.channel_message) {
        const cm = data.channel_message
        if (cm.conversation_id) {
          setLastConversationId(cm.conversation_id)
          if (!knownConversationsRef.current.has(cm.conversation_id)) {
            knownConversationsRef.current.add(cm.conversation_id)
            setNewConversationId(cm.conversation_id)
          }
        }
        // Only display messages if the user is currently viewing this conversation
        if (cm.conversation_id && cm.conversation_id === activeConversationRef.current) {
          const newMsgs: Message[] = []
          // For external messages (source !== 'frontend'), show the user message.
          // 纯图片轮 user_message 为空,但有 attachments 时仍要显示用户气泡。
          const inboundAttachments = parseHistoryAttachments(cm.attachments)
          if (cm.source !== 'frontend' && (cm.user_message || inboundAttachments)) {
            newMsgs.push({
              id: String(msgIdRef.current++),
              role: 'user',
              content: cm.user_message ?? '',
              timestamp: new Date().toISOString(),
              // 与 loadHistory 同一容错映射(设计 §2):入站微信图片并入
              // 乐观用户消息,本地缩略图直接可渲染。
              attachments: inboundAttachments,
            })
          }
          // Always show the AI response
          if (cm.response) {
            newMsgs.push({
              id: String(msgIdRef.current++),
              role: 'assistant',
              content: cm.response,
              timestamp: new Date().toISOString(),
            })
          }
          if (newMsgs.length > 0) {
            setMessages(prev => [...prev, ...newMsgs])
          }
        }
        return
      }

      // 实时工具调用事件(设计 §5.2):复用 chunk 的按会话分桶/落点机制,
      // 避免跨会话串话。工具调用可以先于任何文本出现 —— 当前会话尚无流式
      // assistant 占位消息时,按 chunk 首次到达的方式创建;随后按 call_id
      // 对该消息 upsert 工具卡(一个 turn 多轮 LLM↔工具循环共用同一条)。
      if (data.tool_event) {
        const conv = data.conversation_id ?? null
        if (conv) {
          clearWaitingFor(conv)
          setLastConversationId(conv)
          if (!knownConversationsRef.current.has(conv)) {
            knownConversationsRef.current.add(conv)
            setNewConversationId(conv)
          }
        }

        // 与 chunk 相同的会话交接:上一会话的打字机仍在排水时立即终结。
        const session = sessionConvRef.current
        if (twMsgIdRef.current && conv && session !== conv) {
          stopTypewriter(String(msgIdRef.current++))
          // 上一会话的流就此结束,同样要触发其待发消息的自动发送。
          firePendingFor(streamConvRef.current)
        }
        if (conv && session !== conv) {
          sessionConvRef.current = conv
          completedContentRef.current = null
          if (session === '@pending') {
            activeConversationRef.current = conv
            setWaitingConvIds(prev => prev.map(id => (id === '@pending' ? conv : id)))
          }
        }
        if (conv) streamConvRef.current = conv

        setIsStreaming(true)
        if (conv) setStreamingConvId(conv)
        streamDoneRef.current = false

        // 穿插锚点(设计 §5.3 修订):start 到达时记录当前已接收内容长度,
        // 供渲染端把芯片按发生顺序切进文本流;重复 start 与 upsertToolCall
        // 同样忽略。end 不产生锚点。
        if (data.tool_event.phase === 'start') {
          const anchors = (toolAnchorsRef.current ??= [])
          if (!anchors.some(a => a.callId === data.tool_event!.call_id)) {
            anchors.push({ callId: data.tool_event.call_id, offset: bufferRef.current.length })
          }
        }
        toolCallsRef.current = upsertToolCall(toolCallsRef.current ?? [], data.tool_event)
        const isActiveView = !conv || conv === activeConversationRef.current
        const streamingId = twMsgIdRef.current
        if (!streamingId) {
          const msgId = `stream-${msgIdRef.current}`
          twMsgIdRef.current = msgId
          displayedRef.current = 0
          if (isActiveView) {
            setMessages(prev => [
              ...prev,
              {
                id: msgId,
                role: 'assistant',
                content: '',
                toolCalls: toolCallsRef.current ?? [],
                toolAnchors: toolAnchorsRef.current ?? undefined,
                timestamp: new Date().toISOString(),
              },
            ])
          }
          startTypewriter()
        } else {
          setMessages(prev => {
            const idx = prev.findIndex(m => m.id === streamingId)
            if (idx === -1) return prev
            const updated = [...prev]
            updated[idx] = {
              ...updated[idx],
              toolCalls: toolCallsRef.current ?? [],
              toolAnchors: toolAnchorsRef.current ?? undefined,
            }
            return updated
          })
        }
        return
      }

      // Streaming chunk — buffer + typewriter reveal
      if (data.chunk !== undefined) {
        const conv = data.conversation_id ?? null
        if (conv) {
          clearWaitingFor(conv)
          setLastConversationId(conv)
          if (!knownConversationsRef.current.has(conv)) {
            knownConversationsRef.current.add(conv)
            setNewConversationId(conv)
          }
        }

        const session = sessionConvRef.current
        // Session handoff: the previous conversation's typewriter may still
        // be draining when the next reply starts — finalize it immediately
        // so this conversation's stream starts with clean buffers.
        if (twMsgIdRef.current && conv && session !== conv) {
          stopTypewriter(String(msgIdRef.current++))
          // 上一会话的流就此结束(done 可能刚被收下、打字机还没来得及追平),
          // 同样要触发其待发消息的自动发送。
          firePendingFor(streamConvRef.current)
        }
        if (conv && session !== conv) {
          sessionConvRef.current = conv
          completedContentRef.current = null
          if (session === '@pending') {
            activeConversationRef.current = conv
            setWaitingConvIds(prev => prev.map(id => (id === '@pending' ? conv : id)))
          }
        }

        if (conv) streamConvRef.current = conv

        setIsStreaming(true)
        if (conv) setStreamingConvId(conv)
        streamDoneRef.current = false
        setAwaitingMore(false)
        const isReasoning = data.chunk_type === 'reasoning'
        if (isReasoning) {
          reasoningBufferRef.current += data.chunk
        } else {
          bufferRef.current += data.chunk
        }

        // Render into the message list only while this conversation is on
        // screen; otherwise the persisted history is shown when it reopens.
        const isActiveView = !conv || conv === activeConversationRef.current

        if (!twMsgIdRef.current) {
          const msgId = `stream-${msgIdRef.current}`
          twMsgIdRef.current = msgId
          displayedRef.current = 0
          if (isActiveView) {
            setMessages(prev => [
              ...prev,
              {
                id: msgId,
                role: 'assistant',
                content: '',
                thinking: isReasoning ? reasoningBufferRef.current : undefined,
                timestamp: new Date().toISOString(),
              },
            ])
          }

          startTypewriter()
        } else if (isReasoning) {
          const thinking = reasoningBufferRef.current
          setMessages(prev => {
            const idx = prev.findIndex(m => m.id === twMsgIdRef.current)
            if (idx === -1) return prev
            const updated = [...prev]
            updated[idx] = { ...updated[idx], thinking }
            return updated
          })
        }
        return
      }

      // Stream stopped (user pressed stop) — the backend cancelled the reply.
      // Finalize whatever was typed as a completed assistant message (with the
      // streaming id replaced by a real one), then clear all stream state. An
      // empty buffer simply ends cleanly.
      if (data.stopped) {
        const conv = data.conversation_id ?? null
        if (conv) {
          setLastConversationId(conv)
          if (!knownConversationsRef.current.has(conv)) {
            knownConversationsRef.current.add(conv)
            setNewConversationId(conv)
          }
          clearWaitingFor(conv)
        }
        sessionConvRef.current = null
        // 后端取消不补发 tool_end:先把残留 running 卡标为 interrupted,
        // 再终结消息(终结的 spread 会保留工具卡状态)。
        markInFlightInterrupted()
        // Stop the typewriter and finalize the partial content immediately.
        stopTypewriter(String(msgIdRef.current++))
        bufferRef.current = ''
        reasoningBufferRef.current = ''
        displayedRef.current = 0
        // 流就此结束(用户停止或「立即执行」)→ 触发待发消息自动发送
        firePendingFor(conv)
        return
      }

      // Stream done
      if (data.done) {
        const conv = data.conversation_id ?? null
        if (conv) {
          setLastConversationId(conv)
          if (!knownConversationsRef.current.has(conv)) {
            knownConversationsRef.current.add(conv)
            setNewConversationId(conv)
          }
          clearWaitingFor(conv)
          // 兜底:done 前个别工具未收到 tool_end 时,把 running 卡标为 interrupted
          // (全部正常结束时是 no-op,不打扰已完成卡片)。
          markInFlightInterrupted()
          // Snapshot the finished reply (含工具卡与穿插锚点,切回视图时
          // reconcile 需要) so a history fetch racing the DB write can
          // still reconcile the response on the next view.
          if (bufferRef.current) {
            completedContentRef.current = {
              convId: conv,
              content: bufferRef.current,
              reasoning: reasoningBufferRef.current,
              toolCalls: toolCallsRef.current ?? undefined,
              toolAnchors: toolAnchorsRef.current ?? undefined,
            }
          }
          streamConvRef.current = conv
        }
        sessionConvRef.current = null
        if (twTimerRef.current) {
          // Typewriter running — mark done, it will finalize when caught up.
          // Keep streamingConvId so the streaming conversation (and only it)
          // stays locked until the typewriter drains.
          streamDoneRef.current = true
          return
        }
        // No typewriter — finalize immediately
        setIsStreaming(false)
        setStreamingConvId(null)
        bufferRef.current = ''
        displayedRef.current = 0
        setMessages(prev => {
          const last = prev[prev.length - 1]
          if (last && last.role === 'assistant' && last.id.startsWith('stream-')) {
            return [...prev.slice(0, -1), { ...last, id: String(msgIdRef.current++) }]
          }
          return prev
        })
        // 流正常结束 → 触发待发消息自动发送
        firePendingFor(conv)
        return
      }

      // Non-streaming full response — display immediately
      if (data.response !== undefined) {
        const conv = data.conversation_id ?? null
        if (conv) {
          setLastConversationId(conv)
          if (!knownConversationsRef.current.has(conv)) {
            knownConversationsRef.current.add(conv)
            setNewConversationId(conv)
          }
          clearWaitingFor(conv)
          streamConvRef.current = conv
          // Snapshot the reply (含工具卡与穿插锚点) so a history fetch racing
          // the DB write can reconcile it even when it arrived while this
          // conversation was not on screen (e.g. the user was on another page).
          if (data.response) {
            completedContentRef.current = {
              convId: conv,
              content: data.response,
              reasoning: '',
              toolCalls: toolCallsRef.current ? markInterrupted(toolCallsRef.current) : undefined,
              toolAnchors: toolAnchorsRef.current ?? undefined,
            }
          }
        }
        sessionConvRef.current = null
        setStreamingConvId(null)
        // 实时工具卡可能已为本轮创建了占位消息(非流式下工具事件先于整段
        // 文本到达,设计 §4.4):把回复并入占位消息并终结(保留工具卡),
        // 避免留下一条空气泡;无占位时走原有追加路径。
        const streamingId = twMsgIdRef.current
        if (streamingId) {
          markInFlightInterrupted()
          const liveCards = toolCallsRef.current
          const liveAnchors = toolAnchorsRef.current
          stopTypewriter()
          toolCallsRef.current = null
          toolAnchorsRef.current = null
          setIsStreaming(false)
          if (!conv || conv === activeConversationRef.current) {
            setMessages(prev => {
              const idx = prev.findIndex(m => m.id === streamingId)
              const cards = liveCards && liveCards.length > 0
                ? { toolCalls: liveCards, toolAnchors: liveAnchors ?? undefined }
                : undefined
              if (idx === -1) {
                // 占位消息不在列表(视图曾切走)→ 追加完整回复并带工具卡
                return [
                  ...prev,
                  {
                    id: String(msgIdRef.current++),
                    role: 'assistant',
                    content: data.response!,
                    timestamp: new Date().toISOString(),
                    ...cards,
                  },
                ]
              }
              const updated = [...prev]
              updated[idx] = { ...updated[idx], id: String(msgIdRef.current++), content: data.response!, ...cards }
              return updated
            })
          }
          // 回复正常结束(非流式整段回复)→ 触发待发消息自动发送
          firePendingFor(conv)
          return
        }
        // Only render in the conversation it belongs to; other views load
        // the persisted history when opened.
        if (!conv || conv === activeConversationRef.current) {
          setMessages(prev => [
            ...prev,
            {
              id: String(msgIdRef.current++),
              role: 'assistant',
              content: data.response!,
              timestamp: new Date().toISOString(),
            },
          ])
        }
        // 回复正常结束(非流式整段回复)→ 触发待发消息自动发送
        firePendingFor(conv)
      }
    }

    ws.onclose = () => {
      stopHeartbeat()
      setIsConnected(false)
      setIsStreaming(false)
      clearReplyTimer()
      sessionConvRef.current = null
      setStreamingConvId(null)
      setWaitingConvIds([])
      setAwaitingMore(false)
      // 旧 socket 的关闭(StrictMode 双挂载 / 换 url / 重连换代)不参与调度,
      // 防止双连接;cleanup 的主动关闭同样不调度。
      if (ws !== wsRef.current || manualCloseRef.current) return
      if (everConnectedRef.current) setIsReconnecting(true)
      // 指数退避 + ±20% 抖动,避免服务重启瞬间所有客户端同时重连。
      const base = Math.min(RECONNECT_MAX_MS, RECONNECT_BASE_MS * 2 ** retryAttemptRef.current)
      const delay = Math.round(base * (0.8 + Math.random() * 0.4))
      retryAttemptRef.current += 1
      reconnectTimerRef.current = setTimeout(() => {
        reconnectTimerRef.current = null
        setRetryEpoch(epoch => epoch + 1)
      }, delay)
    }

    ws.onerror = () => {
      // 仅清状态;浏览器规范保证 error 后必随 close,重连统一在 onclose 调度。
      setIsConnected(false)
      setIsStreaming(false)
      clearReplyTimer()
      sessionConvRef.current = null
      setStreamingConvId(null)
      setWaitingConvIds([])
      setAwaitingMore(false)
    }

    return () => {
      manualCloseRef.current = true
      if (reconnectTimerRef.current) {
        clearTimeout(reconnectTimerRef.current)
        reconnectTimerRef.current = null
      }
      stopHeartbeat()
      if (twTimerRef.current) clearInterval(twTimerRef.current)
      twTimerRef.current = null
      clearReplyTimer()
      ws.close()
    }
  }, [url, retryEpoch])

  const switchConversation = useCallback((conversationId: string) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ switch_conversation: conversationId }))
    }
  }, [])

  const loadHistory = useCallback(async (conversationId: string) => {
    const fetchId = ++historyFetchRef.current
    try {
      const res = await fetch(`/api/v1/conversations/${conversationId}`)
      if (!res.ok) return
      const data = await res.json()
      if (!Array.isArray(data.messages)) return
      // A slower response for a previously-opened conversation must not
      // overwrite the view of the conversation the user is on now.
      if (fetchId !== historyFetchRef.current) return
      const history: Message[] = data.messages.map((m: { id: string; role: string; content: string; reasoning_content?: string | null; created_at: string; attachments?: unknown }) => ({
        id: m.id,
        role: m.role as Message['role'],
        content: m.content,
        thinking: m.reasoning_content ?? undefined,
        timestamp: m.created_at,
        attachments: parseHistoryAttachments(m.attachments),
      }))

      let list: Message[] = history
      // done 已到达但打字机被视图切换掐掉时(clearMessages → stopTypewriter 重置
      // streamDoneRef),tick 追平终结路径的 firePendingFor 不会再触发;在
      // setMessages 之后统一补发(无待发消息时 no-op,已触发过时幂等)。
      let finalizePending = false
      // A reply that is still streaming is not persisted until done, so the
      // DB history only contains the user message. Carry the preserved buffer
      // forward so switching away and back does not truncate the response.
      if (sessionConvRef.current === conversationId) {
        const msgId = `stream-${msgIdRef.current++}`
        twMsgIdRef.current = msgId
        displayedRef.current = bufferRef.current.length
        setIsStreaming(true)
        setStreamingConvId(conversationId)
        list = [
          ...history,
          {
            id: msgId,
            role: 'assistant',
            content: bufferRef.current,
            thinking: reasoningBufferRef.current || undefined,
            // 流中切走再切回:重建的流式消息必须带回已累积的工具卡与穿插锚点
            toolCalls: toolCallsRef.current ?? undefined,
            toolAnchors: toolAnchorsRef.current ?? undefined,
            timestamp: new Date().toISOString(),
          },
        ]
        startTypewriter()
      } else if (completedContentRef.current?.convId === conversationId) {
        // The reply finished but the DB write may have raced this fetch.
        const completed = completedContentRef.current
        completedContentRef.current = null
        if (
          completed.content &&
          !history.some(m => m.role === 'assistant' && m.content === completed.content)
        ) {
          list = [
            ...history,
            {
              id: String(msgIdRef.current++),
              role: 'assistant',
              content: completed.content,
              thinking: completed.reasoning || undefined,
              // reconcile 追加的消息同样带回工具卡与穿插锚点
              ...(completed.toolCalls?.length
                ? { toolCalls: completed.toolCalls, toolAnchors: completed.toolAnchors }
                : {}),
              timestamp: new Date().toISOString(),
            },
          ]
        }
        finalizePending = true
      }
      setMessages(list)
      // 必须在 setMessages 之后:firePendingFor → sendMessage 以 updater 追加
      // 用户消息,先于整体赋值执行会被这次 setMessages(list) 覆盖掉。
      if (finalizePending) firePendingFor(conversationId)
    } catch {
      // ignore
    }
  }, [startTypewriter, firePendingFor])

  // loadHistory 声明在 WS effect 之后,这里把最新实例同步给 ref 供重连路径调用。
  useEffect(() => {
    loadHistoryRef.current = loadHistory
  }, [loadHistory])

  const clearMessages = useCallback((conversationId?: string) => {
    stopTypewriter()
    setMessages([])
    msgIdRef.current = 0
    // Preserve an in-flight reply's buffer across a conversation switch so
    // returning to it mid-stream does not truncate the response. Only an
    // explicit clear of the conversation that owns the buffer drops it.
    if (conversationId && streamConvRef.current === conversationId) {
      bufferRef.current = ''
      reasoningBufferRef.current = ''
      displayedRef.current = 0
      completedContentRef.current = null
      toolCallsRef.current = null
      toolAnchorsRef.current = null
    }
    // 显式清空某会话上下文时,连带清掉该会话的待发消息;
    // 无参调用(切换会话视图)不影响任何待发消息。
    if (conversationId) setPendingFor(conversationId, null)
  }, [stopTypewriter, setPendingFor])

  const clearNewConversation = useCallback(() => {
    setNewConversationId(null)
  }, [])

  // 订阅后端广播事件(git_branch / task_event);返回退订函数,组件卸载时调用。
  const subscribe = useCallback((fn: WsListener) => {
    listenersRef.current.add(fn)
    return () => { listenersRef.current.delete(fn) }
  }, [])

  // Expose streaming/waiting/pending state relative to the active conversation
  // so a busy conversation does not lock the others. A null streamingConvId
  // means the reply did not report a conversation — treat it as the active one.
  const isStreamingActive =
    isStreaming && (streamingConvId === null || streamingConvId === activeConversationId)
  const waitingForReply =
    (activeConversationId && waitingConvIds.includes(activeConversationId)) ||
    (!activeConversationId && waitingConvIds.includes('@pending')) || false
  const activePending = activeConversationId ? pendingByConv[activeConversationId] : undefined

  return {
    messages,
    isConnected,
    isReconnecting,
    isStreaming: isStreamingActive,
    streamingMode,
    waitingForReply,
    awaitingMoreContent,
    lastConversationId,
    newConversationId,
    clearNewConversation,
    // 待发条目存在(含纯图片排队:text 为空 → pendingMessage 为 '' 的假值,
    // 悬浮条必须以 pendingActive 为准渲染,否则纯图片排队零反馈)。
    pendingActive: activePending !== undefined,
    pendingMessage: activePending?.text ?? null,
    pendingAttachments: activePending?.attachments ?? undefined,
    pendingHeld: activePending?.held ?? false,
    queuePendingMessage,
    sendPendingNow,
    cancelPendingMessage,
    sendMessage,
    stopGeneration,
    clearMessages,
    switchConversation,
    loadHistory,
    subscribe,
  }
}

export type ChatSocket = ReturnType<typeof useWebSocket>

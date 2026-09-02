import { useCallback, useEffect, useRef, useState } from 'react'
import type { Message } from '../types/chat'

interface WsIncoming {
  chunk?: string
  chunk_type?: 'reasoning' | string
  response?: string
  done?: boolean
  /** Backend finished cancelling a streaming reply after the user pressed stop. */
  stopped?: boolean
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
  }
  /** 后端切换 git 分支后广播的事件,携带工作区与当前分支名。 */
  git_branch?: { workspace: string; branch: string }
  /** 任务调度器生命周期事件(设计 §8.2),与 REST 事件视图字节同构。 */
  task_event?: TaskEventPayload
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

// 打字机阶梯式提速:首批字符最快(让"开口"明显),中段最快,长文本末段降到 3/tick
// 避免高频闪烁。整体节奏较旧 3/30 提速约 2.5-3 倍。
const TICK_INTERVAL = 18
const charsPerTick = (revealed: number) => (revealed < 80 ? 5 : revealed < 240 ? 6 : 3)
// If no response arrives within this window, clear the waiting state
// and surface a timeout message. Prevents the UI from hanging forever
// when the backend LLM call hangs or the WS frame is silently dropped.
const REPLY_TIMEOUT_MS = 90_000

/** 流式进行中排队的待发消息(单条/会话)。held:上次回复异常结束(出错/超时),暂停自动发送。 */
interface PendingEntry {
  text: string
  held?: boolean
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
  // Snapshot of a reply that just finished, so a history fetch that races the
  // DB write can still reconcile the response when the user returns to view.
  const completedContentRef = useRef<{ convId: string; content: string; reasoning: string } | null>(null)
  // Monotonic sequence guarding loadHistory against out-of-order responses.
  const historyFetchRef = useRef(0)
  // Whether a stream is active but has no *new* text to show yet (either the
  // first chunk has not arrived, or the typewriter already revealed everything
  // buffered so far and the model has not finished). Drives the "generating…"
  // indicator in the message list. State mirror guarded by `awaitingMoreRef`.
  const [awaitingMoreContent, setAwaitingMoreContent] = useState(false)
  const awaitingMoreRef = useRef(false)
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

  const sendMessage = useCallback((message: string, conversationId?: string) => {
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
        },
      ])
      setWaitingConvIds(prev => (prev.includes(targetConv) ? prev : [...prev, targetConv]))
      startReplyTimer()
      const payload: Record<string, string> = { message }
      if (conversationId) {
        payload.conversation_id = conversationId
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
      sendMessage(entry.text, convId)
    } else {
      setPendingFor(convId, entry)
    }
  }, [sendMessage, setPendingFor])

  const startTypewriter = useCallback(() => {
    if (twTimerRef.current) clearInterval(twTimerRef.current)
    twTimerRef.current = setInterval(() => {
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
      displayedRef.current = Math.min(displayedRef.current + charsPerTick(displayedRef.current), total)
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
  const queuePendingMessage = useCallback((message: string, conversationId?: string) => {
    const conv = conversationId ?? lastConversationIdRef.current
    if (!conv || sessionConvRef.current !== conv) {
      sendMessage(message, conversationId)
      return
    }
    setPendingFor(conv, { text: message })
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
      sendMessage(entry.text, conversationId)
    }
  }, [stopGeneration, sendMessage, setPendingFor])

  const cancelPendingMessage = useCallback((conversationId?: string) => {
    const conv = conversationId ?? lastConversationIdRef.current
    if (!conv) return
    setPendingFor(conv, null)
  }, [setPendingFor])

  useEffect(() => {
    const ws = new WebSocket(url)
    wsRef.current = ws

    ws.onopen = () => setIsConnected(true)

    ws.onmessage = (event: MessageEvent) => {
      let data: WsIncoming
      try {
        data = JSON.parse(event.data)
      } catch {
        return
      }

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
          stopTypewriter()
          sessionConvRef.current = null
          setStreamingConvId(null)
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
          // For external messages (source !== 'frontend'), show the user message
          if (cm.source !== 'frontend' && cm.user_message) {
            newMsgs.push({
              id: String(msgIdRef.current++),
              role: 'user',
              content: cm.user_message,
              timestamp: new Date().toISOString(),
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
          // Snapshot the finished reply so a history fetch racing the DB
          // write can still reconcile the response on the next view.
          if (bufferRef.current) {
            completedContentRef.current = {
              convId: conv,
              content: bufferRef.current,
              reasoning: reasoningBufferRef.current,
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
          // Snapshot the reply so a history fetch racing the DB write can
          // reconcile it even when it arrived while this conversation was
          // not on screen (e.g. the user was on another page).
          if (data.response) {
            completedContentRef.current = { convId: conv, content: data.response, reasoning: '' }
          }
        }
        sessionConvRef.current = null
        setStreamingConvId(null)
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
      setIsConnected(false)
      setIsStreaming(false)
      clearReplyTimer()
      sessionConvRef.current = null
      setStreamingConvId(null)
      setWaitingConvIds([])
      setAwaitingMore(false)
    }

    ws.onerror = () => {
      setIsConnected(false)
      setIsStreaming(false)
      clearReplyTimer()
      sessionConvRef.current = null
      setStreamingConvId(null)
      setWaitingConvIds([])
      setAwaitingMore(false)
    }

    return () => {
      if (twTimerRef.current) clearInterval(twTimerRef.current)
      twTimerRef.current = null
      clearReplyTimer()
      ws.close()
    }
  }, [url])

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
      const history: Message[] = data.messages.map((m: { id: string; role: string; content: string; reasoning_content?: string | null; created_at: string }) => ({
        id: m.id,
        role: m.role as Message['role'],
        content: m.content,
        thinking: m.reasoning_content ?? undefined,
        timestamp: m.created_at,
      }))

      let list: Message[] = history
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
              timestamp: new Date().toISOString(),
            },
          ]
        }
      }
      setMessages(list)
    } catch {
      // ignore
    }
  }, [startTypewriter])

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

  return { messages, isConnected, isStreaming: isStreamingActive, streamingMode, waitingForReply, awaitingMoreContent, lastConversationId, newConversationId, clearNewConversation, pendingMessage: activePending?.text ?? null, pendingHeld: activePending?.held ?? false, queuePendingMessage, sendPendingNow, cancelPendingMessage, sendMessage, stopGeneration, clearMessages, switchConversation, loadHistory, subscribe }
}

export type ChatSocket = ReturnType<typeof useWebSocket>

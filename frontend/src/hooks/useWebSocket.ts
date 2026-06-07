import { useCallback, useEffect, useRef, useState } from 'react'
import type { Message } from '../types/chat'

interface WsIncoming {
  chunk?: string
  response?: string
  done?: boolean
  conversation_id?: string
  error?: string
  streaming_mode?: boolean
}

const CHARS_PER_TICK = 3
const TICK_INTERVAL = 30

export function useWebSocket(url: string) {
  const [messages, setMessages] = useState<Message[]>([])
  const [isConnected, setIsConnected] = useState(false)
  const [isStreaming, setIsStreaming] = useState(false)
  const [streamingMode, setStreamingMode] = useState(true)
  const [waitingForReply, setWaitingForReply] = useState(false)
  const [lastConversationId, setLastConversationId] = useState<string | null>(null)
  const wsRef = useRef<WebSocket | null>(null)
  const bufferRef = useRef('')
  const displayedRef = useRef(0)
  const msgIdRef = useRef(0)
  const twMsgIdRef = useRef<string | null>(null)
  const twTimerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const streamDoneRef = useRef(false)

  const stopTypewriter = useCallback((finalId?: string) => {
    if (twTimerRef.current) clearInterval(twTimerRef.current)
    twTimerRef.current = null
    const msgId = twMsgIdRef.current
    twMsgIdRef.current = null
    streamDoneRef.current = false
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
  }, [])

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

      if (data.error) {
        setWaitingForReply(false)
        if (data.conversation_id) setLastConversationId(data.conversation_id)
        setMessages(prev => [
          ...prev,
          {
            id: String(msgIdRef.current++),
            role: 'system',
            content: `Error: ${data.error}`,
            timestamp: new Date().toISOString(),
          },
        ])
        return
      }

      if (data.streaming_mode !== undefined) {
        setStreamingMode(data.streaming_mode)
      }

      // Streaming chunk — buffer + typewriter reveal
      if (data.chunk !== undefined) {
        setWaitingForReply(false)
        if (data.conversation_id) setLastConversationId(data.conversation_id)
        setIsStreaming(true)
        streamDoneRef.current = false
        bufferRef.current += data.chunk

        if (!twMsgIdRef.current) {
          const msgId = `stream-${msgIdRef.current}`
          twMsgIdRef.current = msgId
          displayedRef.current = 0
          setMessages(prev => [
            ...prev,
            {
              id: msgId,
              role: 'assistant',
              content: '',
              timestamp: new Date().toISOString(),
            },
          ])

          // Start typewriter interval
          twTimerRef.current = setInterval(() => {
            const total = bufferRef.current.length
            if (displayedRef.current >= total) {
              if (streamDoneRef.current) {
                stopTypewriter(String(msgIdRef.current++))
              }
              return
            }
            // Reveal characters
            displayedRef.current = Math.min(displayedRef.current + CHARS_PER_TICK, total)
            const displayed = bufferRef.current.slice(0, displayedRef.current)
            setMessages(prev => {
              const idx = prev.findIndex(m => m.id === twMsgIdRef.current)
              if (idx === -1) return prev
              const updated = [...prev]
              updated[idx] = { ...updated[idx], content: displayed }
              return updated
            })
          }, TICK_INTERVAL)
        }
        return
      }

      // Stream done
      if (data.done) {
        if (data.conversation_id) setLastConversationId(data.conversation_id)
        if (twTimerRef.current) {
          // Typewriter running — mark done, it will finalize when caught up
          streamDoneRef.current = true
          return
        }
        // No typewriter — finalize immediately
        setIsStreaming(false)
        bufferRef.current = ''
        displayedRef.current = 0
        setMessages(prev => {
          const last = prev[prev.length - 1]
          if (last && last.role === 'assistant' && last.id.startsWith('stream-')) {
            return [...prev.slice(0, -1), { ...last, id: String(msgIdRef.current++) }]
          }
          return prev
        })
        return
      }

      // Non-streaming full response — display immediately
      if (data.response !== undefined) {
        setWaitingForReply(false)
        if (data.conversation_id) setLastConversationId(data.conversation_id)
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
    }

    ws.onclose = () => {
      setIsConnected(false)
      setIsStreaming(false)
    }

    ws.onerror = () => {
      setIsConnected(false)
      setIsStreaming(false)
    }

    return () => {
      if (twTimerRef.current) clearInterval(twTimerRef.current)
      twTimerRef.current = null
      ws.close()
    }
  }, [url])

  const sendMessage = useCallback((message: string, conversationId?: string) => {
    stopTypewriter()

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
      bufferRef.current = ''
      displayedRef.current = 0
      setWaitingForReply(true)
      const payload: Record<string, string> = { message }
      if (conversationId) {
        payload.conversation_id = conversationId
      }
      wsRef.current.send(JSON.stringify(payload))
    }
  }, [stopTypewriter])

  const clearMessages = useCallback(() => {
    stopTypewriter()
    setMessages([])
    bufferRef.current = ''
    displayedRef.current = 0
    msgIdRef.current = 0
    setWaitingForReply(false)
  }, [stopTypewriter])

  return { messages, isConnected, isStreaming, streamingMode, waitingForReply, lastConversationId, sendMessage, clearMessages }
}

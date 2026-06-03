import { useCallback, useEffect, useRef, useState } from 'react'
import type { Message } from '../types/chat'

interface WsIncoming {
  chunk?: string
  response?: string
  done?: boolean
  conversation_id?: string
  error?: string
}

export function useWebSocket(url: string) {
  const [messages, setMessages] = useState<Message[]>([])
  const [isConnected, setIsConnected] = useState(false)
  const [isStreaming, setIsStreaming] = useState(false)
  const wsRef = useRef<WebSocket | null>(null)
  const bufferRef = useRef('')
  const msgIdRef = useRef(0)

  useEffect(() => {
    const ws = new WebSocket(url)
    wsRef.current = ws

    ws.onopen = () => {
      setIsConnected(true)
    }

    ws.onmessage = (event: MessageEvent) => {
      let data: WsIncoming
      try {
        data = JSON.parse(event.data)
      } catch {
        return
      }

      if (data.error) {
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

      // Streaming chunk
      if (data.chunk !== undefined) {
        setIsStreaming(true)
        bufferRef.current += data.chunk
        const buffered = bufferRef.current
        setMessages(prev => {
          const last = prev[prev.length - 1]
          if (last && last.role === 'assistant' && last.id.startsWith('stream-')) {
            return [...prev.slice(0, -1), { ...last, content: buffered }]
          }
          return [
            ...prev,
            {
              id: `stream-${msgIdRef.current}`,
              role: 'assistant',
              content: buffered,
              timestamp: new Date().toISOString(),
            },
          ]
        })
        return
      }

      // Stream done
      if (data.done) {
        setIsStreaming(false)
        bufferRef.current = ''
        setMessages(prev => {
          const last = prev[prev.length - 1]
          if (last && last.role === 'assistant' && last.id.startsWith('stream-')) {
            return [...prev.slice(0, -1), { ...last, id: String(msgIdRef.current++) }]
          }
          return prev
        })
        return
      }

      // Legacy complete response
      if (data.response !== undefined) {
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
      ws.close()
    }
  }, [url])

  const sendMessage = useCallback((message: string, conversationId?: string) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      // Add user message to local state
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
      const payload: Record<string, string> = { message }
      if (conversationId) {
        payload.conversation_id = conversationId
      }
      wsRef.current.send(JSON.stringify(payload))
    }
  }, [])

  const clearMessages = useCallback(() => {
    setMessages([])
    bufferRef.current = ''
    msgIdRef.current = 0
  }, [])

  return { messages, isConnected, isStreaming, sendMessage, clearMessages }
}

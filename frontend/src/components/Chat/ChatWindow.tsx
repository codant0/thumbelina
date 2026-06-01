import { useWebSocket } from '../../hooks/useWebSocket'
import { MessageList } from './MessageList'
import { InputBox } from './InputBox'
import type { Message } from '../../types/chat'

export function ChatWindow() {
  const { messages: wsMessages, isConnected, sendMessage } = useWebSocket(
    `ws://${window.location.host}/ws/chat`
  )

  const messages: Message[] = wsMessages.map((content, i) => ({
    id: String(i),
    role: (i % 2 === 0 ? 'user' : 'assistant') as Message['role'],
    content,
    timestamp: new Date().toISOString(),
  }))

  return (
    <div data-testid="chat-window">
      <div>{isConnected ? '已连接' : '未连接'}</div>
      <MessageList messages={messages} />
      <InputBox onSend={sendMessage} disabled={!isConnected} />
    </div>
  )
}

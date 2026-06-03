import { useWebSocket } from '../../hooks/useWebSocket'
import { MessageList } from './MessageList'
import { InputBox } from './InputBox'

interface ChatWindowProps {
  conversationId?: string
}

export function ChatWindow({ conversationId }: ChatWindowProps) {
  const { messages, isConnected, isStreaming, sendMessage } = useWebSocket(
    `ws://${window.location.host}/ws/chat`
  )

  const handleSend = (text: string) => {
    sendMessage(text, conversationId)
  }

  return (
    <div data-testid="chat-window">
      <div>{isConnected ? (isStreaming ? '正在回复...' : '已连接') : '未连接'}</div>
      <MessageList messages={messages} />
      <InputBox onSend={handleSend} disabled={!isConnected || isStreaming} />
    </div>
  )
}

import type { Message } from '../../types/chat'

interface MessageListProps {
  messages: Message[]
}

export function MessageList({ messages }: MessageListProps) {
  if (messages.length === 0) {
    return <div data-testid="message-list">暂无消息</div>
  }

  return (
    <div data-testid="message-list">
      {messages.map(msg => (
        <div key={msg.id} data-testid="message-item">
          <span>{msg.role === 'user' ? 'You' : 'Assistant'}</span>
          <p>{msg.content}</p>
        </div>
      ))}
    </div>
  )
}

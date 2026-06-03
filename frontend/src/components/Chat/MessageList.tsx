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
          <span>{msg.role === 'user' ? 'You' : msg.role === 'system' ? 'System' : 'Assistant'}</span>
          <p>{msg.content}</p>
          {msg.toolCalls && msg.toolCalls.length > 0 && (
            <div data-testid="tool-calls">
              {msg.toolCalls.map((tc, i) => (
                <div key={i} data-testid="tool-call">
                  <span>{tc.name}</span>
                  <pre>{JSON.stringify(tc.args, null, 2)}</pre>
                  {tc.result && <pre>{tc.result}</pre>}
                </div>
              ))}
            </div>
          )}
        </div>
      ))}
    </div>
  )
}

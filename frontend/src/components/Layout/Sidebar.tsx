import type { Conversation } from '../../types/chat'

interface SidebarProps {
  conversations: Conversation[]
  onSelect: (id: string) => void
}

export function Sidebar({ conversations, onSelect }: SidebarProps) {
  return (
    <div data-testid="sidebar">
      {conversations.length === 0 ? (
        <p>暂无对话</p>
      ) : (
        conversations.map(conv => (
          <div
            key={conv.id}
            data-testid="conversation-item"
            onClick={() => onSelect(conv.id)}
          >
            {conv.id}
          </div>
        ))
      )}
    </div>
  )
}

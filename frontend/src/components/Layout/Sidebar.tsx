import type { Conversation } from '../../types/chat'
import { Plus, X } from 'lucide-react'

interface SidebarProps {
  conversations: Conversation[]
  onSelect: (id: string) => void
  onNew?: () => void
  onDelete?: (id: string) => void
  selectedId?: string
}

export function Sidebar({ conversations, onSelect, onNew, onDelete, selectedId }: SidebarProps) {
  return (
    <aside className="sidebar" data-testid="sidebar">
      <div className="sidebar-header">
        <span>Conversations</span>
        {onNew && (
          <button onClick={onNew} title="New conversation" aria-label="New conversation">
            <Plus size={16} />
          </button>
        )}
      </div>
      <div className="sidebar-list">
        {conversations.length === 0 ? (
          <div className="sidebar-empty" data-testid="sidebar-empty">
            No conversations yet.<br />Send a message to start.
          </div>
        ) : (
          conversations.map(conv => (
            <div
              key={conv.id}
              data-testid="conversation-item"
              className={`sidebar-item${selectedId === conv.id ? ' active' : ''}`}
              onClick={() => onSelect(conv.id)}
            >
              <div className="item-title">{conv.name || conv.summary || conv.id.slice(0, 8)}</div>
              <div className="item-date">
                {conv.updated_at
                  ? new Date(conv.updated_at).toLocaleDateString(undefined, {
                      month: 'short',
                      day: 'numeric',
                    })
                  : ''}
              </div>
              {onDelete && (
                <button
                  className="btn btn-ghost btn-sm sidebar-delete"
                  data-testid="delete-conversation"
                  title="Delete conversation"
                  aria-label="Delete conversation"
                  onClick={e => { e.stopPropagation(); onDelete(conv.id) }}
                >
                  <X size={14} />
                </button>
              )}
            </div>
          ))
        )}
      </div>
    </aside>
  )
}

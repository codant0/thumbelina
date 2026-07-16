import { useState, useEffect, useRef } from 'react'
import type { Conversation } from '../../types/chat'
import { Plus, X, Pencil, Check } from 'lucide-react'
import { WeChatIcon } from '../icons/WeChatIcon'
import { useTranslation } from '../../i18n'

const WECHAT_CONVERSATION_NAME = '微信Clawbot'

interface SidebarProps {
  conversations: Conversation[]
  onSelect: (id: string) => void
  onNew?: () => void
  onDelete?: (id: string) => void
  onRename?: (id: string, name: string) => void
  selectedId?: string
}

export function Sidebar({ conversations, onSelect, onNew, onDelete, onRename, selectedId }: SidebarProps) {
  const [editingId, setEditingId] = useState<string | null>(null)
  const [draft, setDraft] = useState('')
  const inputRef = useRef<HTMLInputElement>(null)
  const { t } = useTranslation()

  useEffect(() => {
    if (editingId && inputRef.current) {
      inputRef.current.focus()
      inputRef.current.select()
    }
  }, [editingId])

  const startEdit = (conv: Conversation) => {
    if (!onRename) return
    setEditingId(conv.id)
    setDraft(conv.name || '')
  }

  const commitEdit = () => {
    if (editingId && onRename) {
      const trimmed = draft.trim()
      if (trimmed) onRename(editingId, trimmed)
    }
    setEditingId(null)
    setDraft('')
  }

  const cancelEdit = () => {
    setEditingId(null)
    setDraft('')
  }

  return (
    <aside className="sidebar" data-testid="sidebar">
      <div className="sidebar-header">
        <span>{t('chat.sidebarTitle')}</span>
        {onNew && (
          <button onClick={onNew} title={t('chat.newConversation')} aria-label={t('chat.newConversation')}>
            <Plus size={16} />
          </button>
        )}
      </div>
      <div className="sidebar-list">
        {conversations.length === 0 ? (
          <div className="sidebar-empty" data-testid="sidebar-empty">
            No conversations yet.<br />{t('chat.sendHint')}
          </div>
        ) : (
          conversations.map(conv => {
            const isWeChat = conv.name === WECHAT_CONVERSATION_NAME
            const isEditing = editingId === conv.id
            return (
              <div
                key={conv.id}
                data-testid="conversation-item"
                className={`sidebar-item${selectedId === conv.id ? ' active' : ''}${conv.pinned ? ' sidebar-item--pinned' : ''}${isWeChat ? ' sidebar-item--wechat' : ''}`}
                onClick={() => !isEditing && onSelect(conv.id)}
              >
                {isEditing ? (
                  <div className="sidebar-item__edit" onClick={e => e.stopPropagation()}>
                    <input
                      ref={inputRef}
                      className="sidebar-item__input"
                      data-testid="rename-input"
                      value={draft}
                      onChange={e => setDraft(e.target.value)}
                      onKeyDown={e => {
                        if (e.key === 'Enter') commitEdit()
                        else if (e.key === 'Escape') cancelEdit()
                      }}
                      maxLength={100}
                      aria-label={t('chat.renameConversation')}
                    />
                    <button
                      className="btn btn-ghost btn-sm sidebar-item__confirm"
                      data-testid="rename-confirm"
                      title={t('chat.saveName')}
                      aria-label={t('chat.saveName')}
                      onClick={e => { e.stopPropagation(); commitEdit() }}
                    >
                      <Check size={14} />
                    </button>
                  </div>
                ) : (
                  <>
                    <div className="item-title">
                      {isWeChat && <WeChatIcon size={14} className="wechat-icon" />}
                      <span className="item-title__text">{conv.name || conv.summary || conv.id.slice(0, 8)}</span>
                    </div>
                    <div className="item-date">
                      {conv.updated_at
                        ? new Date(conv.updated_at).toLocaleDateString(undefined, {
                            month: 'short',
                            day: 'numeric',
                          })
                        : ''}
                    </div>
                    {onRename && !isWeChat && (
                      <button
                        className="btn btn-ghost btn-sm sidebar-action"
                        data-testid="rename-conversation"
                        title={t('chat.renameConversation')}
                        aria-label={t('chat.renameConversation')}
                        onClick={e => { e.stopPropagation(); startEdit(conv) }}
                      >
                        <Pencil size={13} />
                      </button>
                    )}
                    {onDelete && (
                      <button
                        className="btn btn-ghost btn-sm sidebar-delete"
                        data-testid="delete-conversation"
                        title={t('chat.deleteConversation')}
                        aria-label={t('chat.deleteConversation')}
                        onClick={e => { e.stopPropagation(); onDelete(conv.id) }}
                      >
                        <X size={14} />
                      </button>
                    )}
                  </>
                )}
              </div>
            )
          })
        )}
      </div>
    </aside>
  )
}

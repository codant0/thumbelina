import { useMemo, useState } from 'react'
import type { Conversation } from '../../types/chat'
import { ChevronDown, ChevronRight, FileText, FolderClosed, FolderOpen, Pencil, Plus, X, Check } from 'lucide-react'
import { useTranslation } from '../../i18n'

interface CoderSidebarProps {
  conversations: Conversation[]
  onSelect: (id: string) => void
  onNew?: () => void
  onDelete?: (id: string) => void
  onRename?: (id: string, name: string) => void
  selectedId?: string
  loading?: boolean
  /** Shows a close control for the mobile drawer. */
  onClose?: () => void
}

export function CoderSidebar({ conversations, onSelect, onNew, onDelete, onRename, selectedId, loading, onClose }: CoderSidebarProps) {
  const { t } = useTranslation()
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set())
  const [editingId, setEditingId] = useState<string | null>(null)
  const [draft, setDraft] = useState('')

  const groups = useMemo(() => {
    const map = new Map<string, Conversation[]>()
    for (const conv of conversations) {
      const ws = conv.workspace || t('coder.unknownWorkspace')
      const list = map.get(ws) ?? []
      list.push(conv)
      map.set(ws, list)
    }
    for (const list of map.values()) {
      list.sort((a, b) => (b.updated_at ?? '').localeCompare(a.updated_at ?? ''))
    }
    return new Map([...map.entries()].sort((a, b) =>
      (b[1][0]?.updated_at ?? '').localeCompare(a[1][0]?.updated_at ?? ''),
    ))
  }, [conversations, t])

  const toggleGroup = (ws: string) => {
    setCollapsed(prev => {
      const next = new Set(prev)
      if (next.has(ws)) next.delete(ws)
      else next.add(ws)
      return next
    })
  }

  const workspaceName = (ws: string) => ws.split(/[\\/]/).filter(Boolean).pop() || ws

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

  return (
    <aside className="sidebar coder-sidebar" data-testid="coder-sidebar">
      <div className="sidebar-header">
        <span>{t('coder.sidebarTitle')}</span>
        {onNew && (
          <button onClick={onNew} title={t('coder.newConversation')} aria-label={t('coder.newConversation')}>
            <Plus size={16} />
          </button>
        )}
        {onClose && (
          <button className="sidebar-close-btn" onClick={onClose} title={t('common.close')} aria-label={t('common.close')}>
            <X size={16} />
          </button>
        )}
      </div>
      <div className="sidebar-list">
        {loading ? (
          <div className="coder-skeleton" data-testid="coder-sidebar-loading" aria-label={t('common.loading')}>
            <div className="coder-skeleton__line" style={{ width: '60%' }} />
            <div className="coder-skeleton__line" style={{ width: '40%', marginLeft: 12 }} />
            <div className="coder-skeleton__line" style={{ width: '70%', marginLeft: 12 }} />
          </div>
        ) : groups.size === 0 ? (
          <div className="sidebar-empty" data-testid="coder-sidebar-empty">
            {t('coder.emptyHint')}
          </div>
        ) : (
          <div role="tree" aria-label={t('coder.sidebarTitle')}>
            {[...groups.entries()].map(([ws, list]) => {
              const isCollapsed = collapsed.has(ws)
              return (
                <div key={ws} className="coder-group" data-testid="coder-group">
                  <button
                    className="coder-group__header"
                    data-testid="coder-group-toggle"
                    onClick={() => toggleGroup(ws)}
                    title={ws}
                    role="treeitem"
                    aria-expanded={!isCollapsed}
                  >
                    {isCollapsed ? <ChevronRight size={14} /> : <ChevronDown size={14} />}
                    {isCollapsed ? <FolderClosed size={14} /> : <FolderOpen size={14} />}
                    <span className="coder-group__name">{workspaceName(ws)}</span>
                    <span className="coder-group__count">{list.length}</span>
                  </button>
                  <div
                    role="group"
                    className={`coder-group__items${isCollapsed ? ' coder-group__items--collapsed' : ''}`}
                    aria-hidden={isCollapsed}
                  >
                    {list.map(conv => (
                      <div
                        key={conv.id}
                        data-testid="coder-conversation-item"
                        role="treeitem"
                        tabIndex={0}
                        aria-current={selectedId === conv.id ? 'true' : undefined}
                        className={`sidebar-item coder-item${selectedId === conv.id ? ' active' : ''}`}
                        onClick={() => editingId !== conv.id && onSelect(conv.id)}
                        onKeyDown={e => {
                          if (editingId === conv.id) return
                          if (e.key === 'Enter' || e.key === ' ') {
                            e.preventDefault()
                            onSelect(conv.id)
                          }
                        }}
                      >
                        {editingId === conv.id ? (
                          <div className="sidebar-item__edit" onClick={e => e.stopPropagation()}>
                            <input
                              data-testid="rename-input"
                              className="sidebar-item__input"
                              value={draft}
                              onChange={e => setDraft(e.target.value)}
                              onBlur={commitEdit}
                              onKeyDown={e => {
                                if (e.key === 'Enter') commitEdit()
                                else if (e.key === 'Escape') { setEditingId(null); setDraft('') }
                              }}
                              maxLength={100}
                              aria-label={t('chat.renameConversation')}
                            />
                            <button className="btn btn-ghost btn-sm sidebar-item__confirm" data-testid="rename-confirm"
                              title={t('chat.saveName')} aria-label={t('chat.saveName')}
                              onMouseDown={e => e.preventDefault()}
                              onClick={e => { e.stopPropagation(); commitEdit() }}>
                              <Check size={14} />
                            </button>
                          </div>
                        ) : (
                          <>
                            <FileText size={13} className="coder-item-icon" />
                            <span className="item-title__text">{conv.name || conv.summary || t('chat.unnamed')}</span>
                            {onRename && (
                              <button className="btn btn-ghost btn-sm sidebar-action" data-testid="rename-conversation"
                                title={t('chat.renameConversation')} aria-label={t('chat.renameConversation')}
                                onClick={e => { e.stopPropagation(); startEdit(conv) }}>
                                <Pencil size={13} />
                              </button>
                            )}
                            {onDelete && (
                              <button className="btn btn-ghost btn-sm sidebar-delete" data-testid="delete-conversation"
                                title={t('chat.deleteConversation')} aria-label={t('chat.deleteConversation')}
                                onClick={e => { e.stopPropagation(); onDelete(conv.id) }}>
                                <X size={14} />
                              </button>
                            )}
                          </>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </div>
    </aside>
  )
}
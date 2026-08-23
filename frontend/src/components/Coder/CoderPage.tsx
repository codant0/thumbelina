import { useEffect, useMemo, useState } from 'react'
import { Code2 } from 'lucide-react'
import type { ChatSocket } from '../../hooks/useWebSocket'
import type { Conversation, ThinkingEffort } from '../../types/chat'
import { ChatWindow } from '../Chat/ChatWindow'
import { CoderSidebar } from './CoderSidebar'
import { WorkspacePicker } from './WorkspacePicker'
import { useTranslation } from '../../i18n'

interface CoderPageProps {
  ws: ChatSocket
  conversations: Conversation[]
  selectedId?: string
  onSelect: (id: string) => void
  onCreated: (id: string) => void
  onDelete?: (id: string) => void
  onRename?: (id: string, name: string) => void
  onRefresh: () => void
  coderLoading?: boolean
  coderError?: boolean
  onSetEndpoint?: (id: string, endpointId: string | null, model: string | null) => void
  onSetKnowledgeBase?: (id: string, knowledgeBaseId: string | null) => void
  onSetRole?: (id: string, role: string | null) => void
  onSetThinking?: (id: string, enabled: boolean, effort: ThinkingEffort) => void
  onViewTrajectory?: (id: string) => void
}

export function CoderPage({ ws, conversations, selectedId, onSelect, onCreated, onDelete, onRename, onRefresh, coderLoading, coderError, onSetEndpoint, onSetKnowledgeBase, onSetRole, onSetThinking, onViewTrajectory }: CoderPageProps) {
  const [pickerOpen, setPickerOpen] = useState(false)
  const { t } = useTranslation()

  // Only treat a selected conversation as active when it is actually a
  // coder-mode conversation in the coder list. A chat-mode conversation
  // (or a stale id selected elsewhere) must not become the active session
  // here: it has no workspace and would let the agent run unbound, leaking
  // a chat-mode conversation into the coder page.
  const activeCoderId = conversations.find(c => c.id === selectedId)?.mode === 'coder' ? selectedId : undefined

  // Distinct workspaces, most recent first — quick-fill chips in the picker.
  const recentWorkspaces = useMemo(() => {
    const seen = new Set<string>()
    const out: string[] = []
    for (const c of conversations) {
      if (c.workspace && !seen.has(c.workspace)) {
        seen.add(c.workspace)
        out.push(c.workspace)
      }
      if (out.length >= 5) break
    }
    return out
  }, [conversations])

  // Press N to open the workspace picker from the empty/start states.
  // Ignored while typing in any input so the shortcut never steals keys.
  useEffect(() => {
    if (pickerOpen || activeCoderId) return
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null
      if (target && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable)) return
      if (e.key.toLowerCase() === 'n') setPickerOpen(true)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [pickerOpen, activeCoderId])

  let main: React.ReactNode
  if (activeCoderId) {
    main = (
      <div className="coder-viewport" data-testid="coder-viewport">
        <ChatWindow
          ws={ws}
          conversationId={activeCoderId}
          conversations={conversations}
          onConversationCreated={onRefresh}
          onDefaultConversation={onSelect}
          onSetEndpoint={onSetEndpoint}
          onSetKnowledgeBase={onSetKnowledgeBase}
          onSetRole={onSetRole}
          onSetThinking={onSetThinking}
          onViewTrajectory={onViewTrajectory}
        />
      </div>
    )
  } else if (coderError) {
    main = (
      <div className="coder-hero" data-testid="coder-load-error">
        <div className="coder-hero__error">{t('coder.loadFailed')}</div>
        <button className="btn btn-ghost" data-testid="coder-retry" onClick={onRefresh}>
          {t('common.retry')}
        </button>
      </div>
    )
  } else if (coderLoading) {
    main = <div className="coder-empty-state">{t('common.loading')}</div>
  } else if (conversations.length === 0) {
    main = (
      <div className="coder-hero" data-testid="coder-hero-empty">
        <div className="coder-hero__icon" aria-hidden="true">
          <Code2 size={28} />
        </div>
        <div className="coder-hero__title">{t('coder.heroTitle')}</div>
        <div className="coder-hero__desc">{t('coder.heroDesc')}</div>
        <button className="btn btn-primary" data-testid="coder-hero-cta" onClick={() => setPickerOpen(true)}>
          {t('coder.heroCta')}
        </button>
        <div className="coder-hero__shortcut">
          {t('coder.heroShortcut')} <kbd>N</kbd>
        </div>
      </div>
    )
  } else {
    // Conversations exist but none is a valid coder selection — render
    // nothing interactive. Without ChatWindow there is no message input, so
    // no chat-mode conversation can be lazily created from this page.
    main = (
      <div className="coder-empty-state" data-testid="coder-no-selection">
        {t('coder.selectToStart')}
      </div>
    )
  }

  return (
    <div className="coder-shell" data-testid="coder-shell">
      {pickerOpen && (
        <WorkspacePicker
          onClose={() => setPickerOpen(false)}
          onCreated={id => {
            setPickerOpen(false)
            onCreated(id)
          }}
          recentWorkspaces={recentWorkspaces}
        />
      )}
      <CoderSidebar
        conversations={conversations}
        onSelect={onSelect}
        onNew={() => setPickerOpen(true)}
        onDelete={onDelete}
        onRename={onRename}
        selectedId={activeCoderId}
        loading={coderLoading}
      />
      {main}
    </div>
  )
}
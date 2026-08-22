import { useState } from 'react'
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
  onSetEndpoint?: (id: string, endpointId: string | null, model: string | null) => void
  onSetKnowledgeBase?: (id: string, knowledgeBaseId: string | null) => void
  onSetRole?: (id: string, role: string | null) => void
  onSetThinking?: (id: string, enabled: boolean, effort: ThinkingEffort) => void
  onViewTrajectory?: (id: string) => void
}

export function CoderPage({ ws, conversations, selectedId, onSelect, onCreated, onDelete, onRename, onRefresh, onSetEndpoint, onSetKnowledgeBase, onSetRole, onSetThinking, onViewTrajectory }: CoderPageProps) {
  const [pickerOpen, setPickerOpen] = useState(false)
  const { t } = useTranslation()

  // Only treat a selected conversation as active when it is actually a
  // coder-mode conversation in the coder list. A chat-mode conversation
  // (or a stale id selected elsewhere) must not become the active session
  // here: it has no workspace and would let the agent run unbound, leaking
  // a chat-mode conversation into the coder page.
  const activeCoderId = conversations.find(c => c.id === selectedId)?.mode === 'coder' ? selectedId : undefined

  return (
    <>
      {pickerOpen && (
        <WorkspacePicker
          onClose={() => setPickerOpen(false)}
          onCreated={id => {
            setPickerOpen(false)
            onCreated(id)
          }}
        />
      )}
      <CoderSidebar
        conversations={conversations}
        onSelect={onSelect}
        onNew={() => setPickerOpen(true)}
        onDelete={onDelete}
        onRename={onRename}
        selectedId={activeCoderId}
      />
      {activeCoderId ? (
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
      ) : (
        // No valid coder conversation selected — render nothing interactive.
        // Without ChatWindow there is no message input, so no chat-mode
        // conversation can be lazily created from this page.
        <div className="coder-empty-state" data-testid="coder-no-selection">
          {t('coder.selectToStart')}
        </div>
      )}
    </>
  )
}
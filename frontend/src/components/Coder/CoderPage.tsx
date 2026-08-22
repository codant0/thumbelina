import { useState } from 'react'
import type { ChatSocket } from '../../hooks/useWebSocket'
import type { Conversation, ThinkingEffort } from '../../types/chat'
import { ChatWindow } from '../Chat/ChatWindow'
import { CoderSidebar } from './CoderSidebar'
import { WorkspacePicker } from './WorkspacePicker'

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
        selectedId={selectedId}
      />
      <ChatWindow
        ws={ws}
        conversationId={selectedId}
        conversations={conversations}
        onConversationCreated={onRefresh}
        onDefaultConversation={onSelect}
        onSetEndpoint={onSetEndpoint}
        onSetKnowledgeBase={onSetKnowledgeBase}
        onSetRole={onSetRole}
        onSetThinking={onSetThinking}
        onViewTrajectory={onViewTrajectory}
      />
    </>
  )
}
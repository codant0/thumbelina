import { useState, useEffect, useCallback, useMemo, useRef } from 'react'
import { Header, type Page } from './components/Layout/Header'
import { Sidebar, WECHAT_CONVERSATION_NAME } from './components/Layout/Sidebar'
import { ChatWindow } from './components/Chat/ChatWindow'
import { useWebSocket } from './hooks/useWebSocket'
import { TaskManager } from './components/Tasks/TaskManager'
import { TodoPage } from './components/Todo/TodoPage'
import { MemoryViewer } from './components/Memory/MemoryViewer'
import { DreamViewer } from './components/Dream/DreamViewer'
import { SettingsPanel } from './components/Settings/SettingsPanel'
import { PluginsPage } from './components/Plugins/PluginsPage'
import { ChannelsPage } from './components/Channels/ChannelsPage'
import { KnowledgeBasePage } from './components/KnowledgeBase/KnowledgeBasePage'
import { TrajectoryPage } from './components/Trajectory/TrajectoryPage'
import { renameConversation, setConversationEndpoint, setConversationKnowledgeBase, setConversationRole, setConversationThinking, createConversation, fetchConversations as fetchConversationsApi } from './api/conversations'
import { CoderPage } from './components/Coder/CoderPage'
import type { Conversation, ThinkingEffort } from './types/chat'
import './App.css'

function App() {
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [coderConversations, setCoderConversations] = useState<Conversation[]>([])
  const [selectedId, setSelectedId] = useState<string | undefined>()
  const [activePage, setActivePage] = useState<Page>('chat')
  const [trajectorySessionId, setTrajectorySessionId] = useState<string | undefined>()

  // The chat WebSocket lives here (not in ChatWindow) so switching to other
  // pages keeps the connection open — otherwise an in-flight LLM response
  // would be cancelled by the backend and lost.
  const wsUrl = useMemo(() => {
    const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    return `${wsProtocol}//${window.location.host}/ws/chat`
  }, [])
  const chatSocket = useWebSocket(wsUrl, selectedId)

  // Track the latest fetch to discard stale responses
  const latestFetchRef = useRef(0)

  const fetchConversations = useCallback(() => {
    const fetchId = ++latestFetchRef.current
    fetchConversationsApi('chat')
      .then(data => {
        if (fetchId === latestFetchRef.current) {
          setConversations(Array.isArray(data) ? data : [])
        }
      })
      .catch(() => {
        if (fetchId === latestFetchRef.current) {
          setConversations([])
        }
      })
  }, [])

  useEffect(() => {
    fetchConversations()
  }, [fetchConversations])

  // Refresh conversation list when notified by other components (e.g. WeChat QR confirm)
  useEffect(() => {
    const handler = () => fetchConversations()
    window.addEventListener('conversations-updated', handler)
    return () => window.removeEventListener('conversations-updated', handler)
  }, [fetchConversations])

  const fetchCoderConversations = useCallback(() => {
    fetchConversationsApi('coder')
      .then(data => setCoderConversations(Array.isArray(data) ? data : []))
      .catch(() => setCoderConversations([]))
  }, [])

  useEffect(() => {
    fetchCoderConversations()
  }, [fetchCoderConversations])

  // Default to the WeChat conversation when entering the chat page with no selection
  useEffect(() => {
    if (selectedId === undefined && conversations.length > 0) {
      const wechat = conversations.find(c => c.name === WECHAT_CONVERSATION_NAME)
      // eslint-disable-next-line react-hooks/set-state-in-effect
      if (wechat) setSelectedId(wechat.id)
    }
  }, [conversations, selectedId])

  const handleSelect = useCallback((id: string) => {
    setSelectedId(id)
  }, [])

  const handleDefaultConversation = useCallback((id: string) => {
    setSelectedId(prev => prev ?? id)
  }, [])

  const handleNewConversation = useCallback(async () => {
    try {
      const conv = await createConversation({})
      setSelectedId(conv.id)
      // Insert after pinned conversations so pinned items (e.g. 微信Clawbot)
      // always stay on top, mirroring the backend's pinned-first ordering.
      setConversations(prev => {
        const list = Array.isArray(prev) ? prev : []
        const pinned = list.filter(c => c.pinned)
        const rest = list.filter(c => !c.pinned)
        return [...pinned, conv, ...rest]
      })
    } catch { /* ignore */ }
  }, [])

  const handleCoderConversationCreated = useCallback((id: string) => {
    setSelectedId(id)
    fetchCoderConversations()
  }, [fetchCoderConversations])

  const handleDelete = useCallback(async (id: string) => {
    try {
      const res = await fetch(`/api/v1/conversations/${id}`, { method: 'DELETE' })
      if (res.ok) {
        setConversations(prev => Array.isArray(prev) ? prev.filter(c => c.id !== id) : [])
        setCoderConversations(prev => Array.isArray(prev) ? prev.filter(c => c.id !== id) : [])
        if (selectedId === id) setSelectedId(undefined)
      }
    } catch { /* ignore */ }
  }, [selectedId])

  const updateConversationInState = useCallback((conv: Conversation) => {
    const apply = (list: Conversation[]) => (Array.isArray(list) ? list : []).map(c => (c.id === conv.id ? { ...c, ...conv } : c))
    setConversations(prev => apply(prev))
    setCoderConversations(prev => apply(prev))
  }, [])

  const handleRename = useCallback(async (id: string, name: string) => {
    try {
      const updated = await renameConversation(id, name)
      updateConversationInState(updated)
    } catch { /* ignore */ }
  }, [updateConversationInState])

  const handleSetEndpoint = useCallback(async (id: string, endpointId: string | null, model: string | null) => {
    try {
      const updated = await setConversationEndpoint(id, endpointId, model)
      updateConversationInState(updated)
    } catch { /* ignore */ }
  }, [updateConversationInState])

  const handleSetKnowledgeBase = useCallback(async (id: string, knowledgeBaseId: string | null) => {
    try {
      const updated = await setConversationKnowledgeBase(id, knowledgeBaseId)
      updateConversationInState(updated)
    } catch { /* ignore */ }
  }, [updateConversationInState])

  const handleSetRole = useCallback(async (id: string, role: string | null) => {
    try {
      const updated = await setConversationRole(id, role)
      updateConversationInState(updated)
    } catch { /* ignore */ }
  }, [updateConversationInState])

  const handleSetThinking = useCallback(async (id: string, enabled: boolean, effort: ThinkingEffort) => {
    try {
      const updated = await setConversationThinking(id, enabled, effort)
      updateConversationInState(updated)
    } catch { /* ignore */ }
  }, [updateConversationInState])

  const handleViewTrajectory = useCallback(() => {
    setTrajectorySessionId(selectedId)
    setActivePage('trajectory')
  }, [selectedId])

  const renderPage = () => {
    switch (activePage) {
      case 'tasks':
        return <TaskManager />
      case 'todo':
        return <TodoPage />
      case 'memory':
        return <MemoryViewer />
      case 'dream':
        return <DreamViewer />
      case 'settings':
        return <SettingsPanel />
      case 'plugins':
        return <PluginsPage />
      case 'channels':
        return <ChannelsPage />
      case 'knowledge-base':
        return <KnowledgeBasePage />
      case 'trajectory':
        return <TrajectoryPage initialConversationId={trajectorySessionId} />
      case 'coder':
        return (
          <CoderPage
            ws={chatSocket}
            conversations={coderConversations}
            selectedId={selectedId}
            onSelect={handleSelect}
            onCreated={handleCoderConversationCreated}
            onDelete={handleDelete}
            onRename={handleRename}
            onRefresh={fetchCoderConversations}
            onSetEndpoint={handleSetEndpoint}
            onSetKnowledgeBase={handleSetKnowledgeBase}
            onSetRole={handleSetRole}
            onSetThinking={handleSetThinking}
            onViewTrajectory={handleViewTrajectory}
          />
        )
      case 'chat':
      default: {
        // Only treat a selected conversation as active on the chat page when
        // it actually exists in the chat list. A coder conversation selected
        // on the coder page must not stay active here (no chat role, and it
        // would be passed to the backend as an active chat session).
        const chatActiveId = conversations.some(c => c.id === selectedId) ? selectedId : undefined
        return (
          <>
            <Sidebar
              conversations={conversations}
              onSelect={handleSelect}
              onNew={handleNewConversation}
              onDelete={handleDelete}
              onRename={handleRename}
              selectedId={chatActiveId}
            />
            <ChatWindow
              ws={chatSocket}
              conversationId={chatActiveId}
              conversations={conversations}
              onConversationCreated={fetchConversations}
              onDefaultConversation={handleDefaultConversation}
              onSetEndpoint={handleSetEndpoint}
              onSetKnowledgeBase={handleSetKnowledgeBase}
              onSetRole={handleSetRole}
              onSetThinking={handleSetThinking}
              onViewTrajectory={handleViewTrajectory}
            />
          </>
        )
      }
    }
  }

  return (
    <div className="app">
      <Header activePage={activePage} onNavigate={setActivePage} />
      <div className="app-body">
        {renderPage()}
      </div>
    </div>
  )
}

export default App

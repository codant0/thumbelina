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
import { renameConversation, setConversationEndpoint, setConversationKnowledgeBase, setConversationRole, setConversationThinking } from './api/conversations'
import type { Conversation, ThinkingEffort } from './types/chat'
import './App.css'

function App() {
  const [conversations, setConversations] = useState<Conversation[]>([])
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
    fetch('/api/v1/conversations')
      .then(res => {
        if (!res.ok) return []
        return res.json()
      })
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
      const res = await fetch('/api/v1/conversations', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({}),
      })
      if (res.ok) {
        const conv: Conversation = await res.json()
        setSelectedId(conv.id)
        // Insert after pinned conversations so pinned items (e.g. 微信Clawbot)
        // always stay on top, mirroring the backend's pinned-first ordering.
        setConversations(prev => {
          const list = Array.isArray(prev) ? prev : []
          const pinned = list.filter(c => c.pinned)
          const rest = list.filter(c => !c.pinned)
          return [...pinned, conv, ...rest]
        })
      }
    } catch { /* ignore */ }
  }, [])

  const handleDelete = useCallback(async (id: string) => {
    try {
      const res = await fetch(`/api/v1/conversations/${id}`, { method: 'DELETE' })
      if (res.ok) {
        setConversations(prev => Array.isArray(prev) ? prev.filter(c => c.id !== id) : [])
        if (selectedId === id) setSelectedId(undefined)
      }
    } catch { /* ignore */ }
  }, [selectedId])

  const updateConversationInState = useCallback((conv: Conversation) => {
    setConversations(prev => (Array.isArray(prev) ? prev : []).map(c => (c.id === conv.id ? { ...c, ...conv } : c)))
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
      case 'chat':
      default:
        return (
          <>
            <Sidebar
              conversations={conversations}
              onSelect={handleSelect}
              onNew={handleNewConversation}
              onDelete={handleDelete}
              onRename={handleRename}
              selectedId={selectedId}
            />
            <ChatWindow
              ws={chatSocket}
              conversationId={selectedId}
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

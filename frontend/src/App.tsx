import { Suspense, lazy, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { BrowserRouter, Route, Routes, useLocation, useNavigate, useParams } from 'react-router-dom'
import { Header, type Page } from './components/Layout/Header'
import { Sidebar, WECHAT_CONVERSATION_NAME } from './components/Layout/Sidebar'
import { ChatWindow } from './components/Chat/ChatWindow'
import { useWebSocket } from './hooks/useWebSocket'
import { renameConversation, setConversationEndpoint, setConversationKnowledgeBase, setConversationRole, setConversationThinking, createConversation, fetchConversations as fetchConversationsApi } from './api/conversations'
import { CoderPage } from './components/Coder/CoderPage'
import type { Conversation, ThinkingEffort } from './types/chat'

// Everything except the chat/coder shells is deferred: each page becomes its
// own chunk so the initial bundle only carries what the landing view needs.
const TaskManager = lazy(() => import('./components/Tasks/TaskManager').then(m => ({ default: m.TaskManager })))
const TodoPage = lazy(() => import('./components/Todo/TodoPage').then(m => ({ default: m.TodoPage })))
const MemoryViewer = lazy(() => import('./components/Memory/MemoryViewer').then(m => ({ default: m.MemoryViewer })))
const DreamViewer = lazy(() => import('./components/Dream/DreamViewer').then(m => ({ default: m.DreamViewer })))
const SettingsPanel = lazy(() => import('./components/Settings/SettingsPanel').then(m => ({ default: m.SettingsPanel })))
const PluginsPage = lazy(() => import('./components/Plugins/PluginsPage').then(m => ({ default: m.PluginsPage })))
const ChannelsPage = lazy(() => import('./components/Channels/ChannelsPage').then(m => ({ default: m.ChannelsPage })))
const KnowledgeBasePage = lazy(() => import('./components/KnowledgeBase/KnowledgeBasePage').then(m => ({ default: m.KnowledgeBasePage })))
const TrajectoryPage = lazy(() => import('./components/Trajectory/TrajectoryPage').then(m => ({ default: m.TrajectoryPage })))

const PATH_TO_PAGE: Record<string, Page> = {
  '': 'chat',
  chat: 'chat',
  coder: 'coder',
  trajectory: 'trajectory',
  tasks: 'tasks',
  todo: 'todo',
  memory: 'memory',
  dream: 'dream',
  'knowledge-base': 'knowledge-base',
  settings: 'settings',
  plugins: 'plugins',
  channels: 'channels',
}

function pageFromPath(pathname: string): Page {
  const seg = pathname.split('/').filter(Boolean)[0] ?? ''
  return PATH_TO_PAGE[seg] ?? 'chat'
}

function PageFallback() {
  return (
    <div className="loading-state" role="status">
      <span className="spinner" />
    </div>
  )
}

/** Props ChatWindow needs from App state, minus the conversation id which
 *  comes from the route param. */
interface ChatRouteProps {
  ws: ReturnType<typeof useWebSocket>
  conversations: Conversation[]
  onConversationCreated: () => void
  onSelectConversation: (id: string) => void
  onNewConversation: () => void
  onDeleteConversation: (id: string) => void
  onRenameConversation: (id: string, name: string) => void
  onDefaultConversation: (id: string) => void
  onSetEndpoint: (id: string, endpointId: string | null, model: string | null) => void
  onSetKnowledgeBase: (id: string, knowledgeBaseId: string | null) => void
  onSetRole: (id: string, role: string | null) => void
  onSetThinking: (id: string, enabled: boolean, effort: ThinkingEffort) => void
  onViewTrajectory: (id: string) => void
  sidebarOpen: boolean
  onCloseSidebar: () => void
}

function ChatRoute({
  ws, conversations, onConversationCreated, onSelectConversation, onNewConversation,
  onDeleteConversation, onRenameConversation, onDefaultConversation,
  onSetEndpoint, onSetKnowledgeBase, onSetRole, onSetThinking, onViewTrajectory,
  sidebarOpen, onCloseSidebar,
}: ChatRouteProps) {
  const { conversationId: paramId } = useParams()
  // Only a conversation that exists in the chat list counts as active here
  // (a coder id from another route must not leak into the chat session).
  const activeId = conversations.some(c => c.id === paramId) ? paramId : undefined
  return (
    <>
      <Sidebar
        conversations={conversations}
        onSelect={onSelectConversation}
        onNew={onNewConversation}
        onDelete={onDeleteConversation}
        onRename={onRenameConversation}
        selectedId={activeId}
        onClose={onCloseSidebar}
      />
      {sidebarOpen && <button className="sidebar-backdrop" aria-hidden="true" tabIndex={-1} onClick={onCloseSidebar} />}
      <ChatWindow
        ws={ws}
        conversationId={activeId}
        conversations={conversations}
        onConversationCreated={onConversationCreated}
        onDefaultConversation={onDefaultConversation}
        onSetEndpoint={onSetEndpoint}
        onSetKnowledgeBase={onSetKnowledgeBase}
        onSetRole={onSetRole}
        onSetThinking={onSetThinking}
        onViewTrajectory={onViewTrajectory}
      />
    </>
  )
}

function AppInner() {
  const location = useLocation()
  const navigate = useNavigate()
  const activePage = useMemo(() => pageFromPath(location.pathname), [location.pathname])

  const [conversations, setConversations] = useState<Conversation[]>([])
  const [coderConversations, setCoderConversations] = useState<Conversation[]>([])
  const [sidebarOpen, setSidebarOpen] = useState(false)

  // Selected conversation id lives in the URL (/chat/:id, /coder/:id).
  const selectedId = useMemo(() => location.pathname.split('/').filter(Boolean)[1], [location.pathname])

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

  const [coderLoading, setCoderLoading] = useState(true)
  const [coderError, setCoderError] = useState(false)

  const fetchCoderConversations = useCallback(() => {
    fetchConversationsApi('coder')
      .then(data => {
        setCoderConversations(Array.isArray(data) ? data : [])
        setCoderError(false)
      })
      .catch(() => {
        setCoderConversations([])
        setCoderError(true)
      })
      .finally(() => setCoderLoading(false))
  }, [])

  useEffect(() => {
    fetchCoderConversations()
  }, [fetchCoderConversations])

  // Default to the WeChat conversation when entering the chat page with no id
  useEffect(() => {
    if (activePage === 'chat' && !selectedId && conversations.length > 0) {
      const wechat = conversations.find(c => c.name === WECHAT_CONVERSATION_NAME)
      if (wechat) navigate(`/chat/${wechat.id}`, { replace: true })
    }
  }, [activePage, selectedId, conversations, navigate])

  const handleNavigate = useCallback((page: Page) => {
    setSidebarOpen(false)
    navigate(page === 'chat' ? '/chat' : `/${page}`)
  }, [navigate])

  const handleSelectConversation = useCallback((id: string) => {
    setSidebarOpen(false)
    navigate(`/chat/${id}`)
  }, [navigate])

  const handleDefaultConversation = useCallback((id: string) => {
    navigate(`/chat/${id}`, { replace: true })
  }, [navigate])

  const handleNewConversation = useCallback(async () => {
    try {
      const conv = await createConversation({})
      // Insert after pinned conversations so pinned items (e.g. 微信Clawbot)
      // always stay on top, mirroring the backend's pinned-first ordering.
      setConversations(prev => {
        const list = Array.isArray(prev) ? prev : []
        const pinned = list.filter(c => c.pinned)
        const rest = list.filter(c => !c.pinned)
        return [...pinned, conv, ...rest]
      })
      setSidebarOpen(false)
      navigate(`/chat/${conv.id}`)
    } catch { /* ignore */ }
  }, [navigate])

  const handleCoderConversationCreated = useCallback((id: string) => {
    navigate(`/coder/${id}`)
    fetchCoderConversations()
  }, [navigate, fetchCoderConversations])

  const handleCoderSelect = useCallback((id: string) => {
    setSidebarOpen(false)
    navigate(`/coder/${id}`)
  }, [navigate])

  const handleDelete = useCallback(async (id: string) => {
    try {
      const res = await fetch(`/api/v1/conversations/${id}`, { method: 'DELETE' })
      if (res.ok) {
        setConversations(prev => Array.isArray(prev) ? prev.filter(c => c.id !== id) : [])
        setCoderConversations(prev => Array.isArray(prev) ? prev.filter(c => c.id !== id) : [])
        if (selectedId === id) navigate(activePage === 'coder' ? '/coder' : '/chat')
      }
    } catch { /* ignore */ }
  }, [selectedId, navigate, activePage])

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

  const handleViewTrajectory = useCallback((id: string) => {
    navigate(`/trajectory/${id}`)
  }, [navigate])

  const chatProps = {
    ws: chatSocket,
    conversations,
    onConversationCreated: fetchConversations,
    onSelectConversation: handleSelectConversation,
    onNewConversation: () => void handleNewConversation(),
    onDeleteConversation: (id: string) => void handleDelete(id),
    onRenameConversation: (id: string, name: string) => void handleRename(id, name),
    onDefaultConversation: handleDefaultConversation,
    onSetEndpoint: handleSetEndpoint,
    onSetKnowledgeBase: handleSetKnowledgeBase,
    onSetRole: handleSetRole,
    onSetThinking: handleSetThinking,
    onViewTrajectory: handleViewTrajectory,
    sidebarOpen,
    onCloseSidebar: () => setSidebarOpen(false),
  }

  const coderProps = {
    ws: chatSocket,
    conversations: coderConversations,
    selectedId: coderConversations.some(c => c.id === selectedId) ? selectedId : undefined,
    onSelect: handleCoderSelect,
    onCreated: handleCoderConversationCreated,
    onDelete: handleDelete,
    onRename: handleRename,
    onRefresh: fetchCoderConversations,
    coderLoading,
    coderError,
    onSetEndpoint: handleSetEndpoint,
    onSetKnowledgeBase: handleSetKnowledgeBase,
    onSetRole: handleSetRole,
    onSetThinking: handleSetThinking,
    onViewTrajectory: handleViewTrajectory,
    sidebarOpen,
    onCloseSidebar: () => setSidebarOpen(false),
  }

  return (
    <div className="app">
      <Header
        activePage={activePage}
        onNavigate={handleNavigate}
        onToggleSidebar={(activePage === 'chat' || activePage === 'coder') ? () => setSidebarOpen(o => !o) : undefined}
      />
      <div className={`app-body${sidebarOpen ? ' sidebar-open' : ''}`}>
        <Suspense fallback={<PageFallback />}>
          <Routes>
            <Route path="/" element={<ChatRoute {...chatProps} />} />
            <Route path="/chat" element={<ChatRoute {...chatProps} />} />
            <Route path="/chat/:conversationId" element={<ChatRoute {...chatProps} />} />
            <Route path="/coder" element={<CoderPage {...coderProps} />} />
            <Route path="/coder/:conversationId" element={<CoderPage {...coderProps} />} />
            <Route path="/tasks" element={<TaskManager />} />
            <Route path="/todo" element={<TodoPage />} />
            <Route path="/memory" element={<MemoryViewer />} />
            <Route path="/dream" element={<DreamViewer />} />
            <Route path="/settings" element={<SettingsPanel />} />
            <Route path="/plugins" element={<PluginsPage />} />
            <Route path="/channels" element={<ChannelsPage />} />
            <Route path="/knowledge-base" element={<KnowledgeBasePage />} />
            <Route path="/trajectory" element={<TrajectoryPage initialConversationId={undefined} />} />
            <Route path="/trajectory/:conversationId" element={<TrajectoryRoute />} />
            <Route path="*" element={<ChatRoute {...chatProps} />} />
          </Routes>
        </Suspense>
      </div>
    </div>
  )
}

function TrajectoryRoute() {
  const { conversationId } = useParams()
  return <TrajectoryPage initialConversationId={conversationId} />
}

function App() {
  return (
    <BrowserRouter>
      <AppInner />
    </BrowserRouter>
  )
}

export default App

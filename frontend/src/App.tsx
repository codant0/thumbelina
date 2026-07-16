import { useState, useEffect, useCallback, useRef } from 'react'
import { Header, type Page } from './components/Layout/Header'
import { Sidebar } from './components/Layout/Sidebar'
import { ChatWindow } from './components/Chat/ChatWindow'
import { TaskManager } from './components/Tasks/TaskManager'
import { MemoryViewer } from './components/Memory/MemoryViewer'
import { DreamViewer } from './components/Dream/DreamViewer'
import { SettingsPanel } from './components/Settings/SettingsPanel'
import { PluginsPage } from './components/Plugins/PluginsPage'
import { ChannelsPage } from './components/Channels/ChannelsPage'
import { renameConversation, setConversationEndpoint } from './api/conversations'
import type { Conversation } from './types/chat'
import './App.css'

function App() {
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [selectedId, setSelectedId] = useState<string | undefined>()
  const [activePage, setActivePage] = useState<Page>('chat')

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

  const renderPage = () => {
    switch (activePage) {
      case 'tasks':
        return <TaskManager />
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
              conversationId={selectedId}
              conversations={conversations}
              onConversationCreated={fetchConversations}
              onDefaultConversation={handleDefaultConversation}
              onSetEndpoint={handleSetEndpoint}
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

import { useState, useEffect, useCallback } from 'react'
import { Header, type Page } from './components/Layout/Header'
import { Sidebar } from './components/Layout/Sidebar'
import { ChatWindow } from './components/Chat/ChatWindow'
import { TaskManager } from './components/Tasks/TaskManager'
import { MemoryViewer } from './components/Memory/MemoryViewer'
import { DreamViewer } from './components/Dream/DreamViewer'
import { SettingsPanel } from './components/Settings/SettingsPanel'
import { PluginsPage } from './components/Plugins/PluginsPage'
import { ChannelsPage } from './components/Channels/ChannelsPage'
import type { Conversation } from './types/chat'
import './App.css'

function App() {
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [selectedId, setSelectedId] = useState<string | undefined>()
  const [activePage, setActivePage] = useState<Page>('chat')

  const fetchConversations = useCallback(() => {
    fetch('/api/v1/conversations')
      .then(res => {
        if (!res.ok) return []
        return res.json()
      })
      .then(data => setConversations(Array.isArray(data) ? data : []))
      .catch(() => setConversations([]))
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
        setConversations(prev => [conv, ...(Array.isArray(prev) ? prev : [])])
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
              selectedId={selectedId}
            />
            <ChatWindow
              conversationId={selectedId}
              onConversationCreated={fetchConversations}
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

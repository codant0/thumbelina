import { useState, useEffect, useCallback } from 'react'
import { Header, type Page } from './components/Layout/Header'
import { Sidebar } from './components/Layout/Sidebar'
import { ChatWindow } from './components/Chat/ChatWindow'
import { TaskManager } from './components/Tasks/TaskManager'
import { MemoryViewer } from './components/Memory/MemoryViewer'
import { DreamViewer } from './components/Dream/DreamViewer'
import { SettingsPanel } from './components/Settings/SettingsPanel'
import type { Conversation } from './types/chat'

function App() {
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [selectedId, setSelectedId] = useState<string | undefined>()
  const [activePage, setActivePage] = useState<Page>('chat')

  useEffect(() => {
    fetch('/api/v1/conversations')
      .then(res => res.json())
      .then(setConversations)
      .catch(() => {})
  }, [])

  const handleSelect = useCallback((id: string) => {
    setSelectedId(id)
  }, [])

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
      case 'chat':
      default:
        return (
          <>
            <Sidebar conversations={conversations} onSelect={handleSelect} />
            <ChatWindow conversationId={selectedId} />
          </>
        )
    }
  }

  return (
    <div>
      <Header activePage={activePage} onNavigate={setActivePage} />
      {renderPage()}
    </div>
  )
}

export default App

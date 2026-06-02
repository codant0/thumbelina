import { useState, useEffect, useCallback } from 'react'
import { Header } from './components/Layout/Header'
import { Sidebar } from './components/Layout/Sidebar'
import { ChatWindow } from './components/Chat/ChatWindow'
import type { Conversation } from './types/chat'

function App() {
  const [conversations, setConversations] = useState<Conversation[]>([])

  useEffect(() => {
    fetch('/api/v1/conversations')
      .then(res => res.json())
      .then(setConversations)
      .catch(() => {})
  }, [])

  const handleSelect = useCallback((_id: string) => {
    // TODO: load conversation messages
  }, [])

  return (
    <div>
      <Header />
      <Sidebar conversations={conversations} onSelect={handleSelect} />
      <ChatWindow />
    </div>
  )
}

export default App

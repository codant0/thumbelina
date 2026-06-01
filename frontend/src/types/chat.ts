export interface Message {
  id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  timestamp: string
}

export interface Conversation {
  id: string
  created_at: string
  updated_at: string
  messages?: Message[]
}

export interface ChatRequest {
  message: string
  conversation_id?: string
}

export interface ChatResponse {
  response: string
  conversation_id: string
}

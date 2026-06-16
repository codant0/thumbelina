export interface ToolCall {
  name: string
  args: Record<string, unknown>
  result?: string
}

export interface Message {
  id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  timestamp: string
  toolCalls?: ToolCall[]
}

export interface Conversation {
  id: string
  name?: string | null
  pinned?: boolean
  created_at: string
  updated_at: string
  summary?: string | null
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

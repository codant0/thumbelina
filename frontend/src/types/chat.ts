export interface ToolCall {
  name: string
  args: Record<string, unknown>
  result?: string
}

export type ThinkingEffort = 'low' | 'medium' | 'high'

export interface Message {
  id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  timestamp: string
  toolCalls?: ToolCall[]
  thinking?: string
}

export interface Conversation {
  id: string
  name?: string | null
  pinned?: boolean
  mode?: 'chat' | 'coder'
  workspace?: string | null
  endpoint_id?: string | null
  model?: string | null
  knowledge_base_id?: string | null
  role?: string | null
  thinking_enabled?: boolean
  thinking_effort?: ThinkingEffort
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

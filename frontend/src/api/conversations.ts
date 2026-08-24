import type { Conversation, ThinkingEffort } from '../types/chat'

const API_BASE = '/api/v1'

export async function fetchConversations(mode?: 'chat' | 'coder'): Promise<Conversation[]> {
  const query = mode ? `?mode=${mode}` : ''
  const res = await fetch(`${API_BASE}/conversations${query}`)
  if (!res.ok) return []
  const data = await res.json()
  return Array.isArray(data) ? data : []
}

export async function createConversation(options: {
  name?: string
  pinned?: boolean
  mode?: 'chat' | 'coder'
  workspace?: string
} = {}): Promise<Conversation> {
  const res = await fetch(`${API_BASE}/conversations`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(options),
  })
  if (!res.ok) {
    const data = await res.json().catch(() => ({}))
    throw new Error(data.detail || `HTTP ${res.status}`)
  }
  return res.json() as Promise<Conversation>
}

export async function renameConversation(id: string, name: string): Promise<Conversation> {
  const res = await fetch(`${API_BASE}/conversations/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name }),
  })
  if (!res.ok) {
    const data = await res.json().catch(() => ({}))
    throw new Error(data.detail || `HTTP ${res.status}`)
  }
  return res.json() as Promise<Conversation>
}

export async function setConversationEndpoint(
  id: string,
  endpointId: string | null,
  model: string | null = null,
): Promise<Conversation> {
  const res = await fetch(`${API_BASE}/conversations/${id}/endpoint`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ endpoint_id: endpointId, model }),
  })
  if (!res.ok) {
    const data = await res.json().catch(() => ({}))
    throw new Error(data.detail || `HTTP ${res.status}`)
  }
  return res.json() as Promise<Conversation>
}

export async function setConversationKnowledgeBase(
  id: string,
  knowledgeBaseId: string | null,
): Promise<Conversation> {
  const res = await fetch(`${API_BASE}/conversations/${id}/knowledge-base`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ knowledge_base_id: knowledgeBaseId }),
  })
  if (!res.ok) {
    const data = await res.json().catch(() => ({}))
    throw new Error(data.detail || `HTTP ${res.status}`)
  }
  return res.json() as Promise<Conversation>
}

export async function listRoles(): Promise<string[]> {
  const res = await fetch(`${API_BASE}/roles`)
  if (!res.ok) {
    const data = await res.json().catch(() => ({}))
    throw new Error(data.detail || `HTTP ${res.status}`)
  }
  const data = await res.json()
  return Array.isArray(data) ? data : []
}

export async function setConversationRole(
  id: string,
  role: string | null,
): Promise<Conversation> {
  const res = await fetch(`${API_BASE}/conversations/${id}/role`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ role }),
  })
  if (!res.ok) {
    const data = await res.json().catch(() => ({}))
    throw new Error(data.detail || `HTTP ${res.status}`)
  }
  return res.json() as Promise<Conversation>
}

export async function setConversationThinking(
  id: string,
  enabled: boolean,
  effort: ThinkingEffort,
): Promise<Conversation> {
  const res = await fetch(`${API_BASE}/conversations/${id}/thinking`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ enabled, effort }),
  })
  if (!res.ok) {
    const data = await res.json().catch(() => ({}))
    throw new Error(data.detail || `HTTP ${res.status}`)
  }
  return res.json() as Promise<Conversation>
}

export async function clearConversationMessages(id: string): Promise<void> {
  const res = await fetch(`${API_BASE}/conversations/${id}/messages`, {
    method: 'DELETE',
  })
  if (!res.ok) {
    const data = await res.json().catch(() => ({}))
    throw new Error(data.detail || `HTTP ${res.status}`)
  }
}

export interface CompressResult {
  compressed: boolean
  tokens_before?: number
  tokens_after?: number
  kept?: number
  reason?: string
}

export async function compressConversation(id: string): Promise<CompressResult> {
  const res = await fetch(`${API_BASE}/conversations/${id}/compress`, {
    method: 'POST',
  })
  if (!res.ok) {
    const data = await res.json().catch(() => ({}))
    throw new Error(data.detail || `HTTP ${res.status}`)
  }
  return res.json() as Promise<CompressResult>
}

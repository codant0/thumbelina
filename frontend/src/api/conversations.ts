import type { Conversation } from '../types/chat'

const API_BASE = '/api/v1'

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

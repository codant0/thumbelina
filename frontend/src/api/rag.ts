import type {
  KnowledgeBase,
  RagDocument,
  QueryResult,
  ChunkItem,
  BatchUploadResponse,
  UploadTask,
} from '../types/rag'

const API_BASE = '/api/v1/rag'

// ── Knowledge Bases ─────────────────────────────────

export async function listKnowledgeBases(): Promise<KnowledgeBase[]> {
  const res = await fetch(`${API_BASE}/knowledge-bases`)
  if (!res.ok) {
    const data = await res.json().catch(() => ({}))
    throw new Error(data.detail || `HTTP ${res.status}`)
  }
  return res.json() as Promise<KnowledgeBase[]>
}

export async function createKnowledgeBase(
  name: string,
  description?: string | null,
): Promise<KnowledgeBase> {
  const res = await fetch(`${API_BASE}/knowledge-bases`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, description: description || null }),
  })
  if (!res.ok) {
    const data = await res.json().catch(() => ({}))
    throw new Error(data.detail || `HTTP ${res.status}`)
  }
  return res.json() as Promise<KnowledgeBase>
}

export async function updateKnowledgeBase(
  id: string,
  data: { name?: string; description?: string | null },
): Promise<KnowledgeBase> {
  const res = await fetch(`${API_BASE}/knowledge-bases/${id}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || `HTTP ${res.status}`)
  }
  return res.json() as Promise<KnowledgeBase>
}

export async function deleteKnowledgeBase(id: string): Promise<void> {
  const res = await fetch(`${API_BASE}/knowledge-bases/${id}`, { method: 'DELETE' })
  if (!res.ok) {
    const data = await res.json().catch(() => ({}))
    throw new Error(data.detail || `HTTP ${res.status}`)
  }
}

// ── Documents ───────────────────────────────────────

export async function listDocuments(kbId: string): Promise<RagDocument[]> {
  const res = await fetch(`${API_BASE}/knowledge-bases/${kbId}/documents`)
  if (!res.ok) {
    const data = await res.json().catch(() => ({}))
    throw new Error(data.detail || `HTTP ${res.status}`)
  }
  return res.json() as Promise<RagDocument[]>
}

// TODO(task-9): remove after page migration
export async function uploadDocument(kbId: string, file: File): Promise<RagDocument> {
  const formData = new FormData()
  formData.append('file', file)
  const res = await fetch(`${API_BASE}/knowledge-bases/${kbId}/documents`, {
    method: 'POST',
    body: formData,
  })
  if (!res.ok) {
    const data = await res.json().catch(() => ({}))
    throw new Error(data.detail || `HTTP ${res.status}`)
  }
  return res.json() as Promise<RagDocument>
}

// TODO(task-9): remove after page migration
export async function uploadDocumentByUrl(kbId: string, url: string): Promise<RagDocument> {
  const res = await fetch(`${API_BASE}/knowledge-bases/${kbId}/documents/url`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ url }),
  })
  if (!res.ok) {
    const data = await res.json().catch(() => ({}))
    throw new Error(data.detail || `HTTP ${res.status}`)
  }
  return res.json() as Promise<RagDocument>
}

// TODO(task-9): remove after page migration
export async function uploadDocumentsBatch(
  kbId: string,
  files: File[],
): Promise<BatchUploadResponse> {
  const formData = new FormData()
  for (const file of files) {
    formData.append('files', file)
  }
  const res = await fetch(`${API_BASE}/knowledge-bases/${kbId}/documents/batch`, {
    method: 'POST',
    body: formData,
  })
  if (!res.ok) {
    const data = await res.json().catch(() => ({}))
    throw new Error(data.detail || `HTTP ${res.status}`)
  }
  return res.json() as Promise<BatchUploadResponse>
}

// ── Upload Tasks (async) ────────────────────────────

export async function uploadFilesAsync(kbId: string, files: File[]): Promise<string> {
  if (files.length === 0) throw new Error('No files to upload')
  const formData = new FormData()
  let path: string
  if (files.length === 1) {
    formData.append('file', files[0])
    path = `${API_BASE}/knowledge-bases/${kbId}/documents`
  } else {
    for (const file of files) formData.append('files', file)
    path = `${API_BASE}/knowledge-bases/${kbId}/documents/batch`
  }
  const res = await fetch(path, { method: 'POST', body: formData })
  if (!res.ok) {
    const data = await res.json().catch(() => ({}))
    throw new Error(data.detail || `HTTP ${res.status}`)
  }
  const data = (await res.json()) as { task_id: string }
  return data.task_id
}

export async function uploadUrlAsync(kbId: string, url: string): Promise<string> {
  const res = await fetch(`${API_BASE}/knowledge-bases/${kbId}/documents/url`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ url }),
  })
  if (!res.ok) {
    const data = await res.json().catch(() => ({}))
    throw new Error(data.detail || `HTTP ${res.status}`)
  }
  const data = (await res.json()) as { task_id: string }
  return data.task_id
}

export async function listUploadTasks(kbId: string): Promise<UploadTask[]> {
  const res = await fetch(`${API_BASE}/knowledge-bases/${kbId}/upload-tasks`)
  if (!res.ok) {
    const data = await res.json().catch(() => ({}))
    throw new Error(data.detail || `HTTP ${res.status}`)
  }
  return res.json() as Promise<UploadTask[]>
}

export async function cancelUploadTask(taskId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/upload-tasks/${taskId}`, { method: 'DELETE' })
  if (!res.ok) {
    const data = await res.json().catch(() => ({}))
    throw new Error(data.detail || `HTTP ${res.status}`)
  }
}

export async function deleteDocument(docId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/documents/${docId}`, { method: 'DELETE' })
  if (!res.ok) {
    const data = await res.json().catch(() => ({}))
    throw new Error(data.detail || `HTTP ${res.status}`)
  }
}

export async function listDocumentChunks(docId: string): Promise<ChunkItem[]> {
  const res = await fetch(`${API_BASE}/documents/${docId}/chunks`)
  if (!res.ok) {
    const data = await res.json().catch(() => ({}))
    throw new Error(data.detail || `HTTP ${res.status}`)
  }
  return res.json() as Promise<ChunkItem[]>
}

// ── Query ───────────────────────────────────────────

export async function queryKnowledgeBase(
  kbId: string,
  query: string,
  topK = 5,
): Promise<QueryResult[]> {
  const res = await fetch(`${API_BASE}/query`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query, knowledge_base_id: kbId, top_k: topK }),
  })
  if (!res.ok) {
    const data = await res.json().catch(() => ({}))
    throw new Error(data.detail || `HTTP ${res.status}`)
  }
  const data = await res.json()
  return Array.isArray(data) ? data : Array.isArray(data.results) ? data.results : []
}

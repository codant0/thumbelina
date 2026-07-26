export interface KnowledgeBase {
  id: string
  name: string
  description?: string | null
  document_count?: number
  created_at: string
  updated_at: string
}

export interface RagDocument {
  id: string
  knowledge_base_id: string
  name: string
  doc_type: string
  chunk_count: number
  created_at: string
}

export interface QueryResult {
  content: string
  score: number
  metadata?: Record<string, unknown>
}

export interface ChunkItem {
  id: string
  document_id: string
  content: string
  metadata?: string
}

export interface BatchUploadResponse {
  uploaded: RagDocument[]
  skipped: string[]
  errors: Array<{ filename: string; error: string }>
}

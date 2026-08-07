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

export type UploadTaskStatus = 'pending' | 'running' | 'completed' | 'failed' | 'cancelled'
export type UploadTaskKind = 'file' | 'url' | 'batch'

export interface UploadTask {
  id: string
  kb_id: string
  kind: UploadTaskKind
  label: string
  status: UploadTaskStatus
  stage: string
  total_files: number
  done_files: number
  current_file: string
  chunk_done: number
  chunk_total: number
  error?: string | null
  result?: {
    uploaded: Array<{ id: string; name: string; chunk_count: number }>
    skipped: string[]
    errors: Array<{ filename: string; error: string }>
  } | null
  created_at: string
}

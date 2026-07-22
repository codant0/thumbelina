import { useState, useEffect, useCallback, useRef, type FormEvent } from 'react'
import {
  BookOpen, Plus, Trash2, Edit2, Check, X, Upload, Search, FileText,
} from 'lucide-react'
import { useTranslation } from '../../i18n'

interface KnowledgeBase {
  id: string
  name: string
  description?: string | null
  document_count?: number
  created_at: string
  updated_at: string
}

interface Document {
  id: string
  filename: string
  file_type: string
  chunk_count: number
  created_at: string
}

interface QueryResult {
  content: string
  score: number
  metadata?: Record<string, unknown>
}

export function KnowledgeBasePage() {
  const [kbs, setKbs] = useState<KnowledgeBase[]>([])
  const [selectedKb, setSelectedKb] = useState<KnowledgeBase | null>(null)
  const [documents, setDocuments] = useState<Document[]>([])
  const [loading, setLoading] = useState(true)
  const [editingKb, setEditingKb] = useState<KnowledgeBase | null>(null)
  const [creating, setCreating] = useState(false)
  const [kbForm, setKbForm] = useState({ name: '', description: '' })
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState<{ text: string; error: boolean } | null>(null)
  const [uploading, setUploading] = useState(false)
  const [queryText, setQueryText] = useState('')
  const [queryResults, setQueryResults] = useState<QueryResult[]>([])
  const [querying, setQuerying] = useState(false)
  const [deleteConfirm, setDeleteConfirm] = useState<string | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const { t } = useTranslation()

  const loadKbs = useCallback(async () => {
    try {
      const res = await fetch('/api/v1/rag/knowledge-bases')
      if (res.ok) {
        const data = await res.json()
        setKbs(Array.isArray(data) ? data : [])
      }
    } catch {
      // ignore
    } finally {
      setLoading(false)
    }
  }, [])

  const loadDocuments = useCallback(async (kbId: string) => {
    try {
      const res = await fetch(`/api/v1/rag/knowledge-bases/${kbId}/documents`)
      if (res.ok) {
        const data = await res.json()
        setDocuments(Array.isArray(data) ? data : [])
      }
    } catch {
      setDocuments([])
    }
  }, [])

  useEffect(() => {
    void loadKbs()
  }, [loadKbs])

  useEffect(() => {
    if (selectedKb) {
      void loadDocuments(selectedKb.id)
    } else {
      setDocuments([])
    }
  }, [selectedKb, loadDocuments])

  // ── CRUD Handlers ──────────────────────────────────────

  const handleCreate = async (e: FormEvent) => {
    e.preventDefault()
    setSaving(true)
    setMessage(null)
    try {
      const res = await fetch('/api/v1/rag/knowledge-bases', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: kbForm.name, description: kbForm.description || null }),
      })
      if (res.ok) {
        const kb: KnowledgeBase = await res.json()
        setKbs(prev => [...prev, kb])
        setSelectedKb(kb)
        setCreating(false)
        setKbForm({ name: '', description: '' })
        setMessage({ text: t('knowledgeBase.createSuccess'), error: false })
      } else {
        setMessage({ text: t('knowledgeBase.createFailed'), error: true })
      }
    } catch {
      setMessage({ text: t('knowledgeBase.createFailed'), error: true })
    } finally {
      setSaving(false)
    }
  }

  const handleUpdate = async (e: FormEvent) => {
    e.preventDefault()
    if (!editingKb) return
    setSaving(true)
    setMessage(null)
    try {
      const res = await fetch(`/api/v1/rag/knowledge-bases/${editingKb.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: kbForm.name, description: kbForm.description || null }),
      })
      if (res.ok) {
        const updated: KnowledgeBase = await res.json()
        setKbs(prev => prev.map(k => (k.id === updated.id ? updated : k)))
        if (selectedKb?.id === updated.id) setSelectedKb(updated)
        setEditingKb(null)
        setKbForm({ name: '', description: '' })
        setMessage({ text: t('knowledgeBase.updateSuccess'), error: false })
      } else {
        setMessage({ text: t('knowledgeBase.updateFailed'), error: true })
      }
    } catch {
      setMessage({ text: t('knowledgeBase.updateFailed'), error: true })
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async (kbId: string) => {
    setMessage(null)
    try {
      const res = await fetch(`/api/v1/rag/knowledge-bases/${kbId}`, { method: 'DELETE' })
      if (res.ok) {
        setKbs(prev => prev.filter(k => k.id !== kbId))
        if (selectedKb?.id === kbId) setSelectedKb(null)
        setMessage({ text: t('knowledgeBase.deleteSuccess'), error: false })
      } else {
        setMessage({ text: t('knowledgeBase.deleteFailed'), error: true })
      }
    } catch {
      setMessage({ text: t('knowledgeBase.deleteFailed'), error: true })
    }
    setDeleteConfirm(null)
  }

  // ── Document Handlers ──────────────────────────────────

  const handleUpload = async (files: FileList | null) => {
    if (!files || files.length === 0 || !selectedKb) return
    setUploading(true)
    setMessage(null)
    try {
      for (const file of Array.from(files)) {
        const formData = new FormData()
        formData.append('file', file)
        const res = await fetch(`/api/v1/rag/knowledge-bases/${selectedKb.id}/documents`, {
          method: 'POST',
          body: formData,
        })
        if (!res.ok) {
          setMessage({ text: t('knowledgeBase.uploadFailed'), error: true })
          return
        }
      }
      setMessage({ text: t('knowledgeBase.uploadSuccess'), error: false })
      await loadDocuments(selectedKb.id)
      // Refresh kb list to update doc count
      await loadKbs()
    } catch {
      setMessage({ text: t('knowledgeBase.uploadFailed'), error: true })
    } finally {
      setUploading(false)
      if (fileInputRef.current) fileInputRef.current.value = ''
    }
  }

  const handleDeleteDocument = async (docId: string) => {
    setMessage(null)
    try {
      const res = await fetch(`/api/v1/rag/documents/${docId}`, { method: 'DELETE' })
      if (res.ok) {
        setDocuments(prev => prev.filter(d => d.id !== docId))
        setMessage({ text: t('knowledgeBase.deleteSuccess'), error: false })
        await loadKbs()
      } else {
        setMessage({ text: t('knowledgeBase.deleteFailed'), error: true })
      }
    } catch {
      setMessage({ text: t('knowledgeBase.deleteFailed'), error: true })
    }
  }

  // ── Query Handler ──────────────────────────────────────

  const handleQuery = async () => {
    if (!queryText.trim() || !selectedKb) return
    setQuerying(true)
    setQueryResults([])
    try {
      const res = await fetch('/api/v1/rag/query', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          query: queryText.trim(),
          knowledge_base_id: selectedKb.id,
        }),
      })
      if (res.ok) {
        const data = await res.json()
        setQueryResults(Array.isArray(data) ? data : Array.isArray(data.results) ? data.results : [])
      }
    } catch {
      // ignore
    } finally {
      setQuerying(false)
    }
  }

  // ── Edit Start Helpers ─────────────────────────────────

  const startCreate = () => {
    setCreating(true)
    setEditingKb(null)
    setKbForm({ name: '', description: '' })
    setMessage(null)
  }

  const startEdit = (kb: KnowledgeBase) => {
    setEditingKb(kb)
    setCreating(false)
    setKbForm({ name: kb.name, description: kb.description || '' })
    setMessage(null)
  }

  const cancelForm = () => {
    setCreating(false)
    setEditingKb(null)
    setKbForm({ name: '', description: '' })
  }

  if (loading) {
    return (
      <div className="page-container" data-testid="knowledge-base-page">
        <div className="page-title"><BookOpen size={18} />{t('knowledgeBase.title')}</div>
        <div className="loading-state"><div className="spinner" /><span>{t('common.loading')}</span></div>
      </div>
    )
  }

  return (
    <div className="page-container" data-testid="knowledge-base-page">
      <div className="page-title"><BookOpen size={18} />{t('knowledgeBase.title')}</div>

      {message && (
        <p className={`settings-message ${message.error ? 'settings-message--error' : 'settings-message--success'}`}>
          {message.text}
        </p>
      )}

      <div className="kb-layout">
        {/* ── Left Panel: KB List ── */}
        <div className="kb-sidebar">
          <div className="kb-sidebar__header">
            <span className="kb-sidebar__title">{t('knowledgeBase.knowledgeBases')}</span>
            <button className="btn btn-primary btn-sm" onClick={startCreate} data-testid="kb-create-button">
              <Plus size={14} />{t('knowledgeBase.createKnowledgeBase')}
            </button>
          </div>

          {/* Create / Edit Form */}
          {(creating || editingKb) && (
            <form onSubmit={editingKb ? handleUpdate : handleCreate} className="kb-form">
              <div className="form-group">
                <label className="form-label">{t('knowledgeBase.name')}</label>
                <input
                  type="text"
                  className="form-input"
                  value={kbForm.name}
                  onChange={e => setKbForm({ ...kbForm, name: e.target.value })}
                  placeholder={t('knowledgeBase.namePlaceholder')}
                  required
                  autoFocus
                />
              </div>
              <div className="form-group">
                <label className="form-label">{t('knowledgeBase.description')}</label>
                <input
                  type="text"
                  className="form-input"
                  value={kbForm.description}
                  onChange={e => setKbForm({ ...kbForm, description: e.target.value })}
                  placeholder={t('knowledgeBase.descriptionPlaceholder')}
                />
              </div>
              <div className="settings-actions">
                <button type="submit" className="btn btn-primary btn-sm" disabled={saving}>
                  {saving ? t('common.saving') : <><Check size={14} />{t('common.save')}</>}
                </button>
                <button type="button" className="btn btn-ghost btn-sm" onClick={cancelForm}>
                  <X size={14} />{t('common.cancel')}
                </button>
              </div>
            </form>
          )}

          {/* KB List */}
          <div className="kb-list">
            {kbs.length === 0 ? (
              <p className="task-empty">{t('knowledgeBase.noKnowledgeBases')}</p>
            ) : (
              kbs.map(kb => (
                <div
                  key={kb.id}
                  className={`kb-item${selectedKb?.id === kb.id ? ' kb-item--selected' : ''}`}
                  data-testid={`kb-item-${kb.id}`}
                >
                  <button
                    className="kb-item__main"
                    onClick={() => setSelectedKb(kb)}
                  >
                    <BookOpen size={14} />
                    <div className="kb-item__info">
                      <span className="kb-item__name">{kb.name}</span>
                      {kb.description && <span className="kb-item__desc">{kb.description}</span>}
                    </div>
                    <span className="badge badge-neutral">{kb.document_count ?? 0}</span>
                  </button>
                  <div className="kb-item__actions">
                    <button className="btn btn-ghost btn-sm" onClick={() => startEdit(kb)} title={t('common.edit')}>
                      <Edit2 size={12} />
                    </button>
                    {deleteConfirm === kb.id ? (
                      <>
                        <button className="btn btn-danger btn-sm" onClick={() => void handleDelete(kb.id)}>
                          <Check size={12} />
                        </button>
                        <button className="btn btn-ghost btn-sm" onClick={() => setDeleteConfirm(null)}>
                          <X size={12} />
                        </button>
                      </>
                    ) : (
                      <button
                        className="btn btn-ghost btn-sm"
                        onClick={() => setDeleteConfirm(kb.id)}
                        title={t('common.delete')}
                      >
                        <Trash2 size={12} />
                      </button>
                    )}
                  </div>
                </div>
              ))
            )}
          </div>
        </div>

        {/* ── Right Panel: Detail ── */}
        <div className="kb-detail">
          {selectedKb ? (
            <>
              {/* Document List */}
              <div className="card">
                <div className="card-title card-title--between">
                  <span><FileText size={14} />{t('knowledgeBase.documents')}</span>
                  <button
                    className="btn btn-primary btn-sm"
                    onClick={() => fileInputRef.current?.click()}
                    disabled={uploading}
                    data-testid="kb-upload-button"
                  >
                    <Upload size={14} />
                    {uploading ? t('common.saving') : t('knowledgeBase.uploadDocument')}
                  </button>
                  <input
                    ref={fileInputRef}
                    type="file"
                    accept=".txt,.md"
                    multiple
                    hidden
                    onChange={e => void handleUpload(e.target.files)}
                  />
                </div>

                <p className="kb-detail__hint">{t('knowledgeBase.supportedFormats')}</p>

                {documents.length === 0 ? (
                  <p className="task-empty">{t('knowledgeBase.noDocuments')}</p>
                ) : (
                  <div className="kb-doc-table">
                    <div className="kb-doc-table__header">
                      <span>{t('knowledgeBase.documentName')}</span>
                      <span>{t('knowledgeBase.documentType')}</span>
                      <span>{t('knowledgeBase.chunkCount')}</span>
                      <span>{t('knowledgeBase.uploadTime')}</span>
                      <span />
                    </div>
                    {documents.map(doc => (
                      <div key={doc.id} className="kb-doc-table__row" data-testid={`kb-doc-${doc.id}`}>
                        <span className="kb-doc-table__name">{doc.filename}</span>
                        <span className="badge badge-neutral">{doc.file_type}</span>
                        <span>{doc.chunk_count}</span>
                        <span className="kb-doc-table__time">
                          {new Date(doc.created_at).toLocaleString()}
                        </span>
                        <button
                          className="btn btn-ghost btn-sm"
                          onClick={() => void handleDeleteDocument(doc.id)}
                          title={t('common.delete')}
                        >
                          <Trash2 size={12} />
                        </button>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {/* Query Test */}
              <div className="card">
                <div className="card-title">
                  <Search size={14} />{t('knowledgeBase.queryTest')}
                </div>
                <div className="kb-query">
                  <input
                    type="text"
                    className="form-input"
                    value={queryText}
                    onChange={e => setQueryText(e.target.value)}
                    placeholder={t('knowledgeBase.queryPlaceholder')}
                    onKeyDown={e => { if (e.key === 'Enter') void handleQuery() }}
                  />
                  <button
                    className="btn btn-primary btn-sm"
                    onClick={() => void handleQuery()}
                    disabled={querying || !queryText.trim()}
                    data-testid="kb-query-button"
                  >
                    {querying ? t('common.testing') : t('knowledgeBase.runQuery')}
                  </button>
                </div>

                {queryResults.length > 0 && (
                  <div className="kb-query-results">
                    <div className="card-title">{t('knowledgeBase.queryResults')}</div>
                    {queryResults.map((r, i) => (
                      <div key={i} className="kb-query-result">
                        <div className="kb-query-result__header">
                          <span className="badge badge-success">
                            {t('knowledgeBase.score')}: {typeof r.score === 'number' ? r.score.toFixed(3) : r.score}
                          </span>
                        </div>
                        <pre className="kb-query-result__content">{r.content}</pre>
                      </div>
                    ))}
                  </div>
                )}

                {queryResults.length === 0 && querying === false && queryText.trim() !== '' && (
                  <p className="task-empty">{t('knowledgeBase.noQueryResults')}</p>
                )}
              </div>
            </>
          ) : (
            <div className="kb-detail__empty">
              <BookOpen size={48} style={{ opacity: 0.3 }} />
              <p className="task-empty">{t('knowledgeBase.noKnowledgeBases')}</p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

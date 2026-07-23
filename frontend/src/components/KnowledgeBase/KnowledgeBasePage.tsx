import { useState, useEffect, useCallback, useRef, type FormEvent } from 'react'
import {
  BookOpen, Plus, Trash2, Edit2, Check, X, Upload, Search, FileText,
  UploadCloud, ChevronDown, ChevronRight, Database, Clock, RefreshCw,
} from 'lucide-react'
import { useTranslation } from '../../i18n'
import { Toast } from '../Settings/Toast'

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
  name: string
  doc_type: string
  chunk_count: number
  created_at: string
}

interface QueryResult {
  content: string
  score: number
  metadata?: Record<string, unknown>
}

interface ChunkItem {
  id: string
  document_id: string
  content: string
  metadata?: string
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
  const [toastMsg, setToastMsg] = useState('')
  const [toastError, setToastError] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [queryText, setQueryText] = useState('')
  const [queryResults, setQueryResults] = useState<QueryResult[]>([])
  const [querying, setQuerying] = useState(false)
  const [queryDuration, setQueryDuration] = useState<string | null>(null)
  const [deleteConfirm, setDeleteConfirm] = useState<string | null>(null)
  const [isDragOver, setIsDragOver] = useState(false)
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false)
  const [refreshingKbs, setRefreshingKbs] = useState(false)
  const [refreshingDocs, setRefreshingDocs] = useState(false)
  const [expandedDocId, setExpandedDocId] = useState<string | null>(null)
  const [docChunks, setDocChunks] = useState<ChunkItem[]>([])
  const [chunksLoading, setChunksLoading] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const dropzoneRef = useRef<HTMLDivElement>(null)
  const { t } = useTranslation()

  const totalChunks = documents.reduce((sum, d) => sum + d.chunk_count, 0)

  const showToast = useCallback((text: string, error = false) => {
    setToastMsg(text)
    setToastError(error)
  }, [])

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
        showToast(t('knowledgeBase.createSuccess'))
      } else {
        showToast(t('knowledgeBase.createFailed'), true)
      }
    } catch {
      showToast(t('knowledgeBase.createFailed'), true)
    } finally {
      setSaving(false)
    }
  }

  const handleUpdate = async (e: FormEvent) => {
    e.preventDefault()
    if (!editingKb) return
    setSaving(true)
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
        showToast(t('knowledgeBase.updateSuccess'))
      } else {
        showToast(t('knowledgeBase.updateFailed'), true)
      }
    } catch {
      showToast(t('knowledgeBase.updateFailed'), true)
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async (kbId: string) => {
    try {
      const res = await fetch(`/api/v1/rag/knowledge-bases/${kbId}`, { method: 'DELETE' })
      if (res.ok) {
        setKbs(prev => prev.filter(k => k.id !== kbId))
        if (selectedKb?.id === kbId) setSelectedKb(null)
        showToast(t('knowledgeBase.deleteSuccess'))
      } else {
        showToast(t('knowledgeBase.deleteFailed'), true)
      }
    } catch {
      showToast(t('knowledgeBase.deleteFailed'), true)
    }
    setDeleteConfirm(null)
  }

  // ── Document Handlers ──────────────────────────────────

  const handleUpload = useCallback(async (files: FileList | null) => {
    if (!files || files.length === 0 || !selectedKb) return
    setUploading(true)
    try {
      for (const file of Array.from(files)) {
        const formData = new FormData()
        formData.append('file', file)
        const res = await fetch(`/api/v1/rag/knowledge-bases/${selectedKb.id}/documents`, {
          method: 'POST',
          body: formData,
        })
        if (!res.ok) {
          showToast(t('knowledgeBase.uploadFailed'), true)
          return
        }
      }
      showToast(t('knowledgeBase.uploadSuccess'))
      await loadDocuments(selectedKb.id)
      await loadKbs()
    } catch {
      showToast(t('knowledgeBase.uploadFailed'), true)
    } finally {
      setUploading(false)
      if (fileInputRef.current) fileInputRef.current.value = ''
    }
  }, [selectedKb, showToast, t, loadDocuments, loadKbs])

  const handleDeleteDocument = async (docId: string) => {
    try {
      const res = await fetch(`/api/v1/rag/documents/${docId}`, { method: 'DELETE' })
      if (res.ok) {
        setDocuments(prev => prev.filter(d => d.id !== docId))
        showToast(t('knowledgeBase.deleteSuccess'))
        await loadKbs()
      } else {
        showToast(t('knowledgeBase.deleteFailed'), true)
      }
    } catch {
      showToast(t('knowledgeBase.deleteFailed'), true)
    }
  }

  const handleToggleChunks = useCallback(async (docId: string) => {
    if (expandedDocId === docId) {
      setExpandedDocId(null)
      setDocChunks([])
      return
    }
    setExpandedDocId(docId)
    setChunksLoading(true)
    setDocChunks([])
    try {
      const res = await fetch(`/api/v1/rag/documents/${docId}/chunks`)
      if (res.ok) {
        const data = await res.json()
        setDocChunks(Array.isArray(data) ? data : [])
      }
    } catch {
      setDocChunks([])
    } finally {
      setChunksLoading(false)
    }
  }, [expandedDocId])

  // ── Drag-and-drop handlers ─────────────────────────────

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    setIsDragOver(true)
  }, [])

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    if (dropzoneRef.current && !dropzoneRef.current.contains(e.relatedTarget as Node)) {
      setIsDragOver(false)
    }
  }, [])

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    setIsDragOver(false)
    if (e.dataTransfer.files.length > 0) {
      void handleUpload(e.dataTransfer.files)
    }
  }, [handleUpload])

  // ── Query Handler ──────────────────────────────────────

  const handleQuery = async () => {
    if (!queryText.trim() || !selectedKb) return
    setQuerying(true)
    setQueryResults([])
    setQueryDuration(null)
    const start = performance.now()
    try {
      const res = await fetch('/api/v1/rag/query', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          query: queryText.trim(),
          knowledge_base_id: selectedKb.id,
        }),
      })
      const elapsed = ((performance.now() - start) / 1000).toFixed(2)
      setQueryDuration(elapsed)
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
  }

  const startEdit = (kb: KnowledgeBase) => {
    setEditingKb(kb)
    setCreating(false)
    setKbForm({ name: kb.name, description: kb.description || '' })
  }

  const cancelForm = () => {
    setCreating(false)
    setEditingKb(null)
    setKbForm({ name: '', description: '' })
  }

  const selectKb = (kb: KnowledgeBase) => {
    setSelectedKb(kb)
    setMobileMenuOpen(false)
    setDeleteConfirm(null)
  }

  // ── Score rendering helper ─────────────────────────────

  const renderScore = (score: number) => {
    const level = score >= 0.8 ? 'high' : score >= 0.5 ? 'mid' : 'low'
    const pct = Math.min(score * 100, 100)
    return (
      <div className="kb-query-result__header">
        <div
          className="kb-score-bar"
          role="progressbar"
          aria-valuenow={score}
          aria-valuemin={0}
          aria-valuemax={1}
        >
          <div
            className={`kb-score-bar__fill kb-score-bar__fill--${level}`}
            style={{ width: `${pct}%` }}
          />
        </div>
        <span className={`kb-score-value kb-score-value--${level}`}>
          {score.toFixed(3)}
        </span>
      </div>
    )
  }

  // ── Format date helper ─────────────────────────────────

  const formatRelativeDate = (dateStr: string) => {
    const d = new Date(dateStr)
    const now = new Date()
    const diffMs = now.getTime() - d.getTime()
    const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24))
    if (diffDays === 0) return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    if (diffDays === 1) return '昨天'
    if (diffDays < 30) return `${diffDays}天前`
    return d.toLocaleDateString()
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

      <Toast message={toastMsg} isError={toastError} onClose={() => setToastMsg('')} />

      <div className="kb-layout">
        {/* ── Left Panel: KB List ── */}
        <div className="kb-sidebar">
          <div className="kb-sidebar__header">
            <span className="kb-sidebar__title">{t('knowledgeBase.knowledgeBases')}</span>
            <div style={{ display: 'flex', gap: 'var(--sp-1)' }}>
              <button
                className="btn btn-ghost btn-sm"
                onClick={async () => {
                  setRefreshingKbs(true)
                  await loadKbs()
                  setRefreshingKbs(false)
                }}
                title={t('common.refresh')}
                disabled={refreshingKbs}
              >
                <RefreshCw size={14} className={refreshingKbs ? 'spin' : ''} />
              </button>
              <button className="btn btn-primary btn-sm" onClick={startCreate} data-testid="kb-create-button">
                <Plus size={14} />{t('knowledgeBase.createKnowledgeBase')}
              </button>
            </div>
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
              <div className="kb-empty-state">
                <BookOpen size={32} className="kb-empty-state__icon" />
                <p className="kb-empty-state__title">{t('knowledgeBase.noKnowledgeBases')}</p>
              </div>
            ) : (
              kbs.map(kb => (
                <div
                  key={kb.id}
                  className={`kb-item${selectedKb?.id === kb.id ? ' kb-item--selected' : ''}`}
                  data-testid={`kb-item-${kb.id}`}
                >
                  <button
                    className="kb-item__main"
                    onClick={() => selectKb(kb)}
                  >
                    <BookOpen size={14} />
                    <div className="kb-item__info">
                      <span className="kb-item__name" title={kb.name}>{kb.name}</span>
                      {kb.description && (
                        <span className="kb-item__desc" title={kb.description}>{kb.description}</span>
                      )}
                    </div>
                    <span className="badge badge-neutral">
                      <FileText size={10} style={{ marginRight: 2 }} />
                      {kb.document_count ?? 0}
                    </span>
                  </button>
                  <div className="kb-item__actions">
                    <button className="btn btn-ghost btn-sm" onClick={() => startEdit(kb)} title={t('common.edit')}>
                      <Edit2 size={12} />
                    </button>
                    {deleteConfirm === kb.id ? (
                      <>
                        <button
                          className="btn btn-danger btn-sm"
                          onClick={() => void handleDelete(kb.id)}
                          aria-label={t('knowledgeBase.deleteConfirm')}
                        >
                          <Check size={12} />
                        </button>
                        <button
                          className="btn btn-ghost btn-sm"
                          onClick={() => setDeleteConfirm(null)}
                          aria-label={t('common.cancel')}
                        >
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
          {/* Mobile KB Selector */}
          <div className="kb-mobile-selector">
            <button
              className={`kb-mobile-selector__trigger${mobileMenuOpen ? ' kb-mobile-selector__trigger--open' : ''}`}
              onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
            >
              <span>{selectedKb ? selectedKb.name : t('knowledgeBase.mobileSelectKb')}</span>
              <ChevronDown size={16} />
            </button>
            {mobileMenuOpen && (
              <div className="kb-mobile-selector__overlay" onClick={() => setMobileMenuOpen(false)}>
                <div className="kb-mobile-selector__sheet" onClick={e => e.stopPropagation()}>
                  <div className="kb-mobile-selector__sheet-title">
                    {t('knowledgeBase.knowledgeBases')}
                  </div>
                  {kbs.map(kb => (
                    <button
                      key={kb.id}
                      className={`kb-mobile-selector__option${selectedKb?.id === kb.id ? ' kb-mobile-selector__option--selected' : ''}`}
                      onClick={() => selectKb(kb)}
                    >
                      <BookOpen size={14} />
                      <span>{kb.name}</span>
                    </button>
                  ))}
                  {kbs.length === 0 && (
                    <p className="kb-empty-state__title">{t('knowledgeBase.noKnowledgeBases')}</p>
                  )}
                </div>
              </div>
            )}
          </div>

          {selectedKb ? (
            <>
              {/* Overview Card */}
              <div className="kb-overview-card">
                <div className="kb-overview-card__header">
                  <div className="kb-overview-card__title">{selectedKb.name}</div>
                  <div className="kb-overview-card__actions">
                    <button
                      className="btn btn-ghost btn-sm"
                      onClick={() => startEdit(selectedKb)}
                      title={t('common.edit')}
                    >
                      <Edit2 size={14} />
                    </button>
                    {deleteConfirm === selectedKb.id ? (
                      <>
                        <button className="btn btn-danger btn-sm" onClick={() => void handleDelete(selectedKb.id)}>
                          <Check size={14} />
                        </button>
                        <button className="btn btn-ghost btn-sm" onClick={() => setDeleteConfirm(null)}>
                          <X size={14} />
                        </button>
                      </>
                    ) : (
                      <button
                        className="btn btn-ghost btn-sm"
                        onClick={() => setDeleteConfirm(selectedKb.id)}
                        title={t('common.delete')}
                      >
                        <Trash2 size={14} />
                      </button>
                    )}
                  </div>
                </div>
                {selectedKb.description && (
                  <p className="kb-overview-card__desc">{selectedKb.description}</p>
                )}
                <div className="kb-overview-card__stats">
                  <div className="kb-overview-card__stat">
                    <span className="kb-overview-card__stat-value">{selectedKb.document_count ?? 0}</span>
                    <span className="kb-overview-card__stat-label">{t('knowledgeBase.documents')}</span>
                  </div>
                  <div className="kb-overview-card__stat">
                    <span className="kb-overview-card__stat-value">{totalChunks}</span>
                    <span className="kb-overview-card__stat-label">{t('knowledgeBase.totalChunks')}</span>
                  </div>
                  <div className="kb-overview-card__stat">
                    <span className="kb-overview-card__stat-value" style={{ fontSize: 'var(--fs-sm)' }}>
                      <Clock size={14} style={{ verticalAlign: 'middle', marginRight: 4 }} />
                      {formatRelativeDate(selectedKb.created_at)}
                    </span>
                    <span className="kb-overview-card__stat-label">{t('knowledgeBase.createdAt')}</span>
                  </div>
                </div>
              </div>

              {/* Document List */}
              <div className="card">
                <div className="card-title card-title--between">
                  <span><FileText size={14} />{t('knowledgeBase.documents')}</span>
                  <div style={{ display: 'flex', gap: 'var(--sp-1)' }}>
                    <button
                      className="btn btn-ghost btn-sm"
                      onClick={async () => {
                        if (!selectedKb) return
                        setRefreshingDocs(true)
                        await loadDocuments(selectedKb.id)
                        setRefreshingDocs(false)
                      }}
                      title={t('common.refresh')}
                      disabled={refreshingDocs}
                    >
                      <RefreshCw size={14} className={refreshingDocs ? 'spin' : ''} />
                    </button>
                    <button
                      className="btn btn-primary btn-sm"
                      onClick={() => fileInputRef.current?.click()}
                      disabled={uploading}
                      data-testid="kb-upload-button"
                    >
                      <Upload size={14} />
                      {uploading ? t('common.saving') : t('knowledgeBase.uploadDocument')}
                    </button>
                  </div>
                  <input
                    ref={fileInputRef}
                    type="file"
                    accept=".txt,.md"
                    multiple
                    hidden
                    onChange={e => void handleUpload(e.target.files)}
                  />
                </div>

                {/* Drag-and-drop zone */}
                <div
                  ref={dropzoneRef}
                  className={`kb-doc-dropzone${isDragOver ? ' kb-doc-dropzone--active' : ''}`}
                  onDragOver={handleDragOver}
                  onDragEnter={handleDragOver}
                  onDragLeave={handleDragLeave}
                  onDrop={handleDrop}
                  onClick={() => fileInputRef.current?.click()}
                  role="region"
                  aria-label={t('knowledgeBase.dragDropHint')}
                >
                  <UploadCloud size={32} className="kb-doc-dropzone__icon" />
                  <p className="kb-doc-dropzone__text">
                    {isDragOver ? t('knowledgeBase.dropzoneActive') : t('knowledgeBase.dragDropHint')}
                  </p>
                  <p className="kb-doc-dropzone__formats">{t('knowledgeBase.supportedFormats')}</p>
                </div>

                {documents.length === 0 ? (
                  <div className="kb-empty-state">
                    <Database size={32} className="kb-empty-state__icon" />
                    <p className="kb-empty-state__title">{t('knowledgeBase.noDocuments')}</p>
                    <p className="kb-empty-state__desc">{t('knowledgeBase.supportedFormats')}</p>
                  </div>
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
                      <div key={doc.id} data-testid={`kb-doc-${doc.id}`}>
                        <div className="kb-doc-table__row">
                          <span className="kb-doc-table__name" title={doc.name}>
                            <FileText size={12} style={{ marginRight: 4, verticalAlign: 'middle', opacity: 0.5 }} />
                            {doc.name}
                          </span>
                          <span className="badge badge-neutral">{doc.doc_type}</span>
                          <span>{doc.chunk_count}</span>
                          <span className="kb-doc-table__time">
                            {new Date(doc.created_at).toLocaleString()}
                          </span>
                          <div className="kb-doc-table__actions">
                            <button
                              className="btn btn-ghost btn-sm"
                              onClick={() => void handleToggleChunks(doc.id)}
                              title={expandedDocId === doc.id ? t('knowledgeBase.hideChunks') : t('knowledgeBase.viewChunks')}
                            >
                              {expandedDocId === doc.id
                                ? <ChevronDown size={12} />
                                : <ChevronRight size={12} />}
                            </button>
                            <button
                              className="btn btn-ghost btn-sm"
                              onClick={() => void handleDeleteDocument(doc.id)}
                              title={t('common.delete')}
                            >
                              <Trash2 size={12} />
                            </button>
                          </div>
                        </div>
                        {expandedDocId === doc.id && (
                          <div className="kb-chunks-panel">
                            {chunksLoading ? (
                              <div className="kb-chunks-panel__loading">
                                <div className="spinner" />
                                <span>{t('knowledgeBase.loadingChunks')}</span>
                              </div>
                            ) : docChunks.length === 0 ? (
                              <div className="kb-chunks-panel__empty">
                                <span>{t('knowledgeBase.noChunks')}</span>
                              </div>
                            ) : (
                              <div className="kb-chunks-list">
                                {docChunks.map((chunk, idx) => (
                                  <div key={chunk.id} className="kb-chunk-item">
                                    <div className="kb-chunk-item__header">
                                      <span className="kb-chunk-item__index">#{idx + 1}</span>
                                      <span className="kb-chunk-item__id" title={chunk.id}>{chunk.id.slice(0, 8)}…</span>
                                    </div>
                                    <pre className="kb-chunk-item__content">{chunk.content}</pre>
                                  </div>
                                ))}
                              </div>
                            )}
                          </div>
                        )}
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
                    <div className="kb-query-stats">
                      <span>{t('knowledgeBase.queryResultCount', { count: String(queryResults.length) })}</span>
                      {queryDuration && (
                        <>
                          <span className="kb-query-stats__dot" />
                          <span>{t('knowledgeBase.queryDuration', { duration: queryDuration })}</span>
                        </>
                      )}
                    </div>
                    {queryResults.map((r, i) => (
                      <div key={i} className="kb-query-result">
                        {renderScore(typeof r.score === 'number' ? r.score : 0)}
                        <pre className="kb-query-result__content">{r.content}</pre>
                      </div>
                    ))}
                  </div>
                )}

                {queryResults.length === 0 && !querying && queryText.trim() !== '' && (
                  <div className="kb-empty-state" style={{ padding: 'var(--sp-6) var(--sp-4)' }}>
                    <Search size={24} className="kb-empty-state__icon" />
                    <p className="kb-empty-state__title">{t('knowledgeBase.noQueryResults')}</p>
                  </div>
                )}
              </div>
            </>
          ) : (
            <div className="kb-detail__empty">
              <BookOpen size={48} style={{ opacity: 0.2, color: 'var(--text-secondary)' }} />
              <p className="kb-empty-state__title">{t('knowledgeBase.noKnowledgeBases')}</p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

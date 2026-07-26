import { useState, useEffect, useCallback, useRef, type FormEvent } from 'react'
import {
  BookOpen, Plus, Trash2, Edit2, Check, X, Upload, Search, FileText,
  UploadCloud, ChevronDown, Database, Clock, RefreshCw, Copy, Link, FolderOpen,
} from 'lucide-react'
import { useTranslation } from '../../i18n'
import { Toast } from '../Settings/Toast'
import type { KnowledgeBase, RagDocument, QueryResult, ChunkItem } from '../../types/rag'
import * as ragApi from '../../api/rag'

type UploadMode = 'file' | 'url' | 'folder'

const SUPPORTED_EXTENSIONS = '.txt,.md,.pdf,.htm,.html'

export function KnowledgeBasePage() {
  const [kbs, setKbs] = useState<KnowledgeBase[]>([])
  const [selectedKb, setSelectedKb] = useState<KnowledgeBase | null>(null)
  const [documents, setDocuments] = useState<RagDocument[]>([])
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
  const [uploadMode, setUploadMode] = useState<UploadMode>('file')
  const [urlInput, setUrlInput] = useState('')
  const [urlUploading, setUrlUploading] = useState(false)
  const [urlError, setUrlError] = useState('')
  const [folderFiles, setFolderFiles] = useState<File[]>([])
  const [folderFiltered, setFolderFiltered] = useState(0)
  const [batchUploading, setBatchUploading] = useState(false)
  const [batchProgress, setBatchProgress] = useState<{ done: number; total: number } | null>(null)
  const [batchSummary, setBatchSummary] = useState<{
    uploaded: number; skipped: number; errors: number
  } | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const folderInputRef = useRef<HTMLInputElement>(null)
  const dropzoneRef = useRef<HTMLDivElement>(null)
  const { t } = useTranslation()

  const totalChunks = documents.reduce((sum, d) => sum + d.chunk_count, 0)

  const showToast = useCallback((text: string, error = false) => {
    setToastMsg(text)
    setToastError(error)
  }, [])

  const loadKbs = useCallback(async () => {
    try {
      const data = await ragApi.listKnowledgeBases()
      setKbs(Array.isArray(data) ? data : [])
    } catch {
      // ignore
    } finally {
      setLoading(false)
    }
  }, [])

  const loadDocuments = useCallback(async (kbId: string) => {
    try {
      const data = await ragApi.listDocuments(kbId)
      setDocuments(Array.isArray(data) ? data : [])
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
      const kb = await ragApi.createKnowledgeBase(kbForm.name, kbForm.description)
      setKbs(prev => [...prev, kb])
      setSelectedKb(kb)
      setCreating(false)
      setKbForm({ name: '', description: '' })
      showToast(t('knowledgeBase.createSuccess'))
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
      const updated = await ragApi.updateKnowledgeBase(editingKb.id, {
        name: kbForm.name,
        description: kbForm.description || null,
      })
      setKbs(prev => prev.map(k => (k.id === updated.id ? updated : k)))
      if (selectedKb?.id === updated.id) setSelectedKb(updated)
      setEditingKb(null)
      setKbForm({ name: '', description: '' })
      showToast(t('knowledgeBase.updateSuccess'))
    } catch {
      showToast(t('knowledgeBase.updateFailed'), true)
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async (kbId: string) => {
    try {
      await ragApi.deleteKnowledgeBase(kbId)
      setKbs(prev => prev.filter(k => k.id !== kbId))
      if (selectedKb?.id === kbId) setSelectedKb(null)
      showToast(t('knowledgeBase.deleteSuccess'))
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
        try {
          await ragApi.uploadDocument(selectedKb.id, file)
        } catch (err) {
          const detail = err instanceof Error ? err.message : t('knowledgeBase.uploadFailed')
          showToast(detail, true)
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

  const handleUrlUpload = useCallback(async () => {
    if (!selectedKb || !urlInput.trim()) return
    const url = urlInput.trim()
    if (!url.startsWith('http://') && !url.startsWith('https://')) {
      setUrlError(t('knowledgeBase.urlInvalid'))
      return
    }
    setUrlError('')
    setUrlUploading(true)
    try {
      await ragApi.uploadDocumentByUrl(selectedKb.id, url)
      showToast(t('knowledgeBase.uploadSuccess'))
      setUrlInput('')
      await loadDocuments(selectedKb.id)
      await loadKbs()
    } catch (err) {
      const detail = err instanceof Error ? err.message : t('knowledgeBase.uploadFailed')
      showToast(detail, true)
    } finally {
      setUrlUploading(false)
    }
  }, [selectedKb, urlInput, showToast, t, loadDocuments, loadKbs])

  const handleFolderSelect = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files
    if (!files || files.length === 0) {
      setFolderFiles([])
      setFolderFiltered(0)
      return
    }
    const allFiles = Array.from(files)
    const supportedExts = ['.txt', '.md', '.pdf', '.htm', '.html']
    const valid = allFiles.filter(f => {
      const ext = '.' + f.name.split('.').pop()?.toLowerCase()
      return supportedExts.includes(ext)
    })
    setFolderFiles(valid)
    setFolderFiltered(allFiles.length - valid.length)
    setBatchSummary(null)
  }, [])

  const handleFolderUpload = useCallback(async () => {
    if (!selectedKb || folderFiles.length === 0) return
    setBatchUploading(true)
    setBatchSummary(null)
    setBatchProgress({ done: 0, total: folderFiles.length })
    try {
      const result = await ragApi.uploadDocumentsBatch(selectedKb.id, folderFiles)
      setBatchSummary({
        uploaded: result.uploaded.length,
        skipped: result.skipped.length,
        errors: result.errors.length,
      })
      setBatchProgress({ done: folderFiles.length, total: folderFiles.length })
      await loadDocuments(selectedKb.id)
      await loadKbs()
    } catch (err) {
      const detail = err instanceof Error ? err.message : t('knowledgeBase.uploadFailed')
      showToast(detail, true)
    } finally {
      setBatchUploading(false)
    }
  }, [selectedKb, folderFiles, showToast, t, loadDocuments, loadKbs])

  const handleDeleteDocument = async (docId: string) => {
    try {
      await ragApi.deleteDocument(docId)
      setDocuments(prev => prev.filter(d => d.id !== docId))
      showToast(t('knowledgeBase.deleteSuccess'))
      await loadKbs()
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
      const data = await ragApi.listDocumentChunks(docId)
      setDocChunks(Array.isArray(data) ? data : [])
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
      const results = await ragApi.queryKnowledgeBase(selectedKb.id, queryText.trim())
      const elapsed = ((performance.now() - start) / 1000).toFixed(2)
      setQueryDuration(elapsed)
      setQueryResults(results)
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
    // Reset upload state when switching KB
    setUploadMode('file')
    setUrlInput('')
    setUrlError('')
    setFolderFiles([])
    setFolderFiltered(0)
    setBatchSummary(null)
    setBatchProgress(null)
  }

  // ── Copy to clipboard helper ───────────────────────────

  const copyToClipboard = useCallback(async (text: string) => {
    try {
      await navigator.clipboard.writeText(text)
      showToast(t('knowledgeBase.copiedToClipboard'))
    } catch {
      // Fallback for older browsers
      const ta = document.createElement('textarea')
      ta.value = text
      document.body.appendChild(ta)
      ta.select()
      document.execCommand('copy')
      document.body.removeChild(ta)
      showToast(t('knowledgeBase.copiedToClipboard'))
    }
  }, [showToast, t])

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
                  </div>
                </div>

                {/* Upload Mode Tabs */}
                <div className="kb-upload-tabs" role="tablist">
                  <button
                    className={`kb-upload-tab${uploadMode === 'file' ? ' kb-upload-tab--active' : ''}`}
                    onClick={() => setUploadMode('file')}
                    role="tab"
                    aria-selected={uploadMode === 'file'}
                  >
                    <Upload size={14} />{t('knowledgeBase.uploadModeFile')}
                  </button>
                  <button
                    className={`kb-upload-tab${uploadMode === 'url' ? ' kb-upload-tab--active' : ''}`}
                    onClick={() => setUploadMode('url')}
                    role="tab"
                    aria-selected={uploadMode === 'url'}
                  >
                    <Link size={14} />{t('knowledgeBase.uploadModeUrl')}
                  </button>
                  <button
                    className={`kb-upload-tab${uploadMode === 'folder' ? ' kb-upload-tab--active' : ''}`}
                    onClick={() => setUploadMode('folder')}
                    role="tab"
                    aria-selected={uploadMode === 'folder'}
                  >
                    <FolderOpen size={14} />{t('knowledgeBase.uploadModeFolder')}
                  </button>
                </div>

                {/* File Upload Panel */}
                {uploadMode === 'file' && (
                  <>
                    <button
                      className="btn btn-primary btn-sm"
                      onClick={() => fileInputRef.current?.click()}
                      disabled={uploading}
                      data-testid="kb-upload-button"
                      style={{ marginBottom: 'var(--sp-2)' }}
                    >
                      <Upload size={14} />
                      {uploading ? t('common.saving') : t('knowledgeBase.uploadDocument')}
                    </button>
                    <input
                      ref={fileInputRef}
                      type="file"
                      accept={SUPPORTED_EXTENSIONS}
                      multiple
                      hidden
                      onChange={e => void handleUpload(e.target.files)}
                    />

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
                  </>
                )}

                {/* URL Upload Panel */}
                {uploadMode === 'url' && (
                  <div className={`kb-url-upload${urlError ? ' kb-url-upload--invalid' : ''}`}>
                    <input
                      type="url"
                      className="form-input"
                      value={urlInput}
                      onChange={e => {
                        setUrlInput(e.target.value)
                        setUrlError('')
                      }}
                      placeholder={t('knowledgeBase.urlPlaceholder')}
                      onKeyDown={e => { if (e.key === 'Enter') void handleUrlUpload() }}
                      disabled={urlUploading}
                    />
                    <button
                      className="btn btn-primary btn-sm"
                      onClick={() => void handleUrlUpload()}
                      disabled={urlUploading || !urlInput.trim()}
                    >
                      {urlUploading ? t('common.saving') : t('knowledgeBase.urlFetch')}
                    </button>
                    {urlError && <p className="kb-url-upload__error">{urlError}</p>}
                  </div>
                )}

                {/* Folder Upload Panel */}
                {uploadMode === 'folder' && (
                  <div className="kb-folder-upload">
                    <input
                      ref={folderInputRef}
                      type="file"
                      // @ts-expect-error webkitdirectory is non-standard
                      webkitdirectory=""
                      directory=""
                      multiple
                      hidden
                      onChange={handleFolderSelect}
                    />
                    <button
                      className="btn btn-ghost btn-sm"
                      onClick={() => folderInputRef.current?.click()}
                      disabled={batchUploading}
                    >
                      <FolderOpen size={14} />{t('knowledgeBase.selectFolder')}
                    </button>
                    {folderFiles.length > 0 && (
                      <p className="kb-folder-upload__info">
                        <strong>{t('knowledgeBase.filesSelected', { count: String(folderFiles.length) })}</strong>
                        {folderFiltered > 0 && (
                          <span className="kb-folder-upload__filtered">
                            {' · '}{t('knowledgeBase.filesFiltered', { count: String(folderFiltered) })}
                          </span>
                        )}
                      </p>
                    )}
                    {folderFiles.length > 0 && !batchUploading && !batchSummary && (
                      <button
                        className="btn btn-primary btn-sm"
                        onClick={() => void handleFolderUpload()}
                      >
                        <Upload size={14} />
                        {t('knowledgeBase.uploadDocument')} ({folderFiles.length})
                      </button>
                    )}
                  </div>
                )}

                {/* Batch Progress */}
                {batchUploading && batchProgress && (
                  <div className="kb-batch-progress">
                    <div className="kb-batch-progress__bar">
                      <div
                        className="kb-batch-progress__fill"
                        style={{ width: `${(batchProgress.done / batchProgress.total) * 100}%` }}
                      />
                    </div>
                    <span>
                      {t('knowledgeBase.batchUploading', {
                        done: String(batchProgress.done),
                        total: String(batchProgress.total),
                      })}
                    </span>
                  </div>
                )}

                {/* Batch Summary */}
                {batchSummary && (
                  <div className="kb-batch-summary kb-batch-summary--success">
                    <span className="kb-batch-summary__item">
                      <Check size={14} />
                      {t('knowledgeBase.batchComplete', {
                        uploaded: String(batchSummary.uploaded),
                        skipped: String(batchSummary.skipped),
                        errors: String(batchSummary.errors),
                      })}
                    </span>
                  </div>
                )}

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
                          <button
                            className={`kb-doc-table__chunk-btn${expandedDocId === doc.id ? ' kb-doc-table__chunk-btn--active' : ''}`}
                            onClick={() => void handleToggleChunks(doc.id)}
                            title={expandedDocId === doc.id ? t('knowledgeBase.hideChunks') : t('knowledgeBase.viewChunks')}
                            disabled={doc.chunk_count === 0}
                          >
                            {doc.chunk_count}
                          </button>
                          <span className="kb-doc-table__time">
                            {new Date(doc.created_at).toLocaleString()}
                          </span>
                          <div className="kb-doc-table__actions">
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
                              <>
                                <div className="kb-chunks-panel__stats">
                                  <span className="kb-chunks-panel__stat">
                                    {t('knowledgeBase.chunkTotal')}: <strong>{docChunks.length}</strong>
                                  </span>
                                  <span className="kb-chunks-panel__stat">
                                    {t('knowledgeBase.chunkTotalChars')}: <strong>
                                      {docChunks.reduce((sum, c) => sum + c.content.length, 0).toLocaleString()}
                                    </strong>
                                  </span>
                                </div>
                                <div className="kb-chunks-list">
                                  {docChunks.map((chunk, idx) => {
                                    let parsedMeta: Record<string, unknown> | null = null
                                    if (chunk.metadata) {
                                      try { parsedMeta = JSON.parse(chunk.metadata) } catch { /* ignore */ }
                                    }
                                    return (
                                      <div key={chunk.id} className="kb-chunk-item">
                                        <div className="kb-chunk-item__header">
                                          <span className="kb-chunk-item__index">#{idx + 1}</span>
                                          <span className="kb-chunk-item__chars">
                                            {chunk.content.length} {t('knowledgeBase.chunkChars')}
                                          </span>
                                          <span className="kb-chunk-item__id" title={chunk.id}>
                                            {chunk.id.slice(0, 8)}…
                                          </span>
                                          <button
                                            className="btn btn-ghost btn-sm kb-chunk-item__copy"
                                            onClick={() => void copyToClipboard(chunk.content)}
                                            title={t('knowledgeBase.copyContent')}
                                          >
                                            <Copy size={11} />
                                          </button>
                                        </div>
                                        {parsedMeta && Object.keys(parsedMeta).length > 0 && (
                                          <div className="kb-chunk-item__meta">
                                            {Object.entries(parsedMeta).map(([k, v]) => (
                                              <span key={k} className="kb-chunk-item__meta-tag">
                                                <span className="kb-chunk-item__meta-key">{k}:</span>
                                                <span className="kb-chunk-item__meta-val">{String(v)}</span>
                                              </span>
                                            ))}
                                          </div>
                                        )}
                                        <pre className="kb-chunk-item__content">{chunk.content}</pre>
                                      </div>
                                    )
                                  })}
                                </div>
                              </>
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

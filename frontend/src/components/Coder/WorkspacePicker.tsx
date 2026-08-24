import { useEffect, useRef, useState } from 'react'
import { useTranslation } from '../../i18n'
import { createConversation } from '../../api/conversations'
import { listDirs, type DirEntry, type DirListing } from '../../api/fs'

interface WorkspacePickerProps {
  onClose: () => void
  onCreated: (id: string) => void
  /** Existing coder workspaces, deduped, most recent first — click to fill in. */
  recentWorkspaces?: string[]
}

export function WorkspacePicker({ onClose, onCreated, recentWorkspaces }: WorkspacePickerProps) {
  const { t } = useTranslation()
  const browserRef = useRef<HTMLDivElement>(null)
  const [path, setPath] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [creating, setCreating] = useState(false)

  // Server-side directory tree: the browser never sees absolute paths
  // (native pickers expose only a name), and in NAS deployments the agent
  // works on the *server's* filesystem anyway — so we browse that.
  const [currentPath, setCurrentPath] = useState<string | null>(null)
  const [parentPath, setParentPath] = useState<string | null>(null)
  const [entries, setEntries] = useState<DirEntry[] | null>(null)
  const [truncated, setTruncated] = useState(false)
  const [browsing, setBrowsing] = useState(true)
  const [browseError, setBrowseError] = useState<string | null>(null)

  const applyListing = (dir: string | null, listing: DirListing) => {
    setCurrentPath(listing.path)
    setParentPath(listing.parent)
    setEntries(listing.children)
    setTruncated(listing.truncated)
    if (dir !== null) setPath(listing.path ?? '')
  }

  const formatError = (err: unknown) => (err instanceof Error ? err.message : String(err))

  const navigate = async (dir: string | null) => {
    setBrowsing(true)
    setBrowseError(null)
    try {
      applyListing(dir, await listDirs(dir ?? undefined))
    } catch (err) {
      // Browsing is a convenience — a failed listing never blocks manual entry.
      setBrowseError(formatError(err))
    } finally {
      setBrowsing(false)
    }
  }

  useEffect(() => {
    // Initial root listing without synchronous state updates in the effect.
    let cancelled = false
    listDirs()
      .then(listing => { if (!cancelled) applyListing(null, listing) })
      .catch(err => { if (!cancelled) setBrowseError(formatError(err)) })
      .finally(() => { if (!cancelled) setBrowsing(false) })
    return () => { cancelled = true }
  }, [])

  // 进入新目录时回到列表顶部，避免残留滚动位置导致内容看起来缺失
  useEffect(() => {
    if (browserRef.current) browserRef.current.scrollTop = 0
  }, [currentPath])

  const createFromPath = async (workspacePath: string) => {
    setCreating(true)
    setError(null)
    try {
      const conv = await createConversation({ mode: 'coder', workspace: workspacePath })
      onCreated(conv.id)
    } catch (err) {
      setError(err instanceof Error ? err.message : t('coder.createFailed'))
      setCreating(false)
    }
  }

  const submit = async () => {
    const trimmed = path.trim()
    if (!trimmed) {
      setError(t('coder.workspaceRequired'))
      return
    }
    await createFromPath(trimmed)
  }

  return (
    <div className="modal-overlay" data-testid="workspace-picker" onClick={onClose}>
      <div className="modal workspace-picker" onClick={e => e.stopPropagation()}>
        <div className="workspace-picker__chrome">
          <span className="workspace-picker__dot workspace-picker__dot--error" aria-hidden="true" />
          <span className="workspace-picker__dot workspace-picker__dot--warning" aria-hidden="true" />
          <span className="workspace-picker__dot workspace-picker__dot--success" aria-hidden="true" />
          <span className="workspace-picker__title">{t('coder.pickerTitle')}</span>
        </div>
        <div className="workspace-picker__body">
          <div className="workspace-picker__row">
            <input
              data-testid="workspace-path-input"
              className="workspace-picker__input"
              type="text"
              value={path}
              onChange={e => setPath(e.target.value)}
              placeholder={t('coder.workspacePlaceholder')}
              onKeyDown={e => { if (e.key === 'Enter') submit() }}
              autoFocus
            />
          </div>
          <div className="workspace-picker__pathbar" data-testid="workspace-pathbar">
            {currentPath ?? t('coder.selectDrive')}
          </div>
          <div className="workspace-picker__browser" ref={browserRef} data-testid="workspace-browser">
            {browseError ? (
              <div className="workspace-picker__error" data-testid="workspace-browse-error" role="status">
                {t('coder.browseFailed')}: {browseError}
              </div>
            ) : browsing && entries === null ? (
              <div className="workspace-picker__empty">{t('common.loading')}</div>
            ) : parentPath && (
              <button
                type="button"
                className="workspace-picker__dir-row workspace-picker__dir-row--up"
                data-testid="workspace-up"
                onClick={() => navigate(parentPath)}
              >
                ↰ {t('coder.upLevel')}
              </button>
            )}
            {!browseError && entries !== null && entries.length === 0 && (
              <div className="workspace-picker__empty" data-testid="workspace-empty">
                {t('coder.emptyDirectory')}
              </div>
            )}
            {!browseError &&
              (entries ?? []).map(entry => (
                <button
                  key={entry.path}
                  type="button"
                  className="workspace-picker__dir-row"
                  data-testid="workspace-dir-row"
                  onClick={() => navigate(entry.path)}
                  title={entry.name}
                >
                  {entry.name}
                </button>
              ))}
            {!browseError && truncated && (
              <div className="workspace-picker__truncated" data-testid="workspace-truncated">
                {t('coder.listTruncated')}
              </div>
            )}
          </div>
          {recentWorkspaces && recentWorkspaces.length > 0 && (
            <div className="workspace-picker__recent">
              <span>{t('coder.recentWorkspaces')}:</span>
              {recentWorkspaces.map(ws => (
                <button
                  key={ws}
                  type="button"
                  className="picker-chip"
                  data-testid="workspace-recent-chip"
                  onClick={() => setPath(ws)}
                >
                  {ws}
                </button>
              ))}
            </div>
          )}
          {error && (
            <div className="workspace-picker__error" data-testid="workspace-picker-error" role="status">{error}</div>
          )}
        </div>
        <div className="modal-actions">
          <button onClick={onClose}>{t('common.cancel')}</button>
          <button data-testid="workspace-confirm" onClick={submit} disabled={creating}>
            {creating ? t('common.saving') : t('coder.confirmCreate')}
          </button>
        </div>
      </div>
    </div>
  )
}
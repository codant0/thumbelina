import { useMemo, useRef, useState } from 'react'
import { useTranslation } from '../../i18n'
import { createConversation } from '../../api/conversations'

interface DirectoryHandle { name: string }

interface WorkspacePickerProps {
  onClose: () => void
  onCreated: (id: string) => void
  /** Existing coder workspaces, deduped, most recent first — click to fill in. */
  recentWorkspaces?: string[]
}

// The browser only exposes the directory *name* (never the absolute path) —
// but the agent needs the absolute path. We bridge the gap by remembering a
// name → path mapping on this machine (server and browser share the disk),
// so picking a known directory submits immediately.
const STORAGE_KEY = 'thumbelina-coder-workspace-paths'

function loadWorkspacePaths(): Record<string, string> {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    return raw ? JSON.parse(raw) as Record<string, string> : {}
  } catch {
    return {}
  }
}

function saveWorkspacePaths(map: Record<string, string>) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(map))
  } catch {
    // storage unavailable — the mapping simply won't persist
  }
}

const workspaceName = (ws: string) => ws.split(/[\\/]/).filter(Boolean).pop() || ws

export function WorkspacePicker({ onClose, onCreated, recentWorkspaces }: WorkspacePickerProps) {
  const { t } = useTranslation()
  const [path, setPath] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [creating, setCreating] = useState(false)
  const [dirName, setDirName] = useState<string | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  // File System Access API is Chromium-only; without it (Firefox/Safari/
  // non-secure context) the picker button is hidden and the path is typed.
  const supportsPicker = useMemo(
    () => typeof (window as unknown as { showDirectoryPicker?: unknown }).showDirectoryPicker === 'function',
    [],
  )

  const createFromPath = async (workspacePath: string) => {
    setCreating(true)
    setError(null)
    try {
      const conv = await createConversation({ mode: 'coder', workspace: workspacePath })
      // Remember name → resolved path so a later directory pick submits directly.
      if (conv.workspace) {
        const paths = loadWorkspacePaths()
        saveWorkspacePaths({ ...paths, [workspaceName(conv.workspace)]: conv.workspace })
      }
      onCreated(conv.id)
    } catch (err) {
      setError(err instanceof Error ? err.message : t('coder.createFailed'))
      setCreating(false)
    }
  }

  const pickDirectory = async () => {
    try {
      const picker = (window as unknown as {
        showDirectoryPicker?: () => Promise<DirectoryHandle>
      }).showDirectoryPicker
      const handle = picker ? await picker.call(window) : null
      if (!handle) return
      setDirName(handle.name)
      setError(null)
      const known = loadWorkspacePaths()[handle.name]
      if (known) {
        // Known directory — create the session right away and return to chat.
        await createFromPath(known)
      } else {
        // First time: prefill the name and ask for the full path once.
        setPath(handle.name)
        inputRef.current?.focus()
        inputRef.current?.select()
      }
    } catch {
      // user cancelled or the API is unavailable — ignore
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
              ref={inputRef}
              data-testid="workspace-path-input"
              className="workspace-picker__input"
              type="text"
              value={path}
              onChange={e => setPath(e.target.value)}
              placeholder={t('coder.workspacePlaceholder')}
              onKeyDown={e => { if (e.key === 'Enter') submit() }}
              autoFocus
            />
            {supportsPicker && (
              <button data-testid="workspace-pick-native" onClick={pickDirectory} type="button" className="btn btn-ghost">
                {t('coder.pickDirButton')}
              </button>
            )}
          </div>
          {!supportsPicker && (
            <div className="workspace-picker__unavailable" data-testid="workspace-dir-unavailable">
              {t('coder.dirUnavailable')}
            </div>
          )}
          {dirName && (
            <div className="workspace-picker__hint" data-testid="workspace-dir-hint">
              {t('coder.dirConfirmed')}: {dirName}
              {path === dirName && ` — ${t('coder.dirFirstUse')}`}
            </div>
          )}
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
import { useMemo, useState } from 'react'
import { useTranslation } from '../../i18n'
import { createConversation } from '../../api/conversations'

interface DirectoryHandle { name: string }

interface WorkspacePickerProps {
  onClose: () => void
  onCreated: (id: string) => void
  /** Existing coder workspaces, deduped, most recent first — click to fill in. */
  recentWorkspaces?: string[]
}

export function WorkspacePicker({ onClose, onCreated, recentWorkspaces }: WorkspacePickerProps) {
  const { t } = useTranslation()
  const [path, setPath] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [creating, setCreating] = useState(false)
  const [dirName, setDirName] = useState<string | null>(null)

  // File System Access API is Chromium-only; without it (Firefox/Safari/
  // non-secure context) the picker button is hidden and the path is typed.
  const supportsPicker = useMemo(
    () => typeof (window as unknown as { showDirectoryPicker?: unknown }).showDirectoryPicker === 'function',
    [],
  )

  const pickDirectory = async () => {
    try {
      const picker = (window as unknown as {
        showDirectoryPicker?: () => Promise<DirectoryHandle>
      }).showDirectoryPicker
      const handle = picker ? await picker.call(window) : null
      if (handle) {
        setDirName(handle.name)
        setError(null)
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
    setCreating(true)
    setError(null)
    try {
      const conv = await createConversation({ mode: 'coder', workspace: trimmed })
      onCreated(conv.id)
    } catch (err) {
      setError(err instanceof Error ? err.message : t('coder.createFailed'))
    } finally {
      setCreating(false)
    }
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
            <div className="workspace-picker__hint">
              {t('coder.dirConfirmed')}: {dirName}
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
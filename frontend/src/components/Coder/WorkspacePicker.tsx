import { useState } from 'react'
import { useTranslation } from '../../i18n'
import { createConversation } from '../../api/conversations'

interface DirectoryHandle { name: string }

interface WorkspacePickerProps {
  onClose: () => void
  onCreated: (id: string) => void
}

export function WorkspacePicker({ onClose, onCreated }: WorkspacePickerProps) {
  const { t } = useTranslation()
  const [path, setPath] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [creating, setCreating] = useState(false)
  const [dirName, setDirName] = useState<string | null>(null)

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
      <div className="modal" onClick={e => e.stopPropagation()}>
        <h3>{t('coder.pickWorkspaceTitle')}</h3>
        <input
          data-testid="workspace-path-input"
          type="text"
          value={path}
          onChange={e => setPath(e.target.value)}
          placeholder={t('coder.workspacePlaceholder')}
          onKeyDown={e => { if (e.key === 'Enter') submit() }}
        />
        {dirName && (
          <div className="workspace-picker__hint">
            {t('coder.dirPickerHint')}: {dirName}
          </div>
        )}
        <button data-testid="workspace-pick-native" onClick={pickDirectory} type="button">
          {t('coder.pickDirButton')}
        </button>
        {error && (
          <div className="workspace-picker__error" data-testid="workspace-picker-error">{error}</div>
        )}
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
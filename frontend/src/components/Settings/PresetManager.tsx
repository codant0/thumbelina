import { useEffect, useState, useCallback } from 'react'
import type { LLMPreset, PresetFormData } from '../../api/llmConfig'
import {
  fetchPresets,
  createPreset,
  updatePreset,
  deletePreset,
  activatePreset,
} from '../../api/llmConfig'
import { PresetForm } from './PresetForm'
import { Plus, Check, Pencil, Trash2, Loader2, BookMarked } from 'lucide-react'
import { useTranslation } from '../../i18n'

interface PresetManagerProps {
  onMessage: (message: string, isError: boolean) => void
}

export function PresetManager({ onMessage }: PresetManagerProps) {
  const [presets, setPresets] = useState<LLMPreset[]>([])
  const [loading, setLoading] = useState(true)
  const [showForm, setShowForm] = useState(false)
  const [editing, setEditing] = useState<LLMPreset | null>(null)
  const [activatingId, setActivatingId] = useState<string | null>(null)
  const [deletingId, setDeletingId] = useState<string | null>(null)
  const { t } = useTranslation()

  const load = useCallback(async () => {
    try {
      const data = await fetchPresets()
      setPresets(Array.isArray(data) ? data : [])
    } catch (err) {
      onMessage(err instanceof Error ? err.message : t('preset.failedToLoad'), true)
      setPresets([])
    } finally {
      setLoading(false)
    }
  }, [onMessage])

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    load()
  }, [load])

  const handleCreate = async (data: PresetFormData) => {
    try {
      await createPreset(data)
      setShowForm(false)
      onMessage(t('preset.created'), false)
      await load()
    } catch (err) {
      onMessage(err instanceof Error ? err.message : t('preset.createFailed'), true)
    }
  }

  const handleUpdate = async (data: PresetFormData) => {
    if (!editing) return
    try {
      await updatePreset(editing.id, data)
      setEditing(null)
      onMessage(t('preset.updated'), false)
      await load()
    } catch (err) {
      onMessage(err instanceof Error ? err.message : t('preset.updateFailed'), true)
    }
  }

  const handleDelete = async (id: string) => {
    setDeletingId(id)
    try {
      await deletePreset(id)
      onMessage(t('preset.deleted'), false)
      await load()
    } catch (err) {
      onMessage(err instanceof Error ? err.message : t('preset.deleteFailed'), true)
    } finally {
      setDeletingId(null)
    }
  }

  const handleActivate = async (id: string) => {
    setActivatingId(id)
    try {
      const result = await activatePreset(id)
      setPresets(prev => prev.map(p => ({
        ...p,
        is_active: p.id === id,
      })))
      onMessage(t('preset.activated', { name: result.preset_name }), false)
    } catch (err) {
      onMessage(err instanceof Error ? err.message : t('preset.activateFailed'), true)
    } finally {
      setActivatingId(null)
    }
  }

  if (loading) return <p>{t('common.loading')}</p>

  return (
    <div className="card" data-testid="preset-manager">
      <div className="card-title"><BookMarked size={14} />{t('preset.title')}</div>
      <button
        className="btn btn-primary"
        data-testid="add-preset-button"
        onClick={() => setShowForm(true)}
      >
        <Plus size={16} />
        {t('preset.add')}
      </button>
      {showForm && (
        <PresetForm onSubmit={handleCreate} onCancel={() => setShowForm(false)} />
      )}
      {editing && (
        <PresetForm initialValues={editing} onSubmit={handleUpdate} onCancel={() => setEditing(null)} />
      )}
      {presets.length === 0 ? (
        <p className="settings-empty-hint">{t('preset.noPresets')}</p>
      ) : (
        <div className="preset-list">
          {presets.map(preset => (
            <div
              key={preset.id}
              className={`card preset-card${preset.is_active ? ' preset-card--active' : ''}`}
              data-testid={`preset-row-${preset.id}`}
            >
              <div className="preset-card__header">
                <span className="preset-card__name">{preset.name}</span>
                <span className="preset-card__badges">
                  <span className="badge badge-neutral">{preset.provider}</span>
                  {preset.is_active && <span className="badge badge-success">{t('common.active')}</span>}
                </span>
              </div>
              <div className="preset-card__body">
                <span className="preset-card__url" title={preset.base_url}>{preset.base_url}</span>
                <span className="preset-card__model">{preset.model}</span>
                <span className="preset-card__date">{new Date(preset.updated_at).toLocaleString()}</span>
              </div>
              <div className="preset-card__actions">
                {!preset.is_active && (
                  <button
                    className="btn btn-ghost btn-sm"
                    data-testid={`activate-preset-${preset.id}`}
                    onClick={() => handleActivate(preset.id)}
                    disabled={activatingId === preset.id}
                  >
                    {activatingId === preset.id ? <Loader2 size={14} className="spin" /> : <Check size={14} />}
                    {activatingId === preset.id ? t('common.activating') : t('common.activate')}
                  </button>
                )}
                <button
                  className="btn btn-ghost btn-sm"
                  data-testid={`edit-preset-${preset.id}`}
                  onClick={() => setEditing(preset)}
                >
                  <Pencil size={14} />
                  {t('common.edit')}
                </button>
                <button
                  className="btn btn-danger btn-sm"
                  data-testid={`delete-preset-${preset.id}`}
                  onClick={() => handleDelete(preset.id)}
                  disabled={deletingId === preset.id}
                >
                  {deletingId === preset.id ? <Loader2 size={14} className="spin" /> : <Trash2 size={14} />}
                  {deletingId === preset.id ? t('common.delete') : t('common.delete')}
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

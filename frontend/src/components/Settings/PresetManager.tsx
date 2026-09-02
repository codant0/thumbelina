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
import { PresetList } from './PresetList'
import { PresetDetailModal } from './PresetDetailModal'
import { Modal } from './Modal'
import { Plus, BookMarked } from 'lucide-react'
import { useTranslation } from '../../i18n'

interface PresetManagerProps {
  onMessage: (message: string, isError: boolean) => void
}

export function PresetManager({ onMessage }: PresetManagerProps) {
  const [presets, setPresets] = useState<LLMPreset[]>([])
  const [loading, setLoading] = useState(true)
  const [showForm, setShowForm] = useState(false)
  const [editing, setEditing] = useState<LLMPreset | null>(null)
  const [inspecting, setInspecting] = useState<LLMPreset | null>(null)
  const [activatingFromDetail, setActivatingFromDetail] = useState<string | null>(null)
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
    try {
      await deletePreset(id)
      onMessage(t('preset.deleted'), false)
      await load()
    } catch (err) {
      onMessage(err instanceof Error ? err.message : t('preset.deleteFailed'), true)
    }
  }

  const handleActivate = async (id: string) => {
    setActivatingFromDetail(id)
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
      setActivatingFromDetail(null)
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
        <Modal title={t('preset.add')} onClose={() => setShowForm(false)}>
          <PresetForm onSubmit={handleCreate} onCancel={() => setShowForm(false)} />
        </Modal>
      )}
      {editing && (
        <Modal title={t('preset.update')} onClose={() => setEditing(null)}>
          <PresetForm initialValues={editing} onSubmit={handleUpdate} onCancel={() => setEditing(null)} />
        </Modal>
      )}
      {inspecting && !editing && !showForm && (
        <PresetDetailModal
          preset={inspecting}
          activating={activatingFromDetail === inspecting.id}
          onClose={() => setInspecting(null)}
          onEdit={p => {
            setInspecting(null)
            setEditing(p)
          }}
          onDelete={async id => {
            await handleDelete(id)
            setInspecting(null)
          }}
          onActivate={handleActivate}
        />
      )}
      {presets.length === 0 && !showForm ? (
        <p className="settings-empty-hint">{t('preset.noPresets')}</p>
      ) : (
        <PresetList
          presets={presets}
          onInspect={id => setInspecting(presets.find(p => p.id === id) ?? null)}
        />
      )}
    </div>
  )
}
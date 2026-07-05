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

  const load = useCallback(async () => {
    try {
      const data = await fetchPresets()
      setPresets(Array.isArray(data) ? data : [])
    } catch (err) {
      onMessage(err instanceof Error ? err.message : 'Failed to load presets', true)
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
      onMessage('Preset created', false)
      await load()
    } catch (err) {
      onMessage(err instanceof Error ? err.message : 'Failed to create preset', true)
    }
  }

  const handleUpdate = async (data: PresetFormData) => {
    if (!editing) return
    try {
      await updatePreset(editing.id, data)
      setEditing(null)
      onMessage('Preset updated', false)
      await load()
    } catch (err) {
      onMessage(err instanceof Error ? err.message : 'Failed to update preset', true)
    }
  }

  const handleDelete = async (id: string) => {
    setDeletingId(id)
    try {
      await deletePreset(id)
      onMessage('Preset deleted', false)
      await load()
    } catch (err) {
      onMessage(err instanceof Error ? err.message : 'Failed to delete preset', true)
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
      onMessage(`Activated preset: ${result.preset_name}`, false)
    } catch (err) {
      onMessage(err instanceof Error ? err.message : 'Failed to activate preset', true)
    } finally {
      setActivatingId(null)
    }
  }

  if (loading) return <p>Loading presets…</p>

  return (
    <div className="card" data-testid="preset-manager">
      <div className="card-title">LLM Presets</div>
      <button
        className="btn btn-primary"
        data-testid="add-preset-button"
        onClick={() => setShowForm(true)}
      >
        Add Preset
      </button>
      {showForm && (
        <PresetForm onSubmit={handleCreate} onCancel={() => setShowForm(false)} />
      )}
      {editing && (
        <PresetForm initialValues={editing} onSubmit={handleUpdate} onCancel={() => setEditing(null)} />
      )}
      {presets.length === 0 ? (
        <p style={{ color: 'var(--text-secondary)', fontSize: 12, marginTop: 12 }}>
          No presets yet. Create your first preset to quickly switch between LLM providers.
        </p>
      ) : (
        <div className="preset-list" style={{ marginTop: 12 }}>
          {presets.map(preset => (
            <div
              key={preset.id}
              className="card"
              data-testid={`preset-row-${preset.id}`}
              style={{
                borderColor: preset.is_active ? 'var(--success)' : undefined,
              }}
            >
              <div className="endpoint-row-header">
                <strong>{preset.name}</strong>
                <span className="endpoint-badge">{preset.provider}</span>
                {preset.is_active && <span className="endpoint-default-badge">Active</span>}
              </div>
              <div className="endpoint-row-body">
                <span title={preset.base_url}>{preset.base_url}</span>
                <span>{preset.model}</span>
                <span>{new Date(preset.updated_at).toLocaleString()}</span>
              </div>
              <div className="endpoint-row-actions">
                {!preset.is_active && (
                  <button
                    className="btn btn-ghost btn-sm"
                    data-testid={`activate-preset-${preset.id}`}
                    onClick={() => handleActivate(preset.id)}
                    disabled={activatingId === preset.id}
                  >
                    {activatingId === preset.id ? 'Activating…' : 'Activate'}
                  </button>
                )}
                <button
                  className="btn btn-ghost btn-sm"
                  data-testid={`edit-preset-${preset.id}`}
                  onClick={() => setEditing(preset)}
                >
                  Edit
                </button>
                <button
                  className="btn btn-danger btn-sm"
                  data-testid={`delete-preset-${preset.id}`}
                  onClick={() => handleDelete(preset.id)}
                  disabled={deletingId === preset.id}
                >
                  {deletingId === preset.id ? 'Deleting…' : 'Delete'}
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

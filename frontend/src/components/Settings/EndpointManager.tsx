import { useEffect, useState, useCallback } from 'react'
import type { LLMEndpoint, EndpointFormData } from '../../api/llmConfig'
import {
  fetchEndpoints,
  createEndpoint,
  updateEndpoint,
  deleteEndpoint,
  testEndpointConnection,
} from '../../api/llmConfig'
import { useTranslation } from '../../i18n'
import { EndpointList } from './EndpointList'
import { EndpointForm } from './EndpointForm'
import { Plus, Cpu } from 'lucide-react'

interface EndpointManagerProps {
  onMessage: (message: string, isError: boolean) => void
}

export function EndpointManager({ onMessage }: EndpointManagerProps) {
  const { t } = useTranslation()
  const [endpoints, setEndpoints] = useState<LLMEndpoint[]>([])
  const [loading, setLoading] = useState(true)
  const [editing, setEditing] = useState<LLMEndpoint | null>(null)
  const [showForm, setShowForm] = useState(false)
  const [testingConnectionId, setTestingConnectionId] = useState<string | null>(null)
  const [activatingId, setActivatingId] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      const data = await fetchEndpoints()
      setEndpoints(Array.isArray(data) ? data : [])
    } catch (err) {
      onMessage(err instanceof Error ? err.message : 'Failed to load endpoints', true)
      setEndpoints([])
    } finally {
      setLoading(false)
    }
  }, [onMessage])

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    load()
  }, [load])

  const handleCreate = async (data: EndpointFormData) => {
    try {
      await createEndpoint(data)
      setShowForm(false)
      onMessage(t('endpoint.created'), false)
      await load()
    } catch (err) {
      onMessage(err instanceof Error ? err.message : t('endpoint.createFailed'), true)
    }
  }

  const handleUpdate = async (data: EndpointFormData) => {
    if (!editing) return
    try {
      // Omit api_key when the user didn't enter a new one so the backend
      // keeps the stored key (an empty string would overwrite it to empty).
      const patch: Partial<EndpointFormData> = { ...data }
      if (!patch.api_key) delete patch.api_key
      await updateEndpoint(editing.id, patch)
      setEditing(null)
      onMessage(t('endpoint.updated'), false)
      await load()
    } catch (err) {
      onMessage(err instanceof Error ? err.message : t('endpoint.updateFailed'), true)
    }
  }

  const handleDelete = async (id: string) => {
    try {
      await deleteEndpoint(id)
      onMessage(t('endpoint.deleted'), false)
      await load()
    } catch (err) {
      onMessage(err instanceof Error ? err.message : t('endpoint.deleteFailed'), true)
    }
  }

  const handleTestConnection = async (id: string) => {
    setTestingConnectionId(id)
    try {
      const result = await testEndpointConnection(id)
      setEndpoints(prev => prev.map(ep => (ep.id === id ? {
        ...ep,
        is_reachable: result.reachable,
        last_tested_at: new Date().toISOString(),
      } : ep)))
      if (result.reachable) {
        onMessage(t('connectionTest.connected', { latency: result.latency_ms ?? 0 }), false)
      } else {
        onMessage(t('connectionTest.failed', { error: result.error || '' }), true)
      }
    } catch (err) {
      onMessage(err instanceof Error ? err.message : t('connectionTest.failed', { error: '' }), true)
    } finally {
      setTestingConnectionId(null)
    }
  }

  const handleActivate = async (id: string) => {
    const ep = endpoints.find(e => e.id === id)
    if (!ep) return
    setActivatingId(id)
    try {
      // Mark as default and hot-swap the active LLM provider
      await updateEndpoint(id, { is_default: true })
      const res = await fetch('/api/v1/config/llm', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          provider: ep.provider,
          model: ep.model || '',
          base_url: ep.base_url,
          endpoint_id: ep.id,
        }),
      })
      if (res.ok) {
        setEndpoints(prev => prev.map(e => ({
          ...e,
          is_default: e.id === id,
        })))
        onMessage(t('endpoint.activated', { name: ep.name }), false)
      } else {
        const err = await res.json().catch(() => null)
        onMessage(err?.detail || t('endpoint.activateFailed'), true)
      }
    } catch (err) {
      onMessage(err instanceof Error ? err.message : t('endpoint.activateFailed'), true)
    } finally {
      setActivatingId(null)
    }
  }

  if (loading) return <p>{t('endpoint.loading')}</p>

  return (
    <div className="card" data-testid="endpoint-manager">
      <div className="card-title"><Cpu size={14} />{t('settings.endpoints')}</div>
      <button
        className="btn btn-primary"
        data-testid="add-endpoint-button"
        onClick={() => setShowForm(true)}
      >
        <Plus size={16} />
        {t('endpoint.add')}
      </button>
      {showForm && (
        <EndpointForm onSubmit={handleCreate} onCancel={() => setShowForm(false)} />
      )}
      {editing && (
        <EndpointForm initialValues={editing} onSubmit={handleUpdate} onCancel={() => setEditing(null)} />
      )}
      {endpoints.length === 0 && !showForm ? (
        <p className="settings-empty-hint">{t('endpoint.noEndpoints')}</p>
      ) : (
        <EndpointList
          endpoints={endpoints}
          testingConnectionId={testingConnectionId}
          activatingId={activatingId}
          onEdit={id => setEditing(endpoints.find(e => e.id === id) ?? null)}
          onDelete={handleDelete}
          onTestConnection={handleTestConnection}
          onActivate={handleActivate}
        />
      )}
    </div>
  )
}

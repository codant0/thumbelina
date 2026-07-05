import { useEffect, useState, useCallback } from 'react'
import type { LLMEndpoint, EndpointFormData } from '../../api/llmConfig'
import {
  fetchEndpoints,
  createEndpoint,
  updateEndpoint,
  deleteEndpoint,
  runSpeedTest,
  testEndpointConnection,
} from '../../api/llmConfig'
import { useTranslation } from '../../i18n'
import { EndpointList } from './EndpointList'
import { EndpointForm } from './EndpointForm'

interface EndpointManagerProps {
  onMessage: (message: string, isError: boolean) => void
}

export function EndpointManager({ onMessage }: EndpointManagerProps) {
  const { t } = useTranslation()
  const [endpoints, setEndpoints] = useState<LLMEndpoint[]>([])
  const [loading, setLoading] = useState(true)
  const [editing, setEditing] = useState<LLMEndpoint | null>(null)
  const [showForm, setShowForm] = useState(false)
  const [testingId, setTestingId] = useState<string | null>(null)
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
      await updateEndpoint(editing.id, data)
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

  const handleSpeedTest = async (id: string) => {
    const ep = endpoints.find(e => e.id === id)
    setTestingId(id)
    try {
      const result = await runSpeedTest(id, ep?.model || 'gpt-4o')
      setEndpoints(prev => prev.map(ep => (ep.id === id ? {
        ...ep,
        is_reachable: result.reachable,
        last_latency_ms: result.latency_ms,
        last_total_ms: result.total_ms,
        last_tested_at: new Date().toISOString(),
      } : ep)))
      onMessage(result.reachable ? t('endpoint.speedTestPassed') : `${t('endpoint.speedTestFailed')}: ${result.error || ''}`, !result.reachable)
    } catch (err) {
      onMessage(err instanceof Error ? err.message : t('endpoint.speedTestFailed'), true)
    } finally {
      setTestingId(null)
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
      onMessage(result.reachable ? t('connectionTest.connected') : `${t('connectionTest.failed')}: ${result.error || ''}`, !result.reachable)
    } catch (err) {
      onMessage(err instanceof Error ? err.message : t('connectionTest.failed'), true)
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
      <div className="card-title">{t('settings.endpoints')}</div>
      <button
        className="btn btn-primary"
        data-testid="add-endpoint-button"
        onClick={() => setShowForm(true)}
      >
        {t('endpoint.add')}
      </button>
      {showForm && (
        <EndpointForm onSubmit={handleCreate} onCancel={() => setShowForm(false)} />
      )}
      {editing && (
        <EndpointForm initialValues={editing} onSubmit={handleUpdate} onCancel={() => setEditing(null)} />
      )}
      {endpoints.length === 0 && !showForm ? (
        <p style={{ color: 'var(--text-secondary)', fontSize: 12, marginTop: 12 }}>
          {t('endpoint.noEndpoints')}
        </p>
      ) : (
        <EndpointList
          endpoints={endpoints}
          testingId={testingId}
          testingConnectionId={testingConnectionId}
          activatingId={activatingId}
          onEdit={id => setEditing(endpoints.find(e => e.id === id) ?? null)}
          onDelete={handleDelete}
          onSpeedTest={handleSpeedTest}
          onTestConnection={handleTestConnection}
          onActivate={handleActivate}
        />
      )}
    </div>
  )
}

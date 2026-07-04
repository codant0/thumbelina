import { useEffect, useState, useCallback } from 'react'
import type { LLMEndpoint, EndpointFormData } from '../../api/llmConfig'
import {
  fetchEndpoints,
  createEndpoint,
  updateEndpoint,
  deleteEndpoint,
  runSpeedTest,
} from '../../api/llmConfig'
import { EndpointList } from './EndpointList'
import { EndpointForm } from './EndpointForm'

interface EndpointManagerProps {
  onMessage: (message: string, isError: boolean) => void
}

export function EndpointManager({ onMessage }: EndpointManagerProps) {
  const [endpoints, setEndpoints] = useState<LLMEndpoint[]>([])
  const [loading, setLoading] = useState(true)
  const [editing, setEditing] = useState<LLMEndpoint | null>(null)
  const [showForm, setShowForm] = useState(false)
  const [testingId, setTestingId] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      const data = await fetchEndpoints()
      setEndpoints(data)
    } catch (err) {
      onMessage(err instanceof Error ? err.message : 'Failed to load endpoints', true)
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
      onMessage('Endpoint created', false)
      await load()
    } catch (err) {
      onMessage(err instanceof Error ? err.message : 'Failed to create endpoint', true)
    }
  }

  const handleUpdate = async (data: EndpointFormData) => {
    if (!editing) return
    try {
      await updateEndpoint(editing.id, data)
      setEditing(null)
      onMessage('Endpoint updated', false)
      await load()
    } catch (err) {
      onMessage(err instanceof Error ? err.message : 'Failed to update endpoint', true)
    }
  }

  const handleDelete = async (id: string) => {
    try {
      await deleteEndpoint(id)
      onMessage('Endpoint deleted', false)
      await load()
    } catch (err) {
      onMessage(err instanceof Error ? err.message : 'Failed to delete endpoint', true)
    }
  }

  const handleSpeedTest = async (id: string) => {
    setTestingId(id)
    try {
      const result = await runSpeedTest(id, 'gpt-4o')
      setEndpoints(prev => prev.map(ep => (ep.id === id ? {
        ...ep,
        is_reachable: result.reachable,
        last_latency_ms: result.latency_ms,
        last_total_ms: result.total_ms,
        last_tested_at: new Date().toISOString(),
      } : ep)))
      onMessage(result.reachable ? 'Speed test complete' : `Speed test failed: ${result.error || ''}`, !result.reachable)
    } catch (err) {
      onMessage(err instanceof Error ? err.message : 'Speed test failed', true)
    } finally {
      setTestingId(null)
    }
  }

  const handleSetDefault = async (id: string) => {
    const ep = endpoints.find(e => e.id === id)
    if (!ep) return
    try {
      await updateEndpoint(id, { is_default: true })
      onMessage('Default endpoint updated', false)
      await load()
    } catch (err) {
      onMessage(err instanceof Error ? err.message : 'Failed to set default', true)
    }
  }

  if (loading) return <p>Loading endpoints…</p>

  return (
    <div className="card" data-testid="endpoint-manager">
      <div className="card-title">LLM Endpoints</div>
      <button className="btn btn-primary" data-testid="add-endpoint-button" onClick={() => setShowForm(true)}>Add Endpoint</button>
      {showForm && (
        <EndpointForm onSubmit={handleCreate} onCancel={() => setShowForm(false)} />
      )}
      {editing && (
        <EndpointForm initialValues={editing} onSubmit={handleUpdate} onCancel={() => setEditing(null)} />
      )}
      <EndpointList
        endpoints={endpoints}
        testingId={testingId}
        onEdit={id => setEditing(endpoints.find(e => e.id === id) ?? null)}
        onDelete={handleDelete}
        onSpeedTest={handleSpeedTest}
        onSetDefault={handleSetDefault}
      />
    </div>
  )
}

import type { LLMEndpoint } from '../../api/llmConfig'
import { SpeedTestResult } from './SpeedTestResult'

interface EndpointListProps {
  endpoints: LLMEndpoint[]
  testingId: string | null
  onEdit: (id: string) => void
  onDelete: (id: string) => void
  onSpeedTest: (id: string) => void
  onSetDefault: (id: string) => void
}

export function EndpointList({
  endpoints,
  testingId,
  onEdit,
  onDelete,
  onSpeedTest,
  onSetDefault,
}: EndpointListProps) {
  const formatLatency = (ms?: number) => (ms !== undefined ? `${ms} ms` : '—')
  const formatTime = (iso?: string) => (iso ? new Date(iso).toLocaleString() : 'Never')

  return (
    <div className="endpoint-list">
      {endpoints.map((ep) => (
        <div key={ep.id} className="card" data-testid={`endpoint-row-${ep.id}`}>
          <div className="endpoint-row-header">
            <strong>{ep.name}</strong>
            <span className="endpoint-badge">{ep.provider}</span>
            {ep.is_default && <span className="endpoint-default-badge">★ Default</span>}
          </div>
          <div className="endpoint-row-body">
            <span title={ep.base_url}>{ep.base_url}</span>
            <span>
              <span
                className={`endpoint-status-dot ${
                  ep.is_reachable === true
                    ? 'reachable'
                    : ep.is_reachable === false
                      ? 'unreachable'
                      : 'unknown'
                }`}
              />
              {formatLatency(ep.last_latency_ms)} / {formatLatency(ep.last_total_ms)}
            </span>
            <span>{formatTime(ep.last_tested_at)}</span>
          </div>
          <div className="endpoint-row-actions">
            <button
              className="btn btn-ghost btn-sm"
              data-testid={`speed-test-${ep.id}`}
              onClick={() => onSpeedTest(ep.id)}
              disabled={testingId === ep.id}
            >
              {testingId === ep.id ? <SpeedTestResult loading /> : 'Speed Test'}
            </button>
            <button className="btn btn-ghost btn-sm" onClick={() => onEdit(ep.id)}>Edit</button>
            <button className="btn btn-danger btn-sm" onClick={() => onDelete(ep.id)}>Delete</button>
            {!ep.is_default && (
              <button className="btn btn-ghost btn-sm" onClick={() => onSetDefault(ep.id)}>
                Set Default
              </button>
            )}
          </div>
        </div>
      ))}
    </div>
  )
}

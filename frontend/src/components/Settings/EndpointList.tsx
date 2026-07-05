import type { LLMEndpoint } from '../../api/llmConfig'
import { useTranslation } from '../../i18n'
import { SpeedTestResult } from './SpeedTestResult'

interface EndpointListProps {
  endpoints: LLMEndpoint[]
  testingId: string | null
  testingConnectionId: string | null
  activatingId: string | null
  onEdit: (id: string) => void
  onDelete: (id: string) => void
  onSpeedTest: (id: string) => void
  onTestConnection: (id: string) => void
  onActivate: (id: string) => void
}

export function EndpointList({
  endpoints,
  testingId,
  testingConnectionId,
  activatingId,
  onEdit,
  onDelete,
  onSpeedTest,
  onTestConnection,
  onActivate,
}: EndpointListProps) {
  const { t } = useTranslation()
  const formatLatency = (ms?: number) => (ms !== undefined ? `${ms} ms` : '—')
  const formatTime = (iso?: string) => (iso ? new Date(iso).toLocaleString() : t('endpoint.never'))

  return (
    <div className="endpoint-list">
      {endpoints.map((ep) => (
        <div
          key={ep.id}
          className="card"
          data-testid={`endpoint-row-${ep.id}`}
          style={ep.is_default ? { borderColor: 'var(--success)' } : undefined}
        >
          <div className="endpoint-row-header">
            <strong>{ep.name}</strong>
            <span className="endpoint-badge">{ep.provider}</span>
            {ep.is_default && <span className="endpoint-default-badge">{t('endpoint.active')}</span>}
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
            {!ep.is_default && (
              <button
                className="btn btn-primary btn-sm"
                data-testid={`activate-${ep.id}`}
                onClick={() => onActivate(ep.id)}
                disabled={activatingId === ep.id}
              >
                {activatingId === ep.id ? t('common.activating') : t('common.activate')}
              </button>
            )}
            <button
              className="btn btn-ghost btn-sm"
              data-testid={`test-connection-${ep.id}`}
              onClick={() => onTestConnection(ep.id)}
              disabled={testingConnectionId === ep.id}
            >
              {testingConnectionId === ep.id ? <SpeedTestResult loading /> : t('endpoint.testConnection')}
            </button>
            <button
              className="btn btn-ghost btn-sm"
              data-testid={`speed-test-${ep.id}`}
              onClick={() => onSpeedTest(ep.id)}
              disabled={testingId === ep.id}
            >
              {testingId === ep.id ? <SpeedTestResult loading /> : t('endpoint.speedTest')}
            </button>
            <button className="btn btn-ghost btn-sm" onClick={() => onEdit(ep.id)}>
              {t('common.edit')}
            </button>
            <button className="btn btn-danger btn-sm" onClick={() => onDelete(ep.id)}>
              {t('common.delete')}
            </button>
          </div>
        </div>
      ))}
    </div>
  )
}

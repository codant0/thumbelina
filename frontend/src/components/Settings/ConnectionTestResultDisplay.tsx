import type { ConnectionTestResult } from '../../api/llmConfig'

interface ConnectionTestResultDisplayProps {
  result: ConnectionTestResult | null
  loading?: boolean
}

export function ConnectionTestResultDisplay({ result, loading }: ConnectionTestResultDisplayProps) {
  if (loading) {
    return <p style={{ fontSize: 12, color: 'var(--text-secondary)' }}>Testing connection…</p>
  }
  if (!result) {
    return null
  }

  const statusColor = result.reachable ? 'var(--success)' : 'var(--error)'
  const summary = result.reachable
    ? `Connected — ${result.latency_ms} ms`
    : `Connection failed — ${result.error || 'Unknown error'}`

  return (
    <div style={{ marginTop: 8, fontSize: 12 }}>
      <p style={{ margin: '0 0 4px', color: statusColor, fontWeight: 500 }}>
        {result.reachable ? '✓' : '✗'} {summary}
      </p>
      {result.details && (
        <ul style={{ margin: 0, paddingLeft: 16, color: 'var(--text-secondary)', lineHeight: 1.5 }}>
          <li>
            Network: {result.details.network.ok ? '✓' : '✗'}
            {result.details.network.latency_ms !== undefined && ` ${result.details.network.latency_ms} ms`}
            {result.details.network.error && ` — ${result.details.network.error}`}
          </li>
          <li>
            Auth: {result.details.auth.ok ? '✓' : '✗'}
            {result.details.auth.latency_ms !== undefined && ` ${result.details.auth.latency_ms} ms`}
            {result.details.auth.error && ` — ${result.details.auth.error}`}
          </li>
          <li>
            Service: {result.details.service.ok ? '✓' : '✗'}
            {result.details.service.latency_ms !== undefined && ` ${result.details.service.latency_ms} ms`}
            {result.details.service.error && ` — ${result.details.service.error}`}
          </li>
        </ul>
      )}
    </div>
  )
}

import type { SpeedTestResult as SpeedTestResultType } from '../../api/llmConfig'

interface SpeedTestResultProps {
  loading?: boolean
  result?: SpeedTestResultType
}

export function SpeedTestResult({ loading, result }: SpeedTestResultProps) {
  if (loading) {
    return <span className="speed-test-loading">Testing…</span>
  }
  if (!result) {
    return null
  }
  if (result.reachable) {
    return (
      <span className="speed-test-success">
        ✓ <span>{result.latency_ms !== undefined ? `${result.latency_ms} ms` : '—'}</span>
        {' / '}
        <span>{result.total_ms !== undefined ? `${result.total_ms} ms` : '—'}</span>
      </span>
    )
  }
  return (
    <span className="speed-test-error" title={result.error}>
      ✗ Unreachable{result.error ? ` — ${result.error}` : ''}
    </span>
  )
}

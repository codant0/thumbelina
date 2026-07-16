import type { SpeedTestResult as SpeedTestResultType } from '../../api/llmConfig'
import { Check, X, Loader2 } from 'lucide-react'
import { useTranslation } from '../../i18n'

interface SpeedTestResultProps {
  loading?: boolean
  result?: SpeedTestResultType
}

export function SpeedTestResult({ loading, result }: SpeedTestResultProps) {
  const { t } = useTranslation()
  if (loading) {
    return (
      <span className="speed-test-loading">
        <Loader2 size={14} className="spin" />
        {t('common.testing')}
      </span>
    )
  }
  if (!result) {
    return null
  }
  if (result.reachable) {
    return (
      <span className="speed-test-success">
        <Check size={14} />
        <span>{result.latency_ms !== undefined ? `${result.latency_ms} ms` : '—'}</span>
        {' / '}
        <span>{result.total_ms !== undefined ? `${result.total_ms} ms` : '—'}</span>
      </span>
    )
  }
  return (
    <span className="speed-test-error" title={result.error}>
      <X size={14} />
      {t('endpoint.unreachable')}{result.error ? ` — ${result.error}` : ''}
    </span>
  )
}

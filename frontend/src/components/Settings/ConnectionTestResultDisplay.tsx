import type { ConnectionTestResult } from '../../api/llmConfig'
import type { ReactNode } from 'react'
import { Check, X, Loader2, Globe, Lock, Server } from 'lucide-react'

interface ConnectionTestResultDisplayProps {
  result: ConnectionTestResult | null
  loading?: boolean
}

export function ConnectionTestResultDisplay({ result, loading }: ConnectionTestResultDisplayProps) {
  if (loading) {
    return (
      <div className="conn-test">
        <div className="conn-test__summary">
          <Loader2 size={16} className="spin" />
          Testing connection…
        </div>
      </div>
    )
  }
  if (!result) {
    return null
  }

  const ok = result.reachable
  const summary = ok
    ? `Connected — ${result.latency_ms} ms`
    : `Connection failed — ${result.error || 'Unknown error'}`

  return (
    <div className="conn-test">
      <div className={`conn-test__summary ${ok ? 'conn-test__summary--ok' : 'conn-test__summary--fail'}`}>
        {ok ? <Check size={16} /> : <X size={16} />}
        {summary}
      </div>
      {result.details && (
        <ul className="conn-test__list">
          <DetailLine
            icon={<Globe size={14} />}
            label="Network"
            ok={result.details.network.ok}
            latency={result.details.network.latency_ms}
            error={result.details.network.error}
          />
          <DetailLine
            icon={<Lock size={14} />}
            label="Auth"
            ok={result.details.auth.ok}
            latency={result.details.auth.latency_ms}
            error={result.details.auth.error}
          />
          <DetailLine
            icon={<Server size={14} />}
            label="Service"
            ok={result.details.service.ok}
            latency={result.details.service.latency_ms}
            error={result.details.service.error}
          />
        </ul>
      )}
    </div>
  )
}

interface DetailLineProps {
  icon: ReactNode
  label: string
  ok: boolean
  latency?: number
  error?: string
}

function DetailLine({ icon, label, ok, latency, error }: DetailLineProps) {
  return (
    <li className={`conn-test__item ${ok ? 'conn-test__item--ok' : 'conn-test__item--fail'}`}>
      {icon}
      <span className="conn-test__item-name">{label}:</span>
      {ok ? <Check size={14} /> : <X size={14} />}
      {latency !== undefined && ` ${latency} ms`}
      {error && ` — ${error}`}
    </li>
  )
}

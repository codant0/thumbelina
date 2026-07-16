import { useState, useCallback } from 'react'
import { testConnection, testEndpointConnection, type ConnectionTestResult } from '../../api/llmConfig'
import { ConnectionTestResultDisplay } from './ConnectionTestResultDisplay'
import { Loader2, Plug } from 'lucide-react'
import { useTranslation } from '../../i18n'

interface ConnectionTestButtonProps {
  provider: string
  base_url: string
  api_key: string
  model?: string
  /** When provided, falls back to the saved endpoint's key if api_key is empty. */
  endpointId?: string
  onResult?: (result: ConnectionTestResult) => void
}

export function ConnectionTestButton({
  provider,
  base_url,
  api_key,
  model,
  endpointId,
  onResult,
}: ConnectionTestButtonProps) {
  const [result, setResult] = useState<ConnectionTestResult | null>(null)
  const [loading, setLoading] = useState(false)
  const { t } = useTranslation()

  const handleTest = useCallback(async () => {
    setLoading(true)
    setResult(null)
    try {
      // Edit mode: when the user hasn't entered a new key, reuse the saved
      // endpoint's key via the endpoint-scoped endpoint instead of sending an
      // empty key to the generic test-connection (which would fail auth).
      const data = endpointId && !api_key
        ? await testEndpointConnection(endpointId, model || undefined)
        : await testConnection({
          provider,
          base_url,
          api_key: api_key || undefined,
          model: model || undefined,
        })
      setResult(data)
      onResult?.(data)
    } catch (err) {
      setResult({
        provider,
        base_url,
        reachable: false,
        network_reachable: false,
        auth_valid: false,
        service_available: false,
        error: err instanceof Error ? err.message : t('connectionTest.testFailed'),
      })
    } finally {
      setLoading(false)
    }
  }, [provider, base_url, api_key, model, endpointId, onResult])

  return (
    <div>
      <button
        type="button"
        className="btn btn-ghost btn-sm"
        data-testid="test-connection-button"
        onClick={handleTest}
        disabled={loading || !base_url}
        title={base_url ? t('connectionTest.testTooltip') : t('connectionTest.enterBaseUrl')}
      >
        {loading ? <><Loader2 size={14} className="spin" />{t('common.testing')}</> : <><Plug size={14} />{t('connectionTest.button')}</>}
      </button>
      <ConnectionTestResultDisplay result={result} loading={loading} />
    </div>
  )
}

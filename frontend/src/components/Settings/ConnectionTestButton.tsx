import { useState, useCallback } from 'react'
import { testConnection, type ConnectionTestResult } from '../../api/llmConfig'
import { ConnectionTestResultDisplay } from './ConnectionTestResultDisplay'

interface ConnectionTestButtonProps {
  provider: string
  base_url: string
  api_key: string
  model?: string
  onResult?: (result: ConnectionTestResult) => void
}

export function ConnectionTestButton({
  provider,
  base_url,
  api_key,
  model,
  onResult,
}: ConnectionTestButtonProps) {
  const [result, setResult] = useState<ConnectionTestResult | null>(null)
  const [loading, setLoading] = useState(false)

  const handleTest = useCallback(async () => {
    setLoading(true)
    setResult(null)
    try {
      const data = await testConnection({
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
        error: err instanceof Error ? err.message : 'Test failed',
      })
    } finally {
      setLoading(false)
    }
  }, [provider, base_url, api_key, model, onResult])

  return (
    <div>
      <button
        type="button"
        className="btn btn-ghost btn-sm"
        data-testid="test-connection-button"
        onClick={handleTest}
        disabled={loading || !base_url}
        title={base_url ? 'Test connectivity to this endpoint' : 'Enter a base URL first'}
      >
        {loading ? 'Testing…' : 'Test Connection'}
      </button>
      <ConnectionTestResultDisplay result={result} loading={loading} />
    </div>
  )
}

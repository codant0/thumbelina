import { useState, useCallback } from 'react'
import { fetchModels } from '../../api/llmConfig'
import { Loader2, Download } from 'lucide-react'

interface ModelSelectorProps {
  provider: string
  base_url: string
  api_key: string
  model: string
  onSelect: (model: string) => void
}

export function ModelSelector({ provider, base_url, api_key, model, onSelect }: ModelSelectorProps) {
  const [models, setModels] = useState<string[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const supported = provider === 'openai'

  const handleFetch = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const data = await fetchModels({ provider, base_url, api_key })
      setModels(data.models)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch models')
    } finally {
      setLoading(false)
    }
  }, [provider, base_url, api_key])

  return (
    <div className="model-selector">
      <div className="model-selector-input-row">
        <input
          list="model-options"
          type="text"
          className="form-input"
          data-testid="endpoint-model-input"
          value={model}
          onChange={e => onSelect(e.target.value)}
          placeholder="Select or type a model"
        />
        <button
          type="button"
          className="btn btn-ghost btn-sm"
          data-testid="fetch-models-button"
          onClick={handleFetch}
          disabled={!supported || loading || !provider || !base_url || !api_key}
          title={
            !supported
              ? 'Model listing not supported for this provider yet.'
              : !provider || !base_url || !api_key
                ? 'Provider, base URL and API key are required to fetch models'
                : 'Fetch available models'
          }
        >
          {loading ? <><Loader2 size={14} className="spin" />Fetching</> : <><Download size={14} />Fetch</>}
        </button>
      </div>
      {error && <span className="form-error">{error}</span>}
      <datalist id="model-options">
        {models.map(m => (
          <option key={m} value={m} data-testid="model-option" />
        ))}
      </datalist>
    </div>
  )
}

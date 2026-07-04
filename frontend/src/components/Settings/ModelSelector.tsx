import { useState, useCallback } from 'react'
import { fetchModels } from '../../api/llmConfig'

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
      <button
        type="button"
        className="btn btn-ghost btn-sm"
        data-testid="fetch-models-button"
        onClick={handleFetch}
        disabled={!supported || loading || !base_url}
        title={supported ? 'Fetch available models' : 'Model listing not supported for this provider yet.'}
      >
        {loading ? 'Fetching…' : 'Fetch models'}
      </button>
      {error && <span className="form-error">{error}</span>}
      <datalist id="model-options">
        {models.map(m => (
          <option key={m} value={m} data-testid="model-option" />
        ))}
      </datalist>
      <input
        list="model-options"
        type="text"
        className="form-input"
        value={model}
        onChange={e => onSelect(e.target.value)}
        placeholder="Select or type a model"
      />
    </div>
  )
}

import { useState, type FormEvent } from 'react'
import type { EndpointFormData, LLMEndpoint } from '../../api/llmConfig'

interface EndpointFormProps {
  initialValues?: LLMEndpoint
  onSubmit: (data: EndpointFormData) => void
  onCancel: () => void
}

export function EndpointForm({ initialValues, onSubmit, onCancel }: EndpointFormProps) {
  const [provider, setProvider] = useState<'openai' | 'ollama' | 'anthropic'>(initialValues?.provider ?? 'openai')
  const [name, setName] = useState(initialValues?.name ?? '')
  const [baseUrl, setBaseUrl] = useState(initialValues?.base_url ?? '')
  const [apiKey, setApiKey] = useState('')
  const [isDefault, setIsDefault] = useState(initialValues?.is_default ?? false)
  const [error, setError] = useState('')

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault()
    setError('')
    if (!name.trim()) {
      setError('Name is required')
      return
    }
    if (!provider) {
      setError('Provider is required')
      return
    }
    try {
      // eslint-disable-next-line no-new
      new URL(baseUrl)
    } catch {
      setError('Base URL must be a valid URL')
      return
    }
    onSubmit({
      provider,
      name: name.trim(),
      base_url: baseUrl.trim(),
      api_key: apiKey,
      is_default: isDefault,
    })
  }

  return (
    <form onSubmit={handleSubmit} className="card" data-testid="endpoint-form">
      <div className="card-title">{initialValues ? 'Edit Endpoint' : 'Add Endpoint'}</div>
      <div className="form-group">
        <label className="form-label">Provider</label>
        <select className="form-select" data-testid="endpoint-provider-select" value={provider} onChange={e => setProvider(e.target.value as 'openai' | 'ollama' | 'anthropic')}>
          <option value="openai">OpenAI</option>
          <option value="anthropic" disabled>Anthropic (soon)</option>
          <option value="ollama" disabled>Ollama (soon)</option>
        </select>
      </div>
      <div className="form-group">
        <label className="form-label">Name</label>
        <input className="form-input" data-testid="endpoint-name-input" value={name} onChange={e => setName(e.target.value)} />
      </div>
      <div className="form-group">
        <label className="form-label">Base URL</label>
        <input className="form-input" data-testid="endpoint-base-url-input" value={baseUrl} onChange={e => setBaseUrl(e.target.value)} placeholder="https://api.openai.com/v1" />
      </div>
      <div className="form-group">
        <label className="form-label">API Key</label>
        <input className="form-input" data-testid="endpoint-api-key-input" type="password" value={apiKey} onChange={e => setApiKey(e.target.value)} placeholder={initialValues ? 'Leave empty to keep current key' : ''} />
      </div>
      <div className="form-group">
        <label className="form-checkbox">
          <input type="checkbox" checked={isDefault} onChange={e => setIsDefault(e.target.checked)} />
          Set as default
        </label>
      </div>
      {error && <p className="form-error" data-testid="endpoint-form-error">{error}</p>}
      <div className="settings-actions">
        <button type="submit" className="btn btn-primary" data-testid="endpoint-form-submit">Save</button>
        <button type="button" className="btn btn-ghost" onClick={onCancel}>Cancel</button>
      </div>
    </form>
  )
}

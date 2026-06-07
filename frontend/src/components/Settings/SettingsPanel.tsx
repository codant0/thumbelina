import { useState, useEffect, type FormEvent } from 'react'

interface ConfigData {
  provider: string
  model: string
  base_url: string
  rate_limit_enabled: boolean
}

export function SettingsPanel() {
  const [config, setConfig] = useState<ConfigData>({
    provider: 'openai',
    model: 'gpt-4o',
    base_url: '',
    rate_limit_enabled: false,
  })
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState('')
  const [isError, setIsError] = useState(false)

  useEffect(() => {
    fetch('/api/v1/config')
      .then(res => { if (res.ok) return res.json(); return null })
      .then(data => {
        if (data) {
          setConfig({
            provider: data.provider ?? 'openai',
            model: data.model ?? 'gpt-4o',
            base_url: data.base_url ?? '',
            rate_limit_enabled: data.rate_limit_enabled ?? false,
          })
        }
      })
      .catch(() => {})
  }, [])

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault()
    setSaving(true)
    setMessage('')
    fetch('/api/v1/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        llm: {
          provider: config.provider,
          model: config.model,
          base_url: config.base_url || null,
        },
        rate_limit: { enabled: config.rate_limit_enabled },
      }),
    })
      .then(res => {
        if (res.ok) {
          setMessage('Settings saved')
          setIsError(false)
        } else {
          setMessage('Failed to save')
          setIsError(true)
        }
      })
      .catch(() => { setMessage('Failed to save'); setIsError(true) })
      .finally(() => setSaving(false))
  }

  return (
    <div className="page-container" data-testid="settings-panel">
      <div className="page-title">Settings</div>
      <div className="card">
        <form onSubmit={handleSubmit} className="settings-form">
          <div className="form-group">
            <label className="form-label" htmlFor="provider">LLM Provider</label>
            <select
              id="provider"
              className="form-select"
              data-testid="provider-select"
              value={config.provider}
              onChange={e => setConfig({ ...config, provider: e.target.value })}
            >
              <option value="openai">OpenAI</option>
              <option value="anthropic">Anthropic</option>
              <option value="ollama">Ollama</option>
            </select>
          </div>
          <div className="form-group">
            <label className="form-label" htmlFor="model">Model</label>
            <input
              id="model"
              type="text"
              className="form-input"
              data-testid="model-input"
              value={config.model}
              onChange={e => setConfig({ ...config, model: e.target.value })}
            />
          </div>
          <div className="form-group">
            <label className="form-label" htmlFor="base_url">Base URL</label>
            <input
              id="base_url"
              type="text"
              className="form-input"
              data-testid="base-url-input"
              value={config.base_url}
              onChange={e => setConfig({ ...config, base_url: e.target.value })}
              placeholder="Optional custom API base URL"
            />
          </div>
          <div className="form-group">
            <label className="form-checkbox">
              <input
                type="checkbox"
                data-testid="rate-limit-toggle"
                checked={config.rate_limit_enabled}
                onChange={e => setConfig({ ...config, rate_limit_enabled: e.target.checked })}
              />
              Enable Rate Limiting
            </label>
          </div>
          <div className="settings-actions">
            <button type="submit" className="btn btn-primary" disabled={saving} data-testid="save-button">
              {saving ? 'Saving...' : 'Save Changes'}
            </button>
          </div>
        </form>
        {message && (
          <p data-testid="settings-message" style={{ marginTop: 12, fontSize: 12.5, color: isError ? 'var(--error)' : 'var(--success)' }}>
            {message}
          </p>
        )}
      </div>
    </div>
  )
}

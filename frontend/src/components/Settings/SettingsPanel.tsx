import { useState, useEffect, type FormEvent } from 'react'

interface ConfigData {
  provider: string
  model: string
  base_url: string
  auth_enabled: boolean
  rate_limit_enabled: boolean
}

export function SettingsPanel() {
  const [config, setConfig] = useState<ConfigData>({
    provider: 'openai',
    model: 'gpt-4o',
    base_url: '',
    auth_enabled: false,
    rate_limit_enabled: false,
  })
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState('')

  useEffect(() => {
    fetch('/api/v1/config')
      .then(res => {
        if (res.ok) return res.json()
        return null
      })
      .then(data => {
        if (data) {
          setConfig({
            provider: data.llm?.provider ?? 'openai',
            model: data.llm?.model ?? 'gpt-4o',
            base_url: data.llm?.base_url ?? '',
            auth_enabled: !!data.auth?.secret_key,
            rate_limit_enabled: !!data.rate_limit?.enabled,
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
        auth: { enabled: config.auth_enabled },
        rate_limit: { enabled: config.rate_limit_enabled },
      }),
    })
      .then(res => {
        if (res.ok) {
          setMessage('Settings saved successfully')
        } else {
          setMessage('Failed to save settings')
        }
      })
      .catch(() => setMessage('Failed to save settings'))
      .finally(() => setSaving(false))
  }

  return (
    <div data-testid="settings-panel">
      <h2>Settings</h2>
      <form onSubmit={handleSubmit}>
        <div>
          <label htmlFor="provider">LLM Provider</label>
          <select
            id="provider"
            data-testid="provider-select"
            value={config.provider}
            onChange={e => setConfig({ ...config, provider: e.target.value })}
          >
            <option value="openai">OpenAI</option>
            <option value="anthropic">Anthropic</option>
            <option value="ollama">Ollama</option>
          </select>
        </div>
        <div>
          <label htmlFor="model">Model</label>
          <input
            id="model"
            type="text"
            data-testid="model-input"
            value={config.model}
            onChange={e => setConfig({ ...config, model: e.target.value })}
          />
        </div>
        <div>
          <label htmlFor="base_url">Base URL</label>
          <input
            id="base_url"
            type="text"
            data-testid="base-url-input"
            value={config.base_url}
            onChange={e => setConfig({ ...config, base_url: e.target.value })}
            placeholder="Optional custom API base URL"
          />
        </div>
        <div>
          <label>
            <input
              type="checkbox"
              data-testid="auth-toggle"
              checked={config.auth_enabled}
              onChange={e => setConfig({ ...config, auth_enabled: e.target.checked })}
            />
            Enable Authentication
          </label>
        </div>
        <div>
          <label>
            <input
              type="checkbox"
              data-testid="rate-limit-toggle"
              checked={config.rate_limit_enabled}
              onChange={e =>
                setConfig({ ...config, rate_limit_enabled: e.target.checked })
              }
            />
            Enable Rate Limiting
          </label>
        </div>
        <button type="submit" disabled={saving} data-testid="save-button">
          {saving ? 'Saving...' : 'Save'}
        </button>
      </form>
      {message && <p data-testid="settings-message">{message}</p>}
    </div>
  )
}

import { useState, useEffect, useCallback, type FormEvent } from 'react'
import { EndpointManager } from './EndpointManager'
import { ModelSelector } from './ModelSelector'

interface ConfigData {
  provider: string
  model: string
  base_url: string
  api_key: string
  rate_limit_enabled: boolean
}

interface UserProfile {
  id: string
  user_id: string
  communication_style: string
  expertise_level: string
}

interface UserPreference {
  id: string
  category: string
  key: string
  value: string
  confidence_score: number
}

export function SettingsPanel() {
  const [config, setConfig] = useState<ConfigData>({
    provider: 'openai',
    model: 'gpt-4o',
    base_url: '',
    api_key: '',
    rate_limit_enabled: false,
  })
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState('')
  const [isError, setIsError] = useState(false)

  // User profile state
  const [profile, setProfile] = useState<UserProfile | null>(null)
  const [preferences, setPreferences] = useState<UserPreference[]>([])
  const [profileLoading, setProfileLoading] = useState(true)

  // Data management state
  const [exporting, setExporting] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [deleteConfirm, setDeleteConfirm] = useState(false)

  useEffect(() => {
    fetch('/api/v1/config')
      .then(res => { if (res.ok) return res.json(); return null })
      .then(data => {
        if (data) {
          setConfig({
            provider: data.provider ?? 'openai',
            model: data.model ?? 'gpt-4o',
            base_url: data.base_url ?? '',
            api_key: '',
            rate_limit_enabled: data.rate_limit_enabled ?? false,
          })
        }
      })
      .catch(() => {})
  }, [])

  // Fetch user profile
  useEffect(() => {
    fetch('/api/v1/user/profile')
      .then(res => { if (res.ok) return res.json(); return null })
      .then(data => {
        if (data) {
          setProfile(data.profile ?? null)
          setPreferences(data.preferences ?? [])
        }
      })
      .catch(() => {})
      .finally(() => setProfileLoading(false))
  }, [])

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
    setSaving(true)
    setMessage('')
    try {
      const res = await fetch('/api/v1/config/llm', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          provider: config.provider,
          model: config.model,
          base_url: config.base_url || null,
          api_key: config.api_key || '',
        }),
      })
      if (res.ok) {
        const data = await res.json()
        setMessage(`Switched to ${data.provider}/${data.model}`)
        setIsError(false)
        setConfig(prev => ({ ...prev, api_key: '' }))
      } else {
        const err = await res.json().catch(() => null)
        setMessage(err?.detail || 'Failed to switch provider')
        setIsError(true)
      }
    } catch {
      setMessage('Network error')
      setIsError(true)
    } finally {
      setSaving(false)
    }
  }

  const handleRateLimitToggle = async (enabled: boolean) => {
    setConfig(prev => ({ ...prev, rate_limit_enabled: enabled }))
    try {
      await fetch('/api/v1/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ rate_limit: { enabled } }),
      })
    } catch { /* ignore */ }
  }

  const handleExport = useCallback(async () => {
    setExporting(true)
    try {
      const res = await fetch('/api/v1/data/export')
      if (res.ok) {
        const data = await res.json()
        const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
        const url = URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = url
        a.download = `thumbelina-export-${new Date().toISOString().slice(0, 10)}.json`
        a.click()
        URL.revokeObjectURL(url)
      }
    } catch { /* ignore */ } finally {
      setExporting(false)
    }
  }, [])

  const handleDeleteAll = useCallback(async () => {
    if (!deleteConfirm) {
      setDeleteConfirm(true)
      return
    }
    setDeleting(true)
    try {
      const res = await fetch('/api/v1/data/all?confirm=true', { method: 'DELETE' })
      if (res.ok) {
        setMessage('All data deleted')
        setIsError(false)
        setDeleteConfirm(false)
      } else {
        setMessage('Failed to delete data')
        setIsError(true)
      }
    } catch {
      setMessage('Failed to delete data')
      setIsError(true)
    } finally {
      setDeleting(false)
    }
  }, [deleteConfirm])

  return (
    <div className="page-container" data-testid="settings-panel">
      <div className="page-title">Settings</div>

      {/* LLM Configuration */}
      <div className="card">
        <div className="card-title">LLM Configuration</div>
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
            <ModelSelector
              provider={config.provider}
              base_url={config.base_url}
              api_key={config.api_key}
              model={config.model}
              onSelect={model => setConfig(prev => ({ ...prev, model }))}
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
            <label className="form-label" htmlFor="api_key">API Key</label>
            <input
              id="api_key"
              type="password"
              className="form-input"
              data-testid="api-key-input"
              value={config.api_key}
              onChange={e => setConfig({ ...config, api_key: e.target.value })}
              placeholder="Leave empty to keep current key"
            />
          </div>
          <div className="form-group">
            <label className="form-checkbox">
              <input
                type="checkbox"
                data-testid="rate-limit-toggle"
                checked={config.rate_limit_enabled}
                onChange={e => handleRateLimitToggle(e.target.checked)}
              />
              Enable Rate Limiting
            </label>
          </div>
          <div className="settings-actions">
            <button type="submit" className="btn btn-primary" disabled={saving} data-testid="save-button">
              {saving ? 'Switching...' : 'Switch Model'}
            </button>
          </div>
        </form>
        {message && (
          <p data-testid="settings-message" style={{ marginTop: 12, fontSize: 12.5, color: isError ? 'var(--error)' : 'var(--success)' }}>
            {message}
          </p>
        )}
      </div>

      {/* LLM Endpoints */}
      <EndpointManager onMessage={(msg, err) => { setMessage(msg); setIsError(err) }} />

      {/* User Profile */}
      <div className="card" data-testid="user-profile-card">
        <div className="card-title">User Profile</div>
        {profileLoading ? (
          <p style={{ color: 'var(--text-secondary)', fontSize: 12 }}>Loading...</p>
        ) : profile ? (
          <div style={{ fontSize: 13 }}>
            <div style={{ marginBottom: 8 }}>
              <strong>Communication Style:</strong> {profile.communication_style || 'Not set'}
            </div>
            <div style={{ marginBottom: 8 }}>
              <strong>Expertise Level:</strong> {profile.expertise_level || 'Not set'}
            </div>
            {preferences.length > 0 && (
              <div>
                <strong>Preferences:</strong>
                <ul style={{ margin: '4px 0 0 16px', padding: 0 }}>
                  {preferences.map(p => (
                    <li key={p.id} data-testid="preference-item">
                      <span style={{ color: 'var(--text-secondary)' }}>{p.category}/{p.key}:</span> {p.value}
                      <span style={{ marginLeft: 6, fontSize: 11, color: 'var(--text-secondary)' }}>
                        ({Math.round(p.confidence_score * 100)}%)
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        ) : (
          <p style={{ color: 'var(--text-secondary)', fontSize: 12 }}>
            No profile data yet. The agent will build your profile as you chat.
          </p>
        )}
      </div>

      {/* Data Management */}
      <div className="card" data-testid="data-management-card">
        <div className="card-title">Data Management</div>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          <button
            className="btn btn-ghost"
            data-testid="export-button"
            onClick={handleExport}
            disabled={exporting}
          >
            {exporting ? 'Exporting...' : 'Export All Data'}
          </button>
          <button
            className={`btn ${deleteConfirm ? 'btn-danger' : 'btn-ghost'}`}
            data-testid="delete-all-button"
            onClick={handleDeleteAll}
            disabled={deleting}
          >
            {deleting ? 'Deleting...' : deleteConfirm ? 'Click again to confirm' : 'Delete All Data'}
          </button>
          {deleteConfirm && (
            <button
              className="btn btn-ghost btn-sm"
              onClick={() => setDeleteConfirm(false)}
            >
              Cancel
            </button>
          )}
        </div>
      </div>
    </div>
  )
}

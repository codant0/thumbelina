import { useEffect, useState, useCallback } from 'react'
import { Wrench, Search, Save, Loader2, KeyRound, CheckCircle2 } from 'lucide-react'
import { useTranslation } from '../../i18n'
import {
  fetchToolsConfig,
  updateWebSearchConfig,
} from '../../api/toolsConfig'

interface ToolsConfigProps {
  onMessage: (message: string, isError: boolean) => void
}

export function ToolsConfig({ onMessage }: ToolsConfigProps) {
  const { t } = useTranslation()
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [enabled, setEnabled] = useState(true)
  const [provider, setProvider] = useState<'tavily' | 'duckduckgo'>('tavily')
  const [apiKeySet, setApiKeySet] = useState(false)
  const [apiKey, setApiKey] = useState('')

  const load = useCallback(async () => {
    try {
      const data = await fetchToolsConfig()
      setEnabled(data.web_search.enabled)
      setProvider(data.web_search.provider)
      setApiKeySet(data.web_search.api_key_set)
    } catch (err) {
      onMessage(err instanceof Error ? err.message : t('tools.loadFailed'), true)
    } finally {
      setLoading(false)
    }
  }, [onMessage])

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    load()
  }, [load])

  const handleSave = async () => {
    setSaving(true)
    try {
      const patch: { enabled?: boolean; provider?: 'tavily' | 'duckduckgo'; api_key?: string } = {
        enabled,
        provider,
      }
      // Empty api_key means "keep the current key" rather than clearing it.
      if (apiKey.trim()) patch.api_key = apiKey.trim()
      const updated = await updateWebSearchConfig(patch)
      setApiKeySet(updated.api_key_set)
      setApiKey('')
      onMessage(t('tools.saved'), false)
    } catch (err) {
      onMessage(err instanceof Error ? err.message : t('tools.saveFailed'), true)
    } finally {
      setSaving(false)
    }
  }

  if (loading) return <p className="settings-empty-hint">{t('tools.loading')}</p>

  return (
    <div className="card" data-testid="tools-config-card">
      <div className="card-title"><Wrench size={14} />{t('settings.tools')}</div>

      <div className="form-group">
        <label className="form-checkbox">
          <input
            type="checkbox"
            data-testid="websearch-enabled-toggle"
            checked={enabled}
            onChange={e => setEnabled(e.target.checked)}
          />
          <Search size={16} />
          {t('tools.webSearchEnabled')}
        </label>
        <p className="form-hint">{t('tools.webSearchEnabledDesc')}</p>
      </div>

      <div className="form-group">
        <label className="form-label">
          <Search size={14} />
          {t('tools.provider')}
        </label>
        <select
          className="form-select"
          data-testid="websearch-provider-select"
          value={provider}
          onChange={e => setProvider(e.target.value as 'tavily' | 'duckduckgo')}
        >
          <option value="tavily">{t('tools.tavily')}</option>
          <option value="duckduckgo">{t('tools.duckduckgo')}</option>
        </select>
        <p className="form-hint">{t('tools.providerHint')}</p>
      </div>

      {provider === 'tavily' && (
        <div className="form-group" data-testid="websearch-api-key-group">
          <label className="form-label">
            <KeyRound size={14} />
            {t('tools.tavilyApiKey')}
            {apiKeySet && (
              <span className="tools-config__key-set">
                <CheckCircle2 size={13} />
                {t('tools.keySet')}
              </span>
            )}
          </label>
          <input
            className="form-input"
            type="password"
            data-testid="websearch-api-key-input"
            value={apiKey}
            onChange={e => setApiKey(e.target.value)}
            placeholder={apiKeySet ? t('tools.keepKeyHint') : t('tools.tavilyApiKeyPlaceholder')}
          />
          <p className="form-hint">{t('tools.tavilyApiKeyHint')}</p>
        </div>
      )}

      <div className="settings-actions">
        <button
          type="button"
          className="btn btn-primary"
          data-testid="websearch-save-button"
          onClick={handleSave}
          disabled={saving}
        >
          {saving ? <Loader2 size={16} className="spin" /> : <Save size={16} />}
          {saving ? t('tools.saving') : t('common.save')}
        </button>
      </div>
    </div>
  )
}
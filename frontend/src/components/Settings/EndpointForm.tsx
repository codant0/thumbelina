import { useState, type FormEvent } from 'react'
import type { EndpointFormData, LLMEndpoint } from '../../api/llmConfig'
import { useTranslation } from '../../i18n'
import { ConnectionTestButton } from './ConnectionTestButton'
import { ModelSelector } from './ModelSelector'

interface EndpointFormProps {
  initialValues?: LLMEndpoint
  onSubmit: (data: EndpointFormData) => void
  onCancel: () => void
}

export function EndpointForm({ initialValues, onSubmit, onCancel }: EndpointFormProps) {
  const { t } = useTranslation()
  const [provider, setProvider] = useState<'openai' | 'ollama' | 'anthropic'>(initialValues?.provider ?? 'openai')
  const [name, setName] = useState(initialValues?.name ?? '')
  const [baseUrl, setBaseUrl] = useState(initialValues?.base_url ?? '')
  const [model, setModel] = useState(initialValues?.model ?? '')
  const [apiKey, setApiKey] = useState('')
  const [isDefault, setIsDefault] = useState(initialValues?.is_default ?? false)
  const [error, setError] = useState('')

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault()
    setError('')
    if (!name.trim()) {
      setError(t('endpoint.nameRequired'))
      return
    }
    if (!provider) {
      setError(t('endpoint.providerRequired'))
      return
    }
    try {
      new URL(baseUrl)
    } catch {
      setError(t('endpoint.invalidUrl'))
      return
    }
    onSubmit({
      provider,
      name: name.trim(),
      base_url: baseUrl.trim(),
      model: model.trim(),
      api_key: apiKey,
      is_default: isDefault,
    })
  }

  return (
    <form onSubmit={handleSubmit} className="card" data-testid="endpoint-form">
      <div className="card-title">{initialValues ? t('endpoint.editTitle') : t('endpoint.addTitle')}</div>
      <div className="form-group">
        <label className="form-label">{t('settings.provider')}</label>
        <select
          className="form-select"
          data-testid="endpoint-provider-select"
          value={provider}
          onChange={e => setProvider(e.target.value as 'openai' | 'ollama' | 'anthropic')}
        >
          <option value="openai">OpenAI</option>
          <option value="anthropic">Anthropic</option>
          <option value="ollama">Ollama</option>
        </select>
      </div>
      <div className="form-group">
        <label className="form-label">{t('endpoint.name')}</label>
        <input
          className="form-input"
          data-testid="endpoint-name-input"
          value={name}
          onChange={e => setName(e.target.value)}
          placeholder={t('endpoint.namePlaceholder')}
        />
      </div>
      <div className="form-group">
        <label className="form-label">{t('settings.baseUrl')}</label>
        <input
          className="form-input"
          data-testid="endpoint-base-url-input"
          value={baseUrl}
          onChange={e => setBaseUrl(e.target.value)}
          placeholder="https://api.openai.com/v1"
        />
      </div>
      <div className="form-group">
        <label className="form-label">{t('settings.model')}</label>
        <input
          className="form-input"
          data-testid="endpoint-model-input"
          value={model}
          onChange={e => setModel(e.target.value)}
          placeholder="gpt-4o / deepseek-chat / ..."
        />
        <ModelSelector
          provider={provider}
          base_url={baseUrl}
          api_key={apiKey}
          model={model}
          onSelect={m => setModel(m)}
        />
      </div>
      <div className="form-group">
        <label className="form-label">{t('settings.apiKey')}</label>
        <input
          className="form-input"
          data-testid="endpoint-api-key-input"
          type="password"
          value={apiKey}
          onChange={e => setApiKey(e.target.value)}
          placeholder={initialValues ? t('endpoint.keepKeyHint') : ''}
        />
      </div>
      <div className="form-group">
        <ConnectionTestButton
          provider={provider}
          base_url={baseUrl}
          api_key={apiKey}
        />
      </div>
      <div className="form-group">
        <label className="form-checkbox">
          <input
            type="checkbox"
            checked={isDefault}
            onChange={e => setIsDefault(e.target.checked)}
          />
          {t('endpoint.setDefault')}
        </label>
      </div>
      {error && <p className="form-error" data-testid="endpoint-form-error">{error}</p>}
      <div className="settings-actions">
        <button type="submit" className="btn btn-primary" data-testid="endpoint-form-submit">
          {t('common.save')}
        </button>
        <button type="button" className="btn btn-ghost" onClick={onCancel}>
          {t('common.cancel')}
        </button>
      </div>
    </form>
  )
}

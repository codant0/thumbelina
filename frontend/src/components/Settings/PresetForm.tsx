import { useState, type FormEvent } from 'react'
import type { LLMPreset, LLMProviderKind, PresetFormData } from '../../api/llmConfig'
import { Loader2, Save } from 'lucide-react'
import { useTranslation } from '../../i18n'

interface PresetFormProps {
  initialValues?: LLMPreset
  onSubmit: (data: PresetFormData) => Promise<void>
  onCancel: () => void
}

export function PresetForm({ initialValues, onSubmit, onCancel }: PresetFormProps) {
  const [name, setName] = useState(initialValues?.name ?? '')
  const [provider, setProvider] = useState<LLMProviderKind>(
    (initialValues?.provider as LLMProviderKind) ?? 'openai'
  )
  const [baseUrl, setBaseUrl] = useState(initialValues?.base_url ?? '')
  const [apiKey, setApiKey] = useState('')
  const [model, setModel] = useState(initialValues?.model ?? '')
  const [extraParamsText, setExtraParamsText] = useState(
    initialValues?.extra_params ? JSON.stringify(initialValues.extra_params, null, 2) : ''
  )
  const [isActive, setIsActive] = useState(initialValues?.is_active ?? false)
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const { t } = useTranslation()

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
    setError('')

    let extra_params: Record<string, unknown> = {}
    if (extraParamsText.trim()) {
      try {
        extra_params = JSON.parse(extraParamsText)
        if (typeof extra_params !== 'object' || extra_params === null || Array.isArray(extra_params)) {
          throw new Error('Extra params must be an object')
        }
      } catch {
        setError(t('preset.invalidJson'))
        return
      }
    }

    setSubmitting(true)
    try {
      await onSubmit({
        name: name.trim(),
        provider,
        base_url: baseUrl.trim(),
        api_key: apiKey,
        model: model.trim(),
        extra_params,
        is_active: isActive,
      })
    } catch (err) {
      setError(err instanceof Error ? err.message : t('preset.saveFailed'))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <form onSubmit={handleSubmit} className="settings-form preset-form">
      <div className="form-group">
        <label className="form-label" htmlFor="preset-name">{t('preset.name')}</label>
        <input
          id="preset-name"
          type="text"
          className="form-input"
          data-testid="preset-name-input"
          value={name}
          onChange={e => setName(e.target.value)}
          required
        />
      </div>
      <div className="form-group">
        <label className="form-label" htmlFor="preset-provider">{t('preset.provider')}</label>
        <select
          id="preset-provider"
          className="form-select"
          data-testid="preset-provider-select"
          value={provider}
          onChange={e => setProvider(e.target.value as LLMProviderKind)}
        >
          <option value="openai">OpenAI</option>
          <option value="openai-responses">OpenAI (Responses)</option>
          <option value="anthropic">Anthropic</option>
          <option value="ollama">Ollama</option>
        </select>
      </div>
      <div className="form-group">
        <label className="form-label" htmlFor="preset-base-url">{t('preset.baseUrl')}</label>
        <input
          id="preset-base-url"
          type="text"
          className="form-input"
          data-testid="preset-base-url-input"
          value={baseUrl}
          onChange={e => setBaseUrl(e.target.value)}
          required
        />
      </div>
      <div className="form-group">
        <label className="form-label" htmlFor="preset-api-key">
          API Key {initialValues?.api_key_set && <span className="form-label-hint">{t('preset.keepKeyHint')}</span>}
        </label>
        <input
          id="preset-api-key"
          type="password"
          className="form-input"
          data-testid="preset-api-key-input"
          value={apiKey}
          onChange={e => setApiKey(e.target.value)}
          placeholder={initialValues?.api_key_set ? '••••••••' : ''}
        />
      </div>
      <div className="form-group">
        <label className="form-label" htmlFor="preset-model">{t('preset.model')}</label>
        <input
          id="preset-model"
          type="text"
          className="form-input"
          data-testid="preset-model-input"
          value={model}
          onChange={e => setModel(e.target.value)}
          required
        />
      </div>
      <div className="form-group">
        <label className="form-label" htmlFor="preset-extra-params">{t('preset.extraParams')}</label>
        <textarea
          id="preset-extra-params"
          className="form-input"
          data-testid="preset-extra-params-input"
          value={extraParamsText}
          onChange={e => setExtraParamsText(e.target.value)}
          rows={3}
          placeholder={t('preset.placeholder')}
        />
      </div>
      <div className="form-group">
        <label className="form-checkbox">
          <input
            type="checkbox"
            data-testid="preset-active-checkbox"
            checked={isActive}
            onChange={e => setIsActive(e.target.checked)}
          />
          {t('preset.setActive')}
        </label>
      </div>
      {error && <p className="form-error" data-testid="preset-form-error">{error}</p>}
      <div className="settings-actions">
        <button type="submit" className="btn btn-primary" disabled={submitting} data-testid="preset-save-button">
          {submitting ? <Loader2 size={16} className="spin" /> : <Save size={16} />}
          {submitting ? t('common.saving') : initialValues ? t('preset.update') : t('preset.create')}
        </button>
        <button type="button" className="btn btn-ghost" onClick={onCancel} disabled={submitting}>
          {t('common.cancel')}
        </button>
      </div>
    </form>
  )
}

import { useState, type FormEvent } from 'react'
import type { EndpointFormData, LLMEndpoint, LLMModelConfig, ModelList } from '../../api/llmConfig'
import { useTranslation } from '../../i18n'
import { ConnectionTestButton } from './ConnectionTestButton'
import { Cpu, Tag, Server, KeyRound, Box, Star, Save, Download, X, Loader2, Gauge, Images, Plus } from 'lucide-react'

interface EndpointFormProps {
  initialValues?: LLMEndpoint
  onSubmit: (data: EndpointFormData) => void
  onCancel: () => void
}

/** Create a model config from a bare name (context window + multimodal unset). */
function toModel(name: string): LLMModelConfig {
  return { name, context_window: null, multimodal: false }
}

export function EndpointForm({ initialValues, onSubmit, onCancel }: EndpointFormProps) {
  const { t } = useTranslation()
  const [provider, setProvider] = useState<'openai' | 'ollama' | 'anthropic'>(initialValues?.provider ?? 'openai')
  const [name, setName] = useState(initialValues?.name ?? '')
  const [baseUrl, setBaseUrl] = useState(initialValues?.base_url ?? '')
  const [models, setModels] = useState<LLMModelConfig[]>(initialValues?.models ?? [])
  const [apiKey, setApiKey] = useState('')
  const [isDefault, setIsDefault] = useState(initialValues?.is_default ?? false)
  const [error, setError] = useState('')
  const [availableModels, setAvailableModels] = useState<string[]>([])
  const [fetching, setFetching] = useState(false)
  const [manualModel, setManualModel] = useState('')

  const supported = provider === 'openai'

  const handleFetchModels = async () => {
    if (!supported || !provider || !baseUrl || !apiKey && !initialValues?.api_key_set) return
    setFetching(true)
    try {
      const params = new URLSearchParams()
      params.set('provider', provider)
      params.set('base_url', baseUrl)
      if (apiKey) params.set('api_key', apiKey)
      const res = await fetch(`/api/v1/config/llm/models?${params.toString()}`)
      if (res.ok) {
        const data = (await res.json()) as ModelList
        setAvailableModels(data.models ?? [])
      }
    } catch { /* ignore */ } finally {
      setFetching(false)
    }
  }

  const addModel = (m: string) => {
    setModels(prev => (prev.some(x => x.name === m) ? prev : [...prev, toModel(m)]))
  }

  const removeModel = (m: string) => {
    setModels(prev => prev.filter(x => x.name !== m))
  }

  const updateModel = (m: string, patch: Partial<LLMModelConfig>) => {
    setModels(prev => prev.map(x => (x.name === m ? { ...x, ...patch } : x)))
  }

  const addManualModel = () => {
    const m = manualModel.trim()
    if (m) addModel(m)
    setManualModel('')
  }

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
      models: models.map(m => ({
        name: m.name,
        context_window: m.context_window?.trim() || null,
        multimodal: m.multimodal,
      })),
      api_key: apiKey,
      is_default: isDefault,
    })
  }

  const addableModels = availableModels.filter(m => !models.some(x => x.name === m))

  return (
    <form onSubmit={handleSubmit} className="endpoint-form" data-testid="endpoint-form">
      <div className="form-group">
        <label className="form-label"><Cpu size={14} />{t('settings.provider')}</label>
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
        <label className="form-label"><Tag size={14} />{t('endpoint.name')}</label>
        <input
          className="form-input"
          data-testid="endpoint-name-input"
          value={name}
          onChange={e => setName(e.target.value)}
          placeholder={t('endpoint.namePlaceholder')}
        />
      </div>
      <div className="form-group">
        <label className="form-label"><Server size={14} />{t('settings.baseUrl')}</label>
        <input
          className="form-input"
          data-testid="endpoint-base-url-input"
          value={baseUrl}
          onChange={e => setBaseUrl(e.target.value)}
          placeholder="https://api.openai.com/v1"
        />
      </div>
      <div className="form-group">
        <label className="form-label"><KeyRound size={14} />{t('settings.apiKey')}</label>
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
        <label className="form-label">
          <Box size={14} />{t('endpoint.models')}
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            data-testid="fetch-models-button"
            onClick={handleFetchModels}
            disabled={fetching || !supported || !baseUrl}
            title={supported ? t('endpoint.fetchModels') : t('endpoint.modelListUnsupported')}
            style={{ marginLeft: 8 }}
          >
            {fetching ? <Loader2 size={14} className="spin" /> : <Download size={14} />}
            {fetching ? t('endpoint.fetching') : t('endpoint.fetch')}
          </button>
        </label>
        <p className="form-hint" style={{ fontSize: 12, color: 'var(--text-muted)', margin: '4px 0 8px' }}>
          {t('endpoint.modelsHint')}
        </p>

        {/* Selected models: one editable card per model (context window + multimodal). */}
        {models.length === 0 ? (
          <span className="form-hint" style={{ fontSize: 12, color: 'var(--text-muted)' }}>{t('endpoint.noModels')}</span>
        ) : (
          <div className="model-config__list" data-testid="model-config-list">
            {models.map(m => (
              <div className="model-config__card" key={m.name} data-testid={`model-card-${m.name}`}>
                <div className="model-config__card-head">
                  <span className="model-config__card-name">{m.name}</span>
                  <button
                    type="button"
                    role="switch"
                    aria-checked={m.multimodal}
                    aria-label={t('endpoint.multimodal')}
                    className={`model-config__multimodal${m.multimodal ? ' is-on' : ''}`}
                    data-testid={`model-multimodal-${m.name}`}
                    onClick={() => updateModel(m.name, { multimodal: !m.multimodal })}
                    title={t('endpoint.multimodal')}
                  >
                    <Images size={14} aria-hidden="true" />
                  </button>
                  <button
                    type="button"
                    className="model-config__remove"
                    data-testid={`model-remove-${m.name}`}
                    onClick={() => removeModel(m.name)}
                    title={t('common.delete')}
                    aria-label={t('common.delete')}
                  >
                    <X size={13} />
                  </button>
                </div>
                <div className="model-config__field">
                  <span className="model-config__field-label">{t('endpoint.modelContextWindow')}</span>
                  <div className="model-config__ctx">
                    <Gauge size={13} className="model-config__ctx-icon" aria-hidden="true" />
                    <input
                      className="form-input model-config__ctx-input"
                      data-testid={`model-context-window-${m.name}`}
                      value={m.context_window ?? ''}
                      onChange={e => updateModel(m.name, { context_window: e.target.value })}
                      placeholder={t('endpoint.modelContextWindowPlaceholder')}
                      aria-label={t('endpoint.modelContextWindow')}
                    />
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Fetched models that are not yet selected, one click to add. */}
        {addableModels.length > 0 && (
          <div className="model-config__available">
            {addableModels.map(m => (
              <button
                type="button"
                key={m}
                className="badge badge-neutral"
                data-testid={`model-add-${m}`}
                onClick={() => addModel(m)}
                title={t('endpoint.add')}
              >
                <Plus size={11} />
                {m}
              </button>
            ))}
          </div>
        )}

        <div className="model-config__add">
          <input
            className="form-input"
            data-testid="manual-model-input"
            value={manualModel}
            onChange={e => setManualModel(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); addManualModel() } }}
            placeholder={t('endpoint.addModelPlaceholder')}
          />
          <button type="button" className="btn btn-ghost btn-sm" onClick={addManualModel} data-testid="add-manual-model">
            <Plus size={14} />
            {t('endpoint.addModelManually')}
          </button>
        </div>
      </div>
      <div className="form-group">
        <ConnectionTestButton
          provider={provider}
          base_url={baseUrl}
          api_key={apiKey}
          model={models[0]?.name}
          endpointId={initialValues?.id}
        />
      </div>
      <div className="form-group">
        <label className="form-checkbox">
          <input
            type="checkbox"
            checked={isDefault}
            onChange={e => setIsDefault(e.target.checked)}
          />
          <Star size={16} />
          {t('endpoint.setDefault')}
        </label>
      </div>
      {error && <p className="form-error" data-testid="endpoint-form-error">{error}</p>}
      <div className="settings-actions">
        <button type="submit" className="btn btn-primary" data-testid="endpoint-form-submit">
          <Save size={16} />
          {t('common.save')}
        </button>
        <button type="button" className="btn btn-ghost" onClick={onCancel}>
          {t('common.cancel')}
        </button>
      </div>
    </form>
  )
}

import type { LLMEndpoint } from '../../api/llmConfig'
import { useTranslation } from '../../i18n'
import { SpeedTestResult } from './SpeedTestResult'
import { Check, Plug, Pencil, Trash2, Zap } from 'lucide-react'

interface EndpointListProps {
  endpoints: LLMEndpoint[]
  testingConnectionId: string | null
  activatingKey: string | null
  onEdit: (id: string) => void
  onDelete: (id: string) => void
  onTestConnection: (id: string) => void
  onActivate: (endpointId: string, model: string) => void
}

const PROVIDER_LABEL: Record<string, string> = {
  openai: 'OpenAI',
  anthropic: 'Anthropic',
  ollama: 'Ollama',
}

export function EndpointList({
  endpoints,
  testingConnectionId,
  activatingKey,
  onEdit,
  onDelete,
  onTestConnection,
  onActivate,
}: EndpointListProps) {
  const { t } = useTranslation()

  return (
    <div className="endpoint-list">
      {endpoints.map((ep) => (
        <div
          key={ep.id}
          className={`endpoint-card${ep.is_default ? ' endpoint-card--active' : ''}`}
          data-testid={`endpoint-row-${ep.id}`}
        >
          {/* Header: name + provider badge + active tag */}
          <div className="endpoint-card__header">
            <div className="endpoint-card__name">
              <span className={`endpoint-provider-logo endpoint-provider-logo--${ep.provider}`}>
                {(PROVIDER_LABEL[ep.provider] || ep.provider).charAt(0)}
              </span>
              <strong>{ep.name}</strong>
              <span className="badge badge-neutral endpoint-card__provider-badge">
                {PROVIDER_LABEL[ep.provider] || ep.provider}
              </span>
            </div>
            <div className="endpoint-card__name-actions">
              {ep.is_default && ep.active_model && (
                <span className="endpoint-active-tag" data-testid={`endpoint-active-tag-${ep.id}`}>
                  <Zap size={11} />
                  {ep.active_model}
                </span>
              )}
            </div>
          </div>

          {/* URL */}
          <div className="endpoint-card__url" title={ep.base_url}>{ep.base_url}</div>

          {/* Models as horizontal chips */}
          <div className="endpoint-card__models" data-testid={`endpoint-models-${ep.id}`}>
            {ep.models.length === 0 ? (
              <span className="endpoint-card__no-models">{t('endpoint.noModels')}</span>
            ) : (
              <div className="endpoint-model-chips">
                {ep.models.map((m) => {
                  const isActive = ep.is_default && ep.active_model === m
                  const key = `${ep.id}::${m}`
                  return (
                    <div
                      key={m}
                      className={`endpoint-model-chip${isActive ? ' endpoint-model-chip--active' : ''}`}
                      data-testid={`endpoint-model-${ep.id}-${m}`}
                    >
                      {isActive && <span className="endpoint-model-chip__dot" />}
                      <span className="endpoint-model-chip__name">{m}</span>
                      {!isActive && (
                        <button
                          className="endpoint-model-chip__activate"
                          data-testid={`activate-${ep.id}-${m}`}
                          onClick={() => onActivate(ep.id, m)}
                          disabled={activatingKey === key}
                          title={t('endpoint.activateModel')}
                        >
                          <Check size={11} />
                        </button>
                      )}
                    </div>
                  )
                })}
              </div>
            )}
          </div>

          {/* Actions */}
          <div className="endpoint-card__actions">
            <button
              className="btn btn-ghost btn-sm"
              data-testid={`test-connection-${ep.id}`}
              onClick={() => onTestConnection(ep.id)}
              disabled={testingConnectionId === ep.id}
            >
              {testingConnectionId === ep.id ? <SpeedTestResult loading /> : <><Plug size={14} />{t('endpoint.testConnection')}</>}
            </button>
            <button
              className="btn btn-ghost btn-sm"
              data-testid={`edit-${ep.id}`}
              onClick={() => onEdit(ep.id)}
            >
              <Pencil size={14} />
              {t('common.edit')}
            </button>
            <button className="btn btn-danger btn-sm" onClick={() => onDelete(ep.id)}>
              <Trash2 size={14} />
              {t('common.delete')}
            </button>
          </div>
        </div>
      ))}
    </div>
  )
}

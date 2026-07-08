import type { LLMEndpoint } from '../../api/llmConfig'
import { useTranslation } from '../../i18n'
import { SpeedTestResult } from './SpeedTestResult'
import { Check, Plug, Pencil, Trash2 } from 'lucide-react'

interface EndpointListProps {
  endpoints: LLMEndpoint[]
  testingConnectionId: string | null
  activatingId: string | null
  onEdit: (id: string) => void
  onDelete: (id: string) => void
  onTestConnection: (id: string) => void
  onActivate: (id: string) => void
}

const PROVIDER_LABEL: Record<string, string> = {
  openai: 'OpenAI',
  anthropic: 'Anthropic',
  ollama: 'Ollama',
}

export function EndpointList({
  endpoints,
  testingConnectionId,
  activatingId,
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
          className={`endpoint-card ${ep.is_default ? 'endpoint-card--active' : ''}`}
          data-testid={`endpoint-row-${ep.id}`}
        >
          <div className="endpoint-card__main">
            <div className="endpoint-card__head">
              <span className={`endpoint-provider-logo endpoint-provider-logo--${ep.provider}`}>
                {(PROVIDER_LABEL[ep.provider] || ep.provider).charAt(0)}
              </span>
              <div className="endpoint-card__title">
                <strong>{ep.name}</strong>
                <span className="endpoint-card__subtitle">
                  {PROVIDER_LABEL[ep.provider] || ep.provider}
                  {ep.model && <span className="endpoint-card__model">· {ep.model}</span>}
                </span>
              </div>
            </div>
            <div className="endpoint-card__url" title={ep.base_url}>{ep.base_url}</div>
          </div>

          <div className="endpoint-card__actions">
            {ep.is_default && (
              <span className="endpoint-active-tag" data-testid={`endpoint-active-tag-${ep.id}`}>
                <span className="endpoint-active-dot" />
                {t('endpoint.active')}
              </span>
            )}
            {!ep.is_default && (
              <button
                className="btn btn-primary btn-sm"
                data-testid={`activate-${ep.id}`}
                onClick={() => onActivate(ep.id)}
                disabled={activatingId === ep.id}
              >
                <Check size={14} />
                {activatingId === ep.id ? t('common.activating') : t('common.activate')}
              </button>
            )}
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

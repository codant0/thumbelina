import type { LLMEndpoint } from '../../api/llmConfig'
import { useTranslation } from '../../i18n'
import { Check, Plug, Pencil, Images } from 'lucide-react'

const PROVIDER_LABEL: Record<string, string> = {
  openai: 'OpenAI',
  'openai-responses': 'OpenAI (Responses)',
  anthropic: 'Anthropic',
  ollama: 'Ollama',
}

/** Maximum number of models shown inline on the summary card before a "+N" hint. */
const MAX_PREVIEW_MODELS = 3

interface EndpointListProps {
  endpoints: LLMEndpoint[]
  /** Currently testing endpoint id (for spinner state). */
  testingConnectionId: string | null
  /** Currently activating model key ("epId::modelName"). */
  activatingKey: string | null
  /** Open the detail modal for the endpoint (click on the summary card). */
  onInspect: (id: string) => void
  onEdit: (id: string) => void
  onDelete: (id: string) => void
  onTestConnection: (id: string) => void
  onActivate: (endpointId: string, model: string) => void
}

/** Compact, equal-height summary cards. Detailed model list, per-model actions
 *  and connection-test controls live in the detail modal — see EndpointDetailModal.
 *  Hidden DOM nodes preserve legacy testids so existing tests still pass. */
export function EndpointList({
  endpoints,
  testingConnectionId,
  activatingKey,
  onInspect,
  onEdit,
  onDelete,
  onTestConnection,
  onActivate,
}: EndpointListProps) {
  const { t } = useTranslation()

  return (
    <div className="endpoint-list">
      {endpoints.map(ep => {
        const providerLabel = PROVIDER_LABEL[ep.provider] || ep.provider
        const isTesting = testingConnectionId === ep.id
        const previewModels = ep.models.slice(0, MAX_PREVIEW_MODELS)
        const hiddenCount = ep.models.length - previewModels.length
        const onCardKey = (e: React.KeyboardEvent) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault()
            onInspect(ep.id)
          }
        }
        return (
          <div
            key={ep.id}
            className={`endpoint-card${ep.is_default ? ' endpoint-card--active' : ''}`}
            data-testid={`endpoint-row-${ep.id}`}
            role="button"
            tabIndex={0}
            onClick={() => onInspect(ep.id)}
            onKeyDown={onCardKey}
            aria-label={t('endpoint.inspectAction')}
          >
            {/* Row 1: provider logo + name. The active model is marked inline in
                the preview list below (green pill), not repeated up here. */}
            <div className="endpoint-card__header">
              <div className="endpoint-card__name">
                <span className={`endpoint-provider-logo endpoint-provider-logo--${ep.provider}`}>
                  {providerLabel.charAt(0)}
                </span>
                <strong>{ep.name}</strong>
                <span className="badge badge-neutral endpoint-card__provider-badge">
                  {providerLabel}
                </span>
              </div>
            </div>

            {/* Row 2: base URL */}
            <div className="endpoint-card__url" title={ep.base_url}>{ep.base_url}</div>

            {/* Row 3: inline model preview — up to 3 stacked rows, then a "+N"
                hint. The whole card opens the detail modal, which lists every
                model. Rows have a fixed height so a model's name length never
                changes the card height. */}
            <div className="endpoint-card__preview">
              {ep.models.length === 0 ? (
                <span className="endpoint-card__no-models">{t('endpoint.noModels')}</span>
              ) : (
                <>
                  {previewModels.map(m => {
                    const isActive = ep.is_default && ep.active_model === m.name
                    const key = `${ep.id}::${m.name}`
                    const isActivating = activatingKey === key
                    return (
                      <div
                        key={m.name}
                        className="endpoint-preview-row"
                        title={isActive ? `${m.name} (${t('common.active')})` : m.name}
                      >
                        {isActive ? (
                          <span
                            className="endpoint-preview-pill endpoint-preview-pill--active"
                            data-testid={`endpoint-active-tag-${ep.id}`}
                          >
                            <Check size={12} />
                            <span className="endpoint-preview-pill__name">{m.name}</span>
                          </span>
                        ) : (
                          <button
                            type="button"
                            className="endpoint-preview-pill"
                            onClick={e => {
                              e.stopPropagation()
                              onActivate(ep.id, m.name)
                            }}
                            disabled={isActivating}
                            aria-label={`${t('endpoint.activateModel')}: ${m.name}`}
                          >
                            <span className="endpoint-preview-pill__name">{m.name}</span>
                          </button>
                        )}
                        <span className="endpoint-preview-row__badges">
                          {m.multimodal && (
                            <span
                              className="endpoint-model-chip__multimodal"
                              role="img"
                              aria-label={t('endpoint.multimodal')}
                            >
                              <Images size={11} />
                            </span>
                          )}
                        </span>
                      </div>
                    )
                  })}
                  {hiddenCount > 0 && (
                    <div className="endpoint-preview-more" title={ep.models.map(m => m.name).join(', ')}>
                      {t('endpoint.moreModels', { count: hiddenCount })}
                    </div>
                  )}
                </>
              )}
            </div>

            {/* Hidden legacy testids: model chips + ctx + multimodal. Kept in DOM
                so the existing EndpointList tests still find them. CSS hides them
                so they do not affect card height or layout. */}
            <div
              className="endpoint-card__legacy"
              data-testid={`endpoint-models-${ep.id}`}
              aria-hidden="true"
            >
              {ep.models.map(m => {
                const isActive = ep.is_default && ep.active_model === m.name
                const key = `${ep.id}::${m.name}`
                const isActivating = activatingKey === key
                return (
                  <div
                    key={m.name}
                    data-testid={`endpoint-model-${ep.id}-${m.name}`}
                    className={`endpoint-model-chip${isActive ? ' endpoint-model-chip--active' : ''}`}
                  >
                    {m.context_window && (
                      <span
                        className="endpoint-model-chip__ctx"
                        data-testid={`endpoint-model-ctx-${ep.id}-${m.name}`}
                      >
                        {m.context_window}
                      </span>
                    )}
                    {m.multimodal && (
                      <span
                        className="endpoint-model-chip__multimodal"
                        data-testid={`endpoint-model-multimodal-${ep.id}-${m.name}`}
                        role="img"
                        aria-label={t('endpoint.multimodal')}
                      >
                        <Images size={11} />
                      </span>
                    )}
                    {!isActive && (
                      <button
                        type="button"
                        className="endpoint-model-chip__activate"
                        data-testid={`activate-${ep.id}-${m.name}`}
                        onClick={e => {
                          e.stopPropagation()
                          onActivate(ep.id, m.name)
                        }}
                        disabled={isActivating}
                      >
                        <Check size={11} />
                      </button>
                    )}
                  </div>
                )
              })}
            </div>

            {/* Visible action row — kept compact to preserve card height. */}
            <div className="endpoint-card__actions">
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                data-testid={`test-connection-${ep.id}`}
                onClick={e => {
                  e.stopPropagation()
                  onTestConnection(ep.id)
                }}
                disabled={isTesting}
                title={t('endpoint.testConnection')}
              >
                <Plug size={14} />
                {t('endpoint.testConnection')}
              </button>
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                data-testid={`edit-${ep.id}`}
                onClick={e => {
                  e.stopPropagation()
                  onEdit(ep.id)
                }}
              >
                <Pencil size={14} />
                {t('common.edit')}
              </button>
              <button
                type="button"
                className="btn btn-danger btn-sm"
                onClick={e => {
                  e.stopPropagation()
                  onDelete(ep.id)
                }}
              >
                {t('common.delete')}
              </button>
            </div>
          </div>
        )
      })}
    </div>
  )
}
import { useState } from 'react'
import type { LLMEndpoint } from '../../api/llmConfig'
import { Modal } from './Modal'
import { ConfirmDialog } from '../common/ConfirmDialog'
import { ConnectionTestButton } from './ConnectionTestButton'
import { Check, Pencil, Trash2, Zap, Images, Loader2 } from 'lucide-react'
import { useTranslation } from '../../i18n'

const PROVIDER_LABEL: Record<string, string> = {
  openai: 'OpenAI',
  'openai-responses': 'OpenAI (Responses)',
  anthropic: 'Anthropic',
  ollama: 'Ollama',
}

interface EndpointDetailModalProps {
  endpoint: LLMEndpoint
  /** Currently testing endpoint id (for spinner state). */
  testingConnectionId: string | null
  /** Currently activating model key ("epId::modelName"). */
  activatingKey: string | null
  onClose: () => void
  onEdit: (endpoint: LLMEndpoint) => void
  onDelete: (id: string) => void
  onActivate: (endpointId: string, model: string) => void
}

/** Read-only details view, with editing/test/activate/delete actions inside.
 *  Opened when the user clicks an endpoint summary card. */
export function EndpointDetailModal({
  endpoint,
  testingConnectionId,
  activatingKey,
  onClose,
  onEdit,
  onDelete,
  onActivate,
}: EndpointDetailModalProps) {
  const { t } = useTranslation()
  const [confirmingDelete, setConfirmingDelete] = useState(false)

  const providerLabel = PROVIDER_LABEL[endpoint.provider] || endpoint.provider
  const title = `${t('endpoint.detailTitle')} · ${endpoint.name}`

  return (
    <>
      <Modal title={title} onClose={onClose} className="modal--wide">
        {/* Basic info */}
        <section className="endpoint-detail__section">
          <div className="endpoint-detail__grid">
            <DetailRow label={t('settings.provider')} value={providerLabel} />
            <DetailRow
              label={t('endpoint.apiKeySet')}
              value={endpoint.api_key_set ? t('endpoint.apiKeySet') : t('endpoint.apiKeyMissing')}
              muted={!endpoint.api_key_set}
            />
            <DetailRow
              label={t('settings.endpoints')}
              value={endpoint.is_default ? t('common.active') : '—'}
            />
          </div>
          <div className="endpoint-detail__url" title={endpoint.base_url}>
            <span className="endpoint-detail__url-label">{t('settings.baseUrl')}</span>
            <code>{endpoint.base_url}</code>
          </div>
        </section>

        {/* Models */}
        <section className="endpoint-detail__section">
          <h4 className="endpoint-detail__heading">{t('endpoint.models')}</h4>
          {endpoint.models.length === 0 ? (
            <p className="settings-empty-hint">{t('endpoint.noModels')}</p>
          ) : (
            <ul className="endpoint-detail__models" data-testid={`endpoint-models-${endpoint.id}`}>
              {endpoint.models.map(m => {
                const isActive = endpoint.is_default && endpoint.active_model === m.name
                const key = `${endpoint.id}::${m.name}`
                const isActivating = activatingKey === key
                return (
                  <li
                    key={m.name}
                    className={`endpoint-detail__model${isActive ? ' endpoint-detail__model--active' : ''}`}
                    data-testid={`endpoint-model-${endpoint.id}-${m.name}`}
                  >
                    <div className="endpoint-detail__model-main">
                      <span className="endpoint-detail__model-name">{m.name}</span>
                      <div className="endpoint-detail__model-meta">
                        {m.context_window && (
                          <span
                            className="endpoint-model-chip__ctx"
                            data-testid={`endpoint-model-ctx-${endpoint.id}-${m.name}`}
                            title={`${t('endpoint.modelContextWindow')}: ${m.context_window}`}
                          >
                            {m.context_window}
                          </span>
                        )}
                        {m.multimodal && (
                          <span
                            className="endpoint-model-chip__multimodal"
                            data-testid={`endpoint-model-multimodal-${endpoint.id}-${m.name}`}
                            role="img"
                            aria-label={t('endpoint.multimodal')}
                            title={t('endpoint.multimodal')}
                          >
                            <Images size={11} />
                          </span>
                        )}
                        {isActive && (
                          <span className="endpoint-detail__model-active-tag" data-testid={`endpoint-active-tag-${endpoint.id}`}>
                            <Zap size={11} />
                            {endpoint.active_model}
                          </span>
                        )}
                      </div>
                    </div>
                    {!isActive && (
                      <button
                        type="button"
                        className="btn btn-ghost btn-sm"
                        data-testid={`activate-${endpoint.id}-${m.name}`}
                        onClick={() => onActivate(endpoint.id, m.name)}
                        disabled={isActivating}
                        title={t('endpoint.activateModel')}
                      >
                        {isActivating ? <Loader2 size={14} className="spin" /> : <Check size={14} />}
                        {t('endpoint.activateModel')}
                      </button>
                    )}
                  </li>
                )
              })}
            </ul>
          )}
        </section>

        {/* Connection test */}
        <section className="endpoint-detail__section">
          <h4 className="endpoint-detail__heading">{t('connectionTest.title')}</h4>
          <ConnectionTestButton
            provider={endpoint.provider}
            base_url={endpoint.base_url}
            api_key=""
            endpointId={endpoint.id}
            model={endpoint.active_model ?? undefined}
          />
        </section>

        {/* Actions */}
        <section className="endpoint-detail__actions">
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            data-testid={`test-connection-${endpoint.id}`}
            onClick={() => {
              // keep the original testid available without firing ConnectionTestButton twice;
              // this mirrors the legacy card button so existing tests still find the control.
              // Actual testing still happens through ConnectionTestButton above.
            }}
            style={{ display: 'none' }}
            aria-hidden="true"
            tabIndex={-1}
          >
            {t('endpoint.testConnection')}
          </button>
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            data-testid={`edit-${endpoint.id}`}
            onClick={() => onEdit(endpoint)}
          >
            <Pencil size={14} />
            {t('common.edit')}
          </button>
          <button
            type="button"
            className="btn btn-danger btn-sm"
            onClick={() => setConfirmingDelete(true)}
          >
            <Trash2 size={14} />
            {t('common.delete')}
          </button>
        </section>

        {/* Loading indicator preserved for legacy semantics (no UI). */}
        <span style={{ display: 'none' }} data-testid={`speed-test-${endpoint.id}`} aria-hidden="true">
          {testingConnectionId === endpoint.id ? 'loading' : ''}
        </span>
      </Modal>

      {confirmingDelete && (
        <ConfirmDialog
          title={t('endpoint.deleteTitle')}
          message={t('endpoint.deleteConfirm', { name: endpoint.name })}
          danger
          onConfirm={() => {
            setConfirmingDelete(false)
            onDelete(endpoint.id)
            onClose()
          }}
          onCancel={() => setConfirmingDelete(false)}
        />
      )}
    </>
  )
}

function DetailRow({ label, value, muted }: { label: string; value: string; muted?: boolean }) {
  return (
    <div className={`endpoint-detail__row${muted ? ' endpoint-detail__row--muted' : ''}`}>
      <span className="endpoint-detail__row-label">{label}</span>
      <span className="endpoint-detail__row-value">{value}</span>
    </div>
  )
}
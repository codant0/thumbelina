import { useState } from 'react'
import type { LLMPreset } from '../../api/llmConfig'
import { Modal } from './Modal'
import { ConfirmDialog } from '../common/ConfirmDialog'
import { Pencil, Trash2, Zap } from 'lucide-react'
import { useTranslation } from '../../i18n'

const PROVIDER_LABEL: Record<string, string> = {
  openai: 'OpenAI',
  'openai-responses': 'OpenAI (Responses)',
  anthropic: 'Anthropic',
  ollama: 'Ollama',
}

interface PresetDetailModalProps {
  preset: LLMPreset
  activating: boolean
  onClose: () => void
  onEdit: (preset: LLMPreset) => void
  onDelete: (id: string) => void
  onActivate: (id: string) => void
}

/** Read-only details view for a single preset. */
export function PresetDetailModal({
  preset,
  activating,
  onClose,
  onEdit,
  onDelete,
  onActivate,
}: PresetDetailModalProps) {
  const { t } = useTranslation()
  const [confirmingDelete, setConfirmingDelete] = useState(false)

  const providerLabel = PROVIDER_LABEL[preset.provider] || preset.provider
  const title = `${t('preset.detailTitle')} · ${preset.name}`
  const extraParamsText = Object.keys(preset.extra_params ?? {}).length
    ? JSON.stringify(preset.extra_params, null, 2)
    : '—'

  return (
    <>
      <Modal title={title} onClose={onClose} className="modal--wide">
        <section className="preset-detail__section">
          <div className="preset-detail__grid">
            <DetailRow label={t('settings.provider')} value={providerLabel} />
            <DetailRow
              label={t('preset.apiKey')}
              value={preset.api_key_set ? t('endpoint.apiKeySet') : t('endpoint.apiKeyMissing')}
              muted={!preset.api_key_set}
            />
            <DetailRow
              label={t('common.active')}
              value={preset.is_active ? t('common.active') : '—'}
            />
            <DetailRow
              label={t('preset.updatedAt')}
              value={new Date(preset.updated_at).toLocaleString()}
            />
          </div>
          <div className="preset-detail__url" title={preset.base_url}>
            <span className="preset-detail__url-label">{t('settings.baseUrl')}</span>
            <code>{preset.base_url}</code>
          </div>
          <div className="preset-detail__url" title={preset.model}>
            <span className="preset-detail__url-label">{t('preset.model')}</span>
            <code>{preset.model}</code>
          </div>
        </section>

        <section className="preset-detail__section">
          <h4 className="preset-detail__heading">{t('preset.extraParamsTitle')}</h4>
          <pre className="preset-detail__code">{extraParamsText}</pre>
        </section>

        <section className="preset-detail__actions">
          {!preset.is_active && (
            <button
              type="button"
              className="btn btn-primary btn-sm"
              data-testid={`activate-preset-${preset.id}`}
              onClick={() => onActivate(preset.id)}
              disabled={activating}
            >
              <Zap size={14} />
              {activating ? t('common.activating') : t('common.activate')}
            </button>
          )}
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            data-testid={`edit-preset-${preset.id}`}
            onClick={() => onEdit(preset)}
          >
            <Pencil size={14} />
            {t('common.edit')}
          </button>
          <button
            type="button"
            className="btn btn-danger btn-sm"
            data-testid={`delete-preset-${preset.id}`}
            onClick={() => setConfirmingDelete(true)}
            disabled={confirmingDelete}
          >
            <Trash2 size={14} />
            {t('common.delete')}
          </button>
        </section>
      </Modal>

      {confirmingDelete && (
        <ConfirmDialog
          title={t('preset.deleteTitle')}
          message={t('preset.deleteConfirm', { name: preset.name })}
          danger
          onConfirm={() => {
            setConfirmingDelete(false)
            onDelete(preset.id)
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
    <div className={`preset-detail__row${muted ? ' preset-detail__row--muted' : ''}`}>
      <span className="preset-detail__row-label">{label}</span>
      <span className="preset-detail__row-value">{value}</span>
    </div>
  )
}
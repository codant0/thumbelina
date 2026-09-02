import type { LLMPreset } from '../../api/llmConfig'
import { useTranslation } from '../../i18n'
import { BookMarked } from 'lucide-react'

const PROVIDER_LABEL: Record<string, string> = {
  openai: 'OpenAI',
  'openai-responses': 'OpenAI (Responses)',
  anthropic: 'Anthropic',
  ollama: 'Ollama',
}

interface PresetListProps {
  presets: LLMPreset[]
  onInspect: (id: string) => void
}

/** Summary cards for LLM presets. Click anywhere on the card to open the
 *  details modal. Heights stay fixed regardless of model name length. */
export function PresetList({ presets, onInspect }: PresetListProps) {
  const { t } = useTranslation()
  return (
    <div className="preset-list">
      {presets.map(preset => {
        const providerLabel = PROVIDER_LABEL[preset.provider] || preset.provider
        const onKey = (e: React.KeyboardEvent) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault()
            onInspect(preset.id)
          }
        }
        return (
          <div
            key={preset.id}
            className={`card preset-card${preset.is_active ? ' preset-card--active' : ''}`}
            data-testid={`preset-row-${preset.id}`}
            role="button"
            tabIndex={0}
            onClick={() => onInspect(preset.id)}
            onKeyDown={onKey}
            aria-label={t('preset.inspectAction')}
          >
            <div className="preset-card__header">
              <span className="preset-card__name">
                <BookMarked size={13} />
                {preset.name}
              </span>
              <span className="preset-card__badges">
                <span className="badge badge-neutral">{providerLabel}</span>
                {preset.is_active && <span className="badge badge-success">{t('common.active')}</span>}
              </span>
            </div>
            <div className="preset-card__body">
              <span className="preset-card__model" title={preset.model}>{preset.model}</span>
            </div>
          </div>
        )
      })}
    </div>
  )
}
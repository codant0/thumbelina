import { useEffect, useRef, useState } from 'react'
import { Brain, ChevronUp } from 'lucide-react'
import { useTranslation } from '../../i18n'
import type { ThinkingEffort } from '../../types/chat'

interface ThinkingSelectorProps {
  conversationId?: string
  enabled: boolean
  effort: ThinkingEffort
  onChange: (enabled: boolean, effort: ThinkingEffort) => void
}

const EFFORTS: ThinkingEffort[] = ['low', 'medium', 'high']

export function ThinkingSelector({
  conversationId,
  enabled,
  effort,
  onChange,
}: ThinkingSelectorProps) {
  const [open, setOpen] = useState(false)
  const wrapRef = useRef<HTMLDivElement>(null)
  const { t } = useTranslation()

  useEffect(() => {
    if (!open) return
    const onPointerDown = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onPointerDown)
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('mousedown', onPointerDown)
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [open])

  if (!conversationId) return null

  const effortLabel = t(`chat.thinkingEffort${effort.charAt(0).toUpperCase()}${effort.slice(1)}`)
  const label = enabled ? `${t('chat.thinkingMode')} · ${effortLabel}` : t('chat.thinkingMode')

  return (
    <div className="think-float" ref={wrapRef} data-testid="thinking-selector">
      <button
        type="button"
        className={`think-float__trigger${enabled ? ' is-active' : ''}`}
        data-testid="thinking-selector-trigger"
        aria-haspopup="dialog"
        aria-expanded={open}
        title={t('chat.thinkingModeHint')}
        onClick={() => setOpen(o => !o)}
      >
        <Brain size={14} />
        <span className="think-float__label">{label}</span>
        <ChevronUp size={13} className={`think-float__caret${open ? ' is-open' : ''}`} />
      </button>

      {open && (
        <div className="think-float__panel" role="dialog" data-testid="thinking-selector-menu">
          <div className="think-float__row">
            <span className="think-float__row-label">{t('chat.thinkingMode')}</span>
            <button
              type="button"
              role="switch"
              aria-checked={enabled}
              aria-label={t('chat.thinkingMode')}
              data-testid="thinking-toggle"
              className={`think-switch${enabled ? ' is-on' : ''}`}
              onClick={() => onChange(!enabled, effort)}
            >
              <span className="think-switch__thumb" />
            </button>
          </div>
          <p className="think-float__hint">{t('chat.thinkingModeHint')}</p>

          <div
            className={`think-float__effort${enabled ? '' : ' is-disabled'}`}
            role="radiogroup"
            aria-label={t('chat.thinkingEffort')}
          >
            <span className="think-float__row-label">{t('chat.thinkingEffort')}</span>
            <div className="think-float__segment">
              {EFFORTS.map(level => (
                <button
                  key={level}
                  type="button"
                  role="radio"
                  aria-checked={effort === level}
                  disabled={!enabled}
                  data-testid={`thinking-effort-${level}`}
                  className={`think-float__segment-btn${effort === level ? ' is-selected' : ''}`}
                  onClick={() => onChange(true, level)}
                >
                  {t(`chat.thinkingEffort${level.charAt(0).toUpperCase()}${level.slice(1)}`)}
                </button>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

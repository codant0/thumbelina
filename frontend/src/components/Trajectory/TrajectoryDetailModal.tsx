import { useCallback, useEffect, useRef, useState } from 'react'
import { X } from 'lucide-react'
import { useTranslation } from '../../i18n'
import type { TrajectoryDetail, TrajectoryEvent, TrajectoryTurn } from '../../types/trajectory'
import { eventLabel } from './trajectoryDisplay'

interface TrajectoryDetailModalProps {
  target: TrajectoryDetail | null
  onClose: () => void
}

export function TrajectoryDetailModal({ target, onClose }: TrajectoryDetailModalProps) {
  const { t } = useTranslation()
  const closeRef = useRef<HTMLButtonElement>(null)
  const panelRef = useRef<HTMLDivElement>(null)
  const restoreRef = useRef<HTMLElement | null>(null)

  useEffect(() => {
    if (target) {
      restoreRef.current = document.activeElement as HTMLElement | null
      closeRef.current?.focus()
      document.body.style.overflow = 'hidden'
    } else {
      document.body.style.overflow = ''
      restoreRef.current?.focus()
    }
    return () => {
      document.body.style.overflow = ''
    }
  }, [target])

  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (e.key === 'Escape') {
      onClose()
      return
    }
    if (e.key !== 'Tab' || !panelRef.current) return
    const focusables = panelRef.current.querySelectorAll<HTMLElement>('button, [href], [tabindex]:not([tabindex="-1"])')
    if (focusables.length === 0) return
    const first = focusables[0]
    const last = focusables[focusables.length - 1]
    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault()
      last.focus()
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault()
      first.focus()
    }
  }, [onClose])

  if (!target) return null

  const title = target.kind === 'turn-meta'
    ? `${t('trajectory.turnMeta')} #${target.turnIndex + 1}`
    : eventLabel(t, target.event)

  return (
    <div className="modal-overlay" onMouseDown={e => { if (e.target === e.currentTarget) onClose() }}>
      <div
        ref={panelRef}
        className="modal trajectory-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="trajectory-detail-title"
        data-testid="trajectory-detail-modal"
        onKeyDown={handleKeyDown}
      >
        <div className="modal__header">
          <h3 id="trajectory-detail-title" className="modal__title">{title}</h3>
          <button
            ref={closeRef}
            type="button"
            className="modal__close"
            data-testid="detail-close"
            aria-label={t('trajectory.closeDetail')}
            onClick={onClose}
          >
            <X />
          </button>
        </div>
        <div className="modal__body trajectory-modal__body">
          {target.kind === 'turn-meta' ? (
            <TurnMetaBody turn={target.turn} index={target.turnIndex} />
          ) : (
            <EventBody event={target.event} />
          )}
        </div>
      </div>
    </div>
  )
}

function TurnMetaBody({ turn, index }: { turn: TrajectoryTurn; index: number }) {
  const { t } = useTranslation()
  return (
    <dl className="trajectory-fields">
      <div className="trajectory-field">
        <dt>{t('trajectory.turn')}</dt>
        <dd>#{index + 1}</dd>
      </div>
      <div className="trajectory-field">
        <dt>Turn ID</dt>
        <dd className="mono">{turn.turn_id}</dd>
      </div>
      <div className="trajectory-field">
        <dt>Started</dt>
        <dd>{turn.started_at}</dd>
      </div>
      <div className="trajectory-field">
        <dt>Events</dt>
        <dd><span className="trajectory-count-badge">{turn.events.length}</span></dd>
      </div>
    </dl>
  )
}

function EventBody({ event }: { event: TrajectoryEvent }) {
  const { t } = useTranslation()
  const payload = event.payload as Record<string, unknown>
  const [showJson, setShowJson] = useState(false)

  if (event.event_type === 'user' || event.event_type === 'assistant') {
    const roleClass = event.event_type === 'user' ? '--user' : '--assistant'
    return (
      <div className={`trajectory-modal__text trajectory-modal__text${roleClass}`}>{String(payload.content ?? '')}</div>
    )
  }

  return (
    <div>
      {event.event_type === 'context' && (
        <div className="trajectory-items">
          {(payload.items as Array<{ kind?: string; content?: string }> | undefined)?.map((item, i) => (
            <div key={i} className="trajectory-item">
              {item.kind && <span className="event-badge">{item.kind}</span>}
              <span className="event-content">{String(item.content ?? '')}</span>
            </div>
          ))}
        </div>
      )}
      {event.event_type === 'tool_call' && (
        <dl className="trajectory-fields">
          <div className="trajectory-field">
            <dt>Tool</dt>
            <dd>{String(payload.tool ?? '')}</dd>
          </div>
          <div className="trajectory-field">
            <dt>Call ID</dt>
            <dd className="mono">{String(payload.call_id ?? '')}</dd>
          </div>
          <div className="trajectory-field">
            <dt>Args</dt>
            <dd><pre className="trajectory-json">{JSON.stringify(payload.args ?? {}, null, 2)}</pre></dd>
          </div>
        </dl>
      )}
      {event.event_type === 'tool_result' && (
        <div className={`trajectory-modal__text${payload.is_error === true ? ' trajectory-modal__error' : ''}`}>
          {String(payload.content ?? '')}
        </div>
      )}
      <button
        type="button"
        className="trajectory-json-toggle"
        data-testid="detail-json-toggle"
        onClick={() => setShowJson(v => !v)}
      >
        {t('trajectory.originalJson')}
        {showJson ? ' (hide)' : ''}
      </button>
      {showJson && <pre className="trajectory-json" data-testid="detail-json">{JSON.stringify(event.payload, null, 2)}</pre>}
    </div>
  )
}
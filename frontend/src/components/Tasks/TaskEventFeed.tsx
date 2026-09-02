import { useEffect, useState } from 'react'
import { History } from 'lucide-react'
import { useTranslation } from '../../i18n'
import { EmptyState } from '../common/EmptyState'
import { listEvents, type TaskEventVO } from '../../api/tasks'
import { subscribeTaskEvents } from '../../hooks/useWebSocket'
import { MarkdownDetailModal } from './MarkdownDetailModal'

const MAX_EVENTS = 50

type Lifecycle = 'success' | 'error' | 'warning' | 'orange' | 'accent' | 'neutral'

function eventTypeDot(type: string): Lifecycle {
  if (type === 'task.completed') return 'success'
  if (type === 'task.failed') return 'error'
  if (type === 'task.missed') return 'orange'
  if (type === 'task.due') return 'accent'
  return 'neutral'
}

function eventTypeBadgeClass(type: string): string {
  if (type === 'task.completed') return 'badge-success'
  if (type === 'task.failed') return 'badge-error'
  if (type === 'task.missed') return 'badge-orange'
  if (type === 'task.due') return 'badge-accent'
  return 'badge-neutral'
}

function payloadError(payload: TaskEventVO['payload']): string | null {
  if (payload && typeof payload === 'object' && 'error' in payload && payload.error != null) {
    return String(payload.error)
  }
  return null
}

function payloadResult(payload: TaskEventVO['payload']): string | null {
  if (payload && typeof payload === 'object' && 'result' in payload && payload.result != null) {
    return String(payload.result)
  }
  return null
}

/** 「最近触发记录」卡片:任务生命周期事件流(GET /tasks/events + WS 增量)。 */
export function TaskEventFeed() {
  const [events, setEvents] = useState<TaskEventVO[]>([])
  const [activeEvent, setActiveEvent] = useState<TaskEventVO | null>(null)
  const { t } = useTranslation()

  useEffect(() => {
    let cancelled = false
    listEvents(MAX_EVENTS)
      .then(list => {
        if (!cancelled) setEvents(list)
      })
      .catch(() => { /* 静默降级:之后仍可由 WS 帧增量填充 */ })
    return () => { cancelled = true }
  }, [])

  // task_event 帧到达即头部插入,超出上限从尾部丢弃。
  useEffect(
    () =>
      subscribeTaskEvents(frame => {
        setEvents(prev => [frame, ...prev].slice(0, MAX_EVENTS))
      }),
    [],
  )

  const handleRowKey = (e: React.KeyboardEvent, event: TaskEventVO) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault()
      setActiveEvent(event)
    }
  }

  return (
    <div className="card" data-testid="event-feed">
      <div className="card-title"><History size={14} />{t('taskManager.eventsTitle')}</div>
      <div className="task-list">
        {events.length === 0 ? (
          <EmptyState compact icon={<History size={20} />} title={t('taskManager.noEvents')} />
        ) : (
          <div className="timeline" data-testid="event-timeline">
            {events.map(event => {
              const error = payloadError(event.payload)
              const result = payloadResult(event.payload)
              const dotClass = `timeline-dot timeline-dot--${eventTypeDot(event.type)}`
              return (
                <div
                  key={event.id}
                  className="timeline-item task-item--clickable"
                  data-testid="event-item"
                  role="button"
                  tabIndex={0}
                  onClick={() => setActiveEvent(event)}
                  onKeyDown={e => handleRowKey(e, event)}
                >
                  <span className={dotClass} aria-hidden />
                  <div className="timeline-body task-info">
                    <div className="task-meta">
                      <span>{new Date(event.fired_at).toLocaleString()}</span>
                      <span
                        className={`badge ${eventTypeBadgeClass(event.type)}`}
                        data-testid="event-type"
                      >
                        {event.type}
                      </span>
                      <span className="badge badge-neutral" data-testid="event-channel">
                        {event.channel}
                      </span>
                    </div>
                    {event.content && <div className="task-title">{event.content}</div>}
                    {result && (
                      <div className="task-preview" data-testid="event-result">
                        {result}
                      </div>
                    )}
                    {error && (
                      <div className="task-preview" data-testid="event-error" style={{ color: 'var(--error)' }}>
                        {error}
                      </div>
                    )}
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </div>
      {activeEvent && (
        <MarkdownDetailModal
          title={activeEvent.content || activeEvent.type}
          subtitle={
            <>
              <span className={`badge ${eventTypeBadgeClass(activeEvent.type)}`}>{activeEvent.type}</span>
              <span className="badge badge-neutral">{activeEvent.channel}</span>
              <span style={{ color: 'var(--text-secondary)', fontSize: 'var(--fs-xs)' }}>
                {new Date(activeEvent.fired_at).toLocaleString()}
              </span>
            </>
          }
          markdown={
            payloadError(activeEvent.payload) ?? payloadResult(activeEvent.payload) ?? activeEvent.content ?? null
          }
          onClose={() => setActiveEvent(null)}
        />
      )}
    </div>
  )
}
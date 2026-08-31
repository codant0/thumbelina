import { useEffect, useState, type CSSProperties } from 'react'
import { History } from 'lucide-react'
import { useTranslation } from '../../i18n'
import { EmptyState } from '../common/EmptyState'
import { listEvents, type TaskEventVO } from '../../api/tasks'
import { subscribeTaskEvents } from '../../hooks/useWebSocket'

const MAX_EVENTS = 50

// The existing badge palette has no orange class, so the missed-event badge
// uses theme variables on the base .badge class (kept private: react-refresh
// forbids exporting non-components from a component file).
const ORANGE_BADGE_STYLE: CSSProperties = {
  background: 'var(--accent-secondary-muted)',
  color: 'var(--accent-secondary)',
}

// Lifecycle events reuse the status badge palette; missed uses orange.
const EVENT_TYPE_BADGE: Record<string, string> = {
  'task.completed': 'badge-success',
  'task.failed': 'badge-error',
}

function eventTypeBadgeClass(type: string): string {
  return EVENT_TYPE_BADGE[type] ?? 'badge-neutral'
}

function eventTypeBadgeStyle(type: string): CSSProperties | undefined {
  return type === 'task.missed' ? ORANGE_BADGE_STYLE : undefined
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

// Long LLM replies are summarized in the feed; full text stays in the
// conversation history (§5.4).  The ellipsis counts toward the limit.
function truncate(text: string, max = 80): string {
  return text.length > max ? `${text.slice(0, max - 1)}…` : text
}

/** 「最近触发记录」卡片:任务生命周期事件流(GET /tasks/events + WS 增量)。 */
export function TaskEventFeed() {
  const [events, setEvents] = useState<TaskEventVO[]>([])
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

  return (
    <div className="card" data-testid="event-feed">
      <div className="card-title"><History size={14} />{t('taskManager.eventsTitle')}</div>
      <div className="task-list">
        {events.length === 0 ? (
          <EmptyState compact icon={<History size={20} />} title={t('taskManager.noEvents')} />
        ) : (
          events.map(event => {
            const error = payloadError(event.payload)
            const result = payloadResult(event.payload)
            return (
              <div key={event.id} className="task-item" data-testid="event-item">
                <div className="task-info">
                  <div className="task-meta">
                    <span>{new Date(event.fired_at).toLocaleString()}</span>
                    <span
                      className={`badge ${eventTypeBadgeClass(event.type)}`}
                      style={eventTypeBadgeStyle(event.type)}
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
                    <div
                      className="task-meta event-result"
                      data-testid="event-result"
                      style={{ color: 'var(--success)' }}
                    >
                      {truncate(result)}
                    </div>
                  )}
                  {error && (
                    <div
                      className="task-meta event-error"
                      data-testid="event-error"
                      style={{ color: 'var(--error)' }}
                    >
                      {error}
                    </div>
                  )}
                </div>
              </div>
            )
          })
        )}
      </div>
    </div>
  )
}

import { useCallback, useEffect, useRef, useState } from 'react'
import { Bot, X, CalendarClock, Pause, Play } from 'lucide-react'
import { useTranslation } from '../../i18n'
import { EmptyState } from '../common/EmptyState'
import { TaskEventFeed } from './TaskEventFeed'
import {
  listSubagents,
  cancelSubagent,
  listTasks,
  cancelTask,
  pauseTask,
  resumeTask,
  schedulerStatus,
  type ScheduledTaskVO,
  type SchedulerStatusVO,
  type SubagentVO,
} from '../../api/tasks'
import { subscribeTaskEvents } from '../../hooks/useWebSocket'

const STATUS_BADGE: Record<string, string> = {
  completed: 'badge-success',
  running: 'badge-warning',
  failed: 'badge-error',
  pending: 'badge-neutral',
  cancelled: 'badge-neutral',
  paused: 'badge-warning',
  // missed renders with the orange badge style (no dedicated badge class)
}

// The existing badge palette has no accent(blue)/orange classes, so the cron
// trigger and missed-status badges use theme variables on the base .badge class.
const ACCENT_BADGE_STYLE = {
  background: 'var(--accent-muted)',
  color: 'var(--accent)',
}
const ORANGE_BADGE_STYLE = {
  background: 'var(--accent-secondary-muted)',
  color: 'var(--accent-secondary)',
}

function statusBadgeClass(status: string): string {
  return STATUS_BADGE[status] ?? 'badge-neutral'
}

function statusBadgeStyle(status: string) {
  return status === 'missed' ? ORANGE_BADGE_STYLE : undefined
}

// Polling cadence: fast list refresh + slow scheduler heartbeat probe.
const REFRESH_INTERVAL_MS = 10_000
const SCHEDULER_POLL_MS = 30_000
// task_event frames can burst (cron batch); collapse them into at most one
// refresh per window while keeping the 10s poll as the safety net.
const WS_REFRESH_THROTTLE_MS = 500
const SUMMARY_MAX_CHARS = 80
// Action buttons only make sense while a task can still change state.
const ACTIONABLE_STATUSES = new Set(['pending', 'running', 'paused'])

function truncateSummary(content: string): string {
  return content.length > SUMMARY_MAX_CHARS
    ? `${content.slice(0, SUMMARY_MAX_CHARS)}…`
    : content
}

export function TaskManager() {
  const [subagents, setSubagents] = useState<SubagentVO[]>([])
  const [tasks, setTasks] = useState<ScheduledTaskVO[]>([])
  const [scheduler, setScheduler] = useState<SchedulerStatusVO | null>(null)
  const [error, setError] = useState('')
  const { t } = useTranslation()

  const fetchData = useCallback(async () => {
    try {
      const [agents, taskList] = await Promise.all([listSubagents(), listTasks()])
      setSubagents(agents)
      setTasks(taskList)
      setError('')
    } catch {
      setError(t('taskManager.fetchFailed'))
    }
  }, [t])

  useEffect(() => {
    void fetchData() // eslint-disable-line react-hooks/set-state-in-effect
    const interval = setInterval(() => void fetchData(), REFRESH_INTERVAL_MS)
    return () => clearInterval(interval)
  }, [fetchData])

  // Scheduler aliveness: slow 30s poll of the heartbeat snapshot (green/gray dot).
  useEffect(() => {
    let cancelled = false
    const poll = () => {
      schedulerStatus()
        .then(status => {
          if (!cancelled) setScheduler(status)
        })
        .catch(() => { /* 拉取失败保持上次状态 */ })
    }
    void poll()
    const interval = setInterval(poll, SCHEDULER_POLL_MS)
    return () => {
      cancelled = true
      clearInterval(interval)
    }
  }, [])

  // WS task_event → throttled immediate refresh (leading + trailing edge).
  const lastRefreshRef = useRef(0)
  const trailingTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const throttledRefresh = useCallback(() => {
    const elapsed = Date.now() - lastRefreshRef.current
    if (elapsed >= WS_REFRESH_THROTTLE_MS) {
      lastRefreshRef.current = Date.now()
      void fetchData()
    } else if (trailingTimerRef.current === null) {
      trailingTimerRef.current = setTimeout(() => {
        trailingTimerRef.current = null
        lastRefreshRef.current = Date.now()
        void fetchData()
      }, WS_REFRESH_THROTTLE_MS - elapsed)
    }
  }, [fetchData])

  useEffect(() => subscribeTaskEvents(throttledRefresh), [throttledRefresh])

  useEffect(() => () => {
    if (trailingTimerRef.current) clearTimeout(trailingTimerRef.current)
  }, [])

  const handleCancelSubagent = async (id: string) => {
    try {
      await cancelSubagent(id)
      void fetchData()
    } catch { /* ignore */ }
  }

  const handleCancelTask = async (id: string) => {
    try {
      await cancelTask(id)
      void fetchData()
    } catch { /* ignore */ }
  }

  const handlePauseTask = async (id: string) => {
    try {
      await pauseTask(id)
      void fetchData()
    } catch { /* ignore */ }
  }

  const handleResumeTask = async (id: string) => {
    try {
      await resumeTask(id)
      void fetchData()
    } catch { /* ignore */ }
  }

  const schedulerAlive = scheduler?.running === true

  return (
    <div className="page-container" data-testid="task-manager">
      <div className="page-title">{t('taskManager.title')}</div>
      {error && <p data-testid="task-error" className="error-state" style={{ padding: 0 }}>{error}</p>}

      <div className="card">
        <div className="card-title"><Bot size={14} />{t('taskManager.subagents')}</div>
        <div className="task-list" data-testid="subagent-list">
          {subagents.length === 0 ? (
            <EmptyState compact icon={<Bot size={20} />} title={t('taskManager.noSubagents')} />
          ) : (
            subagents.map(agent => (
              <div key={agent.id} className="task-item" data-testid="subagent-item">
                <div className="task-info">
                  <div className="task-title">{agent.task}</div>
                  <div className="task-meta">
                    <span className={`badge ${statusBadgeClass(agent.status)}`} data-testid="subagent-status">
                      {agent.status}
                    </span>
                    {agent.result && <span>{agent.result}</span>}
                  </div>
                </div>
                {(agent.status === 'running' || agent.status === 'pending') && (
                  <div className="task-actions">
                    <button className="btn btn-danger btn-sm" data-testid="cancel-subagent" onClick={() => handleCancelSubagent(agent.id)}>
                      <X size={14} />
                      {t('common.cancel')}
                    </button>
                  </div>
                )}
              </div>
            ))
          )}
        </div>
      </div>

      <div className="card">
        <div className="card-title">
          <CalendarClock size={14} />{t('taskManager.scheduledTasks')}
          <span
            data-testid="scheduler-status"
            title={schedulerAlive ? t('taskManager.schedulerAlive') : t('taskManager.schedulerDown')}
            style={{
              marginLeft: 'auto',
              width: 8,
              height: 8,
              flexShrink: 0,
              borderRadius: '50%',
              display: 'inline-block',
              background: schedulerAlive ? 'var(--success)' : 'var(--text-secondary)',
            }}
          />
        </div>
        <div className="task-list" data-testid="task-list">
          {tasks.length === 0 ? (
            <EmptyState compact icon={<CalendarClock size={20} />} title={t('taskManager.noTasks')} />
          ) : (
            tasks.map(task => (
              <div key={task.id} className="task-item" data-testid="task-item">
                <div className="task-info">
                  <div className="task-title">{task.description}</div>
                  <div className="task-meta">
                    {task.trigger === 'cron' ? (
                      <span className="badge" style={ACCENT_BADGE_STYLE} data-testid="task-trigger">
                        {t('taskManager.triggerCron')}: {task.cron}
                      </span>
                    ) : (
                      <span className="badge badge-neutral" data-testid="task-trigger">
                        {t('taskManager.triggerOnce')}
                      </span>
                    )}
                    <span className={`badge ${statusBadgeClass(task.status)}`} style={statusBadgeStyle(task.status)} data-testid="task-status">
                      {task.status}
                    </span>
                    <span
                      className="badge badge-neutral"
                      data-testid="task-channel"
                      title={t('taskManager.fieldChannel')}
                    >
                      {task.channel}
                    </span>
                    {task.trigger === 'cron' && task.next_run && (
                      <span>
                        {t('taskManager.fieldNextRun')}:{' '}
                        <span data-testid="task-next-run">{new Date(task.next_run).toLocaleString()}</span>
                      </span>
                    )}
                    {task.trigger === 'once' && task.scheduled_time && (
                      <span data-testid="task-next-run">{new Date(task.scheduled_time).toLocaleString()}</span>
                    )}
                  </div>
                  {task.content && (
                    <div data-testid="task-content">{truncateSummary(task.content)}</div>
                  )}
                </div>
                {ACTIONABLE_STATUSES.has(task.status) && (
                  <div className="task-actions">
                    {task.trigger === 'cron' && (task.status === 'paused' ? (
                      <button className="btn btn-sm" data-testid="resume-task" onClick={() => handleResumeTask(task.id)}>
                        <Play size={14} />
                        {t('taskManager.resume')}
                      </button>
                    ) : (
                      <button className="btn btn-sm" data-testid="pause-task" onClick={() => handlePauseTask(task.id)}>
                        <Pause size={14} />
                        {t('taskManager.pause')}
                      </button>
                    ))}
                    <button className="btn btn-danger btn-sm" data-testid="cancel-task" onClick={() => handleCancelTask(task.id)}>
                      <X size={14} />
                      {t('common.cancel')}
                    </button>
                  </div>
                )}
              </div>
            ))
          )}
        </div>
      </div>

      <TaskEventFeed />
    </div>
  )
}

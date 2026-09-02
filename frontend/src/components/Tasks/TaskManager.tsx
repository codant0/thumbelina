import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Bot, X, CalendarClock, Pause, Play, FileText } from 'lucide-react'
import { useTranslation } from '../../i18n'
import { EmptyState } from '../common/EmptyState'
import { TaskEventFeed } from './TaskEventFeed'
import { MarkdownDetailModal } from './MarkdownDetailModal'
import { TaskDetailModal } from './TaskDetailModal'
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

// Shared base classes stay unchanged (.badge-warning / .badge-success / .badge-
// error); the cron-trigger and paused/missed badges use the new accent/orange
// palette (declared in pages.css v2).
const STATUS_BADGE: Record<string, string> = {
  completed: 'badge-success',
  running: 'badge-warning',
  failed: 'badge-error',
  pending: 'badge-neutral',
  cancelled: 'badge-neutral',
}

function statusBadgeClass(status: string): string {
  if (status === 'paused' || status === 'missed') return 'badge-orange'
  return STATUS_BADGE[status] ?? 'badge-neutral'
}

// Polling cadence: fast list refresh + slow scheduler heartbeat probe.
const REFRESH_INTERVAL_MS = 10_000
const SCHEDULER_POLL_MS = 30_000
// task_event frames can burst (cron batch); collapse them into at most one
// refresh per window while keeping the 10s poll as the safety net.
const WS_REFRESH_THROTTLE_MS = 500
// Action buttons only make sense while a task can still change state.
const ACTIONABLE_STATUSES = new Set(['pending', 'running', 'paused'])

type TaskFilter = 'all' | 'active' | 'completed' | 'failed'

function filterTasks(tasks: ScheduledTaskVO[], filter: TaskFilter): ScheduledTaskVO[] {
  if (filter === 'all') return tasks
  if (filter === 'active') return tasks.filter(t => t.status === 'pending' || t.status === 'running' || t.status === 'paused')
  if (filter === 'completed') return tasks.filter(t => t.status === 'completed' || t.status === 'cancelled')
  return tasks.filter(t => t.status === 'failed' || t.status === 'missed')
}

export function TaskManager() {
  const [subagents, setSubagents] = useState<SubagentVO[]>([])
  const [tasks, setTasks] = useState<ScheduledTaskVO[]>([])
  const [scheduler, setScheduler] = useState<SchedulerStatusVO | null>(null)
  const [error, setError] = useState('')
  const [taskFilter, setTaskFilter] = useState<TaskFilter>('all')
  const [detailTaskId, setDetailTaskId] = useState<string | null>(null)
  const [subagentResult, setSubagentResult] = useState<SubagentVO | null>(null)
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

  // Scheduler aliveness: slow 30s poll of the heartbeat snapshot.
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

  const handleRowKey = (e: React.KeyboardEvent, taskId: string) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault()
      setDetailTaskId(taskId)
    }
  }

  const stopRow = (e: React.SyntheticEvent) => e.stopPropagation()

  const schedulerAlive = scheduler?.running === true
  const filteredTasks = useMemo(() => filterTasks(tasks, taskFilter), [tasks, taskFilter])

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
                  </div>
                </div>
                <div className="task-actions">
                  {agent.result && (
                    <button
                      type="button"
                      className="btn btn-ghost btn-sm"
                      data-testid="view-subagent-result"
                      onClick={() => setSubagentResult(agent)}
                    >
                      <FileText size={14} />
                      {t('taskManager.viewResult')}
                    </button>
                  )}
                  {(agent.status === 'running' || agent.status === 'pending') && (
                    <button className="btn btn-danger btn-sm" data-testid="cancel-subagent" onClick={() => handleCancelSubagent(agent.id)}>
                      <X size={14} />
                      {t('common.cancel')}
                    </button>
                  )}
                </div>
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
            className={schedulerAlive ? 'scheduler-pill scheduler-pill--alive' : 'scheduler-pill'}
            title={schedulerAlive ? t('taskManager.schedulerAlive') : t('taskManager.schedulerDown')}
          >
            <span className="scheduler-pill__dot" />
            {schedulerAlive ? t('taskManager.schedulerAlive') : t('taskManager.schedulerDown')}
          </span>
        </div>
        <div className="task-chips" data-testid="task-filter">
          {(['all', 'active', 'completed', 'failed'] as const).map(f => (
            <button
              key={f}
              type="button"
              className={taskFilter === f ? 'chip chip--active' : 'chip'}
              data-testid={`task-filter-${f}`}
              onClick={() => setTaskFilter(f)}
            >
              {t(`taskManager.filter${f[0].toUpperCase()}${f.slice(1)}`)}
            </button>
          ))}
        </div>
        <div className="task-list" data-testid="task-list">
          {filteredTasks.length === 0 ? (
            <EmptyState compact icon={<CalendarClock size={20} />} title={t('taskManager.noTasks')} />
          ) : (
            filteredTasks.map(task => (
              <div
                key={task.id}
                className="task-item task-item--clickable"
                data-testid="task-item"
                role="button"
                tabIndex={0}
                onClick={() => setDetailTaskId(task.id)}
                onKeyDown={e => handleRowKey(e, task.id)}
              >
                <div className="task-info">
                  <div className="task-title">{task.description}</div>
                  <div className="task-meta">
                    {task.trigger === 'cron' ? (
                      <span className="badge badge-accent" data-testid="task-trigger">
                        {t('taskManager.triggerCron')}: {task.cron}
                      </span>
                    ) : (
                      <span className="badge badge-neutral" data-testid="task-trigger">
                        {t('taskManager.triggerOnce')}
                      </span>
                    )}
                    <span className={`badge ${statusBadgeClass(task.status)}`} data-testid="task-status">
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
                    <div className="task-preview" data-testid="task-content">{task.content}</div>
                  )}
                </div>
                {ACTIONABLE_STATUSES.has(task.status) && (
                  <div className="task-actions" onClick={stopRow}>
                    {task.trigger === 'cron' && (task.status === 'paused' ? (
                      <button className="btn btn-sm" data-testid="resume-task" onClick={e => { stopRow(e); void handleResumeTask(task.id) }}>
                        <Play size={14} />
                        {t('taskManager.resume')}
                      </button>
                    ) : (
                      <button className="btn btn-sm" data-testid="pause-task" onClick={e => { stopRow(e); void handlePauseTask(task.id) }}>
                        <Pause size={14} />
                        {t('taskManager.pause')}
                      </button>
                    ))}
                    <button className="btn btn-danger btn-sm" data-testid="cancel-task" onClick={e => { stopRow(e); void handleCancelTask(task.id) }}>
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

      <TaskDetailModal
        taskId={detailTaskId}
        onClose={() => setDetailTaskId(null)}
      />
      {subagentResult && (
        <MarkdownDetailModal
          title={subagentResult.task}
          subtitle={
            <span className={`badge ${statusBadgeClass(subagentResult.status)}`}>
              {subagentResult.status}
            </span>
          }
          markdown={subagentResult.result}
          onClose={() => setSubagentResult(null)}
        />
      )}
    </div>
  )
}
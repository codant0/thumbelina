import { useState, useEffect } from 'react'
import { Bot, X, CalendarClock } from 'lucide-react'
import { useTranslation } from '../../i18n'

interface Subagent {
  id: string
  task: string
  status: string
  result: string | null
}

interface ScheduledTask {
  id: string
  description: string
  scheduled_time: string
  status: string
}

const STATUS_BADGE: Record<string, string> = {
  completed: 'badge-success',
  running: 'badge-warning',
  failed: 'badge-error',
  pending: 'badge-neutral',
  cancelled: 'badge-neutral',
}

export function TaskManager() {
  const [subagents, setSubagents] = useState<Subagent[]>([])
  const [tasks, setTasks] = useState<ScheduledTask[]>([])
  const [error, setError] = useState('')
  const { t } = useTranslation()

  const fetchData = async () => {
    try {
      const [agentsRes, tasksRes] = await Promise.all([
        fetch('/api/v1/subagents'),
        fetch('/api/v1/tasks'),
      ])
      if (agentsRes.ok) setSubagents(await agentsRes.json())
      if (tasksRes.ok) setTasks(await tasksRes.json())
      setError('')
    } catch {
      setError(t('taskManager.fetchFailed'))
    }
  }

  useEffect(() => {
    void fetchData() // eslint-disable-line react-hooks/set-state-in-effect
    const interval = setInterval(() => void fetchData(), 10000)
    return () => clearInterval(interval)
  }, [])

  const handleCancelSubagent = async (id: string) => {
    try {
      await fetch(`/api/v1/subagents/${id}/cancel`, { method: 'POST' })
      void fetchData()
    } catch { /* ignore */ }
  }

  const handleCancelTask = async (id: string) => {
    try {
      await fetch(`/api/v1/tasks/${id}/cancel`, { method: 'POST' })
      void fetchData()
    } catch { /* ignore */ }
  }

  return (
    <div className="page-container" data-testid="task-manager">
      <div className="page-title">{t('taskManager.title')}</div>
      {error && <p data-testid="task-error" className="error-state" style={{ padding: 0 }}>{error}</p>}

      <div className="card">
        <div className="card-title"><Bot size={14} />{t('taskManager.subagents')}</div>
        <div className="task-list" data-testid="subagent-list">
          {subagents.length === 0 ? (
            <p className="task-empty">{t('taskManager.noSubagents')}</p>
          ) : (
            subagents.map(agent => (
              <div key={agent.id} className="task-item" data-testid="subagent-item">
                <div className="task-info">
                  <div className="task-title">{agent.task}</div>
                  <div className="task-meta">
                    <span className={`badge ${STATUS_BADGE[agent.status] ?? 'badge-neutral'}`} data-testid="subagent-status">
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
        <div className="card-title"><CalendarClock size={14} />{t('taskManager.scheduledTasks')}</div>
        <div className="task-list" data-testid="task-list">
          {tasks.length === 0 ? (
            <p className="task-empty">{t('taskManager.noTasks')}</p>
          ) : (
            tasks.map(task => (
              <div key={task.id} className="task-item" data-testid="task-item">
                <div className="task-info">
                  <div className="task-title">{task.description}</div>
                  <div className="task-meta">
                    <span className={`badge ${STATUS_BADGE[task.status] ?? 'badge-neutral'}`} data-testid="task-status">
                      {task.status}
                    </span>
                    <span>{new Date(task.scheduled_time).toLocaleString()}</span>
                  </div>
                </div>
                {(task.status === 'running' || task.status === 'pending') && (
                  <div className="task-actions">
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
    </div>
  )
}

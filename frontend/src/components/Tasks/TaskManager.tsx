import { useState, useEffect } from 'react'

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

const STATUS_COLORS: Record<string, string> = {
  completed: 'green',
  running: 'yellow',
  failed: 'red',
  pending: 'gray',
  cancelled: 'gray',
}

export function TaskManager() {
  const [subagents, setSubagents] = useState<Subagent[]>([])
  const [tasks, setTasks] = useState<ScheduledTask[]>([])
  const [error, setError] = useState('')

  useEffect(() => {
    let active = true

    const fetchData = async () => {
      try {
        const [agentsRes, tasksRes] = await Promise.all([
          fetch('/api/v1/subagents'),
          fetch('/api/v1/tasks'),
        ])
        if (!active) return
        if (agentsRes.ok) {
          setSubagents(await agentsRes.json())
        }
        if (tasksRes.ok) {
          setTasks(await tasksRes.json())
        }
        setError('')
      } catch {
        if (active) setError('Failed to fetch data')
      }
    }

    void fetchData()
    const interval = setInterval(() => void fetchData(), 5000)
    return () => {
      active = false
      clearInterval(interval)
    }
  }, [])

  const handleCancelSubagent = async (id: string) => {
    try {
      await fetch(`/api/v1/subagents/${id}/cancel`, { method: 'POST' })
      fetchData()
    } catch {
      // ignore
    }
  }

  const handleCancelTask = async (id: string) => {
    try {
      await fetch(`/api/v1/tasks/${id}/cancel`, { method: 'POST' })
      fetchData()
    } catch {
      // ignore
    }
  }

  return (
    <div data-testid="task-manager">
      <h2>Task Manager</h2>
      {error && <p data-testid="task-error">{error}</p>}

      <section>
        <h3>Subagents</h3>
        <div data-testid="subagent-list">
          {subagents.length === 0 ? (
            <p>No subagents</p>
          ) : (
            subagents.map(agent => (
              <div key={agent.id} data-testid="subagent-item">
                <span>{agent.task}</span>
                <span
                  data-testid="subagent-status"
                  style={{ color: STATUS_COLORS[agent.status] ?? 'gray' }}
                >
                  {agent.status}
                </span>
                {agent.result && <span>{agent.result}</span>}
                {(agent.status === 'running' || agent.status === 'pending') && (
                  <button
                    data-testid="cancel-subagent"
                    onClick={() => handleCancelSubagent(agent.id)}
                  >
                    Cancel
                  </button>
                )}
              </div>
            ))
          )}
        </div>
      </section>

      <section>
        <h3>Scheduled Tasks</h3>
        <div data-testid="task-list">
          {tasks.length === 0 ? (
            <p>No scheduled tasks</p>
          ) : (
            tasks.map(task => (
              <div key={task.id} data-testid="task-item">
                <span>{task.description}</span>
                <span>{new Date(task.scheduled_time).toLocaleString()}</span>
                <span
                  data-testid="task-status"
                  style={{ color: STATUS_COLORS[task.status] ?? 'gray' }}
                >
                  {task.status}
                </span>
                {(task.status === 'running' || task.status === 'pending') && (
                  <button
                    data-testid="cancel-task"
                    onClick={() => handleCancelTask(task.id)}
                  >
                    Cancel
                  </button>
                )}
              </div>
            ))
          )}
        </div>
      </section>
    </div>
  )
}

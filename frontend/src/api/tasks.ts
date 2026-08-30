/** Typed client for the task scheduler API (design §8.1).

 *  Every task-page fetch goes through here — the component layer must not
 *  call bare ``fetch`` against these endpoints.
 */

const API_BASE = '/api/v1'

/** Serialized scheduled task (backend ``routes/tasks.py::_serialize_task``). */
export interface ScheduledTaskVO {
  id: string
  description: string
  /** ISO local timestamp; null for cron tasks. */
  scheduled_time: string | null
  /** pending | running | completed | cancelled | failed | paused | missed */
  status: string
  /** once | cron */
  trigger: 'once' | 'cron'
  /** 5-field cron expression; null for once tasks. */
  cron: string | null
  /** Next fire time (cron only); null otherwise. */
  next_run: string | null
  last_run: string | null
  /** web | wechat | qq */
  channel: 'web' | 'wechat' | 'qq'
  content: string
  mode: string
  source: string
  error: string | null
}

/** Serialized task lifecycle event (design §8.2; also the WS frame body). */
export interface TaskEventVO {
  id: string
  /** task.created | task.due | task.completed | task.failed | task.missed | task.cancelled */
  type: string
  task_id: string
  fired_at: string
  /** once | cron */
  trigger: string
  channel: string
  content: string
  /** Type-specific extension data (error / scheduled_for / result ...). */
  payload: Record<string, unknown> | null
}

/** Scheduler aliveness snapshot from the heartbeat (§8.1). */
export interface SchedulerStatusVO {
  running: boolean
  last_heartbeat_at: string | null
  task_counts: Record<string, number>
  checks: Record<string, string>
}

/** Serialized subagent (legacy ``/subagents`` endpoint). */
export interface SubagentVO {
  id: string
  task: string
  status: string
  result: string | null
}

export interface CreateTaskInput {
  description: string
  trigger: 'once' | 'cron'
  /** ISO local timestamp; required for once tasks. */
  scheduled_time?: string
  /** 5-field cron expression; required for cron tasks. */
  cron?: string
  channel?: 'web' | 'wechat' | 'qq'
  content?: string
}

async function parseError(res: Response): Promise<never> {
  const data = await res.json().catch(() => ({}))
  throw new Error(data.detail || `HTTP ${res.status}`)
}

export async function listTasks(): Promise<ScheduledTaskVO[]> {
  const res = await fetch(`${API_BASE}/tasks`)
  if (!res.ok) return []
  const data = await res.json()
  return Array.isArray(data) ? (data as ScheduledTaskVO[]) : []
}

export async function createTask(input: CreateTaskInput): Promise<ScheduledTaskVO> {
  const res = await fetch(`${API_BASE}/tasks`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  })
  if (!res.ok) await parseError(res)
  return res.json() as Promise<ScheduledTaskVO>
}

export async function cancelTask(id: string): Promise<{ cancelled: boolean }> {
  const res = await fetch(`${API_BASE}/tasks/${id}/cancel`, { method: 'POST' })
  if (!res.ok) await parseError(res)
  return res.json() as Promise<{ cancelled: boolean }>
}

export async function pauseTask(id: string): Promise<ScheduledTaskVO> {
  const res = await fetch(`${API_BASE}/tasks/${id}/pause`, { method: 'POST' })
  if (!res.ok) await parseError(res)
  return res.json() as Promise<ScheduledTaskVO>
}

export async function resumeTask(id: string): Promise<ScheduledTaskVO> {
  const res = await fetch(`${API_BASE}/tasks/${id}/resume`, { method: 'POST' })
  if (!res.ok) await parseError(res)
  return res.json() as Promise<ScheduledTaskVO>
}

/** Most recent task events, newest first. Backend caps limit at 200. */
export async function listEvents(limit = 50): Promise<TaskEventVO[]> {
  const res = await fetch(`${API_BASE}/tasks/events?limit=${limit}`)
  if (!res.ok) return []
  const data = await res.json()
  return Array.isArray(data) ? (data as TaskEventVO[]) : []
}

/** Heartbeat snapshot, or null when the scheduler is disabled (503). */
export async function schedulerStatus(): Promise<SchedulerStatusVO | null> {
  const res = await fetch(`${API_BASE}/tasks/scheduler/status`)
  if (!res.ok) return null
  const data = await res.json()
  if (!data || typeof data !== 'object' || Array.isArray(data)) return null
  return data as SchedulerStatusVO
}

export async function listSubagents(): Promise<SubagentVO[]> {
  const res = await fetch(`${API_BASE}/subagents`)
  if (!res.ok) return []
  const data = await res.json()
  return Array.isArray(data) ? (data as SubagentVO[]) : []
}

export async function cancelSubagent(id: string): Promise<void> {
  const res = await fetch(`${API_BASE}/subagents/${id}/cancel`, { method: 'POST' })
  if (!res.ok) await parseError(res)
}

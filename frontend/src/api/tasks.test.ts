import { describe, it, expect, vi, beforeEach } from 'vitest'
import {
  listTasks,
  createTask,
  cancelTask,
  pauseTask,
  resumeTask,
  listEvents,
  schedulerStatus,
  listSubagents,
  cancelSubagent,
} from './tasks'
import type { ScheduledTaskVO, TaskEventVO, SchedulerStatusVO } from './tasks'

const TASK: ScheduledTaskVO = {
  id: 't-1',
  description: 'water the plants',
  scheduled_time: '2026-08-30T10:00:00',
  status: 'pending',
  trigger: 'cron',
  cron: '*/5 * * * *',
  next_run: '2026-08-30T12:00:00',
  last_run: null,
  channel: 'web',
  content: 'hello',
  mode: 'notify',
  source: 'agent',
  error: null,
}

const EVENT: TaskEventVO = {
  id: 'e-1',
  type: 'task.completed',
  task_id: 't-1',
  fired_at: '2026-08-30T12:00:05',
  trigger: 'cron',
  channel: 'web',
  content: 'hello',
  payload: null,
}

const STATUS: SchedulerStatusVO = {
  running: true,
  last_heartbeat_at: '2026-08-30T12:00:00',
  task_counts: { pending: 1 },
  checks: {},
}

function jsonResponse(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), { status })
}

describe('tasks API', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('listTasks GETs /api/v1/tasks and returns parsed array', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(jsonResponse([TASK]))
    const tasks = await listTasks()
    expect(fetchSpy.mock.calls[0][0]).toBe('/api/v1/tasks')
    expect(tasks).toEqual([TASK])
  })

  it('listTasks returns empty array when the request fails', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(jsonResponse({ detail: 'down' }, 503))
    await expect(listTasks()).resolves.toEqual([])
  })

  it('createTask POSTs JSON body to /api/v1/tasks and returns the task', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(jsonResponse(TASK, 201))
    const created = await createTask({
      description: 'water the plants',
      trigger: 'cron',
      cron: '*/5 * * * *',
      channel: 'web',
      content: 'hello',
    })
    const [url, init] = fetchSpy.mock.calls[0]
    expect(url).toBe('/api/v1/tasks')
    expect(init?.method).toBe('POST')
    expect(init?.headers).toMatchObject({ 'Content-Type': 'application/json' })
    expect(JSON.parse(init?.body as string)).toEqual({
      description: 'water the plants',
      trigger: 'cron',
      cron: '*/5 * * * *',
      channel: 'web',
      content: 'hello',
    })
    expect(created).toEqual(TASK)
  })

  it('createTask throws the backend detail on 422', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      jsonResponse({ detail: 'Invalid cron expression' }, 422),
    )
    await expect(createTask({ description: 'x', trigger: 'cron', cron: 'bad' })).rejects.toThrow(
      'Invalid cron expression',
    )
  })

  it('cancelTask POSTs to /api/v1/tasks/{id}/cancel', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      jsonResponse({ cancelled: true }),
    )
    const result = await cancelTask('t-1')
    const [url, init] = fetchSpy.mock.calls[0]
    expect(url).toBe('/api/v1/tasks/t-1/cancel')
    expect(init?.method).toBe('POST')
    expect(result).toEqual({ cancelled: true })
  })

  it('pauseTask POSTs to /api/v1/tasks/{id}/pause and returns the task', async () => {
    const paused = { ...TASK, status: 'paused' }
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(jsonResponse(paused))
    const result = await pauseTask('t-1')
    const [url, init] = fetchSpy.mock.calls[0]
    expect(url).toBe('/api/v1/tasks/t-1/pause')
    expect(init?.method).toBe('POST')
    expect(result).toEqual(paused)
  })

  it('pauseTask throws the backend detail on 409', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      jsonResponse({ detail: 'Only pending or running cron tasks can be paused' }, 409),
    )
    await expect(pauseTask('t-1')).rejects.toThrow('Only pending or running cron tasks can be paused')
  })

  it('resumeTask POSTs to /api/v1/tasks/{id}/resume and returns the task', async () => {
    const resumed = { ...TASK, status: 'pending' }
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(jsonResponse(resumed))
    const result = await resumeTask('t-1')
    const [url, init] = fetchSpy.mock.calls[0]
    expect(url).toBe('/api/v1/tasks/t-1/resume')
    expect(init?.method).toBe('POST')
    expect(result).toEqual(resumed)
  })

  it('listEvents GETs /api/v1/tasks/events with limit=50 and returns parsed array', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(jsonResponse([EVENT]))
    const events = await listEvents()
    expect(fetchSpy.mock.calls[0][0]).toBe('/api/v1/tasks/events?limit=50')
    expect(events).toEqual([EVENT])
  })

  it('listEvents supports a custom limit', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(jsonResponse([]))
    await listEvents(10)
    expect(fetchSpy.mock.calls[0][0]).toBe('/api/v1/tasks/events?limit=10')
  })

  it('listEvents returns empty array when the scheduler is disabled (503)', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(jsonResponse({ detail: 'down' }, 503))
    await expect(listEvents()).resolves.toEqual([])
  })

  it('schedulerStatus GETs /api/v1/tasks/scheduler/status and returns the snapshot', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(jsonResponse(STATUS))
    const status = await schedulerStatus()
    expect(fetchSpy.mock.calls[0][0]).toBe('/api/v1/tasks/scheduler/status')
    expect(status).toEqual(STATUS)
  })

  it('schedulerStatus returns null when the heartbeat is unavailable (503)', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(jsonResponse({ detail: 'down' }, 503))
    await expect(schedulerStatus()).resolves.toBeNull()
  })

  it('schedulerStatus returns null on a malformed body', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(jsonResponse(['not', 'an', 'object']))
    await expect(schedulerStatus()).resolves.toBeNull()
  })

  it('listSubagents GETs /api/v1/subagents and returns parsed array', async () => {
    const agents = [{ id: 's-1', task: 'do things', status: 'running', result: null }]
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(jsonResponse(agents))
    const result = await listSubagents()
    expect(fetchSpy.mock.calls[0][0]).toBe('/api/v1/subagents')
    expect(result).toEqual(agents)
  })

  it('cancelSubagent POSTs to /api/v1/subagents/{id}/cancel', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(jsonResponse({ ok: true }))
    await cancelSubagent('s-1')
    const [url, init] = fetchSpy.mock.calls[0]
    expect(url).toBe('/api/v1/subagents/s-1/cancel')
    expect(init?.method).toBe('POST')
  })
})

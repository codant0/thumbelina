import { describe, it, expect, vi, beforeEach } from 'vitest'
import {
  fetchTodoStatus,
  fetchTodoItems,
  addTodoItem,
  updateTodoItem,
  deleteTodoItem,
  fetchNotes,
  addNote,
  updateNote,
  deleteNote,
} from './todo'
import type { TodoItem, TodoNote } from './todo'

const TODO_ITEMS: TodoItem[] = [
  { index: 0, text: 'buy milk', done: false },
  { index: 1, text: 'write tests', done: true },
]

const TODO_NOTES: TodoNote[] = [
  { index: 0, timestamp: '2026-08-14T10:00:00', content: 'first note' },
  { index: 1, timestamp: '2026-08-14T11:30:00', content: 'second note' },
]

function jsonResponse(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), { status })
}

describe('todo API', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('fetchTodoStatus returns parsed status', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      jsonResponse({ enabled: true }),
    )
    const status = await fetchTodoStatus()
    expect(status).toEqual({ enabled: true })
    expect(fetchSpy.mock.calls[0][0]).toBe('/api/v1/todo/status')
  })

  it('fetchTodoItems returns parsed items', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      jsonResponse({ items: TODO_ITEMS }),
    )
    const items = await fetchTodoItems()
    expect(items).toHaveLength(2)
    expect(items[0]).toEqual({ index: 0, text: 'buy milk', done: false })
    expect(items[1].done).toBe(true)
    expect(fetchSpy.mock.calls[0][0]).toBe('/api/v1/todo/items')
  })

  it('fetchNotes returns parsed notes', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      jsonResponse({ notes: TODO_NOTES }),
    )
    const notes = await fetchNotes()
    expect(notes).toHaveLength(2)
    expect(notes[0]).toEqual({ index: 0, timestamp: '2026-08-14T10:00:00', content: 'first note' })
    expect(fetchSpy.mock.calls[0][0]).toBe('/api/v1/todo/notes')
  })

  it('addTodoItem sends POST with text body and returns updated items', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      jsonResponse({ items: TODO_ITEMS }),
    )
    const items = await addTodoItem('buy milk')
    const [url, init] = fetchSpy.mock.calls[0]
    expect(url).toBe('/api/v1/todo/items')
    expect(init?.method).toBe('POST')
    expect(init?.headers).toMatchObject({ 'Content-Type': 'application/json' })
    expect(JSON.parse(init?.body as string)).toEqual({ text: 'buy milk' })
    expect(items).toEqual(TODO_ITEMS)
  })

  it('updateTodoItem sends PATCH with index in URL and patch body', async () => {
    const updated = [{ index: 0, text: 'buy milk', done: true }]
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      jsonResponse({ items: updated }),
    )
    const items = await updateTodoItem(0, { done: true })
    const [url, init] = fetchSpy.mock.calls[0]
    expect(url).toBe('/api/v1/todo/items/0')
    expect(init?.method).toBe('PATCH')
    expect(JSON.parse(init?.body as string)).toEqual({ done: true })
    expect(items).toEqual(updated)
  })

  it('deleteTodoItem sends DELETE with index in URL and no body', async () => {
    const remaining = [{ index: 0, text: 'write tests', done: true }]
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      jsonResponse({ items: remaining }),
    )
    const items = await deleteTodoItem(1)
    const [url, init] = fetchSpy.mock.calls[0]
    expect(url).toBe('/api/v1/todo/items/1')
    expect(init?.method).toBe('DELETE')
    expect(init?.body).toBeUndefined()
    expect(items).toEqual(remaining)
  })

  it('addNote sends POST with content body and returns updated notes', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      jsonResponse({ notes: TODO_NOTES }),
    )
    const notes = await addNote('first note')
    const [url, init] = fetchSpy.mock.calls[0]
    expect(url).toBe('/api/v1/todo/notes')
    expect(init?.method).toBe('POST')
    expect(init?.headers).toMatchObject({ 'Content-Type': 'application/json' })
    expect(JSON.parse(init?.body as string)).toEqual({ content: 'first note' })
    expect(notes).toEqual(TODO_NOTES)
  })

  it('updateNote sends PUT with index in URL and content body', async () => {
    const updated = [{ index: 0, timestamp: '2026-08-14T10:00:00', content: 'edited note' }]
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      jsonResponse({ notes: updated }),
    )
    const notes = await updateNote(0, 'edited note')
    const [url, init] = fetchSpy.mock.calls[0]
    expect(url).toBe('/api/v1/todo/notes/0')
    expect(init?.method).toBe('PUT')
    expect(JSON.parse(init?.body as string)).toEqual({ content: 'edited note' })
    expect(notes).toEqual(updated)
  })

  it('deleteNote sends DELETE with index in URL and no body', async () => {
    const remaining = [{ index: 0, timestamp: '2026-08-14T11:30:00', content: 'second note' }]
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      jsonResponse({ notes: remaining }),
    )
    const notes = await deleteNote(1)
    const [url, init] = fetchSpy.mock.calls[0]
    expect(url).toBe('/api/v1/todo/notes/1')
    expect(init?.method).toBe('DELETE')
    expect(init?.body).toBeUndefined()
    expect(notes).toEqual(remaining)
  })

  it('addTodoItem throws error with status code when request fails', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      jsonResponse({ detail: 'TODO storage unavailable' }, 503),
    )
    await expect(addTodoItem('boom')).rejects.toThrow('TODO storage unavailable')
  })

  it('fetchNotes throws error with status code when response has no detail', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response('Service Unavailable', { status: 503 }),
    )
    await expect(fetchNotes()).rejects.toThrow('503')
  })
})

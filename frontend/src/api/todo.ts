export interface TodoItem {
  index: number
  text: string
  done: boolean
}

export interface TodoNote {
  index: number
  timestamp: string
  content: string
}

export interface TodoListResponse {
  items: TodoItem[]
}

export interface TodoNotesResponse {
  notes: TodoNote[]
}

const API_BASE = '/api/v1'

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
  if (!res.ok) {
    const data = await res.json().catch(() => ({}))
    throw new Error(data.detail || `HTTP ${res.status}`)
  }
  return res.json() as Promise<T>
}

export async function fetchTodoStatus(): Promise<{ enabled: boolean }> {
  return request<{ enabled: boolean }>('/todo/status')
}

export async function fetchTodoItems(): Promise<TodoItem[]> {
  const data = await request<TodoListResponse>('/todo/items')
  return data.items
}

export async function addTodoItem(text: string): Promise<TodoItem[]> {
  const data = await request<TodoListResponse>('/todo/items', {
    method: 'POST',
    body: JSON.stringify({ text }),
  })
  return data.items
}

export async function updateTodoItem(
  index: number,
  patch: { text?: string; done?: boolean },
): Promise<TodoItem[]> {
  const data = await request<TodoListResponse>(`/todo/items/${index}`, {
    method: 'PATCH',
    body: JSON.stringify(patch),
  })
  return data.items
}

export async function deleteTodoItem(index: number): Promise<TodoItem[]> {
  const data = await request<TodoListResponse>(`/todo/items/${index}`, {
    method: 'DELETE',
  })
  return data.items
}

export async function fetchNotes(): Promise<TodoNote[]> {
  const data = await request<TodoNotesResponse>('/todo/notes')
  return data.notes
}

export async function addNote(content: string): Promise<TodoNote[]> {
  const data = await request<TodoNotesResponse>('/todo/notes', {
    method: 'POST',
    body: JSON.stringify({ content }),
  })
  return data.notes
}

export async function updateNote(index: number, content: string): Promise<TodoNote[]> {
  const data = await request<TodoNotesResponse>(`/todo/notes/${index}`, {
    method: 'PUT',
    body: JSON.stringify({ content }),
  })
  return data.notes
}

export async function deleteNote(index: number): Promise<TodoNote[]> {
  const data = await request<TodoNotesResponse>(`/todo/notes/${index}`, {
    method: 'DELETE',
  })
  return data.notes
}

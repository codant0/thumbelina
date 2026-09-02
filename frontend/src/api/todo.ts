export interface TodoItem {
  index: number
  text: string
  done: boolean
  remark: string
  group?: string | null
}

export interface TodoNote {
  index: number
  timestamp: string
  content: string
  group?: string | null
}

export interface TodoListResponse {
  items: TodoItem[]
}

export interface TodoNotesResponse {
  notes: TodoNote[]
}

/** Patch body accepted by PATCH /items/{index}. */
export interface TodoItemPatch {
  text?: string
  done?: boolean
  remark?: string
  /** Explicitly provided group target: '' clears, a name attaches. */
  group?: string | null
}

/** Patch body accepted by PUT /notes/{index}. */
export interface TodoNotePatch {
  content?: string
  group?: string | null
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
  patch: TodoItemPatch,
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

export async function updateNote(index: number, patch: TodoNotePatch): Promise<TodoNote[]> {
  const data = await request<TodoNotesResponse>(`/todo/notes/${index}`, {
    method: 'PUT',
    body: JSON.stringify(patch),
  })
  return data.notes
}

export async function deleteNote(index: number): Promise<TodoNote[]> {
  const data = await request<TodoNotesResponse>(`/todo/notes/${index}`, {
    method: 'DELETE',
  })
  return data.notes
}

// ---------------------------------------------------------------------------
// Group CRUD — items and notes endpoints share a shape but return different
// lists, so each kind has its own typed helper.
// ---------------------------------------------------------------------------

/** Create a new (possibly empty) item group; returns the refreshed list. */
export async function createItemGroup(name: string): Promise<TodoItem[]> {
  const data = await request<TodoListResponse>('/todo/items/groups', {
    method: 'POST',
    body: JSON.stringify({ name }),
  })
  return data.items
}

/** Rename an item group (and every member); returns the refreshed list. */
export async function renameItemGroup(
  oldName: string,
  newName: string,
): Promise<TodoItem[]> {
  const data = await request<TodoListResponse>(
    `/todo/items/groups/${encodeURIComponent(oldName)}`,
    { method: 'PATCH', body: JSON.stringify({ name: newName }) },
  )
  return data.items
}

/** Delete an item group and detach its members; returns the refreshed list. */
export async function deleteItemGroup(name: string): Promise<TodoItem[]> {
  const data = await request<TodoListResponse>(
    `/todo/items/groups/${encodeURIComponent(name)}`,
    { method: 'DELETE' },
  )
  return data.items
}

/** Create a new (possibly empty) notes group; returns the refreshed list. */
export async function createNoteGroup(name: string): Promise<TodoNote[]> {
  const data = await request<TodoNotesResponse>('/todo/notes/groups', {
    method: 'POST',
    body: JSON.stringify({ name }),
  })
  return data.notes
}

/** Rename a notes group (and every member); returns the refreshed list. */
export async function renameNoteGroup(
  oldName: string,
  newName: string,
): Promise<TodoNote[]> {
  const data = await request<TodoNotesResponse>(
    `/todo/notes/groups/${encodeURIComponent(oldName)}`,
    { method: 'PATCH', body: JSON.stringify({ name: newName }) },
  )
  return data.notes
}

/** Delete a notes group and detach its members; returns the refreshed list. */
export async function deleteNoteGroup(name: string): Promise<TodoNote[]> {
  const data = await request<TodoNotesResponse>(
    `/todo/notes/groups/${encodeURIComponent(name)}`,
    { method: 'DELETE' },
  )
  return data.notes
}

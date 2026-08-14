import { useCallback, useEffect, useRef, useState } from 'react'
import {
  ClipboardList,
  StickyNote,
  Plus,
  Pencil,
  Trash2,
  Check,
  X,
  CheckCircle2,
} from 'lucide-react'
import { useTranslation } from '../../i18n'
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
} from '../../api/todo'
import type { TodoItem, TodoNote } from '../../api/todo'

interface TodoStatsBarProps {
  items: TodoItem[]
  notes: TodoNote[]
}

function TodoStatsBar({ items, notes }: TodoStatsBarProps) {
  const { t } = useTranslation()
  const total = items.length
  const done = items.filter(item => item.done).length
  const remaining = total - done
  const pct = total === 0 ? 0 : Math.round((done / total) * 100)

  return (
    <div className="todo-stats card">
      <div className="todo-stats__item">
        <ClipboardList className="todo-stats__icon" size={16} />
        <span className="todo-stats__num">{remaining}</span>{' '}
        <span className="todo-stats__label">{t('todo.remaining')}</span>
      </div>
      <div className="todo-stats__item">
        <CheckCircle2 className="todo-stats__icon todo-stats__icon--done" size={16} />
        <span className="todo-stats__num">{done}</span>{' '}
        <span className="todo-stats__label">{t('todo.doneCount')}</span>
      </div>
      <div className="todo-stats__item">
        <StickyNote className="todo-stats__icon todo-stats__icon--notes" size={16} />
        <span className="todo-stats__num">{notes.length}</span>{' '}
        <span className="todo-stats__label">{t('todo.noteCount')}</span>
      </div>
      <div
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={pct}
        aria-label={t('todo.progress')}
        className="todo-stats__progress"
      >
        <div className="todo-stats__progress-fill" style={{ width: `${pct}%` }} />
      </div>
      <span className="todo-stats__pct">{pct}%</span>
    </div>
  )
}

interface TodoListPanelProps {
  items: TodoItem[]
  busy: boolean
  onAdd: (text: string) => void
  onToggle: (item: TodoItem) => void
  onDelete: (index: number) => void
  onSaveText: (index: number, text: string) => void
}

function TodoListPanel({ items, busy, onAdd, onToggle, onDelete, onSaveText }: TodoListPanelProps) {
  const { t } = useTranslation()
  const [newText, setNewText] = useState('')
  const [editingIndex, setEditingIndex] = useState<number | null>(null)
  const [editText, setEditText] = useState('')

  const submitNew = useCallback(() => {
    const text = newText.trim()
    if (!text || busy) return
    onAdd(text)
    setNewText('')
  }, [newText, busy, onAdd])

  const startEdit = useCallback((item: TodoItem) => {
    setEditingIndex(item.index)
    setEditText(item.text)
  }, [])

  const cancelEdit = useCallback(() => {
    setEditingIndex(null)
    setEditText('')
  }, [])

  // Reset editing state whenever the list changes (e.g. another action
  // re-indexed items server-side), so a draft can never be saved onto a
  // different item that shifted into the edited position. Reference
  // comparison also skips the initial mount.
  const itemsRef = useRef(items)
  useEffect(() => {
    if (itemsRef.current !== items) {
      itemsRef.current = items
      cancelEdit()
    }
  }, [items, cancelEdit])

  const saveEdit = useCallback(() => {
    const text = editText.trim()
    if (editingIndex === null || !text || busy) return
    onSaveText(editingIndex, text)
    setEditingIndex(null)
    setEditText('')
  }, [editingIndex, editText, busy, onSaveText])

  return (
    <>
      <div className="todo-add">
        <input
          className="todo-add__input form-input"
          type="text"
          value={newText}
          placeholder={t('todo.placeholder')}
          aria-label={t('todo.placeholder')}
          disabled={busy}
          onChange={e => setNewText(e.target.value)}
          onKeyDown={e => {
            if (e.key === 'Enter') {
              e.preventDefault()
              submitNew()
            }
          }}
        />
        <button
          className="btn btn-primary"
          disabled={busy || !newText.trim()}
          onClick={submitNew}
        >
          <Plus size={14} />
          {t('todo.add')}
        </button>
      </div>

      {items.length === 0 ? (
        <p className="todo-empty">{t('todo.empty')}</p>
      ) : (
        <div className="todo-list">
          {items.map(item => (
            <div
              key={item.index}
              className={`todo-item${item.done ? ' todo-item--done' : ''}`}
              data-testid="todo-item"
            >
              {editingIndex === item.index ? (
                <div className="todo-item__edit">
                  <input
                    className="todo-item__edit-input form-input"
                    type="text"
                    value={editText}
                    aria-label={t('todo.edit')}
                    autoFocus
                    disabled={busy}
                    onChange={e => setEditText(e.target.value)}
                    onKeyDown={e => {
                      if (e.key === 'Enter') {
                        e.preventDefault()
                        saveEdit()
                      } else if (e.key === 'Escape') {
                        cancelEdit()
                      }
                    }}
                  />
                  <button
                    className="btn btn-primary btn-sm"
                    disabled={busy || !editText.trim()}
                    onClick={saveEdit}
                  >
                    <Check size={14} />
                    {t('todo.save')}
                  </button>
                  <button className="btn btn-ghost btn-sm" disabled={busy} onClick={cancelEdit}>
                    <X size={14} />
                    {t('todo.cancel')}
                  </button>
                </div>
              ) : (
                <>
                  <input
                    className="todo-item__checkbox"
                    type="checkbox"
                    checked={item.done}
                    disabled={busy}
                    aria-label={item.text}
                    onChange={() => onToggle(item)}
                  />
                  <span className="todo-item__text">{item.text}</span>
                  <div className="todo-item__actions">
                    <button
                      className="btn btn-ghost btn-sm"
                      disabled={busy}
                      onClick={() => startEdit(item)}
                    >
                      <Pencil size={14} />
                      {t('todo.edit')}
                    </button>
                    <button
                      className="btn btn-danger btn-sm"
                      disabled={busy}
                      onClick={() => onDelete(item.index)}
                    >
                      <Trash2 size={14} />
                      {t('todo.delete')}
                    </button>
                  </div>
                </>
              )}
            </div>
          ))}
        </div>
      )}
    </>
  )
}

interface TodoNotesPanelProps {
  notes: TodoNote[]
  busy: boolean
  onAdd: (content: string) => void
  onUpdate: (index: number, content: string) => void
  onDelete: (index: number) => void
}

function TodoNotesPanel({ notes, busy, onAdd, onUpdate, onDelete }: TodoNotesPanelProps) {
  const { t } = useTranslation()
  const [draft, setDraft] = useState('')
  const [editingIndex, setEditingIndex] = useState<number | null>(null)
  const [editDraft, setEditDraft] = useState('')

  const submitDraft = useCallback(() => {
    const content = draft.trim()
    if (!content || busy) return
    onAdd(content)
    setDraft('')
  }, [draft, busy, onAdd])

  const startEdit = useCallback((note: TodoNote) => {
    setEditingIndex(note.index)
    setEditDraft(note.content)
  }, [])

  const cancelEdit = useCallback(() => {
    setEditingIndex(null)
    setEditDraft('')
  }, [])

  // Reset editing state whenever the notes list changes, so a draft can
  // never be saved onto a different note that shifted into the edited
  // position. Reference comparison also skips the initial mount.
  const notesRef = useRef(notes)
  useEffect(() => {
    if (notesRef.current !== notes) {
      notesRef.current = notes
      cancelEdit()
    }
  }, [notes, cancelEdit])

  const saveEdit = useCallback(() => {
    const content = editDraft.trim()
    if (editingIndex === null || !content || busy) return
    onUpdate(editingIndex, content)
    setEditingIndex(null)
    setEditDraft('')
  }, [editingIndex, editDraft, busy, onUpdate])

  return (
    <>
      <div className="todo-note-form">
        <textarea
          className="todo-note-form__textarea form-input"
          value={draft}
          placeholder={t('todo.notePlaceholder')}
          aria-label={t('todo.notePlaceholder')}
          rows={3}
          disabled={busy}
          onChange={e => setDraft(e.target.value)}
        />
        <button
          className="todo-note-form__submit btn btn-primary"
          disabled={busy || !draft.trim()}
          onClick={submitDraft}
        >
          <Plus size={14} />
          {t('todo.addNote')}
        </button>
      </div>

      {notes.length === 0 ? (
        <p className="todo-empty">{t('todo.emptyNotes')}</p>
      ) : (
        <div className="todo-note-list">
          {notes.map(note => (
            <div key={note.index} className="todo-note" data-testid="todo-note">
              <div className="todo-note__header">
                <span className="todo-note__time">{note.timestamp}</span>
                <div className="todo-note__actions">
                  <button
                    className="btn btn-ghost btn-sm"
                    disabled={busy}
                    onClick={() => startEdit(note)}
                  >
                    <Pencil size={14} />
                    {t('todo.edit')}
                  </button>
                  <button
                    className="btn btn-danger btn-sm"
                    disabled={busy}
                    onClick={() => onDelete(note.index)}
                    data-testid="note-delete"
                  >
                    <Trash2 size={14} />
                    {t('todo.delete')}
                  </button>
                </div>
              </div>
              {editingIndex === note.index ? (
                <div className="todo-note__edit">
                  <textarea
                    className="todo-note__edit-textarea form-input"
                    value={editDraft}
                    aria-label={t('todo.edit')}
                    rows={3}
                    autoFocus
                    disabled={busy}
                    onChange={e => setEditDraft(e.target.value)}
                  />
                  <div className="todo-note__edit-actions">
                    <button
                      className="btn btn-primary btn-sm"
                      disabled={busy || !editDraft.trim()}
                      onClick={saveEdit}
                    >
                      <Check size={14} />
                      {t('todo.save')}
                    </button>
                    <button className="btn btn-ghost btn-sm" disabled={busy} onClick={cancelEdit}>
                      <X size={14} />
                      {t('todo.cancel')}
                    </button>
                  </div>
                </div>
              ) : (
                <div className="todo-note__content">{note.content}</div>
              )}
            </div>
          ))}
        </div>
      )}
    </>
  )
}

export function TodoPage() {
  const { t } = useTranslation()
  const [enabled, setEnabled] = useState<boolean | null>(null)
  const [items, setItems] = useState<TodoItem[]>([])
  const [notes, setNotes] = useState<TodoNote[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  // Synchronous mutex: guards against duplicate requests from rapid clicks
  // before the busy state re-render takes effect.
  const busyRef = useRef(false)

  const loadAll = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const status = await fetchTodoStatus()
      if (!status.enabled) {
        setEnabled(false)
        return
      }
      const [loadedItems, loadedNotes] = await Promise.all([fetchTodoItems(), fetchNotes()])
      setItems(loadedItems)
      setNotes(loadedNotes)
      setEnabled(true)
    } catch {
      setError(t('common.error'))
    } finally {
      setLoading(false)
    }
  }, [t])

  useEffect(() => {
    void loadAll() // eslint-disable-line react-hooks/set-state-in-effect
  }, [loadAll])

  const writeItems = useCallback(
    async (operation: () => Promise<TodoItem[]>) => {
      if (busyRef.current) return
      busyRef.current = true
      setBusy(true)
      setError('')
      try {
        setItems(await operation())
      } catch {
        setError(t('common.error'))
      } finally {
        busyRef.current = false
        setBusy(false)
      }
    },
    [t],
  )

  const writeNotes = useCallback(
    async (operation: () => Promise<TodoNote[]>) => {
      if (busyRef.current) return
      busyRef.current = true
      setBusy(true)
      setError('')
      try {
        setNotes(await operation())
      } catch {
        setError(t('common.error'))
      } finally {
        busyRef.current = false
        setBusy(false)
      }
    },
    [t],
  )

  const handleAddItem = useCallback(
    (text: string) => void writeItems(() => addTodoItem(text)),
    [writeItems],
  )
  const handleToggleItem = useCallback(
    (item: TodoItem) => void writeItems(() => updateTodoItem(item.index, { done: !item.done })),
    [writeItems],
  )
  const handleDeleteItem = useCallback(
    (index: number) => void writeItems(() => deleteTodoItem(index)),
    [writeItems],
  )
  const handleSaveItemText = useCallback(
    (index: number, text: string) => void writeItems(() => updateTodoItem(index, { text })),
    [writeItems],
  )
  const handleAddNote = useCallback(
    (content: string) => void writeNotes(() => addNote(content)),
    [writeNotes],
  )
  const handleUpdateNote = useCallback(
    (index: number, content: string) => void writeNotes(() => updateNote(index, content)),
    [writeNotes],
  )
  const handleDeleteNote = useCallback(
    (index: number) => void writeNotes(() => deleteNote(index)),
    [writeNotes],
  )

  if (loading) {
    return (
      <div className="page-container" data-testid="todo-loading">
        <div className="page-title">{t('todo.title')}</div>
        <div className="todo-skeleton todo-skeleton--stats" />
        <div className="todo-page">
          <div className="todo-skeleton todo-skeleton--panel" />
          <div className="todo-skeleton todo-skeleton--panel" />
        </div>
      </div>
    )
  }

  if (error && enabled === null) {
    return (
      <div className="page-container">
        <div className="page-title">{t('todo.title')}</div>
        <div className="todo-status" data-testid="todo-error">
          <p>{error}</p>
          <button className="btn btn-ghost" onClick={() => void loadAll()}>
            {t('common.retry')}
          </button>
        </div>
      </div>
    )
  }

  if (enabled === false) {
    return (
      <div className="page-container">
        <div className="page-title">{t('todo.title')}</div>
        <div className="todo-disabled" data-testid="todo-disabled">
          {t('todo.disabled')}
        </div>
      </div>
    )
  }

  return (
    <div className="page-container">
      <div className="page-title">{t('todo.title')}</div>
      {error && (
        <p className="todo-page__error" data-testid="todo-error">
          {error}
        </p>
      )}
      <TodoStatsBar items={items} notes={notes} />
      <div className="todo-page" data-testid="todo-page">
        <section className="todo-page__panel card" data-testid="todo-items-panel">
          <div className="card-title">
            <ClipboardList size={14} />
            {t('todo.items')}
          </div>
          <TodoListPanel
            items={items}
            busy={busy}
            onAdd={handleAddItem}
            onToggle={handleToggleItem}
            onDelete={handleDeleteItem}
            onSaveText={handleSaveItemText}
          />
        </section>
        <section className="todo-page__panel card" data-testid="todo-notes-panel">
          <div className="card-title">
            <StickyNote size={14} />
            {t('todo.notes')}
          </div>
          <TodoNotesPanel
            notes={notes}
            busy={busy}
            onAdd={handleAddNote}
            onUpdate={handleUpdateNote}
            onDelete={handleDeleteNote}
          />
        </section>
      </div>
    </div>
  )
}

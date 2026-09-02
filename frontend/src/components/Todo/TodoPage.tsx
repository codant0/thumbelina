import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { DragEvent, KeyboardEvent } from 'react'
import {
  ClipboardList,
  StickyNote,
  Plus,
  Pencil,
  Trash2,
  Check,
  X,
  CheckCircle2,
  Inbox,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { useTranslation } from '../../i18n'
import {
  fetchTodoStatus,
  fetchTodoItems,
  addTodoItem,
  updateTodoItem,
  deleteTodoItem,
  createItemGroup,
  renameItemGroup,
  deleteItemGroup,
  fetchNotes,
  addNote,
  updateNote,
  deleteNote,
  createNoteGroup,
  renameNoteGroup,
  deleteNoteGroup,
} from '../../api/todo'
import type { TodoItem, TodoNote } from '../../api/todo'
import { MarkdownContent } from '../Chat/MarkdownContent'

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
        aria-valuetext={`${pct}%`}
        aria-label={t('todo.progress')}
        className="todo-stats__progress"
      >
        <div className="todo-stats__progress-fill" style={{ width: `${pct}%` }} />
      </div>
      <span className="todo-stats__pct">{pct}%</span>
    </div>
  )
}

type TodoFilter = 'all' | 'active' | 'done'

interface TodoEmptyStateProps {
  icon: LucideIcon
  text: string
  variant?: 'default' | 'celebrate'
}

function TodoEmptyState({ icon: Icon, text, variant = 'default' }: TodoEmptyStateProps) {
  const modifier = variant === 'celebrate' ? ' todo-empty-state--celebrate' : ''
  return (
    <div className={`todo-empty-state${modifier}`}>
      <Icon size={32} />
      <p>{text}</p>
    </div>
  )
}

interface TodoFilterTabsProps {
  value: TodoFilter
  counts: { all: number; active: number; done: number }
  onChange: (value: TodoFilter) => void
}

function TodoFilterTabs({ value, counts, onChange }: TodoFilterTabsProps) {
  const { t } = useTranslation()
  const tabs: Array<{ key: TodoFilter; label: string; count: number }> = [
    { key: 'all', label: t('todo.all'), count: counts.all },
    { key: 'active', label: t('todo.active'), count: counts.active },
    { key: 'done', label: t('todo.done'), count: counts.done },
  ]
  return (
    <div className="todo-filter-tabs">
      {tabs.map(tab => (
        <button
          key={tab.key}
          type="button"
          aria-pressed={value === tab.key}
          className={`todo-filter-tabs__tab${value === tab.key ? ' todo-filter-tabs__tab--active' : ''}`}
          onClick={() => onChange(tab.key)}
        >
          {tab.label} <span className="todo-filter-tabs__count">{tab.count}</span>
        </button>
      ))}
    </div>
  )
}

/** Sentinel key for the ungrouped bucket in the group filter. */
export const UNGROUPED_KEY = '__ungrouped__'

interface TodoGroupFilterOption {
  /** '' = all items; UNGROUPED_KEY = items without a heading; otherwise the heading text. */
  key: string
  count: number
  /** Whether the card shows the panel icon (all groups or ungrouped). */
  icon: 'all' | 'ungrouped' | null
}

/** Derives filter options from the visible list plus any locally created
 * empty groups. Order: All (total) → ungrouped (only when entries exist
 * without a heading) → named groups in first-occurrence order; freshly
 * created empty groups appear so they can receive their first drag. */
function buildGroupOptions<T extends { group?: string | null }>(
  list: T[],
  emptyGroups: string[] = [],
): TodoGroupFilterOption[] {
  const counts = new Map<string, number>()
  const order: string[] = []
  let ungroupedCount = 0
  for (const entry of list) {
    const key = entry.group ?? ''
    if (key === '') {
      ungroupedCount += 1
      continue
    }
    const next = (counts.get(key) ?? 0) + 1
    counts.set(key, next)
    if (next === 1) order.push(key)
  }
  for (const name of emptyGroups) {
    if (name && !order.includes(name)) order.push(name)
  }
  const options: TodoGroupFilterOption[] = [{ key: '', count: list.length, icon: 'all' }]
  if (ungroupedCount > 0) {
    options.push({ key: UNGROUPED_KEY, count: ungroupedCount, icon: 'ungrouped' })
  }
  for (const key of order) {
    options.push({ key, count: counts.get(key) ?? 0, icon: null })
  }
  return options
}

/** Whether the group filter bar should render: there is something to bucket
 * (entries or freshly created empty groups) besides the All card alone. */
function hasGroupChoices<T extends { group?: string | null }>(
  list: T[],
  emptyGroups: string[],
): boolean {
  return list.length > 0 || emptyGroups.length > 0
}

interface TodoGroupFilterProps {
  options: TodoGroupFilterOption[]
  /** '' shows the full grouped view; otherwise only the selected bucket. */
  selected: string
  onSelect: (key: string) => void
  /** Panel identity used for the 'all' card icon and drag payload checks. */
  kind: 'items' | 'notes'
  /** Drop a dragged entry onto a group card. targetKey: group name, '' for
   * "ungrouped", null when the card is not a drop target. */
  onDropCard: (targetKey: string | null) => void
  onRename: (name: string) => void
  onDelete: (name: string) => void
  onNewGroup: () => void
  busy: boolean
}

const PANEL_PAYLOAD_KIND = { items: 'item', notes: 'note' } as const

const TODO_ALL_ICON = { items: ClipboardList, notes: StickyNote } as const

function TodoGroupFilter({
  options,
  selected,
  onSelect,
  kind,
  onDropCard,
  onRename,
  onDelete,
  onNewGroup,
  busy,
}: TodoGroupFilterProps) {
  const { t } = useTranslation()
  const AllIcon = TODO_ALL_ICON[kind]
  const [dropOverKey, setDropOverKey] = useState<string | null>(null)

  const clearDropOver = useCallback(() => setDropOverKey(null), [])

  const handleDrop = useCallback(
    (key: string) => {
      clearDropOver()
      onDropCard(key)
    },
    [clearDropOver, onDropCard],
  )

  const payloadKind = PANEL_PAYLOAD_KIND[kind]

  return (
    <div
      className="todo-group-filter"
      data-testid="todo-group-filter"
      onDragLeave={clearDropOver}
    >
      {options.map(option => {
        const Icon = option.icon === 'all' ? AllIcon : option.icon === 'ungrouped' ? Inbox : null
        const droppable = option.key !== '' // All is a selector only
        const dropping = dropOverKey === option.key
        const classes = [
          'todo-group-filter__item',
          dropping ? 'todo-group-filter__item--drop-target' : '',
        ]
          .filter(Boolean)
          .join(' ')
        return (
          <div
            key={option.key}
            className={classes}
            onDragOver={e => {
              if (!droppable || !readPanelDrag(e, payloadKind)) return
              e.preventDefault()
              e.dataTransfer.dropEffect = 'move'
              setDropOverKey(option.key)
            }}
            onDragEnter={e => {
              if (droppable && readPanelDrag(e, payloadKind)) setDropOverKey(option.key)
            }}
            onDrop={e => {
              if (!droppable) return
              e.preventDefault()
              handleDrop(option.key === UNGROUPED_KEY ? '' : option.key)
            }}
          >
            <button
              type="button"
              aria-pressed={selected === option.key}
              className={`todo-group-filter__card${selected === option.key ? ' todo-group-filter__card--selected' : ''}`}
              data-testid="todo-group-filter-card"
              onClick={() => onSelect(option.key)}
              title={option.key === '' || option.key === UNGROUPED_KEY ? undefined : option.key}
            >
              {Icon ? <Icon size={14} aria-hidden="true" /> : null}
              <span>
                {option.key === '' ? t('todo.all') : option.key === UNGROUPED_KEY ? t('todo.ungrouped') : option.key}
              </span>
              <span className="todo-group-filter__badge" data-testid="todo-group-filter-count">
                {option.count}
              </span>
            </button>
            {droppable && option.icon === null && (
              <span className="todo-group-filter__actions">
                <button
                  type="button"
                  className="todo-group-filter__action"
                  aria-label={t('todo.renameGroup')}
                  title={t('todo.renameGroup')}
                  data-testid="group-rename"
                  disabled={busy}
                  onClick={() => onRename(option.key)}
                >
                  <Pencil size={12} />
                </button>
                <button
                  type="button"
                  className="todo-group-filter__action todo-group-filter__action--danger"
                  aria-label={t('todo.deleteGroup')}
                  title={t('todo.deleteGroup')}
                  data-testid="group-delete"
                  disabled={busy}
                  onClick={() => onDelete(option.key)}
                >
                  <Trash2 size={12} />
                </button>
              </span>
            )}
          </div>
        )
      })}
      <button
        type="button"
        className="todo-group-filter__new"
        aria-label={t('todo.newGroup')}
        title={t('todo.newGroup')}
        disabled={busy}
        onClick={onNewGroup}
      >
        <Plus size={14} />
      </button>
    </div>
  )
}

interface GroupNameEditorProps {
  /** 'create' | 'rename'; only used to pick the placeholder. */
  mode: 'create' | 'rename'
  initialValue?: string
  busy: boolean
  onSubmit: (name: string) => void
  onCancel: () => void
}

/** Inline input for creating a new group or renaming an existing one. */
function GroupNameEditor({ mode, initialValue = '', busy, onSubmit, onCancel }: GroupNameEditorProps) {
  const { t } = useTranslation()
  const [name, setName] = useState(initialValue)

  const submit = () => {
    const trimmed = name.trim()
    if (!trimmed || busy) return
    onSubmit(trimmed)
  }

  return (
    <div className="todo-group-editor" data-testid="todo-group-editor">
      <input
        className="todo-group-editor__input form-input"
        type="text"
        value={name}
        autoFocus
        disabled={busy}
        placeholder={mode === 'create' ? t('todo.newGroupPlaceholder') : t('todo.renameGroupPlaceholder')}
        aria-label={mode === 'create' ? t('todo.newGroupPlaceholder') : t('todo.renameGroupPlaceholder')}
        onChange={e => setName(e.target.value)}
        onKeyDown={e => {
          if (e.key === 'Enter') {
            e.preventDefault()
            submit()
          } else if (e.key === 'Escape') {
            onCancel()
          }
        }}
      />
      <button
        className="btn btn-primary btn-sm"
        disabled={busy || !name.trim()}
        onClick={submit}
      >
        <Check size={14} />
        {mode === 'create' ? t('todo.createGroup') : t('todo.save')}
      </button>
      <button className="btn btn-ghost btn-sm" disabled={busy} onClick={onCancel}>
        <X size={14} />
        {t('todo.cancel')}
      </button>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Drag & drop between item rows / note cards and group cards
// ---------------------------------------------------------------------------

const CARD_MIME = 'application/x-thumbelina-todo-card'

interface TodoDragPayload {
  /** Which list the dragged entry belongs to (must match the drop panel). */
  kind: 'item' | 'note'
  /** Server index of the dragged entry at drag time. */
  index: number
}

function serializeDrag(payload: TodoDragPayload): string {
  return JSON.stringify(payload)
}

function parseDrag(raw: string | undefined): TodoDragPayload | null {
  if (!raw) return null
  try {
    const parsed = JSON.parse(raw) as TodoDragPayload
    if ((parsed.kind === 'item' || parsed.kind === 'note') && typeof parsed.index === 'number') {
      return parsed
    }
    return null
  } catch {
    return null
  }
}

/** Read a drag payload from a dataTransfer if it belongs to the given panel. */
function readPanelDrag(e: DragEvent, kind: 'item' | 'note'): TodoDragPayload | null {
  const payload = parseDrag(e.dataTransfer.getData(CARD_MIME))
  if (!payload || payload.kind !== kind) return null
  return payload
}

// ---------------------------------------------------------------------------
// Item list panel
// ---------------------------------------------------------------------------

interface TodoItemRowProps {
  item: TodoItem
  busy: boolean
  editing: boolean
  editText: string
  remarkEditing: boolean
  editRemark: string
  onEditTextChange: (text: string) => void
  onSaveEdit: () => void
  onCancelEdit: () => void
  onEditKeyDown: (e: KeyboardEvent<HTMLInputElement>) => void
  onRemarkChange: (remark: string) => void
  onSaveRemark: () => void
  onCancelRemark: () => void
  onStartRemark: () => void
  onStartEdit: () => void
  onToggle: () => void
  onDelete: () => void
  onDragStart: (e: DragEvent<HTMLElement>) => void
  onDragEnd: () => void
  dragging: boolean
}

function TodoItemRow({
  item,
  busy,
  editing,
  editText,
  remarkEditing,
  editRemark,
  onEditTextChange,
  onSaveEdit,
  onCancelEdit,
  onEditKeyDown,
  onRemarkChange,
  onSaveRemark,
  onCancelRemark,
  onStartRemark,
  onStartEdit,
  onToggle,
  onDelete,
  onDragStart,
  onDragEnd,
  dragging,
}: TodoItemRowProps) {
  const { t } = useTranslation()
  const classes = [
    'todo-item',
    item.done ? 'todo-item--done' : '',
    dragging ? 'todo-item--dragging' : '',
    editing || remarkEditing ? 'todo-item--editing' : '',
  ]
    .filter(Boolean)
    .join(' ')

  return (
    <div
      className={classes}
      data-testid="todo-item"
      draggable={!editing && !remarkEditing && !busy}
      onDragStart={onDragStart}
      onDragEnd={onDragEnd}
    >
      {editing ? (
        <div className="todo-item__edit">
          <input
            className="todo-item__edit-input form-input"
            type="text"
            value={editText}
            aria-label={t('todo.edit')}
            autoFocus
            disabled={busy}
            onChange={e => onEditTextChange(e.target.value)}
            onKeyDown={onEditKeyDown}
          />
          <button
            className="btn btn-primary btn-sm"
            disabled={busy || !editText.trim()}
            onClick={onSaveEdit}
          >
            <Check size={14} />
            {t('todo.save')}
          </button>
          <button className="btn btn-ghost btn-sm" disabled={busy} onClick={onCancelEdit}>
            <X size={14} />
            {t('todo.cancel')}
          </button>
        </div>
      ) : (
        <div className="todo-item__body">
          <div className="todo-item__row">
            <input
              className="todo-item__checkbox"
              type="checkbox"
              checked={item.done}
              disabled={busy}
              aria-label={item.text}
              onChange={onToggle}
            />
            <span className="todo-item__text">{item.text}</span>
            <div className="todo-item__actions">
              <button
                className="todo-item__action"
                aria-label={t('todo.remark')}
                title={t('todo.remark')}
                disabled={busy}
                onClick={onStartRemark}
              >
                <StickyNote size={14} />
              </button>
              <button
                className="todo-item__action"
                aria-label={t('todo.edit')}
                title={t('todo.edit')}
                disabled={busy}
                onClick={onStartEdit}
              >
                <Pencil size={14} />
              </button>
              <button
                className="todo-item__action todo-item__action--danger"
                aria-label={t('todo.delete')}
                title={t('todo.delete')}
                disabled={busy}
                onClick={onDelete}
              >
                <Trash2 size={14} />
              </button>
            </div>
          </div>
          {remarkEditing ? (
            <div className="todo-item__remark-edit">
              <textarea
                className="todo-item__remark-textarea form-input"
                value={editRemark}
                aria-label={t('todo.remark')}
                rows={3}
                autoFocus
                disabled={busy}
                onChange={e => onRemarkChange(e.target.value)}
              />
              <div className="todo-item__remark-edit-actions">
                <button className="btn btn-primary btn-sm" disabled={busy} onClick={onSaveRemark}>
                  <Check size={14} />
                  {t('todo.save')}
                </button>
                <button className="btn btn-ghost btn-sm" disabled={busy} onClick={onCancelRemark}>
                  <X size={14} />
                  {t('todo.cancel')}
                </button>
              </div>
            </div>
          ) : item.remark ? (
            <div className="todo-item__remark">
              <MarkdownContent content={item.remark} />
            </div>
          ) : null}
        </div>
      )}
    </div>
  )
}

interface TodoListPanelProps {
  /** Items visible under the current filter. */
  items: TodoItem[]
  /** Unfiltered items, used for the filter counts and the empty-state decision. */
  allItems: TodoItem[]
  filter: TodoFilter
  onFilterChange: (value: TodoFilter) => void
  busy: boolean
  onAdd: (text: string) => void
  onToggle: (item: TodoItem) => void
  onDelete: (index: number) => void
  onSaveText: (index: number, text: string) => void
  onSaveRemark: (index: number, remark: string) => void
  onMoveToGroup: (index: number, group: string) => void
  onCreateGroup: (name: string) => void
  onRenameGroup: (oldName: string, newName: string) => void
  onDeleteGroup: (name: string) => void
}

function TodoListPanel({
  items,
  allItems,
  filter,
  onFilterChange,
  busy,
  onAdd,
  onToggle,
  onDelete,
  onSaveText,
  onSaveRemark,
  onMoveToGroup,
  onCreateGroup,
  onRenameGroup,
  onDeleteGroup,
}: TodoListPanelProps) {
  const { t } = useTranslation()
  const [newText, setNewText] = useState('')
  const [editingIndex, setEditingIndex] = useState<number | null>(null)
  const [editText, setEditText] = useState('')
  const [remarkIndex, setRemarkIndex] = useState<number | null>(null)
  const [editRemark, setEditRemark] = useState('')
  const [groupKey, setGroupKey] = useState<string>('')
  // Named groups with no members yet (created locally, empty on the server).
  const [emptyGroups, setEmptyGroups] = useState<string[]>([])
  // Which group action is open: null, 'create', or the name being renamed.
  const [editorMode, setEditorMode] = useState<'create' | 'rename' | null>(null)
  const [renameTarget, setRenameTarget] = useState('')
  const [draggingIndex, setDraggingIndex] = useState<number | null>(null)

  const groupOptions = useMemo(
    () => buildGroupOptions(items, emptyGroups),
    [items, emptyGroups],
  )
  const showGroupFilter = hasGroupChoices(items, emptyGroups)
  const shownItems = useMemo(() => {
    if (groupKey === '') return items
    return items.filter(item => (item.group ?? '') === (groupKey === UNGROUPED_KEY ? '' : groupKey))
  }, [items, groupKey])

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

  const startRemark = useCallback((item: TodoItem) => {
    setRemarkIndex(item.index)
    setEditRemark(item.remark)
  }, [])

  const cancelRemark = useCallback(() => {
    setRemarkIndex(null)
    setEditRemark('')
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
      cancelRemark()
      setDraggingIndex(null)
    }
  }, [items, cancelEdit, cancelRemark])

  const saveEdit = useCallback(() => {
    const text = editText.trim()
    if (editingIndex === null || !text || busy) return
    onSaveText(editingIndex, text)
    setEditingIndex(null)
    setEditText('')
  }, [editingIndex, editText, busy, onSaveText])

  const saveRemark = useCallback(() => {
    if (remarkIndex === null) return
    const remark = editRemark.trim()
    onSaveRemark(remarkIndex, remark)
    setRemarkIndex(null)
    setEditRemark('')
  }, [remarkIndex, editRemark, onSaveRemark])

  // ---- group management --------------------------------------------------

  const closeEditor = useCallback(() => {
    setEditorMode(null)
    setRenameTarget('')
  }, [])

  const submitEditor = useCallback(
    (name: string) => {
      if (editorMode === 'create') {
        onCreateGroup(name)
        setEmptyGroups(prev => (prev.includes(name) ? prev : [...prev, name]))
        setGroupKey(name) // select the fresh group so items can be dropped in
        closeEditor()
      } else if (editorMode === 'rename' && renameTarget) {
        const target = renameTarget
        onRenameGroup(target, name)
        setEmptyGroups(prev =>
          prev.map(existing => (existing === target ? name : existing)),
        )
        if (groupKey === target) setGroupKey(name)
        closeEditor()
      }
    },
    [editorMode, renameTarget, groupKey, onCreateGroup, onRenameGroup, closeEditor],
  )

  const startRename = useCallback(
    (name: string) => {
      setRenameTarget(name)
      setEditorMode('rename')
    },
    [],
  )

  const requestDeleteGroup = useCallback(
    (name: string) => {
      if (!window.confirm(t('todo.confirmDeleteGroup'))) return
      onDeleteGroup(name)
      setEmptyGroups(prev => prev.filter(existing => existing !== name))
      if (groupKey === name) setGroupKey('')
    },
    [t, onDeleteGroup, groupKey],
  )

  // ---- drag & drop -------------------------------------------------------

  const handleItemDragStart = useCallback(
    (item: TodoItem) => (e: DragEvent<HTMLElement>) => {
      e.dataTransfer.setData(CARD_MIME, serializeDrag({ kind: 'item', index: item.index }))
      e.dataTransfer.effectAllowed = 'move'
      setDraggingIndex(item.index)
    },
    [],
  )

  const handleDropCard = useCallback(
    (targetKey: string | null) => {
      if (targetKey === null || draggingIndex === null) return
      const index = draggingIndex
      const sourceGroup = items.find(item => item.index === index)?.group ?? ''
      if (targetKey === sourceGroup) return // dragging onto its own card
      setDraggingIndex(null)
      onMoveToGroup(index, targetKey)
    },
    [draggingIndex, items, onMoveToGroup],
  )

  const doneCount = allItems.filter(item => item.done).length
  const counts = { all: allItems.length, active: allItems.length - doneCount, done: doneCount }

  const renderEmptyState = () => {
    if (allItems.length === 0) {
      return <TodoEmptyState icon={ClipboardList} text={t('todo.empty')} />
    }
    if (filter === 'active') {
      return <TodoEmptyState icon={CheckCircle2} variant="celebrate" text={t('todo.noActive')} />
    }
    return <TodoEmptyState icon={Inbox} text={t('todo.noCompleted')} />
  }

  const renderItems = (source: TodoItem[]) =>
    source.map(item => (
      <TodoItemRow
        key={item.index}
        item={item}
        busy={busy}
        editing={editingIndex === item.index}
        editText={editText}
        remarkEditing={remarkIndex === item.index}
        editRemark={editRemark}
        dragging={draggingIndex === item.index}
        onEditTextChange={setEditText}
        onSaveEdit={saveEdit}
        onCancelEdit={cancelEdit}
        onEditKeyDown={e => {
          if (e.key === 'Enter') {
            e.preventDefault()
            saveEdit()
          } else if (e.key === 'Escape') {
            cancelEdit()
          }
        }}
        onRemarkChange={setEditRemark}
        onSaveRemark={saveRemark}
        onCancelRemark={cancelRemark}
        onStartRemark={() => startRemark(item)}
        onStartEdit={() => startEdit(item)}
        onToggle={() => onToggle(item)}
        onDelete={() => onDelete(item.index)}
        onDragStart={handleItemDragStart(item)}
        onDragEnd={() => setDraggingIndex(null)}
      />
    ))

  return (
    <>
      {showGroupFilter && (
        <TodoGroupFilter
          options={groupOptions}
          selected={groupKey}
          onSelect={setGroupKey}
          kind="items"
          onDropCard={handleDropCard}
          onRename={startRename}
          onDelete={requestDeleteGroup}
          onNewGroup={() => setEditorMode('create')}
          busy={busy}
        />
      )}
      {editorMode !== null && (
        <GroupNameEditor
          mode={editorMode}
          initialValue={editorMode === 'rename' ? renameTarget : ''}
          busy={busy}
          onSubmit={submitEditor}
          onCancel={closeEditor}
        />
      )}

      <TodoFilterTabs value={filter} counts={counts} onChange={onFilterChange} />

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
        <button className="btn btn-primary" disabled={busy || !newText.trim()} onClick={submitNew}>
          <Plus size={14} />
          {t('todo.add')}
        </button>
      </div>

      {shownItems.length === 0 ? (
        renderEmptyState()
      ) : groupKey === '' ? (
        <div className="todo-list">
          {groupByHeading(items).map(group => (
            <div key={`group-${group.key}`} className="todo-group" data-testid="todo-group">
              <div className="todo-group__header" data-testid="todo-group-header">
                {group.key || t('todo.ungrouped')}
              </div>
              {renderItems(group.items)}
            </div>
          ))}
        </div>
      ) : (
        <div className="todo-list">{renderItems(shownItems)}</div>
      )}
    </>
  )
}

// ---------------------------------------------------------------------------
// Notes panel
// ---------------------------------------------------------------------------

interface TodoNotesPanelProps {
  notes: TodoNote[]
  busy: boolean
  onAdd: (content: string) => void
  onUpdate: (index: number, content: string) => void
  onDelete: (index: number) => void
  onMoveToGroup: (index: number, group: string) => void
  onCreateGroup: (name: string) => void
  onRenameGroup: (oldName: string, newName: string) => void
  onDeleteGroup: (name: string) => void
}

interface NoteGroup {
  key: string
  notes: TodoNote[]
}

/** Groups notes by the date part of their 'YYYY-MM-DD HH:MM' timestamp.
 * Pure function: input order is preserved (API returns newest first) and
 * groups appear in first-occurrence order. */
function groupNotesByDay(notes: TodoNote[]): NoteGroup[] {
  const groups = new Map<string, TodoNote[]>()
  for (const note of notes) {
    const key = note.timestamp.slice(0, 10)
    const bucket = groups.get(key)
    if (bucket) {
      bucket.push(note)
    } else {
      groups.set(key, [note])
    }
  }
  return Array.from(groups, ([key, bucket]) => ({ key, notes: bucket }))
}

interface HeadingGroup<T> {
  /** Group key from the '# heading' marker; '' means ungrouped. */
  key: string
  items: T[]
}

/** Groups entries by their '#' heading marker. The ungrouped bucket (empty
 * key) always comes first, other groups in first-occurrence order. */
function groupByHeading<T extends { group?: string | null }>(list: T[]): HeadingGroup<T>[] {
  const groups = new Map<string, HeadingGroup<T>>()
  for (const entry of list) {
    const key = entry.group ?? ''
    const bucket = groups.get(key)
    if (bucket) {
      bucket.items.push(entry)
    } else {
      groups.set(key, { key, items: [entry] })
    }
  }
  const ungrouped = groups.get('')
  if (!ungrouped) return Array.from(groups.values())
  return [ungrouped, ...Array.from(groups.values()).filter(group => group !== ungrouped)]
}

/** Formats a Date as local YYYY-MM-DD, matching the date part of note
 * timestamps. Manual padding is locale/timezone stable (no 'sv-SE' trick). */
function toLocalDateKey(date: Date): string {
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${date.getFullYear()}-${month}-${day}`
}

interface TodoNoteCardProps {
  note: TodoNote
  busy: boolean
  editing: boolean
  editContent: string
  onEditChange: (content: string) => void
  onSaveEdit: () => void
  onCancelEdit: () => void
  onEditKeyDown: (e: KeyboardEvent<HTMLTextAreaElement>) => void
  onStartEdit: () => void
  onDelete: () => void
  onDragStart: (e: DragEvent<HTMLElement>) => void
  onDragEnd: () => void
  dragging: boolean
}

function TodoNoteCard({
  note,
  busy,
  editing,
  editContent,
  onEditChange,
  onSaveEdit,
  onCancelEdit,
  onEditKeyDown,
  onStartEdit,
  onDelete,
  onDragStart,
  onDragEnd,
  dragging,
}: TodoNoteCardProps) {
  const { t } = useTranslation()
  const classes = [
    'todo-note',
    dragging ? 'todo-note--dragging' : '',
    editing ? 'todo-note--editing' : '',
  ]
    .filter(Boolean)
    .join(' ')
  return (
    <div
      className={classes}
      data-testid="todo-note"
      draggable={!editing && !busy}
      onDragStart={onDragStart}
      onDragEnd={onDragEnd}
    >
      <div className="todo-note__header">
        <span className="todo-note__time">{note.timestamp}</span>
        <div className="todo-note__actions">
          <button
            className="todo-note__action"
            aria-label={t('todo.edit')}
            title={t('todo.edit')}
            disabled={busy}
            onClick={onStartEdit}
          >
            <Pencil size={14} />
          </button>
          <button
            className="todo-note__action todo-note__action--danger"
            aria-label={t('todo.delete')}
            title={t('todo.delete')}
            disabled={busy}
            onClick={onDelete}
            data-testid="note-delete"
          >
            <Trash2 size={14} />
          </button>
        </div>
      </div>
      {editing ? (
        <div className="todo-note__edit">
          <textarea
            className="todo-note__edit-textarea form-input"
            value={editContent}
            aria-label={t('todo.edit')}
            rows={3}
            autoFocus
            disabled={busy}
            onChange={e => onEditChange(e.target.value)}
            onKeyDown={onEditKeyDown}
          />
          <div className="todo-note__edit-actions">
            <button className="btn btn-primary btn-sm" disabled={busy || !editContent.trim()} onClick={onSaveEdit}>
              <Check size={14} />
              {t('todo.save')}
            </button>
            <button className="btn btn-ghost btn-sm" disabled={busy} onClick={onCancelEdit}>
              <X size={14} />
              {t('todo.cancel')}
            </button>
          </div>
        </div>
      ) : (
        <div className="todo-note__content">{note.content}</div>
      )}
    </div>
  )
}

function TodoNotesPanel({
  notes,
  busy,
  onAdd,
  onUpdate,
  onDelete,
  onMoveToGroup,
  onCreateGroup,
  onRenameGroup,
  onDeleteGroup,
}: TodoNotesPanelProps) {
  const { t } = useTranslation()
  const [draft, setDraft] = useState('')
  const [editingIndex, setEditingIndex] = useState<number | null>(null)
  const [editDraft, setEditDraft] = useState('')
  const [groupKey, setGroupKey] = useState<string>('')
  const [emptyGroups, setEmptyGroups] = useState<string[]>([])
  const [editorMode, setEditorMode] = useState<'create' | 'rename' | null>(null)
  const [renameTarget, setRenameTarget] = useState('')
  const [draggingIndex, setDraggingIndex] = useState<number | null>(null)

  const groupOptions = useMemo(() => buildGroupOptions(notes, emptyGroups), [notes, emptyGroups])
  const showGroupFilter = hasGroupChoices(notes, emptyGroups)
  const shownNotes = useMemo(() => {
    if (groupKey === '') return notes
    return notes.filter(note => (note.group ?? '') === (groupKey === UNGROUPED_KEY ? '' : groupKey))
  }, [notes, groupKey])

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
      setDraggingIndex(null)
    }
  }, [notes, cancelEdit])

  const saveEdit = useCallback(() => {
    const content = editDraft.trim()
    if (editingIndex === null || !content || busy) return
    onUpdate(editingIndex, content)
    setEditingIndex(null)
    setEditDraft('')
  }, [editingIndex, editDraft, busy, onUpdate])

  // Translate date-group keys: today/yesterday get friendly labels, older
  // groups show their raw YYYY-MM-DD key. Local date arithmetic avoids the
  // UTC drift that parsing 'YYYY-MM-DD' timestamps would introduce.
  const now = new Date()
  const todayKey = toLocalDateKey(now)
  const yesterdayKey = toLocalDateKey(
    new Date(now.getFullYear(), now.getMonth(), now.getDate() - 1),
  )
  const groupLabel = (key: string): string => {
    if (key === todayKey) return t('todo.today')
    if (key === yesterdayKey) return t('todo.yesterday')
    return key
  }

  // ---- group management --------------------------------------------------

  const closeEditor = useCallback(() => {
    setEditorMode(null)
    setRenameTarget('')
  }, [])

  const submitEditor = useCallback(
    (name: string) => {
      if (editorMode === 'create') {
        onCreateGroup(name)
        setEmptyGroups(prev => (prev.includes(name) ? prev : [...prev, name]))
        setGroupKey(name)
        closeEditor()
      } else if (editorMode === 'rename' && renameTarget) {
        const target = renameTarget
        onRenameGroup(target, name)
        setEmptyGroups(prev => prev.map(existing => (existing === target ? name : existing)))
        if (groupKey === target) setGroupKey(name)
        closeEditor()
      }
    },
    [editorMode, renameTarget, groupKey, onCreateGroup, onRenameGroup, closeEditor],
  )

  const startRename = useCallback((name: string) => {
    setRenameTarget(name)
    setEditorMode('rename')
  }, [])

  const requestDeleteGroup = useCallback(
    (name: string) => {
      if (!window.confirm(t('todo.confirmDeleteGroup'))) return
      onDeleteGroup(name)
      setEmptyGroups(prev => prev.filter(existing => existing !== name))
      if (groupKey === name) setGroupKey('')
    },
    [t, onDeleteGroup, groupKey],
  )

  // ---- drag & drop -------------------------------------------------------

  const handleNoteDragStart = useCallback(
    (note: TodoNote) => (e: DragEvent<HTMLElement>) => {
      e.dataTransfer.setData(CARD_MIME, serializeDrag({ kind: 'note', index: note.index }))
      e.dataTransfer.effectAllowed = 'move'
      setDraggingIndex(note.index)
    },
    [],
  )

  const handleDropCard = useCallback(
    (targetKey: string | null) => {
      if (targetKey === null || draggingIndex === null) return
      const index = draggingIndex
      const sourceGroup = notes.find(note => note.index === index)?.group ?? ''
      if (targetKey === sourceGroup) return // dragging onto its own card
      setDraggingIndex(null)
      onMoveToGroup(index, targetKey)
    },
    [draggingIndex, notes, onMoveToGroup],
  )

  /** Renders one note card with shared edit/drag wiring. */
  const renderNoteCard = (note: TodoNote) => (
    <TodoNoteCard
      key={note.index}
      note={note}
      busy={busy}
      editing={editingIndex === note.index}
      editContent={editDraft}
      dragging={draggingIndex === note.index}
      onEditChange={setEditDraft}
      onSaveEdit={saveEdit}
      onCancelEdit={cancelEdit}
      onEditKeyDown={e => {
        if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
          e.preventDefault()
          saveEdit()
        } else if (e.key === 'Escape') {
          cancelEdit()
        }
      }}
      onStartEdit={() => startEdit(note)}
      onDelete={() => onDelete(note.index)}
      onDragStart={handleNoteDragStart(note)}
      onDragEnd={() => setDraggingIndex(null)}
    />
  )

  /** Day sub-headers + note cards for a single heading (or ungrouped) slice. */
  const renderDayGroups = (source: TodoNote[]) =>
    groupNotesByDay(source).flatMap(dayGroup => [
      <div
        key={`day-${dayGroup.key}`}
        className="todo-note-group__header"
        data-testid="note-group-header"
      >
        {groupLabel(dayGroup.key)}
      </div>,
      ...dayGroup.notes.map(renderNoteCard),
    ])

  /** All view: heading groups (incl. ungrouped) wrap the day sub-headers. */
  const renderAllNotes = (source: TodoNote[]) => (
    <div className="todo-note-list">
      {groupByHeading(source).map(heading => (
        <div key={`heading-${heading.key}`} className="todo-group" data-testid="todo-group">
          <div className="todo-group__header" data-testid="todo-group-header">
            {heading.key || t('todo.ungrouped')}
          </div>
          {renderDayGroups(heading.items)}
        </div>
      ))}
    </div>
  )

  /** Single-group view: flat day sub-headers only (no heading layer). */
  const renderOneGroupNotes = (source: TodoNote[]) => (
    <div className="todo-note-list">{renderDayGroups(source)}</div>
  )

  return (
    <>
      {showGroupFilter && (
        <TodoGroupFilter
          options={groupOptions}
          selected={groupKey}
          onSelect={setGroupKey}
          kind="notes"
          onDropCard={handleDropCard}
          onRename={startRename}
          onDelete={requestDeleteGroup}
          onNewGroup={() => setEditorMode('create')}
          busy={busy}
        />
      )}
      {editorMode !== null && (
        <GroupNameEditor
          mode={editorMode}
          initialValue={editorMode === 'rename' ? renameTarget : ''}
          busy={busy}
          onSubmit={submitEditor}
          onCancel={closeEditor}
        />
      )}

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

      {shownNotes.length === 0 ? (
        <TodoEmptyState icon={StickyNote} text={t('todo.emptyNotes')} />
      ) : groupKey === '' ? (
        renderAllNotes(notes)
      ) : (
        renderOneGroupNotes(shownNotes)
      )}
    </>
  )
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

/** Removes blank placeholder notes (the anchor an empty notes group writes
 * to disk) from the lists the UI operates on. They carry no content and only
 * exist to persist the group marker. */
function withoutPlaceholderNotes(notes: TodoNote[]): TodoNote[] {
  return notes.filter(note => note.content !== '')
}

export function TodoPage() {
  const { t } = useTranslation()
  const [enabled, setEnabled] = useState<boolean | null>(null)
  const [items, setItems] = useState<TodoItem[]>([])
  const [notes, setNotes] = useState<TodoNote[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [filter, setFilter] = useState<TodoFilter>('active')
  // Synchronous mutex: guards against duplicate requests from rapid clicks
  // before the busy state re-render takes effect.
  const busyRef = useRef(false)

  // Filtering is a pure view-layer concern: write operations replace `items`
  // with the full server list and the visible subset re-derives automatically.
  const visibleItems = useMemo(() => {
    if (filter === 'active') return items.filter(item => !item.done)
    if (filter === 'done') return items.filter(item => item.done)
    return items
  }, [items, filter])

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
      setNotes(withoutPlaceholderNotes(loadedNotes))
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
        setNotes(withoutPlaceholderNotes(await operation()))
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
  const handleSaveItemRemark = useCallback(
    (index: number, remark: string) => void writeItems(() => updateTodoItem(index, { remark })),
    [writeItems],
  )
  const handleMoveItemToGroup = useCallback(
    (index: number, group: string) => void writeItems(() => updateTodoItem(index, { group })),
    [writeItems],
  )
  const handleCreateItemGroup = useCallback(
    (name: string) => void writeItems(() => createItemGroup(name)),
    [writeItems],
  )
  const handleRenameItemGroup = useCallback(
    (oldName: string, newName: string) =>
      void writeItems(() => renameItemGroup(oldName, newName)),
    [writeItems],
  )
  const handleDeleteItemGroup = useCallback(
    (name: string) => void writeItems(() => deleteItemGroup(name)),
    [writeItems],
  )

  const handleAddNote = useCallback(
    (content: string) => void writeNotes(() => addNote(content)),
    [writeNotes],
  )
  const handleUpdateNote = useCallback(
    (index: number, content: string) => void writeNotes(() => updateNote(index, { content })),
    [writeNotes],
  )
  const handleDeleteNote = useCallback(
    (index: number) => void writeNotes(() => deleteNote(index)),
    [writeNotes],
  )
  const handleMoveNoteToGroup = useCallback(
    (index: number, group: string) => void writeNotes(() => updateNote(index, { group })),
    [writeNotes],
  )
  const handleCreateNoteGroup = useCallback(
    (name: string) => void writeNotes(() => createNoteGroup(name)),
    [writeNotes],
  )
  const handleRenameNoteGroup = useCallback(
    (oldName: string, newName: string) =>
      void writeNotes(() => renameNoteGroup(oldName, newName)),
    [writeNotes],
  )
  const handleDeleteNoteGroup = useCallback(
    (name: string) => void writeNotes(() => deleteNoteGroup(name)),
    [writeNotes],
  )

  if (loading) {
    return (
      <div className="page-container" data-testid="todo-loading" aria-busy="true">
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
            items={visibleItems}
            allItems={items}
            filter={filter}
            onFilterChange={setFilter}
            busy={busy}
            onAdd={handleAddItem}
            onToggle={handleToggleItem}
            onDelete={handleDeleteItem}
            onSaveText={handleSaveItemText}
            onSaveRemark={handleSaveItemRemark}
            onMoveToGroup={handleMoveItemToGroup}
            onCreateGroup={handleCreateItemGroup}
            onRenameGroup={handleRenameItemGroup}
            onDeleteGroup={handleDeleteItemGroup}
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
            onMoveToGroup={handleMoveNoteToGroup}
            onCreateGroup={handleCreateNoteGroup}
            onRenameGroup={handleRenameNoteGroup}
            onDeleteGroup={handleDeleteNoteGroup}
          />
        </section>
      </div>
    </div>
  )
}

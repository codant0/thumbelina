import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Search,
  SearchX,
  Lock,
  Loader2,
  X,
  ChevronDown,
  Brain,
  User,
  FolderKanban,
  Scale,
  Hash,
  Inbox,
  Clock,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { useTranslation } from '../../i18n'
import { MarkdownContent } from '../Chat/MarkdownContent'

interface MemorySummary {
  title: string
  category: string
  slug: string
  summary: string
  updated: string
  source: string
  relpath: string
}

interface MemoryHit {
  title: string
  category: string
  slug: string
  summary: string
  score: number
  matched_field: string
  snippet: string
  updated: string
  source: string
}

interface MemoryDisplay {
  relpath: string
  category: string
  slug: string
  title: string
  summary: string
  updated: string
  source: string
  snippet?: string
  matchedField?: string
}

interface MemoryDetail {
  overview: string
  full_text: string
}

const CATEGORY_ORDER: ReadonlyArray<string> = ['user', 'project', 'decision', 'topic']

const CATEGORY_ICONS: Record<string, LucideIcon> = {
  user: User,
  project: FolderKanban,
  decision: Scale,
  topic: Hash,
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

/** Highlights exact query matches inside text (safe against regex metachars). */
function renderHighlight(text: string, query: string) {
  const q = query.trim()
  if (!q || !text) return text
  const parts = text.split(new RegExp(`(${escapeRegExp(q)})`, 'gi'))
  return parts.map((part, i) =>
    part && part.toLowerCase() === q.toLowerCase() ? <mark key={i}>{part}</mark> : part,
  )
}

interface GroupOption {
  key: string
  label: string
  count: number
  icon: 'all' | 'user' | 'project' | 'decision' | 'topic'
}

interface MemoryEntryCardProps {
  entry: MemoryDisplay
  expanded: boolean
  query: string
  detail: MemoryDetail | undefined
  matchLabel: (field: string) => string
  categoryLabel: (category: string) => string
  onToggle: () => void
}

function MemoryEntryCard({
  entry,
  expanded,
  query,
  detail,
  matchLabel,
  categoryLabel,
  onToggle,
}: MemoryEntryCardProps) {
  const { t } = useTranslation()
  const CatIcon = CATEGORY_ICONS[entry.category] ?? Inbox
  return (
    <div
      className={`memory-entry${expanded ? ' memory-entry--expanded' : ''}`}
      data-testid="memory-entry"
    >
      <button
        type="button"
        className="memory-entry__header"
        aria-expanded={expanded}
        aria-label={`${entry.title}${expanded ? `, ${t('memory.collapse')}` : ''}`}
        data-testid="memory-entry-toggle"
        onClick={onToggle}
      >
        <span className={`memory-cat memory-cat--${entry.category}`}>
          <CatIcon size={12} aria-hidden="true" />
          {categoryLabel(entry.category)}
        </span>
        <span className="memory-entry__title">{entry.title}</span>
        {entry.matchedField && (
          <span className="memory-match" title={t('memory.updatedAt')}>
            {matchLabel(entry.matchedField)}
          </span>
        )}
        {entry.updated && (
          <span className="memory-entry__updated" title={t('memory.updatedAt')}>
            {entry.updated}
          </span>
        )}
        <ChevronDown size={14} aria-hidden="true" className="memory-entry__chevron" />
      </button>
      <div className="memory-entry__summary" data-testid="memory-entry-summary">
        {entry.snippet
          ? renderHighlight(entry.snippet, query)
          : entry.summary || '–'}
      </div>
      {expanded && (
        <div className="memory-entry__detail" data-testid="memory-entry-detail">
          {!detail ? (
            <Loader2 size={14} className="spin" aria-label={t('common.loading')} />
          ) : detail.overview || detail.full_text ? (
            <>
              {detail.overview && (
                <section className="memory-entry__section">
                  <h4>{t('memory.overview')}</h4>
                  <MarkdownContent content={detail.overview} />
                </section>
              )}
              {detail.full_text && (
                <section className="memory-entry__section">
                  <h4>{t('memory.fullText')}</h4>
                  <MarkdownContent content={detail.full_text} />
                </section>
              )}
            </>
          ) : (
            <p className="task-empty">–</p>
          )}
        </div>
      )}
    </div>
  )
}

export function MemoryViewer() {
  const { t } = useTranslation()
  const [input, setInput] = useState('')
  const [query, setQuery] = useState('')
  const [browse, setBrowse] = useState<MemorySummary[]>([])
  const [results, setResults] = useState<MemoryHit[]>([])
  const [enabled, setEnabled] = useState<boolean | null>(null)
  const [entriesLoading, setEntriesLoading] = useState(true)
  const [searching, setSearching] = useState(false)
  const [error, setError] = useState('')
  const [groupKey, setGroupKey] = useState('')
  const [expandedKey, setExpandedKey] = useState<string | null>(null)
  const [detailCache, setDetailCache] = useState<Record<string, MemoryDetail>>({})

  const hasQuery = query.trim() !== ''

  const categoryLabel = useCallback(
    (category: string): string => {
      switch (category) {
        case 'user':
          return t('memory.categoryUser')
        case 'project':
          return t('memory.categoryProject')
        case 'decision':
          return t('memory.categoryDecision')
        case 'topic':
          return t('memory.categoryTopic')
        default:
          return category
      }
    },
    [t],
  )

  const matchLabel = useCallback(
    (field: string): string => {
      switch (field) {
        case 'title':
          return t('memory.matchedTitle')
        case 'summary':
          return t('memory.matchedSummary')
        case 'overview':
          return t('memory.matchedOverview')
        default:
          return t('memory.matchedFullText')
      }
    },
    [t],
  )

  useEffect(() => {
    void (async () => {
      setEntriesLoading(true)
      setError('')
      try {
        const stRes = await fetch('/api/v1/memory/status')
        const st = stRes.ok ? await stRes.json().catch(() => ({})) : {}
        const moduleEnabled = st.enabled ?? true
        setEnabled(moduleEnabled)
        if (!moduleEnabled) return
        const res = await fetch('/api/v1/memory/entries')
        if (res.ok) {
          setBrowse(await res.json())
        } else {
          setError(t('common.error'))
        }
      } catch {
        setEnabled(true)
        setError(t('common.error'))
      } finally {
        setEntriesLoading(false)
      }
    })()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const handleSearch = useCallback(async () => {
    const q = input.trim()
    if (!q) return
    setSearching(true)
    setError('')
    setExpandedKey(null)
    setGroupKey('')
    try {
      const res = await fetch(`/api/v1/memory/search?q=${encodeURIComponent(q)}&top_k=50`)
      if (!res.ok) {
        setError(t('memory.searchFailed'))
        return
      }
      setResults(await res.json())
      setQuery(q)
    } catch {
      setError(t('memory.searchFailed'))
    } finally {
      setSearching(false)
    }
  }, [input, t])

  const handleClear = useCallback(() => {
    setInput('')
    setQuery('')
    setResults([])
    setExpandedKey(null)
    setGroupKey('')
    setError('')
  }, [])

  const handleToggle = useCallback(
    async (entry: MemoryDisplay) => {
      const key = entry.relpath
      setExpandedKey(prev => (prev === key ? null : key))
      if (detailCache[key]) return
      try {
        const res = await fetch(`/api/v1/memory/${entry.category}/${entry.slug}?depth=full`)
        if (res.ok) {
          const data = await res.json()
          setDetailCache(prev => ({
            ...prev,
            [key]: { overview: data.overview ?? '', full_text: data.full_text ?? '' },
          }))
        }
      } catch { /* ignore */ }
    },
    [detailCache],
  )

  useEffect(() => {
    if (!expandedKey) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setExpandedKey(null)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [expandedKey])

  const base = useMemo((): MemoryDisplay[] => {
    if (hasQuery) {
      return results.map(r => ({
        relpath: `${r.category}/${r.slug}`,
        category: r.category,
        slug: r.slug,
        title: r.title,
        summary: r.summary,
        updated: r.updated,
        source: r.source,
        snippet: r.snippet,
        matchedField: r.matched_field,
      }))
    }
    return browse.map(e => ({
      relpath: e.relpath,
      category: e.category,
      slug: e.slug,
      title: e.title,
      summary: e.summary,
      updated: e.updated,
      source: e.source,
    }))
  }, [hasQuery, results, browse])

  const stats = useMemo(() => {
    const categories = new Set(browse.map(e => e.category)).size
    const latest = browse.reduce((max, e) => (e.updated > max ? e.updated : max), '')
    return { total: browse.length, categories, latest }
  }, [browse])

  const groupOptions = useMemo((): GroupOption[] => {
    if (base.length === 0) return []
    const counts = new Map<string, number>()
    for (const e of base) counts.set(e.category, (counts.get(e.category) ?? 0) + 1)
    const options: GroupOption[] = [
      { key: '', label: t('memory.all'), count: base.length, icon: 'all' },
    ]
    for (const cat of CATEGORY_ORDER) {
      const count = counts.get(cat)
      if (count) options.push({ key: cat, label: categoryLabel(cat), count, icon: cat as GroupOption['icon'] })
    }
    return options
  }, [base, t, categoryLabel])

  const visible = useMemo(() => {
    if (groupKey === '') return base
    return base.filter(e => e.category === groupKey)
  }, [base, groupKey])

  const grouped = useMemo(() => {
    if (groupKey !== '') return null
    const map = new Map<string, MemoryDisplay[]>()
    for (const e of visible) {
      const bucket = map.get(e.category)
      if (bucket) bucket.push(e)
      else map.set(e.category, [e])
    }
    const groups: Array<{ category: string; items: MemoryDisplay[] }> = []
    for (const cat of CATEGORY_ORDER) {
      const items = map.get(cat)
      if (items && items.length > 0) groups.push({ category: cat, items })
    }
    return groups
  }, [visible, groupKey])

  const renderList = () => {
    if (searching) {
      return <p className="memory-status"><Loader2 size={16} className="spin" />{t('memory.searching')}</p>
    }
    if (hasQuery && visible.length === 0) {
      return (
        <div className="memory-empty-state" data-testid="memory-no-results">
          <SearchX size={32} aria-hidden="true" />
          <p>{t('memory.noResults')}</p>
        </div>
      )
    }
    if (!hasQuery && base.length === 0) {
      return (
        <div className="memory-empty-state" data-testid="memory-empty">
          <Brain size={32} aria-hidden="true" />
          <p>{t('memory.empty')}</p>
        </div>
      )
    }
    const cards = (entries: MemoryDisplay[]) =>
      entries.map(entry => (
        <MemoryEntryCard
          key={entry.relpath}
          entry={entry}
          expanded={expandedKey === entry.relpath}
          query={query}
          detail={detailCache[entry.relpath]}
          matchLabel={matchLabel}
          categoryLabel={categoryLabel}
          onToggle={() => void handleToggle(entry)}
        />
      ))
    if (grouped) {
      return (
        <div className="memory-list" data-testid="memory-list">
          {grouped.map(group => (
            <div key={group.category} className="memory-group" data-testid="memory-group">
              <div className="memory-group__header" data-testid="memory-group-header">
                {categoryLabel(group.category)}
                <span className="memory-group__count">{group.items.length}</span>
              </div>
              {cards(group.items)}
            </div>
          ))}
        </div>
      )
    }
    return (
      <div className="memory-list" data-testid="memory-list">
        {cards(visible)}
      </div>
    )
  }

  if (entriesLoading) {
    return (
      <div className="page-container" data-testid="memory-viewer" aria-busy="true">
        <div className="page-title">{t('memory.title')}</div>
        <div className="card">
          <div className="memory-skeleton" />
          <div className="memory-skeleton" />
          <div className="memory-skeleton" />
        </div>
      </div>
    )
  }

  if (enabled === false) {
    return (
      <div className="page-container" data-testid="memory-viewer">
        <div className="page-title">{t('memory.title')}</div>
        <div className="memory-empty-state" data-testid="memory-disabled">
          <Lock size={32} aria-hidden="true" />
          <p>{t('memory.disabled')}</p>
        </div>
      </div>
    )
  }

  const allIcon = Brain
  return (
    <div className="page-container" data-testid="memory-viewer">
      <div className="page-title">{t('memory.title')}</div>

      <div className="memory-stats card" data-testid="memory-stats">
        <div className="memory-stats__item">
          <Brain className="memory-stats__icon" size={16} aria-hidden="true" />
          <span className="memory-stats__num">{stats.total}</span>{' '}
          <span className="memory-stats__label">{t('memory.statsTotal')}</span>
        </div>
        <div className="memory-stats__item">
          <FolderKanban className="memory-stats__icon" size={16} aria-hidden="true" />
          <span className="memory-stats__num">{stats.categories}</span>{' '}
          <span className="memory-stats__label">{t('memory.statsCategories')}</span>
        </div>
        <div className="memory-stats__item">
          <Clock className="memory-stats__icon" size={16} aria-hidden="true" />
          <span className="memory-stats__label">{t('memory.statsUpdated')}</span>{' '}
          <span className="memory-stats__num memory-stats__num--mono">{stats.latest || '–'}</span>
        </div>
      </div>

      <div className="card">
        <div className="card-title">
          <Search size={14} />
          {t('memory.searchMemories')}
        </div>
        <div className="search-bar">
          <div className="memory-search-box">
            <Search size={15} aria-hidden="true" className="memory-search-box__icon" />
            <input
              type="text"
              className="form-input"
              data-testid="search-input"
              placeholder={t('memory.searchPlaceholder')}
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={e => {
                if (e.key === 'Enter') void handleSearch()
              }}
            />
            {hasQuery && (
              <button
                className="memory-search-box__clear"
                data-testid="search-clear"
                title={t('memory.collapse')}
                aria-label={t('memory.collapse')}
                onClick={handleClear}
              >
                <X size={14} />
              </button>
            )}
          </div>
          <button
            className="btn btn-primary"
            data-testid="search-button"
            onClick={() => void handleSearch()}
            disabled={searching || !input.trim()}
          >
            {searching ? <Loader2 size={16} className="spin" /> : <Search size={16} />}
            {searching ? t('memory.searching') : t('memory.search')}
          </button>
        </div>
        {error && (
          <p data-testid="search-error" className="task-empty" style={{ color: 'var(--error)' }}>
            {error}
          </p>
        )}
        {groupOptions.length > 1 && (
          <div className="memory-group-filter" data-testid="memory-group-filter">
            {groupOptions.map(option => {
              const Icon =
                option.icon === 'all' ? allIcon : CATEGORY_ICONS[option.icon] ?? Inbox
              return (
                <button
                  key={option.key}
                  type="button"
                  aria-pressed={groupKey === option.key}
                  className={`memory-group-filter__card${groupKey === option.key ? ' memory-group-filter__card--selected' : ''}`}
                  data-testid="memory-group-filter-card"
                  onClick={() => setGroupKey(option.key)}
                  title={option.label}
                >
                  <Icon size={14} aria-hidden="true" />
                  <span>{option.label}</span>
                  <span className="memory-group-filter__badge" data-testid="memory-group-filter-count">
                    {option.count}
                  </span>
                </button>
              )
            })}
          </div>
        )}
        <div data-testid="search-results">{renderList()}</div>
      </div>
    </div>
  )
}
import { useCallback, useEffect, useRef, useState } from 'react'
import { Boxes, CircleAlert, Loader2, RefreshCw, Route, SearchX, Terminal, Wrench } from 'lucide-react'
import type { Conversation } from '../../types/chat'
import type { TrajectoryDetail, TrajectoryEvent, TrajectoryPageData, TrajectoryTurn } from '../../types/trajectory'
import { fetchTrajectory } from '../../api/trajectory'
import { useTranslation } from '../../i18n'
import { TrajectoryDetailModal } from './TrajectoryDetailModal'
import { collapseMiddle, eventLabel, groupToolEvents } from './trajectoryDisplay'
import type { ToolCallGroup } from './trajectoryDisplay'

const PAGE_SIZE = 20

export function TrajectoryPage({ initialConversationId }: { initialConversationId?: string }) {
  const { t } = useTranslation()
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [selectedId, setSelectedId] = useState<string | undefined>(initialConversationId)
  const [data, setData] = useState<TrajectoryPageData | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [notFound, setNotFound] = useState(false)
  const [detail, setDetail] = useState<TrajectoryDetail | null>(null)

  const listRef = useRef<HTMLDivElement>(null)
  const sentinelRef = useRef<HTMLDivElement>(null)
  const requestSeq = useRef(0)

  useEffect(() => {
    fetch('/api/v1/conversations')
      .then(res => (res.ok ? res.json() : []))
      .then(list => setConversations(Array.isArray(list) ? list : []))
      .catch(() => setConversations([]))
  }, [])

  const load = useCallback(async (conversationId: string, page: number, append: boolean) => {
    const seq = ++requestSeq.current
    setLoading(true)
    setError('')
    setNotFound(false)
    try {
      const pageData = await fetchTrajectory(conversationId, page, PAGE_SIZE)
      if (seq !== requestSeq.current) return
      setData(prev => {
        if (append && prev && prev.conversation_id === conversationId) {
          return { ...pageData, turns: [...prev.turns, ...pageData.turns] }
        }
        return pageData
      })
    } catch (err) {
      if (seq !== requestSeq.current) return
      // 会话不存在(404)时清空选择并提示,而不是展示可重试的通用错误。
      if ((err as { status?: number }).status === 404) {
        setSelectedId(undefined)
        setData(null)
        setNotFound(true)
        return
      }
      setError(t('trajectory.loadFailed'))
    } finally {
      if (seq === requestSeq.current) setLoading(false)
    }
  }, [t])

  useEffect(() => {
    if (selectedId) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      void load(selectedId, 1, false)
    } else {
      setData(null)
    }
  }, [selectedId, load])

  const handleSelect = (id: string) => {
    setSelectedId(id)
    setDetail(null)
    listRef.current?.scrollTo({ top: 0 })
  }

  const hasMore = data !== null && data.turns.length < data.total_turns

  useEffect(() => {
    if (!hasMore || loading || !sentinelRef.current || typeof IntersectionObserver === 'undefined') {
      return
    }
    const observer = new IntersectionObserver(
      entries => {
        if (entries[0]?.isIntersecting) {
          void load(selectedId ?? '', (data?.page ?? 1) + 1, true)
        }
      },
      { root: listRef.current, threshold: 0.05 },
    )
    observer.observe(sentinelRef.current)
    return () => observer.disconnect()
  }, [hasMore, loading, data?.page, selectedId, load])

  const openDetail = useCallback((target: TrajectoryDetail) => {
    setDetail(target)
  }, [])

  return (
    <div className="trajectory-page" data-testid="trajectory-page">
      <div className="trajectory-toolbar">
        <h2>{t('trajectory.title')}</h2>
        <select
          data-testid="trajectory-select"
          value={selectedId ?? ''}
          onChange={e => handleSelect(e.target.value)}
          className="trajectory-select"
        >
          <option value="">{t('trajectory.selectPlaceholder')}</option>
          {conversations.map(c => (
            <option key={c.id} value={c.id}>{c.name || c.id}</option>
          ))}
        </select>
      </div>

      {!selectedId && (
        <div className="trajectory-empty" data-testid="trajectory-empty">
          {notFound ? <SearchX size={36} aria-hidden="true" /> : <Route size={36} aria-hidden="true" />}
          <p className="trajectory-empty__title">
            {notFound ? t('trajectory.conversationNotFound') : t('trajectory.selectPlaceholder')}
          </p>
          <p className="trajectory-empty__hint">{t('trajectory.emptyHint')}</p>
        </div>
      )}

      {error && (
        <div className="trajectory-error" data-testid="trajectory-error">
          <span>{error}</span>
          <button type="button" data-testid="retry-button" onClick={() => selectedId && void load(selectedId, 1, false)}>
            <RefreshCw size={14} /> {t('trajectory.retry')}
          </button>
        </div>
      )}

      {loading && !data && <TrajectorySkeleton />}

      {data && (
        <div className="trajectory-list" data-testid="trajectory-list" ref={listRef}>
          <div className="timeline">
            {data.turns.map((turn, turnIndex) => (
              <TurnTrack
                key={turn.turn_id}
                turn={turn}
                turnIndex={turnIndex}
                turnNumber={data.total_turns - turnIndex}
                onOpenDetail={openDetail}
              />
            ))}
          </div>
          <div ref={sentinelRef} className="trajectory-sentinel" />
          {hasMore && (
            <button
              type="button"
              className="trajectory-load-more"
              data-testid="trajectory-load-more"
              disabled={loading}
              onClick={() => selectedId && void load(selectedId, (data?.page ?? 1) + 1, true)}
            >
              {loading ? <Loader2 size={14} /> : null} {t('trajectory.loadMore')}
            </button>
          )}
          {!hasMore && data.turns.length > 0 && (
            <div className="trajectory-loaded-all">{t('trajectory.loadedAll')}</div>
          )}
        </div>
      )}

      <TrajectoryDetailModal target={detail} onClose={() => setDetail(null)} />
    </div>
  )
}

function TrajectorySkeleton() {
  return (
    <div className="trajectory-loading" data-testid="trajectory-loading" aria-busy="true">
      <div className="timeline timeline-skeleton">
        <div className="skeleton-row">
          <span className="skeleton-node" aria-hidden="true" />
          <span className="skeleton-block skeleton-block--head" />
        </div>
        <div className="skeleton-row">
          <span />
          <span className="skeleton-block skeleton-block--bubble" />
        </div>
        <div className="skeleton-row">
          <span />
          <span className="skeleton-block skeleton-block--chip" />
        </div>
        <div className="skeleton-row">
          <span />
          <span className="skeleton-block skeleton-block--bubble skeleton-block--right" />
        </div>
      </div>
    </div>
  )
}

function TurnTrack({ turn, turnIndex, turnNumber, onOpenDetail }: {
  turn: TrajectoryTurn
  turnIndex: number
  turnNumber: number
  onOpenDetail: (target: TrajectoryDetail) => void
}) {
  const { t } = useTranslation()
  const hasError = turn.events.some(
    e => e.event_type === 'tool_result' && (e.payload as Record<string, unknown>).is_error === true,
  )
  return (
    <div className="turn-track" data-testid="turn-card">
      <span className={`turn-node${hasError ? ' turn-node--error' : ''}`} aria-hidden="true" />
      <button
        type="button"
        className="turn-header turn-header-btn"
        aria-label={`${t('trajectory.turnMeta')} #${turnNumber}`}
        onClick={() => onOpenDetail({ kind: 'turn-meta', turn, turnNumber })}
      >
        <span className="turn-name">{t('trajectory.turn')} #{turnNumber}</span>
        <time className="turn-time" dateTime={turn.started_at}>{turn.started_at}</time>
      </button>
      {turn.events.length === 0 ? (
        <div className="turn-events-empty">{t('trajectory.noEvents')}</div>
      ) : (
        <div className="turn-events">
          {groupToolEvents(turn.events).map(block =>
            'call' in block ? (
              <ToolCallCard
                key={`call-${block.call.seq}`}
                group={block}
                turnIndex={turnIndex}
                onOpenDetail={onOpenDetail}
              />
            ) : (
              <EventBlock
                key={block.seq}
                event={block}
                turnIndex={turnIndex}
                onOpenDetail={onOpenDetail}
              />
            ),
          )}
        </div>
      )}
    </div>
  )
}

function ToolCallCard({ group, turnIndex, onOpenDetail }: {
  group: ToolCallGroup
  turnIndex: number
  onOpenDetail: (target: TrajectoryDetail) => void
}) {
  const { t } = useTranslation()
  const payload = group.call.payload as Record<string, unknown>
  return (
    <div className="tool-call-card">
      <button
        type="button"
        className="tool-call-zone"
        data-testid="turn-event"
        onClick={() => onOpenDetail({ kind: 'event', event: group.call, turnIndex })}
      >
        <span className="chip-label">{eventLabel(t, group.call)}</span>
        <span className="chip-icon"><Wrench size={14} aria-hidden="true" /></span>
        <span className="event-summary">{collapseMiddle(JSON.stringify(payload.args ?? {}), 120, 60, 40).text}</span>
        <span className="event-more">{t('trajectory.viewDetails')}</span>
        {group.results.length === 0 && (
          <span className="tool-call-missing">{t('trajectory.noMatchingResult')}</span>
        )}
      </button>
      {group.results.map(result => {
        const resultPayload = result.payload as Record<string, unknown>
        const isError = resultPayload.is_error === true
        return (
          <button
            key={result.seq}
            type="button"
            className={`tool-call-zone tool-call-result${isError ? ' tool-call-result--error' : ''}`}
            data-testid="turn-event"
            onClick={() => onOpenDetail({ kind: 'event', event: result, turnIndex })}
          >
            <span className="chip-icon">
              {isError ? <CircleAlert size={14} aria-hidden="true" /> : <Terminal size={14} aria-hidden="true" />}
            </span>
            <span className="event-summary">
              {collapseMiddle(String(resultPayload.content ?? ''), 120, 60, 40).text || t('trajectory.noEvents')}
            </span>
            <span className="event-more">{t('trajectory.viewDetails')}</span>
          </button>
        )
      })}
    </div>
  )
}

function EventBlock({ event, turnIndex, onOpenDetail }: {
  event: TrajectoryEvent
  turnIndex: number
  onOpenDetail: (target: TrajectoryDetail) => void
}) {
  const { t } = useTranslation()
  const payload = event.payload as Record<string, unknown>

  if (event.event_type === 'user' || event.event_type === 'assistant') {
    const content = String(payload.content ?? '')
    const preview = collapseMiddle(content)
    return (
      <button
        type="button"
        className={`event-block event-block--bubble event-block--${event.event_type}${preview.truncated ? ' event-block--truncated' : ''}`}
        data-testid="turn-event"
        onClick={() => onOpenDetail({ kind: 'event', event, turnIndex })}
      >
        <span className="event-content">{preview.text}</span>
        {preview.truncated && <span className="event-more">{t('trajectory.viewDetails')}</span>}
      </button>
    )
  }

  const isError = event.event_type === 'tool_result' && payload.is_error === true
  const icon = event.event_type === 'context'
    ? <Boxes size={14} aria-hidden="true" />
    : isError
      ? <CircleAlert size={14} aria-hidden="true" />
      : <Terminal size={14} aria-hidden="true" />

  const summary = event.event_type === 'context'
    ? t('trajectory.contextCount').replace('{n}', String(Array.isArray(payload.items) ? payload.items.length : 0))
    : collapseMiddle(String(payload.content ?? ''), 120, 60, 40).text || t('trajectory.noEvents')

  return (
    <button
      type="button"
      className={`event-block event-block--chip${isError ? ' event-block--error' : ''}`}
      data-testid="turn-event"
      onClick={() => onOpenDetail({ kind: 'event', event, turnIndex })}
    >
      <span className="chip-label">{eventLabel(t, event)}</span>
      <span className="chip-icon">{icon}</span>
      <span className="event-summary">{summary}</span>
      <span className="event-more">{t('trajectory.viewDetails')}</span>
    </button>
  )
}
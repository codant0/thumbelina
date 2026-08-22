import { useCallback, useEffect, useRef, useState } from 'react'
import { Loader2, RefreshCw } from 'lucide-react'
import type { Conversation } from '../../types/chat'
import type { TrajectoryDetail, TrajectoryEvent, TrajectoryPageData, TrajectoryTurn } from '../../types/trajectory'
import { fetchTrajectory } from '../../api/trajectory'
import { useTranslation } from '../../i18n'
import { TrajectoryDetailModal } from './TrajectoryDetailModal'
import { collapseMiddle, eventLabel } from './trajectoryDisplay'

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
          {notFound ? t('trajectory.conversationNotFound') : t('trajectory.selectPlaceholder')}
        </div>
      )}

      {error && (
        <div className="trajectory-error" data-testid="trajectory-error">
          {error}
          <button type="button" data-testid="retry-button" onClick={() => selectedId && void load(selectedId, 1, false)}>
            <RefreshCw size={14} /> {t('trajectory.retry')}
          </button>
        </div>
      )}

      {loading && !data && <div className="trajectory-loading">{t('trajectory.loading')}</div>}

      {data && (
        <div className="trajectory-list" data-testid="trajectory-list" ref={listRef}>
          {data.turns.map((turn, turnIndex) => (
            <TurnCard
              key={turn.turn_id}
              turn={turn}
              turnIndex={turnIndex}
              onOpenDetail={openDetail}
            />
          ))}
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

function TurnCard({ turn, turnIndex, onOpenDetail }: {
  turn: TrajectoryTurn
  turnIndex: number
  onOpenDetail: (target: TrajectoryDetail) => void
}) {
  const { t } = useTranslation()
  return (
    <div className="turn-card" data-testid="turn-card">
      <button
        type="button"
        className="turn-header turn-header-btn"
        aria-label={`${t('trajectory.turnMeta')} #${turnIndex + 1}`}
        onClick={() => onOpenDetail({ kind: 'turn-meta', turn, turnIndex })}
      >
        <span>{t('trajectory.turn')} #{turnIndex + 1}</span>
        <span className="turn-time">{turn.started_at}</span>
      </button>
      {turn.events.length === 0 ? (
        <div className="turn-events-empty">{t('trajectory.noEvents')}</div>
      ) : (
        <div className="turn-events">
          {turn.events.map(event => (
            <EventRow
              key={event.seq}
              event={event}
              turnIndex={turnIndex}
              onOpenDetail={onOpenDetail}
            />
          ))}
        </div>
      )}
    </div>
  )
}

function EventRow({ event, turnIndex, onOpenDetail }: {
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
        className={`turn-event event-row message-${event.event_type}`}
        data-testid="turn-event"
        onClick={() => onOpenDetail({ kind: 'event', event, turnIndex })}
      >
        <span className="event-badge">{t(`trajectory.${event.event_type}`)}</span>
        <span className="event-content">{preview.text}</span>
        <span className="event-more">{t('trajectory.viewDetails')}</span>
      </button>
    )
  }

  const isError = event.event_type === 'tool_result' && payload.is_error === true
  const summary = event.event_type === 'context'
    ? t('trajectory.contextCount').replace('{n}', String(Array.isArray(payload.items) ? payload.items.length : 0))
    : event.event_type === 'tool_call'
      ? String(payload.tool ?? '')
      : collapseMiddle(String(payload.content ?? ''), 120, 60, 40).text || t('trajectory.noEvents')

  return (
    <button
      type="button"
      className={`turn-event event-row event-tech${isError ? ' event-error' : ''}`}
      data-testid="turn-event"
      onClick={() => onOpenDetail({ kind: 'event', event, turnIndex })}
    >
      <span className="event-badge">{eventLabel(t, event)}</span>
      <span className="event-summary">{summary}</span>
      <span className="event-more">{t('trajectory.viewDetails')}</span>
    </button>
  )
}
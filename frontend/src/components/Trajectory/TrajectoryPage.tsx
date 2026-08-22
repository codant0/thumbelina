import { useCallback, useEffect, useState } from 'react'
import { ChevronDown, ChevronUp, Loader2, RefreshCw } from 'lucide-react'
import type { Conversation } from '../../types/chat'
import type { TrajectoryPageData, TrajectoryTurn } from '../../types/trajectory'
import { fetchTrajectory } from '../../api/trajectory'
import { useTranslation } from '../../i18n'

const PAGE_SIZE = 20

export function TrajectoryPage({ initialConversationId }: { initialConversationId?: string }) {
  const { t } = useTranslation()
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [selectedId, setSelectedId] = useState<string | undefined>(initialConversationId)
  const [data, setData] = useState<TrajectoryPageData | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [notFound, setNotFound] = useState(false)
  const [expanded, setExpanded] = useState<Record<string, boolean>>({})

  useEffect(() => {
    fetch('/api/v1/conversations')
      .then(res => (res.ok ? res.json() : []))
      .then(list => setConversations(Array.isArray(list) ? list : []))
      .catch(() => setConversations([]))
  }, [])

  const load = useCallback(async (conversationId: string, page: number, append: boolean) => {
    setLoading(true)
    setError('')
    setNotFound(false)
    try {
      const pageData = await fetchTrajectory(conversationId, page, PAGE_SIZE)
      setData(prev => {
        if (append && prev && prev.conversation_id === conversationId) {
          return { ...pageData, turns: [...prev.turns, ...pageData.turns] }
        }
        return pageData
      })
    } catch (err) {
      // §5.2: 会话不存在(404)时清空选择并提示,而不是展示可重试的通用错误。
      if ((err as { status?: number }).status === 404) {
        setSelectedId(undefined)
        setData(null)
        setNotFound(true)
        return
      }
      setError(t('trajectory.loadFailed'))
    } finally {
      setLoading(false)
    }
  }, [t])

  useEffect(() => {
    if (selectedId) {
      void load(selectedId, 1, false)
    } else {
      setData(null)
    }
  }, [selectedId, load])

  const handleSelect = (id: string) => {
    setSelectedId(id)
    setExpanded({})
  }

  const toggle = useCallback((key: string) => {
    setExpanded(prev => ({ ...prev, [key]: !prev[key] }))
  }, [])

  const hasMore = data !== null && data.turns.length < data.total_turns

  return (
    <div className="trajectory-page" data-testid="trajectory-page">
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

      {data?.turns.map((turn, turnIndex) => (
        <TurnCard
          key={turn.turn_id}
          turn={turn}
          index={turnIndex}
          expanded={expanded}
          onToggle={toggle}
        />
      ))}

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
    </div>
  )
}

function TurnCard({ turn, index, expanded, onToggle }: {
  turn: TrajectoryTurn
  index: number
  expanded: Record<string, boolean>
  onToggle: (key: string) => void
}) {
  const { t } = useTranslation()
  return (
    <div className="turn-card" data-testid="turn-card">
      <div className="turn-header">
        <span>{t('trajectory.turn')} #{index + 1}</span>
        <span className="turn-time">{turn.started_at}</span>
        {turn.legacy && <span className="turn-legacy">{t('trajectory.legacyNote')}</span>}
      </div>
      <div className="turn-events">
        {turn.events.map(event => {
          if (event.event_type === 'user') {
            return (
              <div key={event.seq} className="turn-event message-user" data-testid="turn-event">
                <span className="event-badge">{t('trajectory.user')}</span>
                <span className="event-content">{String(event.payload.content ?? '')}</span>
              </div>
            )
          }
          if (event.event_type === 'assistant') {
            return (
              <div key={event.seq} className="turn-event message-assistant" data-testid="turn-event">
                <span className="event-badge">{t('trajectory.assistant')}</span>
                <span className="event-content">{String(event.payload.content ?? '')}</span>
              </div>
            )
          }
          const label = event.event_type === 'context'
            ? t('trajectory.context')
            : event.event_type === 'tool_call'
              ? `${t('trajectory.toolCall')}: ${String((event.payload as Record<string, unknown>).tool ?? '')}`
              : t('trajectory.toolResult')
          const key = `${turn.turn_id}-${event.seq}`
          const isOpen = !!expanded[key]
          const isError = event.event_type === 'tool_result' && (event.payload as Record<string, unknown>).is_error === true
          const content = String((event.payload as Record<string, unknown>).content ?? '')
          return (
            <div key={event.seq} className={`turn-event event-tech${isError ? ' event-error' : ''}`} data-testid="turn-event">
              <button
                type="button"
                className="event-toggle"
                data-testid="event-toggle"
                onClick={() => onToggle(key)}
              >
                {isOpen ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                {label}
              </button>
              {isOpen && (
                <>
                  {content !== '' && <span className="event-content">{content}</span>}
                  <pre className="event-detail">{JSON.stringify(event.payload, null, 2)}</pre>
                </>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

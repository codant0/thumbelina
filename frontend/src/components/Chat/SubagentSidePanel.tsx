import { useMemo, useState } from 'react'
import {
  AlertCircle,
  Ban,
  Bot,
  CalendarClock,
  CheckCircle2,
  Clock,
  Copy,
  Loader2,
  MessageSquare,
  XCircle,
  X,
} from 'lucide-react'
import { MarkdownContent } from './MarkdownContent'
import { useTranslation } from '../../i18n'
import type { SubagentEventPayload, SubagentStatus } from '../../types/chat'
import { useCopy } from '../../hooks/useCopy'

interface SubagentSidePanelProps {
  /** 被选中的 subagent 事件,提供 result / error / 时间戳等字段。 */
  event: SubagentEventPayload
  /** 点击右上角 X 或外部遮罩时调用,关闭右侧面板。 */
  onClose: () => void
}

interface StatusVisual {
  Icon: typeof CheckCircle2
  heroClass: string
  badgeIcon: typeof CheckCircle2
}

const STATUS_VISUAL: Record<SubagentStatus, StatusVisual> = {
  pending: { Icon: Clock, heroClass: 'subagent-hero--pending', badgeIcon: Clock },
  running: { Icon: Loader2, heroClass: 'subagent-hero--running', badgeIcon: Loader2 },
  completed: { Icon: CheckCircle2, heroClass: 'subagent-hero--completed', badgeIcon: CheckCircle2 },
  failed: { Icon: XCircle, heroClass: 'subagent-hero--failed', badgeIcon: AlertCircle },
  cancelled: { Icon: Ban, heroClass: 'subagent-hero--cancelled', badgeIcon: Ban },
}

function formatTime(iso?: string | null): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  return d.toLocaleString()
}

function formatDuration(startedAt?: string | null, finishedAt?: string | null): string {
  if (!startedAt) return '—'
  const start = new Date(startedAt).getTime()
  const end = finishedAt ? new Date(finishedAt).getTime() : Date.now()
  if (Number.isNaN(start) || Number.isNaN(end)) return '—'
  const delta = Math.max(0, end - start)
  if (delta < 1000) return `${delta}ms`
  const sec = delta / 1000
  if (sec < 60) return `${sec.toFixed(1)}s`
  const m = Math.floor(sec / 60)
  const s = Math.round(sec % 60)
  return `${m}m ${s}s`
}

/** 右侧停靠面板:展示单个 subagent 的完整详情(任务 / 元信息 / 错误 / Markdown 结果)。
 *
 * 不支持拖动 / 多窗口 / 最小化 —— 点击右上角 X 或外部区域即可关闭。
 */
export function SubagentSidePanel({ event, onClose }: SubagentSidePanelProps) {
  const { t } = useTranslation()
  const { copied, copy } = useCopy()
  const [copiedField, setCopiedField] = useState<string | null>(null)

  const visual = STATUS_VISUAL[event.status] ?? STATUS_VISUAL.pending
  const HeroIcon = visual.Icon
  const BadgeIcon = visual.badgeIcon

  const body = useMemo(() => {
    if (event.result) return event.result
    if (event.status === 'failed') {
      return `\`\`\`\n${event.error ?? t('subagent.noResult')}\n\`\`\``
    }
    if (event.status === 'cancelled') return `*${t('subagent.cancelledHint')}*`
    if (event.status === 'running' || event.status === 'pending') {
      return `*${t('subagent.runningHint')}*`
    }
    return `*${t('subagent.noResult')}*`
  }, [event.result, event.error, event.status, t])

  const copyField = async (key: string, text: string) => {
    await copy(text)
    setCopiedField(key)
    window.setTimeout(() => {
      setCopiedField(prev => (prev === key ? null : prev))
    }, 1500)
  }

  return (
    <aside
      className="subagent-side-panel"
      data-testid="subagent-side-panel"
      data-status={event.status}
      aria-label={t('subagent.heroEyebrow')}
    >
      <header className="subagent-side-panel__header">
        <span className={`subagent-badge subagent-badge--${event.status}`} data-testid="subagent-detail-status">
          <BadgeIcon size={12} />
          {t(`subagent.status.${event.status}`)}
        </span>
        <button
          type="button"
          className={`subagent-side-panel__btn${copied ? ' is-done' : ''}`}
          onClick={() => void copyField('result', body)}
          aria-label={t('chat.copy')}
          title={t('chat.copy')}
          data-testid="subagent-copy-result"
        >
          {copiedField === 'result' ? <CheckCircle2 size={14} /> : <Copy size={14} />}
        </button>
        <button
          type="button"
          className="subagent-side-panel__btn subagent-side-panel__close"
          onClick={onClose}
          aria-label={t('common.close')}
          title={t('common.close')}
          data-testid="subagent-side-panel-close"
        >
          <X size={14} />
        </button>
      </header>

      <div className="subagent-side-panel__body">
        <div className={`subagent-hero ${visual.heroClass}`} data-testid="subagent-hero">
          <div className="subagent-hero__icon">
            <HeroIcon size={20} />
          </div>
          <div className="subagent-hero__body">
            <div className="subagent-hero__eyebrow">{t('subagent.heroEyebrow')}</div>
            <div className="subagent-hero__title">{event.task}</div>
            <div className="subagent-hero__meta">
              <span><Bot size={12} />{event.id.slice(0, 8)}</span>
              <span><MessageSquare size={12} />{t(`subagent.status.${event.status}`)}</span>
            </div>
          </div>
        </div>

        <div className="subagent-meta-grid" data-testid="subagent-meta-grid">
          <div className="subagent-meta-card">
            <div className="subagent-meta-card__icon"><CalendarClock size={14} /></div>
            <div className="subagent-meta-card__body">
              <div className="subagent-meta-card__label">{t('subagent.startedAt')}</div>
              <div className="subagent-meta-card__value">{formatTime(event.started_at)}</div>
            </div>
          </div>
          <div className="subagent-meta-card">
            <div className="subagent-meta-card__icon"><CalendarClock size={14} /></div>
            <div className="subagent-meta-card__body">
              <div className="subagent-meta-card__label">{t('subagent.finishedAt')}</div>
              <div className="subagent-meta-card__value">{formatTime(event.finished_at)}</div>
            </div>
          </div>
          <div className="subagent-meta-card">
            <div className="subagent-meta-card__icon"><Clock size={14} /></div>
            <div className="subagent-meta-card__body">
              <div className="subagent-meta-card__label">{t('subagent.duration')}</div>
              <div className="subagent-meta-card__value">{formatDuration(event.started_at, event.finished_at)}</div>
            </div>
          </div>
          <div className="subagent-meta-card">
            <div className="subagent-meta-card__icon"><Bot size={14} /></div>
            <div className="subagent-meta-card__body">
              <div className="subagent-meta-card__label">{t('subagent.id')}</div>
              <div className="subagent-meta-card__value subagent-meta-card__value--mono">{event.id.slice(0, 8)}</div>
            </div>
          </div>
        </div>

        {event.error && (
          <div className="subagent-error-block" data-testid="subagent-error-block">
            <div className="subagent-error-block__header">
              <AlertCircle size={14} />
              <span>{t('subagent.error')}</span>
            </div>
            <pre className="subagent-error-block__body">{event.error}</pre>
          </div>
        )}

        <div className="subagent-result">
          <div className="subagent-result__toolbar">
            <span className="subagent-result__label">{t('subagent.result')}</span>
          </div>
          <div className="subagent-result__body" data-testid="subagent-detail-body">
            <MarkdownContent content={body} />
          </div>
        </div>
      </div>
    </aside>
  )
}
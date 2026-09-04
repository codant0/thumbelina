import { memo, useEffect, useMemo, useState } from 'react'
import { Bot } from 'lucide-react'
import type { SubagentEventPayload } from '../../types/chat'
import { useTranslation } from '../../i18n'

interface SubagentCardProps {
  /** Subagent 生命周期事件;按 id 合并后的最新状态。 */
  event: SubagentEventPayload
  /** 由 ChatWindow 提供:点击整张卡片时触发,在右侧展开详情面板。 */
  onViewDetail?: (event: SubagentEventPayload) => void
}

const STATUS_BADGE_CLASS: Record<string, string> = {
  pending: 'badge badge-neutral',
  running: 'badge badge-accent',
  completed: 'badge badge-success',
  failed: 'badge badge-danger',
  cancelled: 'badge badge-neutral',
}

/** 从 ISO 时间戳计算耗时(如 "4.2s" / "1m 12s");缺失则返回空串。 */
function formatDuration(startedAt?: string | null, finishedAt?: string | null): string {
  if (!startedAt) return ''
  const start = new Date(startedAt).getTime()
  const end = finishedAt ? new Date(finishedAt).getTime() : Date.now()
  if (Number.isNaN(start) || Number.isNaN(end)) return ''
  const delta = Math.max(0, end - start)
  if (delta < 1000) return `${delta}ms`
  const sec = delta / 1000
  if (sec < 60) return `${sec.toFixed(1)}s`
  const m = Math.floor(sec / 60)
  const s = Math.round(sec % 60)
  return `${m}m ${s}s`
}

/** 截断任务文本,避免超长任务撑爆卡片头部。 */
function truncate(text: string, max: number): string {
  if (text.length <= max) return text
  return text.slice(0, max - 1) + '…'
}

/** 内联展示一个 Subagent 的卡片:整体可点击,触发右侧详情面板。
 *
 * 没有展开/收起按钮,也没有「查看对话详情」按钮 —— 详情在右侧浮窗展示,
 * 点击卡片外区域自动关闭。运行时每秒重渲染一次让「已耗时」保持鲜活。
 */
function SubagentCardInner({ event, onViewDetail }: SubagentCardProps) {
  const { t } = useTranslation()
  const duration = useMemo(
    () => formatDuration(event.started_at, event.finished_at),
    [event.started_at, event.finished_at],
  )

  // 运行时:每 1s 刷新一次"已耗时"标签,让卡片头部看起来是活的。
  // 终态后无意义,自动停止。
  const [, setTick] = useState(0)
  useEffect(() => {
    if (event.status !== 'running' && event.status !== 'pending') return
    const id = setInterval(() => setTick(n => n + 1), 1000)
    return () => clearInterval(id)
  }, [event.status])

  const statusClass = STATUS_BADGE_CLASS[event.status] ?? 'badge badge-neutral'
  const statusLabelKey = `subagent.status.${event.status}`
  const statusLabel = t(statusLabelKey) || event.status
  const taskShort = truncate(event.task, 40)

  return (
    <button
      type="button"
      className="subagent-card"
      data-testid="subagent-card"
      data-status={event.status}
      onClick={onViewDetail ? () => onViewDetail(event) : undefined}
      disabled={!onViewDetail}
      aria-label={event.task}
    >
      <span className="subagent-card__summary">
        <span className="subagent-card__name"><Bot size={13} /><span>{taskShort}</span></span>
        <span className="subagent-card__meta">
          <span className={statusClass} data-testid="subagent-status">{statusLabel}</span>
          {duration && <span className="subagent-card__duration">{duration}</span>}
        </span>
      </span>
    </button>
  )
}

export const SubagentCard = memo(SubagentCardInner)
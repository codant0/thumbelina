import { useMemo } from 'react'
import { Zap } from 'lucide-react'
import { fetchCacheStats } from '../../api/trajectory'
import { useTranslation } from '../../i18n'
import type { StatusBarItem } from './types'
import { StatusBar } from './StatusBar'
import { useStatusBarConfig } from './useStatusBarConfig'

function hitOf(d: Record<string, unknown>): number {
  return typeof d.hit_tokens === 'number' ? d.hit_tokens : 0
}

function missOf(d: Record<string, unknown>): number {
  return typeof d.miss_tokens === 'number' ? d.miss_tokens : 0
}

function rateOf(d: Record<string, unknown>): number | null {
  const total = hitOf(d) + missOf(d)
  if (total <= 0) return null
  return hitOf(d) / total
}

/**
 * KV 缓存命中率栏目：展示当前会话最近 100 轮 LLM 请求的缓存命中率。
 *
 * - 数据来自只读端点 /api/v1/trajectory/cache-stats（按会话聚合 llm_usage 事件），
 *   只读展示，不触发 LLM 调用。
 * - 受「状态栏栏目开关」控制：关闭时不渲染（且不发起请求）。
 */
export function CacheHitRateItem({ conversationId }: { conversationId: string }) {
  const { config } = useStatusBarConfig()
  if (!config.cacheHit) return null
  return <CacheHitRateItemInner conversationId={conversationId} />
}

function CacheHitRateItemInner({ conversationId }: { conversationId: string }) {
  const { t } = useTranslation()

  const item = useMemo<StatusBarItem>(() => ({
    key: 'cacheHit',
    icon: <Zap size={13} aria-hidden="true" />,
    getData: () => fetchCacheStats(conversationId),
    render: d => {
      const rate = rateOf(d)
      return rate === null ? '—' : `${Math.round(rate * 100)}%`
    },
    status: d => {
      const rate = rateOf(d)
      if (rate === null) return 'idle'
      if (rate < 0.1) return 'error'
      if (rate < 0.3) return 'warning'
      return 'ok'
    },
    title: d => {
      const rate = rateOf(d)
      const turns = typeof d.turns === 'number' ? d.turns : 0
      const pct = rate === null ? 0 : Math.round(rate * 100)
      return t('statusbar.cacheHitTitle')
        .replace('{pct}', String(pct))
        .replace('{hit}', String(hitOf(d)))
        .replace('{total}', String(hitOf(d) + missOf(d)))
        .replace('{turns}', String(turns))
    },
  // 把 conversationId 写入依赖：会话切换时 item 必须重建,否则 useMemo
  // 缓存里的 getData 闭包仍指向旧会话,fetch 永远查不到新会话的统计。
  }), [t, conversationId])

  return <StatusBar items={[item]} />
}
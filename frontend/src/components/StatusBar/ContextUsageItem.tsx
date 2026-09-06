import { useEffect, useMemo, useState } from 'react'
import { Gauge } from 'lucide-react'
import { fetchEndpoints } from '../../api/llmConfig'
import type { Message } from '../../types/chat'
import { estimateTokens, parseContextWindow } from '../../lib/estimateTokens'
import type { StatusBarItem } from './types'
import { StatusBar } from './StatusBar'
import { useStatusBarConfig } from './useStatusBarConfig'

interface ContextUsageItemProps {
  /** 回合落定的消息快照（useSettledMessages）；null = 等待快照（会话刚切换/切进流式会话） */
  settledMessages: Message[] | null
  /** 快照版本号：变化时重新估算（回合结束/会话切换/清空各触发一次） */
  settledVersion: number
  /** 会话绑定的端点 id（缺省回落默认/激活端点）；用于解析 context 窗口上限 */
  endpointId?: string | null
}

interface ContextData {
  usedTokens: number | null
  limit: number | null
}

function countTokens(messages: Message[]): number {
  return messages.reduce((acc, m) => acc + estimateTokens(m.content ?? ''), 0)
}

function usageOf(data: ContextData): number | null {
  if (data.usedTokens === null || !data.limit) return null
  return (data.usedTokens / data.limit) * 100
}

/**
 * 上下文占用栏目：估算当前会话 token 占用并展示为百分比。
 *
 * - 只做展示，不影响对话：不注入 prompt、不改写发往后端的任何负载，
 *   仅由「回合落定」的消息快照（useSettledMessages）+ 本地估算函数驱动 UI；
 *   流式进行中冻结，收到新响应后才重算一次，不随 chunk 闪烁。
 * - 数据获取为纯本地函数 / 只读端点（`fetchEndpoints`），不触发 LLM 调用。
 *
 * 受「状态栏栏目开关」控制：关闭时不渲染（且不发起端点请求）。
 */
export function ContextUsageItem(props: ContextUsageItemProps) {
  const { config } = useStatusBarConfig()
  if (!config.context) return null
  return <ContextUsageItemInner {...props} />
}

function ContextUsageItemInner({ settledMessages, settledVersion, endpointId }: ContextUsageItemProps) {
  // 解析 context 窗口上限：按会话 endpoint 匹配，缺省回落默认/激活端点
  const [contextWindow, setContextWindow] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    fetchEndpoints()
      .then(list => {
        if (cancelled) return
        const eps = Array.isArray(list) ? list : []
        const match =
          (endpointId && eps.find(ep => ep.id === endpointId)) ||
          eps.find(ep => ep.is_default) ||
          eps[0]
        const activeModel = match?.models?.find(m => m.name === match.active_model)
        const firstModel = match?.models?.[0]
        setContextWindow(activeModel?.context_window ?? firstModel?.context_window ?? null)
      })
      .catch(() => {
        if (!cancelled) setContextWindow(null)
      })
    return () => {
      cancelled = true
    }
  }, [endpointId])

  const item = useMemo<StatusBarItem>(() => {
    const limit = parseContextWindow(contextWindow)
    return {
      key: 'context',
      icon: <Gauge size={13} aria-hidden="true" />,
      // contextWindow 纳入 refreshKey：切换会话后端点异步解析出新窗口上限时
      // 也重算一次，避免停留在按旧上限计算的百分比上。
      refreshKey: `${settledVersion}|${contextWindow ?? ''}`,
      getData: () => ({
        usedTokens: settledMessages === null ? null : countTokens(settledMessages),
        limit,
      }),
      render: d => {
        const pctVal = usageOf(d as ContextData)
        return pctVal === null ? '—' : `${Math.round(pctVal)}%`
      },
      status: d => {
        const pctVal = usageOf(d as ContextData)
        if (pctVal === null) return 'idle'
        if (pctVal > 85) return 'error'
        if (pctVal > 60) return 'warning'
        return 'ok'
      },
    }
  }, [settledMessages, settledVersion, contextWindow])

  return <StatusBar items={[item]} />
}

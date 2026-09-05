import type { ToolCall, ToolEventPayload } from '../../types/chat'

/**
 * 聊天流实时工具卡的纯状态机(设计 §5.2):useWebSocket 收到 ``tool_event``
 * 帧后,对当轮 assistant 消息的 ``toolCalls`` 列表按 ``call_id`` 做 upsert。
 * 全部为纯函数,返回新数组、不原地修改,便于 vitest 直测。
 */

/**
 * 按 ``call_id`` 合并一条工具事件:
 * - start:已在列则忽略(重复帧防御);否则追加一张 running 卡。
 * - end:命中则写入结果/耗时/状态;孤立 end(未见过 start)防御性建卡。
 */
export function upsertToolCall(toolCalls: ToolCall[], ev: ToolEventPayload): ToolCall[] {
  const idx = toolCalls.findIndex((tc) => tc.call_id === ev.call_id)
  if (ev.phase === 'start') {
    if (idx >= 0) return toolCalls
    return [
      ...toolCalls,
      {
        call_id: ev.call_id,
        name: ev.name ?? 'unknown',
        args: ev.args ?? {},
        argsTruncated: ev.args_truncated ?? false,
        status: 'running' as const,
      },
    ]
  }
  const status = ev.is_error ? ('error' as const) : ('ok' as const)
  if (idx < 0) {
    return [
      ...toolCalls,
      {
        call_id: ev.call_id,
        name: 'unknown',
        args: {},
        status,
        result: ev.result_preview,
        resultTruncated: ev.result_truncated,
        durationMs: ev.duration_ms,
      },
    ]
  }
  const next = [...toolCalls]
  next[idx] = {
    ...next[idx],
    status,
    result: ev.result_preview,
    resultTruncated: ev.result_truncated,
    durationMs: ev.duration_ms,
  }
  return next
}

/** 收尾兜底(设计 §6 Stop 取消):把残留 running 卡标为 interrupted;无 running 时返回原数组。 */
export function markInterrupted(toolCalls: ToolCall[]): ToolCall[] {
  if (!toolCalls.some((tc) => tc.status === 'running')) return toolCalls
  return toolCalls.map((tc) =>
    tc.status === 'running' ? { ...tc, status: 'interrupted' as const } : tc
  )
}

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

/** 内容锚点(设计 §5.3 修订:工具芯片按发生顺序穿插在文本流中):
 *  tool_start 事件到达时已接收的内容字符数,即该工具在内容流中的切分位置。 */
export interface ToolAnchor {
  callId: string
  offset: number
}

/** 内容流中的一段:文本(走 Markdown 渲染)或工具芯片(按 call_id 引用 toolCalls)。 */
export interface ContentSegment {
  type: 'text' | 'tool'
  text?: string
  callId?: string
}

/** 按 anchors(offset 升序、同 offset 保持到达顺序)把 content 切分为穿插段。
 *
 * offset 超出内容长度时钳制到末尾(打字机未追平时芯片跟随在已显示文本之后,
 * 追平后自然落位);不产生空文本段;无锚点时退化为单一文本段(历史消息布局)。
 */
export function splitContentByAnchors(content: string, anchors: ToolAnchor[]): ContentSegment[] {
  if (anchors.length === 0) return content ? [{ type: 'text', text: content }] : []
  const sorted = [...anchors].sort((a, b) => a.offset - b.offset)
  const segments: ContentSegment[] = []
  let cursor = 0
  for (const { callId, offset } of sorted) {
    const at = Math.min(offset, content.length)
    if (at > cursor) segments.push({ type: 'text', text: content.slice(cursor, at) })
    segments.push({ type: 'tool', callId })
    cursor = Math.max(cursor, at)
  }
  if (cursor < content.length) segments.push({ type: 'text', text: content.slice(cursor) })
  return segments
}


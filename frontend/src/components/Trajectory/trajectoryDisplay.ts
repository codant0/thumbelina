import type { TrajectoryEvent } from '../../types/trajectory'

export const PREVIEW_LIMIT = 600
export const PREVIEW_HEAD = 200
export const PREVIEW_TAIL = 200

export function collapseMiddle(
  text: string,
  limit = PREVIEW_LIMIT,
  head = PREVIEW_HEAD,
  tail = PREVIEW_TAIL,
): { text: string; truncated: boolean } {
  if (text.length <= limit) return { text, truncated: false }
  return {
    text: `${text.slice(0, head)}…（共 ${text.length} 字）…${text.slice(-tail)}`,
    truncated: true,
  }
}

export function eventLabel(t: (key: string) => string, event: TrajectoryEvent): string {
  if (event.event_type === 'user' || event.event_type === 'assistant') {
    return t(`trajectory.${event.event_type}`)
  }
  if (event.event_type === 'tool_call') {
    return `${t('trajectory.toolCall')}: ${String((event.payload as Record<string, unknown>).tool ?? '')}`
  }
  if (event.event_type === 'tool_result') {
    return t('trajectory.toolResult')
  }
  return t('trajectory.context')
}

/** 同轮次内按 call_id 组合的调用与结果；results 为空表示无匹配结果。 */
export interface ToolCallGroup {
  call: TrajectoryEvent
  results: TrajectoryEvent[]
}

function payloadOf(event: TrajectoryEvent): Record<string, unknown> {
  return event.payload as Record<string, unknown>
}

/** 把 tool_call 与同 call_id 的 tool_result 组合为一块，其余事件保持原顺序透出。 */
export function groupToolEvents(events: TrajectoryEvent[]): (TrajectoryEvent | ToolCallGroup)[] {
  const blocks: (TrajectoryEvent | ToolCallGroup)[] = []
  const consumed = new Set<number>()
  for (const event of events) {
    if (event.event_type === 'tool_call') {
      const callId = payloadOf(event).call_id
      const results = events.filter(e => {
        if (e.event_type !== 'tool_result' || consumed.has(e.seq)) return false
        const resultId = payloadOf(e).call_id
        return typeof callId === 'string' && callId !== '' && resultId === callId
      })
      results.forEach(e => consumed.add(e.seq))
      blocks.push({ call: event, results })
    } else if (event.event_type === 'tool_result' && consumed.has(event.seq)) {
      // 已被前序调用认领，不再单独展示
    } else {
      blocks.push(event)
    }
  }
  return blocks
}
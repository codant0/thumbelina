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
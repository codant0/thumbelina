import type { TrajectoryEvent } from '../../types/trajectory'

export const PREVIEW_LIMIT = 600
export const PREVIEW_HEAD = 200
export const PREVIEW_TAIL = 200

/** 闸门裁决（spec §3.2/§5.2）→ 前端展示语义。allowed 不展示徽标。 */
export type VerdictKind = 'allowed' | 'denied' | 'confirmed' | 'auto_allowed'

/** verdict 字符串 → i18n key / 徽标配色类 / 标题用本地化文本。 */
export interface VerdictInfo {
  kind: VerdictKind | null
  labelKey: string
  badgeClass: string
}

/** reason（stable rule key，如 ``rule.sudo``）→ 与 PermissionRequestCard 同一映射。 */
function reasonToI18nKey(reason: string): string {
  return `permission.rule.${reason.replace(/\./g, '_')}`
}

/** 从 tool_call payload 提取 verdict + reason 渲染信息；非工具事件或缺字段返回 null kind。 */
export function verdictInfo(payload: Record<string, unknown>): VerdictInfo {
  const v = payload.verdict
  if (v === 'denied') {
    return { kind: 'denied', labelKey: 'toolCalls.verdict.denied', badgeClass: 'verdict-badge--denied' }
  }
  if (v === 'confirmed') {
    return { kind: 'confirmed', labelKey: 'toolCalls.verdict.confirmed', badgeClass: 'verdict-badge--confirmed' }
  }
  if (v === 'auto_allowed') {
    return { kind: 'auto_allowed', labelKey: 'toolCalls.verdict.autoAllowed', badgeClass: 'verdict-badge--auto' }
  }
  if (v === 'allowed') {
    return { kind: 'allowed', labelKey: 'toolCalls.verdict.allowed', badgeClass: 'verdict-badge--allowed' }
  }
  return { kind: null, labelKey: '', badgeClass: '' }
}

/** reason → i18n key（与 PermissionRequestCard 同形）。reason 为空时返回 null。 */
export function reasonLabelKey(reason: string | undefined | null): string | null {
  if (typeof reason !== 'string' || reason === '') return null
  return reasonToI18nKey(reason)
}

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
  if (event.event_type === 'llm_usage') {
    return t('trajectory.llmUsage')
  }
  return t('trajectory.context')
}

/** llm_usage 事件摘要：优先展示缓存命中率，否则退回输入/输出 token 数。 */
export function usageSummary(t: (key: string) => string, payload: Record<string, unknown>): string {
  const hit = payload.cache_hit_tokens
  const miss = payload.cache_miss_tokens
  const prompt = payload.prompt_tokens
  const completion = payload.completion_tokens
  if (typeof hit === 'number' && (typeof miss === 'number' || typeof prompt === 'number')) {
    const total = typeof miss === 'number' ? miss + hit : typeof prompt === 'number' ? prompt : hit
    const pct = total > 0 ? Math.round((hit / total) * 100) : 0
    return t('trajectory.usageCache')
      .replace('{hit}', String(hit))
      .replace('{total}', String(total))
      .replace('{pct}', String(pct))
  }
  const parts: string[] = []
  if (typeof prompt === 'number') parts.push(t('trajectory.usageInput').replace('{n}', String(prompt)))
  if (typeof completion === 'number') parts.push(t('trajectory.usageCompletion').replace('{n}', String(completion)))
  return parts.join(' · ') || t('trajectory.noEvents')
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
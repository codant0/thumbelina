import { describe, it, expect } from 'vitest'
import { markInterrupted, upsertToolCall } from './toolCallEvents'
import type { ToolEventPayload } from '../../types/chat'

const start = (call_id: string, name = 'web_search'): ToolEventPayload => ({
  phase: 'start',
  call_id,
  name,
  args: { query: 'q' },
})
const end = (call_id: string, is_error = false): ToolEventPayload => ({
  phase: 'end',
  call_id,
  duration_ms: 1800,
  is_error,
  result_preview: 'preview...',
  result_truncated: true,
})

describe('upsertToolCall', () => {
  it('start 创建 running 卡', () => {
    const list = upsertToolCall([], start('c1'))
    expect(list).toHaveLength(1)
    expect(list[0]).toMatchObject({ call_id: 'c1', name: 'web_search', status: 'running' })
  })
  it('end 把 running 卡改为 ok 并带结果与耗时', () => {
    let list = upsertToolCall([], start('c1'))
    list = upsertToolCall(list, end('c1'))
    expect(list[0]).toMatchObject({ status: 'ok', durationMs: 1800, resultTruncated: true })
  })
  it('end is_error 时状态为 error', () => {
    let list = upsertToolCall([], start('c1'))
    list = upsertToolCall(list, end('c1', true))
    expect(list[0].status).toBe('error')
  })
  it('重复 start 忽略；孤立 end 防御性建卡', () => {
    let list = upsertToolCall([], start('c1'))
    list = upsertToolCall(list, start('c1'))
    expect(list).toHaveLength(1)
    list = upsertToolCall(list, end('c9'))
    expect(list).toHaveLength(2)
    expect(list[1].status).toBe('ok')
  })
  it('多工具并发各自成卡', () => {
    let list = upsertToolCall([], start('a', 't1'))
    list = upsertToolCall(list, start('b', 't2'))
    list = upsertToolCall(list, end('a'))
    expect(list.map((tc) => tc.status)).toEqual(['ok', 'running'])
  })
  it('start 透传 args_truncated', () => {
    const list = upsertToolCall([], {
      phase: 'start',
      call_id: 'c1',
      name: 'big_tool',
      args: { _truncated_json: '{"a": 1' },
      args_truncated: true,
    })
    expect(list[0]).toMatchObject({ argsTruncated: true, args: { _truncated_json: '{"a": 1' } })
  })
})

describe('markInterrupted', () => {
  it('把 running 卡标为 interrupted，其余不动', () => {
    let list = upsertToolCall([], start('c1'))
    list = upsertToolCall(list, end('c1'))
    list = upsertToolCall(list, start('c2'))
    const marked = markInterrupted(list)
    expect(marked.map((tc) => tc.status)).toEqual(['ok', 'interrupted'])
  })
  it('无 running 时返回原数组', () => {
    const list = upsertToolCall(upsertToolCall([], start('c1')), end('c1'))
    expect(markInterrupted(list)).toBe(list)
  })
})

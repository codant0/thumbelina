import { describe, it, expect } from 'vitest'
import { formatToolArgs, markInterrupted, splitContentByAnchors, summarizeToolCalls, upsertToolCall } from './toolCallEvents'
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

describe('splitContentByAnchors', () => {
  const anchor = (callId: string, offset: number) => ({ callId, offset })

  it('无锚点时返回单一文本段', () => {
    expect(splitContentByAnchors('hello world', [])).toEqual([{ type: 'text', text: 'hello world' }])
  })

  it('按 offset 把内容切分为 文本-工具-文本 的有序段', () => {
    const segments = splitContentByAnchors('before-after', [anchor('c1', 7)])
    expect(segments).toEqual([
      { type: 'text', text: 'before-' },
      { type: 'tool', callId: 'c1' },
      { type: 'text', text: 'after' },
    ])
  })

  it('offset 超出内容长度时钳制到末尾', () => {
    const segments = splitContentByAnchors('abc', [anchor('c1', 99)])
    expect(segments).toEqual([{ type: 'text', text: 'abc' }, { type: 'tool', callId: 'c1' }])
  })

  it('offset 0 时芯片位于全部文本之前', () => {
    const segments = splitContentByAnchors('text', [anchor('c1', 0)])
    expect(segments).toEqual([{ type: 'tool', callId: 'c1' }, { type: 'text', text: 'text' }])
  })

  it('同 offset 的锚点保持到达顺序(稳定排序)', () => {
    const segments = splitContentByAnchors('AB', [anchor('c2', 1), anchor('c1', 1)])
    expect(segments).toEqual([
      { type: 'text', text: 'A' },
      { type: 'tool', callId: 'c2' },
      { type: 'tool', callId: 'c1' },
      { type: 'text', text: 'B' },
    ])
  })

  it('多锚点按 offset 升序穿插且不产生空文本段', () => {
    const segments = splitContentByAnchors('abc', [anchor('c1', 3), anchor('c2', 1)])
    expect(segments).toEqual([
      { type: 'text', text: 'a' },
      { type: 'tool', callId: 'c2' },
      { type: 'text', text: 'bc' },
      { type: 'tool', callId: 'c1' },
    ])
  })

  it('空内容只有锚点时不产生文本段', () => {
    expect(splitContentByAnchors('', [anchor('c1', 0)])).toEqual([{ type: 'tool', callId: 'c1' }])
  })
})

describe('summarizeToolCalls', () => {
  it('统计总数与各状态计数', () => {
    const s = summarizeToolCalls([
      { call_id: 'a', name: 'x', args: {}, status: 'ok', durationMs: 100 },
      { call_id: 'b', name: 'y', args: {}, status: 'running' },
      { call_id: 'c', name: 'z', args: {}, status: 'error', durationMs: 50 },
    ])
    expect(s).toEqual({ total: 3, ok: 1, running: 1, error: 1, interrupted: 0 })
  })
  it('空列表归零', () => {
    expect(summarizeToolCalls([])).toEqual({ total: 0, ok: 0, running: 0, error: 0, interrupted: 0 })
  })
})

describe('formatToolArgs', () => {
  it('普通参数 pretty-print', () => {
    expect(formatToolArgs({ query: 'q' })).toBe('{\n  "query": "q"\n}')
  })
  it('截断参数原样输出 _truncated_json', () => {
    expect(formatToolArgs({ _truncated_json: '{"a": 1' }, true)).toBe('{"a": 1')
  })
})

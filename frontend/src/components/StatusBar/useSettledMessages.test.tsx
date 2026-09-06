import { describe, it, expect } from 'vitest'
import { renderHook } from '@testing-library/react'
import { useSettledMessages } from './useSettledMessages'
import type { Message } from '../../types/chat'

function msg(id: string): Message {
  return { id, role: 'user', content: `m-${id}`, timestamp: new Date().toISOString() }
}

interface HookProps {
  messages: Message[]
  turnActive: boolean
  conversationId: string
}

function renderSettledHook(initial: HookProps) {
  return renderHook((props: HookProps) => useSettledMessages(props.messages, props.turnActive, props.conversationId), {
    initialProps: initial,
  })
}

describe('useSettledMessages', () => {
  it('初始挂载即返回当前消息快照（版本号 0，无多余推进）', () => {
    const m1 = [msg('1')]
    const { result } = renderSettledHook({ messages: m1, turnActive: false, conversationId: 'c1' })
    expect(result.current.messages).toBe(m1)
    expect(result.current.version).toBe(0)
  })

  it('回合进行中（turnActive=true）messages 变化被冻结', () => {
    const m1 = [msg('1')]
    const m2 = [msg('1'), msg('2')]
    const { result, rerender } = renderSettledHook({ messages: m1, turnActive: false, conversationId: 'c1' })
    const frozen = result.current

    // 流式 chunk 不断改写 messages,但快照与版本号都保持不动(零重取数)
    rerender({ messages: m2, turnActive: true, conversationId: 'c1' })
    rerender({ messages: [msg('1'), msg('2'), msg('3')], turnActive: true, conversationId: 'c1' })
    expect(result.current.messages).toBe(frozen.messages)
    expect(result.current.version).toBe(frozen.version)
  })

  it('回合结束（turnActive 回落）且 messages 落定 → 重新快照', () => {
    const m1 = [msg('1')]
    const final = [msg('1'), msg('2')]
    const { result, rerender } = renderSettledHook({ messages: m1, turnActive: false, conversationId: 'c1' })
    const before = result.current.version

    rerender({ messages: [msg('1'), msg('2')], turnActive: true, conversationId: 'c1' })
    rerender({ messages: final, turnActive: false, conversationId: 'c1' })
    expect(result.current.messages).toBe(final)
    expect(result.current.version).toBe(before + 1)
  })

  it('回合结束即使消息未变也推进版本号（触发缓存栏刷新）', () => {
    const m1 = [msg('1')]
    const { result, rerender } = renderSettledHook({ messages: m1, turnActive: false, conversationId: 'c1' })
    const before = result.current.version

    // 空回复的回合:turnActive 起、落,消息始终是同一数组
    rerender({ messages: m1, turnActive: true, conversationId: 'c1' })
    rerender({ messages: m1, turnActive: false, conversationId: 'c1' })
    expect(result.current.messages).toBe(m1)
    expect(result.current.version).toBe(before + 1)
  })

  it('切换会话时快照置 null，空闲后随 messages 重新落定', () => {
    const m1 = [msg('1')]
    const { result, rerender } = renderSettledHook({ messages: m1, turnActive: false, conversationId: 'c1' })
    const before = result.current.version

    // 切到 c2:此刻的 messages 可能仍属于 c1 → 先置空等待
    rerender({ messages: m1, turnActive: false, conversationId: 'c2' })
    expect(result.current.messages).toBeNull()
    expect(result.current.version).toBe(before + 1)

    // c2 历史加载完成 → 新快照
    const history = [msg('9')]
    rerender({ messages: history, turnActive: false, conversationId: 'c2' })
    expect(result.current.messages).toBe(history)
  })

  it('切进正在流式的会话：保持 null 直到该回合结束', () => {
    const empty: Message[] = []
    const { result, rerender } = renderSettledHook({ messages: empty, turnActive: false, conversationId: 'c1' })

    // 切进 c2 时 c2 正在流式:不显示错误数值,保持占位
    rerender({ messages: empty, turnActive: true, conversationId: 'c2' })
    expect(result.current.messages).toBeNull()

    // 流式 chunk 持续改写 messages,仍冻结
    rerender({ messages: [msg('a')], turnActive: true, conversationId: 'c2' })
    expect(result.current.messages).toBeNull()

    // 回合结束落定 → 给出最终快照
    const final = [msg('a'), msg('b')]
    rerender({ messages: final, turnActive: false, conversationId: 'c2' })
    expect(result.current.messages).toBe(final)
  })
})

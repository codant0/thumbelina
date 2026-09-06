import { useState } from 'react'
import type { Message } from '../../types/chat'

export interface SettledContext {
  /** 回合落定时的消息快照；null = 等待快照（会话刚切换，或切进正在流式的会话） */
  messages: Message[] | null
  /** 快照版本号：每次重新快照 +1，供状态栏栏目作为 refreshKey 消费 */
  version: number
}

interface SettledState {
  /** 上一渲染的会话 id，用于识别会话切换 */
  prevConv: string | undefined
  /** 上一渲染是否处于回合进行中（回合结束时即使消息未变也要推进版本） */
  wasActive: boolean
  /** 已落定的快照（对外暴露） */
  snapshot: Message[] | null
  /** 快照来源的 messages，用于识别「messages 变了」 */
  source: Message[]
  version: number
}

/**
 * 状态栏回合冻结语义：只在「收到新响应」后刷新。
 *
 * - 回合进行中（turnActive = isStreaming || waitingForReply）冻结上一快照：
 *   流式 chunk / 打字机 tick 只改 messages 不改快照，状态栏零重取数零闪烁。
 * - 回合结束（turnActive 回落）或空闲期消息落定（历史加载、清空、错误消息）
 *   → 重新快照，version+1。
 * - 会话切换 → 快照置 null（栏目显示占位）并 version+1；切换必然伴随
 *   clearMessages/loadHistory 的消息变更，目标会话历史就绪后给出新快照。
 *   切进正在流式的会话时保持 null 直到该回合结束。
 *
 * 采用「渲染期派生状态」模式（React 官方 adjust-state-when-props-change），
 * 避免 effect 内同步 setState 的级联重渲染。
 */
export function useSettledMessages(
  messages: Message[],
  turnActive: boolean,
  conversationId: string | undefined,
): SettledContext {
  const [state, setState] = useState<SettledState>({
    prevConv: conversationId,
    wasActive: turnActive,
    snapshot: messages,
    source: messages,
    version: 0,
  })

  if (state.prevConv !== conversationId) {
    // 会话切换：此刻的 messages 可能仍属于上一会话（子渲染先于父组件的
    // clearMessages effect），不能直接快照 → 置 null 等待目标会话数据落定。
    setState({
      prevConv: conversationId,
      wasActive: turnActive,
      snapshot: null,
      source: messages,
      version: state.version + 1,
    })
  } else if (turnActive && !state.wasActive) {
    // 回合开始：仅记录标记，不推进快照/版本号（回合结束时要据此刷新一次）。
    setState({ ...state, wasActive: true })
  } else if (!turnActive && (state.wasActive || state.source !== messages)) {
    // 回合结束 / 空闲期消息落定：重新快照并推进版本号。
    setState({
      prevConv: conversationId,
      wasActive: false,
      snapshot: messages,
      source: messages,
      version: state.version + 1,
    })
  }

  return { messages: state.snapshot, version: state.version }
}

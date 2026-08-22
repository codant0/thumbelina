import { useEffect, useReducer } from 'react'
import type { StatusBarItem, StatusData, StatusBarState } from './types'
import { StatusBarItemView } from './StatusBarItem'

interface ItemState {
  data?: StatusData
  /** 展示状态（由 status(data) 判定；'error' 也可能表示正常数据但处于警戒态） */
  state: StatusBarState
  /** getData 取数失败（区别于状态警戒）——决定展示占位符 */
  failed?: boolean
}

type Action =
  | { type: 'load'; key: string; data: StatusData; state: StatusBarState }
  | { type: 'error'; key: string }

function reducer(state: Record<string, ItemState>, action: Action): Record<string, ItemState> {
  switch (action.type) {
    case 'load':
      return { ...state, [action.key]: { data: action.data, state: action.state } }
    case 'error':
      return { ...state, [action.key]: { state: 'error', failed: true } }
    default:
      return state
  }
}

interface StatusBarProps {
  /** 已注册的栏目列表（实现 StatusBarItem 协议）。本版仅 context 一项。 */
  items: StatusBarItem[]
}

/**
 * 状态栏容器：遍历注册的栏目，各自取数后统一渲染外壳。
 * 数据获取须为纯函数（只读前端状态 / 只读端点，绝不触发 LLM 调用）。
 * 当 items（或其闭包捕获的实时状态）变化时重新求值，不做整体清空以
 * 避免实时栏目（如随消息流变化的上下文占用）产生闪烁。
 */
export function StatusBar({ items }: StatusBarProps) {
  const [byKey, dispatch] = useReducer(reducer, {})

  useEffect(() => {
    for (const item of items) {
      // 兼容同步与异步 getData，两者抛错都归入 error 降级
      Promise.resolve()
        .then(() => item.getData())
        .then(data => {
          const state = item.status ? item.status(data) : 'ok'
          dispatch({ type: 'load', key: item.key, data, state })
        })
        .catch(() => dispatch({ type: 'error', key: item.key }))
    }
  }, [items])

  return (
    <div className="statusbar" data-testid="statusbar">
      {items.map(item => {
        const st = byKey[item.key]
        // failed 仅在取数失败时置位 → 展示占位符；st.state 仅用于装饰状态点
        const content = st?.failed
          ? '—'
          : (st?.data && item.render(st.data)) ?? '…'
        return (
          <StatusBarItemView
            key={item.key}
            state={st?.state ?? 'idle'}
            label={content}
            title={st?.data && item.title ? item.title(st.data) : undefined}
          />
        )
      })}
    </div>
  )
}

import { useEffect, useRef, useState } from 'react'
import type { StatusBarItem, StatusData, StatusBarState } from './types'
import { StatusBarItemView } from './StatusBarItem'

interface ItemState {
  data?: StatusData
  /** 展示状态（由 status(data) 判定；'error' 也可能表示正常数据但处于警戒态） */
  state: StatusBarState
  /** getData 取数失败（区别于状态警戒）——决定展示占位符 */
  failed?: boolean
}

/**
 * 单栏目取数控制器：只在栏目声明的 resetKey/refreshKey 两个原始值信号变化时取数。
 *
 * item 对象在父组件每次渲染时都可能是新引用（内联 items 数组 / 重建的 useMemo 闭包），
 * 绝不能进 effect 依赖——否则流式对话期间父组件每 chunk 重渲染都会触发
 * 「清空回占位 + 重取数」，状态栏持续闪烁（异步栏目还会形成请求风暴）。
 * 信号变化触发 effect 时，闭包捕获的 item 恰是最近一次渲染的版本，getData 读到的即新值。
 */
function StatusBarItemController({ item }: { item: StatusBarItem }) {
  const [entry, setEntry] = useState<ItemState | null>(null)
  const { resetKey, refreshKey } = item
  // 上一次 resetKey：区分「会话切换/新建」（先清空回占位）与「同会话刷新」（旧值保留到新数据到达）。
  const prevResetRef = useRef(resetKey)

  useEffect(() => {
    if (prevResetRef.current !== resetKey) {
      prevResetRef.current = resetKey
      // resetKey 变化（会话切换/新建）：立刻回到占位符，而不是停留上一会话的数据。
      setEntry(null)
    }
    let cancelled = false
    // 兼容同步与异步 getData，两者抛错都归入 error 降级；
    // cancelled 保证快速连续取数时，上一轮未完成的响应不会覆盖新一轮的数据（竞态防护）。
    Promise.resolve()
      .then(() => item.getData())
      .then(data => {
        if (!cancelled) setEntry({ data, state: item.status ? item.status(data) : 'ok' })
      })
      .catch(() => {
        if (!cancelled) setEntry({ state: 'error', failed: true })
      })
    return () => {
      cancelled = true
    }
    // item 仅为闭包来源；取数时机完全由 resetKey/refreshKey 驱动（见组件注释）。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [resetKey, refreshKey])

  const content = entry?.failed
    ? '—'
    : (entry?.data && item.render(entry.data)) ?? '…'
  return (
    <StatusBarItemView
      icon={item.icon}
      state={entry?.state ?? 'idle'}
      label={content}
      title={entry?.data && item.title ? item.title(entry.data) : undefined}
    />
  )
}

interface StatusBarProps {
  /** 已注册的栏目列表（实现 StatusBarItem 协议） */
  items: StatusBarItem[]
}

/**
 * 状态栏容器：遍历注册的栏目，各自取数后统一渲染外壳。
 * 数据获取须为纯函数（只读前端状态 / 只读端点，绝不触发 LLM 调用）。
 * 重取数只由栏目声明的 resetKey/refreshKey 信号驱动；父组件重渲染导致的
 * items/item 引用变化不触发任何取数——流式对话期间状态栏保持冻结、不闪烁。
 */
export function StatusBar({ items }: StatusBarProps) {
  return (
    <div className="statusbar" data-testid="statusbar">
      {items.map(item => (
        <StatusBarItemController key={item.key} item={item} />
      ))}
    </div>
  )
}

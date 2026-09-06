import type { ReactNode } from 'react'

/** 状态栏栏目的数据源返回值（演进此处即可承载更多字段） */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type StatusData = Record<string, any>

export type StatusBarState = 'idle' | 'ok' | 'warning' | 'error'

/**
 * 状态栏栏目协议（抽象接口）。
 *
 * 新增一个栏目 = 实现一个 StatusBarItem 并注册进 StatusBar 容器即可，
 * 无需改动容器本身。数据获取（getData）必须是纯函数——只读前端已持有的
 * 状态 / 只读本地端点，绝不触发 LLM 调用。
 *
 * 取数时机由两个原始值信号驱动（容器对 item 对象的引用变化免疫，
 * 父组件高频重渲染不会触发重取数/闪烁）：
 * - refreshKey 变化 → 重新取数，旧值保留到新数据到达（同会话回合刷新）；
 * - resetKey 变化   → 先清空回占位符再取数（会话切换/新建语义）。
 */
export interface StatusBarItem {
  /** 唯一标识（用于 i18n 与测试定位） */
  key: string
  /** 数据获取：纯函数，读取前端已有状态或只读端点，不得触发 LLM 调用 */
  getData: () => Promise<StatusData> | StatusData
  /** 取数信号：变化时重新执行 getData（如同会话内回合结束）。缺省只在挂载/resetKey 变化时取数 */
  refreshKey?: string | number
  /** 重置信号：变化时先清空展示回占位符再取数（会话切换/新建）。缺省不清空 */
  resetKey?: string | number
  /** 渲染主体（占用值 / 状态文本等） */
  render: (data: StatusData) => ReactNode
  /** 根据数据判定整体状态（决定外壳状态点颜色） */
  status?: (data: StatusData) => StatusBarState
  /** 悬浮提示 / 无障碍标题（如 "缓存命中率 26%（900/3400 tokens）"） */
  title?: (data: StatusData) => string
  /** 栏目图标（与设置页「状态栏」卡片图标一致） */
  icon?: ReactNode
}

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
 */
export interface StatusBarItem {
  /** 唯一标识（用于 i18n 与测试定位） */
  key: string
  /** 数据获取：纯函数，读取前端已有状态或只读端点，不得触发 LLM 调用 */
  getData: () => Promise<StatusData> | StatusData
  /** 渲染主体（占用值 / 状态文本等） */
  render: (data: StatusData) => ReactNode
  /** 根据数据判定整体状态（决定外壳状态点颜色） */
  status?: (data: StatusData) => StatusBarState
  /** 悬浮提示 / 无障碍标题（如 "缓存命中率 26%（900/3400 tokens）"） */
  title?: (data: StatusData) => string
  /** 栏目图标（与设置页「状态栏」卡片图标一致） */
  icon?: ReactNode
}

import type { ReactNode } from 'react'
import type { StatusBarState } from './types'

interface StatusBarItemViewProps {
  icon?: ReactNode
  /** 主体内容（占用值 / 状态文本等） */
  label: ReactNode
  /** 状态点:ok 绿 / warning 黄 / error 红 */
  state?: StatusBarState
  /** tooltip / 无障碍标题 */
  title?: string
}

/** 状态栏栏目通用外壳：胶囊按钮 + 可选图标 + 状态点 + tooltip。 */
export function StatusBarItemView({ icon, label, state = 'idle', title }: StatusBarItemViewProps) {
  return (
    <span
      className={`statusbar__item statusbar__item--${state}`}
      role="status"
      data-testid="statusbar-item"
      title={title}
      aria-label={title}
    >
      {icon && <span className="statusbar__icon">{icon}</span>}
      {state !== 'idle' && <span className="statusbar__dot" />}
      <span className="statusbar__label">{label}</span>
    </span>
  )
}

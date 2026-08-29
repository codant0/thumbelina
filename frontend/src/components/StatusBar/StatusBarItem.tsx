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
  /** 传入时渲染为可点击按钮；原生 button 自带语义，无需再写 role="status" */
  onClick?: () => void
}

/** 状态栏栏目通用外壳：胶囊外壳 + 可选图标 + 状态点 + tooltip；传 onClick 时渲染为按钮。 */
export function StatusBarItemView({ icon, label, state = 'idle', title, onClick }: StatusBarItemViewProps) {
  const className = `statusbar__item statusbar__item--${state}`
  const body = (
    <>
      {icon && <span className="statusbar__icon">{icon}</span>}
      {state !== 'idle' && <span className="statusbar__dot" />}
      <span className="statusbar__label">{label}</span>
    </>
  )

  if (onClick) {
    return (
      <button
        type="button"
        className={className}
        data-testid="statusbar-item"
        title={title}
        aria-label={title}
        onClick={onClick}
      >
        {body}
      </button>
    )
  }

  return (
    <span
      className={className}
      role="status"
      data-testid="statusbar-item"
      title={title}
      aria-label={title}
    >
      {body}
    </span>
  )
}

import type { ReactNode } from 'react'

interface EmptyStateProps {
  icon: ReactNode
  title: string
  hint?: string
  action?: ReactNode
  testId?: string
  /** Compact variant for in-card empty states (smaller icon tile & padding). */
  compact?: boolean
}

/** Unified empty/first-use state: icon tile, title, optional hint and action. */
export function EmptyState({ icon, title, hint, action, testId, compact }: EmptyStateProps) {
  return (
    <div
      className={`empty-state-block${compact ? ' empty-state-block--compact' : ''}`}
      data-testid={testId}
    >
      <div className="empty-state-block__icon" aria-hidden="true">{icon}</div>
      <div className="empty-state-block__title">{title}</div>
      {hint && <div className="empty-state-block__hint">{hint}</div>}
      {action}
    </div>
  )
}

import type { ReactNode } from 'react'
import { Check } from 'lucide-react'
import type { StatusBarConfig } from './useStatusBarConfig'

export interface StatusBarCardDef<K extends keyof StatusBarConfig> {
  /** 配置键（对应 useStatusBarConfig 中的栏目） */
  key: K
  /** 栏目名（已 i18n） */
  label: string
  /** 一句说明（已 i18n） */
  description: string
  /** 卡片前导图标 */
  icon?: ReactNode
}

interface StatusBarCardGridProps<K extends keyof StatusBarConfig> {
  cards: StatusBarCardDef<K>[]
  config: StatusBarConfig
  onToggle: (key: K) => void
}

/**
 * 状态栏栏目设置的整卡可点切换网格。
 *
 * 每张卡片整体是一个 button，点击切换开/关：开态 = accent 边框+弱化底色+右上角勾选，
 * 关态 = 灰色边框+降级文字。设置页始终渲染本网格（保证用户可随时重开栏目）；
 * 状态栏本体是否隐藏由各栏目组件自身决定，与本网格无关。
 */
export function StatusBarCardGrid<K extends keyof StatusBarConfig>({
  cards,
  config,
  onToggle,
}: StatusBarCardGridProps<K>) {
  if (cards.length === 0) return null

  return (
    <div className="status-grid" data-testid="statusbar-card-grid">
      {cards.map(card => {
        const on = config[card.key]
        return (
          <button
            key={card.key}
            type="button"
            aria-pressed={on}
            aria-label={card.label}
            data-testid={`statusbar-card-${card.key}`}
            className={`status-card${on ? ' status-card--on' : ' status-card--off'}`}
            onClick={() => onToggle(card.key)}
          >
            {card.icon && <span className="status-card__icon">{card.icon}</span>}
            <span className="status-card__body">
              <span className="status-card__label">{card.label}</span>
              <span className="status-card__desc">{card.description}</span>
            </span>
            {on && (
              <span className="status-card__check" aria-hidden="true">
                <Check size={16} />
              </span>
            )}
          </button>
        )
      })}
    </div>
  )
}

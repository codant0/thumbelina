import { useTranslation } from '../../i18n'
import { ThemeToggle } from './ThemeToggle'
import {
  MessageSquare,
  ListTodo,
  Database,
  Sparkles,
  Settings,
  Blocks,
  Radio,
} from 'lucide-react'
import type { ComponentType } from 'react'

export type Page = 'chat' | 'tasks' | 'memory' | 'dream' | 'settings' | 'plugins' | 'channels'

const navKeys: Page[] = ['chat', 'tasks', 'memory', 'dream', 'settings', 'plugins', 'channels']

const NAV_ICONS: Record<Page, ComponentType<{ size?: number | string }>> = {
  chat: MessageSquare,
  tasks: ListTodo,
  memory: Database,
  dream: Sparkles,
  settings: Settings,
  plugins: Blocks,
  channels: Radio,
}

interface HeaderProps {
  activePage: Page
  onNavigate: (page: Page) => void
}

export function Header({ activePage, onNavigate }: HeaderProps) {
  const { t } = useTranslation()

  return (
    <header className="header">
      <div className="header-brand">
        <span className="brand-dot" />
        <h1>Thumbelina</h1>
      </div>
      <nav>
        {navKeys.map(page => {
          const Icon = NAV_ICONS[page]
          return (
            <button
              key={page}
              data-testid={`nav-${page}`}
              className={activePage === page ? 'active' : ''}
              onClick={() => onNavigate(page)}
            >
              <Icon />
              {t(`nav.${page}`)}
            </button>
          )
        })}
      </nav>
      <ThemeToggle />
    </header>
  )
}

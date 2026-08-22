import { useTranslation } from '../../i18n'
import { ThemeToggle } from './ThemeToggle'
import {
  MessageSquare,
  ListTodo,
  ClipboardList,
  Database,
  Sparkles,
  Settings,
  Blocks,
  Radio,
  BookOpen,
  Footprints,
} from 'lucide-react'
import type { ComponentType } from 'react'

export type Page = 'chat' | 'trajectory' | 'tasks' | 'todo' | 'memory' | 'dream' | 'knowledge-base' | 'settings' | 'plugins' | 'channels'

const navKeys: Page[] = ['chat', 'trajectory', 'tasks', 'todo', 'memory', 'dream', 'knowledge-base', 'settings', 'plugins', 'channels']

const NAV_ICONS: Record<Page, ComponentType<{ size?: number | string }>> = {
  chat: MessageSquare,
  trajectory: Footprints,
  tasks: ListTodo,
  todo: ClipboardList,
  memory: Database,
  dream: Sparkles,
  'knowledge-base': BookOpen,
  settings: Settings,
  plugins: Blocks,
  channels: Radio,
}

interface HeaderProps {
  activePage: Page
  onNavigate: (page: Page) => void
}

const NAV_I18N: Record<Page, string> = {
  chat: 'nav.chat',
  trajectory: 'nav.trajectory',
  tasks: 'nav.tasks',
  todo: 'nav.todo',
  memory: 'nav.memory',
  dream: 'nav.dream',
  'knowledge-base': 'nav.knowledgeBase',
  settings: 'nav.settings',
  plugins: 'nav.plugins',
  channels: 'nav.channels',
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
              {t(NAV_I18N[page])}
            </button>
          )
        })}
      </nav>
      <ThemeToggle />
    </header>
  )
}

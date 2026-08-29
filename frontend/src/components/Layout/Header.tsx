import { useTranslation } from '../../i18n'
import { ThemeToggle } from './ThemeToggle'
import {
  MessageSquare,
  Code2,
  ListTodo,
  ClipboardList,
  Database,
  Sparkles,
  Settings,
  Blocks,
  Radio,
  BookOpen,
  Footprints,
  Menu,
  Languages,
} from 'lucide-react'
import type { ComponentType } from 'react'

export type Page = 'chat' | 'coder' | 'trajectory' | 'tasks' | 'todo' | 'memory' | 'dream' | 'knowledge-base' | 'settings' | 'plugins' | 'channels'

const navKeys: Page[] = ['chat', 'coder', 'trajectory', 'tasks', 'todo', 'memory', 'dream', 'knowledge-base', 'settings', 'plugins', 'channels']

const NAV_ICONS: Record<Page, ComponentType<{ size?: number | string }>> = {
  chat: MessageSquare,
  coder: Code2,
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
  /** Toggles the conversation sidebar drawer on small screens. */
  onToggleSidebar?: () => void
}

const NAV_I18N: Record<Page, string> = {
  chat: 'nav.chat',
  coder: 'nav.coder',
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

export function Header({ activePage, onNavigate, onToggleSidebar }: HeaderProps) {
  const { t, locale, setLocale } = useTranslation()

  const toggleLocale = () => setLocale(locale === 'en' ? 'zh-CN' : 'en')

  return (
    <header className="header">
      <div className="header-brand">
        <span className="brand-dot" />
        <h1>Thumbelina</h1>
      </div>
      {onToggleSidebar && (
        <button
          type="button"
          className="sidebar-hamburger"
          data-testid="sidebar-hamburger"
          aria-label={t('chat.sidebarTitle')}
          onClick={onToggleSidebar}
        >
          <Menu size={16} />
        </button>
      )}
      <nav>
        {navKeys.map(page => {
          const Icon = NAV_ICONS[page]
          return (
            <button
              key={page}
              data-testid={`nav-${page}`}
              className={activePage === page ? 'active' : ''}
              title={t(NAV_I18N[page])}
              aria-current={activePage === page ? 'page' : undefined}
              onClick={() => onNavigate(page)}
            >
              <Icon />
              <span className="nav-label">{t(NAV_I18N[page])}</span>
            </button>
          )
        })}
      </nav>
      <div className="header-actions">
        <button
          type="button"
          className="lang-toggle-btn"
          data-testid="lang-toggle"
          onClick={toggleLocale}
          title={t('settings.language')}
          aria-label={t('settings.language')}
        >
          <Languages size={14} />
          <span>{locale === 'en' ? '中文' : 'EN'}</span>
        </button>
        <ThemeToggle />
      </div>
    </header>
  )
}

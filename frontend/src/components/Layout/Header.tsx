import { useTranslation } from '../../i18n'
import { ThemeToggle } from './ThemeToggle'

export type Page = 'chat' | 'tasks' | 'memory' | 'dream' | 'settings' | 'plugins' | 'channels'

const navKeys: Page[] = ['chat', 'tasks', 'memory', 'dream', 'settings', 'plugins', 'channels']

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
        {navKeys.map(page => (
          <button
            key={page}
            data-testid={`nav-${page}`}
            className={activePage === page ? 'active' : ''}
            onClick={() => onNavigate(page)}
          >
            {t(`nav.${page}`)}
          </button>
        ))}
      </nav>
      <ThemeToggle />
    </header>
  )
}

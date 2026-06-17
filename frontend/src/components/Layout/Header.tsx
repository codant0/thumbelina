import { ThemeToggle } from './ThemeToggle'

export type Page = 'chat' | 'tasks' | 'memory' | 'dream' | 'settings' | 'plugins' | 'channels'

interface HeaderProps {
  activePage: Page
  onNavigate: (page: Page) => void
}

const links: { page: Page; label: string }[] = [
  { page: 'chat', label: 'Chat' },
  { page: 'tasks', label: 'Tasks' },
  { page: 'memory', label: 'Memory' },
  { page: 'dream', label: 'Dream' },
  { page: 'settings', label: 'Settings' },
  { page: 'plugins', label: 'Plugins' },
  { page: 'channels', label: 'Channels' },
]

export function Header({ activePage, onNavigate }: HeaderProps) {
  return (
    <header className="header">
      <div className="header-brand">
        <span className="brand-dot" />
        <h1>Thumbelina</h1>
      </div>
      <nav>
        {links.map(link => (
          <button
            key={link.page}
            data-testid={`nav-${link.page}`}
            className={activePage === link.page ? 'active' : ''}
            onClick={() => onNavigate(link.page)}
          >
            {link.label}
          </button>
        ))}
      </nav>
      <ThemeToggle />
    </header>
  )
}

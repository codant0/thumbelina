export type Page = 'chat' | 'tasks' | 'memory' | 'dream' | 'settings'

interface HeaderProps {
  activePage: Page
  onNavigate: (page: Page) => void
}

export function Header({ activePage, onNavigate }: HeaderProps) {
  const links: { page: Page; label: string }[] = [
    { page: 'chat', label: 'Chat' },
    { page: 'tasks', label: 'Tasks' },
    { page: 'memory', label: 'Memory' },
    { page: 'dream', label: 'Dream' },
    { page: 'settings', label: 'Settings' },
  ]

  return (
    <header>
      <h1>Thumbelina</h1>
      <nav>
        {links.map(link => (
          <button
            key={link.page}
            data-testid={`nav-${link.page}`}
            onClick={() => onNavigate(link.page)}
            style={{ fontWeight: activePage === link.page ? 'bold' : 'normal' }}
          >
            {link.label}
          </button>
        ))}
      </nav>
    </header>
  )
}

import { useState, useEffect } from 'react'

type Theme = 'dark' | 'light' | 'warm'

const THEMES: { value: Theme; label: string; icon: string }[] = [
  { value: 'dark', label: 'Dark', icon: '\u{1F319}' },
  { value: 'light', label: 'Light', icon: '\u{2600}\u{FE0F}' },
  { value: 'warm', label: 'Warm', icon: '\u{1F525}' },
]

const STORAGE_KEY = 'thumbelina-theme'

function getInitialTheme(): Theme {
  try {
    const stored = localStorage.getItem(STORAGE_KEY)
    if (stored && ['dark', 'light', 'warm'].includes(stored)) {
      return stored as Theme
    }
  } catch { /* ignore */ }
  return 'dark'
}

export function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>(getInitialTheme)
  const [isOpen, setIsOpen] = useState(false)

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme)
    try {
      localStorage.setItem(STORAGE_KEY, theme)
    } catch { /* ignore */ }
  }, [theme])

  const currentTheme = THEMES.find(t => t.value === theme)!

  return (
    <div className="theme-toggle-wrapper">
      <button
        className="theme-toggle-btn"
        onClick={() => setIsOpen(!isOpen)}
        title="Change theme"
        aria-label="Change theme"
      >
        <span className="theme-toggle-icon">{currentTheme.icon}</span>
      </button>
      {isOpen && (
        <div className="theme-dropdown">
          {THEMES.map(t => (
            <button
              key={t.value}
              className={`theme-option${theme === t.value ? ' active' : ''}`}
              onClick={() => {
                setTheme(t.value)
                setIsOpen(false)
              }}
            >
              <span className="theme-option-icon">{t.icon}</span>
              <span className="theme-option-label">{t.label}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

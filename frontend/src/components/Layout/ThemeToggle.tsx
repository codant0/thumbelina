import { useState, useEffect, useRef } from 'react'
import { Moon, Sun, Flame, Check } from 'lucide-react'
import { useTranslation } from '../../i18n'

type Theme = 'dark' | 'light' | 'warm'

const THEMES: { value: Theme; label: string; Icon: typeof Moon }[] = [
  { value: 'dark', label: 'Dark', Icon: Moon },
  { value: 'light', label: 'Light', Icon: Sun },
  { value: 'warm', label: 'Warm', Icon: Flame },
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
  const wrapperRef = useRef<HTMLDivElement>(null)
  const { t } = useTranslation()

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme)
    try {
      localStorage.setItem(STORAGE_KEY, theme)
    } catch { /* ignore */ }
  }, [theme])

  useEffect(() => {
    if (!isOpen) return
    const handler = (e: MouseEvent) => {
      if (wrapperRef.current && !wrapperRef.current.contains(e.target as Node)) {
        setIsOpen(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [isOpen])

  const currentTheme = THEMES.find(t => t.value === theme)!
  const CurrentIcon = currentTheme.Icon

  return (
    <div className="theme-toggle-wrapper" ref={wrapperRef}>
      <button
        className="theme-toggle-btn"
        onClick={() => setIsOpen(!isOpen)}
        title={t('theme.changeTheme')}
        aria-label={t('theme.changeTheme')}
        aria-expanded={isOpen}
      >
        <CurrentIcon size={16} />
      </button>
      {isOpen && (
        <div className="theme-dropdown" role="menu">
          {THEMES.map(({ value, Icon }) => (
            <button
              key={value}
              className={`theme-option${theme === value ? ' active' : ''}`}
              onClick={() => {
                setTheme(value)
                setIsOpen(false)
              }}
              role="menuitem"
            >
              <span className="theme-option-icon">
                <Icon size={14} />
              </span>
              <span className="theme-option-label">{t(`theme.${value}`)}</span>
              {theme === value && <Check size={14} />}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

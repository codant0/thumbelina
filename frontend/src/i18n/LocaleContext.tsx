/* eslint-disable react-refresh/only-export-components */
import { createContext, useState, useEffect, useCallback, type ReactNode } from 'react'

export type Locale = 'en' | 'zh-CN'

export interface LocaleContextValue {
  locale: Locale
  setLocale: (locale: Locale) => void
  t: (key: string, params?: Record<string, string | number>) => string
}

const STORAGE_KEY = 'thumbelina-locale'
const DEFAULT_LOCALE: Locale = 'en'

function getInitialLocale(): Locale {
  try {
    const stored = localStorage.getItem(STORAGE_KEY)
    if (stored === 'en' || stored === 'zh-CN') return stored
  } catch { /* ignore */ }
  if (typeof navigator !== 'undefined' && navigator.language.startsWith('zh')) {
    return 'zh-CN'
  }
  return DEFAULT_LOCALE
}

import en from './locales/en.json'
import zhCN from './locales/zh-CN.json'

const dictionaries: Record<Locale, Record<string, unknown>> = {
  en,
  'zh-CN': zhCN,
}

export const LocaleContext = createContext<LocaleContextValue>({
  locale: DEFAULT_LOCALE,
  setLocale: () => {},
  t: (key: string) => getNestedValue(en, key) ?? key,
})

interface LocaleProviderProps {
  children: ReactNode
}

export function LocaleProvider({ children }: LocaleProviderProps) {
  const [locale, setLocaleState] = useState<Locale>(getInitialLocale)

  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, locale)
    } catch { /* ignore */ }
  }, [locale])

  const setLocale = useCallback((next: Locale) => {
    setLocaleState(next)
  }, [])

  const t = useCallback(
    (key: string, params?: Record<string, string | number>) => {
      const dictionary = dictionaries[locale]
      let value = getNestedValue(dictionary, key) ?? key
      if (params) {
        value = Object.entries(params).reduce(
          (acc, [k, v]) => acc.replaceAll(`{${k}}`, String(v)),
          value,
        )
      }
      return value
    },
    [locale],
  )

  return (
    <LocaleContext.Provider value={{ locale, setLocale, t }}>
      {children}
    </LocaleContext.Provider>
  )
}

function getNestedValue(obj: Record<string, unknown>, path: string): string | undefined {
  const parts = path.split('.')
  let current: unknown = obj
  for (const part of parts) {
    if (current === null || typeof current !== 'object') return undefined
    current = (current as Record<string, unknown>)[part]
  }
  return typeof current === 'string' ? current : undefined
}

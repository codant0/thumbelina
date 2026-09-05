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

/** {k} 占位符参数替换:与 Provider 内的 t 共用,保证无 Provider 渲染时行为一致。 */
function interpolate(value: string, params?: Record<string, string | number>): string {
  if (!params) return value
  return Object.entries(params).reduce(
    (acc, [k, v]) => acc.replaceAll(`{${k}}`, String(v)),
    value,
  )
}

function translate(dictionary: Record<string, unknown>, key: string, params?: Record<string, string | number>): string {
  return interpolate(getNestedValue(dictionary, key) ?? key, params)
}

export const LocaleContext = createContext<LocaleContextValue>({
  locale: DEFAULT_LOCALE,
  setLocale: () => {},
  t: (key: string, params?: Record<string, string | number>) => translate(en, key, params),
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
    (key: string, params?: Record<string, string | number>) => translate(dictionaries[locale], key, params),
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

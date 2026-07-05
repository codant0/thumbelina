import { useContext } from 'react'
import { LocaleContext, type Locale, type LocaleContextValue } from './LocaleContext'

export function useLocale(): LocaleContextValue {
  return useContext(LocaleContext)
}

export function useTranslation(): { t: LocaleContextValue['t']; locale: Locale; setLocale: LocaleContextValue['setLocale'] } {
  const { t, locale, setLocale } = useContext(LocaleContext)
  return { t, locale, setLocale }
}

export type { Locale } from './LocaleContext'

import { useState, type ReactNode } from 'react'
import { Check, ChevronDown, Copy, FileJson } from 'lucide-react'
import { useTranslation } from '../../i18n'
import { useCopy } from '../../hooks/useCopy'

export function CopyButton({ text, className }: { text: string; className?: string }) {
  const { copied, copy } = useCopy()
  const { t } = useTranslation()
  return (
    <button
      type="button"
      className={className ?? 'codeblock__copy'}
      onClick={() => void copy(text)}
      title={copied ? t('codeblock.copied') : t('codeblock.copy')}
      aria-label={t('codeblock.copy')}
    >
      {copied ? <Check size={13} /> : <Copy size={13} />}
      <span>{copied ? t('codeblock.copied') : t('codeblock.copy')}</span>
    </button>
  )
}

/** Fenced code block with a language/copy header; `children` is the
 *  already-highlighted <code> element produced by rehype-highlight. */
export function CodeBlock({ raw, lang, children }: { raw: string; lang: string; children?: ReactNode }) {
  return (
    <div className="codeblock">
      <div className="codeblock__head">
        <span className="codeblock__lang">{lang}</span>
        <CopyButton text={raw} />
      </div>
      <pre>{children}</pre>
    </div>
  )
}

/** Collapsible card for bare JSON payloads surfaced inside messages
 *  (memory extraction events, raw tool outputs) instead of wall-of-text. */
export function JsonBlock({ text }: { text: string }) {
  const [open, setOpen] = useState(false)
  const { t } = useTranslation()
  let pretty = text
  try {
    pretty = JSON.stringify(JSON.parse(text), null, 2)
  } catch { /* keep raw */ }
  return (
    <div className="json-block" data-testid="json-block">
      <button type="button" className="json-block__header" aria-expanded={open} onClick={() => setOpen(o => !o)}>
        <FileJson size={13} />
        <span className="json-block__label">{t('jsonBlock.title')}</span>
        <ChevronDown size={14} className={`json-block__caret${open ? ' is-open' : ''}`} />
      </button>
      {open && (
        <div className="json-block__body">
          <pre>{pretty}</pre>
          <CopyButton text={pretty} className="codeblock__copy" />
        </div>
      )}
    </div>
  )
}

import { useEffect, useRef, useState } from 'react'
import { BookOpen, Check, ChevronDown } from 'lucide-react'
import { useTranslation } from '../../i18n'

interface KnowledgeBase {
  id: string
  name: string
}

interface KnowledgeBaseSelectorProps {
  conversationId?: string
  selectedKnowledgeBaseId?: string | null
  onChange: (knowledgeBaseId: string | null) => void
}

export function KnowledgeBaseSelector({
  conversationId,
  selectedKnowledgeBaseId,
  onChange,
}: KnowledgeBaseSelectorProps) {
  const [kbs, setKbs] = useState<KnowledgeBase[]>([])
  const [open, setOpen] = useState(false)
  const [loading, setLoading] = useState(true)
  const wrapRef = useRef<HTMLDivElement>(null)
  const { t } = useTranslation()

  useEffect(() => {
    let cancelled = false
    fetch('/api/v1/rag/knowledge-bases')
      .then(res => (res.ok ? res.json() : []))
      .then(data => {
        if (!cancelled) setKbs(Array.isArray(data) ? data : [])
      })
      .catch(() => {
        if (!cancelled) setKbs([])
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    if (!open) return
    const handler = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [open])

  const isNoneSelected = selectedKnowledgeBaseId == null
  const selectedKb = kbs.find(k => k.id === selectedKnowledgeBaseId)
  const label = loading
    ? t('common.loading')
    : isNoneSelected
      ? t('knowledgeBase.notUsingKnowledgeBase')
      : selectedKb?.name ?? t('knowledgeBase.notUsingKnowledgeBase')

  if (!conversationId) return null

  return (
    <div className="kb-selector" ref={wrapRef} data-testid="kb-selector">
      <button
        type="button"
        className="kb-selector__trigger"
        data-testid="kb-selector-trigger"
        title={t('knowledgeBase.chooseKnowledgeBase')}
        onClick={() => setOpen(o => !o)}
      >
        <BookOpen size={14} />
        <span className="kb-selector__label">{label}</span>
        <ChevronDown size={14} />
      </button>
      {open && (
        <ul className="kb-selector__menu" role="listbox" data-testid="kb-selector-menu">
          {/* None option */}
          <li
            role="option"
            aria-selected={isNoneSelected}
            className={`kb-selector__option${isNoneSelected ? ' selected' : ''}`}
            data-testid="kb-option-none"
            onClick={() => {
              onChange(null)
              setOpen(false)
            }}
          >
            <span className="kb-selector__name">{t('knowledgeBase.notUsingKnowledgeBase')}</span>
            {isNoneSelected && <Check size={14} />}
          </li>

          {/* KB options */}
          {kbs.map(kb => {
            const selected = selectedKnowledgeBaseId === kb.id
            return (
              <li
                key={kb.id}
                role="option"
                aria-selected={selected}
                className={`kb-selector__option${selected ? ' selected' : ''}`}
                data-testid={`kb-option-${kb.id}`}
                onClick={() => {
                  onChange(kb.id)
                  setOpen(false)
                }}
              >
                <span className="kb-selector__name">{kb.name}</span>
                {selected && <Check size={14} />}
              </li>
            )
          })}

          {kbs.length === 0 && !loading && (
            <li className="kb-selector__empty">{t('knowledgeBase.noKnowledgeBases')}</li>
          )}
        </ul>
      )}
    </div>
  )
}

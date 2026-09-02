import { useEffect, useRef, useState } from 'react'
import { BookOpen, Check, ChevronUp } from 'lucide-react'
import { useTranslation } from '../../i18n'
import * as ragApi from '../../api/rag'
import type { KnowledgeBase } from '../../types/rag'

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
    ragApi.listKnowledgeBases()
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
    const onPointerDown = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onPointerDown)
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('mousedown', onPointerDown)
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [open])

  if (!conversationId) return null

  const selectedKb = kbs.find(k => k.id === selectedKnowledgeBaseId)
  const active = selectedKb != null
  const label = loading
    ? t('common.loading')
    : selectedKb?.name ?? t('nav.knowledgeBase')

  return (
    <div className="kb-float" ref={wrapRef} data-testid="kb-selector">
      <button
        type="button"
        className={`kb-float__trigger${active ? ' is-active' : ''}`}
        data-testid="kb-selector-trigger"
        aria-haspopup="listbox"
        aria-expanded={open}
        title={t('knowledgeBase.chooseKnowledgeBase')}
        onClick={() => setOpen(o => !o)}
      >
        <BookOpen size={14} />
        <span className="kb-float__label">{label}</span>
        <ChevronUp size={13} className={`kb-float__caret${open ? ' is-open' : ''}`} />
      </button>

      {open && (
        <div
          className="kb-float__panel"
          role="listbox"
          data-testid="kb-selector-menu"
          data-density={kbs.length < 4 ? 'compact' : 'scrollable'}
        >
          <div className="kb-float__heading">{t('knowledgeBase.chooseKnowledgeBase')}</div>

          <button
            type="button"
            role="option"
            aria-selected={selectedKnowledgeBaseId == null}
            className={`kb-float__option${selectedKnowledgeBaseId == null ? ' is-selected' : ''}`}
            data-testid="kb-option-none"
            onClick={() => {
              onChange(null)
              setOpen(false)
            }}
          >
            <span className="kb-float__option-body">
              <span className="kb-float__name">{t('knowledgeBase.notUsingKnowledgeBase')}</span>
            </span>
            {selectedKnowledgeBaseId == null && <Check size={14} className="kb-float__check" />}
          </button>

          {kbs.map(kb => {
            const selected = selectedKnowledgeBaseId === kb.id
            return (
              <button
                key={kb.id}
                type="button"
                role="option"
                aria-selected={selected}
                className={`kb-float__option${selected ? ' is-selected' : ''}`}
                data-testid={`kb-option-${kb.id}`}
                onClick={() => {
                  onChange(kb.id)
                  setOpen(false)
                }}
              >
                <span className="kb-float__option-body">
                  <span className="kb-float__name">{kb.name}</span>
                  {typeof kb.document_count === 'number' && (
                    <span className="kb-float__meta">
                      {t('knowledgeBase.docCount', { count: kb.document_count })}
                    </span>
                  )}
                </span>
                {selected && <Check size={14} className="kb-float__check" />}
              </button>
            )
          })}

          {kbs.length === 0 && !loading && (
            <div className="kb-float__empty">{t('knowledgeBase.noKnowledgeBases')}</div>
          )}
        </div>
      )}
    </div>
  )
}

import { useEffect, useRef } from 'react'
import type { ReactNode } from 'react'
import { X } from 'lucide-react'
import { useTranslation } from '../../i18n'

interface ModalProps {
  /** Dialog title shown in the header. */
  title: string
  /** Called when the user closes the dialog (backdrop / Esc / close button). */
  onClose: () => void
  children: ReactNode
}

/** Reusable centered dialog with backdrop, Esc-to-close and focus entry. */
export function Modal({ title, onClose, children }: ModalProps) {
  const { t } = useTranslation()
  const panelRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKey)
    panelRef.current?.focus()
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  return (
    <div className="modal-overlay" data-testid="modal-overlay" onClick={onClose}>
      <div
        ref={panelRef}
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-label={title}
        tabIndex={-1}
        data-testid="modal"
        onClick={e => e.stopPropagation()}
      >
        <div className="modal__header">
          <span className="modal__title">{title}</span>
          <button
            type="button"
            className="modal__close"
            onClick={onClose}
            aria-label={t('common.close')}
            data-testid="modal-close"
          >
            <X size={16} />
          </button>
        </div>
        <div className="modal__body">{children}</div>
      </div>
    </div>
  )
}

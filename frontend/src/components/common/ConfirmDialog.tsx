import { Modal } from '../Settings/Modal'
import { useTranslation } from '../../i18n'

interface ConfirmDialogProps {
  title: string
  message: string
  /** Renders the confirm button with the danger (red) style. */
  danger?: boolean
  onConfirm: () => void
  onCancel: () => void
}

/** Theme-aware replacement for window.confirm(). */
export function ConfirmDialog({ title, message, danger, onConfirm, onCancel }: ConfirmDialogProps) {
  const { t } = useTranslation()
  return (
    <Modal title={title} onClose={onCancel}>
      <p style={{ fontSize: 'var(--fs-base)', color: 'var(--text-primary)', lineHeight: 1.6 }}>{message}</p>
      <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 'var(--sp-2)', marginTop: 'var(--sp-5)' }}>
        <button type="button" className="btn btn-ghost" data-testid="confirm-cancel" onClick={onCancel}>
          {t('common.cancel')}
        </button>
        <button
          type="button"
          className={`btn ${danger ? 'btn-danger' : 'btn-primary'}`}
          data-testid="confirm-ok"
          onClick={onConfirm}
        >
          {t('common.confirm')}
        </button>
      </div>
    </Modal>
  )
}

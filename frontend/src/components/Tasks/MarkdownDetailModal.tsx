import type { ReactNode } from 'react'
import { Modal } from '../Settings/Modal'
import { MarkdownContent } from '../Chat/MarkdownContent'

interface MarkdownDetailModalProps {
  /** Modal title (becomes the header label and aria-label). */
  title: string
  /** Optional subtitle line under the title (e.g. event time / channel). */
  subtitle?: ReactNode
  /** Markdown body to render. Empty/null renders a "no content" placeholder
   *  instead of an empty modal. */
  markdown: string | null
  onClose: () => void
  /** Extra body block (e.g. a "view conversation" link). */
  footer?: ReactNode
}

/** Lightweight modal that renders a Markdown body. Reused by event-detail and
 *  subagent-result inspetion so both surfaces render Markdown consistently. */
export function MarkdownDetailModal({
  title,
  subtitle,
  markdown,
  onClose,
  footer,
}: MarkdownDetailModalProps) {
  return (
    <Modal title={title} onClose={onClose} className="modal--wide">
      {subtitle && <div className="detail-subtitle">{subtitle}</div>}
      <div className="detail-section">
        {markdown ? (
          <MarkdownContent content={markdown} />
        ) : (
          <div className="detail-empty">—</div>
        )}
      </div>
      {footer}
    </Modal>
  )
}
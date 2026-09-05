import { useEffect } from 'react'
import { ChevronLeft, ChevronRight, X } from 'lucide-react'
import { attachmentUrl } from '../../api/attachments'

/** Lightbox 展示的附件:仅保证 id(乐观插入的用户消息 attachments 无 mime 字段)。 */
interface LightboxAttachment {
  id: string
  alt?: string
}

interface AttachmentLightboxProps {
  /** 当前消息的附件列表(渲染时按 attachmentUrl(id) 取图)。 */
  attachments: LightboxAttachment[]
  /** 当前打开的附件下标。 */
  index: number
  onClose: () => void
  onIndexChange: (index: number) => void
}

/**
 * 轻量图片查看遮罩(设计 §5.2.1 / F5):
 * - 全新遮罩组件,不复用 FloatWindow(那是可拖拽迷你窗,定位不符);
 * - position:fixed 全屏遮罩 + 居中图片 + 顶部关闭 + 多图左右切换 + n / total 计数;
 * - 键盘:Esc 关闭、←/→ 切换(仅打开时挂 document keydown);
 * - 样式类名全部由 T7 统一进 styles/chat.css。
 */
export function AttachmentLightbox({ attachments, index, onClose, onIndexChange }: AttachmentLightboxProps) {
  const total = attachments.length
  const safeIndex = Math.min(Math.max(index, 0), Math.max(total - 1, 0))
  const current = attachments[safeIndex]

  // 键盘导航:Esc 关闭,←/→ 循环切换。仅挂载期间监听(组件只在打开时渲染)。
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onClose()
        return
      }
      if (total <= 1) return
      if (e.key === 'ArrowLeft') onIndexChange((safeIndex - 1 + total) % total)
      if (e.key === 'ArrowRight') onIndexChange((safeIndex + 1) % total)
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [safeIndex, total, onClose, onIndexChange])

  if (!current) return null

  return (
    <div className="lightbox-backdrop" role="dialog" aria-modal="true" aria-label="图片预览" data-testid="attachment-lightbox">
      <button
        type="button"
        className="lightbox-close"
        aria-label="关闭"
        title="关闭"
        onClick={onClose}
      >
        <X size={20} />
      </button>
      {/* 规格 §5.1.4 要求显式 role="img"(<img> 原生即有,双写无害) */}
      <img className="lightbox-image" role="img" src={attachmentUrl(current.id)} alt={current.alt ?? ''} />
      {total > 1 && (
        <>
          <button
            type="button"
            className="lightbox-prev"
            aria-label="上一张"
            title="上一张"
            onClick={() => onIndexChange((safeIndex - 1 + total) % total)}
          >
            <ChevronLeft size={24} />
          </button>
          <button
            type="button"
            className="lightbox-next"
            aria-label="下一张"
            title="下一张"
            onClick={() => onIndexChange((safeIndex + 1) % total)}
          >
            <ChevronRight size={24} />
          </button>
          <div className="lightbox-counter">{safeIndex + 1} / {total}</div>
        </>
      )}
    </div>
  )
}

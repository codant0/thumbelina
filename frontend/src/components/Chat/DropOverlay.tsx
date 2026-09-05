import { useDropZone } from '../../hooks/useDropZone'
import { useTranslation } from '../../i18n'

interface DropOverlayProps {
  /** 落下的图片文件(已由 useDropZone 过滤);与 📎 按钮共用同一条上传管道。 */
  onFiles: (files: File[]) => void
}

/**
 * 全屏拖放覆盖层(设计 §5.1.2 F4):
 * - 仅当拖入的 dataTransfer.types 含 'Files' 时出现(码农页代码块拖选不触发);
 * - position:fixed 蒙层 + 中央卡片「松开以上传图片」(样式统一在 styles/chat.css);
 * - drop 落下的文件经由 onFiles 回调交给 ChatWindow 的共享上传管道。
 */
export function DropOverlay({ onFiles }: DropOverlayProps) {
  const { t } = useTranslation()
  const { isDragging } = useDropZone(onFiles)
  if (!isDragging) return null
  return (
    <div className="drop-overlay" data-testid="drop-overlay">
      <div className="drop-overlay__card">{t('chat.attachments.dropHint')}</div>
    </div>
  )
}

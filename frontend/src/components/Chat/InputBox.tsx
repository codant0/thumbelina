import { useEffect, useRef, useState, type ChangeEvent, type FormEvent, type KeyboardEvent, type ReactNode } from 'react'
import { AlertCircle, Clock, ImagePlus, Send, Square, X, Zap } from 'lucide-react'
import { useTranslation } from '../../i18n'
import { canSendMessage } from '../../hooks/useWebSocket'
import type { SendAttachmentInput } from '../../types/chat'
import type { UploadedAttachment } from '../../api/attachments'
import { addFilesToAttachments, attachmentHintKey, removeLocalAttachment, retryLocalAttachment } from './useAttachments'

/**
 * 本地待发附件状态(设计 §5.1):受控数组由 ChatWindow 持有,
 * InputBox 通过 onAttachmentsChange 同步;上传管道见 useAttachments.ts。
 * previewUrl 为渲染扩展字段:object URL 预览,由 InputBox 在移除/卸载时 revoke。
 */
export interface LocalAttachment {
  localId: string          // crypto.randomUUID() 或递增
  file: File
  status: 'uploading' | 'ready' | 'failed'
  uploaded?: UploadedAttachment
  alt?: string
  /** object URL 缩略图预览(jsdom 不可用时为空串)。 */
  previewUrl?: string
}

interface InputBoxProps {
  onSend: (message: string, attachments?: SendAttachmentInput[]) => void
  disabled?: boolean
  toolbar?: ReactNode
  /** While the model is replying, a stop button appears next to the send button. */
  isStreaming?: boolean
  /** Called when the user stops generation (only used while isStreaming). */
  onStop?: () => void
  /** Queued message for the active conversation (single slot); null = none. */
  pendingMessage?: string | null
  /** The queued message is held because the previous reply ended abnormally. */
  pendingHeld?: boolean
  /** Submitting while streaming queues the message instead of sending it. */
  onQueueSend?: (message: string, attachments?: SendAttachmentInput[]) => void
  /** Send the queued message now (stops the running reply first when needed). */
  onSendPendingNow?: () => void
  onCancelPending?: () => void
  /** 待发附件(受控,由 ChatWindow 持有);不传 = 不启用附件功能。 */
  attachments?: LocalAttachment[]
  /** 附件数组任何变化的同步出口(添加/删除/清空);也接受函数式更新(添加管道并发安全)。 */
  onAttachmentsChange?: (next: LocalAttachment[] | ((prev: LocalAttachment[]) => LocalAttachment[])) => void
  /** 当前待发消息里排队的图片数(悬浮条徽标展示)。 */
  pendingAttachmentCount?: number
}

const EMPTY_ATTACHMENTS: LocalAttachment[] = []

/** 文件名超长截断(规格 §5.1.4):>30 字符 → 前 25 + … + 后 4,避免 aria-label 溢出。 */
function truncateName(name: string): string {
  return name.length > 30 ? `${name.slice(0, 25)}…${name.slice(-4)}` : name
}

/** 上传中/失败态的缩略卡片。 */
function AttachmentThumb({ att, onRemove, onRetry }: {
  att: LocalAttachment
  onRemove: () => void
  onRetry: () => void
}) {
  const { t } = useTranslation()
  const name = truncateName(att.file.name)
  const dims = att.uploaded?.width != null && att.uploaded?.height != null
    ? `, ${att.uploaded.width}×${att.uploaded.height}`
    : ''
  const failed = att.status === 'failed'
  return (
    // failed 态整卡可点重试:重试按钮铺满卡片(inset:0,样式见 chat.css)
    <div
      className={`attachment-thumb${failed ? ' attachment-thumb--failed' : ''}`}
      data-status={att.status}
    >
      <span className="attachment-thumb__image" role="img" aria-label={`${name}${dims}`}>
        {att.previewUrl ? <img src={att.previewUrl} alt="" /> : null}
      </span>
      {att.status === 'uploading' && (
        <span className="attachment-thumb__progress" aria-label={t('chat.attachments.uploading')}>
          {/* 进度环:SVG stroke-dashoffset 动画由 chat.css 实现(stroke 用 var(--accent)) */}
          <svg viewBox="0 0 24 24" width={16} height={16} aria-hidden="true">
            <circle className="attachment-thumb__progress-track" cx="12" cy="12" r="9" fill="none" strokeWidth="3" />
            <circle
              className="attachment-thumb__progress-bar"
              cx="12" cy="12" r="9" fill="none" strokeWidth="3"
              strokeDasharray="56.55" strokeDashoffset="14" strokeLinecap="round"
            />
          </svg>
        </span>
      )}
      {failed && (
        <button
          type="button"
          className="attachment-thumb__retry"
          aria-label={t('chat.attachments.uploadFailed')}
          title={t('chat.attachments.uploadFailed')}
          onClick={onRetry}
        >
          {t('chat.attachments.retry')}
        </button>
      )}
      <button
        type="button"
        className="attachment-thumb__remove"
        aria-label={t('chat.attachments.removeAlt')}
        title={t('chat.attachments.removeAlt')}
        onClick={onRemove}
      >
        <X size={12} />
      </button>
    </div>
  )
}

export function InputBox({
  onSend,
  disabled,
  toolbar,
  isStreaming,
  onStop,
  pendingMessage,
  pendingHeld,
  onQueueSend,
  onSendPendingNow,
  onCancelPending,
  attachments,
  onAttachmentsChange,
  pendingAttachmentCount,
}: InputBoxProps) {
  const [text, setText] = useState('')
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  // 添加管道的行内提示(存 i18n 键,渲染时经 t() 翻译;2 秒自动消失)
  const [hint, setHint] = useState<string | null>(null)
  // 添加/重试管道在 async 续段里要读最新列表 —— 用 ref 镜像受控数组,避免闭包过期。
  const attachmentsRef = useRef<LocalAttachment[]>(attachments ?? EMPTY_ATTACHMENTS)
  // 已创建的 object URL(localId -> url):移除/卸载时 revoke,父级清空(切会话)时兜底回收。
  // 由下方 effect 从受控列表登记(管道在构造 LocalAttachment 时已 createObjectURL)。
  const previewUrlsRef = useRef<Map<string, string>>(new Map())
  const { t } = useTranslation()

  const list = attachments ?? EMPTY_ATTACHMENTS
  const readyItems = list.filter(a => a.status === 'ready' && a.uploaded)
  const readyCount = readyItems.length
  // 仅 ready 项映射为发送引用;failed/uploading 项阻塞发送
  const readyRefs: SendAttachmentInput[] = readyItems.map(a => {
    const ref: SendAttachmentInput = { id: a.uploaded!.id }
    if (a.alt !== undefined) ref.alt = a.alt
    return ref
  })
  const hasBlockingAttachments = list.some(a => a.status !== 'ready')

  useEffect(() => {
    attachmentsRef.current = list
    // 登记当前列表的预览 URL(previewUrlsRef 的唯一写入点):移除/父级清空/卸载
    // 三处回收都从这里读取。previewUrl 为空串(jsdom 不可用兜底)时不登记。
    for (const a of list) {
      if (a.previewUrl) previewUrlsRef.current.set(a.localId, a.previewUrl)
    }
  }, [list])

  // 兜底回收:附件从列表消失(手动删除 / 父级清空)时 revoke 对应 object URL,
  // 并把条目移出映射,避免映射随反复添加/删除无界增长。
  useEffect(() => {
    const alive = new Set(list.map(a => a.localId))
    for (const [localId, url] of previewUrlsRef.current) {
      if (!alive.has(localId)) {
        if (url) URL.revokeObjectURL(url)
        previewUrlsRef.current.delete(localId)
      }
    }
  }, [list])

  // 组件卸载:revoke 全部预览 URL。
  useEffect(() => () => {
    for (const url of previewUrlsRef.current.values()) {
      if (url) URL.revokeObjectURL(url)
    }
  }, [])

  // 行内提示 2 秒自动消失。
  useEffect(() => {
    if (!hint) return
    const timer = setTimeout(() => setHint(null), 2000)
    return () => clearTimeout(timer)
  }, [hint])

  const clearTextarea = () => {
    setText('')
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto'
    }
  }

  // 添加/重试管道的函数式变更出口:在 setState updater 内同步刷新镜像 ref,
  // 管道下一个 async 续段的 getCurrent() 才能读到最新列表(多张上传的补丁
  // 基于最新 prev 计算,互不覆盖——值式写回会被批处理下的过期快照覆盖)。
  const pushAttachmentUpdate = (updater: (prev: LocalAttachment[]) => LocalAttachment[]) => {
    onAttachmentsChange?.(prev => {
      const next = updater(prev)
      attachmentsRef.current = next
      return next
    })
  }

  // 共享添加管道(设计 §5.1.2):与拖放 drop 走同一条 useAttachments.addFilesToAttachments。
  const handleAddFiles = (files: File[]) => {
    if (!onAttachmentsChange || files.length === 0) return
    void addFilesToAttachments(files, {
      getCurrent: () => attachmentsRef.current,
      update: pushAttachmentUpdate,
    }).then(result => {
      if (result) setHint(attachmentHintKey(result))
    })
  }

  const handleFileChosen = (e: ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files ?? [])
    e.target.value = '' // 允许再次选择同一文件
    handleAddFiles(files)
  }

  const handleRemove = (localId: string) => {
    if (!onAttachmentsChange) return
    const url = previewUrlsRef.current.get(localId)
    if (url) {
      URL.revokeObjectURL(url)
      previewUrlsRef.current.delete(localId)
    }
    onAttachmentsChange(removeLocalAttachment(list, localId))
  }

  const handleRetry = (localId: string) => {
    if (!onAttachmentsChange) return
    void retryLocalAttachment(localId, {
      getCurrent: () => attachmentsRef.current,
      update: pushAttachmentUpdate,
    })
  }

  const handleSend = () => {
    const trimmed = text.trim()
    // 空文本 + 无就绪附件 → 不发送;空文本 + 有就绪附件 → 允许(协议 §4.1)
    if (!trimmed && readyCount === 0) return
    if (isStreaming) {
      // 流式进行中:排队为待发消息(附件随文字一起进入待发队列)
      if (readyRefs.length > 0) onQueueSend?.(trimmed, readyRefs)
      else onQueueSend?.(trimmed)
      clearTextarea()
      onAttachmentsChange?.([])
      return
    }
    // 单条队列:已有待发消息时,先通过悬浮条「立即执行/取消」处理
    if (pendingMessage) return
    // 无就绪附件时保持单参调用(旧测试依赖 toHaveBeenCalledWith('Hello world') 形状)
    if (readyRefs.length > 0) onSend(trimmed, readyRefs)
    else onSend(trimmed)
    clearTextarea()
    onAttachmentsChange?.([])
  }

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault()
    handleSend()
  }

  const handleKeyDown = (e: KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  const handleInput = () => {
    const el = textareaRef.current
    if (el) {
      el.style.height = 'auto'
      el.style.height = Math.min(el.scrollHeight, 120) + 'px'
    }
  }

  const pendingState = pendingHeld ? 'held' : 'auto'
  const sendDisabled =
    disabled ||
    !!pendingMessage ||
    !canSendMessage(text, readyCount) ||
    hasBlockingAttachments

  return (
    <div className="input-box">
      {pendingMessage && (
        <div
          className="pending-float"
          data-testid="pending-message"
          data-state={pendingState}
          role="status"
          aria-live="polite"
        >
          <div className="pending-float-head">
            <div className="pending-float-head-row">
              <span className="pending-float-icon-chip" aria-hidden="true">
                {pendingHeld ? (
                  <AlertCircle size={14} data-icon="AlertCircle" />
                ) : (
                  <Clock size={14} data-icon="Clock" />
                )}
              </span>
              <span className="pending-float-title">{t('chat.pendingTitle')}</span>
            </div>
            <div className="pending-float-hint">
              {pendingHeld ? t('chat.pendingHeldHint') : t('chat.pendingHint')}
            </div>
          </div>
          <div className="pending-float-text">{pendingMessage}</div>
          {pendingAttachmentCount ? (
            /* 待发消息携带的图片数徽标(样式见 chat.css .pending-float-attach-badge) */
            <span className="pending-float-attach-badge" data-testid="pending-attach-badge">
              {t('chat.attachments.imagesCount', { n: pendingAttachmentCount })}
            </span>
          ) : null}
          <div className="pending-float-actions">
            <button
              type="button"
              className="btn btn-pill btn-ghost"
              data-testid="pending-cancel"
              onClick={onCancelPending}
            >
              <X size={12} />
              {t('common.cancel')}
            </button>
            <button
              type="button"
              className="btn btn-pill btn-primary"
              data-testid="pending-send-now"
              onClick={onSendPendingNow}
            >
              <Zap size={12} />
              {t('chat.sendNow')}
            </button>
          </div>
        </div>
      )}
      {toolbar && <div className="input-toolbar">{toolbar}</div>}
      {hint && (
        /* 附件添加管道的临时行内提示(2 秒自动消失;样式见 chat.css) */
        <div className="attachment-error-hint" role="status">{t(hint)}</div>
      )}
      {list.length > 0 && (
        <div className="attachments-strip" data-testid="attachments-strip">
          {list.map(att => (
            <AttachmentThumb
              key={att.localId}
              att={att}
              onRemove={() => handleRemove(att.localId)}
              onRetry={() => handleRetry(att.localId)}
            />
          ))}
        </div>
      )}
      <form onSubmit={handleSubmit}>
        {onAttachmentsChange && (
          <>
            <button
              type="button"
              className="attach-btn"
              aria-label={t('chat.attachments.addImage')}
              title={t('chat.attachments.addImage')}
              disabled={disabled}
              onClick={() => fileInputRef.current?.click()}
            >
              <ImagePlus size={16} />
            </button>
            <input
              ref={fileInputRef}
              type="file"
              accept="image/*"
              multiple
              hidden
              tabIndex={-1}
              aria-hidden="true"
              data-testid="attach-input"
              onChange={handleFileChosen}
            />
          </>
        )}
        <textarea
          ref={textareaRef}
          placeholder={t('chat.inputPlaceholder')}
          value={text}
          onChange={e => setText(e.target.value)}
          onKeyDown={handleKeyDown}
          onInput={handleInput}
          disabled={disabled}
          rows={1}
        />
        {isStreaming && (
          <button
            type="button"
            className="stop-send-btn"
            data-testid="stop-generation"
            title={t('chat.stopTitle')}
            aria-label={t('chat.stopTitle')}
            onClick={onStop}
          >
            <Square size={16} />
            {t('chat.stop')}
          </button>
        )}
        <button
          type="submit"
          disabled={sendDisabled}
          title={
            pendingMessage
              ? t('chat.pendingBlockTitle')
              : hasBlockingAttachments
                ? t('chat.attachments.blockingHint')
                : undefined
          }
        >
          <Send size={16} />
          {t('chat.send')}
        </button>
      </form>
    </div>
  )
}

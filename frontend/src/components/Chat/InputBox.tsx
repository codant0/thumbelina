import { useState, useRef, type FormEvent, type KeyboardEvent, type ReactNode } from 'react'
import { AlertCircle, Clock, Send, Square, X, Zap } from 'lucide-react'
import { useTranslation } from '../../i18n'

interface InputBoxProps {
  onSend: (message: string) => void
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
  onQueueSend?: (message: string) => void
  /** Send the queued message now (stops the running reply first when needed). */
  onSendPendingNow?: () => void
  onCancelPending?: () => void
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
}: InputBoxProps) {
  const [text, setText] = useState('')
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const { t } = useTranslation()

  const clearTextarea = () => {
    setText('')
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto'
    }
  }

  const handleSend = () => {
    const trimmed = text.trim()
    if (!trimmed) return
    if (isStreaming) {
      // 流式进行中:排队为待发消息(悬浮条展示,默认当前回复结束后自动发送)
      onQueueSend?.(trimmed)
      clearTextarea()
      return
    }
    // 单条队列:已有待发消息时,先通过悬浮条「立即执行/取消」处理
    if (pendingMessage) return
    onSend(trimmed)
    clearTextarea()
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
          <div className="pending-float-accent" aria-hidden="true" />
          <div className="pending-float-head">
            <span className="pending-float-icon-chip" aria-hidden="true">
              {pendingHeld ? (
                <AlertCircle size={14} data-icon="AlertCircle" />
              ) : (
                <Clock size={14} data-icon="Clock" />
              )}
            </span>
            <span className="pending-float-title">{t('chat.pendingTitle')}</span>
            <span className="pending-float-sep" aria-hidden="true">·</span>
            <span className="pending-float-hint">
              {pendingHeld ? t('chat.pendingHeldHint') : t('chat.pendingHint')}
            </span>
          </div>
          <div className="pending-float-text">{pendingMessage}</div>
          <div className="pending-float-actions">
            <button
              type="button"
              className="btn btn-sm btn-ghost"
              data-testid="pending-cancel"
              onClick={onCancelPending}
            >
              <X size={12} />
              {t('common.cancel')}
            </button>
            <button
              type="button"
              className="btn btn-sm btn-primary"
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
      <form onSubmit={handleSubmit}>
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
          disabled={disabled || !!pendingMessage}
          title={pendingMessage ? t('chat.pendingBlockTitle') : undefined}
        >
          <Send size={16} />
          {t('chat.send')}
        </button>
      </form>
    </div>
  )
}
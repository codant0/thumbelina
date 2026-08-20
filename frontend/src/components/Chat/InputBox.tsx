import { useState, useRef, type FormEvent, type KeyboardEvent, type ReactNode } from 'react'
import { Send, Square } from 'lucide-react'
import { useTranslation } from '../../i18n'

interface InputBoxProps {
  onSend: (message: string) => void
  disabled?: boolean
  toolbar?: ReactNode
  /** While the model is replying, the send button morphs into a stop button. */
  isStreaming?: boolean
  /** Called when the user stops generation (only used while isStreaming). */
  onStop?: () => void
}

export function InputBox({ onSend, disabled, toolbar, isStreaming, onStop }: InputBoxProps) {
  const [text, setText] = useState('')
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const { t } = useTranslation()

  const handleSend = () => {
    if (isStreaming) return
    const trimmed = text.trim()
    if (!trimmed) return
    onSend(trimmed)
    setText('')
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto'
    }
  }

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault()
    handleSend()
  }

  const handleKeyDown = (e: KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      if (!isStreaming) handleSend()
    }
  }

  const handleInput = () => {
    const el = textareaRef.current
    if (el) {
      el.style.height = 'auto'
      el.style.height = Math.min(el.scrollHeight, 120) + 'px'
    }
  }

  return (
    <div className="input-box">
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
        {isStreaming ? (
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
        ) : (
          <button type="submit" disabled={disabled}>
            <Send size={16} />
            {t('chat.send')}
          </button>
        )}
      </form>
    </div>
  )
}

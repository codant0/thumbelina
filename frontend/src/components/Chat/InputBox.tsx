import { useState, type FormEvent, type KeyboardEvent } from 'react'

interface InputBoxProps {
  onSend: (message: string) => void
  disabled?: boolean
}

export function InputBox({ onSend, disabled }: InputBoxProps) {
  const [text, setText] = useState('')

  const handleSend = () => {
    const trimmed = text.trim()
    if (!trimmed) return
    onSend(trimmed)
    setText('')
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

  return (
    <form onSubmit={handleSubmit}>
      <input
        type="text"
        placeholder="输入消息..."
        value={text}
        onChange={e => setText(e.target.value)}
        onKeyDown={handleKeyDown}
        disabled={disabled}
      />
      <button type="submit" disabled={disabled}>
        发送
      </button>
    </form>
  )
}

import { useEffect, useRef, useState } from 'react'
import { CheckCircle, AlertCircle } from 'lucide-react'

interface ToastProps {
  message: string
  isError?: boolean
  duration?: number
  onClose: () => void
}

export function Toast({ message, isError = false, duration = 2500, onClose }: ToastProps) {
  const [visible, setVisible] = useState(false)
  const enterTimerRef = useRef<number | null>(null)
  const leaveTimerRef = useRef<number | null>(null)
  const closeTimerRef = useRef<number | null>(null)

  useEffect(() => {
    if (!message) return

    // Clear any existing timers before showing a new toast.
    if (enterTimerRef.current) window.clearTimeout(enterTimerRef.current)
    if (leaveTimerRef.current) window.clearTimeout(leaveTimerRef.current)
    if (closeTimerRef.current) window.clearTimeout(closeTimerRef.current)

    // Trigger enter animation on the next frame.
    enterTimerRef.current = window.setTimeout(() => setVisible(true), 10)

    // Start leave animation after the display duration.
    leaveTimerRef.current = window.setTimeout(() => setVisible(false), duration)

    return () => {
      if (enterTimerRef.current) window.clearTimeout(enterTimerRef.current)
      if (leaveTimerRef.current) window.clearTimeout(leaveTimerRef.current)
    }
  }, [message, duration])

  useEffect(() => {
    if (!message || visible) return

    // Wait for the leave transition to finish before notifying the parent.
    closeTimerRef.current = window.setTimeout(() => onClose(), 300)

    return () => {
      if (closeTimerRef.current) window.clearTimeout(closeTimerRef.current)
    }
  }, [message, visible, onClose])

  if (!message) return null

  return (
    <div
      className={`toast ${visible ? 'visible' : ''} ${isError ? 'toast-error' : 'toast-success'}`}
      role="status"
      aria-live="polite"
    >
      {isError ? <AlertCircle size={16} /> : <CheckCircle size={16} />}
      {message}
    </div>
  )
}

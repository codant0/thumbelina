import { useCallback, useRef, useState } from 'react'
import { writeToClipboard } from '../lib/codeUtils'

/** Shared "copy → brief done feedback" behavior for all copy affordances. */
export function useCopy() {
  const [copied, setCopied] = useState(false)
  const timerRef = useRef<ReturnType<typeof setTimeout>>(undefined)
  const copy = useCallback(async (text: string) => {
    const ok = await writeToClipboard(text)
    if (ok) {
      setCopied(true)
      clearTimeout(timerRef.current)
      timerRef.current = setTimeout(() => setCopied(false), 1500)
    }
  }, [])
  return { copied, copy }
}

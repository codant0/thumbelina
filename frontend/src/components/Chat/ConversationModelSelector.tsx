import { useEffect, useMemo, useRef, useState } from 'react'
import { Cpu, Check, ChevronDown } from 'lucide-react'
import type { LLMEndpoint } from '../../api/llmConfig'
import { fetchEndpoints } from '../../api/llmConfig'

interface ConversationModelSelectorProps {
  conversationId?: string
  /** endpoint_id currently stored on the conversation (null = default). */
  selectedEndpointId?: string | null
  onChange: (endpointId: string | null) => void
}

export function ConversationModelSelector({
  conversationId,
  selectedEndpointId,
  onChange,
}: ConversationModelSelectorProps) {
  const [endpoints, setEndpoints] = useState<LLMEndpoint[]>([])
  const [open, setOpen] = useState(false)
  const [loading, setLoading] = useState(true)
  const wrapRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    let cancelled = false
    fetchEndpoints()
      .then(data => {
        if (!cancelled) setEndpoints(Array.isArray(data) ? data : [])
      })
      .catch(() => {
        if (!cancelled) setEndpoints([])
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    if (!open) return
    const handler = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [open])

  const selected = useMemo(
    () => endpoints.find(e => e.id === selectedEndpointId) ?? null,
    [endpoints, selectedEndpointId],
  )

  const label = loading
    ? 'Loading models…'
    : selected
      ? selected.name
      : 'Default model'

  if (!conversationId) return null

  return (
    <div className="conv-model-selector" ref={wrapRef} data-testid="conv-model-selector">
      <button
        type="button"
        className="conv-model-selector__trigger"
        data-testid="conv-model-trigger"
        title="Choose model for this conversation"
        onClick={() => setOpen(o => !o)}
      >
        <Cpu size={14} />
        <span className="conv-model-selector__label">{label}</span>
        <ChevronDown size={14} />
      </button>
      {open && (
        <ul className="conv-model-selector__menu" role="listbox" data-testid="conv-model-menu">
          <li
            role="option"
            aria-selected={selectedEndpointId == null}
            className={`conv-model-selector__option${selectedEndpointId == null ? ' selected' : ''}`}
            data-testid="conv-model-default"
            onClick={() => {
              onChange(null)
              setOpen(false)
            }}
          >
            <span className="conv-model-selector__name">Default model</span>
            {selectedEndpointId == null && <Check size={14} />}
          </li>
          {endpoints.map(ep => (
            <li
              key={ep.id}
              role="option"
              aria-selected={selected?.id === ep.id}
              className={`conv-model-selector__option${selected?.id === ep.id ? ' selected' : ''}`}
              data-testid={`conv-model-option-${ep.id}`}
              onClick={() => {
                onChange(ep.id)
                setOpen(false)
              }}
            >
              <span className="conv-model-selector__name">{ep.name}</span>
              <span className="conv-model-selector__meta">{ep.model || ep.provider}</span>
              {selected?.id === ep.id && <Check size={14} />}
            </li>
          ))}
          {endpoints.length === 0 && !loading && (
            <li className="conv-model-selector__empty">No models configured. Add one in Settings.</li>
          )}
        </ul>
      )}
    </div>
  )
}

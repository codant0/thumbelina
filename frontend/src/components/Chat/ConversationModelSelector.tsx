import { useEffect, useMemo, useRef, useState } from 'react'
import { Cpu, Check, ChevronDown } from 'lucide-react'
import type { LLMEndpoint } from '../../api/llmConfig'
import { fetchEndpoints } from '../../api/llmConfig'
import { useTranslation } from '../../i18n'

const PROVIDER_LABEL: Record<string, string> = {
  openai: 'OpenAI',
  anthropic: 'Anthropic',
  ollama: 'Ollama',
}

interface ConversationModelSelectorProps {
  conversationId?: string
  /** endpoint_id currently stored on the conversation (null = default). */
  selectedEndpointId?: string | null
  /** model currently stored on the conversation (null = endpoint's active). */
  selectedModel?: string | null
  onChange: (endpointId: string | null, model: string | null) => void
}

export function ConversationModelSelector({
  conversationId,
  selectedEndpointId,
  selectedModel,
  onChange,
}: ConversationModelSelectorProps) {
  const [endpoints, setEndpoints] = useState<LLMEndpoint[]>([])
  const [open, setOpen] = useState(false)
  const [loading, setLoading] = useState(true)
  const wrapRef = useRef<HTMLDivElement>(null)
  const { t } = useTranslation()

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

  // Each endpoint with at least one model is a group.
  const groups = useMemo(() =>
    endpoints.filter(ep => ep.models.length > 0),
    [endpoints],
  )

  const isDefaultSelected = selectedEndpointId == null
  const label = loading
    ? t('endpoint.loading')
    : isDefaultSelected
      ? t('chat.defaultModel')
      : selectedModel || t('chat.defaultModel')

  if (!conversationId) return null

  return (
    <div className="conv-model-selector" ref={wrapRef} data-testid="conv-model-selector">
      <button
        type="button"
        className="conv-model-selector__trigger"
        data-testid="conv-model-trigger"
        title={t('chat.chooseModel')}
        onClick={() => setOpen(o => !o)}
      >
        <Cpu size={14} />
        <span className="conv-model-selector__label">{label}</span>
        <ChevronDown size={14} />
      </button>
      {open && (
        <ul className="conv-model-selector__menu" role="listbox" data-testid="conv-model-menu">
          {/* Default model option */}
          <li
            role="option"
            aria-selected={isDefaultSelected}
            className={`conv-model-selector__option${isDefaultSelected ? ' selected' : ''}`}
            data-testid="conv-model-default"
            onClick={() => {
              onChange(null, null)
              setOpen(false)
            }}
          >
            <span className="conv-model-selector__name">{t('chat.defaultModel')}</span>
            {isDefaultSelected && <Check size={14} />}
          </li>

          {/* Endpoint groups — each endpoint is its own group */}
          {groups.map(ep => (
            <li key={ep.id} className="conv-model-selector__group" data-testid={`conv-model-group-${ep.id}`}>
              <div className="conv-model-selector__group-header">
                <span className="conv-model-selector__group-name">{ep.name}</span>
                <span className="badge badge-neutral conv-model-selector__group-provider">
                  {PROVIDER_LABEL[ep.provider] || ep.provider}
                </span>
              </div>
              {ep.models.map(m => {
                const selected = selectedEndpointId === ep.id && selectedModel === m
                return (
                  <div
                    key={`${ep.id}-${m}`}
                    role="option"
                    aria-selected={selected}
                    className={`conv-model-selector__option${selected ? ' selected' : ''}`}
                    data-testid={`conv-model-option-${ep.id}-${m}`}
                    onClick={() => {
                      onChange(ep.id, m)
                      setOpen(false)
                    }}
                  >
                    <span className="conv-model-selector__name">{m}</span>
                    {selected && <Check size={14} />}
                  </div>
                )
              })}
            </li>
          ))}

          {endpoints.length === 0 && !loading && (
            <li className="conv-model-selector__empty">{t('chat.noModels')}</li>
          )}
        </ul>
      )}
    </div>
  )
}

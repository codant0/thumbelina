import { useEffect, useRef, useState } from 'react'
import { VenetianMask, Check, ChevronUp } from 'lucide-react'
import { useTranslation } from '../../i18n'
import * as conversationsApi from '../../api/conversations'

interface RoleSelectorProps {
  conversationId?: string
  selectedRole?: string | null
  onChange: (role: string | null) => void
}

export function RoleSelector({ conversationId, selectedRole, onChange }: RoleSelectorProps) {
  const [roles, setRoles] = useState<string[]>([])
  const [open, setOpen] = useState(false)
  const [loading, setLoading] = useState(true)
  const wrapRef = useRef<HTMLDivElement>(null)
  const { t } = useTranslation()

  useEffect(() => {
    let cancelled = false
    conversationsApi
      .listRoles()
      .then(data => {
        if (!cancelled) setRoles(Array.isArray(data) ? data : [])
      })
      .catch(() => {
        if (!cancelled) setRoles([])
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
    const onPointerDown = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onPointerDown)
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('mousedown', onPointerDown)
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [open])

  if (!conversationId) return null

  const active = selectedRole != null && roles.includes(selectedRole)
  const label = loading ? t('common.loading') : selectedRole ?? t('chat.defaultRole')

  return (
    <div className="role-float" ref={wrapRef} data-testid="role-selector">
      <button
        type="button"
        className={`role-float__trigger${active ? ' is-active' : ''}`}
        data-testid="role-selector-trigger"
        aria-haspopup="listbox"
        aria-expanded={open}
        title={t('chat.chooseRole')}
        onClick={() => setOpen(o => !o)}
      >
        <VenetianMask size={14} />
        <span className="role-float__label">{label}</span>
        <ChevronUp size={13} className={`role-float__caret${open ? ' is-open' : ''}`} />
      </button>

      {open && (
        <div
          className="role-float__panel"
          role="listbox"
          data-testid="role-selector-menu"
          data-density={roles.length < 4 ? 'compact' : 'scrollable'}
        >
          <div className="role-float__heading">{t('chat.chooseRole')}</div>

          <button
            type="button"
            role="option"
            aria-selected={selectedRole == null}
            className={`role-float__option${selectedRole == null ? ' is-selected' : ''}`}
            data-testid="role-option-default"
            onClick={() => {
              onChange(null)
              setOpen(false)
            }}
          >
            <span className="role-float__option-body">
              <span className="role-float__name">{t('chat.defaultRole')}</span>
            </span>
            {selectedRole == null && <Check size={14} className="role-float__check" />}
          </button>

          {roles.map(role => {
            const selected = selectedRole === role
            return (
              <button
                key={role}
                type="button"
                role="option"
                aria-selected={selected}
                className={`role-float__option${selected ? ' is-selected' : ''}`}
                data-testid={`role-option-${role}`}
                onClick={() => {
                  onChange(role)
                  setOpen(false)
                }}
              >
                <span className="role-float__option-body">
                  <span className="role-float__name">{role}</span>
                </span>
                {selected && <Check size={14} className="role-float__check" />}
              </button>
            )
          })}

          {roles.length === 0 && !loading && (
            <div className="role-float__empty">{t('chat.noRoles')}</div>
          )}
        </div>
      )}
    </div>
  )
}

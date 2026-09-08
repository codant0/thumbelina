import { useEffect, useRef, useState } from 'react'
import { ShieldCheck, ChevronUp, AlertTriangle } from 'lucide-react'
import { useTranslation } from '../../i18n'
import * as conversationsApi from '../../api/conversations'
import type { PermissionMode } from '../../types/chat'

/** spec §3.1: 五档严格递增 */
const ALL_MODES: PermissionMode[] = [
  'read_only',
  'workspace_write',
  'global_write',
  'full_access',
  'auto',
]

/** chat 会话(spec §3.1)隐藏 workspace_write(无工作区语义);coder 五项全显 */
const CHAT_VISIBLE_MODES: PermissionMode[] = ['read_only', 'global_write', 'full_access', 'auto']

interface PermissionSelectorProps {
  conversationId: string | null
  mode: PermissionMode
  conversationType: 'chat' | 'coder'
  onChange: (m: PermissionMode) => void
  disabled?: boolean
}

/**
 * 会话权限模式选择器(spec §3.1):下拉按钮 + 面板,挂入 ChatWindow 工具栏。
 *
 * 可见集:
 * - chat: 隐藏 workspace_write(spec §3.1: 无工作区 → 等效只读 + global_write 起即整盘)
 * - coder: 五项全显
 *
 * 历史值不在可见集时(典型场景: chat 会话原本是 coder 创建后切回的, 残留
 * workspace_write): 仍展示当前值并附 `permission.selector.hiddenModeHint` 提示,
 * 用户切换到可见项后该提示消失。
 *
 * 与 ThinkingSelector/RoleSelector 不同: 本组件在用户选择新模式时**就地
 * 调用 setConversationPermission 持久化**, 同时通过 onChange 把决策交
 * 给父组件更新 Conversation 状态(避免 ChatWindow 在乐观更新时与后端
 * PUT 返还不一致)。父组件只需传入 onChange 即接收新值, 不必自管 PUT。
 */
export function PermissionSelector({
  conversationId,
  mode,
  conversationType,
  onChange,
  disabled,
}: PermissionSelectorProps) {
  const [open, setOpen] = useState(false)
  const [saving, setSaving] = useState(false)
  const wrapRef = useRef<HTMLDivElement>(null)
  const { t } = useTranslation()

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

  const visible = conversationType === 'chat' ? CHAT_VISIBLE_MODES : ALL_MODES
  const modeIsHidden = !visible.includes(mode)
  const showHiddenHint = modeIsHidden && open
  const labelKey = `permission.mode.${modeCamel(mode)}`
  const label = t(labelKey as `permission.mode.${string}`)

  // 选择新模式: 立即持久化(后端 400 非法值, 但前端已做可见集过滤, 实
  // 践中只可能是网络/服务故障), 同时通知父组件。失败时不关闭面板 ——
  // 用户重选或取消。父组件由 ChatWindow 接管 onChange 更新本地 conversation。
  const handleSelect = async (next: PermissionMode) => {
    if (next === mode) {
      setOpen(false)
      return
    }
    setSaving(true)
    try {
      await conversationsApi.setConversationPermission(conversationId, next)
      onChange(next)
      setOpen(false)
    } catch {
      // 失败:保持面板打开以便重试; 触发器不显示错误态(简洁降级)。
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="permission-float" ref={wrapRef} data-testid="permission-selector">
      <button
        type="button"
        className={`permission-float__trigger permission-float__trigger--${mode}${modeIsHidden ? ' is-hidden' : ''}`}
        data-testid="permission-selector-trigger"
        aria-haspopup="listbox"
        aria-expanded={open}
        disabled={disabled || saving}
        title={t('permission.selector.title')}
        onClick={() => setOpen(o => !o)}
      >
        <ShieldCheck size={14} aria-hidden="true" />
        <span className="permission-float__label">{label}</span>
        {modeIsHidden && <AlertTriangle size={11} className="permission-float__hidden-flag" aria-hidden="true" />}
        <ChevronUp size={13} className={`permission-float__caret${open ? ' is-open' : ''}`} />
      </button>

      {open && (
        <div
          className="permission-float__panel"
          role="listbox"
          data-testid="permission-selector-menu"
          aria-label={t('permission.selector.title')}
        >
          <div className="permission-float__heading">{t('permission.selector.label')}</div>
          {visible.map(m => {
            const selected = !modeIsHidden && m === mode
            return (
              <button
                key={m}
                type="button"
                role="option"
                aria-selected={selected}
                disabled={saving}
                data-testid={`permission-option-${m}`}
                className={`permission-float__option permission-float__option--${m}${selected ? ' is-selected' : ''}`}
                onClick={() => { void handleSelect(m) }}
              >
                <span className="permission-float__option-body">
                  <span className="permission-float__name">{t(`permission.mode.${modeCamel(m)}`)}</span>
                  <span className="permission-float__desc">{t(`permission.mode.${modeCamel(m)}Desc`)}</span>
                </span>
              </button>
            )
          })}
          {/* 历史值不在可见集(例如 chat 上残留 workspace_write): 仍展示并标注"隐藏"提示,
              点击隐藏项外的任何一项后该提示消失; 此处用单独 hint 行而非把它混入列表,
              避免误选。当前值不可点击 —— 选项列表只暴露可见集。 */}
          {showHiddenHint && (
            <div className="permission-float__hint" data-testid="permission-selector-hidden-hint">
              {t('permission.selector.hiddenModeHint')}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

/** snake_case `workspace_write` → camelCase `workspaceWrite` 以匹配 i18n key。 */
function modeCamel(m: PermissionMode): string {
  const parts = m.split('_')
  return parts.map((p, i) => (i === 0 ? p : p.charAt(0).toUpperCase() + p.slice(1))).join('')
}
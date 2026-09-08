import { ShieldCheck, AlertTriangle, ShieldAlert } from 'lucide-react'
import { useTranslation } from '../../i18n'
import { StatusBarItemView } from './StatusBarItem'
import type { StatusBarState } from './types'
import type { PermissionMode } from '../../types/chat'

/** spec §6.1: 状态栏 PermissionBadge 必须常显, 不进 useStatusBarConfig 开关。 */
interface PermissionBadgeProps {
  mode: PermissionMode
}

/** 五档 → 状态点映射(spec §6.1): 只读/工作区写入/全区写入→ok, 完全访问→warning, 自动→error。 */
function modeState(mode: PermissionMode): StatusBarState {
  switch (mode) {
    case 'read_only':
    case 'workspace_write':
    case 'global_write':
      return 'ok'
    case 'full_access':
      return 'warning'
    case 'auto':
      return 'error'
    default:
      return 'idle'
  }
}

/** 模式 → 图标: read_only/workspace_write/global_write 用盾; full_access/auto 用警示盾 */
function modeIcon(mode: PermissionMode) {
  if (mode === 'full_access' || mode === 'auto') {
    return mode === 'auto' ? <ShieldAlert size={13} aria-hidden="true" /> : <AlertTriangle size={13} aria-hidden="true" />
  }
  return <ShieldCheck size={13} aria-hidden="true" />
}

/** snake_case `workspace_write` → camelCase `workspaceWrite` 以匹配 i18n key。 */
function modeCamel(m: PermissionMode): string {
  const parts = m.split('_')
  return parts.map((p, i) => (i === 0 ? p : p.charAt(0).toUpperCase() + p.slice(1))).join('')
}

/**
 * 状态栏 PermissionBadge(spec §6.1): 当前会话权限模式, 常显(不进
 * useStatusBarConfig 开关)。配色映射:
 *   read_only / workspace_write / global_write → ok(蓝)
 *   full_access → warning(黄)
 *   auto → error(红)
 */
export function PermissionBadge({ mode }: PermissionBadgeProps) {
  const { t } = useTranslation()
  const label = t(`permission.mode.${modeCamel(mode)}`)
  const title = t(`permission.badge.title.${modeCamel(mode)}`)
  return (
    <StatusBarItemView
      icon={modeIcon(mode)}
      state={modeState(mode)}
      label={label}
      title={title}
    />
  )
}
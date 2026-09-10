import { ShieldCheck, AlertTriangle, ShieldAlert } from 'lucide-react'
import { useTranslation } from '../../i18n'
import { StatusBarItemView } from './StatusBarItem'
import type { PermissionMode } from '../../types/chat'
import {
  modeCamel,
  permissionBadgeState,
  permissionIconKind,
} from '../../types/chat'

/** spec §6.1: 状态栏 PermissionBadge 必须常显, 不进 useStatusBarConfig 开关。 */
interface PermissionBadgeProps {
  mode: PermissionMode
}

/** 模式 → 图标(spec §6.1 + 用户反馈: 全区写入标黄, 完全访问标红)。
 * 共享映射在 types/chat.ts:permissionIconKind 维护。 */
function renderBadgeIcon(mode: PermissionMode) {
  switch (permissionIconKind(mode)) {
    case 'warning':
      return <AlertTriangle size={13} aria-hidden="true" />
    case 'shield-alert':
      return <ShieldAlert size={13} aria-hidden="true" />
    case 'shield':
    default:
      return <ShieldCheck size={13} aria-hidden="true" />
  }
}

/**
 * 状态栏 PermissionBadge(spec §6.1): 当前会话权限模式, 常显(不进
 * useStatusBarConfig 开关)。配色:
 *   read_only / workspace_write → ok(蓝)
 *   global_write              → warning(黄)
 *   full_access / auto        → error(红)
 */
export function PermissionBadge({ mode }: PermissionBadgeProps) {
  const { t } = useTranslation()
  const label = t(`permission.mode.${modeCamel(mode)}`)
  // 详细解释(spec §6.1): ARIA/hover title 显示完整说明
  const title = t(`permission.mode.tooltip.${modeCamel(mode)}`)
  return (
    <StatusBarItemView
      icon={renderBadgeIcon(mode)}
      state={permissionBadgeState(mode)}
      label={label}
      title={title}
    />
  )
}
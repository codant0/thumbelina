import { Eye, FolderLock, Globe, Unlock, Zap } from 'lucide-react'
import { useTranslation } from '../../i18n'
import { StatusBarItemView } from './StatusBarItem'
import type { PermissionMode } from '../../types/chat'
import {
  modeCamel,
  permissionBadgeState,
  permissionIconKind,
  type PermissionIconKind,
} from '../../types/chat'

/** spec §6.1: 状态栏 PermissionBadge 必须常显, 不进 useStatusBarConfig 开关。 */
interface PermissionBadgeProps {
  mode: PermissionMode
}

/** PermissionIconKind 字符串 → lucide-react 元素。5 档对应 5 个不同的
 * 视觉图标,避免用户混淆(状态色只覆盖状态,图标覆盖语义)。 */
function renderBadgeIcon(kind: PermissionIconKind) {
  switch (kind) {
    case 'eye':
      return <Eye size={13} aria-hidden="true" />
    case 'folder-lock':
      return <FolderLock size={13} aria-hidden="true" />
    case 'globe':
      return <Globe size={13} aria-hidden="true" />
    case 'unlock':
      return <Unlock size={13} aria-hidden="true" />
    case 'zap':
      return <Zap size={13} aria-hidden="true" />
    default:
      return <Eye size={13} aria-hidden="true" />
  }
}

/**
 * 状态栏 PermissionBadge(spec §6.1): 当前会话权限模式, 常显(不进
 * useStatusBarConfig 开关)。配色:
 *   read_only    → ok(绿)
 *   global_write → warning(黄)
 *   full_access  → error(红)
 * workspace_write / auto 使用 'idle' -- 图标本身的语义(FolderLock/Zap)
 * 已足以区分,无需叠加状态点圆点 + 配色。
 */
export function PermissionBadge({ mode }: PermissionBadgeProps) {
  const { t } = useTranslation()
  const label = t(`permission.mode.${modeCamel(mode)}`)
  // 详细解释(spec §6.1): ARIA/hover title 显示完整说明
  const title = t(`permission.mode.tooltip.${modeCamel(mode)}`)
  return (
    <StatusBarItemView
      icon={renderBadgeIcon(permissionIconKind(mode))}
      state={permissionBadgeState(mode)}
      label={label}
      title={title}
    />
  )
}
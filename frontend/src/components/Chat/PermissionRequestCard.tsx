import { useMemo, useState } from 'react'
import { AlertOctagon, Check, ChevronDown, ChevronUp, ShieldOff, Terminal } from 'lucide-react'
import { useTranslation } from '../../i18n'
import type { PermissionCallPayload, PermissionDecision, PermissionRequestPayload } from '../../types/chat'

interface PermissionRequestCardProps {
  request: PermissionRequestPayload
  onDecide: (decisions: PermissionDecision[]) => void
}

/** 后端 reason `rule.sudo` / `dangerous.rm_root` / `user_denied` → i18n key
 *  `permission.rule.rule_sudo` / `permission.rule.dangerous_rm_root` /
 *  `permission.rule.user_denied`。点号替换为下划线。 */
function reasonToI18nKey(reason: string): string {
  return `permission.rule.${reason.replace(/\./g, '_')}`
}

/** 命令预览折叠阈值:超过此字符数显示折叠/展开按钮(spec §4.6)。 */
const COMMAND_PREVIEW_COLLAPSE_THRESHOLD = 500

/** 格式化命令预览: 多行逐行渲染, 等宽字体, 固定高度滚动区(spec §4.6)。 */
function CommandPreview({ text }: { text: string }) {
  const { t } = useTranslation()
  const collapsed = text.length > COMMAND_PREVIEW_COLLAPSE_THRESHOLD
  const [expanded, setExpanded] = useState(!collapsed)
  const display = useMemo(() => {
    if (expanded) return text
    return `${text.slice(0, COMMAND_PREVIEW_COLLAPSE_THRESHOLD)}…`
  }, [text, expanded])
  return (
    <div className="permission-call__command" data-testid="permission-call-command">
      <div className="permission-call__command-header">
        <Terminal size={12} aria-hidden="true" />
        <span>{t('permission.card.commandPreview')}</span>
      </div>
      <pre className="permission-call__command-body" data-expanded={expanded}>
        {display}
      </pre>
      {collapsed && (
        <button
          type="button"
          className="permission-call__expand"
          data-testid="permission-call-expand"
          onClick={() => setExpanded(o => !o)}
          aria-expanded={expanded}
        >
          {expanded ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
          {expanded ? t('common.collapse') : t('common.expand')}
        </button>
      )}
    </div>
  )
}

/** 单个待授权调用的渲染: 工具名 + 规则 i18n 标签 + run_shell 命令预览。 */
function PermissionCallItem({ call }: { call: PermissionCallPayload }) {
  const { t } = useTranslation()
  const ruleLabel = t(reasonToI18nKey(call.reason) as `permission.rule.${string}`)
  const args = call.args as Record<string, unknown>
  const commandText = typeof call.args_display === 'string'
    ? call.args_display
    : (typeof args.command === 'string' ? args.command : JSON.stringify(args))
  return (
    <li className="permission-call" data-testid="permission-call-item" data-call-id={call.call_id}>
      <div className="permission-call__header">
        <span className="permission-call__name">{call.name}</span>
        <span className="permission-call__risk">{t('permission.card.riskBadge')}</span>
      </div>
      <div className="permission-call__rule">
        <span className="permission-call__rule-label">{t('permission.card.ruleLabel')}:</span>
        <span className="permission-call__rule-value">{ruleLabel}</span>
      </div>
      <CommandPreview text={commandText} />
    </li>
  )
}

/**
 * 审批卡(spec §4.6/§5.4): 红色主题, 一次性挂载在消息流末尾等待用户决定。
 *
 * - 按钮: 全部批准 / 全部拒绝 / 逐项批准(后者同时把其他项置为拒绝)
 * - 点击即禁用: 防双击(后端 broker 接收首次响应即结算, 二次响应会收到
 *   `permission_unknown_request` 错误码)。
 * - 命令预览: 多行逐行 + 等宽 + 固定高度滚动 + >500 字符折叠。
 */
export function PermissionRequestCard({ request, onDecide }: PermissionRequestCardProps) {
  const { t } = useTranslation()
  // 已点击任一按钮 → 整个卡按钮禁用, 防止重复决策触发 unknown_request 错误。
  const [decided, setDecided] = useState(false)

  const approveAll = () => {
    if (decided) return
    setDecided(true)
    onDecide(request.calls.map(c => ({ call_id: c.call_id, approved: true })))
  }
  const denyAll = () => {
    if (decided) return
    setDecided(true)
    onDecide(request.calls.map(c => ({ call_id: c.call_id, approved: false })))
  }
  const approveOne = (callId: string) => {
    if (decided) return
    setDecided(true)
    onDecide(request.calls.map(c => ({ call_id: c.call_id, approved: c.call_id === callId })))
  }

  return (
    <aside
      className="permission-card"
      data-testid="permission-request-card"
      role="dialog"
      aria-label={t('permission.card.title')}
    >
      <header className="permission-card__header">
        <span className="permission-card__icon" aria-hidden="true">
          <AlertOctagon size={14} />
        </span>
        <h4 className="permission-card__title">{t('permission.card.title')}</h4>
        <span className="permission-card__count" data-testid="permission-request-count">
          {t('permission.card.callsCount', { count: request.calls.length })}
        </span>
      </header>
      <ul className="permission-card__calls">
        {request.calls.map(call => (
          <div key={call.call_id} className="permission-card__call-wrap">
            <PermissionCallItem call={call} />
            <div className="permission-card__call-actions">
              <button
                type="button"
                className="btn btn-pill btn-primary"
                data-testid="permission-approve-one"
                disabled={decided}
                onClick={() => approveOne(call.call_id)}
              >
                <Check size={12} />
                {t('permission.card.approveOne')}
              </button>
            </div>
          </div>
        ))}
      </ul>
      <footer className="permission-card__actions">
        <button
          type="button"
          className="btn btn-pill btn-danger"
          data-testid="permission-deny-all"
          disabled={decided}
          onClick={denyAll}
        >
          <ShieldOff size={12} />
          {t('permission.card.denyAll')}
        </button>
        <button
          type="button"
          className="btn btn-pill btn-primary"
          data-testid="permission-approve-all"
          disabled={decided}
          onClick={approveAll}
        >
          <Check size={12} />
          {t('permission.card.approveAll')}
        </button>
      </footer>
      <p className="permission-card__hint" data-testid="permission-card-hint">
        {t('permission.card.waitingHint')}
      </p>
    </aside>
  )
}
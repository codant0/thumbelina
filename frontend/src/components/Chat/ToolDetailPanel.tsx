import { useMemo, useState } from 'react'
import { Check, Copy, Wrench, X } from 'lucide-react'
import { useTranslation } from '../../i18n'
import { useCopy } from '../../hooks/useCopy'
import type { ToolCall } from '../../types/chat'

interface ToolDetailPanelProps {
  /** 被选中的一次工具调用;由 ChatWindow 按 msgId+call_id 从消息树实时解析,
   *  running 期间 upsert 后传入对象随之更新,面板内容实时跟随。 */
  toolCall: ToolCall
  /** 点击右上角 X 或外部遮罩时调用,关闭右侧面板。 */
  onClose: () => void
}

/** 右侧停靠面板:展示单次工具调用的完整详情(工具名 / 状态与耗时 / 参数 / 结果)。
 *
 * 与 SubagentSidePanel 同一套停靠面板交互:X 或点外部遮罩关闭,不支持拖动/多窗口。
 * 参数/结果不在此处二次折叠 —— 面板本身就是「详情」,长文本由滚动区承载。
 */
export function ToolDetailPanel({ toolCall: tc, onClose }: ToolDetailPanelProps) {
  const { t } = useTranslation()
  const { copied, copy } = useCopy()
  const [copiedField, setCopiedField] = useState(false)

  // 与聊天流内芯片同一套状态文案:running/interrupted 用文案,ok/error 带耗时。
  const statusText =
    tc.status === 'running'
      ? t('toolCalls.running')
      : tc.status === 'interrupted'
        ? t('toolCalls.interrupted')
        : `${tc.status === 'error' ? '✗' : '✓'} ${t('toolCalls.durationMs', { ms: tc.durationMs ?? 0 })}`

  // 契约:args 序列化超限时后端下发 {"_truncated_json": "<json 字符串>"}
  // 并置 argsTruncated —— 原样展示截断 JSON,而不是把占位对象当普通参数美化。
  const argsText = useMemo(() => {
    const truncated = tc.argsTruncated
      ? (tc.args as { _truncated_json?: unknown })._truncated_json
      : undefined
    if (typeof truncated === 'string') return truncated
    try {
      return JSON.stringify(tc.args, null, 2)
    } catch {
      return String(tc.args)
    }
  }, [tc.args, tc.argsTruncated])

  const copyAll = async () => {
    await copy([tc.name, argsText, tc.result].filter(Boolean).join('\n'))
    setCopiedField(true)
    window.setTimeout(() => setCopiedField(false), 1500)
  }

  return (
    <aside
      className="tool-detail-side-panel"
      data-testid="tool-detail-side-panel"
      data-status={tc.status}
      aria-label={t('toolCalls.detail')}
    >
      <header className="tool-detail-side-panel__header">
        <span className="tool-detail-side-panel__title">{t('toolCalls.detail')}</span>
        <button
          type="button"
          className={`tool-detail-side-panel__btn${copied ? ' is-done' : ''}`}
          onClick={() => void copyAll()}
          aria-label={t('chat.copy')}
          title={t('chat.copy')}
          data-testid="tool-detail-copy"
        >
          {copiedField ? <Check size={14} /> : <Copy size={14} />}
        </button>
        <button
          type="button"
          className="tool-detail-side-panel__btn tool-detail-side-panel__close"
          onClick={onClose}
          aria-label={t('common.close')}
          title={t('common.close')}
          data-testid="tool-detail-close"
        >
          <X size={14} />
        </button>
      </header>

      <div className="tool-detail-side-panel__body">
        <div className="tool-detail-hero">
          <div className="tool-detail-hero__icon">
            <Wrench size={18} />
          </div>
          <div className="tool-detail-hero__body">
            <div className="tool-detail-hero__title">{tc.name}</div>
            <div className="tool-detail-hero__meta">{statusText}</div>
          </div>
        </div>

        <div className="tool-detail-section">
          <div className="tool-detail-section__label">{t('toolCalls.arguments')}</div>
          <pre className="tool-detail-section__pre">{argsText}</pre>
          {tc.argsTruncated && <div className="tool-call__hint">{t('toolCalls.truncatedHint')}</div>}
        </div>

        {tc.result && (
          <div className="tool-detail-section">
            <div className="tool-detail-section__label">{t('toolCalls.result')}</div>
            <pre className="tool-detail-section__pre">{tc.result}</pre>
            {tc.resultTruncated && <div className="tool-call__hint">{t('toolCalls.truncatedHint')}</div>}
          </div>
        )}
      </div>
    </aside>
  )
}

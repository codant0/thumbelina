import { useState } from 'react'
import { ChevronDown, Wrench, X } from 'lucide-react'
import { useTranslation } from '../../i18n'
import type { Message } from '../../types/chat'
import { formatToolArgs } from './toolCallEvents'

interface ToolCallsPanelProps {
  /** 拥有本轮全部工具调用的消息(ChatWindow 按消息 id 实时解析,upsert 后面板跟随)。 */
  message: Message
  /** 点击右上角 X 或外部遮罩时调用,关闭右侧面板。 */
  onClose: () => void
}

/** 右侧停靠面板:统一展示一条消息(一个 turn)的全部工具调用。
 *
 * 行按时间序排列(即 toolCalls 数组序,即事件到达序),每行显示状态与耗时,
 * 可展开参数/结果;running 行带 spinner 并实时跟随消息更新。
 * 与 SubagentSidePanel 同一套停靠交互:X 或外部遮罩关闭。
 */
export function ToolCallsPanel({ message, onClose }: ToolCallsPanelProps) {
  const { t } = useTranslation()
  const [openIndex, setOpenIndex] = useState<number | null>(null)
  return (
    <aside className="tool-calls-panel" data-testid="tool-calls-panel" aria-label={t('toolCalls.detail')}>
      <header className="tool-calls-panel__header">
        <span className="tool-calls-panel__title">
          <Wrench size={13} />
          <span>{t('toolCalls.button')}</span>
        </span>
        <button
          type="button"
          className="tool-detail-side-panel__btn tool-detail-side-panel__close"
          onClick={onClose}
          aria-label={t('common.close')}
          title={t('common.close')}
          data-testid="tool-calls-panel-close"
        >
          <X size={14} />
        </button>
      </header>
      <div className="tool-calls-panel__body">
        {(message.toolCalls ?? []).map((tc, i) => (
          <div
            key={tc.call_id ?? i}
            className={`tool-calls-row status-${tc.status}`}
            data-testid="tool-calls-row"
          >
            <button
              type="button"
              className="tool-calls-row__header"
              aria-expanded={openIndex === i}
              onClick={() => setOpenIndex(openIndex === i ? null : i)}
            >
              {tc.status === 'running' && <span className="tool-call__spinner" aria-hidden="true" />}
              <span className="tool-calls-row__name">{tc.name}</span>
              <span className="tool-calls-row__meta">
                {tc.status === 'running' && t('toolCalls.running')}
                {tc.status === 'ok' && `✓ ${t('toolCalls.durationMs', { ms: tc.durationMs ?? 0 })}`}
                {tc.status === 'error' && `✗ ${t('toolCalls.durationMs', { ms: tc.durationMs ?? 0 })}`}
                {tc.status === 'interrupted' && t('toolCalls.interrupted')}
              </span>
              <ChevronDown size={13} className={`tool-calls-row__caret${openIndex === i ? ' is-open' : ''}`} />
            </button>
            {openIndex === i && (
              <div className="tool-calls-row__detail">
                <div className="tool-detail-section">
                  <div className="tool-detail-section__label">{t('toolCalls.arguments')}</div>
                  <pre className="tool-detail-section__pre">{formatToolArgs(tc.args, tc.argsTruncated)}</pre>
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
            )}
          </div>
        ))}
      </div>
    </aside>
  )
}

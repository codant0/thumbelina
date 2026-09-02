import { useCallback, useEffect, useState } from 'react'
import { AlertTriangle, RefreshCw } from 'lucide-react'
import { useTranslation } from '../../i18n'
import { Modal } from '../Settings/Modal'
import { MarkdownContent } from '../Chat/MarkdownContent'
import { getTask, type ScheduledTaskDetailVO } from '../../api/tasks'

interface TaskDetailModalProps {
  /** When non-null, the modal opens and fetches this task. null = closed. */
  taskId: string | null
  onClose: () => void
}

type State =
  | { kind: 'loading' }
  | { kind: 'error'; message: string }
  | { kind: 'ready'; task: ScheduledTaskDetailVO }

/** Detail modal for a single scheduled task (GET /tasks/{id}).
 *  Three states (skeleton / error-with-retry / detail). The detail body
 *  shows the task's content + last run output as Markdown so anything the
 *  user typed (long prompts, fenced code, tables) renders intact — not
 *  truncated to 80 chars like the previous list view. */
export function TaskDetailModal({ taskId, onClose }: TaskDetailModalProps) {
  const { t } = useTranslation()
  const [state, setState] = useState<State>({ kind: 'loading' })
  const [retryNonce, setRetryNonce] = useState(0)

  useEffect(() => {
    if (taskId === null) return
    let cancelled = false
    getTask(taskId)
      .then(task => {
        if (!cancelled) setState({ kind: 'ready', task })
      })
      .catch((err: unknown) => {
        if (cancelled) return
        setState({
          kind: 'error',
          message: err instanceof Error ? err.message : String(err),
        })
      })
    return () => {
      cancelled = true
    }
  }, [taskId, retryNonce])

  // Reset to the skeleton when the user opens a different task.
  useEffect(() => {
    setState({ kind: 'loading' }) // eslint-disable-line react-hooks/set-state-in-effect
  }, [taskId, retryNonce])

  const handleRetry = useCallback(() => setRetryNonce(n => n + 1), [])

  if (taskId === null) return null

  return (
    <Modal title={t('taskManager.viewDetail')} onClose={onClose} className="modal--wide">
      {state.kind === 'loading' && <DetailSkeleton />}
      {state.kind === 'error' && (
        <div className="detail-state" data-testid="detail-error-state">
          <AlertTriangle size={24} aria-hidden />
          <div>{t('taskManager.detailLoadFailed')}</div>
          <div style={{ fontSize: 'var(--fs-xs)', color: 'var(--text-secondary)' }}>
            {state.message}
          </div>
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            data-testid="detail-retry"
            onClick={handleRetry}
          >
            <RefreshCw size={14} />
            {t('taskManager.retry')}
          </button>
        </div>
      )}
      {state.kind === 'ready' && <DetailBody task={state.task} />}
    </Modal>
  )
}

function DetailSkeleton() {
  return (
    <div className="detail-skeleton" data-testid="detail-skeleton">
      <div className="detail-skeleton__bar detail-skeleton__bar--lg" />
      <div className="detail-skeleton__bar" style={{ width: '70%' }} />
      <div className="detail-skeleton__bar" style={{ width: '90%' }} />
      <div className="detail-skeleton__bar" style={{ width: '55%' }} />
    </div>
  )
}

function DetailBody({ task }: { task: ScheduledTaskDetailVO }) {
  const { t } = useTranslation()

  const triggerLabel =
    task.trigger === 'cron'
      ? `${t('taskManager.triggerCron')}${task.cron ? `: ${task.cron}` : ''}`
      : t('taskManager.triggerOnce')
  const modeLabel =
    task.mode === 'prompt'
      ? t('taskManager.modePrompt')
      : task.mode === 'notify'
        ? t('taskManager.modeNotify')
        : task.mode
  const sourceLabel =
    task.source === 'agent'
      ? t('taskManager.sourceAgent')
      : task.source === 'web'
        ? t('taskManager.sourceWeb')
        : task.source === 'api'
          ? t('taskManager.sourceApi')
          : task.source
  const statusClass = statusBadgeClass(task.status)

  return (
    <div data-testid="detail-body">
      <div className="detail-subtitle">
        <span className="task-title" style={{ fontSize: 'var(--fs-md)' }}>
          {task.description}
        </span>
        <span className={`badge ${statusClass}`} data-testid="detail-status">
          {task.status}
        </span>
        {task.trigger === 'cron' ? (
          <span className="badge badge-accent">{triggerLabel}</span>
        ) : (
          <span className="badge badge-neutral">{triggerLabel}</span>
        )}
        <span className="badge badge-neutral" data-testid="detail-channel">
          {task.channel}
        </span>
      </div>

      <div className="detail-meta">
        <Meta label={t('taskManager.fieldTrigger')}>{triggerLabel}</Meta>
        {task.cron && <Meta label={t('taskManager.fieldCron')}>{task.cron}</Meta>}
        <Meta label={t('taskManager.fieldChannel')}>{task.channel}</Meta>
        <Meta label={t('taskManager.fieldMode')}>{modeLabel}</Meta>
        <Meta label={t('taskManager.fieldSource')}>{sourceLabel}</Meta>
        {task.scheduled_time && (
          <Meta label={task.trigger === 'cron' ? t('taskManager.fieldNextRun') : t('taskManager.fieldNextRun')}>
            {new Date(task.scheduled_time).toLocaleString()}
          </Meta>
        )}
        {task.last_run && (
          <Meta label={t('taskManager.fieldLastRun')}>
            {new Date(task.last_run).toLocaleString()}
          </Meta>
        )}
        <Meta label={t('taskManager.fieldCreatedAt')}>
          {new Date(task.created_at).toLocaleString()}
        </Meta>
      </div>

      {task.content && (
        <div className="detail-section">
          <div className="detail-section__label">{t('taskManager.detailContent')}</div>
          <MarkdownContent content={task.content} />
        </div>
      )}

      <div className="detail-section">
        <div className="detail-section__label">{t('taskManager.detailResult')}</div>
        {task.result ? (
          <div className="detail-result">
            <MarkdownContent content={task.result} />
          </div>
        ) : (
          <div className="detail-empty">{t('taskManager.noResult')}</div>
        )}
      </div>

      {task.error && (
        <div className="detail-section">
          <div className="detail-section__label">{t('taskManager.detailError')}</div>
          <div className="detail-error">{task.error}</div>
        </div>
      )}
    </div>
  )
}

function Meta({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="detail-meta__item">
      <div className="detail-meta__label">{label}</div>
      <div className="detail-meta__value">{children}</div>
    </div>
  )
}

function statusBadgeClass(status: string): string {
  if (status === 'completed') return 'badge-success'
  if (status === 'running') return 'badge-warning'
  if (status === 'failed') return 'badge-error'
  if (status === 'paused' || status === 'missed') return 'badge-orange'
  return 'badge-neutral'
}
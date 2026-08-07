import { Check, FileText, Files, Link, Loader2, X, XCircle } from 'lucide-react'
import { useTranslation } from '../../i18n'
import type { UploadTask } from '../../types/rag'

interface Props {
  tasks: UploadTask[]
  onCancel: (taskId: string) => void
  onDismiss: (taskId: string) => void
}

const ACTIVE_STATUSES = new Set(['pending', 'running'])

const statusKey: Record<string, string> = {
  pending: 'uploadTask.statusPending',
  running: 'uploadTask.statusRunning',
  completed: 'uploadTask.statusCompleted',
  failed: 'uploadTask.statusFailed',
  cancelled: 'uploadTask.statusCancelled',
}

const stageKey: Record<string, string> = {
  loading: 'uploadTask.stageLoading',
  chunking: 'uploadTask.stageChunking',
  embedding: 'uploadTask.stageEmbedding',
  storing: 'uploadTask.stageStoring',
}

function taskPercent(task: UploadTask): number {
  if (task.status === 'completed') return 100
  if (task.total_files <= 0) return 0
  const fileSpan = 100 / task.total_files
  const chunkPart = task.chunk_total > 0 ? (task.chunk_done / task.chunk_total) * fileSpan : 0
  return Math.min(Math.round(task.done_files * fileSpan + chunkPart), 99)
}

export function UploadTaskList({ tasks, onCancel, onDismiss }: Props) {
  const { t } = useTranslation()
  if (tasks.length === 0) return null

  return (
    <div className="kb-upload-tasks" data-testid="kb-upload-tasks">
      <div className="kb-upload-tasks__title">{t('uploadTask.title')}</div>
      {tasks.map(task => {
        const active = ACTIVE_STATUSES.has(task.status)
        const pct = taskPercent(task)
        return (
          <div key={task.id} className="kb-upload-task" data-testid={`kb-upload-task-${task.id}`}>
            <div className="kb-upload-task__header">
              <span className="kb-upload-task__icon">
                {task.kind === 'url' ? (
                  <Link size={13} />
                ) : task.kind === 'batch' ? (
                  <Files size={13} />
                ) : (
                  <FileText size={13} />
                )}
              </span>
              <span className="kb-upload-task__label" title={task.label}>
                {task.kind === 'batch'
                  ? t('uploadTask.batchFileLabel', { name: task.label, count: task.total_files })
                  : task.label}
              </span>
              <span className={`kb-upload-task__badge kb-upload-task__badge--${task.status}`}>
                {task.status === 'running' && <Loader2 size={10} className="spin" />}
                {task.status === 'completed' && <Check size={10} />}
                {task.status === 'failed' && <XCircle size={10} />}
                {t(statusKey[task.status] ?? task.status)}
              </span>
              {active ? (
                <button
                  className="btn btn-ghost btn-sm"
                  onClick={() => onCancel(task.id)}
                  title={t('uploadTask.cancelTask')}
                >
                  <X size={12} />
                </button>
              ) : (
                <button
                  className="btn btn-ghost btn-sm"
                  onClick={() => onDismiss(task.id)}
                  title={t('uploadTask.dismissTask')}
                >
                  <X size={12} />
                </button>
              )}
            </div>
            {active && (
              <>
                <div
                  className="kb-upload-task__bar"
                  role="progressbar"
                  aria-valuenow={pct}
                  aria-valuemin={0}
                  aria-valuemax={100}
                >
                  <div className="kb-upload-task__fill" style={{ width: `${pct}%` }} />
                </div>
                <div className="kb-upload-task__detail">
                  <span>
                    {task.status === 'pending'
                      ? t('uploadTask.stageQueued')
                      : t(stageKey[task.stage] ?? task.stage)}
                  </span>
                  {task.total_files > 1 && (
                    <span>
                      {t('uploadTask.fileProgress', {
                        done: task.done_files,
                        total: task.total_files,
                      })}
                    </span>
                  )}
                  {task.chunk_total > 0 && (
                    <span>
                      {t('uploadTask.chunkProgress', {
                        done: task.chunk_done,
                        total: task.chunk_total,
                      })}
                    </span>
                  )}
                </div>
              </>
            )}
            {task.status === 'completed' && task.result && (
              <div className="kb-upload-task__result">
                {t('uploadTask.taskResult', {
                  uploaded: task.result.uploaded.length,
                  skipped: task.result.skipped.length,
                  errors: task.result.errors.length,
                })}
              </div>
            )}
            {task.status === 'failed' && task.error && (
              <div className="kb-upload-task__error">{task.error}</div>
            )}
          </div>
        )
      })}
    </div>
  )
}

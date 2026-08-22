import { useState, useCallback } from 'react'
import { EndpointManager } from './EndpointManager'
import { useTranslation } from '../../i18n'
import { Toast } from './Toast'
import { Gauge, Globe, Database, Download, Trash2, Loader2, Zap } from 'lucide-react'
import { StatusBarCardGrid } from '../StatusBar/StatusBarCardGrid'
import { useStatusBarConfig } from '../StatusBar/useStatusBarConfig'

export function SettingsPanel() {
  const { t, locale, setLocale } = useTranslation()
  const [message, setMessage] = useState('')
  const [isError, setIsError] = useState(false)
  const { config, toggle } = useStatusBarConfig()

  // Data management state
  const [exporting, setExporting] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [deleteConfirm, setDeleteConfirm] = useState(false)

  const handleExport = useCallback(async () => {
    setExporting(true)
    try {
      const res = await fetch('/api/v1/data/export')
      if (res.ok) {
        const data = await res.json()
        const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
        const url = URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = url
        a.download = `thumbelina-export-${new Date().toISOString().slice(0, 10)}.json`
        a.click()
        URL.revokeObjectURL(url)
      }
    } catch { /* ignore */ } finally {
      setExporting(false)
    }
  }, [])

  const handleDeleteAll = useCallback(async () => {
    if (!deleteConfirm) {
      setDeleteConfirm(true)
      return
    }
    setDeleting(true)
    try {
      const res = await fetch('/api/v1/data/all?confirm=true', { method: 'DELETE' })
      if (res.ok) {
        setMessage(t('settings.allDataDeleted'))
        setIsError(false)
        setDeleteConfirm(false)
      } else {
        setMessage(t('settings.failedToDelete'))
        setIsError(true)
      }
    } catch {
      setMessage('Failed to delete data')
      setIsError(true)
    } finally {
      setDeleting(false)
    }
  }, [deleteConfirm])

  return (
    <div className="page-container" data-testid="settings-panel">
      <div className="page-title">{t('settings.title')}</div>

      <Toast
        message={message}
        isError={isError}
        onClose={() => setMessage('')}
      />

      {/* Language selector */}
      <div className="card">
        <div className="card-title"><Globe size={14} />{t('settings.language')}</div>
        <div className="settings-row">
          <select
            className="form-select"
            data-testid="language-select"
            value={locale}
            onChange={e => setLocale(e.target.value === 'zh-CN' ? 'zh-CN' : 'en')}
          >
            <option value="en">{t('language.en')}</option>
            <option value="zh-CN">{t('language.zhCN')}</option>
          </select>
        </div>
      </div>

      {/* Status Bar */}
      <div className="card" data-testid="statusbar-settings-card">
        <div className="card-title"><Gauge size={14} />{t('settings.statusBar')}</div>
        <StatusBarCardGrid
          cards={[
            {
              key: 'context',
              label: t('settings.statusbarColumns.context'),
              description: t('settings.statusbarColumns.contextDesc'),
              icon: <Gauge size={18} />,
            },
            {
              key: 'cacheHit',
              label: t('settings.statusbarColumns.cacheHit'),
              description: t('settings.statusbarColumns.cacheHitDesc'),
              icon: <Zap size={18} />,
            },
          ]}
          config={config}
          onToggle={toggle}
        />
      </div>

      {/* LLM Configuration */}
      <EndpointManager onMessage={(msg, err) => { setMessage(msg); setIsError(err) }} />

      {/* Data Management */}
      <div className="card" data-testid="data-management-card">
        <div className="card-title"><Database size={14} />{t('settings.dataManagement')}</div>
        <div className="settings-row settings-row--wrap">
          <button
            className="btn btn-ghost"
            data-testid="export-button"
            onClick={handleExport}
            disabled={exporting}
          >
            {exporting ? <Loader2 size={16} className="spin" /> : <Download size={16} />}
            {exporting ? t('settings.exporting') : t('settings.exportAll')}
          </button>
          <button
            className={`btn ${deleteConfirm ? 'btn-danger' : 'btn-ghost'}`}
            data-testid="delete-all-button"
            onClick={handleDeleteAll}
            disabled={deleting}
          >
            {deleting ? <Loader2 size={16} className="spin" /> : <Trash2 size={16} />}
            {deleting ? t('settings.deleting') : deleteConfirm ? t('settings.confirmDelete') : t('settings.deleteAll')}
          </button>
          {deleteConfirm && (
            <button
              className="btn btn-ghost btn-sm"
              onClick={() => setDeleteConfirm(false)}
            >
              {t('common.cancel')}
            </button>
          )}
        </div>
      </div>
    </div>
  )
}

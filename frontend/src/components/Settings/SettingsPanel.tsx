import { useState, useEffect, useCallback } from 'react'
import { EndpointManager } from './EndpointManager'
import { useTranslation } from '../../i18n'
import { Toast } from './Toast'
import { Globe, User, Database, Download, Trash2, Loader2 } from 'lucide-react'

interface UserProfile {
  id: string
  user_id: string
  communication_style: string
  expertise_level: string
}

interface UserPreference {
  id: string
  category: string
  key: string
  value: string
  confidence_score: number
}

export function SettingsPanel() {
  const { t, locale, setLocale } = useTranslation()
  const [message, setMessage] = useState('')
  const [isError, setIsError] = useState(false)

  // User profile state
  const [profile, setProfile] = useState<UserProfile | null>(null)
  const [preferences, setPreferences] = useState<UserPreference[]>([])
  const [profileLoading, setProfileLoading] = useState(true)

  // Data management state
  const [exporting, setExporting] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [deleteConfirm, setDeleteConfirm] = useState(false)

  // Fetch user profile
  useEffect(() => {
    fetch('/api/v1/user/profile')
      .then(res => { if (res.ok) return res.json(); return null })
      .then(data => {
        if (data) {
          setProfile(data.profile ?? null)
          setPreferences(data.preferences ?? [])
        }
      })
      .catch(() => {})
      .finally(() => setProfileLoading(false))
  }, [])

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

      {/* LLM Configuration */}
      <EndpointManager onMessage={(msg, err) => { setMessage(msg); setIsError(err) }} />

      {/* User Profile */}
      <div className="card" data-testid="user-profile-card">
        <div className="card-title"><User size={14} />{t('settings.userProfile')}</div>
        {profileLoading ? (
          <p className="settings-empty-hint">{t('common.loading')}</p>
        ) : profile ? (
          <div className="settings-profile-list">
            <div className="settings-profile-item">
              <strong>{t('profile.communicationStyle')}:</strong>&nbsp;{profile.communication_style || t('profile.notSet')}
            </div>
            <div className="settings-profile-item">
              <strong>{t('profile.expertiseLevel')}:</strong>&nbsp;{profile.expertise_level || t('profile.notSet')}
            </div>
            {preferences.length > 0 && (
              <div className="settings-profile-item">
                <div>
                  <strong>{t('profile.preferences')}:</strong>
                  <ul className="settings-preference-list">
                    {preferences.map(p => (
                      <li key={p.id} data-testid="preference-item" className="settings-preference-li">
                        <span className="settings-preference-key">{p.category}/{p.key}:</span> {p.value}
                        <span className="settings-preference-score"> ({Math.round(p.confidence_score * 100)}%)</span>
                      </li>
                    ))}
                  </ul>
                </div>
              </div>
            )}
          </div>
        ) : (
          <p className="settings-empty-hint">{t('profile.noData')}</p>
        )}
      </div>

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

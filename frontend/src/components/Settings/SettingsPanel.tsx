import { useState, useEffect, useCallback } from 'react'
import { EndpointManager } from './EndpointManager'
import { useTranslation } from '../../i18n'

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
        setMessage('All data deleted')
        setIsError(false)
        setDeleteConfirm(false)
      } else {
        setMessage('Failed to delete data')
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

      {/* Language selector */}
      <div className="card">
        <div className="card-title">{t('settings.language')}</div>
        <div style={{ display: 'flex', gap: 8 }}>
          <select
            className="form-select"
            data-testid="language-select"
            value={locale}
            onChange={e => setLocale(e.target.value === 'zh-CN' ? 'zh-CN' : 'en')}
            style={{ maxWidth: 200 }}
          >
            <option value="en">{t('language.en')}</option>
            <option value="zh-CN">{t('language.zhCN')}</option>
          </select>
        </div>
      </div>

      {/* LLM Configuration */}
      <EndpointManager onMessage={(msg, err) => { setMessage(msg); setIsError(err) }} />

      {message && (
        <p
          data-testid="settings-message"
          style={{ fontSize: 12.5, color: isError ? 'var(--error)' : 'var(--success)', margin: '8px 0' }}
        >
          {message}
        </p>
      )}

      {/* User Profile */}
      <div className="card" data-testid="user-profile-card">
        <div className="card-title">{t('settings.userProfile')}</div>
        {profileLoading ? (
          <p style={{ color: 'var(--text-secondary)', fontSize: 12 }}>{t('common.loading')}</p>
        ) : profile ? (
          <div style={{ fontSize: 13 }}>
            <div style={{ marginBottom: 8 }}>
              <strong>{t('profile.communicationStyle')}:</strong> {profile.communication_style || t('profile.notSet')}
            </div>
            <div style={{ marginBottom: 8 }}>
              <strong>{t('profile.expertiseLevel')}:</strong> {profile.expertise_level || t('profile.notSet')}
            </div>
            {preferences.length > 0 && (
              <div>
                <strong>{t('profile.preferences')}:</strong>
                <ul style={{ margin: '4px 0 0 16px', padding: 0 }}>
                  {preferences.map(p => (
                    <li key={p.id} data-testid="preference-item">
                      <span style={{ color: 'var(--text-secondary)' }}>{p.category}/{p.key}:</span> {p.value}
                      <span style={{ marginLeft: 6, fontSize: 11, color: 'var(--text-secondary)' }}>
                        ({Math.round(p.confidence_score * 100)}%)
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        ) : (
          <p style={{ color: 'var(--text-secondary)', fontSize: 12 }}>
            {t('profile.noData')}
          </p>
        )}
      </div>

      {/* Data Management */}
      <div className="card" data-testid="data-management-card">
        <div className="card-title">{t('settings.dataManagement')}</div>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          <button
            className="btn btn-ghost"
            data-testid="export-button"
            onClick={handleExport}
            disabled={exporting}
          >
            {exporting ? 'Exporting...' : t('settings.exportAll')}
          </button>
          <button
            className={`btn ${deleteConfirm ? 'btn-danger' : 'btn-ghost'}`}
            data-testid="delete-all-button"
            onClick={handleDeleteAll}
            disabled={deleting}
          >
            {deleting ? 'Deleting...' : deleteConfirm ? t('settings.confirmDelete') : t('settings.deleteAll')}
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

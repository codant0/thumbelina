import { useState, useEffect, useRef, type FormEvent } from 'react'
import { QRCodeSVG } from 'qrcode.react'

interface ChannelConfig {
  qq: {
    enabled: boolean
    app_id: string
    app_secret_set: boolean
    allowed_guilds: string[]
    allowed_groups: string[]
  }
  wechat: {
    enabled: boolean
    ilink_bot_id: string
    bot_token_set: boolean
  }
}

interface ChannelStatus {
  connected: boolean
  error?: string
}

interface QQForm {
  enabled: boolean
  app_id: string
  app_secret: string
  allowed_guilds: string
  allowed_groups: string
}

interface WeChatForm {
  enabled: boolean
  bot_token: string
  ilink_bot_id: string
  ilink_user_id: string
  ilink_base_url: string
}

type QRFlowState = 'idle' | 'loading' | 'scanning' | 'scanned' | 'confirmed' | 'expired' | 'error'

export function ChannelsPage() {
  const [config, setConfig] = useState<ChannelConfig | null>(null)
  const [qqStatus, setQqStatus] = useState<ChannelStatus | null>(null)
  const [wechatStatus, setWechatStatus] = useState<ChannelStatus | null>(null)
  const [loading, setLoading] = useState(true)

  // Edit mode state
  const [editingQq, setEditingQq] = useState(false)
  const [editingWechat, setEditingWechat] = useState(false)
  const [qqForm, setQqForm] = useState<QQForm>({
    enabled: false, app_id: '', app_secret: '', allowed_guilds: '', allowed_groups: '',
  })
  const [wechatForm, setWechatForm] = useState<WeChatForm>({
    enabled: false, bot_token: '', ilink_bot_id: '', ilink_user_id: '', ilink_base_url: '',
  })
  const [saving, setSaving] = useState<string | null>(null)
  const [message, setMessage] = useState<{ channel: string; text: string; error: boolean } | null>(null)

  // QR code login state
  const [qrFlow, setQrFlow] = useState<QRFlowState>('idle')
  const [qrData, setQrData] = useState<{ qrcode: string; imgContent: string } | null>(null)
  const [qrError, setQrError] = useState<string | null>(null)
  const pollingRef = useRef(false)

  const loadConfig = async () => {
    try {
      const configRes = await fetch('/api/v1/config')
      if (configRes.ok) {
        const data = await configRes.json()
        setConfig(data.channels)
      }
    } catch { /* ignore */ }
  }

  const fetchStatus = async (channels: ChannelConfig) => {
    const promises: Promise<void>[] = []
    if (channels.qq.enabled) {
      promises.push(
        fetch('/api/v1/qq/status')
          .then(res => res.ok ? res.json() : { connected: false, error: 'Channel not available' })
          .then(setQqStatus)
          .catch(() => setQqStatus({ connected: false, error: 'Channel not available' }))
      )
    } else {
      setQqStatus(null)
    }
    if (channels.wechat.enabled) {
      promises.push(
        fetch('/api/v1/wechat/status')
          .then(res => res.ok ? res.json() : { connected: false, error: 'Channel not available' })
          .then(setWechatStatus)
          .catch(() => setWechatStatus({ connected: false, error: 'Channel not available' }))
      )
    } else {
      setWechatStatus(null)
    }
    await Promise.allSettled(promises)
  }

  useEffect(() => {
    const load = async () => {
      setLoading(true)
      await loadConfig()
      setLoading(false)
    }
    void load()
  }, [])

  useEffect(() => {
    if (!config) return
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void fetchStatus(config)
  }, [config])

  // Cleanup polling on unmount
  useEffect(() => {
    return () => { pollingRef.current = false }
  }, [])

  // ── QR Code Flow ──────────────────────────────────────────────

  const startQRFlow = async () => {
    setQrFlow('loading')
    setQrError(null)
    try {
      const res = await fetch('/api/v1/wechat/qrcode', { method: 'POST' })
      if (!res.ok) {
        const err = await res.json().catch(() => null)
        throw new Error(err?.detail || 'Failed to fetch QR code')
      }
      const data = await res.json()
      setQrData({ qrcode: data.qrcode, imgContent: data.qrcode_img_content })
      setQrFlow('scanning')
      pollingRef.current = true
      startPolling(data.qrcode)
    } catch (e) {
      setQrFlow('error')
      setQrError(e instanceof Error ? e.message : 'Unknown error')
    }
  }

  const startPolling = async (qrcode: string) => {
    while (pollingRef.current) {
      try {
        const res = await fetch(
          `/api/v1/wechat/qrcode/status?qrcode=${encodeURIComponent(qrcode)}`
        )
        if (!res.ok) {
          const err = await res.json().catch(() => null)
          throw new Error(err?.detail || 'Poll failed')
        }
        const data = await res.json()

        if (data.status === 'scaned') {
          setQrFlow('scanned')
        } else if (data.status === 'confirmed') {
          setQrFlow('confirmed')
          pollingRef.current = false
          // Auto-save credentials
          await confirmLogin(data.credentials)
          return
        } else if (data.status === 'expired') {
          setQrFlow('expired')
          pollingRef.current = false
          return
        }
        // 'wait' — continue polling
      } catch (e) {
        // Network errors are transient during long-poll, continue
        if (!pollingRef.current) return
        // Only break on non-network errors
        if (e instanceof Error && !e.message.includes('fetch')) {
          setQrFlow('error')
          setQrError(e.message)
          pollingRef.current = false
          return
        }
      }
    }
  }

  const confirmLogin = async (credentials: {
    bot_token: string
    ilink_bot_id: string
    base_url: string
    ilink_user_id: string
  }) => {
    try {
      const res = await fetch('/api/v1/wechat/qrcode/confirm', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(credentials),
      })
      if (res.ok) {
        const confirmData = await res.json().catch(() => null)
        await loadConfig()
        setQrFlow('confirmed')
        if (confirmData?.connected) {
          setMessage({ channel: 'wechat', text: 'Login successful! WeChat channel is connected.', error: false })
        }
        // Notify App to refresh conversation list (WeChat conversation was created)
        window.dispatchEvent(new Event('conversations-updated'))
      } else {
        const err = await res.json().catch(() => null)
        setQrFlow('error')
        setQrError(err?.detail || 'Failed to save credentials')
      }
    } catch {
      setQrFlow('error')
      setQrError('Network error')
    }
  }

  const resetQRFlow = () => {
    pollingRef.current = false
    setQrFlow('idle')
    setQrData(null)
    setQrError(null)
  }

  // ── QQ Edit Handlers ─────────────────────────────────────────

  const startEditQq = () => {
    if (!config) return
    setQqForm({
      enabled: config.qq.enabled,
      app_id: config.qq.app_id,
      app_secret: '',
      allowed_guilds: config.qq.allowed_guilds.join(', '),
      allowed_groups: config.qq.allowed_groups.join(', '),
    })
    setEditingQq(true)
    setMessage(null)
  }

  const startEditWechat = () => {
    if (!config) return
    setWechatForm({
      enabled: config.wechat.enabled,
      bot_token: '',
      ilink_bot_id: config.wechat.ilink_bot_id,
      ilink_user_id: '',
      ilink_base_url: '',
    })
    setEditingWechat(true)
    setMessage(null)
  }

  const handleSaveQq = async (e: FormEvent) => {
    e.preventDefault()
    setSaving('qq')
    setMessage(null)
    try {
      const res = await fetch('/api/v1/config/channels/qq', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          enabled: qqForm.enabled,
          app_id: qqForm.app_id,
          app_secret: qqForm.app_secret || undefined,
          allowed_guilds: qqForm.allowed_guilds
            ? qqForm.allowed_guilds.split(',').map(s => s.trim()).filter(Boolean)
            : [],
          allowed_groups: qqForm.allowed_groups
            ? qqForm.allowed_groups.split(',').map(s => s.trim()).filter(Boolean)
            : [],
        }),
      })
      if (res.ok) {
        const data = await res.json()
        setMessage({ channel: 'qq', text: `QQ Bot ${data.enabled ? 'enabled' : 'disabled'}${data.connected ? ' (connected)' : ''}`, error: false })
        setEditingQq(false)
        await loadConfig()
      } else {
        const err = await res.json().catch(() => null)
        setMessage({ channel: 'qq', text: err?.detail || 'Failed to save', error: true })
      }
    } catch {
      setMessage({ channel: 'qq', text: 'Network error', error: true })
    } finally {
      setSaving(null)
    }
  }

  const handleSaveWechat = async (e: FormEvent) => {
    e.preventDefault()
    setSaving('wechat')
    setMessage(null)
    try {
      const res = await fetch('/api/v1/config/channels/wechat', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          enabled: wechatForm.enabled,
          bot_token: wechatForm.bot_token || undefined,
          ilink_bot_id: wechatForm.ilink_bot_id || undefined,
          ilink_user_id: wechatForm.ilink_user_id || undefined,
          ilink_base_url: wechatForm.ilink_base_url || undefined,
        }),
      })
      if (res.ok) {
        const data = await res.json()
        setMessage({ channel: 'wechat', text: `WeChat ${data.enabled ? 'enabled' : 'disabled'}${data.connected ? ' (connected)' : ''}`, error: false })
        setEditingWechat(false)
        await loadConfig()
      } else {
        const err = await res.json().catch(() => null)
        setMessage({ channel: 'wechat', text: err?.detail || 'Failed to save', error: true })
      }
    } catch {
      setMessage({ channel: 'wechat', text: 'Network error', error: true })
    } finally {
      setSaving(null)
    }
  }

  if (loading) {
    return (
      <div className="page-container" data-testid="channels-page">
        <div className="page-title">Channels</div>
        <div className="loading-state"><div className="spinner" /><span>Loading...</span></div>
      </div>
    )
  }

  return (
    <div className="page-container" data-testid="channels-page">
      <div className="page-title">Channels</div>

      {/* QQ Bot Card */}
      <div className="card" data-testid="qq-channel-card">
        <div className="card-title" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <span>QQ Bot</span>
          <span className={`badge ${config?.qq.enabled ? 'badge-success' : 'badge-error'}`}>
            {config?.qq.enabled ? 'enabled' : 'disabled'}
          </span>
        </div>

        {editingQq ? (
          <form onSubmit={handleSaveQq}>
            <div className="form-group">
              <label className="form-checkbox">
                <input
                  type="checkbox"
                  checked={qqForm.enabled}
                  onChange={e => setQqForm({ ...qqForm, enabled: e.target.checked })}
                />
                Enable QQ Bot
              </label>
            </div>
            <div className="form-group">
              <label className="form-label" htmlFor="qq-app-id">App ID</label>
              <input
                id="qq-app-id"
                type="text"
                className="form-input"
                value={qqForm.app_id}
                onChange={e => setQqForm({ ...qqForm, app_id: e.target.value })}
                placeholder="QQ Bot App ID"
              />
            </div>
            <div className="form-group">
              <label className="form-label" htmlFor="qq-app-secret">App Secret</label>
              <input
                id="qq-app-secret"
                type="password"
                className="form-input"
                value={qqForm.app_secret}
                onChange={e => setQqForm({ ...qqForm, app_secret: e.target.value })}
                placeholder={config?.qq.app_secret_set ? "Leave empty to keep current" : ""}
              />
            </div>
            <div className="form-group">
              <label className="form-label" htmlFor="qq-guilds">Allowed Guilds</label>
              <input
                id="qq-guilds"
                type="text"
                className="form-input"
                value={qqForm.allowed_guilds}
                onChange={e => setQqForm({ ...qqForm, allowed_guilds: e.target.value })}
                placeholder="Comma-separated guild IDs (empty = all)"
              />
            </div>
            <div className="form-group">
              <label className="form-label" htmlFor="qq-groups">Allowed Groups</label>
              <input
                id="qq-groups"
                type="text"
                className="form-input"
                value={qqForm.allowed_groups}
                onChange={e => setQqForm({ ...qqForm, allowed_groups: e.target.value })}
                placeholder="Comma-separated group IDs (empty = all)"
              />
            </div>
            <div className="settings-actions">
              <button type="submit" className="btn btn-primary" disabled={saving === 'qq'}>
                {saving === 'qq' ? 'Saving...' : 'Save'}
              </button>
              <button type="button" className="btn btn-ghost" onClick={() => setEditingQq(false)}>Cancel</button>
            </div>
          </form>
        ) : (
          <>
            {config?.qq.enabled ? (
              <>
                <div className="chat-status" style={{ marginBottom: 12, borderRadius: 'var(--radius-sm)', padding: '6px 10px', fontSize: 12 }}>
                  <span className={`dot ${qqStatus?.connected ? 'connected' : 'disconnected'}`} />
                  <span>{qqStatus?.connected ? 'Connected' : qqStatus?.error || 'Disconnected'}</span>
                </div>

                <div className="form-group">
                  <label className="form-label">App ID</label>
                  <div className="form-input" style={{ opacity: 0.7, cursor: 'default' }}>
                    {config.qq.app_id || '(not set)'}
                  </div>
                </div>

                {config.qq.allowed_guilds.length > 0 && (
                  <div className="form-group">
                    <label className="form-label">Allowed Guilds</label>
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                      {config.qq.allowed_guilds.map(id => (
                        <span key={id} className="badge badge-neutral">{id}</span>
                      ))}
                    </div>
                  </div>
                )}

                {config.qq.allowed_groups.length > 0 && (
                  <div className="form-group">
                    <label className="form-label">Allowed Groups</label>
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                      {config.qq.allowed_groups.map(id => (
                        <span key={id} className="badge badge-neutral">{id}</span>
                      ))}
                    </div>
                  </div>
                )}
              </>
            ) : (
              <p style={{ color: 'var(--text-secondary)', fontSize: 12, padding: '8px 0' }}>
                QQ Bot is not enabled. Click Edit to configure.
              </p>
            )}
            <div className="settings-actions" style={{ marginTop: 8 }}>
              <button className="btn btn-ghost" onClick={startEditQq} data-testid="edit-qq-button">
                Edit
              </button>
            </div>
          </>
        )}

        {message?.channel === 'qq' && (
          <p style={{ marginTop: 8, fontSize: 12.5, color: message.error ? 'var(--error)' : 'var(--success)' }}>
            {message.text}
          </p>
        )}
      </div>

      {/* WeChat Card */}
      <div className="card" data-testid="wechat-channel-card">
        <div className="card-title" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <span>WeChat</span>
          <span className={`badge ${config?.wechat.enabled ? 'badge-success' : 'badge-error'}`}>
            {config?.wechat.enabled ? 'enabled' : 'disabled'}
          </span>
        </div>

        {editingWechat ? (
          <form onSubmit={handleSaveWechat}>
            <div className="form-group">
              <label className="form-checkbox">
                <input
                  type="checkbox"
                  checked={wechatForm.enabled}
                  onChange={e => setWechatForm({ ...wechatForm, enabled: e.target.checked })}
                />
                Enable WeChat Channel
              </label>
            </div>
            <div className="form-group">
              <label className="form-label" htmlFor="wechat-bot-token">Bot Token</label>
              <input
                id="wechat-bot-token"
                type="password"
                className="form-input"
                value={wechatForm.bot_token}
                onChange={e => setWechatForm({ ...wechatForm, bot_token: e.target.value })}
                placeholder={config?.wechat.bot_token_set ? "Leave empty to keep current" : ""}
              />
            </div>
            <div className="form-group">
              <label className="form-label" htmlFor="wechat-bot-id">Bot ID</label>
              <input
                id="wechat-bot-id"
                type="text"
                className="form-input"
                value={wechatForm.ilink_bot_id}
                onChange={e => setWechatForm({ ...wechatForm, ilink_bot_id: e.target.value })}
                placeholder="e.g. wxid_xxxx"
              />
            </div>
            <div className="form-group">
              <label className="form-label" htmlFor="wechat-user-id">User ID</label>
              <input
                id="wechat-user-id"
                type="text"
                className="form-input"
                value={wechatForm.ilink_user_id}
                onChange={e => setWechatForm({ ...wechatForm, ilink_user_id: e.target.value })}
                placeholder="e.g. wxid_xxxx"
              />
            </div>
            <div className="form-group">
              <label className="form-label" htmlFor="wechat-base-url">iLink Base URL</label>
              <input
                id="wechat-base-url"
                type="text"
                className="form-input"
                value={wechatForm.ilink_base_url}
                onChange={e => setWechatForm({ ...wechatForm, ilink_base_url: e.target.value })}
                placeholder="https://ilinkai.weixin.qq.com (default)"
              />
            </div>
            <div className="settings-actions">
              <button type="submit" className="btn btn-primary" disabled={saving === 'wechat'}>
                {saving === 'wechat' ? 'Saving...' : 'Save'}
              </button>
              <button type="button" className="btn btn-ghost" onClick={() => setEditingWechat(false)}>Cancel</button>
            </div>
          </form>
        ) : (
          <>
            {config?.wechat.enabled ? (
              <>
                <div className="chat-status" style={{ marginBottom: 12, borderRadius: 'var(--radius-sm)', padding: '6px 10px', fontSize: 12 }}>
                  <span className={`dot ${wechatStatus?.connected ? 'connected' : 'disconnected'}`} />
                  <span>{wechatStatus?.connected ? 'Connected' : wechatStatus?.error || 'Disconnected'}</span>
                </div>

                <div className="form-group">
                  <label className="form-label">Bot ID</label>
                  <div className="form-input" style={{ opacity: 0.7, cursor: 'default' }}>
                    {config.wechat.ilink_bot_id || '(not set)'}
                  </div>
                </div>
              </>
            ) : (
              <>
                {/* QR Code Login Flow */}
                {qrFlow === 'idle' && (
                  <div style={{ padding: '12px 0' }}>
                    <p style={{ color: 'var(--text-secondary)', fontSize: 12, marginBottom: 12 }}>
                      Scan a QR code with WeChat to login, or configure manually.
                    </p>
                    <div className="settings-actions">
                      <button
                        className="btn btn-primary"
                        onClick={startQRFlow}
                        data-testid="wechat-qrcode-button"
                      >
                        Scan QR Code to Login
                      </button>
                      <button
                        className="btn btn-ghost"
                        onClick={startEditWechat}
                        data-testid="edit-wechat-button"
                      >
                        Manual Config
                      </button>
                    </div>
                  </div>
                )}

                {qrFlow === 'loading' && (
                  <div style={{ padding: '16px 0', textAlign: 'center' }}>
                    <div className="spinner" />
                    <p style={{ color: 'var(--text-secondary)', fontSize: 12, marginTop: 8 }}>
                      Fetching QR code...
                    </p>
                  </div>
                )}

                {(qrFlow === 'scanning' || qrFlow === 'scanned') && qrData && (
                  <div style={{ padding: '12px 0', textAlign: 'center' }}>
                    <div
                      style={{
                        display: 'inline-block',
                        padding: 16,
                        background: '#fff',
                        borderRadius: 'var(--radius)',
                        marginBottom: 12,
                      }}
                      data-testid="wechat-qrcode-display"
                    >
                      <QRCodeSVG value={qrData.imgContent} size={200} />
                    </div>
                    <p style={{ fontSize: 13, fontWeight: 500, marginBottom: 4 }}>
                      {qrFlow === 'scanned'
                        ? 'Scanned! Please confirm on your phone.'
                        : 'Scan this QR code with WeChat'}
                    </p>
                    <p style={{ color: 'var(--text-secondary)', fontSize: 11 }}>
                      Waiting for confirmation...
                    </p>
                    <button
                      className="btn btn-ghost btn-sm"
                      style={{ marginTop: 8 }}
                      onClick={resetQRFlow}
                    >
                      Cancel
                    </button>
                  </div>
                )}

                {qrFlow === 'confirmed' && (
                  <div style={{ padding: '16px 0', textAlign: 'center' }}>
                    <p style={{ fontSize: 14, fontWeight: 500, color: 'var(--success)', marginBottom: 8 }}>
                      Login successful!
                    </p>
                    <p style={{ color: 'var(--text-secondary)', fontSize: 12, marginBottom: 12 }}>
                      WeChat channel is now enabled and connected.
                    </p>
                    <button className="btn btn-ghost" onClick={resetQRFlow}>
                      Done
                    </button>
                  </div>
                )}

                {qrFlow === 'expired' && (
                  <div style={{ padding: '12px 0', textAlign: 'center' }}>
                    <p style={{ fontSize: 13, color: 'var(--error)', marginBottom: 8 }}>
                      QR code expired.
                    </p>
                    <button className="btn btn-primary" onClick={startQRFlow}>
                      Get New QR Code
                    </button>
                    <button className="btn btn-ghost" style={{ marginLeft: 8 }} onClick={resetQRFlow}>
                      Cancel
                    </button>
                  </div>
                )}

                {qrFlow === 'error' && (
                  <div style={{ padding: '12px 0', textAlign: 'center' }}>
                    <p style={{ fontSize: 13, color: 'var(--error)', marginBottom: 8 }}>
                      {qrError || 'Something went wrong'}
                    </p>
                    <button className="btn btn-primary" onClick={startQRFlow}>
                      Retry
                    </button>
                    <button className="btn btn-ghost" style={{ marginLeft: 8 }} onClick={resetQRFlow}>
                      Cancel
                    </button>
                  </div>
                )}
              </>
            )}

            {config?.wechat.enabled && (
              <div className="settings-actions" style={{ marginTop: 8 }}>
                <button className="btn btn-ghost" onClick={startEditWechat} data-testid="edit-wechat-button">
                  Edit
                </button>
              </div>
            )}
          </>
        )}

        {message?.channel === 'wechat' && (
          <p style={{ marginTop: 8, fontSize: 12.5, color: message.error ? 'var(--error)' : 'var(--success)' }}>
            {message.text}
          </p>
        )}
      </div>
    </div>
  )
}

import { useState, useEffect } from 'react'

interface ChannelConfig {
  qq: {
    enabled: boolean
    app_id: string
    allowed_guilds: string[]
    allowed_groups: string[]
  }
  wechat: {
    enabled: boolean
    weclaw_api_url: string
  }
}

interface ChannelStatus {
  connected: boolean
  error?: string
}

export function ChannelsPage() {
  const [config, setConfig] = useState<ChannelConfig | null>(null)
  const [qqStatus, setQqStatus] = useState<ChannelStatus | null>(null)
  const [wechatStatus, setWechatStatus] = useState<ChannelStatus | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const load = async () => {
      setLoading(true)
      try {
        const configRes = await fetch('/api/v1/config')
        if (configRes.ok) {
          const data = await configRes.json()
          setConfig(data.channels)
        }
      } catch { /* ignore */ }

      if (config?.qq.enabled || config?.wechat.enabled) {
        const [qqRes, wechatRes] = await Promise.allSettled([
          fetch('/api/v1/qq/status'),
          fetch('/api/v1/wechat/status'),
        ])
        if (qqRes.status === 'fulfilled' && qqRes.value.ok) {
          setQqStatus(await qqRes.value.json())
        } else {
          setQqStatus({ connected: false, error: 'Channel not available' })
        }
        if (wechatRes.status === 'fulfilled' && wechatRes.value.ok) {
          setWechatStatus(await wechatRes.value.json())
        } else {
          setWechatStatus({ connected: false, error: 'Channel not available' })
        }
      }
      setLoading(false)
    }
    void load()
  }, [])

  // Re-fetch status after config loads
  useEffect(() => {
    if (!config) return
    const fetchStatus = async () => {
      const promises: Promise<void>[] = []
      if (config.qq.enabled) {
        promises.push(
          fetch('/api/v1/qq/status')
            .then(res => res.ok ? res.json() : { connected: false, error: 'Channel not available' })
            .then(setQqStatus)
            .catch(() => setQqStatus({ connected: false, error: 'Channel not available' }))
        )
      }
      if (config.wechat.enabled) {
        promises.push(
          fetch('/api/v1/wechat/status')
            .then(res => res.ok ? res.json() : { connected: false, error: 'Channel not available' })
            .then(setWechatStatus)
            .catch(() => setWechatStatus({ connected: false, error: 'Channel not available' }))
        )
      }
      await Promise.allSettled(promises)
    }
    void fetchStatus()
  }, [config])

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
            QQ Bot is not enabled. Set <code>channels.qq.enabled: true</code> in thumbelina.yaml to enable.
          </p>
        )}
      </div>

      {/* WeChat Card */}
      <div className="card" data-testid="wechat-channel-card">
        <div className="card-title" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <span>WeChat / WeClaw</span>
          <span className={`badge ${config?.wechat.enabled ? 'badge-success' : 'badge-error'}`}>
            {config?.wechat.enabled ? 'enabled' : 'disabled'}
          </span>
        </div>

        {config?.wechat.enabled ? (
          <>
            <div className="chat-status" style={{ marginBottom: 12, borderRadius: 'var(--radius-sm)', padding: '6px 10px', fontSize: 12 }}>
              <span className={`dot ${wechatStatus?.connected ? 'connected' : 'disconnected'}`} />
              <span>{wechatStatus?.connected ? 'Connected' : wechatStatus?.error || 'Disconnected'}</span>
            </div>

            <div className="form-group">
              <label className="form-label">WeClaw API URL</label>
              <div className="form-input" style={{ opacity: 0.7, cursor: 'default' }}>
                {config.wechat.weclaw_api_url}
              </div>
            </div>
          </>
        ) : (
          <p style={{ color: 'var(--text-secondary)', fontSize: 12, padding: '8px 0' }}>
            WeChat is not enabled. Set <code>channels.wechat.enabled: true</code> in thumbelina.yaml to enable.
          </p>
        )}
      </div>
    </div>
  )
}

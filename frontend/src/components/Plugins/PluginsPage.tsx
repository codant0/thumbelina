import { useState, useEffect } from 'react'
import { Blocks, ShieldCheck, ShieldAlert, FileWarning } from 'lucide-react'

interface Plugin {
  id: string
  name: string
  description: string
  plugin_type: string
  version: string
  enabled: boolean
  sandbox?: {
    is_valid: boolean
    violation_count: number
  }
}

interface SandboxReport {
  plugin_name: string
  is_valid: boolean
  violations: { violation_type: string; message: string; line: number | null }[]
}

export function PluginsPage() {
  const [plugins, setPlugins] = useState<Plugin[]>([])
  const [report, setReport] = useState<SandboxReport[]>([])
  const [loading, setLoading] = useState(true)
  const [showReport, setShowReport] = useState(false)

  useEffect(() => {
    const load = async () => {
      setLoading(true)
      try {
        const [pluginsRes, reportRes] = await Promise.all([
          fetch('/api/v1/plugins'),
          fetch('/api/v1/plugins/sandbox-report'),
        ])
        if (pluginsRes.ok) setPlugins(await pluginsRes.json())
        if (reportRes.ok) {
          const data = await reportRes.json()
          setReport(data.report ?? [])
        }
      } catch { /* ignore */ } finally {
        setLoading(false)
      }
    }
    void load()
  }, [])

  if (loading) {
    return (
      <div className="page-container" data-testid="plugins-page">
        <div className="page-title">Plugins</div>
        <div className="loading-state"><div className="spinner" /><span>Loading...</span></div>
      </div>
    )
  }

  return (
    <div className="page-container" data-testid="plugins-page">
      <div className="page-title">Plugins</div>

      <div className="card">
        <div className="card-title card-title--between">
          <span><Blocks size={14} />Loaded Plugins ({plugins.length})</span>
          <button
            className="btn btn-ghost btn-sm"
            data-testid="toggle-report"
            onClick={() => setShowReport(v => !v)}
          >
            {showReport ? 'Hide' : 'Show'} Sandbox Report
          </button>
        </div>
        {plugins.length === 0 ? (
          <p className="task-empty">
            No plugins loaded. Configure plugin_dirs in thumbelina.yaml to load plugins.
          </p>
        ) : (
          <div className="task-list" data-testid="plugin-list">
            {plugins.map(plugin => (
              <div key={plugin.id} className="task-item" data-testid="plugin-item">
                <div className="task-info">
                  <div className="task-title">{plugin.name}</div>
                  <div className="task-meta">
                    <span className="badge badge-neutral">{plugin.plugin_type}</span>
                    <span className="badge badge-neutral">v{plugin.version}</span>
                    <span className={`badge ${plugin.enabled ? 'badge-success' : 'badge-error'}`}>
                      {plugin.enabled ? 'enabled' : 'disabled'}
                    </span>
                    {plugin.sandbox && (
                      <span className={`badge ${plugin.sandbox.is_valid ? 'badge-success' : 'badge-error'}`}>
                        {plugin.sandbox.is_valid ? <ShieldCheck size={12} /> : <ShieldAlert size={12} />}
                        {plugin.sandbox.is_valid ? 'sandbox ok' : `${plugin.sandbox.violation_count} violations`}
                      </span>
                    )}
                  </div>
                  {plugin.description && <div className="plugin-desc">{plugin.description}</div>}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {showReport && report.length > 0 && (
        <div className="card" data-testid="sandbox-report">
          <div className="card-title">Sandbox Validation Report</div>
          <div className="task-list">
            {report.map(entry => (
              <div key={entry.plugin_name} className="task-item search-result-item">
                <div className="task-info">
                  <div className="task-title">{entry.plugin_name}</div>
                  <div className="task-meta">
                    <span className={`badge ${entry.is_valid ? 'badge-success' : 'badge-error'}`}>
                      {entry.is_valid ? 'valid' : 'invalid'}
                    </span>
                    <span>{entry.violations.length} violations</span>
                  </div>
                  {entry.violations.length > 0 && (
                    <ul className="sandbox-report">
                      {entry.violations.map((v, i) => (
                        <li key={i}>
                          <FileWarning size={14} />
                          <span>
                            <span className={`badge ${v.violation_type === 'error' ? 'badge-error' : 'badge-warning'}`}>
                              {v.violation_type}
                            </span>
                            {' '}{v.message}
                            {v.line !== null && ` (line ${v.line})`}
                          </span>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

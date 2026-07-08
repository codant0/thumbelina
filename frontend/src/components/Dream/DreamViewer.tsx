import { useState, useEffect } from 'react'
import { RefreshCw } from 'lucide-react'

interface TimelineSkill {
  id: string
  name: string
  success_rate: number
}

interface TimelineEntry {
  date: string
  skills: TimelineSkill[]
}

interface TopSkill {
  id: string
  name: string
  version: number
  success_rate: number
}

interface Category {
  name: string
  count: number
}

interface SkillStats {
  total: number
  timeline: TimelineEntry[]
  top_skills: TopSkill[]
  categories: Category[]
}

const ACCENT_COLORS = [
  'var(--accent)',
  'var(--accent-secondary)',
  'var(--accent-hover)',
  'var(--accent-secondary-hover)',
]

export function DreamViewer() {
  const [stats, setStats] = useState<SkillStats | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const fetchStats = async () => {
    setLoading(true)
    setError('')
    try {
      const res = await fetch('/api/v1/skills/stats')
      if (res.ok) {
        setStats(await res.json())
      } else {
        setError('Failed to load skill statistics')
      }
    } catch {
      setError('Failed to load skill statistics')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void fetchStats() // eslint-disable-line react-hooks/set-state-in-effect
  }, [])

  if (loading) {
    return (
      <div className="page-container" data-testid="dream-viewer">
        <div className="page-title">Dream</div>
        <div className="loading-state" data-testid="dream-loading">
          <div className="spinner" />
          <span>Loading...</span>
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="page-container" data-testid="dream-viewer">
        <div className="page-title">Dream</div>
        <div className="error-state" data-testid="dream-error">
          <span>{error}</span>
          <button className="btn btn-ghost" data-testid="retry-button" onClick={fetchStats}>Retry</button>
        </div>
      </div>
    )
  }

  if (!stats || stats.total === 0) {
    return (
      <div className="page-container" data-testid="dream-viewer">
        <div className="page-title">Dream</div>
        <div className="empty-state" data-testid="dream-empty">
          <p>No skills recorded yet. Skills will appear here as the agent learns.</p>
        </div>
      </div>
    )
  }

  const maxBarValue = stats.top_skills.length > 0
    ? Math.max(...stats.top_skills.map(s => s.success_rate), 0.01)
    : 1

  const maxCatCount = stats.categories.length > 0
    ? Math.max(...stats.categories.map(c => c.count))
    : 1

  return (
    <div className="page-container" data-testid="dream-viewer">
      <div className="page-title-row">
        <div className="page-title">Dream</div>
        <button className="btn btn-ghost btn-sm" data-testid="refresh-button" onClick={fetchStats}>
          <RefreshCw size={14} />
          Refresh
        </button>
      </div>

      <div className="stats-grid">
        <div className="stat-card" data-testid="stat-total">
          <div className="stat-value">{stats.total}</div>
          <div className="stat-label">Skills</div>
        </div>
        <div className="stat-card" data-testid="stat-categories">
          <div className="stat-value">{stats.categories.length}</div>
          <div className="stat-label">Categories</div>
        </div>
        <div className="stat-card" data-testid="stat-timeline">
          <div className="stat-value">{stats.timeline.length}</div>
          <div className="stat-label">Active Days</div>
        </div>
      </div>

      <div className="card" data-testid="skill-timeline">
        <div className="card-title">Timeline</div>
        <div className="timeline">
          {stats.timeline.map((entry, idx) => {
            const color = ACCENT_COLORS[idx % ACCENT_COLORS.length]
            return (
              <div key={entry.date} className="timeline-entry" data-testid="timeline-entry">
                <div className="timeline-date">{entry.date}</div>
                <div className="timeline-skills">
                  {entry.skills.map(skill => (
                    <span
                      key={skill.id}
                      className="badge"
                      style={{
                        background: `color-mix(in srgb, ${color} 14%, transparent)`,
                        color,
                        border: `1px solid color-mix(in srgb, ${color} 30%, transparent)`,
                      }}
                    >
                      {skill.name}
                      {skill.success_rate > 0 && ` ${(skill.success_rate * 100).toFixed(0)}%`}
                    </span>
                  ))}
                </div>
              </div>
            )
          })}
        </div>
      </div>

      <div className="card" data-testid="skill-chart">
        <div className="card-title">Top Skills by Maturity</div>
        <div className="bar-chart">
          {stats.top_skills.map((skill, idx) => (
            <div key={skill.id} className="bar-row" data-testid="bar-row">
              <div className="bar-label">{skill.name}</div>
              <div className="bar-track">
                <div
                  className="bar-fill"
                  data-testid="bar-fill"
                  style={{
                    width: `${(skill.success_rate / maxBarValue) * 100}%`,
                    background: ACCENT_COLORS[idx % ACCENT_COLORS.length],
                    transitionDelay: `${idx * 80}ms`,
                  }}
                />
              </div>
              <div className="bar-value">v{skill.version}</div>
            </div>
          ))}
        </div>
      </div>

      <div className="card" data-testid="skill-categories">
        <div className="card-title">Categories</div>
        <div className="bar-chart">
          {stats.categories.map((cat, idx) => (
            <div key={cat.name} className="bar-row" data-testid="category-row">
              <div className="bar-label">{cat.name}</div>
              <div className="bar-track">
                <div
                  className="bar-fill"
                  style={{
                    width: `${(cat.count / maxCatCount) * 100}%`,
                    background: ACCENT_COLORS[idx % ACCENT_COLORS.length],
                    transitionDelay: `${idx * 80}ms`,
                  }}
                />
              </div>
              <div className="bar-value">{cat.count}</div>
            </div>
          ))}
        </div>
      </div>

      <div className="card" data-testid="skill-cloud">
        <div className="card-title">Skill Cloud</div>
        <div className="word-cloud">
          {stats.top_skills.map((skill, idx) => {
            const size = 0.85 + (skill.success_rate / maxBarValue) * 1.2
            return (
              <span
                key={skill.id}
                className="word"
                data-testid="cloud-word"
                style={{
                  fontSize: `${size}rem`,
                  color: ACCENT_COLORS[idx % ACCENT_COLORS.length],
                }}
              >
                {skill.name}
              </span>
            )
          })}
        </div>
      </div>
    </div>
  )
}

import { useState, useEffect } from 'react'

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

const TIMELINE_COLORS = [
  '#6366f1', '#8b5cf6', '#a78bfa', '#c4b5fd',
  '#818cf8', '#a5b4fc', '#c7d2fe',
]

const BAR_COLORS = [
  '#f472b6', '#fb923c', '#facc15', '#34d399',
  '#22d3ee', '#60a5fa', '#a78bfa', '#f87171',
  '#4ade80', '#fbbf24',
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
      <div data-testid="dream-viewer" className="dream-viewer">
        <h2>Dream Visualization</h2>
        <div data-testid="dream-loading" className="dream-loading">
          <div className="loading-spinner" />
          <p>Loading dream data...</p>
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div data-testid="dream-viewer" className="dream-viewer">
        <h2>Dream Visualization</h2>
        <div data-testid="dream-error" className="dream-error">
          <p>{error}</p>
          <button data-testid="retry-button" onClick={fetchStats}>
            Retry
          </button>
        </div>
      </div>
    )
  }

  if (!stats || stats.total === 0) {
    return (
      <div data-testid="dream-viewer" className="dream-viewer">
        <h2>Dream Visualization</h2>
        <div data-testid="dream-empty" className="dream-empty">
          <p>No skills recorded yet. Skills will appear here as the agent learns.</p>
        </div>
      </div>
    )
  }

  const maxBarValue = stats.top_skills.length > 0
    ? Math.max(...stats.top_skills.map(s => s.version))
    : 1

  const maxCatCount = stats.categories.length > 0
    ? Math.max(...stats.categories.map(c => c.count))
    : 1

  return (
    <div data-testid="dream-viewer" className="dream-viewer">
      <h2>Dream Visualization</h2>

      <div className="dream-stats-summary">
        <div className="stat-card" data-testid="stat-total">
          <span className="stat-value">{stats.total}</span>
          <span className="stat-label">Total Skills</span>
        </div>
        <div className="stat-card" data-testid="stat-categories">
          <span className="stat-value">{stats.categories.length}</span>
          <span className="stat-label">Categories</span>
        </div>
        <div className="stat-card" data-testid="stat-timeline">
          <span className="stat-value">{stats.timeline.length}</span>
          <span className="stat-label">Active Days</span>
        </div>
      </div>

      {/* Skill Timeline */}
      <section data-testid="skill-timeline" className="dream-section">
        <h3>Skill Timeline</h3>
        <div className="timeline">
          {stats.timeline.map((entry, idx) => (
            <div key={entry.date} className="timeline-entry" data-testid="timeline-entry">
              <div
                className="timeline-dot"
                style={{ backgroundColor: TIMELINE_COLORS[idx % TIMELINE_COLORS.length] }}
              />
              <div className="timeline-content">
                <div className="timeline-date">{entry.date}</div>
                <div className="timeline-skills">
                  {entry.skills.map(skill => (
                    <span key={skill.id} className="timeline-skill-tag">
                      {skill.name}
                      {skill.success_rate > 0 && (
                        <span className="skill-rate">
                          {(skill.success_rate * 100).toFixed(0)}%
                        </span>
                      )}
                    </span>
                  ))}
                </div>
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* Skill Usage Chart */}
      <section data-testid="skill-chart" className="dream-section">
        <h3>Top Skills by Maturity</h3>
        <div className="bar-chart">
          {stats.top_skills.map((skill, idx) => (
            <div key={skill.id} className="bar-row" data-testid="bar-row">
              <div className="bar-label">{skill.name}</div>
              <div className="bar-track">
                <div
                  className="bar-fill"
                  data-testid="bar-fill"
                  style={{
                    width: `${(skill.version / maxBarValue) * 100}%`,
                    backgroundColor: BAR_COLORS[idx % BAR_COLORS.length],
                    animationDelay: `${idx * 0.1}s`,
                  }}
                />
              </div>
              <div className="bar-value">v{skill.version}</div>
            </div>
          ))}
        </div>
      </section>

      {/* Skill Categories */}
      <section data-testid="skill-categories" className="dream-section">
        <h3>Skill Categories</h3>
        <div className="category-chart">
          {stats.categories.map((cat, idx) => (
            <div key={cat.name} className="category-row" data-testid="category-row">
              <div className="category-label">{cat.name}</div>
              <div className="category-track">
                <div
                  className="category-fill"
                  style={{
                    width: `${(cat.count / maxCatCount) * 100}%`,
                    backgroundColor: TIMELINE_COLORS[idx % TIMELINE_COLORS.length],
                    animationDelay: `${idx * 0.15}s`,
                  }}
                />
              </div>
              <div className="category-count">{cat.count}</div>
            </div>
          ))}
        </div>
      </section>

      {/* Skill Cloud */}
      <section data-testid="skill-cloud" className="dream-section">
        <h3>Skill Cloud</h3>
        <div className="skill-cloud">
          {stats.top_skills.map((skill, idx) => {
            const size = 0.8 + (skill.version / maxBarValue) * 1.4
            return (
              <span
                key={skill.id}
                className="cloud-word"
                data-testid="cloud-word"
                style={{
                  fontSize: `${size}rem`,
                  color: BAR_COLORS[idx % BAR_COLORS.length],
                  animationDelay: `${idx * 0.2}s`,
                }}
              >
                {skill.name}
              </span>
            )
          })}
        </div>
      </section>

      <style>{`
        .dream-viewer {
          flex: 1;
          padding: 1.5rem;
          overflow-y: auto;
          max-height: calc(100vh - 4rem);
        }

        .dream-viewer h2 {
          margin-bottom: 1.5rem;
          color: #e2e8f0;
        }

        .dream-section {
          margin-bottom: 2rem;
          background: rgba(30, 41, 59, 0.6);
          border-radius: 12px;
          padding: 1.25rem;
          border: 1px solid rgba(99, 102, 241, 0.15);
        }

        .dream-section h3 {
          margin-bottom: 1rem;
          color: #a5b4fc;
          font-size: 1.1rem;
        }

        /* Loading */
        .dream-loading {
          display: flex;
          flex-direction: column;
          align-items: center;
          gap: 1rem;
          padding: 3rem;
          color: #94a3b8;
        }

        .loading-spinner {
          width: 40px;
          height: 40px;
          border: 3px solid rgba(99, 102, 241, 0.2);
          border-top-color: #6366f1;
          border-radius: 50%;
          animation: spin 0.8s linear infinite;
        }

        @keyframes spin {
          to { transform: rotate(360deg); }
        }

        /* Error */
        .dream-error {
          text-align: center;
          padding: 2rem;
          color: #f87171;
        }

        .dream-error button {
          margin-top: 1rem;
          padding: 0.5rem 1.5rem;
          background: #6366f1;
          color: white;
          border: none;
          border-radius: 6px;
          cursor: pointer;
        }

        .dream-error button:hover {
          background: #4f46e5;
        }

        /* Empty */
        .dream-empty {
          text-align: center;
          padding: 3rem;
          color: #94a3b8;
        }

        /* Stats Summary */
        .dream-stats-summary {
          display: flex;
          gap: 1rem;
          margin-bottom: 1.5rem;
        }

        .stat-card {
          flex: 1;
          background: rgba(30, 41, 59, 0.8);
          border-radius: 10px;
          padding: 1rem;
          text-align: center;
          border: 1px solid rgba(99, 102, 241, 0.2);
          animation: fadeInUp 0.5s ease-out both;
        }

        .stat-card:nth-child(2) { animation-delay: 0.1s; }
        .stat-card:nth-child(3) { animation-delay: 0.2s; }

        .stat-value {
          display: block;
          font-size: 2rem;
          font-weight: 700;
          color: #a78bfa;
        }

        .stat-label {
          display: block;
          font-size: 0.85rem;
          color: #94a3b8;
          margin-top: 0.25rem;
        }

        /* Timeline */
        .timeline {
          position: relative;
          padding-left: 2rem;
        }

        .timeline::before {
          content: '';
          position: absolute;
          left: 8px;
          top: 0;
          bottom: 0;
          width: 2px;
          background: linear-gradient(to bottom, #6366f1, #a78bfa, #c4b5fd);
        }

        .timeline-entry {
          position: relative;
          margin-bottom: 1.5rem;
          animation: fadeInLeft 0.5s ease-out both;
        }

        .timeline-entry:nth-child(1) { animation-delay: 0.1s; }
        .timeline-entry:nth-child(2) { animation-delay: 0.2s; }
        .timeline-entry:nth-child(3) { animation-delay: 0.3s; }
        .timeline-entry:nth-child(4) { animation-delay: 0.4s; }
        .timeline-entry:nth-child(5) { animation-delay: 0.5s; }

        .timeline-dot {
          position: absolute;
          left: -2rem;
          top: 0.25rem;
          width: 14px;
          height: 14px;
          border-radius: 50%;
          border: 2px solid #1e293b;
          animation: pulse 2s ease-in-out infinite;
        }

        @keyframes pulse {
          0%, 100% { box-shadow: 0 0 0 0 rgba(99, 102, 241, 0.4); }
          50% { box-shadow: 0 0 0 6px rgba(99, 102, 241, 0); }
        }

        .timeline-date {
          font-size: 0.85rem;
          color: #94a3b8;
          margin-bottom: 0.35rem;
        }

        .timeline-skills {
          display: flex;
          flex-wrap: wrap;
          gap: 0.5rem;
        }

        .timeline-skill-tag {
          background: rgba(99, 102, 241, 0.15);
          color: #c7d2fe;
          padding: 0.25rem 0.75rem;
          border-radius: 9999px;
          font-size: 0.8rem;
          border: 1px solid rgba(99, 102, 241, 0.25);
        }

        .skill-rate {
          margin-left: 0.35rem;
          color: #34d399;
          font-size: 0.7rem;
        }

        /* Bar Chart */
        .bar-chart {
          display: flex;
          flex-direction: column;
          gap: 0.75rem;
        }

        .bar-row {
          display: flex;
          align-items: center;
          gap: 0.75rem;
        }

        .bar-label {
          width: 140px;
          font-size: 0.85rem;
          color: #cbd5e1;
          text-align: right;
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }

        .bar-track {
          flex: 1;
          height: 24px;
          background: rgba(15, 23, 42, 0.5);
          border-radius: 4px;
          overflow: hidden;
        }

        .bar-fill {
          height: 100%;
          border-radius: 4px;
          animation: growBar 0.8s ease-out both;
          min-width: 4px;
        }

        @keyframes growBar {
          from { width: 0 !important; }
        }

        .bar-value {
          width: 40px;
          font-size: 0.8rem;
          color: #94a3b8;
          text-align: left;
        }

        /* Category Chart */
        .category-chart {
          display: flex;
          flex-direction: column;
          gap: 0.6rem;
        }

        .category-row {
          display: flex;
          align-items: center;
          gap: 0.75rem;
        }

        .category-label {
          width: 100px;
          font-size: 0.85rem;
          color: #cbd5e1;
          text-align: right;
        }

        .category-track {
          flex: 1;
          height: 20px;
          background: rgba(15, 23, 42, 0.5);
          border-radius: 4px;
          overflow: hidden;
        }

        .category-fill {
          height: 100%;
          border-radius: 4px;
          animation: growBar 0.8s ease-out both;
          min-width: 4px;
        }

        .category-count {
          width: 30px;
          font-size: 0.8rem;
          color: #94a3b8;
          text-align: left;
        }

        /* Skill Cloud */
        .skill-cloud {
          display: flex;
          flex-wrap: wrap;
          gap: 0.75rem;
          justify-content: center;
          align-items: center;
          padding: 1rem;
          min-height: 100px;
        }

        .cloud-word {
          font-weight: 600;
          padding: 0.25rem 0.5rem;
          animation: floatIn 0.6s ease-out both;
          cursor: default;
          transition: transform 0.2s;
        }

        .cloud-word:hover {
          transform: scale(1.15);
        }

        @keyframes floatIn {
          from {
            opacity: 0;
            transform: translateY(10px) scale(0.8);
          }
          to {
            opacity: 1;
            transform: translateY(0) scale(1);
          }
        }

        @keyframes fadeInUp {
          from {
            opacity: 0;
            transform: translateY(12px);
          }
          to {
            opacity: 1;
            transform: translateY(0);
          }
        }

        @keyframes fadeInLeft {
          from {
            opacity: 0;
            transform: translateX(-12px);
          }
          to {
            opacity: 1;
            transform: translateX(0);
          }
        }
      `}</style>
    </div>
  )
}

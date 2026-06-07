import { useState, useCallback } from 'react'

interface SearchResult {
  conversation_id: string
  content: string
  role: string
}

interface Skill {
  id: string
  name: string
  description: string
  trigger_conditions: string[]
  steps: string[]
  version: number
  success_rate: number
}

export function MemoryViewer() {
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<SearchResult[]>([])
  const [skills, setSkills] = useState<Skill[]>([])
  const [searching, setSearching] = useState(false)
  const [skillsLoaded, setSkillsLoaded] = useState(false)
  const [error, setError] = useState('')

  const handleSearch = useCallback(async () => {
    if (!query.trim()) return
    setSearching(true)
    setError('')
    try {
      const res = await fetch(`/api/v1/conversations/search/${encodeURIComponent(query.trim())}`)
      if (res.ok) {
        setResults(await res.json())
      } else {
        setError('Search failed')
      }
    } catch {
      setError('Search failed')
    } finally {
      setSearching(false)
    }
  }, [query])

  const handleLoadSkills = useCallback(async () => {
    try {
      const res = await fetch('/api/v1/skills')
      if (res.ok) {
        setSkills(await res.json())
        setSkillsLoaded(true)
      }
    } catch { /* ignore */ }
  }, [])

  return (
    <div className="page-container" data-testid="memory-viewer">
      <div className="page-title">Memory</div>

      <div className="card">
        <div className="card-title">Search Conversations</div>
        <div className="search-bar">
          <input
            type="text"
            className="form-input"
            data-testid="search-input"
            placeholder="Search messages..."
            value={query}
            onChange={e => setQuery(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') void handleSearch() }}
          />
          <button
            className="btn btn-primary"
            data-testid="search-button"
            onClick={handleSearch}
            disabled={searching}
          >
            {searching ? 'Searching...' : 'Search'}
          </button>
        </div>
        {error && <p data-testid="search-error" style={{ color: 'var(--error)', fontSize: 12, marginBottom: 8 }}>{error}</p>}
        <div data-testid="search-results">
          {results.length === 0 && query && !searching ? (
            <p style={{ color: 'var(--text-secondary)', fontSize: 12, padding: '8px 0' }}>No results found</p>
          ) : (
            results.map((r, i) => (
              <div key={i} data-testid="search-result-item" className="task-item" style={{ marginBottom: 6, alignItems: 'flex-start' }}>
                <div className="task-info">
                  <div className="task-title" style={{ whiteSpace: 'pre-wrap', overflow: 'visible', textOverflow: 'unset' }}>{r.content}</div>
                  <div className="task-meta">
                    <span className={`badge ${r.role === 'user' ? 'badge-neutral' : 'badge-success'}`}>{r.role}</span>
                    <span>Conv: {r.conversation_id.slice(0, 8)}</span>
                  </div>
                </div>
              </div>
            ))
          )}
        </div>
      </div>

      <div className="card">
        <div className="card-title" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <span>Skills</span>
          <button
            className="btn btn-ghost btn-sm"
            data-testid="load-skills-button"
            onClick={handleLoadSkills}
            disabled={skillsLoaded}
          >
            {skillsLoaded ? 'Loaded' : 'Load Skills'}
          </button>
        </div>
        <div className="skill-grid" data-testid="skills-list">
          {skills.length === 0 && skillsLoaded ? (
            <p style={{ color: 'var(--text-secondary)', fontSize: 12, padding: '8px 0' }}>No skills found</p>
          ) : (
            skills.map(skill => (
              <div key={skill.id} className="skill-card" data-testid="skill-item">
                <div className="skill-name">{skill.name}</div>
                <div className="skill-desc">{skill.description}</div>
                <div className="skill-meta">
                  <span className="badge badge-neutral">v{skill.version}</span>
                  <span className="badge badge-success">{(skill.success_rate * 100).toFixed(0)}%</span>
                  {skill.trigger_conditions.length > 0 && (
                    <span className="badge badge-neutral" title={skill.trigger_conditions.join(', ')}>
                      {skill.trigger_conditions.length} triggers
                    </span>
                  )}
                </div>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  )
}

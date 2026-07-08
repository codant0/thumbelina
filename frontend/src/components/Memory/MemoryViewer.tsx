import { useState, useCallback } from 'react'
import { Search, Sparkles, Layers, Loader2 } from 'lucide-react'

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

interface Composition {
  id: string
  name: string
  description: string
  skill_ids: string[]
  trigger_patterns: string[]
  usage_count: number
  created_at: string
}

export function MemoryViewer() {
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<SearchResult[]>([])
  const [skills, setSkills] = useState<Skill[]>([])
  const [compositions, setCompositions] = useState<Composition[]>([])
  const [searching, setSearching] = useState(false)
  const [skillsLoaded, setSkillsLoaded] = useState(false)
  const [compositionsLoaded, setCompositionsLoaded] = useState(false)
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

  const handleLoadCompositions = useCallback(async () => {
    try {
      const res = await fetch('/api/v1/compositions')
      if (res.ok) {
        setCompositions(await res.json())
        setCompositionsLoaded(true)
      }
    } catch { /* ignore */ }
  }, [])

  return (
    <div className="page-container" data-testid="memory-viewer">
      <div className="page-title">Memory</div>

      <div className="card">
        <div className="card-title"><Search size={14} />Search Conversations</div>
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
            {searching ? <Loader2 size={16} className="spin" /> : <Search size={16} />}
            {searching ? 'Searching...' : 'Search'}
          </button>
        </div>
        {error && <p data-testid="search-error" className="task-empty" style={{ color: 'var(--error)' }}>{error}</p>}
        <div data-testid="search-results">
          {results.length === 0 && query && !searching ? (
            <p className="task-empty">No results found</p>
          ) : (
            results.map((r, i) => (
              <div key={i} data-testid="search-result-item" className="task-item search-result-item">
                <div className="task-info">
                  <div className="task-title search-result-content">{r.content}</div>
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
        <div className="card-title card-title--between">
          <span><Sparkles size={14} />Skills</span>
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
            <p className="task-empty">No skills found</p>
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

      {/* Skill Compositions */}
      <div className="card">
        <div className="card-title card-title--between">
          <span><Layers size={14} />Skill Compositions</span>
          <button
            className="btn btn-ghost btn-sm"
            data-testid="load-compositions-button"
            onClick={handleLoadCompositions}
            disabled={compositionsLoaded}
          >
            {compositionsLoaded ? 'Loaded' : 'Load Compositions'}
          </button>
        </div>
        <div data-testid="compositions-list">
          {compositions.length === 0 && compositionsLoaded ? (
            <p className="task-empty">No compositions found</p>
          ) : (
            compositions.map(comp => (
              <div key={comp.id} className="task-item search-result-item" data-testid="composition-item">
                <div className="task-info">
                  <div className="task-title">{comp.name}</div>
                  <div className="task-meta">
                    <span className="badge badge-neutral">{comp.skill_ids.length} skills</span>
                    <span className="badge badge-neutral">used {comp.usage_count}x</span>
                    {comp.trigger_patterns.length > 0 && (
                      <span className="badge badge-neutral" title={comp.trigger_patterns.join(', ')}>
                        {comp.trigger_patterns.length} triggers
                      </span>
                    )}
                  </div>
                  {comp.description && (
                    <div className="task-desc">{comp.description}</div>
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

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
      const res = await fetch(
        `/api/v1/conversations/search/${encodeURIComponent(query.trim())}`,
      )
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
    } catch {
      // ignore
    }
  }, [])

  return (
    <div data-testid="memory-viewer">
      <h2>Memory Viewer</h2>

      <section>
        <h3>Search Conversations</h3>
        <div>
          <input
            type="text"
            data-testid="search-input"
            placeholder="Search messages..."
            value={query}
            onChange={e => setQuery(e.target.value)}
            onKeyDown={e => {
              if (e.key === 'Enter') handleSearch()
            }}
          />
          <button
            data-testid="search-button"
            onClick={handleSearch}
            disabled={searching}
          >
            {searching ? 'Searching...' : 'Search'}
          </button>
        </div>
        {error && <p data-testid="search-error">{error}</p>}
        <div data-testid="search-results">
          {results.length === 0 && query && !searching ? (
            <p>No results found</p>
          ) : (
            results.map((r, i) => (
              <div key={i} data-testid="search-result-item">
                <span>{r.role}</span>
                <p>{r.content}</p>
                <small>Conversation: {r.conversation_id}</small>
              </div>
            ))
          )}
        </div>
      </section>

      <section>
        <h3>Skills</h3>
        <button
          data-testid="load-skills-button"
          onClick={handleLoadSkills}
          disabled={skillsLoaded}
        >
          {skillsLoaded ? 'Skills Loaded' : 'Load Skills'}
        </button>
        <div data-testid="skills-list">
          {skills.length === 0 && skillsLoaded ? (
            <p>No skills found</p>
          ) : (
            skills.map(skill => (
              <div key={skill.id} data-testid="skill-item">
                <strong>{skill.name}</strong>
                <p>{skill.description}</p>
                <div>
                  <span>Triggers: {skill.trigger_conditions.join(', ')}</span>
                </div>
                <div>
                  <span>Success rate: {(skill.success_rate * 100).toFixed(0)}%</span>
                </div>
                <div>
                  <span>Version: {skill.version}</span>
                </div>
              </div>
            ))
          )}
        </div>
      </section>
    </div>
  )
}

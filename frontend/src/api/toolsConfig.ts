export interface WebSearchConfig {
  enabled: boolean
  provider: 'tavily' | 'duckduckgo'
  /** Whether an API key is currently set (the key itself is never returned). */
  api_key_set: boolean
}

export interface ToolsConfig {
  web_search: WebSearchConfig
}

const API_BASE = '/api/v1'

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
  if (!res.ok) {
    const data = await res.json().catch(() => ({}))
    throw new Error(data.detail || `HTTP ${res.status}`)
  }
  return res.json() as Promise<T>
}

export async function fetchToolsConfig(): Promise<ToolsConfig> {
  return request<ToolsConfig>('/config/tools')
}

export async function updateWebSearchConfig(data: {
  enabled?: boolean
  provider?: 'tavily' | 'duckduckgo'
  api_key?: string
}): Promise<WebSearchConfig> {
  return request<WebSearchConfig>('/config/tools/web_search', {
    method: 'PUT',
    body: JSON.stringify(data),
  })
}
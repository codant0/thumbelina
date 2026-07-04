export interface LLMEndpoint {
  id: string
  provider: 'openai' | 'ollama' | 'anthropic'
  name: string
  base_url: string
  api_key_set: boolean
  is_default: boolean
  last_latency_ms?: number
  last_total_ms?: number
  is_reachable?: boolean
  last_tested_at?: string
}

export interface EndpointFormData {
  provider: 'openai' | 'ollama' | 'anthropic'
  name: string
  base_url: string
  api_key: string
  is_default: boolean
}

export interface SpeedTestResult {
  endpoint_id: string
  reachable: boolean
  latency_ms?: number
  total_ms?: number
  error?: string
}

export interface ModelList {
  provider: string
  base_url: string
  models: string[]
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

export async function fetchEndpoints(provider?: string): Promise<LLMEndpoint[]> {
  const query = provider ? `?provider=${encodeURIComponent(provider)}` : ''
  return request<LLMEndpoint[]>(`/config/llm/endpoints${query}`)
}

export async function createEndpoint(data: EndpointFormData): Promise<LLMEndpoint> {
  return request<LLMEndpoint>('/config/llm/endpoints', {
    method: 'POST',
    body: JSON.stringify(data),
  })
}

export async function updateEndpoint(id: string, data: Partial<EndpointFormData>): Promise<LLMEndpoint> {
  return request<LLMEndpoint>(`/config/llm/endpoints/${id}`, {
    method: 'PUT',
    body: JSON.stringify(data),
  })
}

export async function deleteEndpoint(id: string): Promise<void> {
  await request<void>(`/config/llm/endpoints/${id}`, { method: 'DELETE' })
}

export async function runSpeedTest(id: string, model: string): Promise<SpeedTestResult> {
  return request<SpeedTestResult>(`/config/llm/endpoints/${id}/speed-test?model=${encodeURIComponent(model)}`)
}

export async function fetchModels(params: { provider: string; base_url: string; api_key?: string }): Promise<ModelList> {
  const query = new URLSearchParams()
  query.set('provider', params.provider)
  query.set('base_url', params.base_url)
  if (params.api_key) query.set('api_key', params.api_key)
  return request<ModelList>(`/config/llm/models?${query.toString()}`)
}

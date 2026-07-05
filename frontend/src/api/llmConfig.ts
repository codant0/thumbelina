export interface LLMEndpoint {
  id: string
  provider: 'openai' | 'ollama' | 'anthropic'
  name: string
  base_url: string
  model: string
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
  model: string
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

export interface ConnectionTestStep {
  ok: boolean
  latency_ms?: number
  error?: string
}

export interface ConnectionTestDetails {
  network: ConnectionTestStep
  auth: ConnectionTestStep
  service: ConnectionTestStep
}

export interface ConnectionTestResult {
  provider: string
  base_url: string
  endpoint_id?: string
  reachable: boolean
  network_reachable: boolean
  auth_valid: boolean
  service_available: boolean
  latency_ms?: number
  error?: string
  details?: ConnectionTestDetails
}

export interface LLMPreset {
  id: string
  name: string
  provider: 'openai' | 'ollama' | 'anthropic'
  base_url: string
  api_key_set: boolean
  model: string
  extra_params: Record<string, unknown>
  is_active: boolean
  created_at: string
  updated_at: string
}

export interface PresetFormData {
  name: string
  provider: 'openai' | 'ollama' | 'anthropic'
  base_url: string
  api_key: string
  model: string
  extra_params: Record<string, unknown>
  is_active: boolean
}

export interface PresetActivateResponse {
  status: string
  preset_id: string
  preset_name: string
  provider: string
  model: string
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
  return request<SpeedTestResult>(`/config/llm/endpoints/${id}/speed-test?model=${encodeURIComponent(model)}`, {
    method: 'POST',
  })
}

export async function fetchModels(params: { provider: string; base_url: string; api_key?: string }): Promise<ModelList> {
  const query = new URLSearchParams()
  query.set('provider', params.provider)
  query.set('base_url', params.base_url)
  if (params.api_key) query.set('api_key', params.api_key)
  return request<ModelList>(`/config/llm/models?${query.toString()}`)
}

export async function testConnection(params: {
  provider: string
  base_url: string
  api_key?: string
  model?: string
}): Promise<ConnectionTestResult> {
  return request<ConnectionTestResult>('/config/llm/test-connection', {
    method: 'POST',
    body: JSON.stringify(params),
  })
}

export async function testEndpointConnection(
  endpointId: string,
  model?: string,
): Promise<ConnectionTestResult> {
  const query = model ? `?model=${encodeURIComponent(model)}` : ''
  return request<ConnectionTestResult>(`/config/llm/endpoints/${endpointId}/test-connection${query}`, {
    method: 'POST',
  })
}

export async function fetchPresets(): Promise<LLMPreset[]> {
  return request<LLMPreset[]>('/config/llm/presets')
}

export async function createPreset(data: PresetFormData): Promise<LLMPreset> {
  return request<LLMPreset>('/config/llm/presets', {
    method: 'POST',
    body: JSON.stringify(data),
  })
}

export async function updatePreset(id: string, data: Partial<PresetFormData>): Promise<LLMPreset> {
  return request<LLMPreset>(`/config/llm/presets/${id}`, {
    method: 'PUT',
    body: JSON.stringify(data),
  })
}

export async function deletePreset(id: string): Promise<void> {
  await request<void>(`/config/llm/presets/${id}`, { method: 'DELETE' })
}

export async function activatePreset(id: string): Promise<PresetActivateResponse> {
  return request<PresetActivateResponse>(`/config/llm/presets/${id}/activate`, {
    method: 'POST',
  })
}

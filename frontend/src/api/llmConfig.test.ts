import { describe, it, expect, vi, beforeEach } from 'vitest'
import { fetchEndpoints, createEndpoint } from './llmConfig'

describe('llmConfig API', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('fetchEndpoints returns parsed endpoints', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify([{ id: '1', provider: 'openai', name: 'Default', base_url: 'https://api.openai.com/v1', models: [{ name: 'gpt-4o', context_window: null, multimodal: false }], api_key_set: true, is_default: true }]), { status: 200 }),
    )
    const endpoints = await fetchEndpoints()
    expect(endpoints).toHaveLength(1)
    expect(endpoints[0].name).toBe('Default')
    expect(endpoints[0].models).toEqual([{ name: 'gpt-4o', context_window: null, multimodal: false }])
  })

  it('createEndpoint sends api_key in body', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ id: '1', provider: 'openai', name: 'Default', base_url: 'https://api.openai.com/v1', models: [{ name: 'gpt-4o', context_window: null, multimodal: false }], api_key_set: true, is_default: false }), { status: 201 }),
    )
    await createEndpoint({
      provider: 'openai',
      name: 'Default',
      base_url: 'https://api.openai.com/v1',
      models: [{ name: 'gpt-4o', context_window: null, multimodal: false }],
      api_key: 'sk-test',
      is_default: false,
    })
    const [, init] = fetchSpy.mock.calls[0]
    const body = JSON.parse(init?.body as string)
    expect(body.api_key).toBe('sk-test')
    expect(body.models).toEqual([{ name: 'gpt-4o', context_window: null, multimodal: false }])
  })

  it('throws error with backend detail', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ detail: 'Invalid URL' }), { status: 422 }),
    )
    await expect(createEndpoint({ provider: 'openai', name: 'x', base_url: 'bad', models: [], api_key: '', is_default: false })).rejects.toThrow('Invalid URL')
  })
})

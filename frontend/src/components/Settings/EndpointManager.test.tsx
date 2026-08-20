import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { EndpointManager } from './EndpointManager'

const mockEndpoints = [
  { id: '1', provider: 'openai', name: 'Default', base_url: 'https://api.openai.com/v1', models: [{ name: 'gpt-4o', context_window: null, multimodal: false }], active_model: 'gpt-4o', api_key_set: true, is_default: true },
]

describe('EndpointManager', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    vi.spyOn(globalThis, 'fetch').mockImplementation((url) => {
      const urlStr = typeof url === 'string' ? url : url.toString()
      if (urlStr.includes('/config/llm/endpoints')) {
        return Promise.resolve(new Response(JSON.stringify(mockEndpoints), { status: 200 }))
      }
      return Promise.resolve(new Response('{}', { status: 200 }))
    })
  })

  it('renders endpoint list after loading', async () => {
    render(<EndpointManager onMessage={vi.fn()} />)
    await waitFor(() => {
      expect(screen.getByText('Default')).toBeInTheDocument()
    })
  })

  it('opens form on add endpoint click', async () => {
    render(<EndpointManager onMessage={vi.fn()} />)
    await waitFor(() => {
      expect(screen.getByTestId('add-endpoint-button')).toBeInTheDocument()
    })
    fireEvent.click(screen.getByTestId('add-endpoint-button'))
    await waitFor(() => {
      expect(screen.getByTestId('endpoint-form')).toBeInTheDocument()
    })
  })

  it('omits empty api_key on update to preserve stored key', async () => {
    render(<EndpointManager onMessage={vi.fn()} />)
    await waitFor(() => {
      expect(screen.getByText('Default')).toBeInTheDocument()
    })
    fireEvent.click(screen.getByTestId('edit-1'))
    await waitFor(() => {
      expect(screen.getByTestId('endpoint-form')).toBeInTheDocument()
    })
    fireEvent.click(screen.getByTestId('endpoint-form-submit'))
    await waitFor(() => {
      const calls = vi.mocked(globalThis.fetch).mock.calls as [string, RequestInit][]
      const put = calls.find(
        ([url, init]) =>
          typeof url === 'string' &&
          url.includes('/config/llm/endpoints/') &&
          init?.method === 'PUT',
      )
      expect(put).toBeTruthy()
      const body = JSON.parse((put![1]?.body as string) ?? '{}')
      expect(body).not.toHaveProperty('api_key')
    })
  })
})

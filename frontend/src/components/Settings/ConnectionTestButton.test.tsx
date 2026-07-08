import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { ConnectionTestButton } from './ConnectionTestButton'

describe('ConnectionTestButton', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('uses saved endpoint key when api_key is empty (edit mode)', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ provider: 'openai', base_url: 'https://api.openai.com/v1', reachable: true }), { status: 200 }),
    )
    render(
      <ConnectionTestButton
        provider="openai"
        base_url="https://api.openai.com/v1"
        api_key=""
        endpointId="ep-1"
      />,
    )
    fireEvent.click(screen.getByTestId('test-connection-button'))
    await waitFor(() => expect(fetchSpy).toHaveBeenCalled())
    const [url] = fetchSpy.mock.calls[0] as [string, RequestInit]
    expect(url).toContain('/config/llm/endpoints/ep-1/test-connection')
  })

  it('uses generic test-connection when api_key is provided', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ provider: 'openai', base_url: 'https://api.openai.com/v1', reachable: true }), { status: 200 }),
    )
    render(
      <ConnectionTestButton
        provider="openai"
        base_url="https://api.openai.com/v1"
        api_key="sk-new"
        endpointId="ep-1"
      />,
    )
    fireEvent.click(screen.getByTestId('test-connection-button'))
    await waitFor(() => expect(fetchSpy).toHaveBeenCalled())
    const [url] = fetchSpy.mock.calls[0] as [string, RequestInit]
    expect(url).toContain('/config/llm/test-connection')
  })
})

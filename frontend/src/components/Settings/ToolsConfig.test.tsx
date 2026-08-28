import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { ToolsConfig } from './ToolsConfig'
import { LocaleProvider } from '../../i18n'

const DEFAULT_RESPONSE = {
  web_search: { enabled: true, provider: 'tavily', api_key_set: false },
}

function mockFetch() {
  return vi.spyOn(globalThis, 'fetch').mockImplementation(
    (url: string | URL | Request, init?: RequestInit) => {
      const urlString = typeof url === 'string' ? url : url.toString()
      const method = init?.method ?? 'GET'
      if (urlString.includes('/config/tools') && method === 'GET') {
        return Promise.resolve(new Response(JSON.stringify(DEFAULT_RESPONSE), { status: 200 }))
      }
      if (urlString.includes('/config/tools/web_search') && method === 'PUT') {
        return Promise.resolve(new Response(JSON.stringify(DEFAULT_RESPONSE.web_search), { status: 200 }))
      }
      return Promise.resolve(new Response(JSON.stringify({}), { status: 200 }))
    },
  )
}

function renderTools() {
  return render(
    <LocaleProvider>
      <ToolsConfig onMessage={() => {}} />
    </LocaleProvider>,
  )
}

describe('ToolsConfig', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('renders the card and loads config', async () => {
    mockFetch()
    renderTools()
    await waitFor(() => {
      expect(screen.getByTestId('tools-config-card')).toBeInTheDocument()
    })
    await waitFor(() => {
      expect(screen.getByTestId('websearch-provider-select')).toHaveValue('tavily')
    })
    expect(screen.getByTestId('websearch-enabled-toggle')).toBeChecked()
  })

  it('shows the API key input when Tavily is selected', async () => {
    mockFetch()
    renderTools()
    await waitFor(() => {
      expect(screen.getByTestId('websearch-api-key-group')).toBeInTheDocument()
    })
  })

  it('hides the API key input when DuckDuckGo is selected', async () => {
    mockFetch()
    renderTools()
    await waitFor(() => {
      expect(screen.getByTestId('websearch-provider-select')).toBeInTheDocument()
    })
    fireEvent.change(screen.getByTestId('websearch-provider-select'), {
      target: { value: 'duckduckgo' },
    })
    expect(screen.queryByTestId('websearch-api-key-group')).not.toBeInTheDocument()
  })

  it('saves provider changes via PUT', async () => {
    const fetchMock = mockFetch()
    renderTools()
    await waitFor(() => {
      expect(screen.getByTestId('websearch-provider-select')).toBeInTheDocument()
    })
    fireEvent.change(screen.getByTestId('websearch-provider-select'), {
      target: { value: 'duckduckgo' },
    })
    fireEvent.click(screen.getByTestId('websearch-save-button'))
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/v1/config/tools/web_search',
        expect.objectContaining({ method: 'PUT' }),
      )
    })
    const putCall = fetchMock.mock.calls.find(([url]) =>
      String(url).includes('/config/tools/web_search'),
    )
    expect(JSON.parse(putCall?.[1]?.body as string)).toEqual({
      enabled: true,
      provider: 'duckduckgo',
    })
  })

  it('sends the API key when provided', async () => {
    const fetchMock = mockFetch()
    renderTools()
    await waitFor(() => {
      expect(screen.getByTestId('websearch-api-key-input')).toBeInTheDocument()
    })
    fireEvent.change(screen.getByTestId('websearch-api-key-input'), {
      target: { value: 'tvly-secret' },
    })
    fireEvent.click(screen.getByTestId('websearch-save-button'))
    await waitFor(() => {
      const putCall = fetchMock.mock.calls.find(
        ([url]) => String(url).includes('/config/tools/web_search'),
      )
      expect(JSON.parse(putCall?.[1]?.body as string)).toMatchObject({ api_key: 'tvly-secret' })
    })
  })
})
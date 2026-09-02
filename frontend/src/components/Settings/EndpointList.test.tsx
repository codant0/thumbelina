import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { LocaleProvider } from '../../i18n'
import { EndpointList } from './EndpointList'

const sampleEndpoint = {
  id: '1',
  provider: 'openai' as const,
  name: 'Mimo',
  base_url: 'https://api.openai.com/v1',
  models: [
    { name: 'gpt-4o', context_window: '128K', multimodal: true },
    { name: 'gpt-4o-mini', context_window: null, multimodal: false },
  ],
  active_model: 'gpt-4o',
  api_key_set: true,
  is_default: true,
  is_reachable: true,
  last_latency_ms: 123,
  last_total_ms: 245,
  last_tested_at: new Date().toISOString(),
}

const defaultProps = {
  endpoints: [sampleEndpoint],
  onInspect: vi.fn(),
  onEdit: vi.fn(),
  onDelete: vi.fn(),
  onTestConnection: vi.fn(),
  onActivate: vi.fn(),
  testingConnectionId: null,
  activatingKey: null,
}

describe('EndpointList', () => {
  it('renders endpoint name as card title', () => {
    render(
      <LocaleProvider>
        <EndpointList {...defaultProps} />
      </LocaleProvider>,
    )
    expect(screen.getByText('Mimo')).toBeInTheDocument()
  })

  it('renders provider badge', () => {
    render(
      <LocaleProvider>
        <EndpointList {...defaultProps} />
      </LocaleProvider>,
    )
    expect(screen.getByText('OpenAI')).toBeInTheDocument()
  })

  it('renders model chips for the endpoint', () => {
    render(
      <LocaleProvider>
        <EndpointList {...defaultProps} />
      </LocaleProvider>,
    )
    expect(screen.getByTestId('endpoint-model-1-gpt-4o')).toBeInTheDocument()
    expect(screen.getByTestId('endpoint-model-1-gpt-4o-mini')).toBeInTheDocument()
  })

  it('shows active model tag with the model name', () => {
    render(
      <LocaleProvider>
        <EndpointList {...defaultProps} />
      </LocaleProvider>,
    )
    expect(screen.getByTestId('endpoint-active-tag-1').textContent).toContain('gpt-4o')
  })

  it('emits test-connection event', () => {
    const onTestConnection = vi.fn()
    render(
      <LocaleProvider>
        <EndpointList {...defaultProps} onTestConnection={onTestConnection} />
      </LocaleProvider>,
    )
    fireEvent.click(screen.getByTestId('test-connection-1'))
    expect(onTestConnection).toHaveBeenCalledWith('1')
  })

  it('emits activate event with endpoint id and model', () => {
    const onActivate = vi.fn()
    render(
      <LocaleProvider>
        <EndpointList {...defaultProps} onActivate={onActivate} />
      </LocaleProvider>,
    )
    fireEvent.click(screen.getByTestId('activate-1-gpt-4o-mini'))
    expect(onActivate).toHaveBeenCalledWith('1', 'gpt-4o-mini')
  })

  it('renders each model own context window badge', () => {
    render(
      <LocaleProvider>
        <EndpointList {...defaultProps} />
      </LocaleProvider>,
    )
    expect(screen.getByTestId('endpoint-model-ctx-1-gpt-4o')).toHaveTextContent('128K')
    expect(screen.queryByTestId('endpoint-model-ctx-1-gpt-4o-mini')).not.toBeInTheDocument()
  })

  it('renders the multimodal badge only for multimodal models', () => {
    render(
      <LocaleProvider>
        <EndpointList {...defaultProps} />
      </LocaleProvider>,
    )
    expect(screen.getByTestId('endpoint-model-multimodal-1-gpt-4o')).toBeInTheDocument()
    expect(screen.queryByTestId('endpoint-model-multimodal-1-gpt-4o-mini')).not.toBeInTheDocument()
  })
})

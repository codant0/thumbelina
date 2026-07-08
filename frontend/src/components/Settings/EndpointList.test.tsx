import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { LocaleProvider } from '../../i18n'
import { EndpointList } from './EndpointList'

const sampleEndpoint = {
  id: '1',
  provider: 'openai' as const,
  name: 'OpenAI Default',
  base_url: 'https://api.openai.com/v1',
  model: 'gpt-4o',
  api_key_set: true,
  is_default: true,
  is_reachable: true,
  last_latency_ms: 123,
  last_total_ms: 245,
  last_tested_at: new Date().toISOString(),
}

const defaultProps = {
  endpoints: [sampleEndpoint],
  onEdit: vi.fn(),
  onDelete: vi.fn(),
  onTestConnection: vi.fn(),
  onActivate: vi.fn(),
  testingConnectionId: null,
  activatingId: null,
}

describe('EndpointList', () => {
  it('renders endpoint name and provider', () => {
    render(
      <LocaleProvider>
        <EndpointList {...defaultProps} />
      </LocaleProvider>,
    )
    expect(screen.getByText('OpenAI Default')).toBeInTheDocument()
    expect(screen.getByText('OpenAI')).toBeInTheDocument()
  })

  it('renders active tag for default endpoint', () => {
    render(
      <LocaleProvider>
        <EndpointList {...defaultProps} />
      </LocaleProvider>,
    )
    expect(screen.getByTestId('endpoint-active-tag-1')).toBeInTheDocument()
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
})

import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { EndpointList } from './EndpointList'

const sampleEndpoint = {
  id: '1',
  provider: 'openai' as const,
  name: 'OpenAI Default',
  base_url: 'https://api.openai.com/v1',
  api_key_set: true,
  is_default: true,
  is_reachable: true,
  last_latency_ms: 123,
  last_total_ms: 245,
  last_tested_at: new Date().toISOString(),
}

describe('EndpointList', () => {
  it('renders endpoint name and provider', () => {
    render(<EndpointList endpoints={[sampleEndpoint]} onEdit={vi.fn()} onDelete={vi.fn()} onSpeedTest={vi.fn()} onSetDefault={vi.fn()} testingId={null} />)
    expect(screen.getByText('OpenAI Default')).toBeInTheDocument()
    expect(screen.getByText('openai')).toBeInTheDocument()
  })

  it('emits speed-test event', () => {
    const onSpeedTest = vi.fn()
    render(<EndpointList endpoints={[sampleEndpoint]} onEdit={vi.fn()} onDelete={vi.fn()} onSpeedTest={onSpeedTest} onSetDefault={vi.fn()} testingId={null} />)
    fireEvent.click(screen.getByTestId('speed-test-1'))
    expect(onSpeedTest).toHaveBeenCalledWith('1')
  })
})

import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { SpeedTestResult } from './SpeedTestResult'

describe('SpeedTestResult', () => {
  it('shows loading state', () => {
    render(<SpeedTestResult loading />)
    expect(screen.getByText('Testing…')).toBeInTheDocument()
  })

  it('shows success state', () => {
    render(<SpeedTestResult result={{ endpoint_id: '1', reachable: true, latency_ms: 123, total_ms: 245 }} />)
    expect(screen.getByText('123 ms')).toBeInTheDocument()
    expect(screen.getByText('245 ms')).toBeInTheDocument()
  })

  it('shows error state', () => {
    render(<SpeedTestResult result={{ endpoint_id: '1', reachable: false, error: 'Connection refused' }} />)
    expect(screen.getByText(/Unreachable/)).toBeInTheDocument()
    expect(screen.getByText(/Connection refused/)).toBeInTheDocument()
  })
})

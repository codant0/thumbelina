import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, act } from '@testing-library/react'
import { Toast } from './Toast'

describe('Toast', () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('renders success message and fades out automatically', () => {
    const onClose = vi.fn()
    render(<Toast message="连通正常(100ms)" onClose={onClose} duration={2000} />)

    const toast = screen.getByRole('status')
    expect(toast).toHaveTextContent('连通正常(100ms)')
    expect(toast).toHaveClass('toast-success')

    act(() => vi.advanceTimersByTime(2100))
    act(() => vi.advanceTimersByTime(400))

    expect(onClose).toHaveBeenCalled()
  })

  it('renders error styling', () => {
    render(<Toast message="连通失败" isError onClose={vi.fn()} />)
    expect(screen.getByRole('status')).toHaveClass('toast-error')
  })
})

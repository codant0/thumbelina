import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { Sidebar } from './Sidebar'

describe('Sidebar', () => {
  it('should render conversation list', () => {
    render(<Sidebar conversations={[]} onSelect={vi.fn()} />)
    expect(screen.getByTestId('sidebar')).toBeInTheDocument()
  })

  it('should render conversations', () => {
    const conversations = [
      { id: '1', created_at: '2024-01-01T00:00:00Z', updated_at: '2024-01-01T00:00:00Z' },
      { id: '2', created_at: '2024-01-02T00:00:00Z', updated_at: '2024-01-02T00:00:00Z' },
    ]
    render(<Sidebar conversations={conversations} onSelect={vi.fn()} />)
    expect(screen.getAllByTestId('conversation-item')).toHaveLength(2)
  })

  it('should call onSelect when conversation is clicked', async () => {
    const onSelect = vi.fn()
    const conversations = [
      { id: '1', created_at: '2024-01-01T00:00:00Z', updated_at: '2024-01-01T00:00:00Z' },
    ]
    const { user } = await import('@testing-library/user-event').then(m => ({
      user: m.default.setup(),
    }))

    render(<Sidebar conversations={conversations} onSelect={onSelect} />)
    await user.click(screen.getByTestId('conversation-item'))

    expect(onSelect).toHaveBeenCalledWith('1')
  })

  it('should show empty state when no conversations', () => {
    render(<Sidebar conversations={[]} onSelect={vi.fn()} />)
    expect(screen.getByText(/暂无对话/i)).toBeInTheDocument()
  })
})

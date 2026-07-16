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
    expect(screen.getByText(/No conversations yet/i)).toBeInTheDocument()
  })
})


describe('Sidebar rename', () => {
  it('calls onRename with the edited name', async () => {
    const onRename = vi.fn()
    const conversations = [
      { id: '1', name: '旧名称', created_at: '2024-01-01T00:00:00Z', updated_at: '2024-01-01T00:00:00Z' },
    ]
    const { user } = await import('@testing-library/user-event').then(m => ({ user: m.default.setup() }))
    render(<Sidebar conversations={conversations} onSelect={vi.fn()} onRename={onRename} />)

    await user.click(screen.getByTestId('rename-conversation'))
    const input = screen.getByTestId('rename-input') as HTMLInputElement
    await user.clear(input)
    await user.type(input, '新名称')
    await user.click(screen.getByTestId('rename-confirm'))

    expect(onRename).toHaveBeenCalledWith('1', '新名称')
  })

  it('does not show rename button for the WeChat conversation', () => {
    const onRename = vi.fn()
    const conversations = [
      { id: 'wx', name: '微信Clawbot', pinned: true, created_at: '2024-01-01T00:00:00Z', updated_at: '2024-01-01T00:00:00Z' },
    ]
    render(<Sidebar conversations={conversations} onSelect={vi.fn()} onRename={onRename} />)
    expect(screen.queryByTestId('rename-conversation')).toBeNull()
  })
})

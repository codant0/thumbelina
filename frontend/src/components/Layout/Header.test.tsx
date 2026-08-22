import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { Header } from './Header'

describe('Header', () => {
  it('should render app title', () => {
    render(<Header activePage="chat" onNavigate={vi.fn()} />)
    expect(screen.getByText('Thumbelina')).toBeInTheDocument()
  })

  it('should render navigation', () => {
    render(<Header activePage="chat" onNavigate={vi.fn()} />)
    expect(screen.getByRole('navigation')).toBeInTheDocument()
  })

  it('should render all nav links', () => {
    render(<Header activePage="chat" onNavigate={vi.fn()} />)
    expect(screen.getByTestId('nav-chat')).toBeInTheDocument()
    expect(screen.getByTestId('nav-tasks')).toBeInTheDocument()
    expect(screen.getByTestId('nav-todo')).toBeInTheDocument()
    expect(screen.getByTestId('nav-memory')).toBeInTheDocument()
    expect(screen.getByTestId('nav-dream')).toBeInTheDocument()
    expect(screen.getByTestId('nav-settings')).toBeInTheDocument()
  })

  it('should call onNavigate when a link is clicked', () => {
    const onNavigate = vi.fn()
    render(<Header activePage="chat" onNavigate={onNavigate} />)
    screen.getByTestId('nav-tasks').click()
    expect(onNavigate).toHaveBeenCalledWith('tasks')
  })

  it('renders trajectory nav entry', () => {
    render(<Header activePage="chat" onNavigate={vi.fn()} />)
    expect(screen.getByTestId('nav-trajectory')).toBeInTheDocument()
  })
})

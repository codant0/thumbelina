import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MessageList } from './MessageList'
import type { Message } from '../../types/chat'

describe('MessageList', () => {
  it('should render empty state', () => {
    const { container } = render(<MessageList messages={[]} />)
    expect(container.querySelector('[data-testid="message-list"]')).toBeInTheDocument()
  })

  it('should render user messages', () => {
    const messages: Message[] = [
      { id: '1', role: 'user', content: 'Hello', timestamp: '2024-01-01T00:00:00Z' },
    ]
    render(<MessageList messages={messages} />)
    expect(screen.getByText('Hello')).toBeInTheDocument()
  })

  it('should render assistant messages', () => {
    const messages: Message[] = [
      { id: '1', role: 'assistant', content: 'Hi there!', timestamp: '2024-01-01T00:00:00Z' },
    ]
    render(<MessageList messages={messages} />)
    expect(screen.getByText('Hi there!')).toBeInTheDocument()
  })

  it('should render multiple messages in order', () => {
    const messages: Message[] = [
      { id: '1', role: 'user', content: 'First', timestamp: '2024-01-01T00:00:00Z' },
      { id: '2', role: 'assistant', content: 'Second', timestamp: '2024-01-01T00:00:01Z' },
      { id: '3', role: 'user', content: 'Third', timestamp: '2024-01-01T00:00:02Z' },
    ]
    render(<MessageList messages={messages} />)

    const items = screen.getAllByTestId('message-item')
    expect(items).toHaveLength(3)
  })

  it('should display role labels', () => {
    const messages: Message[] = [
      { id: '1', role: 'user', content: 'Hello', timestamp: '2024-01-01T00:00:00Z' },
      { id: '2', role: 'assistant', content: 'Hi!', timestamp: '2024-01-01T00:00:01Z' },
    ]
    render(<MessageList messages={messages} />)
    expect(screen.getByText('You')).toBeInTheDocument()
    expect(screen.getByText('Assistant')).toBeInTheDocument()
  })
})

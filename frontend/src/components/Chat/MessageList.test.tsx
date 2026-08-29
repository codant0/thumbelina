import { describe, it, expect, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
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

  it('should render assistant markdown (bold, lists, code)', () => {
    const messages: Message[] = [
      {
        id: '1',
        role: 'assistant',
        content: '**bold** answer\n\n- item one\n- item two\n\n`inline code`',
        timestamp: '2024-01-01T00:00:00Z',
      },
    ]
    const { container } = render(<MessageList messages={messages} />)
    const strong = container.querySelector('.md-body strong')
    expect(strong?.textContent).toBe('bold')
    const items = container.querySelectorAll('.md-body li')
    expect(items).toHaveLength(2)
    const code = container.querySelector('.md-body code')
    expect(code?.textContent).toBe('inline code')
  })

  it('should preserve single line breaks in assistant markdown', () => {
    const messages: Message[] = [
      {
        id: '1',
        role: 'assistant',
        content: 'line one\nline two\n\nnew paragraph',
        timestamp: '2024-01-01T00:00:00Z',
      },
    ]
    const { container } = render(<MessageList messages={messages} />)
    // Single newlines become <br> (soft breaks), while blank lines still
    // produce separate paragraphs.
    const brs = container.querySelectorAll('.md-body br')
    expect(brs.length).toBe(1)
    expect(container.querySelectorAll('.md-body p')).toHaveLength(2)
  })

  it('should keep user messages as plain text', () => {
    const messages: Message[] = [
      { id: '1', role: 'user', content: '**not rendered**', timestamp: '2024-01-01T00:00:00Z' },
    ]
    const { container } = render(<MessageList messages={messages} />)
    expect(container.querySelector('.message.user .md-body')).toBeNull()
    expect(screen.getByText('**not rendered**')).toBeInTheDocument()
  })

  const streamMsg = (thinking: string): Message[] => [
    {
      id: 'stream-1',
      role: 'assistant',
      content: '',
      thinking,
      timestamp: '2024-01-01T00:00:00Z',
    },
  ]

  // jsdom has no layout; simulate a scrollable container whose scroll
  // position persists across rerenders.
  const mockScrollGeometry = (el: HTMLElement, geometry: { height: number; top: number }) => {
    Object.defineProperty(el, 'clientHeight', { configurable: true, value: 260 })
    Object.defineProperty(el, 'scrollHeight', { configurable: true, get: () => geometry.height })
    Object.defineProperty(el, 'scrollTop', {
      configurable: true,
      get: () => geometry.top,
      set: (v: number) => {
        geometry.top = v
      },
    })
  }

  it('should auto-scroll the thinking body to the bottom as content streams in', () => {
    const { rerender } = render(<MessageList messages={streamMsg('a')} isStreaming />)
    const body = screen.getByTestId('thinking-body')
    const geometry = { height: 300, top: 40 } // 300 - 40 - 260 = 0 → at bottom
    mockScrollGeometry(body, geometry)

    rerender(<MessageList messages={streamMsg('a'.repeat(100))} isStreaming />)
    expect(body.scrollTop).toBe(body.scrollHeight)
  })

  it('should not force-scroll the thinking body when the user has scrolled up', () => {
    const { rerender } = render(<MessageList messages={streamMsg('a')} isStreaming />)
    const body = screen.getByTestId('thinking-body')
    const geometry = { height: 900, top: 0 } // user at the top, far from bottom
    mockScrollGeometry(body, geometry)

    rerender(<MessageList messages={streamMsg('a'.repeat(100))} isStreaming />)
    expect(body.scrollTop).toBe(0)
  })

  // Mock the outer message-list scroll geometry (jsdom has no layout).
  const mockListGeometry = (el: HTMLElement, geometry: { height: number; top: number }) => {
    Object.defineProperty(el, 'clientHeight', { configurable: true, value: 400 })
    Object.defineProperty(el, 'scrollHeight', { configurable: true, get: () => geometry.height })
    Object.defineProperty(el, 'scrollTop', {
      configurable: true,
      get: () => geometry.top,
      set: (v: number) => {
        geometry.top = v
      },
    })
  }

  it('should follow new streaming content while the user is at the bottom', () => {
    const userMsg: Message = { id: '1', role: 'user', content: 'hi', timestamp: '2024-01-01T00:00:00Z' }
    const { rerender } = render(<MessageList messages={[userMsg]} isStreaming />)
    const list = screen.getByTestId('message-list')
    const geometry = { height: 800, top: 400 } // 800 - 400 - 400 = 0 → at bottom
    mockListGeometry(list, geometry)

    const streamed: Message = {
      id: 'stream-1',
      role: 'assistant',
      content: 'x'.repeat(50),
      timestamp: '2024-01-01T00:00:01Z',
    }
    rerender(<MessageList messages={[userMsg, streamed]} isStreaming />)
    expect(list.scrollTop).toBe(list.scrollHeight)
  })

  it('should stop auto-scrolling when the user has scrolled up to read', () => {
    const userMsg: Message = { id: '1', role: 'user', content: 'hi', timestamp: '2024-01-01T00:00:00Z' }
    const { rerender } = render(<MessageList messages={[userMsg]} isStreaming />)
    const list = screen.getByTestId('message-list')
    const geometry = { height: 1200, top: 800 } // starts at bottom
    mockListGeometry(list, geometry)

    // User scrolls up to read earlier content
    geometry.top = 100
    fireEvent.scroll(list)

    const streamed: Message = {
      id: 'stream-1',
      role: 'assistant',
      content: 'x'.repeat(200),
      timestamp: '2024-01-01T00:00:01Z',
    }
    rerender(<MessageList messages={[userMsg, streamed]} isStreaming />)
    // Must not yank the user back to the bottom
    expect(geometry.top).toBe(100)
  })

  it('shows the generating indicator when streaming but awaiting more content', () => {
    const streamed: Message = {
      id: 'stream-1',
      role: 'assistant',
      content: 'revealed',
      timestamp: '2024-01-01T00:00:01Z',
    }
    render(
      <MessageList
        messages={[streamed]}
        isStreaming
        awaitingMoreContent
        waitingForReply={false}
      />,
    )
    expect(screen.getByTestId('generating-indicator')).toBeInTheDocument()
  })

  it('hides the generating indicator while new content is being revealed', () => {
    const streamed: Message = {
      id: 'stream-1',
      role: 'assistant',
      content: 'revealed',
      timestamp: '2024-01-01T00:00:01Z',
    }
    render(
      <MessageList
        messages={[streamed]}
        isStreaming
        awaitingMoreContent={false}
        waitingForReply={false}
      />,
    )
    expect(screen.queryByTestId('generating-indicator')).not.toBeInTheDocument()
  })

  it('prefers the typing indicator when still waiting for the first reply', () => {
    const userMsg: Message = { id: '1', role: 'user', content: 'hi', timestamp: '2024-01-01T00:00:00Z' }
    render(
      <MessageList
        messages={[userMsg]}
        isStreaming
        awaitingMoreContent
        waitingForReply
      />,
    )
    expect(screen.getByTestId('typing-indicator')).toBeInTheDocument()
    expect(screen.queryByTestId('generating-indicator')).not.toBeInTheDocument()
  })

  it('should resume following when the user sends a new message', () => {
    const userMsg: Message = { id: '1', role: 'user', content: 'hi', timestamp: '2024-01-01T00:00:00Z' }
    const reply: Message = { id: '2', role: 'assistant', content: 'reply', timestamp: '2024-01-01T00:00:01Z' }
    const { rerender } = render(<MessageList messages={[userMsg, reply]} />)
    const list = screen.getByTestId('message-list')
    const geometry = { height: 1200, top: 100 }
    mockListGeometry(list, geometry)

    // User scrolled up (not following)
    fireEvent.scroll(list)

    // User sends a new message → jump back to the bottom
    const nextUser: Message = { id: '3', role: 'user', content: 'again', timestamp: '2024-01-01T00:00:02Z' }
    rerender(<MessageList messages={[userMsg, reply, nextUser]} />)
    expect(list.scrollTop).toBe(list.scrollHeight)
  })

  it('renders fenced code as a highlighted block with a copy button', () => {
    const messages: Message[] = [
      { id: '1', role: 'assistant', content: '```python\ndef f():\n    return 1\n```', timestamp: '2024-01-01T00:00:00Z' },
    ]
    const { container } = render(<MessageList messages={messages} />)
    expect(container.querySelector('.codeblock')).toBeTruthy()
    expect(container.querySelector('.codeblock__lang')?.textContent).toBe('python')
    expect(container.querySelector('.codeblock .hljs-keyword')).toBeTruthy()
    expect(screen.getByText('Copy', { selector: '.codeblock__copy span' })).toBeInTheDocument()
  })

  it('lifts a leading raw JSON payload into a collapsed card', () => {
    const json = '{"action":"NEW","target":"","entry":{"title":"用户称呼习惯","category":"user","slug":"addr","summary":"偏好称呼为大哥","full_text":"用户要求称呼大哥","source":"对话"}}\n\n好的大哥记住了'
    const messages: Message[] = [
      { id: '1', role: 'assistant', content: json, timestamp: '2024-01-01T00:00:00Z' },
    ]
    const { container } = render(<MessageList messages={messages} />)
    expect(container.querySelector('[data-testid="json-block"]')).toBeTruthy()
    expect(screen.getByText(/好的大哥记住了/)).toBeInTheDocument()
  })

  it('collapses tool calls behind a summary toggle', () => {
    const messages: Message[] = [
      {
        id: '1', role: 'assistant', content: 'ok', timestamp: '2024-01-01T00:00:00Z',
        toolCalls: [{ name: 'web_search', args: { query: 'hello' }, result: 'found 3 results' }],
      },
    ]
    const { container } = render(<MessageList messages={messages} />)
    // Collapsed by default: args payload not visible
    expect(container.querySelector('.tool-call__detail')).toBeNull()
    fireEvent.click(container.querySelector('.tool-call__summary')!)
    const detail = container.querySelector('.tool-call__detail')
    expect(detail).toBeTruthy()
    expect(detail!.textContent).toContain('"query": "hello"')
  })

  it('offers regenerate on the last assistant message when idle', () => {
    const messages: Message[] = [
      { id: '1', role: 'user', content: 'hi', timestamp: '2024-01-01T00:00:00Z' },
      { id: '2', role: 'assistant', content: 'yo', timestamp: '2024-01-01T00:00:01Z' },
    ]
    const onRegenerate = vi.fn()
    render(<MessageList messages={messages} onRegenerate={onRegenerate} />)
    const btn = screen.getByTestId('regenerate')
    fireEvent.click(btn)
    expect(onRegenerate).toHaveBeenCalledTimes(1)
  })

  it('does not offer regenerate while streaming', () => {
    const messages: Message[] = [
      { id: '1', role: 'user', content: 'hi', timestamp: '2024-01-01T00:00:00Z' },
      { id: '2', role: 'assistant', content: 'partial', timestamp: '2024-01-01T00:00:01Z' },
    ]
    render(<MessageList messages={messages} isStreaming onRegenerate={() => {}} />)
    expect(screen.queryByTestId('regenerate')).toBeNull()
  })
})

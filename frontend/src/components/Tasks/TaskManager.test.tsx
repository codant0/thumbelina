import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { TaskManager } from './TaskManager'

describe('TaskManager', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    vi.spyOn(globalThis, 'fetch').mockImplementation((url: string | URL | Request) => {
      const urlStr = typeof url === 'string' ? url : url.toString()
      if (urlStr.includes('/api/v1/subagents')) {
        return Promise.resolve(new Response(JSON.stringify([]), { status: 200 }))
      }
      if (urlStr.includes('/api/v1/tasks')) {
        return Promise.resolve(new Response(JSON.stringify([]), { status: 200 }))
      }
      return Promise.resolve(new Response('[]', { status: 200 }))
    })
  })

  it('should render task manager', () => {
    render(<TaskManager />)
    expect(screen.getByTestId('task-manager')).toBeInTheDocument()
  })

  it('should render subagent list section', () => {
    render(<TaskManager />)
    expect(screen.getByTestId('subagent-list')).toBeInTheDocument()
  })

  it('should render task list section', () => {
    render(<TaskManager />)
    expect(screen.getByTestId('task-list')).toBeInTheDocument()
  })

  it('should show empty state for subagents', () => {
    render(<TaskManager />)
    expect(screen.getByText('No subagents')).toBeInTheDocument()
  })

  it('should show empty state for tasks', () => {
    render(<TaskManager />)
    expect(screen.getByText('No scheduled tasks')).toBeInTheDocument()
  })
})

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryViewer } from './MemoryViewer'

describe('MemoryViewer', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify([]), { status: 200 }),
    )
  })

  it('should render memory viewer', () => {
    render(<MemoryViewer />)
    expect(screen.getByTestId('memory-viewer')).toBeInTheDocument()
  })

  it('should render search input', () => {
    render(<MemoryViewer />)
    expect(screen.getByTestId('search-input')).toBeInTheDocument()
  })

  it('should render search button', () => {
    render(<MemoryViewer />)
    expect(screen.getByTestId('search-button')).toBeInTheDocument()
  })

  it('should render search results container', () => {
    render(<MemoryViewer />)
    expect(screen.getByTestId('search-results')).toBeInTheDocument()
  })

  it('should render skills list', () => {
    render(<MemoryViewer />)
    expect(screen.getByTestId('skills-list')).toBeInTheDocument()
  })

  it('should render load skills button', () => {
    render(<MemoryViewer />)
    expect(screen.getByTestId('load-skills-button')).toBeInTheDocument()
  })
})

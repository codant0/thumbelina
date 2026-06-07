import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { DreamViewer } from './DreamViewer'

const mockStats = {
  total: 3,
  timeline: [
    {
      date: '2026-06-01',
      skills: [
        { id: '1', name: 'Code Review', success_rate: 0.85 },
        { id: '2', name: 'Data Analysis', success_rate: 0.7 },
      ],
    },
    {
      date: '2026-06-02',
      skills: [
        { id: '3', name: 'File Search', success_rate: 0.9 },
      ],
    },
  ],
  top_skills: [
    { id: '1', name: 'Code Review', version: 3, success_rate: 0.85 },
    { id: '2', name: 'Data Analysis', version: 2, success_rate: 0.7 },
    { id: '3', name: 'File Search', version: 1, success_rate: 0.9 },
  ],
  categories: [
    { name: '编程开发', count: 2 },
    { name: '数据分析', count: 1 },
  ],
}

describe('DreamViewer', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('should render loading state initially', () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(() => new Promise(() => {}))
    render(<DreamViewer />)
    expect(screen.getByTestId('dream-loading')).toBeInTheDocument()
    expect(screen.getByText('Loading...')).toBeInTheDocument()
  })

  it('should render error state on fetch failure', async () => {
    vi.spyOn(globalThis, 'fetch').mockRejectedValue(new Error('Network error'))
    render(<DreamViewer />)
    await waitFor(() => {
      expect(screen.getByTestId('dream-error')).toBeInTheDocument()
    })
    expect(screen.getByText('Failed to load skill statistics')).toBeInTheDocument()
  })

  it('should render error state on non-ok response', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response('error', { status: 500 }),
    )
    render(<DreamViewer />)
    await waitFor(() => {
      expect(screen.getByTestId('dream-error')).toBeInTheDocument()
    })
  })

  it('should render empty state when no skills', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(
        JSON.stringify({ total: 0, timeline: [], top_skills: [], categories: [] }),
        { status: 200 },
      ),
    )
    render(<DreamViewer />)
    await waitFor(() => {
      expect(screen.getByTestId('dream-empty')).toBeInTheDocument()
    })
    expect(screen.getByText(/No skills recorded yet/)).toBeInTheDocument()
  })

  it('should render skill stats on successful fetch', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(mockStats), { status: 200 }),
    )
    render(<DreamViewer />)
    await waitFor(() => {
      expect(screen.getByTestId('stat-total')).toBeInTheDocument()
    })
    expect(screen.getByText('3')).toBeInTheDocument()
    expect(screen.getByText('Skills')).toBeInTheDocument()
  })

  it('should render timeline entries', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(mockStats), { status: 200 }),
    )
    render(<DreamViewer />)
    await waitFor(() => {
      expect(screen.getByTestId('skill-timeline')).toBeInTheDocument()
    })
    const entries = screen.getAllByTestId('timeline-entry')
    expect(entries).toHaveLength(2)
    expect(screen.getByText('2026-06-01')).toBeInTheDocument()
    expect(screen.getByText('2026-06-02')).toBeInTheDocument()
  })

  it('should render bar chart rows', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(mockStats), { status: 200 }),
    )
    render(<DreamViewer />)
    await waitFor(() => {
      expect(screen.getByTestId('skill-chart')).toBeInTheDocument()
    })
    const bars = screen.getAllByTestId('bar-row')
    expect(bars).toHaveLength(3)
  })

  it('should render skill cloud words', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(mockStats), { status: 200 }),
    )
    render(<DreamViewer />)
    await waitFor(() => {
      expect(screen.getByTestId('skill-cloud')).toBeInTheDocument()
    })
    const words = screen.getAllByTestId('cloud-word')
    expect(words).toHaveLength(3)
  })

  it('should render category rows', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(mockStats), { status: 200 }),
    )
    render(<DreamViewer />)
    await waitFor(() => {
      expect(screen.getByTestId('skill-categories')).toBeInTheDocument()
    })
    const rows = screen.getAllByTestId('category-row')
    expect(rows).toHaveLength(2)
  })

  it('should show retry button on error and refetch on click', async () => {
    let callCount = 0
    vi.spyOn(globalThis, 'fetch').mockImplementation(() => {
      callCount++
      if (callCount === 1) {
        return Promise.resolve(new Response('error', { status: 500 }))
      }
      return Promise.resolve(
        new Response(JSON.stringify(mockStats), { status: 200 }),
      )
    })
    render(<DreamViewer />)
    await waitFor(() => {
      expect(screen.getByTestId('retry-button')).toBeInTheDocument()
    })
    screen.getByTestId('retry-button').click()
    await waitFor(() => {
      expect(screen.getByTestId('stat-total')).toBeInTheDocument()
    })
  })
})

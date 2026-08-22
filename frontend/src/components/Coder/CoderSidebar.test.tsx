import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { CoderSidebar } from './CoderSidebar'
import type { Conversation } from '../../types/chat'

const conv = (id: string, workspace: string | null, updatedAt: string, name?: string): Conversation => ({
  id,
  name: name ?? null,
  workspace,
  mode: 'coder',
  created_at: updatedAt,
  updated_at: updatedAt,
})

describe('CoderSidebar', () => {
  const base = {
    onSelect: vi.fn(),
    onNew: vi.fn(),
    onDelete: vi.fn(),
    selectedId: undefined,
  }

  it('groups conversations by workspace', () => {
    render(<CoderSidebar {...base} conversations={[
      conv('c1', 'C:\\proj\\alpha', '2026-08-22T10:00:00Z', 'fix bug'),
      conv('c2', 'C:\\proj\\alpha', '2026-08-22T09:00:00Z', 'add tests'),
      conv('c3', 'D:\\other', '2026-08-22T08:00:00Z', 'docs'),
    ]} />)
    expect(screen.getAllByTestId('coder-group')).toHaveLength(2)
    expect(screen.getByText('alpha')).toBeInTheDocument()
    expect(screen.getByText('other')).toBeInTheDocument()
    expect(screen.getAllByTestId('coder-conversation-item')).toHaveLength(3)
  })

  it('collapses a group when its header is clicked', () => {
    render(<CoderSidebar {...base} conversations={[conv('c1', 'ws-a', '2026-08-22T10:00:00Z')]} />)
    const toggle = screen.getByTestId('coder-group-toggle')
    const items = screen.getByRole('group')
    expect(items.className).not.toContain('coder-group__items--collapsed')
    expect(toggle.getAttribute('aria-expanded')).toBe('true')
    fireEvent.click(toggle)
    expect(items.className).toContain('coder-group__items--collapsed')
    expect(toggle.getAttribute('aria-expanded')).toBe('false')
  })

  it('shows a loading skeleton while fetching', () => {
    render(<CoderSidebar {...base} conversations={[]} loading />)
    expect(screen.getByTestId('coder-sidebar-loading')).toBeInTheDocument()
    expect(screen.queryByTestId('coder-sidebar-empty')).not.toBeInTheDocument()
  })

  it('shows empty state when there are no conversations', () => {
    render(<CoderSidebar {...base} conversations={[]} />)
    expect(screen.getByTestId('coder-sidebar-empty')).toBeInTheDocument()
  })

  it('calls onNew and onDelete', () => {
    const onNew = vi.fn()
    const onDelete = vi.fn()
    render(<CoderSidebar {...base} onNew={onNew} onDelete={onDelete} conversations={[conv('c1', 'ws-a', '2026-08-22T10:00:00Z')]} />)
    fireEvent.click(screen.getByTitle('New coder conversation'))
    expect(onNew).toHaveBeenCalled()
    fireEvent.click(screen.getByTestId('delete-conversation'))
    expect(onDelete).toHaveBeenCalledWith('c1')
  })
})
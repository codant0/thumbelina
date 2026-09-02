import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { RoleSelector } from './RoleSelector'
import * as conversationsApi from '../../api/conversations'

const roles = ['assistant', 'coder']

describe('RoleSelector', () => {
  beforeEach(() => {
    vi.spyOn(conversationsApi, 'listRoles').mockResolvedValue(roles)
  })

  it('renders nothing when no conversation is selected', () => {
    const { container } = render(
      <RoleSelector conversationId={undefined} onChange={vi.fn()} />,
    )
    expect(container.firstChild).toBeNull()
  })

  it('shows the default role label when no role is selected', async () => {
    render(<RoleSelector conversationId="c1" selectedRole={null} onChange={vi.fn()} />)
    await waitFor(() => expect(screen.getByTestId('role-selector-trigger')).toBeInTheDocument())
    expect(screen.getByTestId('role-selector-trigger').textContent).toContain('Default role')
  })

  it('shows the selected role name', async () => {
    render(<RoleSelector conversationId="c1" selectedRole="coder" onChange={vi.fn()} />)
    await waitFor(() => expect(screen.getByTestId('role-selector-trigger')).toBeInTheDocument())
    expect(screen.getByTestId('role-selector-trigger').textContent).toContain('coder')
  })

  it('calls onChange with the chosen role', async () => {
    const onChange = vi.fn()
    render(<RoleSelector conversationId="c1" selectedRole={null} onChange={onChange} />)
    await waitFor(() =>
      expect(screen.getByTestId('role-selector-trigger').textContent).toContain('Default role'),
    )
    fireEvent.click(screen.getByTestId('role-selector-trigger'))
    fireEvent.click(screen.getByTestId('role-option-coder'))
    expect(onChange).toHaveBeenCalledWith('coder')
  })

  it('calls onChange with null when the default role is chosen', async () => {
    const onChange = vi.fn()
    render(<RoleSelector conversationId="c1" selectedRole="coder" onChange={onChange} />)
    await waitFor(() =>
      expect(screen.getByTestId('role-selector-trigger').textContent).toContain('coder'),
    )
    fireEvent.click(screen.getByTestId('role-selector-trigger'))
    fireEvent.click(screen.getByTestId('role-option-default'))
    expect(onChange).toHaveBeenCalledWith(null)
  })

  it('marks the panel compact (no scrollable max-height) when there are few options', async () => {
    // roles fixture has 2 items + 1 default option = 3 → < 4 threshold → compact.
    render(<RoleSelector conversationId="c1" selectedRole={null} onChange={vi.fn()} />)
    await waitFor(() => expect(screen.getByTestId('role-selector-trigger')).toBeInTheDocument())
    fireEvent.click(screen.getByTestId('role-selector-trigger'))
    const panel = screen.getByTestId('role-selector-menu')
    expect(panel.getAttribute('data-density')).toBe('compact')
  })

  it('switches to scrollable density once options reach the threshold', async () => {
    vi.spyOn(conversationsApi, 'listRoles').mockResolvedValueOnce([
      'a', 'b', 'c', 'd', 'e',
    ])
    render(<RoleSelector conversationId="c1" selectedRole={null} onChange={vi.fn()} />)
    await waitFor(() => expect(screen.getByTestId('role-selector-trigger')).toBeInTheDocument())
    fireEvent.click(screen.getByTestId('role-selector-trigger'))
    const panel = screen.getByTestId('role-selector-menu')
    expect(panel.getAttribute('data-density')).toBe('scrollable')
  })
})

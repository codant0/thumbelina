import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, act } from '@testing-library/react'
import { PermissionSelector } from './PermissionSelector'
import * as conversationsApi from '../../api/conversations'

vi.mock('../../api/conversations', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../api/conversations')>()
  return {
    ...actual,
    setConversationPermission: vi.fn(async () => ({ id: 'c1', permission: 'global_write' })),
  }
})

const setPermissionMock = conversationsApi.setConversationPermission as unknown as ReturnType<typeof vi.fn>

beforeEach(() => {
  setPermissionMock.mockClear()
})

describe('PermissionSelector', () => {
  it('chat 会话隐藏 workspace_write, 显示其他四项', () => {
    render(
      <PermissionSelector
        conversationId="c1"
        mode="read_only"
        conversationType="chat"
        onChange={() => {}}
      />,
    )
    fireEvent.click(screen.getByTestId('permission-selector-trigger'))
    const menu = screen.getByTestId('permission-selector-menu')
    expect(menu.querySelector('[data-testid="permission-option-workspace_write"]')).toBeNull()
    expect(menu.querySelector('[data-testid="permission-option-read_only"]')).not.toBeNull()
    expect(menu.querySelector('[data-testid="permission-option-global_write"]')).not.toBeNull()
    expect(menu.querySelector('[data-testid="permission-option-full_access"]')).not.toBeNull()
    expect(menu.querySelector('[data-testid="permission-option-auto"]')).not.toBeNull()
  })

  it('coder 会话五项全显', () => {
    render(
      <PermissionSelector
        conversationId="c1"
        mode="read_only"
        conversationType="coder"
        onChange={() => {}}
      />,
    )
    fireEvent.click(screen.getByTestId('permission-selector-trigger'))
    const menu = screen.getByTestId('permission-selector-menu')
    expect(menu.querySelector('[data-testid="permission-option-workspace_write"]')).not.toBeNull()
    expect(menu.querySelector('[data-testid="permission-option-read_only"]')).not.toBeNull()
    expect(menu.querySelector('[data-testid="permission-option-global_write"]')).not.toBeNull()
    expect(menu.querySelector('[data-testid="permission-option-full_access"]')).not.toBeNull()
    expect(menu.querySelector('[data-testid="permission-option-auto"]')).not.toBeNull()
  })

  it('历史值不在可见集时显示提示, 选项列表仍只暴露可见集', () => {
    render(
      <PermissionSelector
        conversationId="c1"
        mode="workspace_write"
        conversationType="chat"
        onChange={() => {}}
      />,
    )
    fireEvent.click(screen.getByTestId('permission-selector-trigger'))
    // 触发器按钮文案仍显示当前 workspace_write, 提示行存在
    expect(screen.getByTestId('permission-selector-hidden-hint')).toBeInTheDocument()
    // 选项列表里没有 workspace_write(它对 chat 隐藏)
    const menu = screen.getByTestId('permission-selector-menu')
    expect(menu.querySelector('[data-testid="permission-option-workspace_write"]')).toBeNull()
  })

  it('conversationId 为 null 时不渲染任何东西', () => {
    const { container } = render(
      <PermissionSelector
        conversationId={null}
        mode="read_only"
        conversationType="chat"
        onChange={() => {}}
      />,
    )
    expect(container.querySelector('[data-testid="permission-selector"]')).toBeNull()
  })

  it('选择后回调 onChange 并调用 setConversationPermission', async () => {
    const onChange = vi.fn()
    render(
      <PermissionSelector
        conversationId="c1"
        mode="read_only"
        conversationType="chat"
        onChange={onChange}
      />,
    )
    fireEvent.click(screen.getByTestId('permission-selector-trigger'))
    await act(async () => {
      fireEvent.click(screen.getByTestId('permission-option-global_write'))
    })
    expect(onChange).toHaveBeenCalledWith('global_write')
    expect(setPermissionMock).toHaveBeenCalledWith('c1', 'global_write')
  })
})
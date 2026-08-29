import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { LocaleProvider } from '../../i18n'
import { GitBranchSelector } from './GitBranchSelector'
import type { ChatSocket } from '../../hooks/useWebSocket'
import * as fsApi from '../../api/fs'

const ws = {
  subscribe: vi.fn(() => () => {}),
} as unknown as ChatSocket

function localGit(on: boolean) {
  localStorage.setItem('thumbelina-statusbar-items', JSON.stringify({ git: on }))
}

function mock(info: Partial<fsApi.GitInfo>) {
  vi.spyOn(fsApi, 'fetchGitInfo').mockResolvedValue({ is_git: true, branch: 'main', ...info })
}

describe('GitBranchSelector', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    localStorage.clear()
    localStorage.setItem('thumbelina-locale', 'zh-CN')
    localGit(true)
  })

  it('配置关闭时不渲染', () => {
    localGit(false)
    render(<LocaleProvider><GitBranchSelector ws={ws} workspace="/ws" /></LocaleProvider>)
    expect(screen.queryByTestId('git-branch-selector')).not.toBeInTheDocument()
  })

  it('无 workspace(非码农)时不渲染', () => {
    render(<LocaleProvider><GitBranchSelector ws={ws} workspace={null} /></LocaleProvider>)
    expect(screen.queryByTestId('git-branch-selector')).not.toBeInTheDocument()
  })

  it('非 git 目录隐藏', async () => {
    mock({ is_git: false, branch: null })
    render(<LocaleProvider><GitBranchSelector ws={ws} workspace="/ws" /></LocaleProvider>)
    await waitFor(() => expect(screen.queryByTestId('git-branch-selector')).not.toBeInTheDocument())
  })

  it('git 目录显示当前分支', async () => {
    mock({ is_git: true, branch: 'main' })
    render(<LocaleProvider><GitBranchSelector ws={ws} workspace="/ws" /></LocaleProvider>)
    expect(await screen.findByText('main')).toBeInTheDocument()
    expect(screen.getByTestId('statusbar-item')).toHaveAttribute('title', '当前分支 main')
  })

  it('点击打开面板并列出分支', async () => {
    mock({ is_git: true, branch: 'main' })
    vi.spyOn(fsApi, 'fetchGitBranches').mockResolvedValue({
      is_git: true, current: 'main', branches: ['feature-a', 'main'],
    })
    render(<LocaleProvider><GitBranchSelector ws={ws} workspace="/ws" /></LocaleProvider>)
    const trigger = await screen.findByTestId('statusbar-item')
    fireEvent.click(trigger)
    expect(await screen.findByTestId('git-branch-menu')).toBeInTheDocument()
    expect(screen.getByTestId('git-branch-option-feature-a')).toBeInTheDocument()
  })

  it('点击分支调用 checkout 并刷新', async () => {
    mock({ is_git: true, branch: 'main' })
    vi.spyOn(fsApi, 'fetchGitBranches').mockResolvedValue({
      is_git: true, current: 'main', branches: ['feature-a', 'main'],
    })
    const checkout = vi.spyOn(fsApi, 'checkoutBranch').mockResolvedValue({ is_git: true, branch: 'feature-a' })
    render(<LocaleProvider><GitBranchSelector ws={ws} workspace="/ws" /></LocaleProvider>)
    fireEvent.click(await screen.findByTestId('statusbar-item'))
    fireEvent.click(await screen.findByTestId('git-branch-option-feature-a'))
    await waitFor(() => {
      expect(checkout).toHaveBeenCalledWith('/ws', 'feature-a')
      expect(screen.queryByTestId('git-branch-menu')).not.toBeInTheDocument()
    })
    expect(await screen.findByText('feature-a')).toBeInTheDocument()
  })

  it('checkout 失败显示错误并保持面板', async () => {
    mock({ is_git: true, branch: 'main' })
    vi.spyOn(fsApi, 'fetchGitBranches').mockResolvedValue({
      is_git: true, current: 'main', branches: ['feature-a', 'main'],
    })
    vi.spyOn(fsApi, 'checkoutBranch').mockRejectedValue(new Error('本地改动会丢失'))
    render(<LocaleProvider><GitBranchSelector ws={ws} workspace="/ws" /></LocaleProvider>)
    fireEvent.click(await screen.findByTestId('statusbar-item'))
    fireEvent.click(await screen.findByTestId('git-branch-option-feature-a'))
    expect(await screen.findByTestId('git-branch-error')).toBeInTheDocument()
    expect(screen.getByTestId('git-branch-menu')).toBeInTheDocument()
  })

  it('Esc 关闭面板', async () => {
    mock({ is_git: true, branch: 'main' })
    vi.spyOn(fsApi, 'fetchGitBranches').mockResolvedValue({
      is_git: true, current: 'main', branches: ['main'],
    })
    render(<LocaleProvider><GitBranchSelector ws={ws} workspace="/ws" /></LocaleProvider>)
    fireEvent.click(await screen.findByTestId('statusbar-item'))
    await screen.findByTestId('git-branch-menu')
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(screen.queryByTestId('git-branch-menu')).not.toBeInTheDocument()
  })

  it('收到 git_branch 事件刷新分支', async () => {
    let captured: Parameters<ChatSocket['subscribe']>[0] | null = null
    const subscribe = vi.fn((cb: Parameters<ChatSocket['subscribe']>[0]) => {
      captured = cb
      return () => {}
    })
    const ws2 = { subscribe } as unknown as ChatSocket
    mock({ is_git: true, branch: 'main' })
    render(<LocaleProvider><GitBranchSelector ws={ws2} workspace="/ws" /></LocaleProvider>)
    await screen.findByText('main')
    await waitFor(() => expect(subscribe).toHaveBeenCalled())
    captured!({ git_branch: { workspace: '/ws', branch: 'feature-2' } })
    expect(await screen.findByText('feature-2')).toBeInTheDocument()
  })
})

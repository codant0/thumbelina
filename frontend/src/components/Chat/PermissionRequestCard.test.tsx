import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { PermissionRequestCard } from './PermissionRequestCard'
import type { PermissionRequestPayload } from '../../types/chat'

const request: PermissionRequestPayload = {
  request_id: 'req-1',
  calls: [
    {
      call_id: 'c1',
      name: 'run_shell',
      args: { command: 'sudo ls' },
      risk: 'dangerous',
      reason: 'confirm.sudo',
      args_display: 'sudo ls',
    },
    {
      call_id: 'c2',
      name: 'run_shell',
      args: { command: 'rm -rf /tmp/x' },
      risk: 'dangerous',
      reason: 'dangerous.rm_root',
      args_display: 'rm -rf /tmp/x',
    },
  ],
}

describe('PermissionRequestCard', () => {
  it('点击"全部批准"后所有按钮禁用并发送全批准决策', () => {
    const onDecide = vi.fn()
    render(<PermissionRequestCard request={request} onDecide={onDecide} />)
    fireEvent.click(screen.getByTestId('permission-approve-all'))
    expect(onDecide).toHaveBeenCalledWith([
      { call_id: 'c1', approved: true },
      { call_id: 'c2', approved: true },
    ])
    // 防双击: 所有按钮禁用
    expect(screen.getByTestId('permission-approve-all')).toBeDisabled()
    expect(screen.getByTestId('permission-deny-all')).toBeDisabled()
    expect(screen.getAllByTestId('permission-approve-one')[0]).toBeDisabled()
    // 二次点击不再触发回调
    onDecide.mockClear()
    fireEvent.click(screen.getByTestId('permission-approve-all'))
    expect(onDecide).not.toHaveBeenCalled()
  })

  it('点击"全部拒绝"后发送全拒绝决策', () => {
    const onDecide = vi.fn()
    render(<PermissionRequestCard request={request} onDecide={onDecide} />)
    fireEvent.click(screen.getByTestId('permission-deny-all'))
    expect(onDecide).toHaveBeenCalledWith([
      { call_id: 'c1', approved: false },
      { call_id: 'c2', approved: false },
    ])
  })

  it('逐项批准:点击 c1 后该 call 批准、其他拒绝', () => {
    const onDecide = vi.fn()
    render(<PermissionRequestCard request={request} onDecide={onDecide} />)
    const buttons = screen.getAllByTestId('permission-approve-one')
    fireEvent.click(buttons[0]) // c1
    expect(onDecide).toHaveBeenCalledWith([
      { call_id: 'c1', approved: true },
      { call_id: 'c2', approved: false },
    ])
  })

  it('命令预览使用归一化的 args_display 而非原始 args.command', () => {
    const longCommand = 'sudo '.padEnd(600, 'x')
    const req: PermissionRequestPayload = {
      request_id: 'req-2',
      calls: [{
        call_id: 'c1',
        name: 'run_shell',
        args: { command: 'sudo ' + 'x'.repeat(600) },
        risk: 'dangerous',
        reason: 'confirm.sudo',
        args_display: longCommand,
      }],
    }
    const onDecide = vi.fn()
    render(<PermissionRequestCard request={req} onDecide={onDecide} />)
    const preview = screen.getByTestId('permission-call-command')
    // 折叠态: 显示前 500 字符 + 省略号
    expect(preview.textContent).toContain('…')
    // 展开按钮存在
    const expandBtn = screen.getByTestId('permission-call-expand')
    fireEvent.click(expandBtn)
    expect(preview.querySelector('pre')?.getAttribute('data-expanded')).toBe('true')
  })
})
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { ContextUsageItem } from './ContextUsageItem'
import type { Message } from '../../types/chat'

vi.mock('../../api/llmConfig', () => ({
  fetchEndpoints: vi.fn(),
}))

import { fetchEndpoints } from '../../api/llmConfig'

const mockedFetch = vi.mocked(fetchEndpoints)

function msg(id: string, content: string): Message {
  return { id, role: 'user', content, timestamp: new Date().toISOString() }
}

function cjk(n: number): string {
  return '你'.repeat(n)
}

/** 等到状态栏条目的文本达到期待值后返回其条目元素（用于断言类名）。 */
async function statusItem(expectedText: string): Promise<HTMLElement> {
  const label = await screen.findByText(expectedText)
  const item = label.closest('.statusbar__item')
  expect(item).not.toBeNull()
  return item as HTMLElement
}

function ui(settledMessages: Message[] | null, settledVersion: number, endpointId = 'ep1') {
  return <ContextUsageItem settledMessages={settledMessages} settledVersion={settledVersion} endpointId={endpointId} />
}

describe('ContextUsageItem', () => {
  beforeEach(() => {
    localStorage.clear()
    mockedFetch.mockReset()
  })

  it('按会话 endpoint 激活模型的 context_window 估算并展示百分比', async () => {
    mockedFetch.mockResolvedValue([
      { id: 'ep1', is_default: false, active_model: 'gpt-4o', models: [{ name: 'gpt-4o', context_window: '200', multimodal: false }] },
    ] as never)
    // 2 个 CJK 字符 = 4 tokens;200 窗口 → 2%
    render(ui([msg('1', '你好')], 1))
    const item = await statusItem('2%')
    expect(item).toHaveClass('statusbar__item--ok')
  })

  it('endpointId 未匹配时回落到默认端点', async () => {
    mockedFetch.mockResolvedValue([
      { id: 'ep-default', is_default: true, active_model: 'm', models: [{ name: 'm', context_window: '100', multimodal: false }] },
      { id: 'ep-other', is_default: false, active_model: 'x', models: [{ name: 'x', context_window: '999999', multimodal: false }] },
    ] as never)
    render(ui([msg('1', '你好')], 1, 'no-such'))
    const item = await statusItem('4%') // 4/100
    expect(item).toHaveClass('statusbar__item--ok')
  })

  it('优先使用激活模型的 context_window，而非首个模型', async () => {
    mockedFetch.mockResolvedValue([
      {
        id: 'ep1',
        is_default: true,
        active_model: 'b',
        models: [
          { name: 'a', context_window: '999999', multimodal: false },
          { name: 'b', context_window: '100', multimodal: false },
        ],
      },
    ] as never)
    // 4/100（激活模型 b 的窗口），而不是 4/999999
    render(ui([msg('1', '你好')], 1))
    const item = await statusItem('4%')
    expect(item).toHaveClass('statusbar__item--ok')
  })

  it('超过 60% 时警告高亮', async () => {
    mockedFetch.mockResolvedValue([{ id: 'ep1', is_default: true, active_model: 'm', models: [{ name: 'm', context_window: '100', multimodal: false }] }] as never)
    // 35 CJK = 70 tokens → 70%
    render(ui([msg('1', cjk(35))], 1))
    const item = await statusItem('70%')
    expect(item).toHaveClass('statusbar__item--warning')
  })

  it('超过 85% 时错误高亮', async () => {
    mockedFetch.mockResolvedValue([{ id: 'ep1', is_default: true, active_model: 'm', models: [{ name: 'm', context_window: '100', multimodal: false }] }] as never)
    // 45 CJK = 90 tokens → 90%
    render(ui([msg('1', cjk(45))], 1))
    const item = await statusItem('90%')
    expect(item).toHaveClass('statusbar__item--error')
  })

  it('窗口上限未设置时展示占位而非百分比', async () => {
    mockedFetch.mockResolvedValue([{ id: 'ep1', is_default: true, active_model: 'm', models: [{ name: 'm', context_window: null, multimodal: false }] }] as never)
    render(ui([msg('1', '你好')], 1))
    const item = await statusItem('—')
    expect(item).toHaveClass('statusbar__item--idle')
  })

  it('端点获取失败时降级为占位，不崩溃', async () => {
    mockedFetch.mockRejectedValue(new Error('network'))
    render(ui([msg('1', '你好')], 1))
    const item = await statusItem('—')
    expect(item).toHaveClass('statusbar__item--idle')
  })

  it('栏目开关关闭时不渲染，且不发起端点请求', async () => {
    localStorage.setItem('thumbelina-statusbar-items', JSON.stringify({ context: false }))
    const { container } = render(ui([msg('1', '你好')], 1))
    expect(container.querySelector('[data-testid="statusbar"]')).toBeNull()
    expect(mockedFetch).not.toHaveBeenCalled()
  })
})

describe('ContextUsageItem 回合落定刷新', () => {
  beforeEach(() => {
    localStorage.clear()
    mockedFetch.mockReset()
    mockedFetch.mockResolvedValue([{ id: 'ep1', is_default: true, active_model: 'm', models: [{ name: 'm', context_window: '100', multimodal: false }] }] as never)
  })

  it('settledVersion 变化时按新快照重新估算（收到新响应后刷新）', async () => {
    const { rerender } = render(ui([msg('1', '你好')], 1))
    await statusItem('4%') // 4/100
    // 下一回合落定：快照更新 → 百分比随之刷新
    rerender(ui([msg('1', '你好'), msg('2', cjk(21))], 2))
    await statusItem('46%') // (4+42)/100
  })

  it('settledVersion 未变时保持展示（回合进行中冻结由上游快照保证）', async () => {
    const { rerender } = render(ui([msg('1', '你好')], 1))
    await statusItem('4%')
    // 版本号未推进（回合仍在进行中）：消息引用变化也不重算
    rerender(ui([msg('1', '你好'), msg('2', cjk(21))], 1))
    expect(screen.getByText('4%')).toBeInTheDocument()
  })

  it('快照为 null（会话刚切换）时展示占位', async () => {
    render(ui(null, 2))
    const item = await statusItem('—')
    expect(item).toHaveClass('statusbar__item--idle')
  })

  it('空快照（新建会话）展示 0%', async () => {
    render(ui([], 1))
    const item = await statusItem('0%')
    expect(item).toHaveClass('statusbar__item--ok')
  })
})

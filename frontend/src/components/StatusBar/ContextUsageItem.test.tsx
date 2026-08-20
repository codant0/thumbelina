import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { ContextUsageItem } from './ContextUsageItem'
import type { Message } from '../../types/chat'

vi.mock('../../api/llmConfig', () => ({
  fetchEndpoints: vi.fn(),
}))

import { fetchEndpoints } from '../../api/llmConfig'

const mockedFetch = vi.mocked(fetchEndpoints)

function msg(content: string): Message {
  return { id: '1', role: 'user', content, timestamp: new Date().toISOString() }
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

describe('ContextUsageItem', () => {
  beforeEach(() => {
    localStorage.clear()
    mockedFetch.mockReset()
  })

  it('按会话 endpoint 的 context_window 估算并展示百分比', async () => {
    mockedFetch.mockResolvedValue([
      { id: 'ep1', is_default: false, context_window: '200' },
    ] as never)
    // 2 个 CJK 字符 = 4 tokens;200 窗口 → 2%
    render(<ContextUsageItem messages={[msg('你好')]} endpointId="ep1" />)
    const item = await statusItem('2%')
    expect(item).toHaveClass('statusbar__item--ok')
  })

  it('endpointId 未匹配时回落到默认端点', async () => {
    mockedFetch.mockResolvedValue([
      { id: 'ep-default', is_default: true, context_window: '100' },
      { id: 'ep-other', is_default: false, context_window: '999999' },
    ] as never)
    render(<ContextUsageItem messages={[msg('你好')]} endpointId="no-such" />)
    const item = await statusItem('4%') // 4/100
    expect(item).toHaveClass('statusbar__item--ok')
  })

  it('超过 60% 时警告高亮', async () => {
    mockedFetch.mockResolvedValue([{ id: 'ep1', is_default: true, context_window: '100' }] as never)
    // 35 CJK = 70 tokens → 70%
    render(<ContextUsageItem messages={[msg(cjk(35))]} endpointId="ep1" />)
    const item = await statusItem('70%')
    expect(item).toHaveClass('statusbar__item--warning')
  })

  it('超过 85% 时错误高亮', async () => {
    mockedFetch.mockResolvedValue([{ id: 'ep1', is_default: true, context_window: '100' }] as never)
    // 45 CJK = 90 tokens → 90%
    render(<ContextUsageItem messages={[msg(cjk(45))]} endpointId="ep1" />)
    const item = await statusItem('90%')
    expect(item).toHaveClass('statusbar__item--error')
  })

  it('窗口上限未设置时展示占位而非百分比', async () => {
    mockedFetch.mockResolvedValue([{ id: 'ep1', is_default: true, context_window: null }] as never)
    render(<ContextUsageItem messages={[msg('你好')]} endpointId="ep1" />)
    const item = await statusItem('—')
    expect(item).toHaveClass('statusbar__item--idle')
  })

  it('端点获取失败时降级为占位，不崩溃', async () => {
    mockedFetch.mockRejectedValue(new Error('network'))
    render(<ContextUsageItem messages={[msg('你好')]} endpointId="ep1" />)
    const item = await statusItem('—')
    expect(item).toHaveClass('statusbar__item--idle')
  })

  it('栏目开关关闭时不渲染，且不发起端点请求', async () => {
    localStorage.setItem('thumbelina-statusbar-items', JSON.stringify({ context: false }))
    const { container } = render(<ContextUsageItem messages={[msg('你好')]} endpointId="ep1" />)
    expect(container.querySelector('[data-testid="statusbar"]')).toBeNull()
    expect(mockedFetch).not.toHaveBeenCalled()
  })
})

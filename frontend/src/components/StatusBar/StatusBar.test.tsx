import { describe, it, expect, vi } from 'vitest'
import { act, render, screen } from '@testing-library/react'
import { StatusBar } from './StatusBar'
import type { StatusBarItem } from './types'

describe('StatusBar container', () => {
  it('渲染注册的栏目并按渲染函数展示内容', async () => {
    const item: StatusBarItem = {
      key: 'demo',
      getData: () => ({ n: 42 }),
      render: data => `val ${(data as { n: number }).n}`,
      status: () => 'ok',
    }
    render(<StatusBar items={[item]} />)
    const el = await screen.findByRole('status')
    expect(el).toHaveTextContent('val 42')
    expect(el).toHaveClass('statusbar__item--ok')
  })

  it('getData 抛错时降级为占位并标红', async () => {
    const item: StatusBarItem = {
      key: 'demo',
      getData: () => { throw new Error('boom') },
      render: () => 'x',
    }
    render(<StatusBar items={[item]} />)
    const el = await screen.findByRole('status')
    expect(el).toHaveTextContent('—')
    expect(el).toHaveClass('statusbar__item--error')
  })

  it('未定义 status 时默认视为 ok', async () => {
    const item: StatusBarItem = {
      key: 'demo',
      getData: () => ({ a: 1 }),
      render: () => 'shown',
    }
    render(<StatusBar items={[item]} />)
    const el = await screen.findByRole('status')
    expect(el).toHaveClass('statusbar__item--ok')
  })

  it('容器的数据获取不触发任何额外调用（仅调用声明过的 getData）', async () => {
    const getData = vi.fn().mockReturnValue({ n: 1 })
    const item: StatusBarItem = {
      key: 'demo',
      getData,
      render: () => 'hello',
    }
    render(<StatusBar items={[item]} />)
    await screen.findByRole('status')
    expect(getData).toHaveBeenCalledTimes(1)
  })
})

describe('StatusBar icon passing', () => {
  it('把 item.icon 渲染到胶囊内（图标即栏目区分）', async () => {
    const item: StatusBarItem = {
      key: 'demo',
      icon: <svg data-testid="item-icon" />,
      getData: () => ({ n: 1 }),
      render: () => 'v',
    }
    render(<StatusBar items={[item]} />)
    const el = await screen.findByRole('status')
    expect(el.querySelector('[data-testid="item-icon"]')).not.toBeNull()
  })
})

describe('StatusBar 取数信号（防闪烁）', () => {
  it('items/item 引用变化但信号未变时，不重新取数', async () => {
    // 模拟父组件高频重渲染:每次都传入新的 items 数组与新的 item 对象
    const getData = vi.fn().mockReturnValue({ n: 1 })
    const renderItem = (): StatusBarItem => ({
      key: 'demo',
      getData,
      render: data => `n${(data as { n: number }).n}`,
    })
    const { rerender } = render(<StatusBar items={[renderItem()]} />)
    await screen.findByRole('status')
    rerender(<StatusBar items={[renderItem()]} />)
    rerender(<StatusBar items={[renderItem()]} />)
    expect(getData).toHaveBeenCalledTimes(1)
  })

  it('refreshKey 变化时重新取数，旧值保留到新数据到达（不回占位符）', async () => {
    let resolveSecond: ((value: { n: number }) => void) = () => {}
    const getData = vi.fn<() => Promise<{ n: number }>>()
      .mockResolvedValueOnce({ n: 1 })
      .mockImplementationOnce(() => new Promise(resolve => { resolveSecond = resolve }))
    const renderItem = (version: number): StatusBarItem => ({
      key: 'demo',
      refreshKey: version,
      getData,
      render: data => `n${(data as { n: number }).n}`,
    })
    const { rerender } = render(<StatusBar items={[renderItem(1)]} />)
    expect(await screen.findByText('n1')).toBeInTheDocument()

    // 取数挂起期间旧值仍在展示,而不是闪回「…」
    rerender(<StatusBar items={[renderItem(2)]} />)
    expect(screen.getByText('n1')).toBeInTheDocument()

    // 先 flush 一次微任务,让 effect 的取数链真正调到 getData(resolveSecond 就位),
    // 再在 act 内放行挂起的取数。
    await act(async () => { await Promise.resolve() })
    await act(async () => {
      resolveSecond({ n: 2 })
    })
    expect(await screen.findByText('n2')).toBeInTheDocument()
    expect(getData).toHaveBeenCalledTimes(2)
  })

  it('resetKey 变化时先清空回占位符再取数（会话切换语义）', async () => {
    let resolveSecond: ((value: { n: number }) => void) = () => {}
    const getData = vi.fn<() => Promise<{ n: number }>>()
      .mockResolvedValueOnce({ n: 1 })
      .mockImplementationOnce(() => new Promise(resolve => { resolveSecond = resolve }))
    const renderItem = (conv: string): StatusBarItem => ({
      key: 'demo',
      resetKey: conv,
      getData,
      render: data => `n${(data as { n: number }).n}`,
    })
    const { rerender } = render(<StatusBar items={[renderItem('conv-a')]} />)
    expect(await screen.findByText('n1')).toBeInTheDocument()

    // 切换会话:在新的取数解析前,展示应先回到占位符
    rerender(<StatusBar items={[renderItem('conv-b')]} />)
    expect(screen.getByText('…')).toBeInTheDocument()

    // 先 flush 微任务让取数链发出请求(resolveSecond 就位),再放行
    await act(async () => { await Promise.resolve() })
    await act(async () => {
      resolveSecond({ n: 2 })
    })
    expect(await screen.findByText('n2')).toBeInTheDocument()
  })

  it('快速连续取数时,未完成的旧响应不覆盖新数据（竞态防护）', async () => {
    let resolveFirst: ((value: { n: number }) => void) = () => {}
    const getData = vi.fn<() => Promise<{ n: number }>>()
      .mockImplementationOnce(() => new Promise(resolve => { resolveFirst = resolve }))
      .mockResolvedValueOnce({ n: 2 })
    const renderItem = (version: number): StatusBarItem => ({
      key: 'demo',
      refreshKey: version,
      getData,
      render: data => `n${(data as { n: number }).n}`,
    })
    const { rerender } = render(<StatusBar items={[renderItem(1)]} />)
    rerender(<StatusBar items={[renderItem(2)]} />)
    // 第二次取数已落地
    expect(await screen.findByText('n2')).toBeInTheDocument()
    // 第一次(已过期)的响应此刻才到达:必须被丢弃
    resolveFirst({ n: 999 })
    await Promise.resolve()
    expect(screen.getByText('n2')).toBeInTheDocument()
  })
})

import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
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

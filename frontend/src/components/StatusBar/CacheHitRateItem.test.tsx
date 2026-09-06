import { describe, it, expect, vi, beforeEach } from 'vitest'
import { act, render, screen } from '@testing-library/react'
import { CacheHitRateItem } from './CacheHitRateItem'
import { LocaleProvider } from '../../i18n'

function mockStats(resp: unknown) {
  return vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify(resp), { status: 200 }))
}

function renderWithI18n(ui: React.ReactElement) {
  return render(<LocaleProvider>{ui}</LocaleProvider>)
}

describe('CacheHitRateItem', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    localStorage.clear()
    localStorage.setItem('thumbelina-locale', 'zh-CN')
  })

  it('展示缓存命中率与悬浮明细', async () => {
    const fetchSpy = mockStats({ hit_tokens: 900, miss_tokens: 300, turns: 4 })
    renderWithI18n(<CacheHitRateItem conversationId="conv-1" />)
    expect(await screen.findByText('75%')).toBeInTheDocument()
    expect(screen.getByTestId('statusbar-item')).toHaveAttribute(
      'title',
      '缓存命中率 75%（900/1200 tokens · 4 轮）',
    )
    expect(fetchSpy.mock.calls[0][0]).toContain(
      '/api/v1/trajectory/cache-stats?conversation_id=conv-1&limit=100',
    )
  })

  it('命中率低于 10% 显示 error 状态点', async () => {
    mockStats({ hit_tokens: 5, miss_tokens: 95, turns: 2 })
    renderWithI18n(<CacheHitRateItem conversationId="conv-1" />)
    expect(await screen.findByText('5%')).toBeInTheDocument()
    expect(screen.getByTestId('statusbar-item')).toHaveClass('statusbar__item--error')
  })

  it('无数据时展示占位符', async () => {
    mockStats({ hit_tokens: 0, miss_tokens: 0, turns: 0 })
    renderWithI18n(<CacheHitRateItem conversationId="conv-1" />)
    expect(await screen.findByText('—')).toBeInTheDocument()
  })

  it('取数失败时展示占位符', async () => {
    vi.spyOn(globalThis, 'fetch').mockRejectedValue(new Error('network'))
    renderWithI18n(<CacheHitRateItem conversationId="conv-1" />)
    expect(await screen.findByText('—')).toBeInTheDocument()
  })

  it('栏目关闭时不渲染且不请求', async () => {
    localStorage.setItem('thumbelina-statusbar-items', JSON.stringify({ context: true, cacheHit: false }))
    const fetchSpy = mockStats({ hit_tokens: 1, miss_tokens: 1, turns: 1 })
    renderWithI18n(<CacheHitRateItem conversationId="conv-1" />)
    expect(screen.queryByTestId('statusbar')).not.toBeInTheDocument()
    expect(fetchSpy).not.toHaveBeenCalled()
  })
})
describe('CacheHitRateItem 图标', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    localStorage.clear()
    localStorage.setItem('thumbelina-locale', 'zh-CN')
  })

  it('胶囊内渲染 Zap 图标', async () => {
    mockStats({ hit_tokens: 1, miss_tokens: 1, turns: 1 })
    renderWithI18n(<CacheHitRateItem conversationId="conv-1" />)
    const item = await screen.findByTestId('statusbar-item')
    expect(item.querySelector('svg')).not.toBeNull()
  })
})

describe('CacheHitRateItem 会话切换', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    localStorage.clear()
    localStorage.setItem('thumbelina-locale', 'zh-CN')
  })

  it('切换 conversationId 时按新会话请求(修复闭包陈旧)', async () => {
    // 每个 conversationId 返回不同的统计,验证闭包不再锁住旧值
    let conv = 'conv-A'
    const fetchSpy = vi
      .spyOn(globalThis, 'fetch')
      .mockImplementation(async (input: RequestInfo | URL) => {
        const url = typeof input === 'string' ? input : (input as URL).toString()
        const cid = new URL(url, 'http://x').searchParams.get('conversation_id')
        // A: 命中率高(80%);B: 命中率低(10%),对比明显
        const hit = cid === 'conv-A' ? 800 : 100
        const miss = cid === 'conv-A' ? 200 : 900
        return new Response(
          JSON.stringify({ hit_tokens: hit, miss_tokens: miss, turns: 4 }),
          { status: 200 },
        )
      })

    const { rerender } = renderWithI18n(<CacheHitRateItem conversationId={conv} />)
    expect(await screen.findByText('80%')).toBeInTheDocument()

    // 切到 B:应重新请求 B 的统计,而不是沿用 A 的 80%
    conv = 'conv-B'
    rerender(
      <LocaleProvider>
        <CacheHitRateItem conversationId={conv} />
      </LocaleProvider>,
    )
    expect(await screen.findByText('10%')).toBeInTheDocument()

    // 应至少请求过两次,且最后一次必须包含 conv-B
    expect(fetchSpy.mock.calls.length).toBeGreaterThanOrEqual(2)
    const lastUrl = fetchSpy.mock.calls[fetchSpy.mock.calls.length - 1][0]
    expect(String(lastUrl)).toContain('conversation_id=conv-B')
  })

  it('切换会话时立刻回到占位符(避免旧数据闪烁)', async () => {
    const fetchHolder: { resolve: ((value: Response) => void) | null } = { resolve: null }
    vi.spyOn(globalThis, 'fetch').mockImplementation(
      () =>
        new Promise<Response>(resolve => {
          fetchHolder.resolve = resolve
        }),
    )

    const { rerender } = renderWithI18n(<CacheHitRateItem conversationId="conv-A" />)
    // 等 useEffect 排队后再解析第一个 fetch:render 后仍显示「…」
    expect(await screen.findByText('…')).toBeInTheDocument()

    // 第一次请求解析为 A 的统计
    fetchHolder.resolve?.(
      new Response(JSON.stringify({ hit_tokens: 800, miss_tokens: 200, turns: 4 }), {
        status: 200,
      }),
    )
    // 让 microtask 走完
    await Promise.resolve()
    await Promise.resolve()
    expect(await screen.findByText('80%')).toBeInTheDocument()

    // 切到 B;在新的 fetch 解析前,展示应先回到「…」,而不是停留 80%
    rerender(
      <LocaleProvider>
        <CacheHitRateItem conversationId="conv-B" />
      </LocaleProvider>,
    )
    // 此刻 B 的 fetch 尚未 resolve;resetKey(conversationId)变化已把展示清回初始态
    expect(screen.getByText('…')).toBeInTheDocument()
  })
})

describe('CacheHitRateItem 回合落定刷新', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    localStorage.clear()
    localStorage.setItem('thumbelina-locale', 'zh-CN')
  })

  it('refreshKey 变化时重新请求,取数期间保留旧值不回占位符', async () => {
    // 第一次请求立即返回 80%;第二次(回合落定)挂起,由测试手动放行
    let call = 0
    let resolveSecond: ((value: Response) => void) = () => {}
    vi.spyOn(globalThis, 'fetch').mockImplementation(() => {
      call += 1
      if (call === 1) {
        return Promise.resolve(new Response(JSON.stringify({ hit_tokens: 800, miss_tokens: 200, turns: 4 }), { status: 200 }))
      }
      return new Promise<Response>(resolve => { resolveSecond = resolve })
    })

    const { rerender } = renderWithI18n(<CacheHitRateItem conversationId="conv-1" refreshKey={1} />)
    expect(await screen.findByText('80%')).toBeInTheDocument()

    // 回合结束(version+1):同会话原地刷新,fetch 挂起期间仍显示 80%(不闪「…」)
    rerender(
      <LocaleProvider>
        <CacheHitRateItem conversationId="conv-1" refreshKey={2} />
      </LocaleProvider>,
    )
    expect(screen.getByText('80%')).toBeInTheDocument()

    // 先 flush 微任务让 effect 的取数链真正发出第二次 fetch(resolveSecond 就位),
    // 再在 act 内放行挂起的取数。
    await act(async () => { await Promise.resolve() })
    await act(async () => {
      resolveSecond(new Response(JSON.stringify({ hit_tokens: 100, miss_tokens: 900, turns: 5 }), { status: 200 }))
    })
    expect(await screen.findByText('10%')).toBeInTheDocument()
  })

  it('refreshKey 未变时即使组件重渲染也不重复请求(流式期间零请求)', async () => {
    const fetchSpy = mockStats({ hit_tokens: 900, miss_tokens: 300, turns: 4 })
    const { rerender } = renderWithI18n(<CacheHitRateItem conversationId="conv-1" refreshKey={7} />)
    expect(await screen.findByText('75%')).toBeInTheDocument()

    // 父组件重渲染(引用变化),conversationId/refreshKey 均未变 → 不再发请求
    rerender(
      <LocaleProvider>
        <CacheHitRateItem conversationId="conv-1" refreshKey={7} />
      </LocaleProvider>,
    )
    await Promise.resolve()
    expect(fetchSpy).toHaveBeenCalledTimes(1)
  })
})

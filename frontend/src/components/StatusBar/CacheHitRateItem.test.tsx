import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
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

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { TrajectoryPage } from './TrajectoryPage'
import { LocaleProvider } from '../../i18n'

const TRAJECTORY_DATA = {
  conversation_id: 'c1',
  conversation_name: '会话1',
  legacy: false,
  total_turns: 3,
  page: 1,
  page_size: 2,
  turns: [
    {
      turn_id: 't3',
      started_at: '2026-08-22T10:03:11',
      legacy: false,
      events: [
        { seq: 0, event_type: 'user', payload: { content: '你好' }, created_at: '2026-08-22T10:03:11' },
        { seq: 1, event_type: 'tool_call', payload: { tool: 'search', args: { q: 'x' }, call_id: 'c1' }, created_at: '2026-08-22T10:03:12' },
        { seq: 2, event_type: 'tool_result', payload: { call_id: 'c1', content: '结果A', is_error: false }, created_at: '2026-08-22T10:03:13' },
        { seq: 3, event_type: 'assistant', payload: { content: '好的' }, created_at: '2026-08-22T10:03:14' },
      ],
    },
    {
      turn_id: 't2',
      started_at: '2026-08-22T10:00:00',
      legacy: true,
      events: [
        { seq: 0, event_type: 'user', payload: { content: '旧消息' }, created_at: '2026-08-22T10:00:00' },
        { seq: 1, event_type: 'assistant', payload: { content: '旧回复' }, created_at: '2026-08-22T10:00:01' },
      ],
    },
  ],
}

const CONVERSATIONS = [{ id: 'c1', name: '会话1', created_at: '2026-08-01', updated_at: '2026-08-22' }]

function mockFetchOnce(resp: unknown) {
  return vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify(resp), { status: 200 }))
}

/** 组件依赖 i18n（中文字段断言），统一包裹 LocaleProvider 并固定为 zh-CN，保证测试确定性。 */
function renderWithI18n(ui: React.ReactElement) {
  return render(<LocaleProvider>{ui}</LocaleProvider>)
}

describe('TrajectoryPage', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    localStorage.setItem('thumbelina-locale', 'zh-CN')
    mockFetchOnce(CONVERSATIONS)
  })

  it('默认空状态：不请求轨迹数据', async () => {
    const fetchSpy = mockFetchOnce(CONVERSATIONS)
    renderWithI18n(<TrajectoryPage />)
    expect(await screen.findByTestId('trajectory-empty')).toBeInTheDocument()
    expect(fetchSpy.mock.calls.some(c => String(c[0]).includes('/trajectory/'))).toBe(false)
  })

  it('选择会话后加载轨迹并展示轮次', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockImplementation((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('/trajectory/')) {
        return Promise.resolve(new Response(JSON.stringify({ ...TRAJECTORY_DATA }), { status: 200 }))
      }
      return Promise.resolve(new Response(JSON.stringify(CONVERSATIONS), { status: 200 }))
    })
    renderWithI18n(<TrajectoryPage />)
    const select = await screen.findByTestId('trajectory-select')
    fireEvent.change(select, { target: { value: 'c1' } })

    await waitFor(() => {
      expect(screen.getAllByTestId('turn-card')).toHaveLength(2)
    })
    expect(screen.getByText('你好')).toBeInTheDocument()
    expect(fetchSpy).toHaveBeenCalledWith(expect.stringContaining('/trajectory/c1?page=1'))
  })

  it('工具调用与上下文事件默认折叠，点击展开', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('/trajectory/')) {
        return Promise.resolve(new Response(JSON.stringify({ ...TRAJECTORY_DATA }), { status: 200 }))
      }
      return Promise.resolve(new Response(JSON.stringify(CONVERSATIONS), { status: 200 }))
    })
    renderWithI18n(<TrajectoryPage />)
    const select = await screen.findByTestId('trajectory-select')
    fireEvent.change(select, { target: { value: 'c1' } })

    const toggle = await screen.findAllByTestId('event-toggle')
    expect(toggle.length).toBeGreaterThan(0)
    expect(screen.queryByText('结果A')).not.toBeInTheDocument()
    // toggle[0] 为 tool_call，toggle[1] 为 tool_result（其 payload 含 结果A）
    fireEvent.click(toggle[1])
    expect(await screen.findByText('结果A')).toBeInTheDocument()
  })

  it('legacy 轮次展示旧记录提示', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('/trajectory/')) {
        return Promise.resolve(new Response(JSON.stringify({ ...TRAJECTORY_DATA }), { status: 200 }))
      }
      return Promise.resolve(new Response(JSON.stringify(CONVERSATIONS), { status: 200 }))
    })
    renderWithI18n(<TrajectoryPage />)
    const select = await screen.findByTestId('trajectory-select')
    fireEvent.change(select, { target: { value: 'c1' } })
    expect(await screen.findByText('旧记录：无工具调用/上下文数据')).toBeInTheDocument()
  })

  it('加载更多：翻页追加', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('/trajectory/')) {
        const page = url.includes('page=2') ? 2 : 1
        return Promise.resolve(new Response(JSON.stringify({
          ...TRAJECTORY_DATA,
          page,
          turns: page === 2 ? [{ ...TRAJECTORY_DATA.turns[0], turn_id: 't1' }] : TRAJECTORY_DATA.turns,
        }), { status: 200 }))
      }
      return Promise.resolve(new Response(JSON.stringify(CONVERSATIONS), { status: 200 }))
    })
    renderWithI18n(<TrajectoryPage />)
    const select = await screen.findByTestId('trajectory-select')
    fireEvent.change(select, { target: { value: 'c1' } })
    await screen.findAllByTestId('turn-card')

    fireEvent.click(screen.getByTestId('trajectory-load-more'))
    await waitFor(() => {
      expect(screen.getAllByTestId('turn-card')).toHaveLength(3)
    })
  })

  it('加载失败展示错误与重试', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockImplementation((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('/trajectory/')) {
        return Promise.reject(new Error('network'))
      }
      return Promise.resolve(new Response(JSON.stringify(CONVERSATIONS), { status: 200 }))
    })
    renderWithI18n(<TrajectoryPage />)
    const select = await screen.findByTestId('trajectory-select')
    fireEvent.change(select, { target: { value: 'c1' } })
    expect(await screen.findByTestId('trajectory-error')).toBeInTheDocument()

    fetchSpy.mockImplementation((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('/trajectory/')) {
        return Promise.resolve(new Response(JSON.stringify({ ...TRAJECTORY_DATA }), { status: 200 }))
      }
      return Promise.resolve(new Response(JSON.stringify(CONVERSATIONS), { status: 200 }))
    })
    fireEvent.click(screen.getByTestId('retry-button'))
    await waitFor(() => {
      expect(screen.getAllByTestId('turn-card')).toHaveLength(2)
    })
  })
})
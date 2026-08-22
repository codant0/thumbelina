import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react'
import { TrajectoryPage } from './TrajectoryPage'
import { collapseMiddle } from './trajectoryDisplay'
import { LocaleProvider } from '../../i18n'

const LONG_TEXT = '长'.repeat(800)

const TRAJECTORY_DATA = {
  conversation_id: 'c1',
  conversation_name: '会话1',
  total_turns: 3,
  page: 1,
  page_size: 2,
  turns: [
    {
      turn_id: 't3',
      started_at: '2026-08-22T10:03:11',
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
      events: [
        { seq: 0, event_type: 'user', payload: { content: LONG_TEXT }, created_at: '2026-08-22T10:00:00' },
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

function mockTrajectoryFetch() {
  return vi.spyOn(globalThis, 'fetch').mockImplementation((input: RequestInfo | URL) => {
    const url = String(input)
    if (url.includes('/trajectory/')) {
      return Promise.resolve(new Response(JSON.stringify({ ...TRAJECTORY_DATA }), { status: 200 }))
    }
    return Promise.resolve(new Response(JSON.stringify(CONVERSATIONS), { status: 200 }))
  })
}

async function selectConversation() {
  const select = await screen.findByTestId('trajectory-select')
  fireEvent.change(select, { target: { value: 'c1' } })
  await waitFor(() => {
    expect(screen.getAllByTestId('turn-card').length).toBeGreaterThan(0)
  })
}

describe('collapseMiddle', () => {
  it('短文本原样返回', () => {
    expect(collapseMiddle('你好世界')).toEqual({ text: '你好世界', truncated: false })
  })

  it('长文本保留首尾并标记截断', () => {
    const { text, truncated } = collapseMiddle('a'.repeat(600) + 'Z', 600, 200, 200)
    expect(truncated).toBe(true)
    expect(text.startsWith('a'.repeat(200))).toBe(true)
    expect(text.endsWith('Z')).toBe(true)
    expect(text).toContain('共 601 字')
  })

  it('边界长度不截断', () => {
    expect(collapseMiddle('x'.repeat(600), 600, 200, 200).truncated).toBe(false)
  })
})

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
    const fetchSpy = mockTrajectoryFetch()
    renderWithI18n(<TrajectoryPage />)
    await selectConversation()
    expect(screen.getByText('你好')).toBeInTheDocument()
    expect(fetchSpy).toHaveBeenCalledWith(expect.stringContaining('/trajectory/c1?page=1'))
  })

  it('轮次序号倒序编号：顶部最新为 #total，越往下越小', async () => {
    mockTrajectoryFetch()
    renderWithI18n(<TrajectoryPage />)
    await selectConversation()
    expect(screen.getByText('轮次 #3')).toBeInTheDocument()
    expect(screen.getByText('轮次 #2')).toBeInTheDocument()
    expect(screen.queryByText('轮次 #1')).not.toBeInTheDocument()
  })

  it('时间线结构：轮次轨道含节点与时间线容器', async () => {
    mockTrajectoryFetch()
    renderWithI18n(<TrajectoryPage />)
    await selectConversation()
    expect(document.querySelector('.timeline')).not.toBeNull()
    expect(document.querySelectorAll('.turn-node').length).toBeGreaterThan(0)
  })

  it('请求未返回时展示骨架占位', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('/trajectory/')) return new Promise<Response>(() => {})
      return Promise.resolve(new Response(JSON.stringify(CONVERSATIONS), { status: 200 }))
    })
    renderWithI18n(<TrajectoryPage />)
    const select = await screen.findByTestId('trajectory-select')
    fireEvent.change(select, { target: { value: 'c1' } })

    const skeleton = await screen.findByTestId('trajectory-loading')
    expect(skeleton).toHaveAttribute('aria-busy', 'true')
    expect(screen.queryByText('你好')).not.toBeInTheDocument()
  })

  it('长文本在卡片内首尾折叠并提示查看详情', async () => {
    mockTrajectoryFetch()
    renderWithI18n(<TrajectoryPage />)
    await selectConversation()
    const preview = screen.getByText(/^长{200}…（共 800 字）…长{200}$/)
    expect(preview).toBeInTheDocument()
    expect(screen.getAllByText('查看详情').length).toBeGreaterThan(0)
  })

  it('点击事件行打开详情弹窗展示全文', async () => {
    mockTrajectoryFetch()
    renderWithI18n(<TrajectoryPage />)
    await selectConversation()

    // 点击用户消息行 → 弹窗展示全文（长文本不被折叠）
    const rows = screen.getAllByTestId('turn-event')
    fireEvent.click(rows[0])
    expect(await screen.findByTestId('trajectory-detail-modal')).toBeInTheDocument()
    fireEvent.click(screen.getByTestId('detail-close'))
    await waitFor(() => {
      expect(screen.queryByTestId('trajectory-detail-modal')).not.toBeInTheDocument()
    })

    // 点击工具调用行 → 弹窗标题含工具名，可展开原始 JSON
    fireEvent.click(screen.getAllByTestId('turn-event')[1])
    const modal = await screen.findByTestId('trajectory-detail-modal')
    expect(within(modal).getByText('工具调用: search')).toBeInTheDocument()
    fireEvent.click(within(modal).getByTestId('detail-json-toggle'))
    expect(await within(modal).findByTestId('detail-json')).toBeInTheDocument()
    expect(within(modal).getByTestId('detail-json').textContent).toContain('"tool": "search"')

    // Esc 关闭
    fireEvent.keyDown(screen.getByTestId('trajectory-detail-modal'), { key: 'Escape' })
    await waitFor(() => {
      expect(screen.queryByTestId('trajectory-detail-modal')).not.toBeInTheDocument()
    })
  })

  it('点击轮次头打开轮次信息弹窗', async () => {
    mockTrajectoryFetch()
    renderWithI18n(<TrajectoryPage />)
    await selectConversation()
    fireEvent.click(screen.getByText(/^轮次 #3$/))
    expect(await screen.findByTestId('trajectory-detail-modal')).toBeInTheDocument()
    expect(screen.getByText('轮次信息 #3')).toBeInTheDocument()
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
    await selectConversation()

    fireEvent.click(screen.getByTestId('trajectory-load-more'))
    await waitFor(() => {
      expect(screen.getAllByTestId('turn-card')).toHaveLength(3)
    })
    // 追加的最旧一轮（底部）编号为 #1
    expect(screen.getByText('轮次 #1')).toBeInTheDocument()
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
      expect(screen.getAllByTestId('turn-card').length).toBeGreaterThan(0)
    })
  })

  it('轨迹接口返回 404 时清空选择并提示会话不存在', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('/trajectory/')) {
        return Promise.resolve(new Response(JSON.stringify({ detail: 'Conversation not found' }), { status: 404 }))
      }
      return Promise.resolve(new Response(JSON.stringify(CONVERSATIONS), { status: 200 }))
    })
    renderWithI18n(<TrajectoryPage />)
    const select = await screen.findByTestId('trajectory-select')
    fireEvent.change(select, { target: { value: 'c1' } })

    await waitFor(() => {
      expect((screen.getByTestId('trajectory-select') as HTMLSelectElement).value).toBe('')
    })
    expect(await screen.findByText('会话不存在')).toBeInTheDocument()
    expect(screen.queryByTestId('trajectory-error')).not.toBeInTheDocument()
  })
})
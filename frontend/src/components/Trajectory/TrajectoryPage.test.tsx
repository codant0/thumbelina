import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react'
import { TrajectoryPage } from './TrajectoryPage'
import { collapseMiddle, groupToolEvents } from './trajectoryDisplay'
import type { ToolCallGroup } from './trajectoryDisplay'
import type { TrajectoryEvent } from '../../types/trajectory'
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

function ev(seq: number, event_type: string, payload: Record<string, unknown>): TrajectoryEvent {
  return { seq, event_type, payload, created_at: '2026-08-22T10:00:00' }
}

describe('groupToolEvents', () => {
  const call = (seq: number, callId: string) => ev(seq, 'tool_call', { tool: 'search', args: {}, call_id: callId })
  const result = (seq: number, callId: string, content = 'ok') => ev(seq, 'tool_result', { call_id: callId, content, is_error: false })

  it('按 call_id 组合调用与结果', () => {
    const events = [call(0, 'c1'), result(1, 'c1')]
    const [block] = groupToolEvents(events)
    expect((block as ToolCallGroup).call).toBe(events[0])
    expect((block as ToolCallGroup).results).toEqual([events[1]])
  })

  it('调用无匹配结果时 results 为空', () => {
    const [block] = groupToolEvents([call(0, 'c1')])
    expect((block as ToolCallGroup).results).toEqual([])
  })

  it('结果找不到调用时单独保留', () => {
    const events = [call(0, 'c1'), result(1, 'c2')]
    const blocks = groupToolEvents(events)
    expect(blocks).toHaveLength(2)
    expect((blocks[0] as ToolCallGroup).results).toEqual([])
    expect(blocks[1]).toBe(events[1])
  })

  it('同一调用多个结果全部归入', () => {
    const events = [call(0, 'c1'), result(1, 'c1', 'a'), result(2, 'c1', 'b')]
    const blocks = groupToolEvents(events)
    expect(blocks).toHaveLength(1)
    expect((blocks[0] as ToolCallGroup).results).toHaveLength(2)
  })

  it('call_id 为空不配对', () => {
    expect(groupToolEvents([call(0, ''), result(1, '')])).toHaveLength(2)
  })

  it('非工具事件透出并保持顺序', () => {
    const user = ev(0, 'user', { content: 'hi' })
    const assistant = ev(3, 'assistant', { content: 'ok' })
    const blocks = groupToolEvents([user, call(1, 'c1'), result(2, 'c1'), assistant])
    expect(blocks.map(b => ('call' in b ? 'group' : b.event_type))).toEqual(['user', 'group', 'assistant'])
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

  it('工具调用与结果合并为一张卡片，分区点击打开对应弹窗', async () => {
    mockTrajectoryFetch()
    renderWithI18n(<TrajectoryPage />)
    await selectConversation()

    const card = document.querySelector('.tool-call-card') as HTMLElement
    expect(card).not.toBeNull()
    // 卡片内同时包含调用与结果
    expect(within(card).getByText('工具调用: search')).toBeInTheDocument()
    expect(within(card).getByText('结果A')).toBeInTheDocument()

    // 结果区 → tool_result 详情弹窗
    fireEvent.click(card.querySelectorAll('[data-testid="turn-event"]')[1])
    const resultModal = await screen.findByTestId('trajectory-detail-modal')
    expect(within(resultModal).getByText('工具结果')).toBeInTheDocument()
    fireEvent.click(screen.getByTestId('detail-close'))

    // 请求区 → tool_call 详情弹窗
    fireEvent.click(card.querySelectorAll('[data-testid="turn-event"]')[0])
    const callModal = await screen.findByTestId('trajectory-detail-modal')
    expect(within(callModal).getByText('工具调用: search')).toBeInTheDocument()
  })

  it('调用无匹配结果时展示提示，孤儿结果仍单独展示', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('/trajectory/')) {
        return Promise.resolve(new Response(JSON.stringify({
          ...TRAJECTORY_DATA,
          turns: [{
            turn_id: 't9',
            started_at: '2026-08-22T11:00:00',
            events: [
              { seq: 0, event_type: 'tool_call', payload: { tool: 'web', args: { u: 'x' }, call_id: 'no-result' }, created_at: '2026-08-22T11:00:00' },
              { seq: 1, event_type: 'tool_result', payload: { call_id: 'other', content: '别的结果', is_error: false }, created_at: '2026-08-22T11:00:01' },
            ],
          }],
        }), { status: 200 }))
      }
      return Promise.resolve(new Response(JSON.stringify(CONVERSATIONS), { status: 200 }))
    })
    renderWithI18n(<TrajectoryPage />)
    await selectConversation()

    expect(screen.getByText('无匹配结果')).toBeInTheDocument()
    expect(screen.getByText('别的结果')).toBeInTheDocument()
    // 无匹配结果提示位于调用卡片内部
    expect(document.querySelector('.tool-call-card')).not.toBeNull()
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
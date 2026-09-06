import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { useWebSocket, advanceFor } from './useWebSocket'

interface MockMessageEvent {
  data: string
}

/** 捕获 hook 内部创建的 WebSocket 实例,便于手动派发 onmessage 帧。 */
interface CapturedWebSocket {
  onmessage: (event: MockMessageEvent) => void
  send: ReturnType<typeof vi.fn>
  close: ReturnType<typeof vi.fn>
}

describe('useWebSocket.git_branch 订阅', () => {
  let ws: CapturedWebSocket | null = null

  beforeEach(() => {
    vi.stubGlobal('WebSocket', class {
      static OPEN = 1
      readyState = 1
      send = vi.fn()
      close = vi.fn()
      constructor() {
        ws = this as unknown as CapturedWebSocket
      }
    })
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    ws = null
  })

  /** 向 hook 的 WebSocket onmessage 派发一条文本帧。 */
  function dispatch(payload: string) {
    act(() => {
      ws!.onmessage({ data: payload })
    })
  }

  it('订阅后收到 git_branch 消息会触发回调', () => {
    const { result } = renderHook(() => useWebSocket('ws://localhost/x'))
    const received: string[] = []
    result.current.subscribe(msg => {
      received.push(msg.git_branch?.branch ?? '')
    })

    dispatch(JSON.stringify({ git_branch: { workspace: '/ws', branch: 'main' } }))
    expect(received).toEqual(['main'])
  })

  it('unsubscribe 后不再触发回调', () => {
    const { result } = renderHook(() => useWebSocket('ws://localhost/x'))
    const received: string[] = []
    const unsub = result.current.subscribe(msg => {
      received.push(msg.git_branch?.branch ?? '')
    })

    dispatch(JSON.stringify({ git_branch: { workspace: '/ws', branch: 'main' } }))
    expect(received).toEqual(['main'])

    unsub()
    dispatch(JSON.stringify({ git_branch: { workspace: '/ws', branch: 'feature' } }))
    expect(received).toEqual(['main'])
  })

  it('malformed JSON 不崩溃、不触发回调,后续合法消息仍能派发', () => {
    const { result } = renderHook(() => useWebSocket('ws://localhost/x'))
    const received: string[] = []
    result.current.subscribe(msg => {
      received.push(msg.git_branch?.branch ?? '')
    })

    dispatch('not-json{{')
    expect(received).toHaveLength(0)

    dispatch(JSON.stringify({ git_branch: { workspace: '/ws', branch: 'main' } }))
    expect(received).toEqual(['main'])
  })

  it('非 git_branch 消息不触发监听者', () => {
    const { result } = renderHook(() => useWebSocket('ws://localhost/x'))
    const received: string[] = []
    result.current.subscribe(msg => {
      received.push(msg.git_branch?.branch ?? '')
    })

    dispatch(JSON.stringify({ foo: 'bar' }))
    expect(received).toHaveLength(0)
  })
})

describe('advanceFor 打字机时间基推进', () => {
  it('正常 18ms 间隔:等效 1 个 tick,与固定步进一致(阶梯 5/6/3 字)', () => {
    expect(advanceFor(0, 18)).toBe(5)
    expect(advanceFor(79, 18)).toBe(5)
    expect(advanceFor(80, 18)).toBe(6)
    expect(advanceFor(240, 18)).toBe(3)
  })

  it('后台节流:单次 tick 按真实经过时间比例补齐', () => {
    // 节流期间一次 tick 顶 10 个等效 tick(仍在 <80 字档位,精确可算)
    expect(advanceFor(0, 180)).toBe(50)
    // ~1s 未被调度:一次补齐 ≈55 个等效 tick(旧逻辑只会推进 3-6 字)
    expect(advanceFor(5, 1000)).toBeGreaterThan(250)
    expect(advanceFor(5, 1000)).toBeLessThanOrEqual(56 * 6)
  })

  it('早到的 tick(加工期抖动)按 1 个等效 tick 处理', () => {
    expect(advanceFor(0, 0)).toBe(5)
    expect(advanceFor(0, 4)).toBe(5)
  })
})

/** 描述块内复用的 WS 桩:捕获实例并保持 OPEN 状态,send 记录上行帧。 */
function stubChatWebSocket() {
  let ws: CapturedWebSocket | null = null
  vi.stubGlobal('WebSocket', class {
    static OPEN = 1
    readyState = 1
    send = vi.fn()
    close = vi.fn()
    constructor() {
      ws = this as unknown as CapturedWebSocket
    }
  })
  return () => ws
}

function lastAssistantContent(result: { current: ReturnType<typeof useWebSocket> }): string {
  const list = result.current.messages
  for (let i = list.length - 1; i >= 0; i--) {
    if (list[i].role === 'assistant') return list[i].content
  }
  return ''
}

describe('useWebSocket 打字机推进节奏', () => {
  let getWs: () => CapturedWebSocket | null

  beforeEach(() => {
    getWs = stubChatWebSocket()
    // 全量 fake(定时器 + Date):advanceTimersByTime 推进时会同步推进时钟,
    // 单次 tick 的 elapsed 恰为步长 → 可精确断言前台节奏不受改造影响。
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  function dispatch(payload: string) {
    act(() => {
      getWs()!.onmessage({ data: payload })
    })
  }

  it('前台 18ms 一 tick:推进量与旧固定步进逐字一致', () => {
    const { result } = renderHook(() => useWebSocket('ws://localhost/x', 'c1'))
    dispatch(JSON.stringify({ chunk: 'x'.repeat(1000), conversation_id: 'c1' }))

    act(() => { vi.advanceTimersByTime(18) })
    expect(lastAssistantContent(result)).toHaveLength(5)
    act(() => { vi.advanceTimersByTime(18) })
    expect(lastAssistantContent(result)).toHaveLength(10)

    // 连续 30 tick:阶梯档位混合,只做区间断言(10 起步,5 字档跑到 80 后转 6 字档)
    act(() => { vi.advanceTimersByTime(18 * 30) })
    const len = lastAssistantContent(result).length
    expect(len).toBeGreaterThan(100)
    expect(len).toBeLessThan(300)
  })
})

describe('useWebSocket 后台节流补齐(集成)', () => {
  let getWs: () => CapturedWebSocket | null

  beforeEach(() => {
    getWs = stubChatWebSocket()
    // 只 fake Date:setInterval 保持真实节奏,时钟跳变才等价于
    // "浏览器后台节流后很久才轮到一次 tick"的真实场景。
    vi.useFakeTimers({ toFake: ['Date'] })
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  function dispatch(payload: string) {
    act(() => {
      getWs()!.onmessage({ data: payload })
    })
  }

  it('系统时钟跳变后,单个真实 tick 按比例补齐后台期间进度', async () => {
    const { result } = renderHook(() => useWebSocket('ws://localhost/x', 'c1'))
    dispatch(JSON.stringify({ chunk: 'x'.repeat(2000), conversation_id: 'c1' }))

    // 前台正常跑一小段,建立基线(真实 18ms interval)。注意:tick 的
    // setMessages 在 act 退出时才提交,读取必须放在 act 块之外。
    await act(async () => {
      await new Promise(r => setTimeout(r, 80))
    })
    const baseline = lastAssistantContent(result).length

    // 模拟后台节流:时钟跳 1s(真实定时器不会补火),再等一个真实 tick
    await act(async () => {
      vi.advanceTimersByTime(1000)
      await new Promise(r => setTimeout(r, 80))
    })
    const after = lastAssistantContent(result).length

    // 旧逻辑单 tick 只推进 3-6 字;新逻辑一次补齐 ≈55 个等效 tick
    expect(after - baseline).toBeGreaterThan(250)
    expect(after).toBeLessThanOrEqual(2000)
  })
})

describe('useWebSocket 切回视图收尾(done 后切回)', () => {
  let getWs: () => CapturedWebSocket | null

  beforeEach(() => {
    getWs = stubChatWebSocket()
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('/api/v1/conversations/')) {
        return { ok: true, json: async () => ({ messages: [] }) } as Response
      }
      return { ok: true, json: async () => ({}) } as Response
    }) as unknown as typeof fetch)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  function dispatch(payload: string) {
    act(() => {
      getWs()!.onmessage({ data: payload })
    })
  }

  it('done 已到、打字机未追平时切回:完整回复显示且待发消息自动发送', async () => {
    const { result } = renderHook(() => useWebSocket('ws://localhost/x', 'c1'))
    // 大 buffer + 不推进真实时钟 → done 到达时打字机必然尚未追平
    dispatch(JSON.stringify({ chunk: 'a'.repeat(500), conversation_id: 'c1' }))
    act(() => { result.current.queuePendingMessage('follow-up', 'c1') })
    dispatch(JSON.stringify({ done: true, conversation_id: 'c1' }))

    // 模拟切回聊天页:ChatWindow 挂载即执行 clearMessages() + loadHistory('c1')
    await act(async () => {
      result.current.clearMessages()
      await result.current.loadHistory('c1')
    })

    // 完整回复通过完成快照兜底显示(既有行为,确认未被破坏)
    expect(result.current.messages.some(m => m.role === 'assistant' && m.content === 'a'.repeat(500))).toBe(true)
    // 回归点:此前该场景下 firePendingFor 永不触发,待发消息会永久卡住
    const sent = getWs()!.send.mock.calls.map(call => JSON.parse(call[0] as string))
    expect(sent).toContainEqual(expect.objectContaining({ message: 'follow-up', conversation_id: 'c1' }))
  })
})

/** 重连测试用的可编程 WS 桩:onopen/onclose 由测试手动触发,实例全部入册。 */
interface ReconnectableWS {
  onopen: ((event: Event) => void) | null
  onmessage: ((event: { data: string }) => void) | null
  onclose: ((event: CloseEvent) => void) | null
  send: ReturnType<typeof vi.fn>
  close: ReturnType<typeof vi.fn>
}

describe('useWebSocket 断线重连与心跳', () => {
  let instances: ReconnectableWS[]

  beforeEach(() => {
    instances = []
    vi.stubGlobal('WebSocket', class {
      static OPEN = 1
      readyState = 1
      onopen: ((event: Event) => void) | null = null
      onmessage: ((event: { data: string }) => void) | null = null
      onclose: ((event: CloseEvent) => void) | null = null
      send = vi.fn()
      close = vi.fn()
      constructor() {
        instances.push(this as unknown as ReconnectableWS)
      }
    })
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  const open = (ws: ReconnectableWS) => act(() => ws.onopen?.(new Event('open')))
  const close = (ws: ReconnectableWS) => act(() => ws.onclose?.(new CloseEvent('close')))

  it('意外断开后按指数退避自动重连', () => {
    renderHook(() => useWebSocket('ws://localhost/x', 'c1'))
    const ws1 = instances[0]
    open(ws1)

    // 第一次断开:基数 1s × 抖动(0.8~1.2) → 延迟 ∈ [800, 1200]
    close(ws1)
    expect(instances).toHaveLength(1)
    act(() => { vi.advanceTimersByTime(799) })
    expect(instances).toHaveLength(1)
    act(() => { vi.advanceTimersByTime(401) })
    expect(instances).toHaveLength(2)

    // 第二次断开(未再 open):基数 2s → 延迟 ∈ [1600, 2400]
    close(instances[1])
    act(() => { vi.advanceTimersByTime(1599) })
    expect(instances).toHaveLength(2)
    act(() => { vi.advanceTimersByTime(801) })
    expect(instances).toHaveLength(3)
  })

  it('重连成功后复位状态、清零退避并刷新当前会话历史', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) =>
      String(input).includes('/api/v1/conversations/')
        ? ({ ok: true, json: async () => ({ messages: [] }) } as Response)
        : ({ ok: true, json: async () => ({}) } as Response)
    )
    vi.stubGlobal('fetch', fetchMock)

    const { result } = renderHook(() => useWebSocket('ws://localhost/x', 'c1'))
    const ws1 = instances[0]
    open(ws1)
    close(ws1)
    expect(result.current.isReconnecting).toBe(true)

    act(() => { vi.advanceTimersByTime(1200) })
    const ws2 = instances[1]
    await act(async () => { open(ws2) })

    expect(result.current.isReconnecting).toBe(false)
    expect(result.current.isConnected).toBe(true)
    // 断线期间的落库变化(在途生成被取消等)通过重载历史对齐
    expect(fetchMock).toHaveBeenCalledWith('/api/v1/conversations/c1')

    // 退避计数已清零:再次断开回到 1s 档
    close(ws2)
    act(() => { vi.advanceTimersByTime(1200) })
    expect(instances).toHaveLength(3)
  })

  it('心跳:每 25s 发 ping,持续无帧超过 70s 判死并主动断开', () => {
    renderHook(() => useWebSocket('ws://localhost/x', 'c1'))
    const ws1 = instances[0]
    open(ws1)

    act(() => { vi.advanceTimersByTime(25_000) })
    expect(ws1.send).toHaveBeenCalledWith('{"ping":true}')
    act(() => { vi.advanceTimersByTime(25_000) })
    expect(ws1.send).toHaveBeenCalledTimes(2)
    // 75s 无任何帧 → 判死,主动 close(走 onclose 统一重连),不再发 ping
    act(() => { vi.advanceTimersByTime(25_000) })
    expect(ws1.close).toHaveBeenCalled()
    expect(ws1.send).toHaveBeenCalledTimes(2)
  })

  it('收到任何帧都刷新活性,心跳不会误杀活跃连接', () => {
    renderHook(() => useWebSocket('ws://localhost/x', 'c1'))
    const ws1 = instances[0]
    open(ws1)

    for (let i = 0; i < 3; i++) {
      act(() => { vi.advanceTimersByTime(25_000) })
      expect(ws1.close).not.toHaveBeenCalled()
      expect(ws1.send).toHaveBeenCalledWith('{"ping":true}')
      // 后端 pong(或任意帧)到达 → 活性时间戳前移
      act(() => { ws1.onmessage?.({ data: '{"pong":true}' }) })
    }
    expect(ws1.send).toHaveBeenCalledTimes(3)
  })

  it('卸载后的 onclose 不再调度重连', () => {
    const { unmount } = renderHook(() => useWebSocket('ws://localhost/x', 'c1'))
    const ws1 = instances[0]
    open(ws1)
    unmount()
    close(ws1)
    act(() => { vi.advanceTimersByTime(60_000) })
    expect(instances).toHaveLength(1)
  })

  it('换代后旧 socket 的迟到 onclose 被忽略', () => {
    renderHook(() => useWebSocket('ws://localhost/x', 'c1'))
    const ws1 = instances[0]
    open(ws1)
    close(ws1)
    act(() => { vi.advanceTimersByTime(1200) })
    expect(instances).toHaveLength(2)
    // ws1 已被新一代连接替换:它迟到的 onclose 不得再触发调度(防双连接)
    close(ws1)
    act(() => { vi.advanceTimersByTime(60_000) })
    expect(instances).toHaveLength(2)
  })
})

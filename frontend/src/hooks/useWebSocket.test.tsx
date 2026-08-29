import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { useWebSocket } from './useWebSocket'

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

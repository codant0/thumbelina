import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderHook, act, waitFor } from '@testing-library/react'
import { useUploadTasks } from './useUploadTasks'

let fetchMock: ReturnType<typeof vi.fn>

function respond(tasks: unknown[]) {
  fetchMock.mockResolvedValueOnce(
    new Response(JSON.stringify(tasks), { status: 200 }),
  )
}

describe('useUploadTasks', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    // @testing-library/dom 仅通过全局 jest 检测 fake timers（见 DTL #1197），
    // Vitest 不提供该全局，需手动桥接，否则 waitFor 的重试定时器被 fake 时钟接管后永不触发。
    vi.stubGlobal('jest', vi)
    fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  it('loads tasks on mount', async () => {
    respond([{ id: 't1', status: 'completed' }])
    const { result } = renderHook(() => useUploadTasks('kb1'))
    await waitFor(() => expect(result.current.tasks).toHaveLength(1))
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('polls while active tasks exist and stops after settle', async () => {
    respond([{ id: 't1', status: 'running' }])
    const onSettled = vi.fn()
    const { result } = renderHook(() => useUploadTasks('kb1', onSettled))
    await waitFor(() => expect(result.current.tasks).toHaveLength(1))

    respond([{ id: 't1', status: 'running' }])
    await act(async () => { await vi.advanceTimersByTimeAsync(1000) })
    expect(fetchMock).toHaveBeenCalledTimes(2)

    respond([{ id: 't1', status: 'completed' }])
    await act(async () => { await vi.advanceTimersByTimeAsync(1000) })
    await waitFor(() => expect(onSettled).toHaveBeenCalledTimes(1))

    await act(async () => { await vi.advanceTimersByTimeAsync(3000) })
    expect(fetchMock).toHaveBeenCalledTimes(3) // 不再轮询
  })

  it('cancel calls DELETE and refreshes', async () => {
    respond([{ id: 't1', status: 'running' }])
    const { result } = renderHook(() => useUploadTasks('kb1'))
    await waitFor(() => expect(result.current.tasks).toHaveLength(1))

    fetchMock.mockResolvedValueOnce(new Response('{"cancelled": true}', { status: 200 }))
    respond([])
    await act(async () => { await result.current.cancel('t1') })
    expect(fetchMock.mock.calls[1][1]?.method).toBe('DELETE')
  })

  it('dismissed terminal tasks stay hidden after refresh', async () => {
    respond([
      { id: 't1', status: 'completed' },
      { id: 't2', status: 'running' },
    ])
    const { result } = renderHook(() => useUploadTasks('kb1'))
    await waitFor(() => expect(result.current.tasks).toHaveLength(2))

    act(() => result.current.dismiss('t1'))
    expect(result.current.tasks).toHaveLength(1)

    respond([
      { id: 't1', status: 'completed' },
      { id: 't2', status: 'completed' },
    ])
    await act(async () => { await result.current.refresh() })
    expect(result.current.tasks.map(t => t.id)).toEqual(['t2'])
  })

  it('resets when kbId changes', async () => {
    respond([{ id: 't1', status: 'completed' }])
    const { result, rerender } = renderHook(
      ({ kb }: { kb: string | null }) => useUploadTasks(kb),
      { initialProps: { kb: 'kb1' as string | null } },
    )
    await waitFor(() => expect(result.current.tasks).toHaveLength(1))
    rerender({ kb: null })
    expect(result.current.tasks).toHaveLength(0)
  })
})

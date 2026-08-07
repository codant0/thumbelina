import { useCallback, useEffect, useRef, useState } from 'react'
import type { UploadTask } from '../types/rag'
import * as ragApi from '../api/rag'

const POLL_INTERVAL_MS = 1000

function isActive(t: UploadTask): boolean {
  return t.status === 'pending' || t.status === 'running'
}

export function useUploadTasks(kbId: string | null, onSettled?: () => void) {
  const [tasks, setTasks] = useState<UploadTask[]>([])
  const prevActiveRef = useRef<Set<string>>(new Set())
  const dismissedRef = useRef<Set<string>>(new Set())
  const onSettledRef = useRef(onSettled)

  useEffect(() => {
    onSettledRef.current = onSettled
  }, [onSettled])

  const refresh = useCallback(async () => {
    if (!kbId) return
    try {
      const list = await ragApi.listUploadTasks(kbId)
      const visible = list.filter(t => !dismissedRef.current.has(t.id))
      const activeIds = new Set(visible.filter(isActive).map(t => t.id))
      const settledNow = [...prevActiveRef.current].filter(id => !activeIds.has(id))
      prevActiveRef.current = activeIds
      setTasks(visible)
      if (settledNow.length > 0) onSettledRef.current?.()
    } catch {
      // 轮询的瞬时错误忽略，下一轮重试
    }
  }, [kbId])

  useEffect(() => {
    if (!kbId) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setTasks([])
      prevActiveRef.current = new Set()
      dismissedRef.current = new Set()
      return
    }
    void refresh()
  }, [kbId, refresh])

  const hasActive = tasks.some(isActive)

  useEffect(() => {
    if (!kbId || !hasActive) return
    const timer = setInterval(() => void refresh(), POLL_INTERVAL_MS)
    return () => clearInterval(timer)
  }, [kbId, hasActive, refresh])

  const submitFiles = useCallback(
    async (files: File[]) => {
      if (!kbId) return
      await ragApi.uploadFilesAsync(kbId, files)
      await refresh()
    },
    [kbId, refresh],
  )

  const submitUrl = useCallback(
    async (url: string) => {
      if (!kbId) return
      await ragApi.uploadUrlAsync(kbId, url)
      await refresh()
    },
    [kbId, refresh],
  )

  const cancel = useCallback(
    async (taskId: string) => {
      await ragApi.cancelUploadTask(taskId)
      await refresh()
    },
    [refresh],
  )

  const dismiss = useCallback((taskId: string) => {
    dismissedRef.current.add(taskId)
    setTasks(prev => prev.filter(t => t.id !== taskId))
  }, [])

  return { tasks, hasActive, submitFiles, submitUrl, cancel, dismiss, refresh }
}

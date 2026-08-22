import { useCallback, useState } from 'react'

const STORAGE_KEY = 'thumbelina-statusbar-items'

export interface StatusBarConfig {
  /** 上下文占用栏目是否展示 */
  context: boolean
  /** KV 缓存命中率栏目是否展示 */
  cacheHit: boolean
}

const DEFAULTS: StatusBarConfig = { context: true, cacheHit: true }

function load(): StatusBarConfig {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return DEFAULTS
    const parsed = JSON.parse(raw) as Partial<StatusBarConfig>
    return {
      context: typeof parsed.context === 'boolean' ? parsed.context : DEFAULTS.context,
      cacheHit: typeof parsed.cacheHit === 'boolean' ? parsed.cacheHit : DEFAULTS.cacheHit,
    }
  } catch {
    return DEFAULTS
  }
}

/**
 * 状态栏栏目展示开关，localStorage 持久化（沿用 `thumbelina-*` 命名）。
 * 聊天页与设置页不同时挂载，故每次挂载时从 localStorage 读取即可保持最新。
 */
export function useStatusBarConfig() {
  const [config, setConfig] = useState<StatusBarConfig>(load)

  const toggle = useCallback((key: keyof StatusBarConfig) => {
    setConfig(prev => {
      const next = { ...prev, [key]: !prev[key] }
      try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(next))
      } catch {
        // 持久化失败时仅保留内存态
      }
      return next
    })
  }, [])

  return { config, toggle }
}

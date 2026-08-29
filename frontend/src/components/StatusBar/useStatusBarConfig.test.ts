import { describe, it, expect, beforeEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { useStatusBarConfig } from './useStatusBarConfig'

describe('useStatusBarConfig', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('默认展示所有栏目（context 为 true）', () => {
    const { result } = renderHook(() => useStatusBarConfig())
    expect(result.current.config.context).toBe(true)
  })

  it('从 localStorage 读取已保存的配置', () => {
    localStorage.setItem('thumbelina-statusbar-items', JSON.stringify({ context: false }))
    const { result } = renderHook(() => useStatusBarConfig())
    expect(result.current.config.context).toBe(false)
  })

  it('toggle 会切换状态并持久化到 localStorage', () => {
    const { result } = renderHook(() => useStatusBarConfig())
    act(() => result.current.toggle('context'))
    expect(result.current.config.context).toBe(false)
    const saved = JSON.parse(localStorage.getItem('thumbelina-statusbar-items') ?? '{}')
    expect(saved.context).toBe(false)
  })

  it('localStorage 数据损坏时回落到默认值', () => {
    localStorage.setItem('thumbelina-statusbar-items', 'not json')
    const { result } = renderHook(() => useStatusBarConfig())
    expect(result.current.config.context).toBe(true)
  })
})

describe('useStatusBarConfig cacheHit 栏目', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('默认展示缓存命中率栏目', () => {
    const { result } = renderHook(() => useStatusBarConfig())
    expect(result.current.config.cacheHit).toBe(true)
  })

  it('从 localStorage 读取 cacheHit 开关', () => {
    localStorage.setItem('thumbelina-statusbar-items', JSON.stringify({ context: true, cacheHit: false }))
    const { result } = renderHook(() => useStatusBarConfig())
    expect(result.current.config.cacheHit).toBe(false)
  })

  it('旧配置(无 cacheHit 键)回落默认开启', () => {
    localStorage.setItem('thumbelina-statusbar-items', JSON.stringify({ context: false }))
    const { result } = renderHook(() => useStatusBarConfig())
    expect(result.current.config.cacheHit).toBe(true)
  })

  it('toggle 切换并持久化', () => {
    const { result } = renderHook(() => useStatusBarConfig())
    act(() => result.current.toggle('cacheHit'))
    expect(result.current.config.cacheHit).toBe(false)
    const saved = JSON.parse(localStorage.getItem('thumbelina-statusbar-items') ?? '{}')
    expect(saved.cacheHit).toBe(false)
  })
})

describe('useStatusBarConfig git 栏目', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('默认展示 git 栏目', () => {
    const { result } = renderHook(() => useStatusBarConfig())
    expect(result.current.config.git).toBe(true)
  })

  it('旧配置(无 git 键)回落默认开启', () => {
    localStorage.setItem('thumbelina-statusbar-items', JSON.stringify({ context: false }))
    const { result } = renderHook(() => useStatusBarConfig())
    expect(result.current.config.git).toBe(true)
  })

  it('toggle 切换并持久化', () => {
    const { result } = renderHook(() => useStatusBarConfig())
    act(() => result.current.toggle('git'))
    expect(result.current.config.git).toBe(false)
    const saved = JSON.parse(localStorage.getItem('thumbelina-statusbar-items') ?? '{}')
    expect(saved.git).toBe(false)
  })
})

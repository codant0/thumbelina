import { describe, it, expect } from 'vitest'
import { estimateTokens, parseContextWindow } from './estimateTokens'

describe('estimateTokens', () => {
  it('同为纯 ASCII 字符串按 0.25 token/字符估算（截断）', () => {
    // 5 * 0.25 = 1.25 → floor 1
    expect(estimateTokens('hello')).toBe(1)
    // 11 * 0.25 = 2.75 → floor 2
    expect(estimateTokens('hello world')).toBe(2)
  })

  it('CJK 字符按 2 token/字估算', () => {
    // 2 * 2 = 4
    expect(estimateTokens('你好')).toBe(4)
    // 3 * 2 = 6
    expect(estimateTokens('你好世界啊')).toBe(10)
  })

  it('混合字符按各自比例估算', () => {
    // 2 CJK + 5 ascii = 2*2 + 5*0.25 = 5.25 → floor 5
    expect(estimateTokens('你好world')).toBe(5)
  })

  it('空字符串为 0', () => {
    expect(estimateTokens('')).toBe(0)
  })

  it('全角/扩展 CJK 也计入（east_asian_width W/F）', () => {
    expect(estimateTokens('ｈｅｌｌｏ')).toBe(10) // 全角 5 字符 * 2
    expect(estimateTokens('가나다')).toBe(6) // 谚文
  })
})

describe('parseContextWindow', () => {
  it('解析纯数字', () => {
    expect(parseContextWindow('32000')).toBe(32000)
  })

  it('解析 K/M 后缀（不区分大小写）', () => {
    expect(parseContextWindow('128K')).toBe(128000)
    expect(parseContextWindow('128k')).toBe(128000)
    expect(parseContextWindow('1M')).toBe(1000000)
    expect(parseContextWindow('1m')).toBe(1000000)
  })

  it('容忍前后空白', () => {
    expect(parseContextWindow(' 128K ')).toBe(128000)
  })

  it('无法解析 / 空值返回 null', () => {
    expect(parseContextWindow(null)).toBeNull()
    expect(parseContextWindow(undefined)).toBeNull()
    expect(parseContextWindow('')).toBeNull()
    expect(parseContextWindow('12x')).toBeNull()
    expect(parseContextWindow('abc')).toBeNull()
  })
})

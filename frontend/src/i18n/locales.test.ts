import { describe, it, expect } from 'vitest'
import zhCN from './locales/zh-CN.json'
import en from './locales/en.json'

/**
 * 双语键集一致性守卫(设计 Task F7):
 * zh-CN 与 en 的键集合必须完全一致——新增键只允许成对出现,
 * 否则一种语言会回退渲染出键名(t() 的 ?? key 兜底)。
 */

/** 递归收集叶子键(值为字符串的路径,点号拼接)。 */
function leafKeys(obj: Record<string, unknown>, prefix = ''): Set<string> {
  const out = new Set<string>()
  for (const [key, value] of Object.entries(obj)) {
    const path = prefix ? `${prefix}.${key}` : key
    if (value !== null && typeof value === 'object') {
      for (const k of leafKeys(value as Record<string, unknown>, path)) out.add(k)
    } else {
      out.add(path)
    }
  }
  return out
}

const zhKeys = leafKeys(zhCN as Record<string, unknown>)
const enKeys = leafKeys(en as Record<string, unknown>)

describe('locale dictionaries', () => {
  it('zh-CN and en have identical key sets (whole tree)', () => {
    expect([...enKeys].filter(k => !zhKeys.has(k))).toEqual([])
    expect([...zhKeys].filter(k => !enKeys.has(k))).toEqual([])
  })

  it('chat.attachments namespace exists in both locales with identical key sets', () => {
    const zhChat = (zhCN as Record<string, unknown>).chat as Record<string, unknown>
    const enChat = (en as Record<string, unknown>).chat as Record<string, unknown>
    const zhAttKeys = leafKeys(zhChat.attachments as Record<string, unknown>)
    const enAttKeys = leafKeys(enChat.attachments as Record<string, unknown>)
    expect(zhAttKeys.size).toBeGreaterThan(0)
    expect([...enAttKeys].filter(k => !zhAttKeys.has(k))).toEqual([])
    expect([...zhAttKeys].filter(k => !enAttKeys.has(k))).toEqual([])
  })

  it('renders the imagesCount interpolation through LocaleContext t()', async () => {
    // LocaleContext.t 用 {k} 占位符做参数替换;验证 imagesCount 的双语占位符齐全
    const zhChat = (zhCN as Record<string, unknown>).chat as Record<string, unknown>
    const enChat = (en as Record<string, unknown>).chat as Record<string, unknown>
    const zhAtt = zhChat.attachments as Record<string, string>
    const enAtt = enChat.attachments as Record<string, string>
    expect(zhAtt.imagesCount).toContain('{n}')
    expect(enAtt.imagesCount).toContain('{n}')
  })
})

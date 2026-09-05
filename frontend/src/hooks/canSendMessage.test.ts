import { describe, it, expect } from 'vitest'
import { canSendMessage } from './useWebSocket'

// 协议约束(设计 §4.1):message 与 attachments 至少一项非空,
// 发送按钮启用条件集中在这里,InputBox/Coder 输入框共用。
describe('canSendMessage', () => {
  it('有非空白文字即可发送(无附件)', () => {
    expect(canSendMessage('hello', 0)).toBe(true)
    expect(canSendMessage('  x  ', 0)).toBe(true)
  })

  it('空串或纯空白视为无文字,无附件时不可发送', () => {
    expect(canSendMessage('', 0)).toBe(false)
    expect(canSendMessage('   ', 0)).toBe(false)
    expect(canSendMessage('\n\t ', 0)).toBe(false)
  })

  it('无文字但带附件即可发送(纯图片消息)', () => {
    expect(canSendMessage('', 1)).toBe(true)
    expect(canSendMessage('   ', 3)).toBe(true)
  })
})

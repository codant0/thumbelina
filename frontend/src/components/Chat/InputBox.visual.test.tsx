import { describe, it, expect, beforeAll } from 'vitest'
import { render } from '@testing-library/react'
import { InputBox, type LocalAttachment } from './InputBox'
// 拉入 composer.css + chat.css + themes.css 使 jsdom 解析得到 .pending-float-* /
// .attachments-strip / .attachment-thumb 的真实规则与主题 token。
import '../../styles/composer.css'
import '../../styles/chat.css'
import '../../styles/themes.css'

// themes.css 的 token 写在 [data-theme="dark"] 等选择器下;为让 jsdom 解析得到
// 变量值,在根节点上挂上 data-theme="dark"(应用默认的 dark 主题 token)。
beforeAll(() => {
  document.documentElement.setAttribute('data-theme', 'dark')
})

// jsdom 不展开 var(--x) 与 @keyframes;为断言"规则已被消费"——直接遍历 stylesheet。
const allRuleText = (): string => {
  let buf = ''
  for (const sheet of Array.from(document.styleSheets)) {
    try {
      for (const rule of Array.from(sheet.cssRules)) {
        buf += rule.cssText + '\n'
      }
    } catch {
      // cross-origin sheet — ignore
    }
  }
  return buf
}

// Layout/color-shape assertions for the queued message bar.
// jsdom computes the computed value of CSS variables, so we read what the
// browser would actually see for the accent strip, chip background, and the
// preview scroll container.

const renderBar = (props: Record<string, unknown>) =>
  render(
    <InputBox
      onSend={() => {}}
      pendingActive
      pendingMessage="queued text that might run on a bit"
      onSendPendingNow={() => {}}
      onCancelPending={() => {}}
      {...props}
    />,
  )

const readVar = (el: Element, varName: string): string =>
  getComputedStyle(el).getPropertyValue(varName).trim()

describe('PendingMessageBar layout', () => {
  it('colors the icon chip with accent-secondary-muted in auto state', () => {
    const { container } = renderBar({})
    const chip = container.querySelector('.pending-float-icon-chip') as HTMLElement
    expect(chip).toBeTruthy()
    expect(readVar(chip, '--accent-secondary-muted')).toBeTruthy()
  })

  it('colors the icon chip with warning-muted in held state', () => {
    const { container } = renderBar({ pendingHeld: true })
    const chip = container.querySelector('.pending-float-icon-chip') as HTMLElement
    expect(readVar(chip, '--warning-muted')).toBeTruthy()
  })

  it('keeps the preview scrollable rather than overflowing the card', () => {
    const { container } = renderBar({ pendingMessage: 'A very long text '.repeat(40) })
    const preview = container.querySelector('.pending-float-text') as HTMLElement
    expect(preview).toBeTruthy()
    const cs = getComputedStyle(preview)
    expect(cs.overflowY).toBe('auto')
    expect(parseInt(cs.maxHeight, 10)).toBeLessThanOrEqual(96)
  })

  it('uses a 12px rounded glass card with gradient + backdrop blur', () => {
    const { container } = renderBar({})
    const card = container.querySelector('.pending-float') as HTMLElement
    expect(card).toBeTruthy()
    // jsdom 不展开 var(--x) 与 backdrop-filter;改用 stylesheet 文本断言 token 被消费。
    const rules = allRuleText()
    expect(rules).toMatch(/\.pending-float\s*\{[^}]*border-radius:\s*var\(--pending-radius\)/)
    expect(rules).toMatch(/\.pending-float\s*\{[^}]*background-image:\s*linear-gradient\(/)
    expect(rules).toMatch(/\.pending-float\s*\{[^}]*backdrop-filter:\s*blur\(/)
  })

  it('is narrower than the input box — centered, ~2/3 width', () => {
    // jsdom 不解析 calc()/var();断言 stylesheet 文本包含 width/居中声明。
    const rules = allRuleText()
    expect(rules).toMatch(/\.pending-float\s*\{[^}]*width:\s*calc\(/)
    expect(rules).toMatch(/\.pending-float\s*\{[^}]*\/\s*3/)
    expect(rules).toMatch(/\.pending-float\s*\{[^}]*left:\s*50%/)
    expect(rules).toMatch(/\.pending-float\s*\{[^}]*margin-left:\s*calc\(/)
  })

  it('pulses the icon chip in auto state and freezes it in held', () => {
    // jsdom 不解析 @keyframes → animation-name 始终是 none;改为断言 stylesheet 中
    // auto 规则包含 pending-pulse 动画、held 规则包含 animation:none。
    const rules = allRuleText()
    expect(rules).toMatch(/\.pending-float-icon-chip\s*\{[^}]*animation:\s*pending-pulse/)
    expect(rules).toMatch(/@keyframes\s+pending-pulse/)
    expect(rules).toMatch(/\[data-state="held"\]\s*\.pending-float-icon-chip\s*\{[^}]*animation:\s*none/)
  })

  it('renders action buttons as pills (height 32, border-radius 9999)', () => {
    const { container } = renderBar({})
    const cancel = container.querySelector('[data-testid="pending-cancel"]') as HTMLElement
    const send = container.querySelector('[data-testid="pending-send-now"]') as HTMLElement
    for (const el of [cancel, send]) {
      const cs = getComputedStyle(el)
      expect(cs.borderRadius).toBe('9999px')
      expect(parseInt(cs.height, 10)).toBe(32)
    }
  })
})

// 带缩略图 + 流式中的 composer 布局(Task F8 视觉补缺):jsdom 结构断言风格,
// 与上方 pending-float 用例同范式 —— DOM 结构 + stylesheet 令牌消费断言。
describe('AttachmentStrip + streaming composer layout', () => {
  const readyAtt = (i: number): LocalAttachment => ({
    localId: `local-${i}`,
    file: new File(['x'], `shot${i}.png`, { type: 'image/png' }),
    status: 'ready',
    uploaded: { id: `att-${i}`, mime: 'image/png', size: 1, width: 10, height: 10, sha256: null },
    previewUrl: '',
  })

  it('renders two ready thumbnails above the composer with the stop button while streaming', () => {
    const { container } = render(
      <InputBox
        onSend={() => {}}
        isStreaming
        onStop={() => {}}
        onQueueSend={() => {}}
        attachments={[readyAtt(1), readyAtt(2)]}
        onAttachmentsChange={() => {}}
      />,
    )

    // 结构:缩略条在表单上方,两张就绪缩略卡,流式停止按钮与发送并排。
    const strip = container.querySelector('[data-testid="attachments-strip"]') as HTMLElement
    expect(strip).toBeTruthy()
    const form = container.querySelector('form') as HTMLElement
    expect(strip.compareDocumentPosition(form) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    const thumbs = [...strip.querySelectorAll('.attachment-thumb')]
    expect(thumbs).toHaveLength(2)
    for (const thumb of thumbs) expect(thumb.getAttribute('data-status')).toBe('ready')
    expect(container.querySelector('[data-testid="stop-generation"]')).toBeTruthy()
    expect(container.querySelector('.attach-btn')).toBeTruthy()

    // 令牌消费:48×48 缩略卡与间距走主题变量(chat.css),非硬编码色值。
    const rules = allRuleText()
    expect(rules).toMatch(/\.attachment-thumb\s*\{[^}]*width:\s*48px/)
    expect(rules).toMatch(/\.attachment-thumb\s*\{[^}]*border-radius:\s*var\(--radius\)/)
    expect(rules).toMatch(/\.attachment-thumb\s*\{[^}]*border:\s*1px solid var\(--border\)/)
    expect(rules).toMatch(/\.attachments-strip\s*\{[^}]*gap:\s*var\(--sp-2\)/)
  })
})
import { describe, it, expect, beforeAll } from 'vitest'
import { render } from '@testing-library/react'
import { InputBox } from './InputBox'
// 拉入 composer.css + themes.css 使 jsdom 解析得到 .pending-float-* 的真实规则与 token。
import '../../styles/composer.css'
import '../../styles/themes.css'

// themes.css 的 token 写在 [data-theme="dark"] 等选择器下;为让 jsdom 解析得到
// 变量值,在根节点上挂上 data-theme="dark"(应用默认的 dark 主题 token)。
beforeAll(() => {
  document.documentElement.setAttribute('data-theme', 'dark')
})

// Layout/color-shape assertions for the queued message bar.
// jsdom computes the computed value of CSS variables, so we read what the
// browser would actually see for the accent strip, chip background, and the
// preview scroll container.

const renderBar = (props: Record<string, unknown>) =>
  render(
    <InputBox
      onSend={() => {}}
      pendingMessage="queued text that might run on a bit"
      onSendPendingNow={() => {}}
      onCancelPending={() => {}}
      {...props}
    />,
  )

const readVar = (el: Element, varName: string): string =>
  getComputedStyle(el).getPropertyValue(varName).trim()

describe('PendingMessageBar layout', () => {
  it('renders the 2px accent-secondary top strip on the card', () => {
    const { container } = renderBar({})
    const card = container.querySelector('.pending-float') as HTMLElement
    expect(card).toBeTruthy()
    // The accent strip is a positioned overlay at the top of the card with a
    // 2px height and an accent-secondary fill. jsdom resolves the CSS variable
    // values from the dark theme (data-theme="dark" on <html>).
    const accent = container.querySelector('.pending-float-accent') as HTMLElement
    expect(accent).toBeTruthy()
    expect(getComputedStyle(accent).height).toBe('2px')
    const accentColor = readVar(accent, '--accent-secondary')
    expect(accentColor).toBeTruthy()
  })

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
})
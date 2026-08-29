import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { StatusBarItemView } from './StatusBarItem'

describe('StatusBarItemView onClick', () => {
  it('提供 onClick 时渲染为 button 并触发回调', () => {
    const onClick = vi.fn()
    render(<StatusBarItemView label="main" state="ok" title="main" onClick={onClick} />)
    const el = screen.getByTestId('statusbar-item') as HTMLButtonElement
    expect(el.tagName).toBe('BUTTON')
    // button 保留相同 class / data-testid / title，且不加 role（原生语义）
    expect(el).toHaveClass('statusbar__item--ok')
    expect(el).toHaveAttribute('title', 'main')
    expect(el).not.toHaveAttribute('role')
    fireEvent.click(el)
    expect(onClick).toHaveBeenCalledOnce()
  })

  it('不传 onClick 时仍渲染为 span（非可点击栏目不受影响）', () => {
    render(<StatusBarItemView label="context" state="ok" />)
    const el = screen.getByTestId('statusbar-item')
    expect(el.tagName).toBe('SPAN')
    expect(el).toHaveAttribute('role', 'status')
  })
})

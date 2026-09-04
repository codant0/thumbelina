import { describe, it, expect, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { FloatWindow } from './FloatWindow'
import { LocaleProvider } from '../../i18n/LocaleContext'

function renderWithI18n(ui: React.ReactNode) {
  return render(<LocaleProvider>{ui}</LocaleProvider>)
}

describe('FloatWindow', () => {
  it('renders title and body content', () => {
    renderWithI18n(
      <FloatWindow windowId="w1" title="hello" zIndex={1000} onClose={() => {}}>
        <p data-testid="body">body content</p>
      </FloatWindow>,
    )
    expect(screen.getByText('hello')).toBeInTheDocument()
    expect(screen.getByTestId('body')).toBeInTheDocument()
  })

  it('calls onClose when X button clicked', () => {
    const onClose = vi.fn()
    renderWithI18n(
      <FloatWindow windowId="w1" title="t" zIndex={1000} onClose={onClose}>
        body
      </FloatWindow>,
    )
    fireEvent.click(screen.getByTestId('float-window-close'))
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('calls onMinimize when minimize button clicked', () => {
    const onMin = vi.fn()
    renderWithI18n(
      <FloatWindow windowId="w1" title="t" zIndex={1000} onClose={() => {}} onMinimize={onMin}>
        body
      </FloatWindow>,
    )
    fireEvent.click(screen.getByTestId('float-window-minimize'))
    expect(onMin).toHaveBeenCalledTimes(1)
  })

  it('hides body when minimized', () => {
    renderWithI18n(
      <FloatWindow windowId="w1" title="t" zIndex={1000} onClose={() => {}} minimized>
        <p data-testid="body">body</p>
      </FloatWindow>,
    )
    expect(screen.queryByTestId('body')).not.toBeInTheDocument()
  })

  it('renders resize handles', () => {
    renderWithI18n(
      <FloatWindow windowId="w1" title="t" zIndex={1000} onClose={() => {}}>
        body
      </FloatWindow>,
    )
    expect(screen.getByTestId('float-window-resize-se')).toBeInTheDocument()
    expect(screen.getByTestId('float-window-resize-n')).toBeInTheDocument()
  })

  it('closes on Escape key', () => {
    const onClose = vi.fn()
    renderWithI18n(
      <FloatWindow windowId="w1" title="t" zIndex={1000} onClose={onClose}>
        body
      </FloatWindow>,
    )
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(onClose).toHaveBeenCalledTimes(1)
  })
})
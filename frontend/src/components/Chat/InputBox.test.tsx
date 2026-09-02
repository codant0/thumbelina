import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { InputBox } from './InputBox'

describe('InputBox', () => {
  it('should render input field', () => {
    render(<InputBox onSend={vi.fn()} />)
    expect(screen.getByPlaceholderText(/Type a message/i)).toBeInTheDocument()
  })

  it('should render send button', () => {
    render(<InputBox onSend={vi.fn()} />)
    expect(screen.getByRole('button', { name: /Send/i })).toBeInTheDocument()
  })

  it('should call onSend with message text', async () => {
    const onSend = vi.fn()
    const user = userEvent.setup()

    render(<InputBox onSend={onSend} />)

    const input = screen.getByPlaceholderText(/Type a message/i)
    await user.type(input, 'Hello world')
    await user.click(screen.getByRole('button', { name: /Send/i }))

    expect(onSend).toHaveBeenCalledWith('Hello world')
  })

  it('should clear input after sending', async () => {
    const onSend = vi.fn()
    const user = userEvent.setup()

    render(<InputBox onSend={onSend} />)

    const input = screen.getByPlaceholderText(/Type a message/i)
    await user.type(input, 'Hello')
    await user.click(screen.getByRole('button', { name: /Send/i }))

    expect(input).toHaveValue('')
  })

  it('should not send empty messages', async () => {
    const onSend = vi.fn()
    const user = userEvent.setup()

    render(<InputBox onSend={onSend} />)

    await user.click(screen.getByRole('button', { name: /Send/i }))

    expect(onSend).not.toHaveBeenCalled()
  })

  it('should send on Enter key', async () => {
    const onSend = vi.fn()
    const user = userEvent.setup()

    render(<InputBox onSend={onSend} />)

    const input = screen.getByPlaceholderText(/Type a message/i)
    await user.type(input, 'Hello{enter}')

    expect(onSend).toHaveBeenCalledWith('Hello')
  })

  it('should be disabled when disabled prop is true', () => {
    render(<InputBox onSend={vi.fn()} disabled />)

    expect(screen.getByPlaceholderText(/Type a message/i)).toBeDisabled()
    expect(screen.getByRole('button', { name: /Send/i })).toBeDisabled()
  })

  it('renders a stop button while streaming and stops on click', async () => {
    const onStop = vi.fn()
    const user = userEvent.setup()

    render(<InputBox onSend={vi.fn()} isStreaming onStop={onStop} onQueueSend={vi.fn()} />)

    const stop = screen.getByTestId('stop-generation')
    await user.click(stop)
    expect(onStop).toHaveBeenCalled()
  })

  it('renders stop and send buttons side by side while streaming', () => {
    render(<InputBox onSend={vi.fn()} isStreaming onStop={vi.fn()} onQueueSend={vi.fn()} />)

    expect(screen.getByTestId('stop-generation')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Send' })).toBeInTheDocument()
  })

  it('queues the message on Enter while streaming instead of blocking', async () => {
    const onSend = vi.fn()
    const onQueueSend = vi.fn()
    const user = userEvent.setup()

    render(<InputBox onSend={onSend} isStreaming onQueueSend={onQueueSend} />)

    const input = screen.getByPlaceholderText(/Type a message/i)
    await user.type(input, 'Hello{enter}')

    expect(onSend).not.toHaveBeenCalled()
    expect(onQueueSend).toHaveBeenCalledWith('Hello')
    expect(input).toHaveValue('')
  })

  it('queues the message when clicking send while streaming', async () => {
    const onSend = vi.fn()
    const onQueueSend = vi.fn()
    const user = userEvent.setup()

    render(<InputBox onSend={onSend} isStreaming onQueueSend={onQueueSend} />)

    const input = screen.getByPlaceholderText(/Type a message/i)
    await user.type(input, 'Hello')
    await user.click(screen.getByRole('button', { name: 'Send' }))

    expect(onSend).not.toHaveBeenCalled()
    expect(onQueueSend).toHaveBeenCalledWith('Hello')
  })

  it('blocks submitting while a pending message exists (single slot)', async () => {
    const onSend = vi.fn()
    const user = userEvent.setup()

    render(
      <InputBox
        onSend={onSend}
        pendingMessage="queued text"
        onSendPendingNow={vi.fn()}
        onCancelPending={vi.fn()}
      />,
    )

    expect(screen.getByRole('button', { name: 'Send' })).toBeDisabled()

    const input = screen.getByPlaceholderText(/Type a message/i)
    await user.type(input, 'Hello{enter}')
    expect(onSend).not.toHaveBeenCalled()
  })

  it('renders the pending float with actions to send now or cancel', async () => {
    const onSendPendingNow = vi.fn()
    const onCancelPending = vi.fn()
    const user = userEvent.setup()

    render(
      <InputBox
        onSend={vi.fn()}
        pendingMessage="queued text"
        onSendPendingNow={onSendPendingNow}
        onCancelPending={onCancelPending}
      />,
    )

    expect(screen.getByTestId('pending-message')).toHaveTextContent('queued text')
    expect(screen.getByText(/Will be sent when the current reply finishes/i)).toBeInTheDocument()

    await user.click(screen.getByTestId('pending-send-now'))
    expect(onSendPendingNow).toHaveBeenCalledTimes(1)

    await user.click(screen.getByTestId('pending-cancel'))
    expect(onCancelPending).toHaveBeenCalledTimes(1)
  })

  it('shows the held hint when the previous reply ended abnormally', () => {
    render(
      <InputBox
        onSend={vi.fn()}
        pendingMessage="queued"
        pendingHeld
        onSendPendingNow={vi.fn()}
        onCancelPending={vi.fn()}
      />,
    )

    expect(screen.getByText(/auto-send paused/i)).toBeInTheDocument()
    expect(screen.queryByText(/Will be sent when the current reply finishes/i)).not.toBeInTheDocument()
  })

  it('marks the pending bar with data-state=auto when not held', () => {
    render(
      <InputBox
        onSend={vi.fn()}
        pendingMessage="queued"
        onSendPendingNow={vi.fn()}
        onCancelPending={vi.fn()}
      />,
    )
    expect(screen.getByTestId('pending-message').getAttribute('data-state')).toBe('auto')
  })

  it('marks the pending bar with data-state=held and swaps to the warning icon', () => {
    const { container } = render(
      <InputBox
        onSend={vi.fn()}
        pendingMessage="queued"
        pendingHeld
        onSendPendingNow={vi.fn()}
        onCancelPending={vi.fn()}
      />,
    )
    expect(screen.getByTestId('pending-message').getAttribute('data-state')).toBe('held')
    // icon chip carries an inline data-icon for the visual test; warning icon wins under held.
    expect(container.querySelector('.pending-float-icon-chip [data-icon="AlertCircle"]')).toBeTruthy()
    expect(container.querySelector('.pending-float-icon-chip [data-icon="Clock"]')).toBeNull()
  })

  it('uses pill variants and the right ordering (ghost cancel before primary send-now)', () => {
    render(
      <InputBox
        onSend={vi.fn()}
        pendingMessage="queued"
        onSendPendingNow={vi.fn()}
        onCancelPending={vi.fn()}
      />,
    )
    const cancel = screen.getByTestId('pending-cancel')
    const sendNow = screen.getByTestId('pending-send-now')
    expect(cancel.className).toMatch(/btn-pill/)
    expect(cancel.className).toMatch(/btn-ghost/)
    expect(sendNow.className).toMatch(/btn-pill/)
    expect(sendNow.className).toMatch(/btn-primary/)
    // DOM order: cancel first, send-now second
    expect(cancel.compareDocumentPosition(sendNow) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  })

  it('exposes the pending bar as a polite live region for screen readers', () => {
    render(
      <InputBox
        onSend={vi.fn()}
        pendingMessage="queued"
        onSendPendingNow={vi.fn()}
        onCancelPending={vi.fn()}
      />,
    )
    const bar = screen.getByTestId('pending-message')
    expect(bar.getAttribute('role')).toBe('status')
    expect(bar.getAttribute('aria-live')).toBe('polite')
  })

  it('uses pill button variant (btn-pill, ghost before primary)', () => {
    render(
      <InputBox
        onSend={vi.fn()}
        pendingMessage="queued"
        onSendPendingNow={vi.fn()}
        onCancelPending={vi.fn()}
      />,
    )
    const cancel = screen.getByTestId('pending-cancel')
    const sendNow = screen.getByTestId('pending-send-now')
    expect(cancel.className).toMatch(/btn-pill/)
    expect(sendNow.className).toMatch(/btn-pill/)
    // Cancel = ghost, Send-now = primary (kept from before)
    expect(cancel.className).toMatch(/btn-ghost/)
    expect(sendNow.className).toMatch(/btn-primary/)
  })

  it('renders the header as two stacked lines: title row + hint row', () => {
    const { container } = render(
      <InputBox
        onSend={vi.fn()}
        pendingMessage="queued"
        onSendPendingNow={vi.fn()}
        onCancelPending={vi.fn()}
      />,
    )
    const head = container.querySelector('.pending-float-head') as HTMLElement
    expect(head).toBeTruthy()
    // The title and the hint now live in two separate <span>s sharing the head row group.
    expect(head.querySelector('.pending-float-title')).toBeTruthy()
    expect(head.querySelector('.pending-float-hint')).toBeTruthy()
  })
})

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
    const onSend = vi.fn()
    const onStop = vi.fn()
    const user = userEvent.setup()

    render(<InputBox onSend={onSend} isStreaming onStop={onStop} />)

    expect(screen.queryByRole('button', { name: /Send/i })).not.toBeInTheDocument()
    const stop = screen.getByTestId('stop-generation')
    await user.click(stop)
    expect(onStop).toHaveBeenCalled()
    expect(onSend).not.toHaveBeenCalled()
  })

  it('does not send on Enter while streaming', async () => {
    const onSend = vi.fn()
    const user = userEvent.setup()

    render(<InputBox onSend={onSend} isStreaming />)

    const input = screen.getByPlaceholderText(/Type a message/i)
    await user.type(input, 'Hello{enter}')

    expect(onSend).not.toHaveBeenCalled()
  })
})

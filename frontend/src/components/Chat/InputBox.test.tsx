import { describe, it, expect, vi, beforeEach } from 'vitest'
import { useState } from 'react'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { InputBox, type LocalAttachment } from './InputBox'
import { uploadAttachment } from '../../api/attachments'
import type { SendAttachmentInput } from '../../types/chat'

vi.mock('../../api/attachments', () => ({
  // 上传管道 mock:由测试用例按需设定 resolve/reject
  uploadAttachment: vi.fn(),
  attachmentUrl: (id: string) => `/api/v1/attachments/${id}`,
}))

/** 持有 attachments 受控状态的测试壳:模拟 ChatWindow 的接法。 */
function Harness({ initial = [], onSend }: {
  initial?: LocalAttachment[]
  onSend?: (message: string, attachments?: SendAttachmentInput[]) => void
}) {
  const [atts, setAtts] = useState<LocalAttachment[]>(initial)
  return <InputBox onSend={onSend ?? vi.fn()} attachments={atts} onAttachmentsChange={setAtts} />
}

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

  it('does not render the attach entry when the attachments feature is not wired', () => {
    render(<InputBox onSend={vi.fn()} />)
    expect(screen.queryByRole('button', { name: '添加图片' })).not.toBeInTheDocument()
    expect(screen.queryByTestId('attach-input')).not.toBeInTheDocument()
  })
})

describe('InputBox attachments', () => {
  const png = (name = 'shot.png') => new File(['x'], name, { type: 'image/png' })
  const uploaded = { id: 'att-1', mime: 'image/png', size: 1, width: 10, height: 10, sha256: null }

  const localAtt = (over: Partial<LocalAttachment> = {}): LocalAttachment => ({
    localId: 'local-1',
    file: png(),
    status: 'ready',
    uploaded,
    previewUrl: '',
    ...over,
  })

  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(uploadAttachment).mockResolvedValue(uploaded)
  })

  it('opens the hidden file input from the attach button', async () => {
    const user = userEvent.setup()
    render(<InputBox onSend={vi.fn()} onAttachmentsChange={vi.fn()} />)
    const input = screen.getByTestId('attach-input') as HTMLInputElement
    const spy = vi.spyOn(input, 'click')
    await user.click(screen.getByRole('button', { name: '添加图片' }))
    expect(spy).toHaveBeenCalledTimes(1)
  })

  it('uploads chosen files and renders ready thumbnails in the strip', async () => {
    render(<Harness />)
    const input = screen.getByTestId('attach-input')
    fireEvent.change(input, { target: { files: [png()] } })
    await waitFor(() => {
      expect(uploadAttachment).toHaveBeenCalledTimes(1)
    })
    await waitFor(() => {
      expect(screen.getByTestId('attachments-strip').querySelector('[data-status="ready"]')).toBeTruthy()
    })
    expect(screen.getByRole('img', { name: /shot\.png/ })).toBeInTheDocument()
  })

  it('removes a thumbnail via the X button and calls onAttachmentsChange', async () => {
    const onAttachmentsChange = vi.fn()
    render(
      <InputBox
        onSend={vi.fn()}
        attachments={[localAtt()]}
        onAttachmentsChange={onAttachmentsChange}
      />,
    )
    fireEvent.click(screen.getByRole('button', { name: '移除 shot.png' }))
    expect(onAttachmentsChange).toHaveBeenCalledWith([])
  })

  it('sends ready attachment refs with the message and clears the strip', async () => {
    const onSend = vi.fn()
    const onAttachmentsChange = vi.fn()
    const user = userEvent.setup()
    render(
      <InputBox
        onSend={onSend}
        attachments={[localAtt({ uploaded: { ...uploaded, id: 'att-9' }, alt: '首页' })]}
        onAttachmentsChange={onAttachmentsChange}
      />,
    )
    await user.type(screen.getByPlaceholderText(/Type a message/i), '看图')
    await user.click(screen.getByRole('button', { name: 'Send' }))
    expect(onSend).toHaveBeenCalledWith('看图', [{ id: 'att-9', alt: '首页' }])
    expect(onAttachmentsChange).toHaveBeenLastCalledWith([])
  })

  it('keeps the single-argument onSend call when no ready attachments exist', async () => {
    const onSend = vi.fn()
    const user = userEvent.setup()
    render(<InputBox onSend={onSend} />)
    await user.type(screen.getByPlaceholderText(/Type a message/i), 'Hello world')
    await user.click(screen.getByRole('button', { name: /Send/i }))
    expect(onSend).toHaveBeenCalledWith('Hello world')
  })

  it('enables send with empty text when a ready attachment exists', async () => {
    const onSend = vi.fn()
    const user = userEvent.setup()
    render(
      <InputBox onSend={onSend} attachments={[localAtt()]} onAttachmentsChange={vi.fn()} />,
    )
    const send = screen.getByRole('button', { name: 'Send' })
    expect(send).toBeEnabled()
    await user.click(send)
    expect(onSend).toHaveBeenCalledWith('', [{ id: 'att-1' }])
  })

  it('disables send while an attachment is uploading', () => {
    render(
      <InputBox
        onSend={vi.fn()}
        attachments={[localAtt({ status: 'uploading', uploaded: undefined })]}
        onAttachmentsChange={vi.fn()}
      />,
    )
    expect(screen.getByRole('button', { name: 'Send' })).toBeDisabled()
    expect(screen.getByTestId('attachments-strip').querySelector('[data-status="uploading"]')).toBeTruthy()
    expect(screen.getByLabelText('上传中')).toBeInTheDocument()
  })

  it('offers retry on a failed attachment and re-runs the upload', async () => {
    vi.mocked(uploadAttachment).mockRejectedValueOnce(new Error('boom'))
    render(<Harness />)
    fireEvent.change(screen.getByTestId('attach-input'), { target: { files: [png()] } })
    await waitFor(() => {
      expect(screen.getByTestId('attachments-strip').querySelector('[data-status="failed"]')).toBeTruthy()
    })
    expect(screen.getByRole('button', { name: 'Send' })).toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: '上传失败，重试' }))
    await waitFor(() => {
      expect(screen.getByTestId('attachments-strip').querySelector('[data-status="ready"]')).toBeTruthy()
    })
    expect(uploadAttachment).toHaveBeenCalledTimes(2)
  })

  it('rejects additions beyond 4 with an inline hint and no upload', async () => {
    const onAttachmentsChange = vi.fn()
    const full = [1, 2, 3, 4].map(i => localAtt({ localId: `local-${i}`, file: png(`f${i}.png`) }))
    render(<InputBox onSend={vi.fn()} attachments={full} onAttachmentsChange={onAttachmentsChange} />)
    fireEvent.change(screen.getByTestId('attach-input'), { target: { files: [png('extra.png')] } })
    expect(screen.getByTestId('attachments-strip').children).toHaveLength(4)
    expect(await screen.findByText('最多 4 张')).toBeInTheDocument()
    expect(uploadAttachment).not.toHaveBeenCalled()
  })

  it('marks a non-image file failed with the unsupported-type hint', async () => {
    render(<Harness />)
    fireEvent.change(screen.getByTestId('attach-input'), {
      target: { files: [new File(['x'], 'doc.pdf', { type: 'application/pdf' })] },
    })
    expect(await screen.findByText('仅支持 PNG / JPEG / WebP / GIF')).toBeInTheDocument()
    await waitFor(() => {
      expect(screen.getByTestId('attachments-strip').querySelector('[data-status="failed"]')).toBeTruthy()
    })
    expect(uploadAttachment).not.toHaveBeenCalled()
  })

  it('marks an oversized file failed with the too-large hint', async () => {
    const big = new File(['x'], 'big.png', { type: 'image/png' })
    Object.defineProperty(big, 'size', { value: 11 * 1024 * 1024 })
    render(<Harness />)
    fireEvent.change(screen.getByTestId('attach-input'), { target: { files: [big] } })
    expect(await screen.findByText('图片超过 10MB')).toBeInTheDocument()
    expect(uploadAttachment).not.toHaveBeenCalled()
  })

  it('queues ready attachment refs while streaming', async () => {
    const onQueueSend = vi.fn()
    const user = userEvent.setup()
    render(
      <InputBox
        onSend={vi.fn()}
        isStreaming
        onQueueSend={onQueueSend}
        attachments={[localAtt({ uploaded: { ...uploaded, id: 'att-7' } })]}
        onAttachmentsChange={vi.fn()}
      />,
    )
    await user.type(screen.getByPlaceholderText(/Type a message/i), '排队')
    await user.click(screen.getByRole('button', { name: 'Send' }))
    expect(onQueueSend).toHaveBeenCalledWith('排队', [{ id: 'att-7' }])
  })

  it('shows the pending-image count badge on the queued message bar', () => {
    render(
      <InputBox
        onSend={vi.fn()}
        pendingMessage="queued"
        pendingAttachmentCount={2}
        onSendPendingNow={vi.fn()}
        onCancelPending={vi.fn()}
      />,
    )
    expect(screen.getByTestId('pending-attach-badge')).toHaveTextContent('+ 2 张图片')
  })

  it('hides the pending-image badge when the queued message has no attachments', () => {
    render(
      <InputBox
        onSend={vi.fn()}
        pendingMessage="queued"
        onSendPendingNow={vi.fn()}
        onCancelPending={vi.fn()}
      />,
    )
    expect(screen.queryByTestId('pending-attach-badge')).not.toBeInTheDocument()
  })
})

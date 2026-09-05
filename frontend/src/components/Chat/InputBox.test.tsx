import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { useState } from 'react'
import { act, render, screen, fireEvent, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { InputBox, type LocalAttachment } from './InputBox'
import { uploadAttachment, type UploadedAttachment } from '../../api/attachments'
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
        pendingActive
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
        pendingActive
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
        pendingActive
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
        pendingActive
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
        pendingActive
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
        pendingActive
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
        pendingActive
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
        pendingActive
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
        pendingActive
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
    // 测试环境默认 locale 为 en(LocaleContext DEFAULT_LOCALE,测试未包 Provider)
    expect(screen.queryByRole('button', { name: 'Add image' })).not.toBeInTheDocument()
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
    await user.click(screen.getByRole('button', { name: 'Add image' }))
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
    fireEvent.click(screen.getByRole('button', { name: 'Remove image' }))
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
    expect(onSend).toHaveBeenCalledWith(
      '看图',
      [{ id: 'att-9', mime: 'image/png', width: 10, height: 10, alt: '首页' }],
    )
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
    expect(onSend).toHaveBeenCalledWith('', [
      { id: 'att-1', mime: 'image/png', width: 10, height: 10 },
    ])
  })

  it('sends an image-only message via Enter with empty text', async () => {
    // 验收 §9 P0 边界的 Enter 路径:附件就绪 + 文字为空,Enter 同样发出 ('', refs)。
    const onSend = vi.fn()
    const user = userEvent.setup()
    render(
      <InputBox onSend={onSend} attachments={[localAtt()]} onAttachmentsChange={vi.fn()} />,
    )
    await user.type(screen.getByPlaceholderText(/Type a message/i), '{enter}')
    expect(onSend).toHaveBeenCalledWith('', [
      { id: 'att-1', mime: 'image/png', width: 10, height: 10 },
    ])
  })

  it('disables send when text and attachments are both empty', () => {
    // 验收 §9:文字与附件均为空 → 发送按钮禁用(canSendMessage('') 为 false)。
    render(<InputBox onSend={vi.fn()} onAttachmentsChange={vi.fn()} />)
    expect(screen.getByRole('button', { name: 'Send' })).toBeDisabled()
  })

  it('disables send for whitespace-only text with no attachments', async () => {
    const onSend = vi.fn()
    const user = userEvent.setup()
    render(<InputBox onSend={onSend} onAttachmentsChange={vi.fn()} />)
    expect(screen.getByRole('button', { name: 'Send' })).toBeDisabled()
    await user.type(screen.getByPlaceholderText(/Type a message/i), '   ')
    expect(screen.getByRole('button', { name: 'Send' })).toBeDisabled()
    expect(onSend).not.toHaveBeenCalled()
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
    expect(screen.getByLabelText('Uploading…')).toBeInTheDocument()
  })

  it('offers retry on a failed attachment and re-runs the upload', async () => {
    vi.mocked(uploadAttachment).mockRejectedValueOnce(new Error('boom'))
    render(<Harness />)
    fireEvent.change(screen.getByTestId('attach-input'), { target: { files: [png()] } })
    await waitFor(() => {
      expect(screen.getByTestId('attachments-strip').querySelector('[data-status="failed"]')).toBeTruthy()
    })
    expect(screen.getByRole('button', { name: 'Send' })).toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: 'Upload failed, click to retry' }))
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
    expect(await screen.findByText('Up to 4 images')).toBeInTheDocument()
    expect(uploadAttachment).not.toHaveBeenCalled()
  })

  it('marks a non-image file failed with the unsupported-type hint', async () => {
    render(<Harness />)
    fireEvent.change(screen.getByTestId('attach-input'), {
      target: { files: [new File(['x'], 'doc.pdf', { type: 'application/pdf' })] },
    })
    expect(await screen.findByText('Only PNG / JPEG / WebP / GIF supported')).toBeInTheDocument()
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
    expect(await screen.findByText('Image exceeds 10MB')).toBeInTheDocument()
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
    expect(onQueueSend).toHaveBeenCalledWith('排队', [
      { id: 'att-7', mime: 'image/png', width: 10, height: 10 },
    ])
  })

  it('shows the pending-image count badge on the queued message bar', () => {
    render(
      <InputBox
        onSend={vi.fn()}
        pendingActive
        pendingMessage="queued"
        pendingAttachmentCount={2}
        onSendPendingNow={vi.fn()}
        onCancelPending={vi.fn()}
      />,
    )
    expect(screen.getByTestId('pending-attach-badge')).toHaveTextContent('+ 2 image(s)')
  })

  it('hides the pending-image badge when the queued message has no attachments', () => {
    render(
      <InputBox
        onSend={vi.fn()}
        pendingActive
        pendingMessage="queued"
        onSendPendingNow={vi.fn()}
        onCancelPending={vi.fn()}
      />,
    )
    expect(screen.queryByTestId('pending-attach-badge')).not.toBeInTheDocument()
  })

  it('renders the float for an image-only queue with the badge as its text content', () => {
    // Finding 3 回归:纯图片排队时 pendingMessage 为 ''(假值),悬浮条改由
    // pendingActive 门控;无文本时 imagesCount 徽标即正文,用户才有排队反馈,
    // 且单条队列语义不变(发送按钮禁用)。
    const { container } = render(
      <InputBox
        onSend={vi.fn()}
        pendingActive
        pendingMessage=""
        pendingAttachmentCount={1}
        onSendPendingNow={vi.fn()}
        onCancelPending={vi.fn()}
      />,
    )
    expect(screen.getByTestId('pending-message')).toBeInTheDocument()
    expect(screen.getByTestId('pending-attach-badge')).toHaveTextContent('+ 1 image(s)')
    expect(container.querySelector('.pending-float-text')).toBeNull()
    expect(screen.getByRole('button', { name: 'Send' })).toBeDisabled()
  })

  it('does not render the pending float when no entry is queued', () => {
    render(
      <InputBox
        onSend={vi.fn()}
        pendingActive={false}
        pendingMessage={null}
        onSendPendingNow={vi.fn()}
        onCancelPending={vi.fn()}
      />,
    )
    expect(screen.queryByTestId('pending-message')).not.toBeInTheDocument()
  })

  it('keeps every batch-added attachment ready when uploads resolve individually (race regression)', async () => {
    // 多文件同批添加的竞态回归:管道曾用「读快照 → 整组写回」打补丁,多张上传时
    // 后一张会在 React 提交前一张 ready 之前读到过期列表,把前一张覆盖回
    // uploading(终态 [uploading, ready],第 1 张永久卡住并阻塞发送)。
    // 这里用受控 deferred 让两张的上传在同一个微任务窗口内先后 resolve
    // (React 不提交任何 ready 补丁),锁定旧实现的竞态窗口;修复后的管道走
    // 函数式更新,基于最新 prev 链式落地,任何交错下都全部 ready。
    const resolveUpload: Array<(v: UploadedAttachment) => void> = []
    vi.mocked(uploadAttachment)
      .mockImplementationOnce(
        () => new Promise<UploadedAttachment>(resolve => { resolveUpload.push(resolve) }),
      )
      .mockImplementationOnce(
        () => new Promise<UploadedAttachment>(resolve => { resolveUpload.push(resolve) }),
      )
    const onSend = vi.fn()
    const user = userEvent.setup()
    render(<Harness onSend={onSend} />)

    fireEvent.change(screen.getByTestId('attach-input'), {
      target: { files: [png('first.png'), png('second.png')] },
    })
    expect(screen.getByTestId('attachments-strip').children).toHaveLength(2)
    // 第 1 张上传已发起(此刻仅整批插入提交,无任何 ready 补丁)
    await waitFor(() => expect(uploadAttachment).toHaveBeenCalledTimes(1))

    // 同一 act 域内:第 1 张 resolve → ready 补丁入队、第 2 张上传发起(仅冲
    // 微任务)→ 第 2 张也 resolve。React 在 act 结束前不提交任何 ready。
    await act(async () => {
      resolveUpload[0]({ ...uploaded, id: 'att-first' })
      for (let i = 0; i < 20; i++) await Promise.resolve()
      expect(uploadAttachment).toHaveBeenCalledTimes(2)
      resolveUpload[1]({ ...uploaded, id: 'att-second' })
      for (let i = 0; i < 5; i++) await Promise.resolve()
    })

    // 两张都必须 ready:任何一张停在 uploading 都说明补丁被过期快照覆盖
    await waitFor(() => {
      const thumbs = [...screen.getByTestId('attachments-strip').children]
      expect(thumbs.map(t => t.getAttribute('data-status'))).toEqual(['ready', 'ready'])
    })

    // 发送不再被阻塞,且携带全部就绪引用(添加顺序)
    await user.type(screen.getByPlaceholderText(/Type a message/i), '看图')
    await user.click(screen.getByRole('button', { name: 'Send' }))
    expect(onSend).toHaveBeenCalledWith('看图', [
      { id: 'att-first', mime: 'image/png', width: 10, height: 10 },
      { id: 'att-second', mime: 'image/png', width: 10, height: 10 },
    ])
  })
})

describe('InputBox preview URL revocation', () => {
  // object URL 生命周期回归:previewUrlsRef 曾只读不写,createObjectURL 产生的
  // 预览地址全部泄漏。spy 两个静态方法(默认透传真实实现),断言移除 / 发送后
  // 清空 / 卸载三条路径都会 revoke(环境无 createObjectURL 时管道退回空串,
  // 不会走到这些断言的 blob: 前缀检查,用真实环境验证)。
  const png = (name: string) => new File(['x'], name, { type: 'image/png' })
  const uploaded = { id: 'att-1', mime: 'image/png', size: 1, width: 10, height: 10, sha256: null }

  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(uploadAttachment).mockResolvedValue(uploaded)
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('revokes the object URL when a thumbnail is removed', async () => {
    const createSpy = vi.spyOn(URL, 'createObjectURL')
    const revokeSpy = vi.spyOn(URL, 'revokeObjectURL')
    render(<Harness />)

    fireEvent.change(screen.getByTestId('attach-input'), { target: { files: [png('gone.png')] } })
    await waitFor(() => {
      expect(screen.getByTestId('attachments-strip').querySelector('[data-status="ready"]')).toBeTruthy()
    })
    const previewUrl = createSpy.mock.results[0]?.value as string
    expect(previewUrl).toMatch(/^blob:/)
    revokeSpy.mockClear()

    fireEvent.click(screen.getByRole('button', { name: 'Remove image' }))
    expect(revokeSpy).toHaveBeenCalledTimes(1)
    expect(revokeSpy).toHaveBeenCalledWith(previewUrl)
  })

  it('revokes the object URL when the strip is cleared after sending', async () => {
    const createSpy = vi.spyOn(URL, 'createObjectURL')
    const revokeSpy = vi.spyOn(URL, 'revokeObjectURL')
    const onSend = vi.fn()
    const user = userEvent.setup()
    render(<Harness onSend={onSend} />)

    fireEvent.change(screen.getByTestId('attach-input'), { target: { files: [png('sent.png')] } })
    await waitFor(() => {
      expect(screen.getByTestId('attachments-strip').querySelector('[data-status="ready"]')).toBeTruthy()
    })
    const previewUrl = createSpy.mock.results[0]?.value as string
    revokeSpy.mockClear()

    await user.type(screen.getByPlaceholderText(/Type a message/i), 'hi')
    await user.click(screen.getByRole('button', { name: 'Send' }))
    expect(onSend).toHaveBeenCalledWith('hi', [
      { id: 'att-1', mime: 'image/png', width: 10, height: 10 },
    ])
    // 发送后父级清空列表 → 兜底回收 effect revoke 剩余预览地址
    expect(revokeSpy).toHaveBeenCalledWith(previewUrl)
    expect(screen.queryByTestId('attachments-strip')).not.toBeInTheDocument()
  })

  it('revokes all object URLs on unmount', async () => {
    const createSpy = vi.spyOn(URL, 'createObjectURL')
    const revokeSpy = vi.spyOn(URL, 'revokeObjectURL')
    const { unmount } = render(<Harness />)

    fireEvent.change(screen.getByTestId('attach-input'), {
      target: { files: [png('a.png'), png('b.png')] },
    })
    // 预览 URL 在插入后的首次提交就随列表登记(与上传进度无关),等两次上传
    // 都已发起即可卸载,断言两个预览都被回收。
    await waitFor(() => {
      expect(uploadAttachment).toHaveBeenCalledTimes(2)
    })
    const urls = createSpy.mock.results.map(r => r.value as string)
    expect(urls).toHaveLength(2)
    revokeSpy.mockClear()

    unmount()
    expect(revokeSpy).toHaveBeenCalledWith(urls[0])
    expect(revokeSpy).toHaveBeenCalledWith(urls[1])
  })
})

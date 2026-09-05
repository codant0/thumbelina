import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { AttachmentLightbox } from './AttachmentLightbox'

const attachments = [
  { id: 'att-1', alt: '首页截图' },
  { id: 'att-2' },
  { id: 'att-3', alt: '第三张' },
]

describe('AttachmentLightbox', () => {
  it('renders the current image from attachmentUrl(id) with alt', () => {
    render(<AttachmentLightbox attachments={attachments} index={0} onClose={vi.fn()} onIndexChange={vi.fn()} />)
    const img = screen.getByRole('img')
    expect(img.getAttribute('src')).toBe('/api/v1/attachments/att-1')
    expect(img.getAttribute('alt')).toBe('首页截图')
    expect(screen.getByText('1 / 3')).toBeInTheDocument()
  })

  it('closes on the close button and on Escape', async () => {
    const onClose = vi.fn()
    render(<AttachmentLightbox attachments={attachments} index={0} onClose={onClose} onIndexChange={vi.fn()} />)
    fireEvent.click(screen.getByRole('button', { name: 'Close' }))
    expect(onClose).toHaveBeenCalledTimes(1)
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(onClose).toHaveBeenCalledTimes(2)
  })

  it('navigates with arrow keys and prev/next buttons (wrapping)', () => {
    const onIndexChange = vi.fn()
    render(<AttachmentLightbox attachments={attachments} index={0} onClose={vi.fn()} onIndexChange={onIndexChange} />)
    fireEvent.keyDown(document, { key: 'ArrowRight' })
    expect(onIndexChange).toHaveBeenLastCalledWith(1)
    fireEvent.keyDown(document, { key: 'ArrowLeft' })
    expect(onIndexChange).toHaveBeenLastCalledWith(2) // 从 0 左移回绕到 2
    fireEvent.click(screen.getByRole('button', { name: 'Next image' }))
    expect(onIndexChange).toHaveBeenLastCalledWith(1)
    fireEvent.click(screen.getByRole('button', { name: 'Previous image' }))
    expect(onIndexChange).toHaveBeenLastCalledWith(2)
  })

  it('hides prev/next and counter for a single image', () => {
    const onIndexChange = vi.fn()
    render(<AttachmentLightbox attachments={[attachments[0]]} index={0} onClose={vi.fn()} onIndexChange={onIndexChange} />)
    expect(screen.queryByRole('button', { name: 'Previous image' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Next image' })).not.toBeInTheDocument()
    expect(screen.queryByText(/\/ 1/)).not.toBeInTheDocument()
    fireEvent.keyDown(document, { key: 'ArrowRight' })
    fireEvent.keyDown(document, { key: 'ArrowLeft' })
    expect(onIndexChange).not.toHaveBeenCalled() // 单图时方向键不触发切换
  })
})

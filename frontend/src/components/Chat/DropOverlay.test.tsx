import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent, cleanup } from '@testing-library/react'
import { DropOverlay } from './DropOverlay'

// 拖放事件挂在 document 上(文档级监听),fireEvent 的 dataTransfer 通过 init 注入。
const dragEnter = (types: string[]) =>
  fireEvent.dragEnter(document, { dataTransfer: { types, files: [] } })
const dragOver = () => fireEvent.dragOver(document, { dataTransfer: { types: ['Files'], files: [] } })
const dragLeave = () => fireEvent.dragLeave(document, { dataTransfer: { types: ['Files'], files: [] } })

describe('DropOverlay', () => {
  it('does not render the overlay when nothing is dragged', () => {
    render(<DropOverlay onFiles={vi.fn()} />)
    expect(screen.queryByTestId('drop-overlay')).not.toBeInTheDocument()
  })

  it('shows the overlay for file drags and hides it after leave', () => {
    render(<DropOverlay onFiles={vi.fn()} />)
    dragEnter(['Files'])
    expect(screen.getByTestId('drop-overlay')).toBeInTheDocument()
    expect(screen.getByText('松开以上传图片')).toBeInTheDocument()
    dragLeave()
    expect(screen.queryByTestId('drop-overlay')).not.toBeInTheDocument()
  })

  it('prevents default on dragover so the browser allows drop', () => {
    render(<DropOverlay onFiles={vi.fn()} />)
    dragEnter(['Files'])
    // fireEvent 返回「默认行为未被阻止」;preventDefault 后为 false
    expect(dragOver()).toBe(false)
  })

  it('ignores drags without Files type (coder page code-drag must not trigger)', () => {
    render(<DropOverlay onFiles={vi.fn()} />)
    dragEnter(['text/plain'])
    dragEnter(['text/html'])
    expect(screen.queryByTestId('drop-overlay')).not.toBeInTheDocument()
  })

  it('counts nested dragenter/dragleave pairs before hiding', () => {
    render(<DropOverlay onFiles={vi.fn()} />)
    dragEnter(['Files'])
    dragEnter(['Files']) // 进入子元素 → 成对 enter/leave
    dragLeave()
    expect(screen.getByTestId('drop-overlay')).toBeInTheDocument()
    dragLeave()
    expect(screen.queryByTestId('drop-overlay')).not.toBeInTheDocument()
  })

  it('drops image files only and calls onFiles with them', () => {
    const onFiles = vi.fn()
    render(<DropOverlay onFiles={onFiles} />)
    dragEnter(['Files'])
    const png = new File(['x'], 'a.png', { type: 'image/png' })
    const txt = new File(['y'], 'b.txt', { type: 'text/plain' })
    fireEvent.drop(document, { dataTransfer: { types: ['Files'], files: [png, txt] } })
    expect(onFiles).toHaveBeenCalledTimes(1)
    expect(onFiles).toHaveBeenCalledWith([png])
    expect(screen.queryByTestId('drop-overlay')).not.toBeInTheDocument()
  })

  it('unsubscribes document listeners on unmount', () => {
    const onFiles = vi.fn()
    const { unmount } = render(<DropOverlay onFiles={onFiles} />)
    unmount()
    dragEnter(['Files'])
    fireEvent.drop(document, { dataTransfer: { types: ['Files'], files: [new File(['x'], 'a.png', { type: 'image/png' })] } })
    expect(onFiles).not.toHaveBeenCalled()
    expect(screen.queryByTestId('drop-overlay')).not.toBeInTheDocument()
    cleanup()
  })
})

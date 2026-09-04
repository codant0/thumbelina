import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import { Minus, X } from 'lucide-react'
import { useTranslation } from '../../i18n'

export interface FloatWindowPosition {
  x: number
  y: number
  width: number
  height: number
}

interface FloatWindowProps {
  /** 唯一 id,用于 z-index 栈管理;多个窗口同时存在时点击会置顶。 */
  windowId: string
  title: string
  /** 可选的副标题/状态徽章,渲染在标题下方。 */
  subtitle?: ReactNode
  /** 初始位置和尺寸;未提供时使用默认值。 */
  initial?: Partial<FloatWindowPosition>
  /** 最小尺寸约束。 */
  minWidth?: number
  minHeight?: number
  /** 关闭回调(用户点 X 或 Esc)。 */
  onClose: () => void
  /** 最小化回调(用户点击 _ 按钮)。 */
  onMinimize?: () => void
  /** 标题栏右侧的自定义操作按钮。 */
  headerActions?: ReactNode
  /** z-index 调度器:通知父组件哪个窗口应该置顶。 */
  onFocus?: (windowId: string) => void
  /** 当前 z-index 值,由父组件计算后传入。 */
  zIndex: number
  /** 是否最小化(只显示标题栏)。 */
  minimized?: boolean
  children: ReactNode
}

const DEFAULT_WIDTH = 560
const DEFAULT_HEIGHT = 480
const DEFAULT_X = 80
const DEFAULT_Y = 80
const MIN_WIDTH = 320
const MIN_HEIGHT = 220

/** 独立浮动窗口组件。
 *
 * 设计目标:
 * - 不受父容器尺寸约束,完全浮在视口上;
 * - 标题栏可拖动移动;
 * - 右下角 + 右/下/左/下八个方向可调整大小;
 * - Esc 关闭、最小化、可同时打开多个;
 * - z-index 由父组件集中调度(避免互相遮挡)。
 */
export function FloatWindow({
  windowId,
  title,
  subtitle,
  initial,
  minWidth = MIN_WIDTH,
  minHeight = MIN_HEIGHT,
  onClose,
  onMinimize,
  headerActions,
  onFocus,
  zIndex,
  minimized = false,
  children,
}: FloatWindowProps) {
  const { t } = useTranslation()
  const panelRef = useRef<HTMLDivElement>(null)
  const [pos, setPos] = useState<{ x: number; y: number }>(() => ({
    x: initial?.x ?? DEFAULT_X,
    y: initial?.y ?? DEFAULT_Y,
  }))
  const [size, setSize] = useState<{ width: number; height: number }>(() => ({
    width: initial?.width ?? DEFAULT_WIDTH,
    height: initial?.height ?? DEFAULT_HEIGHT,
  }))

  // Esc 关闭交给窗口本身处理(每个窗口独立监听)。
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  // 视口尺寸变化时,把窗口钳制在可见范围内。
  useEffect(() => {
    const onResize = () => {
      setPos(p => clampToViewport(p.x, p.y, size.width, size.height))
      setSize(s => clampSize(s.width, s.height, minWidth, minHeight))
    }
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [size.width, size.height, minWidth, minHeight])

  // ---- 拖动 ----------------------------------------------------------
  const dragStateRef = useRef<{
    startX: number
    startY: number
    origX: number
    origY: number
    pointerId: number
  } | null>(null)

  const handleDragStart = useCallback(
    (e: React.PointerEvent<HTMLDivElement>) => {
      // 排除在关闭/最小化/自定义按钮上的点击
      const target = e.target as HTMLElement
      if (target.closest('button')) return
      e.preventDefault()
      onFocus?.(windowId)
      dragStateRef.current = {
        startX: e.clientX,
        startY: e.clientY,
        origX: pos.x,
        origY: pos.y,
        pointerId: e.pointerId,
      }
      ;(e.currentTarget as HTMLElement).setPointerCapture(e.pointerId)
    },
    [pos.x, pos.y, onFocus, windowId],
  )

  const handleDragMove = useCallback((e: React.PointerEvent<HTMLDivElement>) => {
    const ds = dragStateRef.current
    if (!ds || ds.pointerId !== e.pointerId) return
    const dx = e.clientX - ds.startX
    const dy = e.clientY - ds.startY
    setPos(() => clampToViewport(ds.origX + dx, ds.origY + dy, size.width, size.height))
  }, [size.width, size.height])

  const handleDragEnd = useCallback((e: React.PointerEvent<HTMLDivElement>) => {
    if (dragStateRef.current?.pointerId === e.pointerId) {
      ;(e.currentTarget as HTMLElement).releasePointerCapture(e.pointerId)
      dragStateRef.current = null
    }
  }, [])

  // ---- Resize -------------------------------------------------------
  type ResizeEdge = 'n' | 's' | 'e' | 'w' | 'ne' | 'nw' | 'se' | 'sw'
  const resizeStateRef = useRef<{
    edge: ResizeEdge
    startX: number
    startY: number
    origX: number
    origY: number
    origW: number
    origH: number
    pointerId: number
  } | null>(null)

  const handleResizeStart = useCallback(
    (edge: ResizeEdge) => (e: React.PointerEvent<HTMLDivElement>) => {
      e.preventDefault()
      e.stopPropagation()
      onFocus?.(windowId)
      resizeStateRef.current = {
        edge,
        startX: e.clientX,
        startY: e.clientY,
        origX: pos.x,
        origY: pos.y,
        origW: size.width,
        origH: size.height,
        pointerId: e.pointerId,
      }
      ;(e.currentTarget as HTMLElement).setPointerCapture(e.pointerId)
    },
    [pos.x, pos.y, size.width, size.height, onFocus, windowId],
  )

  const handleResizeMove = useCallback((e: React.PointerEvent<HTMLDivElement>) => {
    const rs = resizeStateRef.current
    if (!rs || rs.pointerId !== e.pointerId) return
    const dx = e.clientX - rs.startX
    const dy = e.clientY - rs.startY
    const { origX, origY, origW, origH } = rs
    let newX = origX
    let newY = origY
    let newW = origW
    let newH = origH
    if (rs.edge.includes('e')) newW = Math.max(minWidth, origW + dx)
    if (rs.edge.includes('s')) newH = Math.max(minHeight, origH + dy)
    if (rs.edge.includes('w')) {
      newW = Math.max(minWidth, origW - dx)
      newX = origX + (origW - newW)
    }
    if (rs.edge.includes('n')) {
      newH = Math.max(minHeight, origH - dy)
      newY = origY + (origH - newH)
    }
    setPos({ x: newX, y: newY })
    setSize({ width: newW, height: newH })
  }, [minWidth, minHeight])

  const handleResizeEnd = useCallback((e: React.PointerEvent<HTMLDivElement>) => {
    if (resizeStateRef.current?.pointerId === e.pointerId) {
      ;(e.currentTarget as HTMLElement).releasePointerCapture(e.pointerId)
      resizeStateRef.current = null
    }
  }, [])

  return (
    <div
      ref={panelRef}
      className={`float-window${minimized ? ' float-window--minimized' : ''}`}
      style={{
        left: `${pos.x}px`,
        top: `${pos.y}px`,
        width: `${size.width}px`,
        height: minimized ? undefined : `${size.height}px`,
        zIndex,
      }}
      role="dialog"
      aria-modal="false"
      aria-label={title}
      data-testid="float-window"
      data-window-id={windowId}
      onMouseDown={() => onFocus?.(windowId)}
    >
      <div
        className="float-window__header"
        onPointerDown={handleDragStart}
        onPointerMove={handleDragMove}
        onPointerUp={handleDragEnd}
        onPointerCancel={handleDragEnd}
        data-testid="float-window-header"
      >
        <div className="float-window__title-wrap">
          <span className="float-window__title">{title}</span>
          {subtitle && <div className="float-window__subtitle">{subtitle}</div>}
        </div>
        <div className="float-window__actions">
          {headerActions}
          {onMinimize && (
            <button
              type="button"
              className="float-window__btn"
              onClick={onMinimize}
              aria-label={t('common.minimize')}
              data-testid="float-window-minimize"
            >
              <Minus size={14} />
            </button>
          )}
          <button
            type="button"
            className="float-window__btn float-window__btn--close"
            onClick={onClose}
            aria-label={t('common.close')}
            data-testid="float-window-close"
          >
            <X size={14} />
          </button>
        </div>
      </div>
      {!minimized && (
        <div className="float-window__body" data-testid="float-window-body">
          {children}
        </div>
      )}
      {!minimized && (
        <>
          {/* 八向 resize handle */}
          {(['n', 's', 'e', 'w', 'ne', 'nw', 'se', 'sw'] as ResizeEdge[]).map(edge => (
            <div
              key={edge}
              className={`float-window__resize float-window__resize--${edge}`}
              onPointerDown={handleResizeStart(edge)}
              onPointerMove={handleResizeMove}
              onPointerUp={handleResizeEnd}
              onPointerCancel={handleResizeEnd}
              data-testid={`float-window-resize-${edge}`}
              aria-hidden="true"
            />
          ))}
        </>
      )}
    </div>
  )
}

function clampToViewport(
  x: number,
  y: number,
  w: number,
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  _h: number,
): { x: number; y: number } {
  const maxX = Math.max(0, window.innerWidth - Math.min(w, 80))
  const maxY = Math.max(0, window.innerHeight - 40) // 至少保留 40px 标题栏可见
  return {
    x: Math.min(Math.max(0, x), maxX),
    y: Math.min(Math.max(0, y), maxY),
  }
}

function clampSize(w: number, h: number, minW: number, minH: number): { width: number; height: number } {
  return {
    width: Math.max(minW, Math.min(w, window.innerWidth - 40)),
    height: Math.max(minH, Math.min(h, window.innerHeight - 40)),
  }
}
import { useState, useCallback, useRef, useEffect } from 'react'

interface UsePanelResizeOptions {
  /** Default width in pixels */
  defaultWidth: number
  /** Minimum width in pixels */
  minWidth?: number
  /** Maximum width in pixels */
  maxWidth?: number
  /** Resize direction: 'right' means handle is on the right edge, 'left' means on the left edge */
  direction?: 'right' | 'left'
}

interface UsePanelResizeReturn {
  /** Current panel width */
  width: number
  /** Props to spread on the resize handle element */
  handleProps: {
    onMouseDown: (e: React.MouseEvent) => void
    className: string
    title: string
  }
}

/**
 * Hook that provides drag-to-resize for a panel.
 * Returns state for the current width and props for a resize handle element.
 */
export function usePanelResize({
  defaultWidth,
  minWidth = 150,
  maxWidth = 600,
  direction = 'right',
}: UsePanelResizeOptions): UsePanelResizeReturn {
  const [width, setWidth] = useState(defaultWidth)
  const dragRef = useRef<{ startX: number; startWidth: number } | null>(null)

  const onMouseDown = useCallback(
    (e: React.MouseEvent) => {
      e.preventDefault()
      e.stopPropagation()
      dragRef.current = { startX: e.clientX, startWidth: width }

      const onMouseMove = (moveEvent: MouseEvent) => {
        if (!dragRef.current) return
        const delta =
          direction === 'right'
            ? moveEvent.clientX - dragRef.current.startX
            : dragRef.current.startX - moveEvent.clientX
        const newWidth = Math.min(maxWidth, Math.max(minWidth, dragRef.current.startWidth + delta))
        setWidth(newWidth)
      }

      const onMouseUp = () => {
        dragRef.current = null
        document.removeEventListener('mousemove', onMouseMove)
        document.removeEventListener('mouseup', onMouseUp)
        document.body.style.cursor = ''
        document.body.style.userSelect = ''
      }

      document.addEventListener('mousemove', onMouseMove)
      document.addEventListener('mouseup', onMouseUp)
      document.body.style.cursor = 'col-resize'
      document.body.style.userSelect = 'none'
    },
    [width, direction, minWidth, maxWidth],
  )

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      document.body.style.cursor = ''
      document.body.style.userSelect = ''
    }
  }, [])

  const handleClassName =
    direction === 'right'
      ? 'absolute right-0 top-0 bottom-0 w-1.5 cursor-col-resize hover:bg-primary/40 active:bg-primary/60 z-20'
      : 'absolute left-0 top-0 bottom-0 w-1.5 cursor-col-resize hover:bg-primary/40 active:bg-primary/60 z-20'

  return {
    width,
    handleProps: {
      onMouseDown,
      className: handleClassName,
      title: 'Drag to resize',
    },
  }
}

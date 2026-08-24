/**
 * useColumnResize - Hook for resizing matrix column widths
 * Supports drag-to-resize column headers and persists widths
 */

import { useState, useCallback, useRef, useEffect } from 'react'

export interface ColumnWidths {
  [columnKey: string]: number
}

export interface RowHeights {
  [rowKey: string]: number
}

interface UseColumnResizeOptions {
  initialWidths: ColumnWidths
  minWidth?: number
  maxWidth?: number
  onWidthsChange?: (widths: ColumnWidths) => void
}

interface ResizeState {
  columnKey: string
  startX: number
  startWidth: number
}

export function useColumnResize({
  initialWidths,
  minWidth = 40,
  maxWidth = 500,
  onWidthsChange,
}: UseColumnResizeOptions) {
  const [widths, setWidths] = useState<ColumnWidths>(initialWidths)
  const resizeRef = useRef<ResizeState | null>(null)
  const widthsRef = useRef<ColumnWidths>(widths)

  // Keep widthsRef in sync
  useEffect(() => { widthsRef.current = widths }, [widths])

  // Update widths when initialWidths change
  useEffect(() => {
    setWidths(initialWidths)
  }, [initialWidths])

  const getWidth = useCallback(
    (columnKey: string, defaultWidth: number = 100): number => {
      return widths[columnKey] ?? defaultWidth
    },
    [widths]
  )

  const handleResizeStart = useCallback(
    (columnKey: string, e: React.MouseEvent) => {
      e.preventDefault()
      e.stopPropagation()

      const startWidth = widthsRef.current[columnKey] ?? 100

      resizeRef.current = {
        columnKey,
        startX: e.clientX,
        startWidth,
      }

      const handleMouseMove = (moveEvent: MouseEvent) => {
        if (!resizeRef.current) return

        const deltaX = moveEvent.clientX - resizeRef.current.startX
        const newWidth = Math.max(minWidth, Math.min(maxWidth, resizeRef.current.startWidth + deltaX))

        setWidths((prev) => {
          const next = { ...prev, [resizeRef.current!.columnKey]: newWidth }
          widthsRef.current = next
          return next
        })
      }

      const handleMouseUp = () => {
        document.removeEventListener('mousemove', handleMouseMove)
        document.removeEventListener('mouseup', handleMouseUp)
        if (resizeRef.current) {
          const key = resizeRef.current.columnKey
          resizeRef.current = null
          onWidthsChange?.({ ...widthsRef.current })
        } else {
          resizeRef.current = null
        }
      }

      document.addEventListener('mousemove', handleMouseMove)
      document.addEventListener('mouseup', handleMouseUp)
    },
    [minWidth, maxWidth, onWidthsChange]
  )

  const resetWidth = useCallback(
    (columnKey: string) => {
      setWidths((prev) => {
        const next = { ...prev }
        delete next[columnKey]
        widthsRef.current = next
        return next
      })
      onWidthsChange?.({ ...widthsRef.current })
    },
    [onWidthsChange]
  )

  const resetAllWidths = useCallback(() => {
    setWidths({})
    widthsRef.current = {}
    onWidthsChange?.({})
  }, [onWidthsChange])

  return {
    widths,
    getWidth,
    handleResizeStart,
    resetWidth,
    resetAllWidths,
    isResizing: resizeRef.current !== null,
  }
}

// --- Row resize hook ---

interface UseRowResizeOptions {
  initialHeights: RowHeights
  minHeight?: number
  maxHeight?: number
  onHeightsChange?: (heights: RowHeights) => void
}

interface RowResizeState {
  rowKey: string
  startY: number
  startHeight: number
}

export function useRowResize({
  initialHeights,
  minHeight = 20,
  maxHeight = 300,
  onHeightsChange,
}: UseRowResizeOptions) {
  const [heights, setHeights] = useState<RowHeights>(initialHeights)
  const resizeRef = useRef<RowResizeState | null>(null)
  const heightsRef = useRef<RowHeights>(heights)

  useEffect(() => { heightsRef.current = heights }, [heights])
  useEffect(() => { setHeights(initialHeights) }, [initialHeights])

  const getHeight = useCallback(
    (rowKey: string, defaultHeight: number = 28): number => {
      return heights[rowKey] ?? defaultHeight
    },
    [heights]
  )

  const handleResizeStart = useCallback(
    (rowKey: string, e: React.MouseEvent) => {
      e.preventDefault()
      e.stopPropagation()

      const startHeight = heightsRef.current[rowKey] ?? 28

      resizeRef.current = {
        rowKey,
        startY: e.clientY,
        startHeight,
      }

      const handleMouseMove = (moveEvent: MouseEvent) => {
        if (!resizeRef.current) return
        const deltaY = moveEvent.clientY - resizeRef.current.startY
        const newHeight = Math.max(minHeight, Math.min(maxHeight, resizeRef.current.startHeight + deltaY))
        setHeights((prev) => {
          const next = { ...prev, [resizeRef.current!.rowKey]: newHeight }
          heightsRef.current = next
          return next
        })
      }

      const handleMouseUp = () => {
        document.removeEventListener('mousemove', handleMouseMove)
        document.removeEventListener('mouseup', handleMouseUp)
        if (resizeRef.current) {
          resizeRef.current = null
          onHeightsChange?.({ ...heightsRef.current })
        }
      }

      document.addEventListener('mousemove', handleMouseMove)
      document.addEventListener('mouseup', handleMouseUp)
    },
    [minHeight, maxHeight, onHeightsChange]
  )

  return { heights, getHeight, handleResizeStart }
}

/**
 * ResizeHandle component for column headers
 */
interface ResizeHandleProps {
  columnKey: string
  onResizeStart: (columnKey: string, e: React.MouseEvent) => void
}

export function ResizeHandle({ columnKey, onResizeStart }: ResizeHandleProps) {
  return (
    <div
      className="absolute right-0 top-0 bottom-0 w-1 cursor-col-resize hover:bg-primary/50 z-10"
      onMouseDown={(e) => onResizeStart(columnKey, e)}
      data-testid={`resize-handle-${columnKey}`}
    />
  )
}

/**
 * RowResizeHandle component for row borders
 */
interface RowResizeHandleProps {
  rowKey: string
  onResizeStart: (rowKey: string, e: React.MouseEvent) => void
}

export function RowResizeHandle({ rowKey, onResizeStart }: RowResizeHandleProps) {
  return (
    <div
      className="absolute left-0 right-0 bottom-0 h-1 cursor-row-resize hover:bg-primary/50 z-10"
      onMouseDown={(e) => onResizeStart(rowKey, e)}
      data-testid={`row-resize-handle-${rowKey}`}
    />
  )
}

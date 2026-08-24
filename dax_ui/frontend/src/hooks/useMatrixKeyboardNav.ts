/**
 * useMatrixKeyboardNav - Hook for arrow key navigation in matrix visuals
 * Handles Up/Down/Left/Right arrow keys to move selection between cells
 */

import { useCallback, useEffect } from 'react'

export interface MatrixSelection {
  rowIndex: number
  colIndex: number
}

interface UseMatrixKeyboardNavOptions {
  enabled: boolean
  rowCount: number
  colCount: number
  selection: MatrixSelection | null
  onSelectionChange: (selection: MatrixSelection) => void
  onEscape?: () => void
  containerRef: React.RefObject<HTMLElement>
}

export function useMatrixKeyboardNav({
  enabled,
  rowCount,
  colCount,
  selection,
  onSelectionChange,
  onEscape,
  containerRef,
}: UseMatrixKeyboardNavOptions) {
  const handleKeyDown = useCallback(
    (e: KeyboardEvent) => {
      if (!enabled || !selection) return

      // Only handle if container or its children have focus
      const container = containerRef.current
      if (!container) return
      if (!container.contains(document.activeElement) && document.activeElement !== container) {
        return
      }

      const { rowIndex, colIndex } = selection

      switch (e.key) {
        case 'ArrowUp':
          e.preventDefault()
          if (rowIndex > 0) {
            onSelectionChange({ rowIndex: rowIndex - 1, colIndex })
          }
          break

        case 'ArrowDown':
          e.preventDefault()
          if (rowIndex < rowCount - 1) {
            onSelectionChange({ rowIndex: rowIndex + 1, colIndex })
          }
          break

        case 'ArrowLeft':
          e.preventDefault()
          if (colIndex > 0) {
            onSelectionChange({ rowIndex, colIndex: colIndex - 1 })
          }
          break

        case 'ArrowRight':
          e.preventDefault()
          if (colIndex < colCount - 1) {
            onSelectionChange({ rowIndex, colIndex: colIndex + 1 })
          }
          break

        case 'Home':
          e.preventDefault()
          if (e.ctrlKey) {
            // Ctrl+Home = go to top-left
            onSelectionChange({ rowIndex: 0, colIndex: 0 })
          } else {
            // Home = go to start of row
            onSelectionChange({ rowIndex, colIndex: 0 })
          }
          break

        case 'End':
          e.preventDefault()
          if (e.ctrlKey) {
            // Ctrl+End = go to bottom-right
            onSelectionChange({ rowIndex: rowCount - 1, colIndex: colCount - 1 })
          } else {
            // End = go to end of row
            onSelectionChange({ rowIndex, colIndex: colCount - 1 })
          }
          break

        case 'PageUp':
          e.preventDefault()
          // Move up by 10 rows (or to top)
          onSelectionChange({ rowIndex: Math.max(0, rowIndex - 10), colIndex })
          break

        case 'PageDown':
          e.preventDefault()
          // Move down by 10 rows (or to bottom)
          onSelectionChange({ rowIndex: Math.min(rowCount - 1, rowIndex + 10), colIndex })
          break

        case 'Escape':
          if (onEscape) {
            e.preventDefault()
            onEscape()
          }
          break

        default:
          // Don't prevent default for other keys
          break
      }
    },
    [enabled, selection, rowCount, colCount, onSelectionChange, onEscape, containerRef]
  )

  useEffect(() => {
    if (!enabled) return

    document.addEventListener('keydown', handleKeyDown)
    return () => {
      document.removeEventListener('keydown', handleKeyDown)
    }
  }, [enabled, handleKeyDown])

  return {
    // Utility to scroll selected cell into view
    scrollToSelection: useCallback(
      (sel: MatrixSelection) => {
        const container = containerRef.current
        if (!container) return

        const cell = container.querySelector(
          `[data-row="${sel.rowIndex}"][data-col="${sel.colIndex}"]`
        ) as HTMLElement
        if (cell) {
          cell.scrollIntoView({ block: 'nearest', inline: 'nearest' })
        }
      },
      [containerRef]
    ),
  }
}

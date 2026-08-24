/**
 * MatrixContextMenu - Right-click context menu for matrix drill operations
 * Supports drill down/up, expand to next level, etc.
 */

import { useEffect, useRef, useCallback } from 'react'
import { ChevronDown, ChevronUp, ChevronRight, Expand, Shrink, Download, Trash2, Pencil } from 'lucide-react'

export interface MatrixCellInfo {
  axis: 'rows' | 'cols'
  level: number
  key: string
  value: string
  rowPath?: string[]
  colPath?: string[]
}

interface MatrixContextMenuProps {
  visualId: string
  cellInfo: MatrixCellInfo | null
  position: { x: number; y: number } | null
  onClose: () => void
  onAction: (action: string, cellInfo: MatrixCellInfo) => void
  maxRowLevel: number
  maxColLevel: number
  currentRowLevel: number
  currentColLevel: number
}

export function MatrixContextMenu({
  visualId: _visualId,
  cellInfo,
  position,
  onClose,
  onAction,
  maxRowLevel,
  maxColLevel,
  currentRowLevel,
  currentColLevel,
}: MatrixContextMenuProps) {
  const menuRef = useRef<HTMLDivElement>(null)

  // Close on outside click
  useEffect(() => {
    if (!position) return

    const handleClick = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        onClose()
      }
    }

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onClose()
      }
    }

    // Delay to avoid closing immediately on right-click
    const timer = setTimeout(() => {
      document.addEventListener('mousedown', handleClick, true)
      document.addEventListener('contextmenu', handleClick, true)
      document.addEventListener('keydown', handleKeyDown)
    }, 0)

    return () => {
      clearTimeout(timer)
      document.removeEventListener('mousedown', handleClick, true)
      document.removeEventListener('contextmenu', handleClick, true)
      document.removeEventListener('keydown', handleKeyDown)
    }
  }, [position, onClose])

  const handleAction = useCallback(
    (action: string) => {
      if (cellInfo) {
        onAction(action, cellInfo)
      }
      onClose()
    },
    [cellInfo, onAction, onClose]
  )

  if (!position || !cellInfo) return null

  const canDrillDownRows = currentRowLevel < maxRowLevel
  const canDrillUpRows = currentRowLevel > 0
  const canDrillDownCols = currentColLevel < maxColLevel
  const canDrillUpCols = currentColLevel > 0

  return (
    <div
      ref={menuRef}
      className="fixed z-50 min-w-[180px] rounded-md border bg-popover p-1 text-popover-foreground shadow-md"
      style={{
        left: position.x,
        top: position.y,
      }}
      data-testid="matrix-context-menu"
    >
      {/* Row drill options */}
      {maxRowLevel > 0 && (
        <>
          <div className="px-2 py-1 text-[10px] font-semibold text-muted-foreground uppercase">
            Rows
          </div>
          <button
            className="relative flex w-full cursor-pointer select-none items-center rounded-sm px-2 py-1.5 text-xs outline-none hover:bg-accent disabled:opacity-50 disabled:pointer-events-none"
            disabled={!canDrillDownRows}
            onClick={() => handleAction('drill-down-rows')}
            data-testid="menu-drill-down-rows"
          >
            <ChevronDown className="mr-2 h-3 w-3" />
            Drill Down
          </button>
          <button
            className="relative flex w-full cursor-pointer select-none items-center rounded-sm px-2 py-1.5 text-xs outline-none hover:bg-accent disabled:opacity-50 disabled:pointer-events-none"
            disabled={!canDrillUpRows}
            onClick={() => handleAction('drill-up-rows')}
            data-testid="menu-drill-up-rows"
          >
            <ChevronUp className="mr-2 h-3 w-3" />
            Drill Up
          </button>
          <button
            className="relative flex w-full cursor-pointer select-none items-center rounded-sm px-2 py-1.5 text-xs outline-none hover:bg-accent disabled:opacity-50 disabled:pointer-events-none"
            disabled={!canDrillDownRows}
            onClick={() => handleAction('go-to-next-level-rows')}
            data-testid="menu-next-level-rows"
          >
            <ChevronRight className="mr-2 h-3 w-3" />
            Go to Next Level
          </button>
          <button
            className="relative flex w-full cursor-pointer select-none items-center rounded-sm px-2 py-1.5 text-xs outline-none hover:bg-accent disabled:opacity-50 disabled:pointer-events-none"
            disabled={!canDrillDownRows}
            onClick={() => handleAction('expand-to-next-level-rows')}
            data-testid="menu-expand-rows"
          >
            <Expand className="mr-2 h-3 w-3" />
            Expand to Next Level
          </button>
        </>
      )}

      {/* Column drill options */}
      {maxColLevel > 0 && (
        <>
          {maxRowLevel > 0 && <div className="my-1 h-px bg-border" />}
          <div className="px-2 py-1 text-[10px] font-semibold text-muted-foreground uppercase">
            Columns
          </div>
          <button
            className="relative flex w-full cursor-pointer select-none items-center rounded-sm px-2 py-1.5 text-xs outline-none hover:bg-accent disabled:opacity-50 disabled:pointer-events-none"
            disabled={!canDrillDownCols}
            onClick={() => handleAction('drill-down-cols')}
            data-testid="menu-drill-down-cols"
          >
            <ChevronDown className="mr-2 h-3 w-3" />
            Drill Down
          </button>
          <button
            className="relative flex w-full cursor-pointer select-none items-center rounded-sm px-2 py-1.5 text-xs outline-none hover:bg-accent disabled:opacity-50 disabled:pointer-events-none"
            disabled={!canDrillUpCols}
            onClick={() => handleAction('drill-up-cols')}
            data-testid="menu-drill-up-cols"
          >
            <ChevronUp className="mr-2 h-3 w-3" />
            Drill Up
          </button>
          <button
            className="relative flex w-full cursor-pointer select-none items-center rounded-sm px-2 py-1.5 text-xs outline-none hover:bg-accent disabled:opacity-50 disabled:pointer-events-none"
            disabled={!canDrillDownCols}
            onClick={() => handleAction('go-to-next-level-cols')}
            data-testid="menu-next-level-cols"
          >
            <ChevronRight className="mr-2 h-3 w-3" />
            Go to Next Level
          </button>
          <button
            className="relative flex w-full cursor-pointer select-none items-center rounded-sm px-2 py-1.5 text-xs outline-none hover:bg-accent disabled:opacity-50 disabled:pointer-events-none"
            disabled={!canDrillDownCols}
            onClick={() => handleAction('expand-to-next-level-cols')}
            data-testid="menu-expand-cols"
          >
            <Expand className="mr-2 h-3 w-3" />
            Expand to Next Level
          </button>
        </>
      )}

      {/* General actions */}
      <div className="my-1 h-px bg-border" />
      <button
        className="relative flex w-full cursor-pointer select-none items-center rounded-sm px-2 py-1.5 text-xs outline-none hover:bg-accent"
        onClick={() => handleAction('expand-all')}
        data-testid="menu-expand-all"
      >
        <Expand className="mr-2 h-3 w-3" />
        Expand All
      </button>
      <button
        className="relative flex w-full cursor-pointer select-none items-center rounded-sm px-2 py-1.5 text-xs outline-none hover:bg-accent"
        onClick={() => handleAction('collapse-all')}
        data-testid="menu-collapse-all"
      >
        <Shrink className="mr-2 h-3 w-3" />
        Collapse All
      </button>

      {/* Card-level operations */}
      <div className="my-1 h-px bg-border" />
      <button
        className="relative flex w-full cursor-pointer select-none items-center rounded-sm px-2 py-1.5 text-xs outline-none hover:bg-accent"
        onClick={() => handleAction('edit-mode')}
        data-testid="menu-edit-mode"
      >
        <Pencil className="mr-2 h-3 w-3" />
        Edit Matrix Layout
      </button>
      <button
        className="relative flex w-full cursor-pointer select-none items-center rounded-sm px-2 py-1.5 text-xs outline-none hover:bg-accent"
        onClick={() => handleAction('export')}
        data-testid="menu-export-visual"
      >
        <Download className="mr-2 h-3 w-3" />
        Export to Excel
      </button>
      <button
        className="relative flex w-full cursor-pointer select-none items-center rounded-sm px-2 py-1.5 text-xs outline-none hover:bg-accent text-destructive hover:text-destructive"
        onClick={() => handleAction('delete')}
        data-testid="menu-delete-visual"
      >
        <Trash2 className="mr-2 h-3 w-3" />
        Delete
      </button>
    </div>
  )
}

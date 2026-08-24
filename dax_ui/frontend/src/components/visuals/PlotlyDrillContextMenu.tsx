/**
 * PlotlyDrillContextMenu - Right-click context menu for Plotly chart drill operations.
 * Modelled after MatrixContextMenu but tailored for chart hierarchies.
 */

import { useEffect, useRef, useCallback } from 'react'
import { ChevronDown, ChevronUp, ChevronsDown, Layers, ExternalLink } from 'lucide-react'
import type { DrillMeta } from '@/lib/api'

interface PlotlyDrillContextMenuProps {
  position: { x: number; y: number } | null
  onClose: () => void
  drillMeta: DrillMeta | null
  hoveredValue: unknown
  hoveredColumn?: { table: string; column: string } | null
  isExpanded: boolean
  canExpand: boolean
  onDrillDown: (value: unknown) => void
  onDrillUp: () => void
  onGoToNextLevel: () => void
  onExpandAllDown: () => void
  onCollapseOneLevel: () => void
  drillthroughPages?: Array<{ id: string; name?: string; displayName?: string }>
  onDrillthrough?: (pageId: string, hoveredValue?: unknown) => void
}

export function PlotlyDrillContextMenu({
  position,
  onClose,
  drillMeta,
  hoveredValue,
  isExpanded,
  canExpand,
  onDrillDown,
  onDrillUp,
  onGoToNextLevel,
  onExpandAllDown,
  onCollapseOneLevel,
  drillthroughPages,
  onDrillthrough,
}: PlotlyDrillContextMenuProps) {
  const menuRef = useRef<HTMLDivElement>(null)

  // Close on outside click / Escape
  useEffect(() => {
    if (!position) return

    const handleClick = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        onClose()
      }
    }

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }

    // Delay to avoid closing immediately on the triggering right-click
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

  // Adjust position to keep menu within viewport
  useEffect(() => {
    if (!position || !menuRef.current) return
    const rect = menuRef.current.getBoundingClientRect()
    const vw = window.innerWidth
    const vh = window.innerHeight
    let { x, y } = position
    if (x + rect.width > vw) x = vw - rect.width - 4
    if (y + rect.height > vh) y = vh - rect.height - 4
    if (x < 0) x = 4
    if (y < 0) y = 4
    if (x !== position.x || y !== position.y) {
      menuRef.current.style.left = `${x}px`
      menuRef.current.style.top = `${y}px`
    }
  }, [position])

  const handleDrillDown = useCallback(() => {
    if (hoveredValue != null) onDrillDown(hoveredValue)
    onClose()
  }, [hoveredValue, onDrillDown, onClose])

  const handleDrillUp = useCallback(() => {
    onDrillUp()
    onClose()
  }, [onDrillUp, onClose])

  const handleGoToNextLevel = useCallback(() => {
    onGoToNextLevel()
    onClose()
  }, [onGoToNextLevel, onClose])

  const handleExpandAllDown = useCallback(() => {
    onExpandAllDown()
    onClose()
  }, [onExpandAllDown, onClose])

  const handleCollapseOneLevel = useCallback(() => {
    onCollapseOneLevel()
    onClose()
  }, [onCollapseOneLevel, onClose])

  if (!position || !drillMeta) return null

  const canDrillDown = drillMeta.can_drill_down && hoveredValue != null
  const canDrillUp = drillMeta.can_drill_up
  const canGoToNextLevel = drillMeta.can_drill_down
  const currentLevelName = drillMeta.levels[drillMeta.current_level]?.name || `Level ${drillMeta.current_level}`
  const nextLevelName = drillMeta.levels[drillMeta.current_level + 1]?.name || 'next level'
  const expandLevels = drillMeta.expand_levels ?? 1
  const nextExpandName = drillMeta.levels[drillMeta.current_level + expandLevels]?.name || 'next level'

  const btnClass = 'relative flex w-full cursor-pointer select-none items-center rounded-sm px-2 py-1.5 text-xs outline-none hover:bg-accent disabled:opacity-50 disabled:pointer-events-none'

  return (
    <div
      ref={menuRef}
      className="fixed z-50 min-w-[200px] rounded-md border bg-popover p-1 text-popover-foreground shadow-md"
      style={{
        left: position.x,
        top: position.y,
      }}
      data-testid="plotly-drill-context-menu"
    >
      <div className="px-2 py-1 text-[10px] font-semibold text-muted-foreground uppercase">
        {drillMeta.hierarchy_name} — {currentLevelName}
      </div>

      {/* Drill Down on value */}
      <button
        className={btnClass}
        disabled={!canDrillDown}
        onClick={handleDrillDown}
        data-testid="plotly-menu-drill-down"
      >
        <ChevronDown className="mr-2 h-3 w-3" />
        {hoveredValue != null
          ? `Drill Down on "${String(hoveredValue)}"`
          : 'Drill Down (hover a data point)'}
      </button>

      {/* Drill Up */}
      <button
        className={btnClass}
        disabled={!canDrillUp}
        onClick={handleDrillUp}
        data-testid="plotly-menu-drill-up"
      >
        <ChevronUp className="mr-2 h-3 w-3" />
        Drill Up
      </button>

      {/* Go to Next Level */}
      <button
        className={btnClass}
        disabled={!canGoToNextLevel}
        onClick={handleGoToNextLevel}
        data-testid="plotly-menu-next-level"
      >
        <ChevronsDown className="mr-2 h-3 w-3" />
        Go to Next Level ({nextLevelName})
      </button>

      <div className="my-1 h-px bg-border" />

      {/* Expand All Down One Level */}
      <button
        className={btnClass}
        disabled={!canExpand}
        onClick={handleExpandAllDown}
        data-testid="plotly-menu-expand"
      >
        <Layers className="mr-2 h-3 w-3" />
        Expand All Down One Level ({nextExpandName})
      </button>

      {/* Collapse One Level */}
      {isExpanded && (
        <button
          className={btnClass}
          onClick={handleCollapseOneLevel}
          data-testid="plotly-menu-collapse"
        >
          <Layers className="mr-2 h-3 w-3 opacity-50" />
          Collapse One Level
        </button>
      )}

      {/* Drillthrough */}
      {drillthroughPages && drillthroughPages.length > 0 && hoveredValue != null && (
        <>
          <div className="my-1 h-px bg-border" />
          <div className="px-2 py-1 text-[10px] font-semibold text-muted-foreground uppercase">
            Drillthrough
          </div>
          {drillthroughPages.map(page => (
            <button
              key={page.id}
              className={btnClass}
              onClick={() => {
                onDrillthrough?.(page.id, hoveredValue)
                onClose()
              }}
              data-testid={`plotly-menu-drillthrough-${page.id}`}
            >
              <ExternalLink className="mr-2 h-3 w-3" />
              {page.displayName || page.name || page.id}
            </button>
          ))}
        </>
      )}
    </div>
  )
}

import { cn } from '@/lib/utils'
import { type VisualInfo, type VisualInteractions, type ColumnRef, exportVisual, updateVisual } from '@/lib/api'
import { useVisualRender, useInteractions, useVisualDragResize, useMatrixState, useMatrixStore, useTheme } from '@/hooks'
import { EMPTY_RENDER_STATE } from '@/hooks/useVisualRender'
import { useAppStore, useReportStore, useThemeStore } from '@/stores'
import { useFilterStore, type Filter as VisualFilter } from '@/stores/filter-store'
import { useChartDrillStore } from '@/stores/chart-drill-store'
import { useDrillthroughStore } from '@/stores/drillthrough-store'
import { shadowClass } from '@/lib/theme-defaults'
import { toast } from '@/components/ui/toast'
import { isHighlightResponse, mergeHighlightResponse } from '@/lib/highlightMerge'
import { StaticVisualContent, isStaticVisualType } from '@/components/visuals/StaticVisualContent'
import { AlertTriangle, Info, Loader2, RefreshCw, Download, Trash2, Scissors, Copy, CopyPlus, MoreVertical, Pencil, ShieldAlert, Maximize2, Camera, Group, Ungroup, ChevronUp, ChevronDown, ChevronsDown, Layers, ArrowUpAZ, ArrowDownZA, ArrowUpDown, Filter } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { lazy, Suspense, useMemo, useCallback, useState, useRef, useEffect } from 'react'
import { MatrixVisual } from './MatrixVisual'
import { MatrixEditMode } from './MatrixEditMode'
import { PlotlyDrillContextMenu } from './PlotlyDrillContextMenu'
import { TooltipPopup, useTooltipPage } from './TooltipPopup'
import { PowerBISidecarBadges } from './PowerBISidecarBadges'
import { IBCSBarChart, IBCSCard, IBCSLineChart, IBCSWaterfall, IBCSTable, IBCSSmallMultiples } from './ibcs'
import { DecisionPanel } from '@/components/decision'
import type { TablixPlan, TablixCell } from '@/types/matrix'
import type { MatrixCellInfo } from '@/components/matrix'
import type { ColumnWidths } from '@/hooks/useColumnResize'
import {
  ContextMenu,
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuSeparator,
  ContextMenuTrigger,
} from '@/components/ui/context-menu'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
// Lazy load Plotly to reduce initial bundle size
const Plot = lazy(() => import('react-plotly.js'))

// Default dimensions
const DEFAULT_WIDTH = 400
const DEFAULT_HEIGHT = 300
const EMPTY_VISUAL_FILTERS: VisualFilter[] = []

interface VisualCardProps {
  visual: VisualInfo
  isSelected: boolean
  isInGroup?: boolean
  groupMembers?: string[]
  onSelect: (e?: React.MouseEvent) => void
  style: React.CSSProperties
}

type LooseRecord = Record<string, unknown>

function asRecord(value: unknown): LooseRecord | null {
  return typeof value === 'object' && value !== null && !Array.isArray(value) ? value as LooseRecord : null
}

function asArray(value: unknown): unknown[] {
  if (Array.isArray(value)) return value
  return value == null ? [] : [value]
}

function summarizeFilterBadge(filter: unknown): string {
  const row = asRecord(filter)
  if (!row) return 'Imported filter'
  const columnRecord = asRecord(row.column)
  const table = typeof row.table === 'string'
    ? row.table
    : typeof columnRecord?.table === 'string'
      ? columnRecord.table
      : ''
  const column = typeof row.column === 'string'
    ? row.column
    : typeof columnRecord?.column === 'string'
      ? columnRecord.column
      : ''
  const field = table && column ? `${table}.${column}` : column || table || 'Imported filter'
  const operator = typeof row.operator === 'string' ? row.operator : 'in'
  const values = Array.isArray(row.values)
    ? row.values
    : row.value != null
      ? [row.value]
      : []
  const shown = values.slice(0, 2).map(value => String(value)).join(', ')
  const suffix = values.length > 2 ? ` +${values.length - 2}` : ''
  return shown ? `${field} ${operator} ${shown}${suffix}` : field
}

function getObjectBool(record: LooseRecord | null, keys: string[]): boolean | undefined {
  if (!record) return undefined
  for (const key of keys) {
    const value = record[key]
    if (typeof value === 'boolean') return value
    if (typeof value === 'string' && value.trim()) {
      const normalized = value.trim().toLowerCase()
      if (['true', 'yes', '1', 'on', 'show'].includes(normalized)) return true
      if (['false', 'no', '0', 'off', 'hide'].includes(normalized)) return false
    }
  }
  return undefined
}

function powerBIHeaderIconVisible(visualHeader: unknown, keys: string[], fallback = true): boolean {
  const header = asRecord(visualHeader)
  const icons = asRecord(header?.icons)
  const objects = asRecord(header?.objects)
  const visualHeaderObject = asRecord(objects?.['vc:visualHeader']) ?? asRecord(objects?.visualHeader)
  const headerEnabled = getObjectBool(visualHeaderObject, ['show', 'visible', 'enabled'])
  if (headerEnabled === false) return false
  const fromIcons = getObjectBool(icons, keys)
  if (fromIcons !== undefined) return fromIcons
  const fromHeader = getObjectBool(header, keys)
  if (fromHeader !== undefined) return fromHeader
  return fallback
}

function getContainerChromeInfo(containerFormat: unknown) {
  const container = asRecord(containerFormat)
  const objects = asRecord(container?.objects)
  const divider = asRecord(objects?.['vc:divider']) ?? asRecord(objects?.divider)
  const stylePreset = asRecord(objects?.['vc:stylePreset']) ?? asRecord(objects?.stylePreset)
  const layerOrder = asRecord(objects?.['vc:layerOrder']) ?? asRecord(objects?.layerOrder)
  return {
    dividerVisible: getObjectBool(divider, ['show', 'visible', 'enabled']) === true,
    dividerColor: typeof divider?.color === 'string' ? divider.color : '#d1d5db',
    dividerWidth: typeof divider?.width === 'number' ? divider.width : 1,
    stylePreset: typeof stylePreset?.name === 'string' ? stylePreset.name : typeof container?.stylePreset === 'string' ? container.stylePreset : undefined,
    keepLayerOrder: getObjectBool(layerOrder, ['keepLayerOrder', 'keep_layer_order']) ?? getObjectBool(container, ['keepLayerOrder', 'keep_layer_order']),
  }
}

function getMatrixOutlineStyle(tableMatrixFormat: unknown): string | undefined {
  const format = asRecord(tableMatrixFormat)
  const objects = asRecord(format?.objects)
  const rowHeaders = asRecord(objects?.rowHeaders) ?? asRecord(format?.rowHeaders)
  const value = rowHeaders?.outline_style ?? rowHeaders?.outlineStyle
  return typeof value === 'string' && value.trim() ? value.trim() : undefined
}

// Resize handle component
function ResizeHandle({ 
  position, 
  onPointerDown 
}: { 
  position: 'n' | 's' | 'e' | 'w' | 'ne' | 'nw' | 'se' | 'sw'
  onPointerDown: (e: React.PointerEvent) => void
}) {
  const positionClasses: Record<string, string> = {
    n: 'top-0 left-1/2 -translate-x-1/2 -translate-y-1/2 cursor-ns-resize w-4 h-2',
    s: 'bottom-0 left-1/2 -translate-x-1/2 translate-y-1/2 cursor-ns-resize w-4 h-2',
    e: 'right-0 top-1/2 translate-x-1/2 -translate-y-1/2 cursor-ew-resize w-2 h-4',
    w: 'left-0 top-1/2 -translate-x-1/2 -translate-y-1/2 cursor-ew-resize w-2 h-4',
    ne: 'top-0 right-0 translate-x-1/2 -translate-y-1/2 cursor-nesw-resize w-3 h-3',
    nw: 'top-0 left-0 -translate-x-1/2 -translate-y-1/2 cursor-nwse-resize w-3 h-3',
    se: 'bottom-0 right-0 translate-x-1/2 translate-y-1/2 cursor-nwse-resize w-3 h-3',
    sw: 'bottom-0 left-0 -translate-x-1/2 translate-y-1/2 cursor-nesw-resize w-3 h-3',
  }

  return (
    <div
      className={cn(
        'absolute bg-primary/70 rounded-sm opacity-0 group-hover:opacity-100 hover:opacity-100 transition-opacity z-20',
        positionClasses[position]
      )}
      onPointerDown={onPointerDown}
      data-testid={`resize-handle-${position}`}
    />
  )
}

export function VisualCard({ visual, isSelected, isInGroup, groupMembers, onSelect, style }: VisualCardProps) {
  const { render } = useVisualRender()
  const { interactionFilters, applyInteractionSelection, applyRowInteractionSelection, getCategoricalColumn, hasActiveInteraction, normalizeInteractions } = useInteractions()
  const projectPath = useAppStore(s => s.projectPath)
  const currentRole = useAppStore(s => s.currentRole)
  const roles = useAppStore(s => s.roles)
  const setDirty = useAppStore(s => s.setDirty)
  const setFocusedVisualId = useAppStore(s => s.setFocusedVisualId)
  const removeVisual = useReportStore(s => s.removeVisual)
  const updateVisualInStore = useReportStore(s => s.updateVisual)
  const addVisual = useReportStore(s => s.addVisual)
  const selectVisual = useReportStore(s => s.selectVisual)
  const currentPageId = useReportStore(s => s.currentPageId)
  const selectedVisualIds = useReportStore(s => s.selectedVisualIds)
  const pages = useReportStore(s => s.pages)
  const setCurrentPage = useReportStore(s => s.setCurrentPage)
  const createGroup = useReportStore(s => s.createGroup)
  const ungroupVisuals = useReportStore(s => s.ungroupVisuals)
  const getGroupForVisual = useReportStore(s => s.getGroupForVisual)
  const copyVisualToClipboard = useReportStore(s => s.copyVisualToClipboard)
  const cutVisualToClipboard = useReportStore(s => s.cutVisualToClipboard)
  const editInteractionsSourceId = useReportStore(s => s.editInteractionsSourceId)
  const visuals = useReportStore(s => s.visuals)
  const persistedVisualFilters = useFilterStore(s => s.visualFilters[visual.id] ?? EMPTY_VISUAL_FILTERS)
  const [exporting, setExporting] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [removingHidden, setRemovingHidden] = useState(false)
  const [duplicating, setDuplicating] = useState(false)
  
  // Matrix edit mode state
  const isMatrix = visual.visual_type?.toLowerCase() === 'matrix'
  const { isEditMode, toggleEditMode } = useMatrixState({ visualId: visual.id })

  // Table/Tablix sort editor state (lifted here so the toggle button lives in the card header)
  const isTableOrTablix = ['table', 'tablix'].includes(visual.visual_type?.toLowerCase() || '')
  const [showTableSortEditor, setShowTableSortEditor] = useState(false)
  const [tableSortCount, setTableSortCount] = useState(0)

  // Chart types that support manual sort controls in header
  const CHART_SORT_TYPES = ['bar', 'column', 'combo', 'line', 'area', 'scatter', 'pie', 'donut', 'treemap', 'funnel', 'waterfall']
  const isChartWithSort = CHART_SORT_TYPES.includes(visual.visual_type?.toLowerCase() || '')
  const currentCategorySort = (visual.format?.categorySort as 'asc' | 'desc' | 'default' | undefined) || 'default'

  // IBCS bar/column mode switch (comparison vs waterfall)
  const isIBCSBarColumn = ['ibcs_bar', 'ibcs_column'].includes(visual.visual_type?.toLowerCase() || '')
  const ibcsMainChartMode = (visual.format?.ibcsMainChartMode as 'comparison' | 'waterfall' | undefined) || 'comparison'

  // Chart drill state (hierarchy drill for non-matrix visuals)
  const chartDrillMeta = useChartDrillStore(s => s.drillMeta[visual.id])
  const chartDrillLevel = useChartDrillStore(s => s.drillLevels[visual.id] ?? 0)
  const drillDown = useChartDrillStore(s => s.drillDown)
  const drillUp = useChartDrillStore(s => s.drillUp)
  const goToNextLevel = useChartDrillStore(s => s.goToNextLevel)
  const hasDrill = useChartDrillStore(s => s.hasDrill)
  const expandAllDownOneLevel = useChartDrillStore(s => s.expandAllDownOneLevel)
  const collapseOneLevel = useChartDrillStore(s => s.collapseOneLevel)
  const chartCanExpand = useChartDrillStore(s => s.canExpand(visual.id))
  const chartIsExpanded = useChartDrillStore(s => s.isExpanded(visual.id))
  const canDrillDown = chartDrillMeta?.can_drill_down ?? false
  const canDrillUp = chartDrillMeta?.can_drill_up ?? false
  const isChartWithDrill = !isMatrix && hasDrill(visual.id)
  // Drill mode: when true, clicking a chart data point drills down instead of crossfiltering
  const [drillMode, setDrillMode] = useState(false)
  // Plotly context menu state (position + hovered data point value)
  const [plotlyContextMenu, setPlotlyContextMenu] = useState<{ pos: { x: number; y: number }; value: unknown } | null>(null)
  // Tooltip page hover state
  const { hoverData: tooltipHoverData, showTooltip: showTooltipPage, dismissTooltip: dismissTooltipPage, hasTooltipPage } = useTooltipPage(visual.tooltip_page_id)
  const handleTooltipUnhover = useCallback(() => {
    dismissTooltipPage()
  }, [dismissTooltipPage])
  // Chart category sort cycle: default → asc → desc → default
  const handleChartSortCycle = useCallback(() => {
    const cycle: Record<string, 'asc' | 'desc' | 'default'> = {
      default: 'asc',
      asc: 'desc',
      desc: 'default',
    }
    const next = cycle[currentCategorySort] || 'asc'
    updateVisualInStore(visual.id, {
      format: { ...(visual.format || {}), categorySort: next },
    })
    setDirty(true)
    // Trigger re-render so chart reflects new sort
    render(visual.id, { force: true })
  }, [visual.id, visual.format, currentCategorySort, updateVisualInStore, setDirty, render])

  const handleIBCSMainModeChange = useCallback((mode: 'comparison' | 'waterfall') => {
    updateVisualInStore(visual.id, {
      format: { ...(visual.format || {}), ibcsMainChartMode: mode },
    })
    setDirty(true)
  }, [visual.id, visual.format, updateVisualInStore, setDirty])

  // Use drag/resize hook
  const {
    position,
    size,
    isDragging,
    isResizing,
    handlers,
    resizeHandlers,
  } = useVisualDragResize({
    visualId: visual.id,
    initialX: visual.layout?.x ?? visual.x ?? (style.left as number) ?? 20,
    initialY: visual.layout?.y ?? visual.y ?? (style.top as number) ?? 20,
    initialWidth: visual.layout?.w ?? visual.width ?? (style.width as number) ?? DEFAULT_WIDTH,
    initialHeight: visual.layout?.h ?? visual.height ?? (style.height as number) ?? DEFAULT_HEIGHT,
    groupMembers,
  })
  
  // Subscribe to THIS visual's render state only — avoids re-rendering
  // when other visuals' states change (the core fix for React #185).
  const reactiveState = useReportStore(s => s.renderStates[visual.id] ?? EMPTY_RENDER_STATE)
  const { loading, blocked, hiddenRefs } = reactiveState
  const error = reactiveState.error as string | null
  const data = reactiveState.data as unknown
  const hasData = data != null

  // Get interaction config for this visual
  const interactions = useMemo(() => normalizeInteractions(visual), [visual, normalizeInteractions])
  const categoricalColumn = useMemo(() => getCategoricalColumn(visual), [visual, getCategoricalColumn])
  const handleTooltipHover = useCallback((mouseX: number, mouseY: number, value: unknown) => {
    if (categoricalColumn) {
      showTooltipPage(mouseX, mouseY, { [`${categoricalColumn.table}.${categoricalColumn.column}`]: value })
      return
    }
    showTooltipPage(mouseX, mouseY, { value: String(value) })
  }, [categoricalColumn, showTooltipPage])
  const isInteractionSource = hasActiveInteraction(visual.id)

  // Selected values + point indices for highlighting.
  // Two cases:
  //  A) This visual IS the source — highlight its own clicked values
  //  B) This visual is a TARGET in highlight mode — highlight values from
  //     incoming interaction filters whose column matches our categorical axis
  const selectedValues = useMemo(() => {
    // Case A: source visual self-highlight
    const selfFilter = interactionFilters.find(f => f.source_visual_id === visual.id)
    if (selfFilter) return selfFilter.values

    // Case B: target visual highlight mode
    if (!interactions.is_affected || interactions.mode !== 'highlight') return null
    if (!categoricalColumn) return null

    // Collect values from OTHER visuals' interaction filters that match our axis column
    const otherFilters = interactionFilters.filter(f => f.source_visual_id !== visual.id)
    if (otherFilters.length === 0) return null

    const matchingValues: unknown[] = []
    for (const f of otherFilters) {
      if (f.table === categoricalColumn.table && f.column === categoricalColumn.column) {
        matchingValues.push(...f.values)
      }
    }
    return matchingValues.length > 0 ? matchingValues : null
  }, [interactionFilters, visual.id, interactions, categoricalColumn])

  const selectedPointIndices = useMemo(() => {
    const filter = interactionFilters.find(f => f.source_visual_id === visual.id)
    if (!filter) return null
    return filter.pointIndices ?? null
  }, [interactionFilters, visual.id])

  // Handle click on chart point
  const handleChartClick = useCallback((value: unknown, isMultiSelect: boolean, pointIndex?: number, columnOverride?: { table: string; column: string }) => {
    // When drill mode is active, drill down on the clicked value
    if (drillMode && canDrillDown && chartDrillMeta) {
      const currentLevel = chartDrillMeta.levels[chartDrillMeta.current_level]
      if (currentLevel) {
        drillDown(visual.id, currentLevel.column, value, chartDrillMeta.table)
        setDrillMode(false) // Reset drill mode after drilling
        // Trigger re-render with new drill state
        render(visual.id, { force: true })
        return
      }
    }

    if (!interactions.affects_others) return
    const col = columnOverride
      ? { type: 'ColumnRef' as const, ...columnOverride }
      : categoricalColumn
    if (!col) return
    
    applyInteractionSelection({
      visualId: visual.id,
      column: col as ColumnRef,
      value,
      isMultiSelect,
      pointIndex,
    })
  }, [visual.id, interactions.affects_others, categoricalColumn, applyInteractionSelection, drillMode, canDrillDown, chartDrillMeta, drillDown, render])

  // Drill up handler
  const handleDrillUp = useCallback((e: React.MouseEvent) => {
    e.stopPropagation()
    if (!canDrillUp) return
    drillUp(visual.id)
    render(visual.id, { force: true })
  }, [visual.id, canDrillUp, drillUp, render])

  // Toggle drill mode (for drill-down, user clicks button then clicks a bar)
  const handleToggleDrillMode = useCallback((e: React.MouseEvent) => {
    e.stopPropagation()
    if (!canDrillDown) return
    setDrillMode(prev => !prev)
  }, [canDrillDown])

  // Go to next hierarchy level showing ALL values (no filter, no click needed)
  const handleGoToNextLevel = useCallback((e: React.MouseEvent) => {
    e.stopPropagation()
    if (!canDrillDown) return
    goToNextLevel(visual.id)
    setDrillMode(false)
    render(visual.id, { force: true })
  }, [visual.id, canDrillDown, goToNextLevel, render])

  // Expand all down one level: show current level(s) + next level with concatenated labels
  const handleExpandAllDown = useCallback((e: React.MouseEvent) => {
    e.stopPropagation()
    if (!chartCanExpand) return
    expandAllDownOneLevel(visual.id)
    render(visual.id, { force: true })
  }, [visual.id, chartCanExpand, expandAllDownOneLevel, render])

  // Collapse one expanded level
  const handleCollapseOneLevel = useCallback((e: React.MouseEvent) => {
    e.stopPropagation()
    if (!chartIsExpanded) return
    collapseOneLevel(visual.id)
    render(visual.id, { force: true })
  }, [visual.id, chartIsExpanded, collapseOneLevel, render])

  // Plotly right-click: show context menu with drill options
  const handlePlotlyRightClick = useCallback((pos: { x: number; y: number }, hoveredValue: unknown) => {
    if (!isChartWithDrill) return
    setPlotlyContextMenu({ pos, value: hoveredValue })
  }, [isChartWithDrill])

  // Drill down on a specific value from context menu
  const handleContextDrillDown = useCallback((value: unknown) => {
    if (!canDrillDown || !chartDrillMeta) return
    const currentLevel = chartDrillMeta.levels[chartDrillMeta.current_level]
    if (currentLevel) {
      drillDown(visual.id, currentLevel.column, value, chartDrillMeta.table)
      render(visual.id, { force: true })
    }
  }, [visual.id, canDrillDown, chartDrillMeta, drillDown, render])

  // Close context menu
  const handleCloseContextMenu = useCallback(() => {
    setPlotlyContextMenu(null)
  }, [])

  // Drillthrough: find target pages that are marked as drillthrough targets
  const drillthroughPages = useMemo(() => 
    pages.filter(p => p.drillthrough && p.id !== currentPageId), 
    [pages, currentPageId]
  )
  const startDrillthrough = useDrillthroughStore(s => s.startDrillthrough)

  // Handle drillthrough navigation
  const handleDrillthrough = useCallback((targetPageId: string, contextValue?: unknown) => {
    // Build filters from this visual's categorical column/value context
    const col = categoricalColumn
    const filters: Array<{ table: string; column: string; value: unknown }> = []
    if (col && contextValue !== undefined && contextValue !== null) {
      filters.push({ table: col.table, column: col.column, value: contextValue })
    }
    // If visual has an active interaction selection, use those values as drillthrough filters
    const selfFilter = interactionFilters.find(f => f.source_visual_id === visual.id)
    if (filters.length === 0 && selfFilter && col) {
      for (const v of selfFilter.values) {
        filters.push({ table: col.table, column: col.column, value: v })
      }
    }
    startDrillthrough(currentPageId ?? '', filters)
    setCurrentPage(targetPageId)
  }, [categoricalColumn, interactionFilters, visual.id, currentPageId, startDrillthrough, setCurrentPage])

  const patchTablixInStore = useCallback((mutator: (tablix: Record<string, unknown>) => Record<string, unknown>) => {
    const latestVisual = useReportStore.getState().visuals.find(v => v.id === visual.id)
    if (!latestVisual) return
    const latestEnc = (latestVisual.encodings || {}) as Record<string, unknown>
    const latestTablix = (latestEnc.tablix || {}) as Record<string, unknown>
    const nextTablix = mutator(latestTablix)
    updateVisualInStore(visual.id, {
      encodings: { ...latestEnc, tablix: nextTablix },
    })
  }, [visual.id, updateVisualInStore])

  const updateBlockExpandedPaths = useCallback((opts: {
    axis: 'rows' | 'cols'
    blockIndex: number
    path: string[]
    expanded: boolean
  }) => {
    const { axis, blockIndex, path, expanded } = opts
    patchTablixInStore((tablix) => {
      const key = axis === 'rows' ? 'rowMeasureBlocks' : 'columnMeasureBlocks'
      const blocks = Array.isArray(tablix[key]) ? [...(tablix[key] as unknown[])] : []
      const block = { ...(blocks[blockIndex] as Record<string, unknown> | undefined) }
      const expandedPaths = Array.isArray(block.expandedPaths) ? [...block.expandedPaths] : []

      const pathKey = JSON.stringify(path)
      const matchIndex = expandedPaths.findIndex((ep) => {
        if (!ep || typeof ep !== 'object') return false
        const axisVal = (ep as { axis?: string }).axis
        const epPath = (ep as { path?: unknown }).path
        return axisVal === axis && JSON.stringify(Array.isArray(epPath) ? epPath : []) === pathKey
      })

      if (expanded) {
        if (matchIndex < 0) {
          expandedPaths.push({ axis, path })
        }
      } else {
        const prefix = path.join('__') + '__'
        const filtered = expandedPaths.filter((ep) => {
          if (!ep || typeof ep !== 'object') return true
          const axisVal = (ep as { axis?: string }).axis
          if (axisVal !== axis) return true
          const epPath = (ep as { path?: unknown }).path
          const p = Array.isArray(epPath) ? epPath : []
          const keyStr = p.join('__')
          if (keyStr === path.join('__')) return false
          return !keyStr.startsWith(prefix)
        })
        expandedPaths.splice(0, expandedPaths.length, ...filtered)
      }

      block.expandedPaths = expandedPaths
      block.expandAll = false
      blocks[blockIndex] = block

      return { ...tablix, [key]: blocks }
    })
  }, [patchTablixInStore])

  const setAllBlockExpandState = useCallback((axis: 'rows' | 'cols', expanded: boolean) => {
    patchTablixInStore((tablix) => {
      const key = axis === 'rows' ? 'rowMeasureBlocks' : 'columnMeasureBlocks'
      const blocksRaw = tablix[key]
      if (!Array.isArray(blocksRaw) || blocksRaw.length === 0) return tablix

      const nextBlocks = blocksRaw.map((blockRaw) => {
        const block = { ...(blockRaw as Record<string, unknown>) }
        block.expandAll = expanded
        block.expandedPaths = []
        return block
      })

      return { ...tablix, [key]: nextBlocks }
    })
  }, [patchTablixInStore])

  // Matrix: expand/collapse row hierarchy, then re-render
  const handleMatrixExpand = useCallback((rowPath: string[], expanded: boolean, ctx?: { blockIndex?: number }) => {
    if (ctx?.blockIndex !== undefined) {
      updateBlockExpandedPaths({
        axis: 'rows',
        blockIndex: ctx.blockIndex,
        path: rowPath,
        expanded,
      })
    } else {
      const store = useMatrixStore.getState()
      store.setRowExpanded(visual.id, rowPath, expanded)
    }
    // Trigger re-render with updated expand state
    render(visual.id, { force: true })
  }, [visual.id, render, updateBlockExpandedPaths])

  const handleMatrixColExpand = useCallback((colPath: string[], expanded: boolean, ctx?: { blockIndex?: number }) => {
    if (ctx?.blockIndex !== undefined) {
      updateBlockExpandedPaths({
        axis: 'cols',
        blockIndex: ctx.blockIndex,
        path: colPath,
        expanded,
      })
    } else {
      const store = useMatrixStore.getState()
      store.setColExpanded(visual.id, colPath, expanded)
    }
    render(visual.id, { force: true })
  }, [visual.id, render, updateBlockExpandedPaths])

  // Matrix: cell click for crossfilter interaction
  const handleMatrixCellClick = useCallback((cell: TablixCell) => {
    // Only emit interaction if this visual affects others and has a row header value
    if (!interactions.affects_others) return
    if (cell.role !== 'row_header' || !cell.value) return
    // Use the row key (dimension column name) for the interaction filter
    const colName = cell.rowKey || cell.label
    if (!colName) return
    applyInteractionSelection({
      visualId: visual.id,
      column: { type: 'ColumnRef', table: '', column: colName },
      value: cell.value,
      isMultiSelect: false,
    })
  }, [visual.id, interactions.affects_others, applyInteractionSelection])

  // Matrix: drill action from context menu
  const handleMatrixDrillAction = useCallback((action: string, cellInfo: MatrixCellInfo) => {
    const store = useMatrixStore.getState()
    const axis = cellInfo.axis
    switch (action) {
      case 'drill-down-rows':
      case 'drill-down-cols':
        if (cellInfo.key && cellInfo.value !== undefined && cellInfo.level !== undefined) {
          store.drillDown(visual.id, axis, cellInfo.key, cellInfo.value, cellInfo.level)
        }
        break
      case 'drill-up-rows':
      case 'drill-up-cols':
        store.drillUp(visual.id, axis)
        break
      case 'go-to-next-level-rows':
      case 'go-to-next-level-cols':
        store.goToNextLevel(visual.id, axis)
        break
      case 'expand-to-next-level-rows':
      case 'expand-to-next-level-cols':
        store.expandToNextLevel(visual.id, axis)
        break
      case 'expand-all':
        store.expandAllBoth(visual.id)
        setAllBlockExpandState('rows', true)
        setAllBlockExpandState('cols', true)
        break
      case 'collapse-all':
        store.collapseAllBoth(visual.id)
        setAllBlockExpandState('rows', false)
        setAllBlockExpandState('cols', false)
        break
      case 'edit-mode':
        toggleEditMode()
        return  // No re-render needed for edit mode toggle
      default:
        return
    }
    render(visual.id, { force: true })
  }, [visual.id, render, setAllBlockExpandState])

  /** Simplified toolbar action handler for MatrixEditMode (expand/collapse all) */
  const handleToolbarAction = useCallback((action: string, axis?: 'rows' | 'cols') => {
    const store = useMatrixStore.getState()
    switch (action) {
      case 'expand-all':
        if (axis === 'rows') {
          store.expandAllRows(visual.id)
          setAllBlockExpandState('rows', true)
        } else if (axis === 'cols') {
          store.expandAllCols(visual.id)
          setAllBlockExpandState('cols', true)
        } else {
          store.expandAllBoth(visual.id)
          setAllBlockExpandState('rows', true)
          setAllBlockExpandState('cols', true)
        }
        break
      case 'collapse-all':
        if (axis === 'rows') {
          store.collapseAllRows(visual.id)
          setAllBlockExpandState('rows', false)
        } else if (axis === 'cols') {
          store.collapseAllCols(visual.id)
          setAllBlockExpandState('cols', false)
        } else {
          store.collapseAllBoth(visual.id)
          setAllBlockExpandState('rows', false)
          setAllBlockExpandState('cols', false)
        }
        break
      default:
        return
    }
    render(visual.id, { force: true })
  }, [visual.id, render, setAllBlockExpandState])

  const handleRetry = (e: React.MouseEvent) => {
    e.stopPropagation()
    render(visual.id, { force: true })
  }

  const handleExport = useCallback(async (e: React.MouseEvent) => {
    e.stopPropagation()
    setExporting(true)
    try {
      await exportVisual(visual.id, projectPath ?? undefined, currentRole ?? undefined)
      toast('Export complete', { variant: 'success' })
    } catch (err) {
      console.error('Export failed:', err)
      toast('Export failed', { variant: 'error' })
    } finally {
      setExporting(false)
    }
  }, [visual.id, projectPath, currentRole])

  const handleDelete = useCallback((e: React.MouseEvent) => {
    e.stopPropagation()
    if (!confirm(`Delete visual "${visual.title || visual.id}"?`)) return
    
    // In-memory only — persisted via Save All
    removeVisual(visual.id)
    setDirty(true)
  }, [visual.id, visual.title, removeVisual, setDirty])

  // Handle duplicating a visual (in-memory only, persisted via Save All)
  const handleDuplicate = useCallback(() => {
    setDuplicating(true)
    try {
      const id = `v_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`
      const duplicated = {
        id,
        title: `${visual.title || visual.id} (Copy)`,
        visual_type: visual.visual_type,
        page_id: currentPageId ?? visual.page_id,
        encodings: visual.encodings,
        interactions: visual.interactions,
        x: (visual.x ?? 20) + 30,
        y: (visual.y ?? 20) + 30,
        width: visual.width,
        height: visual.height,
      }
      addVisual(duplicated)
      selectVisual(duplicated.id)
      setDirty(true)
    } catch (err) {
      console.error('Duplicate failed:', err)
    } finally {
      setDuplicating(false)
    }
  }, [visual, currentPageId, addVisual, selectVisual, setDirty])

  const handleCopyVisual = useCallback((e?: React.MouseEvent) => {
    e?.stopPropagation()
    copyVisualToClipboard(visual.id)
    toast('Visual copied', { variant: 'success' })
  }, [copyVisualToClipboard, visual.id])

  const handleCutVisual = useCallback((e?: React.MouseEvent) => {
    e?.stopPropagation()
    cutVisualToClipboard(visual.id)
    setDirty(true)
    toast('Visual cut', { variant: 'success' })
  }, [cutVisualToClipboard, visual.id, setDirty])

  // Handle copying visual definition to clipboard
  const handleCopyDefinition = useCallback(async () => {
    const definition = {
      id: visual.id,
      title: visual.title,
      visual_type: visual.visual_type,
      encodings: visual.encodings,
      interactions: visual.interactions,
      x: visual.x,
      y: visual.y,
      width: visual.width,
      height: visual.height,
    }
    
    try {
      await navigator.clipboard.writeText(JSON.stringify(definition, null, 2))
    } catch (err) {
      console.error('Copy to clipboard failed:', err)
    }
  }, [visual])

  // Handle copying visual as picture to clipboard
  const visualCardRef = useRef<HTMLDivElement>(null)
  const handleCopyAsPicture = useCallback(async () => {
    // Find the visual card DOM element
    const el = document.querySelector(`[data-testid="visual-${visual.id}"]`) as HTMLElement | null
    if (!el) return
    try {
      const svgEl = el.querySelector('svg')
      if (svgEl) {
        // Read viewBox or bounding rect for explicit dimensions
        const vb = svgEl.getAttribute('viewBox')?.split(/[\s,]+/).map(Number)
        const svgW = vb && vb.length >= 4 ? vb[2] : (svgEl.getBoundingClientRect().width || svgEl.clientWidth || 500)
        const svgH = vb && vb.length >= 4 ? vb[3] : (svgEl.getBoundingClientRect().height || svgEl.clientHeight || 300)

        // Clone SVG
        const svgClone = svgEl.cloneNode(true) as SVGSVGElement
        svgClone.setAttribute('xmlns', 'http://www.w3.org/2000/svg')
        svgClone.setAttribute('xmlns:xlink', 'http://www.w3.org/1999/xlink')
        svgClone.setAttribute('width', String(svgW))
        svgClone.setAttribute('height', String(svgH))
        if (!svgClone.getAttribute('viewBox')) {
          svgClone.setAttribute('viewBox', `0 0 ${svgW} ${svgH}`)
        }

        // Aggressively inline ALL styles from original DOM elements onto clone.
        // We must read from the ORIGINAL (in-DOM) elements because getComputedStyle
        // only works on elements attached to the document.
        const inlineStyles = (origSel: string, cloneSel: string, props: string[]) => {
          const origEls = Array.from(svgEl.querySelectorAll(origSel))
          const cloneEls = Array.from(svgClone.querySelectorAll(cloneSel))
          origEls.forEach((origEl, idx) => {
            if (idx >= cloneEls.length) return
            const cs = window.getComputedStyle(origEl)
            const cloneEl = cloneEls[idx] as SVGElement
            // Skip pattern fills — don't override url(#...) references
            const fillAttr = cloneEl.getAttribute('fill') || ''
            for (const prop of props) {
              if (prop === 'fill' && fillAttr.startsWith('url(')) continue
              const val = cs.getPropertyValue(prop)
              if (val && val !== 'none' && val !== '') {
                cloneEl.style.setProperty(prop, val)
              }
            }
          })
        }

        // Inline text styles
        inlineStyles('text', 'text', ['font-family', 'font-size', 'fill', 'font-weight', 'font-variant-numeric'])
        // Inline shape styles
        inlineStyles('rect, line, polygon, circle, path', 'rect, line, polygon, circle, path', ['fill', 'stroke', 'stroke-width'])

        // Also inline the root SVG font-family
        const rootCs = window.getComputedStyle(svgEl)
        svgClone.style.fontFamily = rootCs.fontFamily

        // Serialize and use data URL (more reliable than blob URL for cross-browser SVG rendering)
        const svgData = new XMLSerializer().serializeToString(svgClone)
        const dataUrl = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(svgData)

        const img = new Image()
        img.onload = async () => {
          const dpr = 2  // retina quality
          const canvas = document.createElement('canvas')
          canvas.width = svgW * dpr
          canvas.height = svgH * dpr
          const ctx = canvas.getContext('2d')
          if (!ctx) return
          ctx.scale(dpr, dpr)
          ctx.fillStyle = '#ffffff'
          ctx.fillRect(0, 0, svgW, svgH)
          ctx.drawImage(img, 0, 0, svgW, svgH)
          canvas.toBlob(async (blob) => {
            if (!blob) return
            try {
              await navigator.clipboard.write([
                new ClipboardItem({ 'image/png': blob }),
              ])
              toast('Copied as picture', { variant: 'success' })
            } catch (e) {
              // Fallback: offer download
              const a = document.createElement('a')
              a.href = URL.createObjectURL(blob)
              a.download = `${visual.title || visual.id}.png`
              a.click()
              URL.revokeObjectURL(a.href)
              toast('Downloaded as picture (clipboard not available)', { variant: 'success' })
            }
          }, 'image/png')
        }
        img.onerror = (e) => {
          console.error('SVG image load error:', e)
          toast('Failed to render visual as picture', { variant: 'error' })
        }
        img.src = dataUrl
      } else {
        toast('No renderable content found', { variant: 'error' })
      }
    } catch (err) {
      console.error('Copy as picture failed:', err)
    }
  }, [visual.id, visual.title])

  // Handle removing OLS-hidden fields from visual encodings
  const handleRemoveHiddenFields = useCallback(async (e: React.MouseEvent) => {
    e.stopPropagation()
    
    // Get current role's OLS config
    const role = roles.find(r => r.name === currentRole)
    if (!role?.ols) {
      console.warn('No OLS config for current role')
      return
    }
    
    const olsHiddenTables = new Set(role.ols.tables || [])
    const olsHiddenMeasures = new Set(role.ols.measures || [])
    const olsHiddenColumns = role.ols.columns || {}
    
    // Helper to check if an expression ref is hidden
    const isHidden = (expr: unknown): boolean => {
      if (!expr || typeof expr !== 'object') return false
      const e = expr as Record<string, unknown>
      
      // Check measure ref
      if (e.type === 'measure' || e.kind === 'measure') {
        const name = (e.name || e.measure) as string
        return olsHiddenMeasures.has(name)
      }
      
      // Check column ref
      if (e.type === 'column' || e.kind === 'column') {
        const table = (e.table || '') as string
        const column = (e.column || e.name || '') as string
        if (olsHiddenTables.has(table)) return true
        const hiddenCols = olsHiddenColumns[table]
        if (hiddenCols && hiddenCols.includes(column)) return true
      }
      
      // Check table ref
      if (e.type === 'table' || e.kind === 'table') {
        const table = (e.table || e.name || '') as string
        return olsHiddenTables.has(table)
      }
      
      return false
    }
    
    // Filter encodings
    const encodings = visual.encodings || {}
    const newEncodings: Record<string, unknown> = {}
    let changed = false
    
    for (const [key, val] of Object.entries(encodings)) {
      if (Array.isArray(val)) {
        const kept = val.filter(expr => !isHidden(expr))
        newEncodings[key] = kept
        if (kept.length !== val.length) changed = true
      } else if (val && isHidden(val)) {
        newEncodings[key] = null
        changed = true
      } else {
        newEncodings[key] = val
      }
    }
    
    if (!changed) {
      console.log('No hidden fields to remove')
      return
    }
    
    setRemovingHidden(true)
    try {
      // Update visual on server
      await updateVisual(visual.id, { encodings: newEncodings }, projectPath ?? undefined)
      
      // Update visual in local store
      updateVisualInStore(visual.id, { encodings: newEncodings })
      
      // Re-render the visual
      render(visual.id, { force: true })
    } catch (err) {
      console.error('Remove hidden fields failed:', err)
    } finally {
      setRemovingHidden(false)
    }
  }, [visual.id, visual.encodings, projectPath, currentRole, roles, updateVisualInStore, render])

  // Handle focus mode
  const handleFocus = useCallback((e: React.MouseEvent) => {
    e.stopPropagation()
    setFocusedVisualId(visual.id)
  }, [visual.id, setFocusedVisualId])

  // Reporting theme — visual card layout specs
  const themeCard = useThemeStore((s) => s.reportingTheme.visualCard)
  const themeFont = useThemeStore((s) => s.reportingTheme.font)
  const showHeaderIcons = useThemeStore((s) => s.reportingTheme.canvas?.showHeaderIcons)
  const showVisualHeaders = useThemeStore((s) => s.reportingTheme.canvas?.showVisualHeaders)
  const showPbiFocusIcon = powerBIHeaderIconVisible(visual.visual_header, ['showFocusModeButton', 'focusMode', 'focus'])
  const showPbiExportIcon = powerBIHeaderIconVisible(visual.visual_header, ['showExportDataButton', 'showExportButton', 'exportData', 'export'])
  const showPbiMoreIcon = powerBIHeaderIconVisible(visual.visual_header, ['showMoreOptionsButton', 'showOptionsMenu', 'moreOptions', 'options'])
  const showPbiDrillIcons = powerBIHeaderIconVisible(visual.visual_header, ['showDrillDownButton', 'showDrillButtons', 'drill'])
  const showPbiTooltipIcon = powerBIHeaderIconVisible(visual.visual_header, ['showTooltipButton', 'tooltip', 'showHelpTooltipButton'], false)
  const containerChrome = getContainerChromeInfo(visual.container_format)
  const visualFilterBadges = useMemo(() => {
    const looseVisual = visual as unknown as LooseRecord
    const rows = [
      ...persistedVisualFilters,
      ...asArray(looseVisual.visual_filters),
      ...asArray(looseVisual.cached_filters),
    ].filter(row => asRecord(row) !== null)
    const seen = new Set<string>()
    return rows
      .map(row => summarizeFilterBadge(row))
      .filter(label => {
        if (!label || seen.has(label)) return false
        seen.add(label)
        return true
      })
      .slice(0, 3)
  }, [persistedVisualFilters, visual])

  // Whether the header bar (title + border line) is visible.
  // Controlled globally by canvas.showVisualHeaders AND per-visual by format.showVisualHeader.
  const headerVisible = showVisualHeaders !== false && visual.format?.showVisualHeader !== false
  // Per-visual title visibility (PBI: VCO title.show).  Defaults to true.
  const titleVisible = visual.format?.showTitle !== false
  // Per-visual subtitle visibility (PBI: VCO subTitle.show).  Defaults to true when subtitle exists.
  const subtitleVisible = visual.format?.showSubtitle !== false
  const displaySubtitle = visual.subtitle || ''

  // Computed style with drag/resize position + theme card layout
  // Read both native UI format names AND PBI transfer names (fallback chain)
  const fmtBgColor = (visual.format?.visualBgColor ?? visual.format?.backgroundColor) as string | undefined
  const fmtBgImage = visual.format?.visualBgImage as string | undefined
  const fmtBorderRadius = (visual.format?.visualBorderRadius ?? visual.format?.border_radius) as number | undefined
  const fmtShowBorder = (visual.format?.showVisualBorder ?? visual.format?.border_show) as boolean | undefined
  // Transparent background: explicit flag OR PBI background_show=false
  const fmtTransparentBg = visual.format?.transparentBg === true || visual.format?.background_show === false
  const fmtHeaderFontSize = visual.format?.visualHeaderFontSize as number | undefined
  const fmtHeaderFontFamily = visual.format?.headerFontFamily as string | undefined
  // PBI border color (from VCO transfer)
  const fmtBorderColor = (visual.format?.borderColor) as string | undefined
  // PBI border width (from VCO transfer)
  const fmtBorderWidth = (visual.format?.border_width) as number | undefined
  // PBI drop shadow (from VCO transfer)
  const fmtDropShadow = visual.format?.drop_shadow as { show?: boolean; shadowBlur?: number; shadowDistance?: number; shadowSpread?: number; transparency?: number; shadowColor?: string } | undefined
  // PBI padding (from VCO transfer)
  const fmtPadding = visual.format?.padding as { top?: number; left?: number; right?: number; bottom?: number } | undefined
  // z-index from layout (PBI z-order) — use for layering
  const layoutZ = visual.layout?.z
  // Format title override: format.title (from format pane) takes priority over visual.title
  const displayTitle = (visual.format?.title as string | undefined) || visual.title || ''

  // Build drop shadow CSS if specified
  const dropShadowCss = fmtDropShadow?.show
    ? `${fmtDropShadow.shadowDistance ?? 0}px ${fmtDropShadow.shadowDistance ?? 0}px ${fmtDropShadow.shadowBlur ?? 4}px ${fmtDropShadow.shadowSpread ?? 0}px ${fmtDropShadow.shadowColor ? fmtDropShadow.shadowColor : `rgba(0,0,0,${(100 - (fmtDropShadow.transparency ?? 50)) / 100})`}`
    : undefined

  // Build padding CSS if specified
  const paddingCss = fmtPadding
    ? `${fmtPadding.top ?? 0}px ${fmtPadding.right ?? 0}px ${fmtPadding.bottom ?? 0}px ${fmtPadding.left ?? 0}px`
    : undefined

  const isStaticVisual = isStaticVisualType(visual.visual_type ?? '')
  const staticAction = visual.static_content?.action
  const isActionableStaticVisual = isStaticVisual && (
    String(visual.visual_type || '').toLowerCase() === 'button'
    || Boolean(visual.static_content?.url)
    || Boolean(staticAction && staticAction.type !== 'none')
  )

  const computedStyle: React.CSSProperties = {
    ...style,
    left: position.x,
    top: position.y,
    width: size.width,
    height: size.height,
    cursor: isDragging ? 'grabbing' : undefined,
    // z-index: use PBI z-order as base, bump for selection/drag
    zIndex: isDragging || isResizing || isSelected ? (layoutZ != null ? layoutZ + 10000 : 40) : (layoutZ ?? 1),
    transition: isDragging || isResizing ? 'none' : 'box-shadow 0.2s, border-color 0.2s',
    // Theme card layout specs
    borderRadius: fmtBorderRadius ?? themeCard.borderRadius ?? 8,
    borderWidth: fmtShowBorder === false ? 0 : (fmtBorderWidth ?? themeCard.borderWidth ?? 1),
    ...(fmtBorderColor ? { borderColor: fmtBorderColor } : themeCard.borderColor && fmtShowBorder !== false ? { borderColor: themeCard.borderColor } : {}),
    ...(fmtTransparentBg ? { backgroundColor: 'transparent' } : fmtBgColor ? { backgroundColor: fmtBgColor } : themeCard.background ? { backgroundColor: themeCard.background } : {}),
    ...(fmtBgImage ? { backgroundImage: `url(${fmtBgImage})`, backgroundSize: 'cover', backgroundPosition: 'center' } : {}),
    ...(paddingCss ? { padding: paddingCss } : themeCard.padding ? { padding: themeCard.padding } : {}),
    ...(dropShadowCss ? { boxShadow: dropShadowCss } : {}),
    ...(themeFont.family ? { fontFamily: themeFont.family } : {}),
    // Decorative static visuals should not
    // intercept pointer events when they overlay interactive charts — clicks
    // pass through to sort buttons / headers underneath.  Re-enable on
    // selection, and keep actionable buttons/shapes clickable.
    ...(isStaticVisual && !isSelected && !isActionableStaticVisual ? { pointerEvents: 'none' as const } : {}),
  }

  return (
    <ContextMenu>
      <ContextMenuTrigger asChild>
        <div
          className={cn(
            'absolute cursor-pointer group flex flex-col',
            isSelected ? 'overflow-visible' : 'overflow-hidden',
            !fmtTransparentBg && 'bg-card',
            fmtShowBorder !== false && !fmtTransparentBg && 'border',
            !fmtTransparentBg && !fmtDropShadow?.show && shadowClass(themeCard.shadow),
            !fmtTransparentBg && 'hover:shadow-md',
            fmtShowBorder !== false && !fmtTransparentBg && 'hover:border-primary/50',
            isSelected && 'ring-2 ring-primary border-primary',
            isInGroup && !isSelected && 'border-2 border-dashed border-blue-400 dark:border-blue-500',
            blocked && 'border-destructive/50',
            isInteractionSource && 'ring-1 ring-blue-400',
            isDragging && 'shadow-lg opacity-90',
            isMatrix && isEditMode && 'ring-2 ring-orange-400 border-orange-400'
          )}
          style={computedStyle}
          onClick={(e) => { e.stopPropagation(); onSelect(e) }}
          onKeyDown={(e) => {
            if (e.key === 'Enter' || e.key === ' ') {
              e.preventDefault()
              e.stopPropagation()
              onSelect()
            }
          }}
          onPointerDown={handlers.onPointerDown}
          onPointerMove={handlers.onPointerMove}
          onPointerUp={handlers.onPointerUp}
          tabIndex={0}
          role="button"
          aria-label={`Visual: ${visual.title || visual.id}`}
          data-testid={`visual-${visual.id}`}
          data-visual-type={visual.visual_type}
          data-edit-mode={isMatrix && isEditMode ? 'true' : undefined}
          data-interaction-source={isInteractionSource || undefined}
          data-style-preset={containerChrome.stylePreset}
          data-keep-layer-order={containerChrome.keepLayerOrder === true ? 'true' : undefined}
        >
      {/* Resize handles - only show when selected */}
      {isSelected && (
        <>
          <ResizeHandle position="n" onPointerDown={(e) => resizeHandlers.onResizeStart(e, 'n')} />
          <ResizeHandle position="s" onPointerDown={(e) => resizeHandlers.onResizeStart(e, 's')} />
          <ResizeHandle position="e" onPointerDown={(e) => resizeHandlers.onResizeStart(e, 'e')} />
          <ResizeHandle position="w" onPointerDown={(e) => resizeHandlers.onResizeStart(e, 'w')} />
          <ResizeHandle position="ne" onPointerDown={(e) => resizeHandlers.onResizeStart(e, 'ne')} />
          <ResizeHandle position="nw" onPointerDown={(e) => resizeHandlers.onResizeStart(e, 'nw')} />
          <ResizeHandle position="se" onPointerDown={(e) => resizeHandlers.onResizeStart(e, 'se')} />
          <ResizeHandle position="sw" onPointerDown={(e) => resizeHandlers.onResizeStart(e, 'sw')} />
        </>
      )}

      {/* Edit Interactions overlay badge — shown on non-source visuals when
          "Edit Interactions" mode is active for another visual */}
      {editInteractionsSourceId && editInteractionsSourceId !== visual.id && (() => {
        const sourceVisual = visuals.find(v => v.id === editInteractionsSourceId)
        if (!sourceVisual) return null
        const targets = (sourceVisual.interactions as Record<string, unknown> | undefined)?.interaction_targets as Record<string, string> | undefined
        const globalMode = (sourceVisual.interactions as Record<string, unknown> | undefined)?.mode as string | undefined || 'filter'
        const currentTargetMode = targets?.[visual.id] ?? globalMode
        const modeLabel = currentTargetMode === 'none' ? 'None' : currentTargetMode === 'highlight' ? 'Highlight' : 'Filter'
        const modeColor = currentTargetMode === 'none'
          ? 'bg-muted text-muted-foreground border-muted-foreground/30'
          : currentTargetMode === 'highlight'
            ? 'bg-amber-100 text-amber-800 border-amber-400 dark:bg-amber-900/50 dark:text-amber-300 dark:border-amber-600'
            : 'bg-blue-100 text-blue-800 border-blue-400 dark:bg-blue-900/50 dark:text-blue-300 dark:border-blue-600'
        const modeIcon = currentTargetMode === 'none' ? '⊘' : currentTargetMode === 'highlight' ? '◐' : '▼'
        return (
          <div
            className="absolute -top-3 left-1/2 -translate-x-1/2 z-50 flex items-center"
            onClick={(e) => e.stopPropagation()}
          >
            <button
              className={cn(
                'flex items-center gap-1 px-2 py-0.5 rounded-full border text-[10px] font-medium shadow-sm',
                'cursor-pointer hover:scale-105 transition-transform',
                modeColor
              )}
              data-testid={`interaction-target-badge-${visual.id}`}
              title={`Interaction: ${modeLabel} — Click to change`}
              onClick={async (e) => {
                e.stopPropagation()
                // Cycle: filter → highlight → none → filter
                const nextMode = currentTargetMode === 'filter' ? 'highlight' : currentTargetMode === 'highlight' ? 'none' : 'filter'
                const newTargets = { ...(targets || {}), [visual.id]: nextMode }
                // If the new mode matches globalMode, remove the override to keep the map clean
                if (nextMode === globalMode) {
                  delete newTargets[visual.id]
                }
                const interactions: VisualInteractions = {
                  ...(sourceVisual.interactions || {}),
                  interaction_targets: Object.keys(newTargets).length > 0
                    ? newTargets as Record<string, 'filter' | 'highlight' | 'none'>
                    : undefined,
                }
                // Persist to backend
                await updateVisual(sourceVisual.id, { interactions }, projectPath ?? undefined)
                // Update local state
                updateVisualInStore(sourceVisual.id, { interactions })
              }}
            >
              <span>{modeIcon}</span>
              <span>{modeLabel}</span>
            </button>
          </div>
        )
      })()}

      {/* Visual header bar — Power BI style: title + subtitle + border-bottom line.
          Only shown when showVisualHeader is not explicitly false.
          Title and subtitle each have independent show/hide via format.showTitle / format.showSubtitle. */}
      {headerVisible && (titleVisible && displayTitle || subtitleVisible && displaySubtitle) ? (
        <div
          className="relative px-3 py-1 cursor-grab active:cursor-grabbing"
          data-testid={`visual-header-${visual.id}`}
          data-drag-handle
        >
          {titleVisible && displayTitle && (
            <h3
              className="font-semibold truncate"
              style={{
                fontSize: fmtHeaderFontSize ?? themeFont.sizeTitle ?? 14,
                ...(fmtHeaderFontFamily ? { fontFamily: fmtHeaderFontFamily } : {}),
                ...(!document.documentElement.classList.contains('dark') && themeFont.colorTitle ? { color: themeFont.colorTitle } : {}),
              }}
            >{displayTitle}</h3>
          )}
          {subtitleVisible && displaySubtitle && (
            <p
              className="text-muted-foreground truncate"
              data-testid={`visual-subtitle-${visual.id}`}
              style={{
                fontSize: (fmtHeaderFontSize ? Math.max(fmtHeaderFontSize - 2, 10) : (themeFont.sizeTitle ? themeFont.sizeTitle - 2 : 12)),
                ...(fmtHeaderFontFamily ? { fontFamily: fmtHeaderFontFamily } : {}),
              }}
            >{displaySubtitle}</p>
          )}
        </div>
      ) : (
        /* Headerless visuals: thin drag bar at top, visible on hover */
        <div
          className="h-2 w-full cursor-grab active:cursor-grabbing opacity-0 group-hover:opacity-100 transition-opacity bg-muted/30 hover:bg-muted/60"
          data-drag-handle
          data-testid={`visual-drag-bar-${visual.id}`}
        />
      )}

      {/* OLS blocked indicator — always visible when relevant */}
      {containerChrome.dividerVisible && (
        <div
          className="shrink-0"
          style={{
            borderTop: `${containerChrome.dividerWidth}px solid ${containerChrome.dividerColor}`,
          }}
          data-testid={`visual-container-divider-${visual.id}`}
        />
      )}

      {blocked && hiddenRefs && hiddenRefs.length > 0 && (
        <div className="absolute top-1 left-1 z-10">
          <span
            className="inline-flex items-center text-destructive"
            title={`${hiddenRefs.length} field(s) hidden by security role`}
            data-testid={`ols-indicator-${visual.id}`}
          >
            <ShieldAlert className="h-3.5 w-3.5" />
          </span>
        </div>
      )}

      <PowerBISidecarBadges visual={visual} pages={pages} />

      {visualFilterBadges.length > 0 && (
        <div
          className="pointer-events-auto absolute bottom-1 left-1 z-20 flex max-w-[calc(100%-0.5rem)] flex-wrap gap-1"
          data-testid={`visual-filter-badges-${visual.id}`}
        >
          {visualFilterBadges.map((label, index) => (
            <span
              key={`${label}-${index}`}
              className="inline-flex max-w-[180px] items-center gap-1 rounded border border-blue-300 bg-blue-50/95 px-1.5 py-0.5 text-[10px] font-medium text-blue-800 shadow-sm dark:border-blue-700 dark:bg-blue-950/90 dark:text-blue-200"
              title={label}
              data-testid={`visual-filter-badge-${visual.id}-${index}`}
            >
              <Filter className="h-3 w-3 shrink-0" />
              <span className="truncate">{label}</span>
            </span>
          ))}
        </div>
      )}

      {/* Floating header action buttons — Power BI style: float ABOVE the card.
          Uses negative top to position outside the card boundary, like Power BI does.
          Shown on hover even when the visual header line is deactivated. */}
      {showHeaderIcons !== false && (
        <div
          className="absolute -top-7 right-0 z-[50] flex items-center gap-1 p-1 rounded-t-md bg-card/90 dark:bg-card/95 border border-b-0 border-border/40 backdrop-blur-sm opacity-0 group-hover:opacity-100 transition-opacity"
          data-testid={`visual-header-actions-${visual.id}`}
        >
          {/* IBCS bar/column mode switch — comparison vs waterfall */}
          {isIBCSBarColumn && (
            <div className="flex items-center rounded-md border border-border bg-background/80" data-testid="ibcs-main-mode-switch">
              <button
                type="button"
                data-testid="ibcs-main-mode-btn-comparison"
                title="Comparison bars"
                aria-label="Comparison bars"
                className={cn(
                  'h-5 w-5 flex items-center justify-center rounded-l-md transition-colors',
                  ibcsMainChartMode === 'comparison' ? 'bg-foreground text-background' : 'text-muted-foreground hover:bg-muted'
                )}
                onClick={(e) => {
                  e.stopPropagation()
                  handleIBCSMainModeChange('comparison')
                }}
              >
                <svg width="12" height="12" viewBox="0 0 14 14" aria-hidden="true">
                  <rect x="1" y="8" width="2.5" height="5" fill="currentColor" />
                  <rect x="5.75" y="5.5" width="2.5" height="7.5" fill="currentColor" />
                  <rect x="10.5" y="3" width="2.5" height="10" fill="currentColor" />
                </svg>
              </button>
              <button
                type="button"
                data-testid="ibcs-main-mode-btn-waterfall"
                title="Waterfall bridge"
                aria-label="Waterfall bridge"
                className={cn(
                  'h-5 w-5 flex items-center justify-center rounded-r-md transition-colors',
                  ibcsMainChartMode === 'waterfall' ? 'bg-foreground text-background' : 'text-muted-foreground hover:bg-muted'
                )}
                onClick={(e) => {
                  e.stopPropagation()
                  handleIBCSMainModeChange('waterfall')
                }}
              >
                <svg width="12" height="12" viewBox="0 0 14 14" aria-hidden="true">
                  <rect x="1" y="7" width="3" height="3" fill="currentColor" />
                  <rect x="5.5" y="4" width="3" height="3" fill="currentColor" />
                  <rect x="10" y="8" width="3" height="3" fill="currentColor" />
                  <path d="M4 8.5 H5.5 M8.5 5.5 H10" stroke="currentColor" strokeWidth="1" fill="none" />
                </svg>
              </button>
            </div>
          )}
          {/* Matrix edit mode button */}
          {isMatrix && (
            <Button
              variant={isEditMode ? 'default' : 'ghost'}
              size="icon"
              className={cn('h-5 w-5', isEditMode ? '' : '')}
              data-testid={`matrix-edit-btn-${visual.id}`}
              onClick={(e) => {
                e.stopPropagation()
                toggleEditMode()
              }}
              aria-label={isEditMode ? 'Exit edit mode' : 'Edit matrix layout'}
              title={isEditMode ? 'Exit Edit Mode' : 'Edit matrix layout (cell formatting, rules, structure)'}
            >
              <Pencil className="h-3 w-3" />
            </Button>
          )}
          {/* Matrix options menu */}
          {isMatrix && showPbiMoreIcon && (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-5 w-5"
                  data-testid={`matrix-options-btn-${visual.id}`}
                  onClick={(e) => e.stopPropagation()}
                  aria-label="Matrix options"
                  title="Matrix options"
                >
                  <MoreVertical className="h-3 w-3" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem
                  onClick={(e) => {
                    e.stopPropagation()
                    toggleEditMode()
                  }}
                  data-testid="matrix-options-edit-btn"
                >
                  <Pencil className="h-3 w-3 mr-2" />
                  {isEditMode ? 'Exit Edit Mode' : 'Edit'}
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          )}
          {/* Chart drill buttons */}
          {isChartWithDrill && showPbiDrillIcons && (
            <>
              <Button
                variant="ghost"
                size="icon"
                className="h-5 w-5"
                onClick={handleDrillUp}
                disabled={!canDrillUp}
                data-testid={`drill-up-${visual.id}`}
                aria-label="Drill up"
                title={canDrillUp ? `Drill up to ${chartDrillMeta?.levels[chartDrillMeta.current_level - 1]?.name || 'previous level'}` : 'At top level'}
              >
                <ChevronUp className="h-3 w-3" />
              </Button>
              <Button
                variant={drillMode ? 'default' : 'ghost'}
                size="icon"
                className={cn('h-5 w-5', drillMode ? '' : '')}
                onClick={handleToggleDrillMode}
                disabled={!canDrillDown}
                data-testid={`drill-down-${visual.id}`}
                aria-label="Drill down mode"
                title={canDrillDown ? `Click to enable drill-down, then click a data point (${chartDrillMeta?.levels[chartDrillMeta.current_level + 1]?.name || 'next level'})` : 'At bottom level'}
              >
                <ChevronDown className="h-3 w-3" />
              </Button>
              <Button
                variant="ghost"
                size="icon"
                className="h-5 w-5"
                onClick={handleGoToNextLevel}
                disabled={!canDrillDown}
                data-testid={`drill-next-level-${visual.id}`}
                aria-label="Go to next level"
                title={canDrillDown ? `Go to next level: show all ${chartDrillMeta?.levels[chartDrillMeta.current_level + 1]?.name || 'next level'} values` : 'At bottom level'}
              >
                <ChevronsDown className="h-3 w-3" />
              </Button>
              <Button
                variant={chartIsExpanded ? 'default' : 'ghost'}
                size="icon"
                className="h-5 w-5"
                onClick={chartIsExpanded ? handleCollapseOneLevel : handleExpandAllDown}
                disabled={!chartCanExpand && !chartIsExpanded}
                data-testid={`drill-expand-${visual.id}`}
                aria-label={chartIsExpanded ? 'Collapse one level' : 'Expand all down one level'}
                title={
                  chartIsExpanded
                    ? 'Collapse one expanded level'
                    : chartCanExpand
                      ? `Expand all down one level: show ${chartDrillMeta?.levels[chartDrillMeta.current_level + (chartDrillMeta.expand_levels ?? 1)]?.name || 'next level'} alongside current`
                      : 'Cannot expand further'
                }
              >
                <Layers className="h-3 w-3" />
              </Button>
            </>
          )}
          {/* Chart sort toggle — cycle: default → asc → desc → default */}
          {isChartWithSort && (
            <Button
              variant={currentCategorySort !== 'default' ? 'default' : 'ghost'}
              size="icon"
              className="h-5 w-5"
              onClick={(e) => { e.stopPropagation(); handleChartSortCycle() }}
              data-testid={`chart-sort-toggle-${visual.id}`}
              aria-label={`Sort: ${currentCategorySort}`}
              title={`Category sort: ${currentCategorySort === 'asc' ? 'Ascending (click for Descending)' : currentCategorySort === 'desc' ? 'Descending (click for Default)' : 'Default (click for Ascending)'}`}
            >
              {currentCategorySort === 'asc' ? (
                <ArrowUpAZ className="h-3 w-3" />
              ) : currentCategorySort === 'desc' ? (
                <ArrowDownZA className="h-3 w-3" />
              ) : (
                <ArrowUpDown className="h-3 w-3" />
              )}
            </Button>
          )}
          {/* Table/Tablix sort editor toggle */}
          {isTableOrTablix && (
            <Button
              variant={showTableSortEditor ? 'default' : 'ghost'}
              size="icon"
              className="h-5 w-5"
              onClick={(e) => { e.stopPropagation(); setShowTableSortEditor(prev => !prev) }}
              data-testid={`sort-editor-toggle-${visual.id}`}
              aria-label="Sort editor"
              title="Sort editor"
            >
              <span className="text-[10px] font-bold leading-none">⇅{tableSortCount > 0 ? tableSortCount : ''}</span>
            </Button>
          )}
          {showPbiTooltipIcon && (visual.tooltip_page_id || visual.tooltip) && (
            <Button
              variant="ghost"
              size="icon"
              className="h-5 w-5"
              data-testid={`tooltip-info-${visual.id}`}
              aria-label="Tooltip target"
              title={visual.tooltip_page_id ? `Tooltip page: ${visual.tooltip_page_id}` : 'Imported tooltip metadata'}
              onClick={(e) => e.stopPropagation()}
            >
              <Info className="h-3 w-3" />
            </Button>
          )}
          {showPbiFocusIcon && (
            <Button
              variant="ghost"
              size="icon"
              className="h-5 w-5"
              onClick={handleFocus}
              data-testid={`focus-visual-${visual.id}`}
              aria-label="Focus mode"
              title="Focus mode"
            >
              <Maximize2 className="h-3 w-3" />
            </Button>
          )}
          {showPbiExportIcon && (
            <Button
              variant="ghost"
              size="icon"
              className="h-5 w-5"
              onClick={handleExport}
              disabled={exporting}
              data-testid={`export-visual-${visual.id}`}
              aria-label="Export visual"
              title="Export visual to Excel"
            >
              {exporting ? (
                <Loader2 className="h-3 w-3 animate-spin" />
              ) : (
                <Download className="h-3 w-3" />
              )}
            </Button>
          )}
          <Button
            variant="ghost"
            size="icon"
            className="h-5 w-5 text-destructive hover:text-destructive"
            onClick={handleDelete}
            disabled={deleting}
            data-testid={`delete-visual-${visual.id}`}
            aria-label="Delete visual"
            title="Delete visual"
          >
            {deleting ? (
              <Loader2 className="h-3 w-3 animate-spin" />
            ) : (
              <Trash2 className="h-3 w-3" />
            )}
          </Button>
        </div>
      )}
      
      {/* Visual content — fills remaining height below header, clips overflow */}
      <div 
        className="relative flex-1 min-h-0 overflow-hidden"
      >
        {/* Loading state — only show full spinner overlay when no previous data exists (first load).
           For re-renders (crossfiltering, format changes), keep the chart visible without a spinner flash. */}
        {loading && !hasData && (
          <div className="absolute inset-0 flex items-center justify-center bg-background/50 z-10">
            <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
          </div>
        )}

        {/* Error state — overlay mode: keep last good render visible behind the error banner */}
        {(() => {
          if (!error || loading) return null;
          if (hasData) return (
            /* Keep-last-render: show error banner on top, render last good data underneath */
            <div className="absolute top-0 left-0 right-0 z-20 flex items-center gap-2 bg-destructive/90 text-destructive-foreground px-3 py-1.5" data-testid="error-overlay-banner">
              <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
              <p className="text-[10px] line-clamp-1 flex-1">{(() => { let m = String(error); try { const p = JSON.parse(m); if (p?.error) m = p.error; } catch {} return m; })()}</p>
              <Button
                variant="ghost"
                size="sm"
                className="h-5 px-1.5 text-[10px] text-destructive-foreground hover:bg-destructive/80"
                onClick={handleRetry}
              >
                <RefreshCw className="h-3 w-3 mr-0.5" />
                Retry
              </Button>
            </div>
          );
          return (
            /* No previous data — full error state */
            (() => {
              const errStr = String(error)
              // Parse JSON error from server
              let errorMsg = errStr
              try {
                const parsed = JSON.parse(errStr)
                if (parsed && typeof parsed === 'object' && parsed.error) {
                  errorMsg = parsed.error
                }
              } catch { /* not JSON, use as-is */ }

              // Friendly message for missing encoding slots (new/empty visuals)
              const isMissingEncoding = errorMsg.toLowerCase().includes('missing required encoding slot')
              if (isMissingEncoding) {
                return (
                  <div className="absolute inset-0 flex flex-col items-center justify-center p-4 text-center pointer-events-none">
                    <Info className="h-8 w-8 text-muted-foreground mb-2" />
                    <p className="text-sm text-muted-foreground font-medium">Configure this visual</p>
                    <p className="text-xs text-muted-foreground mt-1">
                      Drag fields into the encoding slots in the right panel to populate this visual.
                    </p>
                  </div>
                )
              }

              return (
                <div className="absolute inset-0 flex flex-col items-center justify-center p-4 text-center pointer-events-none">
                  <AlertTriangle className="h-8 w-8 text-destructive mb-2" />
                  <p className="text-xs text-destructive line-clamp-3">{errorMsg}</p>
                  <Button
                    variant="outline"
                    size="sm"
                    className="mt-2 pointer-events-auto"
                    onClick={handleRetry}
                  >
                    <RefreshCw className="h-3 w-3 mr-1" />
                    Retry
                  </Button>
                </div>
              )
            })()
          );
        })()}

        {/* Blocked state (OLS) */}
        {blocked && !loading && !error && (
          <div 
            className="absolute inset-0 flex flex-col items-center justify-center p-4 text-center bg-destructive/5"
            data-testid="olsBlockedBanner"
          >
            <AlertTriangle className="h-8 w-8 text-destructive mb-2" />
            <p className="text-xs text-destructive font-medium">Visual Blocked</p>
            <p className="text-xs text-muted-foreground mt-1">
              Contains hidden fields
            </p>
            {hiddenRefs && hiddenRefs.length > 0 && (
              <div className="mt-2 text-xs text-muted-foreground max-h-20 overflow-auto">
                {hiddenRefs.map((ref, i) => (
                  <div key={i}>
                    {ref.kind === 'column' && `${ref.table}[${ref.column}]`}
                    {ref.kind === 'measure' && ref.name}
                    {ref.kind === 'table' && ref.table}
                  </div>
                ))}
              </div>
            )}
            <Button
              variant="outline"
              size="sm"
              className="mt-3"
              onClick={handleRemoveHiddenFields}
              disabled={removingHidden}
              data-testid="btnRemoveHiddenFields"
            >
              {removingHidden ? (
                <Loader2 className="h-3 w-3 mr-1 animate-spin" />
              ) : (
                <Scissors className="h-3 w-3 mr-1" />
              )}
              Remove hidden fields
            </Button>
          </div>
        )}

        {/* Render content based on visual type — keep content visible during loading so re-renders
           don't flash blank. Content stays mounted with old data until new data arrives. */}
        {!blocked && (!error || hasData) && (
          isMatrix && isEditMode ? (
            <MatrixEditMode 
              visual={visual} 
              tablixPlan={(data as { tablix_plan?: TablixPlan; tablix?: TablixPlan })?.tablix_plan ?? (data as { tablix?: TablixPlan })?.tablix} 
              className="h-full" 
              onToolbarAction={handleToolbarAction}
              onExpand={handleMatrixExpand}
              onColExpand={handleMatrixColExpand}
            />
          ) : (
            <div className="flex flex-col h-full">
              <div className="flex-1 min-h-0 overflow-auto">
                <VisualContent
                  visual={visual}
                  data={data}
                  onChartClick={handleChartClick}
                  onPlotlyRightClick={handlePlotlyRightClick}
                  selectedValues={selectedValues}
                  selectedPointIndices={selectedPointIndices}
                  onMatrixExpand={handleMatrixExpand}
                  onMatrixColExpand={handleMatrixColExpand}
                  onMatrixCellClick={handleMatrixCellClick}
                  onMatrixDrillAction={handleMatrixDrillAction}
                  showSortEditor={showTableSortEditor}
                  setShowSortEditor={setShowTableSortEditor}
                  onSortCountChange={setTableSortCount}
                  onTooltipHover={hasTooltipPage ? handleTooltipHover : undefined}
                  onTooltipUnhover={hasTooltipPage ? handleTooltipUnhover : undefined}
                />
              </div>
            </div>
          )
        )}
        {/* Plotly drill context menu (rendered as fixed overlay) */}
        {isChartWithDrill && plotlyContextMenu && (
          <PlotlyDrillContextMenu
            position={plotlyContextMenu.pos}
            hoveredValue={plotlyContextMenu.value}
            drillMeta={chartDrillMeta ?? null}
            isExpanded={chartIsExpanded}
            canExpand={chartCanExpand}
            onDrillDown={handleContextDrillDown}
            onDrillUp={() => { drillUp(visual.id); render(visual.id, { force: true }) }}
            onGoToNextLevel={() => { goToNextLevel(visual.id); render(visual.id, { force: true }) }}
            onExpandAllDown={() => { expandAllDownOneLevel(visual.id); render(visual.id, { force: true }) }}
            onCollapseOneLevel={() => { collapseOneLevel(visual.id); render(visual.id, { force: true }) }}
            onClose={handleCloseContextMenu}
            drillthroughPages={drillthroughPages}
            onDrillthrough={(pageId) => handleDrillthrough(pageId, plotlyContextMenu.value)}
          />
        )}
        {/* Tooltip page popup (rendered as fixed overlay via portal) */}
        {hasTooltipPage && (
          <TooltipPopup hoverData={tooltipHoverData} onDismiss={dismissTooltipPage} />
        )}
        </div>
      </div>
      </ContextMenuTrigger>
      <ContextMenuContent data-testid="visualContextMenu">
        {isMatrix && (
          <>
            <ContextMenuItem
              onClick={() => toggleEditMode()}
              data-testid="contextMenuEditMode"
            >
              <Pencil className="h-4 w-4 mr-2" />
              {isEditMode ? 'Exit Edit Mode' : 'Edit Matrix Layout'}
            </ContextMenuItem>
            <ContextMenuSeparator />
          </>
        )}
        <ContextMenuItem 
          onClick={handleDuplicate} 
          disabled={duplicating}
          data-testid="contextMenuDuplicate"
        >
          {duplicating ? (
            <Loader2 className="h-4 w-4 mr-2 animate-spin" />
          ) : (
            <CopyPlus className="h-4 w-4 mr-2" />
          )}
          Duplicate
        </ContextMenuItem>
        <ContextMenuItem
          onClick={handleCopyVisual}
          data-testid="contextMenuCopyVisual"
        >
          <Copy className="h-4 w-4 mr-2" />
          Copy Visual
        </ContextMenuItem>
        <ContextMenuItem
          onClick={handleCutVisual}
          data-testid="contextMenuCutVisual"
        >
          <Scissors className="h-4 w-4 mr-2" />
          Cut Visual
        </ContextMenuItem>
        <ContextMenuItem 
          onClick={handleFocus}
          data-testid="contextMenuFocus"
        >
          <Maximize2 className="h-4 w-4 mr-2" />
          Focus Mode
        </ContextMenuItem>
        <ContextMenuItem 
          onClick={handleCopyDefinition}
          data-testid="contextMenuCopy"
        >
          <Copy className="h-4 w-4 mr-2" />
          Copy Definition
        </ContextMenuItem>
        <ContextMenuItem 
          onClick={handleCopyAsPicture}
          data-testid="contextMenuCopyPicture"
        >
          <Camera className="h-4 w-4 mr-2" />
          Copy as Picture
        </ContextMenuItem>
        <ContextMenuSeparator />
        <ContextMenuItem 
          onClick={handleExport} 
          disabled={exporting}
          data-testid="contextMenuExport"
        >
          {exporting ? (
            <Loader2 className="h-4 w-4 mr-2 animate-spin" />
          ) : (
            <Download className="h-4 w-4 mr-2" />
          )}
          Export to Excel
        </ContextMenuItem>
        <ContextMenuSeparator />
        {/* Group / Ungroup */}
        {(() => {
          const group = getGroupForVisual(visual.id)
          const canGroup = selectedVisualIds.length >= 2 && selectedVisualIds.includes(visual.id)
          return (
            <>
              {canGroup && !group && (
                <ContextMenuItem
                  onClick={() => createGroup(selectedVisualIds)}
                  data-testid="contextMenuGroup"
                >
                  <Group className="h-4 w-4 mr-2" />
                  Group Selected ({selectedVisualIds.length})
                </ContextMenuItem>
              )}
              {group && (
                <ContextMenuItem
                  onClick={() => ungroupVisuals(group.id)}
                  data-testid="contextMenuUngroup"
                >
                  <Ungroup className="h-4 w-4 mr-2" />
                  Ungroup
                </ContextMenuItem>
              )}
              {(canGroup || group) && <ContextMenuSeparator />}
            </>
          )
        })()}
        {/* Drillthrough to target pages */}
        {drillthroughPages.length > 0 && (
          <>
            <ContextMenuSeparator />
            {drillthroughPages.map(p => (
              <ContextMenuItem
                key={p.id}
                onClick={() => handleDrillthrough(p.id)}
                data-testid={`contextMenuDrillthrough-${p.id}`}
              >
                <ChevronDown className="h-4 w-4 mr-2" />
                Drillthrough → {p.title}
              </ContextMenuItem>
            ))}
          </>
        )}
        <ContextMenuSeparator />
        <ContextMenuItem 
          onClick={handleDelete} 
          disabled={deleting}
          className="text-destructive focus:text-destructive"
          data-testid="contextMenuDelete"
        >
          {deleting ? (
            <Loader2 className="h-4 w-4 mr-2 animate-spin" />
          ) : (
            <Trash2 className="h-4 w-4 mr-2" />
          )}
          Delete
        </ContextMenuItem>
      </ContextMenuContent>
    </ContextMenu>
  )
}

// Explanation commentary panel — renders explanation results from ExplanationRef bindings
function ExplanationPanel({ data }: { data: unknown }) {
  const raw = data as { explanation?: { explanations?: Array<{
    playbook: string; edu_id: string; version?: string; error?: string;
    per_row?: ExplNodeT[];
    nodes?: ExplNodeT[];
  }> } }

  const explanations = raw?.explanation?.explanations
  if (!explanations || explanations.length === 0) return null

  return (
    <div className="border-t bg-amber-50/50 px-3 py-2 space-y-2" data-testid="explanation-panel">
      <div className="flex items-center gap-1.5 text-xs font-medium text-amber-800">
        <span>💡</span>
        <span>Variance Explanation</span>
      </div>
      {explanations.map((expl, i) => (
        <div key={i} className="text-xs space-y-1">
          {expl.error ? (
            <div className="text-red-600" data-testid={`explanation-error-${i}`}>
              {expl.playbook}: {expl.error}
            </div>
          ) : (
            // Show the first per_row node as the summary, or fall back to nodes
            (() => {
              const summaryNode = expl.per_row?.[0] ?? expl.nodes?.[0]
              if (!summaryNode) return null
              return (
                <div className="rounded bg-white/80 border border-amber-200 px-2 py-1.5" data-testid={`explanation-node-${i}-0`}>
                  {summaryNode.narrative && (
                    <div className="text-amber-800 italic leading-snug">{summaryNode.narrative}</div>
                  )}
                  <div className="flex gap-3 text-muted-foreground mt-0.5">
                    {summaryNode.actual != null && <span>Actual: {Number(summaryNode.actual).toLocaleString()}</span>}
                    {summaryNode.base != null && <span>Budget: {Number(summaryNode.base).toLocaleString()}</span>}
                    {summaryNode.abs_delta != null && (
                      <span className={deltaColor(summaryNode.abs_delta, summaryNode.higher_is_better !== false)}>
                        Δ {summaryNode.abs_delta >= 0 ? '+' : ''}{Number(summaryNode.abs_delta).toLocaleString()}
                        {' '}({isFavorable(summaryNode.abs_delta, summaryNode.higher_is_better !== false) ? '✓ favorable' : '✗ unfavorable'})
                      </span>
                    )}
                    {summaryNode.rel_delta != null && (
                      <span className="text-muted-foreground">
                        ({(summaryNode.rel_delta * 100).toFixed(1)}%)
                      </span>
                    )}
                  </div>
                  {summaryNode.is_material && (
                    <span className="inline-block mt-1 text-[10px] bg-amber-200 text-amber-900 px-1.5 py-0.5 rounded">
                      Material
                    </span>
                  )}
                </div>
              )
            })()
          )}
        </div>
      ))}
    </div>
  )
}

// Shared type for explanation nodes (recursive tree)
type ExplNodeT = {
  metric: string; actual: number | null; base: number | null;
  abs_delta: number | null; rel_delta: number | null;
  narrative: string | null; children: ExplNodeT[];
  is_material: boolean; driver_mode: string | null;
  unexplained_delta?: number | null;
  sign?: number;  // +1 or -1, contribution direction to parent
  higher_is_better?: boolean;  // Whether positive delta is favorable
}

/** Determine if a delta is favorable based on higher_is_better polarity */
function isFavorable(delta: number, higher_is_better: boolean): boolean {
  return (delta > 0 && higher_is_better) || (delta < 0 && !higher_is_better)
}

/** Get CSS color class for a delta based on favorability */
function deltaColor(delta: number, higher_is_better: boolean = true): string {
  if (delta === 0) return 'text-muted-foreground'
  return isFavorable(delta, higher_is_better) ? 'text-green-700' : 'text-red-700'
}

// Client-side narrative generator based on depth selection
// Mirrors server-side _generate_explanation_narrative: tracks cumulative sign
// and disambiguates duplicate metric labels with parent prefix.
function generateNarrative(
  node: ExplNodeT,
  depth: 'children' | 'leaf' | 'all',
  comparatorLabel: string = 'budget',
): string {
  const { metric, actual, base, abs_delta: delta, rel_delta: rel } = node
  if (delta == null || delta === 0) return `${metric} is on target.`

  const direction = delta > 0 ? 'above' : 'below'
  const relPct = rel != null ? ` (${rel > 0 ? '+' : ''}${(rel * 100).toFixed(1)}%)` : ''
  const compLabel = comparatorLabel.charAt(0).toUpperCase() + comparatorLabel.slice(1)
  const higherIsBetter = node.higher_is_better !== false
  const favorable = isFavorable(delta, higherIsBetter)
  const favLabel = favorable ? 'favorable' : 'unfavorable'
  const parts: string[] = [
    `${metric} is ${Math.abs(delta).toLocaleString()}${relPct} ${direction} ${comparatorLabel}` +
    ` (Actual ${(actual ?? 0).toLocaleString()} vs ${compLabel} ${(base ?? 0).toLocaleString()}) — ${favLabel}.`
  ]

  // Collect nodes with effective sign and full ancestor path for context-qualified labels
  type TaggedNode = { node: ExplNodeT; effectiveSign: number; parentPath: string[] }

  function collectLeaves(n: ExplNodeT, effSign: number, parentPath: string[]): TaggedNode[] {
    if (!n.children || n.children.length === 0) {
      return [{ node: n, effectiveSign: effSign, parentPath }]
    }
    const leaves: TaggedNode[] = []
    for (const c of n.children) {
      const childSign = effSign * (c.sign === -1 ? -1 : 1)
      leaves.push(...collectLeaves(c, childSign, [...parentPath, n.metric]))
    }
    return leaves
  }

  function collectAll(n: ExplNodeT, effSign: number, parentPath: string[]): TaggedNode[] {
    const result: TaggedNode[] = []
    if (n.children && n.children.length > 0) {
      for (const c of n.children) {
        const childSign = effSign * (c.sign === -1 ? -1 : 1)
        const childPath = [...parentPath, n.metric]
        result.push({ node: c, effectiveSign: childSign, parentPath: childPath })
        result.push(...collectAll(c, childSign, childPath))
      }
    }
    return result
  }

  let taggedNodes: TaggedNode[] = []
  if (depth === 'leaf' && node.children?.length > 0) {
    taggedNodes = collectLeaves(node, 1, [])
  } else if (depth === 'all' && node.children?.length > 0) {
    taggedNodes = collectAll(node, 1, [])
  } else {
    // children mode: direct children with their own sign
    taggedNodes = (node.children || []).map(c => ({
      node: c,
      effectiveSign: c.sign === -1 ? -1 : 1,
      parentPath: [node.metric],
    }))
  }

  if (taggedNodes.length > 0) {
    // Disambiguate: if the same metric name appears more than once, prefix with parent label
    const metricCounts = new Map<string, number>()
    for (const t of taggedNodes) {
      metricCounts.set(t.node.metric, (metricCounts.get(t.node.metric) || 0) + 1)
    }

    const sorted = [...taggedNodes]
      .filter(t => t.node.abs_delta != null && t.node.abs_delta !== 0)
      .sort((a, b) => Math.abs(b.node.abs_delta ?? 0) - Math.abs(a.node.abs_delta ?? 0))
      .slice(0, depth === 'children' ? 8 : 5)
    if (sorted.length > 0) {
      const label = depth === 'leaf' ? 'Leaf drivers' : 'Key drivers'
      const driverParts = sorted.map(t => {
        // Apply effective sign to delta for correct contribution direction
        const contribution = (t.node.abs_delta ?? 0) * t.effectiveSign
        const sign = contribution >= 0 ? '+' : ''
        // For deep/leaf modes, always show full context path for clarity.
        // For children mode, keep concise labels and only disambiguate duplicates.
        const parentTrail = t.parentPath.join(' > ')
        const isDeepMode = depth === 'leaf' || depth === 'all'
        const compactAncestors = t.parentPath
          .filter((p, idx) => !(idx === 0 && p === metric))
          .slice(-2)
        const compactTrail = compactAncestors.join(' > ')
        const displayName = isDeepMode
          ? (compactTrail ? `${compactTrail} > ${t.node.metric}` : t.node.metric)
          : ((metricCounts.get(t.node.metric) || 0) > 1 && parentTrail
            ? `${parentTrail}: ${t.node.metric}`
            : t.node.metric)
        return `${displayName} ${sign}${contribution.toLocaleString()}`
      })
      if (depth === 'children') {
        parts.push(`${label}: ${driverParts.join(', ')}.`)
      } else {
        const bullets = driverParts.map(p => `• ${p}`).join('\n')
        parts.push(`${label}:\n${bullets}`)
      }
    }
  }

  return parts.join(' ')
}

// Recursive tree component for expanded explanation children
function ExplTreeChildren({ nodes, depth, expandAllGen }: { nodes: ExplNodeT[]; depth: number; expandAllGen?: number }) {
  // expandAllGen: positive = expand all, negative = collapse all, 0/undefined = manual
  const [expanded, setExpanded] = useState<Set<number>>(new Set())
  const lastGen = useRef(0)

  // React to expandAllGen changes
  useEffect(() => {
    if (expandAllGen == null || expandAllGen === 0) return
    if (expandAllGen === lastGen.current) return
    lastGen.current = expandAllGen
    if (expandAllGen > 0) {
      // Expand all: add all indices that have children
      setExpanded(new Set(nodes.map((_, i) => i).filter(i => {
        const c = nodes[i]?.children
        return Array.isArray(c) && c.length > 0
      })))
    } else {
      // Collapse all
      setExpanded(new Set())
    }
  }, [expandAllGen, nodes])

  if (!nodes || nodes.length === 0) return null
  const indent = depth * 12
  return (
    <div className="mt-0.5 border-l border-amber-200" style={{ marginLeft: `${indent}px`, paddingLeft: '6px' }}>
      {nodes.map((child, ci) => {
        const hasKids = Array.isArray(child.children) && child.children.length > 0
        const isOpen = expanded.has(ci)
        const delta = child.abs_delta ?? 0
        const colorClass = deltaColor(delta, child.higher_is_better !== false)
        return (
          <div key={ci} className="py-0.5">
            <div className="flex items-start gap-1">
              {hasKids ? (
                <button
                  onClick={(e) => { e.stopPropagation(); setExpanded(prev => { const n = new Set(prev); if (n.has(ci)) n.delete(ci); else n.add(ci); return n }) }}
                  className="mt-px text-amber-600 hover:text-amber-800 flex-shrink-0 font-mono text-[10px] leading-none"
                >
                  {isOpen ? '▼' : '▶'}
                </button>
              ) : (
                <span className="mt-px text-amber-300 flex-shrink-0 font-mono text-[10px] leading-none">●</span>
              )}
              <div className="flex-1 min-w-0">
                <span className="font-medium text-amber-900">{child.metric}</span>
                {child.sign === -1 && (
                  <span className="ml-0.5 text-[8px] text-red-400" title="Subtracts from parent">−</span>
                )}
                <span className={`ml-1.5 ${colorClass} font-medium`}>
                  {delta >= 0 ? '+' : ''}{Number(delta).toLocaleString()}
                </span>
                {child.rel_delta != null && (
                  <span className="ml-1 text-muted-foreground">({(child.rel_delta * 100).toFixed(1)}%)</span>
                )}
                {child.actual != null && child.base != null && (
                  <span className="ml-1.5 text-muted-foreground text-[9px]">
                    [{Number(child.actual).toLocaleString()} vs {Number(child.base).toLocaleString()}]
                  </span>
                )}
              </div>
            </div>
            {isOpen && hasKids && (
              <ExplTreeChildren nodes={child.children} depth={depth + 1} expandAllGen={expandAllGen} />
            )}
          </div>
        )
      })}
    </div>
  )
}

interface VisualContentProps {
  visual: VisualInfo
  data: unknown
  onChartClick?: (value: unknown, isMultiSelect: boolean, pointIndex?: number, columnOverride?: { table: string; column: string }) => void
  onPlotlyRightClick?: (pos: { x: number; y: number }, hoveredValue: unknown) => void
  selectedValues?: unknown[] | null
  selectedPointIndices?: number[] | null
  onMatrixExpand?: (rowPath: string[], expanded: boolean, ctx?: { blockIndex?: number }) => void
  onMatrixColExpand?: (colPath: string[], expanded: boolean, ctx?: { blockIndex?: number }) => void
  onMatrixCellClick?: (cell: TablixCell) => void
  onMatrixDrillAction?: (action: string, cellInfo: MatrixCellInfo) => void
  showSortEditor?: boolean
  setShowSortEditor?: (v: boolean | ((prev: boolean) => boolean)) => void
  onSortCountChange?: (count: number) => void
  onTooltipHover?: (mouseX: number, mouseY: number, value: unknown) => void
  onTooltipUnhover?: () => void
}

function collectUnsupportedVisualFieldLabels(value: unknown, labels: string[] = [], seen = new Set<string>()): string[] {
  if (labels.length >= 6 || value == null) return labels
  if (Array.isArray(value)) {
    for (const item of value) collectUnsupportedVisualFieldLabels(item, labels, seen)
    return labels
  }
  if (typeof value !== 'object') return labels

  const record = value as Record<string, unknown>
  const type = String(record.type || '')
  let label = ''
  if (type === 'ColumnRef') {
    label = `${String(record.table || '')}[${String(record.column || '')}]`
  } else if (type === 'MeasureRef') {
    label = String(record.table || '')
      ? `${String(record.table)}[${String(record.name || '')}]`
      : String(record.name || '')
  } else if (type === 'HierarchyRef' || type === 'ParamRef') {
    label = String(record.name || '')
  }
  if (label && !seen.has(label)) {
    seen.add(label)
    labels.push(label)
  }
  for (const nestedValue of Object.values(record)) {
    collectUnsupportedVisualFieldLabels(nestedValue, labels, seen)
  }
  return labels
}

function UnsupportedPowerBIVisual({ visual }: { visual: VisualInfo }) {
  const unsupported = visual.unsupported_visual || {}
  const blocked = visual.render_blocked || {}
  const sourceVisualType = String(unsupported.source_visual_type || visual.visual_type || 'Power BI visual')
  const sourceVisualId = String(unsupported.source_visual_id || visual.id)
  const reason = String(
    unsupported.unsupported_reason
    || blocked.message
    || 'Custom visual execution requires a compatible Power BI custom visual sandbox and capabilities runtime; the visual metadata is preserved but not executed.'
  )
  const preservedFields = collectUnsupportedVisualFieldLabels(visual.encodings)

  return (
    <div
      className="h-full w-full p-3 flex flex-col justify-center gap-2 text-xs text-muted-foreground bg-muted/20"
      data-testid="unsupported-visual-card"
    >
      <div className="flex items-center gap-2 text-foreground">
        <AlertTriangle className="h-4 w-4 text-amber-600 shrink-0" aria-hidden="true" />
        <div className="min-w-0">
          <div className="font-medium truncate" data-testid="unsupported-visual-type">
            {sourceVisualType}
          </div>
          <div className="text-[10px] text-muted-foreground truncate" data-testid="unsupported-visual-id">
            {sourceVisualId}
          </div>
        </div>
      </div>
      <div className="rounded border bg-background/70 p-2 leading-snug" data-testid="unsupported-visual-reason">
        {reason}
      </div>
      {preservedFields.length > 0 && (
        <div className="flex flex-wrap gap-1" data-testid="unsupported-visual-fields">
          {preservedFields.map((fieldLabel) => (
            <span key={fieldLabel} className="rounded border bg-background px-1.5 py-0.5 text-[10px] text-foreground">
              {fieldLabel}
            </span>
          ))}
        </div>
      )}
      <div className="text-[10px]" data-testid="unsupported-visual-status">
        {String(unsupported.preservation_status || 'preserve_only')}
      </div>
    </div>
  )
}

function VisualContent({ visual, data, onChartClick, onPlotlyRightClick, selectedValues, selectedPointIndices, onMatrixExpand, onMatrixColExpand, onMatrixCellClick, onMatrixDrillAction, showSortEditor: showSortEditorProp, setShowSortEditor: setShowSortEditorProp, onSortCountChange, onTooltipHover, onTooltipUnhover }: VisualContentProps) {
  const visualType = visual.visual_type?.toLowerCase() || 'unknown'
  const setDirty = useAppStore(s => s.setDirty)
  const updateVisualInStore = useReportStore(s => s.updateVisual)
  // sort_by_column lookup from model tables (for default sort substitution)
  const storeTables = useAppStore(s => s.tables)
  // Crossfilter: VisualContent is a top-level component, so it needs its own
  // useInteractions() call (the one in VisualCard is out of scope here).
  const { applyRowInteractionSelection, normalizeInteractions: normInteractions } = useInteractions()
  const interactions = useMemo(() => normInteractions(visual), [visual, normInteractions])
  // Track which explanation rows are expanded (by row index)
  const [expandedExplRows, setExpandedExplRows] = useState<Set<number>>(new Set())
  // Global expand/collapse generation counter for explanation tree
  // Positive = expand all, negative = collapse all
  const [explExpandAllGen, setExplExpandAllGen] = useState(0)
  // Narrative depth: which tree level appears in the written summary
  const [narrativeDepth, setNarrativeDepth] = useState<'children' | 'leaf' | 'all'>('children')
  // Table selection state: cell, row, or column
  const [tableSelection, setTableSelection] = useState<{
    type: 'cell' | 'row' | 'column'
    rowIndex?: number
    colName?: string
  } | null>(null)
  // Multi-column sort state (ordered list of sort specs)
  const [tableSortSpecs, setTableSortSpecs] = useState<Array<{ col: string; dir: 'asc' | 'desc' }>>([])
  // Sort editor visibility — use lifted props if available, else local fallback
  const [showSortEditorLocal, setShowSortEditorLocal] = useState(false)
  const showSortEditor = showSortEditorProp ?? showSortEditorLocal
  const setShowSortEditor = setShowSortEditorProp ?? setShowSortEditorLocal
  // Report sort count back to card header
  useEffect(() => {
    onSortCountChange?.(tableSortSpecs.length)
  }, [tableSortSpecs.length, onSortCountChange])
  // Column resize state for matrix visuals
  const [matrixColWidths, setMatrixColWidths] = useState<ColumnWidths>({})
  // Row resize state for matrix visuals
  const [matrixRowHeights, setMatrixRowHeights] = useState<Record<string, number>>({})

  // Band resize handler: updates band width/height in visual config
  const handleBandResize = useCallback((axis: 'row' | 'col', bandIndex: number, newSize: number) => {
    const tablix = (visual.encodings?.tablix || {}) as Record<string, unknown>
    const key = axis === 'row' ? 'rowHeaderBands' : 'colHeaderBands'
    const bands = Array.isArray(tablix[key]) ? [...(tablix[key] as Record<string, unknown>[])] : []
    if (bandIndex < bands.length) {
      const band = { ...bands[bandIndex] }
      band[axis === 'row' ? 'width' : 'height'] = newSize
      bands[bandIndex] = band
      const nextTablix = { ...tablix, [key]: bands }
      updateVisualInStore(visual.id, {
        encodings: { ...(visual.encodings || {}), tablix: nextTablix },
      })
    }
  }, [visual.id, visual.encodings, updateVisualInStore])

  // Pre-extract rows + columns for table/tablix sort — must call useMemo unconditionally.
  // For highlight dual-query responses, merge first so we get the highlight rows
  // (raw `data` has {baseline, highlight} — no top-level rows/columns).
  const preData = useMemo(() => {
    if (data && isHighlightResponse(data)) {
      return mergeHighlightResponse(visualType, data) as {
        rows?: Array<Record<string, unknown>>
        columns?: string[]
      }
    }
    return data as { rows?: Array<Record<string, unknown>>; columns?: string[] } | null
  }, [data, visualType])
  const preRows = preData?.rows || []
  const preCols = preData?.columns || []
  const sortedRowEntries = useMemo(() => {
    // Deterministic comparator used for both user-sort and default-stable-sort
    const compareRows = (a: Record<string, unknown>, b: Record<string, unknown>, specs: Array<{ col: string; dir: 'asc' | 'desc' }>) => {
      for (const spec of specs) {
        const va = a[spec.col]
        const vb = b[spec.col]
        if (va == null && vb == null) continue
        if (va == null) return 1
        if (vb == null) return -1
        let cmp = 0
        if (typeof va === 'number' && typeof vb === 'number') {
          cmp = va - vb
        } else {
          cmp = String(va).localeCompare(String(vb), undefined, { numeric: true, sensitivity: 'base' })
        }
        if (cmp !== 0) return spec.dir === 'asc' ? cmp : -cmp
      }
      return 0
    }
    const sorted = preRows.map((row, originalIndex) => ({ row, originalIndex }))
    if (tableSortSpecs.length > 0) {
      sorted.sort((a, b) => compareRows(a.row, b.row, tableSortSpecs))
    } else if (preCols.length > 0) {
      // Default stable sort: for columns that have sort_by_column set in the model,
      // substitute the sort column (e.g. "MonthName" sorts by "MonthNumber").
      // Build a flat sort_by_column lookup from all model tables.
      const sortByLookup: Record<string, string> = {}
      for (const t of storeTables) {
        if (t.sort_by_columns) {
          for (const [col, sbCol] of Object.entries(t.sort_by_columns)) {
            sortByLookup[col] = sbCol
          }
        }
      }
      const defaultSpecs = preCols.map(c => ({
        col: sortByLookup[c] && preCols.includes(sortByLookup[c]) ? sortByLookup[c] : c,
        dir: 'asc' as const
      }))
      sorted.sort((a, b) => compareRows(a.row, b.row, defaultSpecs))
    }
    return sorted
  }, [preRows, preCols, tableSortSpecs, storeTables])
  const sortedRows = useMemo(() => sortedRowEntries.map(e => e.row), [sortedRowEntries])

  if (visual.unsupported_visual) {
    return <UnsupportedPowerBIVisual visual={visual} />
  }

  // Static visuals render from static_content, no data needed
  if (isStaticVisualType(visualType)) {
    return (
      <StaticVisualContent
        visualType={visualType}
        staticContent={visual.static_content}
        staticAsset={visual.static_asset}
        staticResources={visual.static_resources}
      />
    )
  }

  // If no data yet, show placeholder
  if (!data) {
    return (
      <div className="flex items-center justify-center h-full text-muted-foreground">
        <span className="text-xs">Loading...</span>
      </div>
    )
  }

  // Handle highlight dual-query response: merge baseline + highlight into
  // a single figure that can be rendered by the normal chart pipeline.
  // Reuse preData (already merged in the useMemo above) to avoid double-merge.
  const effectiveData = preData ?? data

  const rawData = effectiveData as {
    columns?: string[]
    rows?: Array<Record<string, unknown>>
    plotly_data?: unknown[]
    plotly_layout?: Record<string, unknown>
    figure?: { data?: unknown[]; layout?: Record<string, unknown> }
    value?: unknown
    title?: string
    tablix_plan?: TablixPlan
    tablix?: TablixPlan
    _highlight_merged?: boolean
    _card_title?: string
  }

  // Map server-side Plotly figure (figure.data / figure.layout) to plotly_data / plotly_layout
  const renderData = {
    ...rawData,
    plotly_data: rawData.plotly_data ?? rawData.figure?.data,
    plotly_layout: rawData.plotly_layout ?? rawData.figure?.layout,
  }

  // Card visual (single value)
  if (visualType === 'card') {
    // When highlight-merged, show the merged title (e.g., "1234 (sel: 567)")
    if (rawData._highlight_merged && rawData._card_title) {
      // Safety: Plotly may serialise title as {text: "..."} — always render as string
      const cardTitle = typeof rawData._card_title === 'object'
        ? String((rawData._card_title as Record<string, unknown>).text ?? rawData._card_title)
        : String(rawData._card_title)
      return (
        <div className="flex flex-col items-center justify-center h-full p-4" data-testid="card-highlight">
          <span className="text-3xl font-bold">{cardTitle}</span>
        </div>
      )
    }
    // If multi-column data is available (e.g., AC + PY), use IBCSCard for rich KPI display
    const cardColumns = renderData.columns || []
    const cardRows = renderData.rows || []
    if (cardColumns.length >= 2 && cardRows.length >= 1) {
      const isDark = document.documentElement.classList.contains('dark')
      return <IBCSCard columns={cardColumns} rows={cardRows} isDark={isDark} />
    }
    const rawValue = renderData.rows?.[0] 
      ? Object.values(renderData.rows[0])[0] 
      : renderData.value ?? null
    const value = rawValue == null ? '–' : typeof rawValue === 'number' ? rawValue.toLocaleString() : String(rawValue)
    // Category label: visual title (measure name) preferred over SQL column alias
    const categoryLabel = visual.title || renderData.columns?.[0] || ''
    // PBI multiRowCard styling from format
    const barColor = (visual.format?.cardBarColor as string) || '#E66C37'
    const barWeight = (visual.format?.cardBarWeight as number) || 4
    const catFontSize = (visual.format?.cardCategoryFontSize as number) || 11
    const catColor = (visual.format?.cardCategoryColor as string) || '#707070'
    const dataColor = (visual.format?.cardValueColor as string) || undefined
    const dataFontSize = (visual.format?.cardDataLabelsFontSize as number) || 25
    const dataFontFamily = (visual.format?.cardDataLabelsFontFamily as string) || 'inherit'
    return (
      <div className="flex items-stretch h-full" data-testid="card-visual">
        {/* Accent bar */}
        <div style={{ width: barWeight, backgroundColor: barColor, flexShrink: 0 }} />
        <div className="flex flex-col justify-center px-3 py-2 min-w-0">
          <span style={{ fontSize: dataFontSize, fontFamily: dataFontFamily, color: dataColor, fontWeight: 600, lineHeight: 1.2 }}>
            {value}
          </span>
          {categoryLabel && (
            <span style={{ fontSize: catFontSize, color: catColor, marginTop: 2 }}>
              {categoryLabel}
            </span>
          )}
        </div>
      </div>
    )
  }

  // Table/Tablix visual
  if (visualType === 'table' || visualType === 'tablix') {
    const columns = renderData.columns || []
    // rows already sorted via sortedRows (useMemo above, before early returns)

    // Handle column header click for sorting
    const handleSortClick = (col: string, shiftKey: boolean) => {
      setTableSortSpecs(prev => {
        const idx = prev.findIndex(s => s.col === col)
        if (shiftKey) {
          // Shift+click: add/toggle column in multi-sort chain
          // Also open the sort editor to show what happened
          setShowSortEditor(true)
          if (idx >= 0) {
            const cur = prev[idx]
            if (cur.dir === 'asc') {
              // toggle to desc
              return [...prev.slice(0, idx), { col, dir: 'desc' as const }, ...prev.slice(idx + 1)]
            } else {
              // remove from sort (was desc, now unsort)
              return [...prev.slice(0, idx), ...prev.slice(idx + 1)]
            }
          }
          return [...prev, { col, dir: 'asc' as const }]
        } else {
          // Regular click: set as sole sort column
          if (idx >= 0 && prev.length === 1) {
            if (prev[0].dir === 'asc') return [{ col, dir: 'desc' as const }]
            return [] // was desc → clear sort
          }
          return [{ col, dir: 'asc' as const }]
        }
      })
    }

    // Helper to get sort indicator for a column
    const sortIndicator = (col: string) => {
      const idx = tableSortSpecs.findIndex(s => s.col === col)
      if (idx < 0) return null
      const arrow = tableSortSpecs[idx].dir === 'asc' ? '▲' : '▼'
      const num = tableSortSpecs.length > 1 ? `${idx + 1}` : ''
      return <span className="ml-1 text-[9px] text-primary/70">{arrow}{num}</span>
    }
    
    // Extract per-row explanation data to inject an Explanation column
    const explData = (effectiveData as { explanation?: {
      explanations?: Array<{
        per_row?: ExplNodeT[];
        nodes?: ExplNodeT[];
        error?: string;
      }>;
      comparator_label?: string;
      narrative_depth?: string;
    } })?.explanation
    const explRaw = explData?.explanations
    const comparatorLabel = explData?.comparator_label ?? 'budget'
    // per_row is the new per-row array; fall back to old nodes[0]-only format
    const perRowNodes: (ExplNodeT | null)[] | null = explRaw?.[0]?.per_row ?? null
    // Legacy fallback: if no per_row, use nodes[0] for row 0 only
    const legacyNode: ExplNodeT | null = (!perRowNodes ? explRaw?.[0]?.nodes?.[0] : null) ?? null
    const hasExplanation = (perRowNodes != null && perRowNodes.length > 0) || legacyNode != null
    
    return (
      <div className="h-full overflow-auto relative">
        {/* Sort editor floating popup - positioned below the card header */}
        {showSortEditor && (
          <div
            className="absolute top-1 right-1 z-50 w-64 bg-popover text-popover-foreground border rounded-lg shadow-lg"
            data-testid="sort-editor-popup"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between px-3 py-2 border-b">
              <span className="text-xs font-semibold">Sort Order</span>
              <div className="flex gap-1">
                {tableSortSpecs.length > 0 && (
                  <button
                    onClick={() => setTableSortSpecs([])}
                    className="text-[10px] px-1.5 py-0.5 rounded hover:bg-destructive/10 text-muted-foreground hover:text-destructive"
                  >
                    Clear all
                  </button>
                )}
                <button
                  onClick={() => setShowSortEditor(false)}
                  className="text-muted-foreground hover:text-foreground px-1"
                  title="Close"
                >✕</button>
              </div>
            </div>
            <div className="px-3 py-2 space-y-1.5 max-h-48 overflow-auto">
              {tableSortSpecs.length === 0 && (
                <p className="text-[10px] text-muted-foreground italic">No sort levels. Click a column header or add one below.</p>
              )}
              {tableSortSpecs.map((spec, idx) => (
                <div key={spec.col} className="flex items-center gap-1.5 group">
                  <span className="text-[9px] text-muted-foreground w-3 text-center font-mono">{idx + 1}</span>
                  <span className="text-[11px] font-medium flex-1 truncate">{spec.col}</span>
                  <select
                    value={spec.dir}
                    onChange={(e) => setTableSortSpecs(prev => prev.map((s, i) =>
                      i === idx ? { ...s, dir: e.target.value as 'asc' | 'desc' } : s
                    ))}
                    className="text-[10px] px-1 py-0.5 rounded border bg-background w-[90px]"
                  >
                    <option value="asc">A→Z / 0→9</option>
                    <option value="desc">Z→A / 9→0</option>
                  </select>
                  {idx > 0 && (
                    <button
                      onClick={() => setTableSortSpecs(prev => {
                        const next = [...prev]
                        ;[next[idx - 1], next[idx]] = [next[idx], next[idx - 1]]
                        return next
                      })}
                      className="text-[10px] px-0.5 rounded hover:bg-primary/10 opacity-0 group-hover:opacity-100"
                      title="Move up"
                    >↑</button>
                  )}
                  {idx < tableSortSpecs.length - 1 && (
                    <button
                      onClick={() => setTableSortSpecs(prev => {
                        const next = [...prev]
                        ;[next[idx], next[idx + 1]] = [next[idx + 1], next[idx]]
                        return next
                      })}
                      className="text-[10px] px-0.5 rounded hover:bg-primary/10 opacity-0 group-hover:opacity-100"
                      title="Move down"
                    >↓</button>
                  )}
                  <button
                    onClick={() => setTableSortSpecs(prev => prev.filter((_, i) => i !== idx))}
                    className="text-[10px] px-0.5 rounded hover:bg-destructive/10 text-muted-foreground hover:text-destructive opacity-0 group-hover:opacity-100"
                    title="Remove"
                  >✕</button>
                </div>
              ))}
            </div>
            {columns.filter(c => !tableSortSpecs.some(s => s.col === c)).length > 0 && (
              <div className="px-3 py-2 border-t">
                <select
                  value=""
                  onChange={(e) => {
                    if (e.target.value) {
                      setTableSortSpecs(prev => [...prev, { col: e.target.value, dir: 'asc' }])
                    }
                  }}
                  className="text-[10px] w-full px-1.5 py-1 rounded border bg-background text-muted-foreground"
                  data-testid="sort-editor-add-column"
                >
                  <option value="">+ Add sort level...</option>
                  {columns.filter(c => !tableSortSpecs.some(s => s.col === c)).map(c => (
                    <option key={c} value={c}>{c}</option>
                  ))}
                </select>
              </div>
            )}
          </div>
        )}
        <table className="w-full text-xs">
          <thead className="sticky top-0 bg-muted">
            <tr>
              {columns.map((col) => (
                <th
                  key={col}
                  className={cn(
                    'px-2 py-1 text-left font-medium border-b cursor-pointer select-none hover:bg-primary/10',
                    tableSelection?.type === 'column' && tableSelection.colName === col && 'bg-primary/20',
                    tableSortSpecs.some(s => s.col === col) && 'bg-primary/5',
                  )}
                  onClick={(e) => {
                    if (e.ctrlKey || e.metaKey) {
                      // Ctrl+click: select/deselect column (visual highlight)
                      e.stopPropagation()
                      setTableSelection(prev =>
                        prev?.type === 'column' && prev.colName === col ? null : { type: 'column', colName: col }
                      )
                    } else {
                      // Regular click or shift+click: sort
                      handleSortClick(col, e.shiftKey)
                    }
                  }}
                  title={`Click to sort · Shift+click to add sort level · Ctrl+click to select column`}
                >
                  {col}{sortIndicator(col)}
                </th>
              ))}
              {hasExplanation && (
                <th className="px-2 py-1 text-left font-medium border-b bg-amber-100 text-amber-900" data-testid="explanation-column-header">
                  <div className="flex items-center gap-2">
                    <span>💡 Explanation</span>
                    <select
                      value={narrativeDepth}
                      onChange={(e) => setNarrativeDepth(e.target.value as 'children' | 'leaf' | 'all')}
                      className="text-[9px] px-1 py-0.5 rounded border border-amber-300 bg-amber-50 text-amber-800 cursor-pointer"
                      title="Narrative detail level"
                      data-testid="narrative-depth-selector"
                    >
                      <option value="children">Summary</option>
                      <option value="leaf">Leaf Detail</option>
                      <option value="all">All Levels</option>
                    </select>
                    <div className="flex gap-1 ml-auto">
                      <button
                        onClick={() => {
                          setExpandedExplRows(new Set(sortedRows.slice(0, 20).map((_: unknown, i: number) => i)))
                          setExplExpandAllGen(prev => Math.abs(prev) + 1)
                        }}
                        className="px-1.5 py-0.5 text-[9px] rounded bg-amber-200 hover:bg-amber-300 text-amber-800 font-medium"
                        title="Expand all explanation trees"
                        data-testid="explanation-expand-all"
                      >
                        ⊞ All
                      </button>
                      <button
                        onClick={() => {
                          setExpandedExplRows(new Set())
                          setExplExpandAllGen(prev => -(Math.abs(prev) + 1))
                        }}
                        className="px-1.5 py-0.5 text-[9px] rounded bg-amber-200 hover:bg-amber-300 text-amber-800 font-medium"
                        title="Collapse all explanation trees"
                        data-testid="explanation-collapse-all"
                      >
                        ⊟ All
                      </button>
                    </div>
                  </div>
                </th>
              )}
            </tr>
          </thead>
          <tbody>
            {sortedRows.slice(0, 20).map((row, i) => {
              const isRowSelected = tableSelection?.type === 'row' && tableSelection.rowIndex === i
              return (
              <tr
                key={i}
                className={cn(
                  'hover:bg-muted/50',
                  'cursor-pointer',
                  isRowSelected && 'bg-primary/15 font-medium',
                )}
                onClick={() => {
                  // Row click is handled by individual cell clicks — nothing here
                }}
              >
                {columns.map((col) => {
                  const isCellSelected = tableSelection?.type === 'cell' && tableSelection.rowIndex === i && tableSelection.colName === col
                  const isColSelected = tableSelection?.type === 'column' && tableSelection.colName === col
                  // Faint row/col highlight when a cell is selected
                  const isCellInSelectedRow = tableSelection?.type === 'cell' && tableSelection.rowIndex === i
                  const isCellInSelectedCol = tableSelection?.type === 'cell' && tableSelection.colName === col
                  const isRowHighlight = isRowSelected || isCellInSelectedRow
                  const isColHighlight = isColSelected || isCellInSelectedCol
                  const dimmed = tableSelection != null && !isCellSelected && !isRowHighlight && !isColHighlight
                  return (
                  <td
                    key={col}
                    className={cn(
                      'px-2 py-1 border-b',
                      isCellSelected && 'bg-primary/20 font-semibold ring-1 ring-primary/40',
                      !isCellSelected && isColHighlight && isRowHighlight && 'bg-primary/10',
                      !isCellSelected && isColHighlight && !isRowHighlight && 'bg-primary/5',
                      !isCellSelected && !isColHighlight && isRowHighlight && 'bg-primary/5',
                      isColSelected && !isCellSelected && 'bg-primary/10',
                      dimmed && 'opacity-40',
                    )}
                    onClick={() => {
                      // Regular click: select cell (highlights cell + faint row/col)
                      setTableSelection(prev =>
                        prev?.type === 'cell' && prev.rowIndex === i && prev.colName === col
                          ? null
                          : { type: 'cell', rowIndex: i, colName: col }
                      )
                      // Fire crossfilter using ALL dimension (ColumnRef) columns
                      // from the clicked row. This sends multi-column interaction
                      // filters so other visuals can filter/highlight precisely.
                      if (interactions.affects_others) {
                        const encCols = (visual.encodings as Record<string, unknown>)?.columns
                        if (Array.isArray(encCols)) {
                          const columnValues: Array<{ column: { type: 'ColumnRef'; table: string; column: string }; value: unknown }> = []
                          for (const enc of encCols) {
                            const e = enc as Record<string, unknown>
                            if (!e || e.type !== 'ColumnRef') continue
                            const colName = String(e.column || '')
                            const tableName = String(e.table || '')
                            if (!colName || !tableName) continue
                            columnValues.push({
                              column: { type: 'ColumnRef', table: tableName, column: colName },
                              value: row[colName],
                            })
                          }
                          if (columnValues.length > 0) {
                            applyRowInteractionSelection(visual.id, columnValues)
                          }
                        }
                      }
                    }}
                  >
                    {formatCellValue(row[col])}
                  </td>
                  )
                })}
                {hasExplanation && (() => {
                  const originalRowIndex = sortedRowEntries[i]?.originalIndex ?? i
                  const rowNode = perRowNodes?.[originalRowIndex] ?? (i === 0 ? legacyNode : null)
                  const isExpanded = expandedExplRows.has(i)
                  const hasChildren = Array.isArray(rowNode?.children) && rowNode!.children.length > 0
                  const toggleExpand = (e: React.MouseEvent) => {
                    e.stopPropagation()
                    setExpandedExplRows(prev => {
                      const next = new Set(prev)
                      if (next.has(i)) next.delete(i); else next.add(i)
                      return next
                    })
                  }
                  return (
                  <td className="px-2 py-1 border-b bg-amber-50/50 text-xs align-top" data-testid={`explanation-cell-${i}`}>
                    {rowNode ? (
                      <div className="space-y-0.5">
                        {/* Narrative + expand toggle */}
                        <div className="flex items-start gap-1">
                          {hasChildren && (
                            <button
                              onClick={toggleExpand}
                              className="mt-0.5 text-amber-600 hover:text-amber-800 flex-shrink-0 font-mono text-[10px] leading-none"
                              title={isExpanded ? 'Collapse details' : 'Expand details'}
                            >
                              {isExpanded ? '▼' : '▶'}
                            </button>
                          )}
                          <div className="flex-1">
                            {rowNode.narrative && (
                              <div className={`text-amber-800 italic leading-snug whitespace-pre-line ${hasChildren ? 'cursor-pointer' : ''}`}
                                   onClick={hasChildren ? toggleExpand : undefined}>
                                {narrativeDepth === 'children'
                                  ? rowNode.narrative
                                  : generateNarrative(rowNode, narrativeDepth, comparatorLabel)}
                              </div>
                            )}
                          </div>
                        </div>
                        {/* Expanded sub-tree */}
                        {isExpanded && hasChildren && (
                          <ExplTreeChildren nodes={rowNode!.children} depth={1} expandAllGen={explExpandAllGen} />
                        )}
                      </div>
                    ) : <span className="text-muted-foreground">—</span>}
                  </td>
                  )
                })()}
              </tr>
              )
            })}
            {sortedRows.length > 20 && (
              <tr>
                <td colSpan={columns.length + (hasExplanation ? 1 : 0)} className="px-2 py-1 text-center text-muted-foreground">
                  ... and {sortedRows.length - 20} more rows
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    )
  }

  // Matrix visual - use TabixPlan if available, fallback to simple table
  if (visualType === 'matrix') {
    // Prefer tablix_plan (or tablix) for full matrix rendering
    const tablixData = renderData.tablix_plan ?? renderData.tablix
    if (tablixData) {
      // Extract design cell formats for data view styling
      const enc = visual.encodings as Record<string, unknown> | undefined
      const tlx = enc?.tablix as Record<string, unknown> | undefined
      const dc = tlx?.designCells as Record<string, import('./DesignCellEditor').CellFormat> | undefined
      // Phase 10.9: Extract explanation data from render response
      const explData = (renderData as Record<string, unknown>)?.explanation ?? null
      // Extract truncation info from query metadata (performance safety caps)
      const queryMeta = (renderData as Record<string, unknown>)?.query as Record<string, unknown> | undefined
      const truncInfo = (queryMeta?.truncated ?? ((renderData as Record<string, unknown>)?.matrix as Record<string, unknown>)?.truncated ?? null) as
        { rows?: boolean; cols?: boolean; max_rows?: number | null; max_cols?: number | null } | null
      return (
        <MatrixVisual
          data={tablixData}
          visualId={visual.id}
          truncationInfo={truncInfo}
          onExpand={onMatrixExpand}
          onColExpand={onMatrixColExpand}
          onCellClick={onMatrixCellClick}
          onDrillAction={onMatrixDrillAction}
          columnWidths={matrixColWidths}
          onColumnWidthsChange={setMatrixColWidths}
          rowHeights={matrixRowHeights}
          onRowHeightsChange={setMatrixRowHeights}
          onBandResize={handleBandResize}
          designCells={dc}
          explanationData={explData as any}
          rowHeaderOutlineStyle={getMatrixOutlineStyle(visual.table_matrix_format)}
          className="h-full"
        />
      )
    }
    
    // Fallback: simple table view from rows/columns
    const columns = renderData.columns || []
    const rows = renderData.rows || []
    
    return (
      <div className="h-full overflow-auto pointer-events-none" data-testid="matrix-visual-fallback">
        <table className="w-full text-xs pointer-events-auto">
          <thead className="sticky top-0 bg-muted">
            <tr>
              {columns.map((col) => (
                <th key={col} className="px-2 py-1 text-left font-medium border-b">
                  {col}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.slice(0, 20).map((row, i) => (
              <tr key={i} className="hover:bg-muted/50">
                {columns.map((col) => (
                  <td key={col} className="px-2 py-1 border-b">
                    {formatCellValue(row[col])}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    )
  }

  // Slicer visual
  if (visualType === 'slicer') {
    const columns = renderData.columns || []
    const rows = renderData.rows || []
    const valueCol = columns[0]
    
    return (
      <div className="h-full overflow-auto p-2">
        <div className="space-y-1">
          {rows.slice(0, 50).map((row, i) => (
            <div
              key={i}
              className="px-2 py-1 text-xs hover:bg-accent rounded cursor-pointer"
            >
              {formatCellValue(row[valueCol])}
            </div>
          ))}
        </div>
      </div>
    )
  }

  // IBCS Table visual
  if (visualType === 'ibcs_table') {
    const ibcsColumns = renderData.columns || []
    const ibcsRows = renderData.rows || []
    const isDark = document.documentElement.classList.contains('dark')
    return (
      <IBCSTable
        columns={ibcsColumns}
        rows={ibcsRows}
        isDark={isDark}
      />
    )
  }

  // IBCS Small Multiples
  if (visualType === 'small_multiples' || visualType === 'ibcs_small_multiples') {
    const smColumns = renderData.columns || []
    const smRows = renderData.rows || []
    const isDark = document.documentElement.classList.contains('dark')
    const enc = visual.encodings as Record<string, unknown> | undefined
    const groupByCol = (enc?.groupBy as string) || (visual.format?.groupByColumn as string) || smColumns[0] || ''
    const chartType = (enc?.chartType as string) || (visual.format?.smallMultiplesChartType as string) || 'bar'
    const maxCols = (visual.format?.smallMultiplesMaxColumns as number) || 3
    const syncScale = visual.format?.smallMultiplesSyncScale !== false
    return (
      <IBCSSmallMultiples
        columns={smColumns}
        rows={smRows}
        groupByColumn={groupByCol}
        chartType={chartType as 'bar' | 'line' | 'waterfall' | 'card'}
        isDark={isDark}
        maxColumns={maxCols}
        syncScale={syncScale}
        onCellClick={onChartClick ? (gv, v, multi) => onChartClick(v, multi) : undefined}
      />
    )
  }

  // IBCS SVG chart visuals
  if (['ibcs_bar', 'ibcs_column', 'ibcs_line', 'ibcs_card', 'ibcs_waterfall'].includes(visualType)) {
    const ibcsColumns = renderData.columns || []
    const ibcsRows = renderData.rows || []
    const isDark = document.documentElement.classList.contains('dark')

    if (visualType === 'ibcs_card') {
      const cardMainEncodings = (visual.encodings as Record<string, unknown> | undefined) || {}
      const cardGraphicColumns = Array.isArray((renderData as { graphic_columns?: unknown }).graphic_columns)
        ? ((renderData as { graphic_columns?: string[] }).graphic_columns || [])
        : []
      const cardGraphicRows = Array.isArray((renderData as { graphic_rows?: unknown }).graphic_rows)
        ? ((renderData as { graphic_rows?: Array<Record<string, unknown>> }).graphic_rows || [])
        : []
      const cardDecisionOverlays = Array.isArray((renderData as { decision_overlays?: unknown }).decision_overlays)
        ? (((renderData as { decision_overlays?: unknown[] }).decision_overlays) || [])
        : undefined
      const cardPackSummary = ((): Record<string, unknown> | null => {
        const candidate = (renderData as { pack_summary?: unknown }).pack_summary
        return candidate && typeof candidate === 'object' && !Array.isArray(candidate)
          ? (candidate as Record<string, unknown>)
          : null
      })()
      const cardOverlayMeta = ((): Record<string, unknown> | null => {
        const candidate = (renderData as { overlay_meta?: unknown }).overlay_meta
        return candidate && typeof candidate === 'object' && !Array.isArray(candidate)
          ? (candidate as Record<string, unknown>)
          : null
      })()
      const cardShowGraphic = visual.format?.ibcsCardShowGraphic === true
      const rawCardGraphicSourceType = (visual.format?.ibcsCardGraphicSourceType as string | undefined) || 'custom'
      const cardGraphicSourceType: 'custom' | 'generated' = rawCardGraphicSourceType === 'generated' ? 'generated' : 'custom'
      const cardGraphicPosition = (visual.format?.ibcsCardGraphicPosition as 'top' | 'right' | 'bottom' | 'left' | undefined) || 'bottom'
      const cardDiPosition = (visual.format?.ibcsCardDiPosition as 'top' | 'right' | 'bottom' | 'left' | undefined) || 'bottom'
      const cardEduPosition = (visual.format?.ibcsCardEduPosition as 'top' | 'right' | 'bottom' | 'left' | 'inline' | undefined) || 'inline'
      const cardShowEduSummary = visual.format?.ibcsCardShowEduSummary !== false
      const cardShowSignals = visual.format?.ibcsCardShowSignals !== false
      const cardEduSummary = (() => {
        const candidate = (renderData as { edu_summary?: unknown }).edu_summary
        return Array.isArray(candidate) ? candidate as Array<{ comparator: string; drivers: Array<{ label: string; delta: number; relDelta?: number }> }> : undefined
      })()
      const cardGraphicSvg = (visual.format?.ibcsCardGraphicSvg as string | undefined) || ''
      const cardGraphicGeneratedType = (visual.format?.ibcsCardGraphicGeneratedType as 'ibcs_bar' | 'ibcs_line' | 'ibcs_waterfall' | undefined) || 'ibcs_bar'
      const cardGraphicCategoryLabel = (visual.format?.ibcsCardGraphicCategoryLabel as string | undefined) || ''
      const cardGraphicEncodingCategory = ((visual.format?.ibcsCardGraphicEncodingCategory as Record<string, unknown> | null | undefined) || (cardMainEncodings.category as Record<string, unknown> | undefined) || null)
      const cardGraphicEncodingAC = ((visual.format?.ibcsCardGraphicEncodingAC as Record<string, unknown> | null | undefined) || (cardMainEncodings.ac as Record<string, unknown> | undefined) || null)
      const cardGraphicEncodingPY = ((visual.format?.ibcsCardGraphicEncodingPY as Record<string, unknown> | null | undefined) || (cardMainEncodings.py as Record<string, unknown> | undefined) || null)
      const cardGraphicEncodingPL = ((visual.format?.ibcsCardGraphicEncodingPL as Record<string, unknown> | null | undefined) || (cardMainEncodings.pl as Record<string, unknown> | undefined) || null)
      const cardGraphicEncodingFC = ((visual.format?.ibcsCardGraphicEncodingFC as Record<string, unknown> | null | undefined) || (cardMainEncodings.fc as Record<string, unknown> | undefined) || null)
      const cardGraphicGeneratedOrientation = (visual.format?.ibcsCardGraphicGeneratedOrientation as 'horizontal' | 'vertical' | undefined) || 'horizontal'
      const cardGraphicGeneratedScenario = (visual.format?.ibcsCardGraphicGeneratedScenario as 'ac' | 'py' | 'pl' | 'fc' | undefined) || 'ac'
      const cardGraphicGeneratedShowTotals = visual.format?.ibcsCardGraphicGeneratedShowTotals !== false
      const cardGraphicIbcsMainChartMode = (visual.format?.ibcsCardGraphicIbcsMainChartMode as 'comparison' | 'waterfall' | undefined) || 'comparison'
      const cardGraphicIbcsLabelPosition = (visual.format?.ibcsCardGraphicIbcsLabelPosition as 'top-inside' | 'top-outside' | 'middle' | 'bottom' | undefined) || 'top-inside'
      const cardGraphicIbcsFontSize = (visual.format?.ibcsCardGraphicIbcsFontSize as number | undefined) || undefined
      const cardGraphicIbcsDataLabelFontSize = (visual.format?.ibcsCardGraphicIbcsDataLabelFontSize as number | undefined) || undefined
      const cardGraphicIbcsFontFamily = (visual.format?.ibcsCardGraphicIbcsFontFamily as string | undefined) || undefined
      const cardGraphicIbcsXAxisRotation = visual.format?.ibcsCardGraphicIbcsXAxisRotation != null ? (visual.format.ibcsCardGraphicIbcsXAxisRotation as number) : undefined
      const cardGraphicIbcsShowVariancePanels = visual.format?.ibcsCardGraphicIbcsShowVariancePanels as boolean | undefined
      const cardGraphicIbcsWaterfallShowConnectors = visual.format?.ibcsCardGraphicIbcsWaterfallShowConnectors as boolean | undefined
      const cardGraphicIbcsCanvasPaddingH = (visual.format?.ibcsCardGraphicIbcsCanvasPaddingH as number | undefined) ?? undefined
      const cardGraphicIbcsCanvasPaddingV = (visual.format?.ibcsCardGraphicIbcsCanvasPaddingV as number | undefined) ?? undefined
      const handleCardGraphicEditorRequest = () => {
        updateVisualInStore(visual.id, {
          format: {
            ...(visual.format || {}),
            ibcsCardShowGraphic: true,
            ibcsCardGraphicSourceType: 'generated',
            ibcsCardGraphicEditorOpen: true,
          },
        })
        setDirty(true)
      }
      return (
        <>
        <IBCSCard
          columns={ibcsColumns}
          rows={ibcsRows}
          decisionOverlays={cardDecisionOverlays}
          packSummary={cardPackSummary}
          overlayMeta={cardOverlayMeta}
          graphicColumns={cardGraphicColumns}
          graphicRows={cardGraphicRows}
          isDark={isDark}
          showGraphic={cardShowGraphic}
          graphicSourceType={cardGraphicSourceType}
          graphicPosition={cardGraphicPosition}
          diPosition={cardDiPosition}
          eduPosition={cardEduPosition}
          showEduSummary={cardShowEduSummary}
          showSignals={cardShowSignals}
          eduSummary={cardEduSummary}
          graphicSvg={cardGraphicSvg}
          graphicGeneratedType={cardGraphicGeneratedType}
          graphicCategoryLabel={cardGraphicCategoryLabel}
          graphicEncodingCategory={cardGraphicEncodingCategory}
          graphicEncodingAC={cardGraphicEncodingAC}
          graphicEncodingPY={cardGraphicEncodingPY}
          graphicEncodingPL={cardGraphicEncodingPL}
          graphicEncodingFC={cardGraphicEncodingFC}
          graphicGeneratedOrientation={cardGraphicGeneratedOrientation}
          graphicGeneratedScenario={cardGraphicGeneratedScenario}
          graphicGeneratedShowTotals={cardGraphicGeneratedShowTotals}
          graphicIbcsMainChartMode={cardGraphicIbcsMainChartMode}
          graphicIbcsLabelPosition={cardGraphicIbcsLabelPosition}
          graphicIbcsFontSize={cardGraphicIbcsFontSize}
          graphicIbcsDataLabelFontSize={cardGraphicIbcsDataLabelFontSize}
          graphicIbcsFontFamily={cardGraphicIbcsFontFamily}
          graphicIbcsXAxisRotation={cardGraphicIbcsXAxisRotation}
          graphicIbcsShowVariancePanels={cardGraphicIbcsShowVariancePanels}
          graphicIbcsWaterfallShowConnectors={cardGraphicIbcsWaterfallShowConnectors}
          graphicIbcsCanvasPaddingH={cardGraphicIbcsCanvasPaddingH}
          graphicIbcsCanvasPaddingV={cardGraphicIbcsCanvasPaddingV}
          onGraphicEditorRequest={handleCardGraphicEditorRequest}
        />
      </>
      )
    }
    if (visualType === 'ibcs_waterfall') {
      const ibcsFontSize = (visual.format?.ibcsFontSize as number) || undefined
      const ibcsDataLabelFontSize = (visual.format?.ibcsDataLabelFontSize as number) || undefined
      const ibcsFontFamily = (visual.format?.ibcsFontFamily as string) || undefined
      const ibcsXAxisRotation = visual.format?.ibcsXAxisRotation != null ? (visual.format.ibcsXAxisRotation as number) : undefined
      const wfShowTotals = visual.format?.ibcsWaterfallShowTotals as boolean | undefined
      const wfScenario = (visual.format?.ibcsWaterfallScenario as 'ac' | 'py' | 'pl' | 'fc' | undefined) || 'ac'
      const wfShowConnectors = visual.format?.ibcsWaterfallShowConnectors as boolean | undefined
      const wfAllowSubtotalToggle = visual.format?.ibcsWaterfallAllowSubtotalToggle as boolean | undefined
      const wfSubtotalLabelsRaw = (visual.format?.ibcsWaterfallSubtotalLabels as string | undefined) || ''
      const wfSubtotalLabels = wfSubtotalLabelsRaw
        .split(',')
        .map((s) => s.trim())
        .filter((s) => s.length > 0)
      const wfEncodingMap = (visual.encodings || {}) as Record<string, unknown>
      const wfScenarioMeasureName = (wfEncodingMap[wfScenario] as { name?: string } | undefined)?.name
      const wfValueColumnName = wfScenarioMeasureName && ibcsColumns.includes(wfScenarioMeasureName)
        ? wfScenarioMeasureName
        : undefined
      return (
        <IBCSWaterfall
          columns={ibcsColumns}
          rows={ibcsRows}
          isDark={isDark}
          showTotals={wfShowTotals !== false}
          scenario={wfScenario}
          valueColumnName={wfValueColumnName}
          showConnectors={wfShowConnectors !== false}
          allowSubtotalToggle={wfAllowSubtotalToggle === true}
          subtotalLabels={wfSubtotalLabels}
          fontSize={ibcsFontSize}
          dataLabelFontSize={ibcsDataLabelFontSize}
          fontFamily={ibcsFontFamily}
          xAxisRotation={ibcsXAxisRotation}
          onBarClick={onChartClick ? (value, isMulti) => onChartClick(value, isMulti) : undefined}
        />
      )
    }
    if (visualType === 'ibcs_line') {
      return (
        <IBCSLineChart
          columns={ibcsColumns}
          rows={ibcsRows}
          isDark={isDark}
          onPointClick={onChartClick ? (value, isMulti) => onChartClick(value, isMulti) : undefined}
        />
      )
    }
    // ibcs_bar (horizontal) or ibcs_column (vertical)
    const ibcsOrientation = (visual.format?.ibcsOrientation as string) || (visualType === 'ibcs_column' ? 'vertical' : 'horizontal')
    const ibcsLabelPos = (visual.format?.ibcsLabelPosition as string) || 'top-inside'
    const ibcsFontSize = (visual.format?.ibcsFontSize as number) || undefined
    const ibcsDataLabelFontSize = (visual.format?.ibcsDataLabelFontSize as number) || undefined
    const ibcsFontFamily = (visual.format?.ibcsFontFamily as string) || undefined
    const ibcsXAxisRotation = visual.format?.ibcsXAxisRotation != null ? (visual.format.ibcsXAxisRotation as number) : undefined
    const ibcsCanvasPaddingH = (visual.format?.ibcsCanvasPaddingH as number) ?? undefined
    const ibcsCanvasPaddingV = (visual.format?.ibcsCanvasPaddingV as number) ?? undefined
    const ibcsShowVariancePanels = visual.format?.ibcsShowVariancePanels as boolean | undefined
    const ibcsMainChartMode = (visual.format?.ibcsMainChartMode as 'comparison' | 'waterfall' | undefined) || 'comparison'
    const handleIBCSMainModeChange = (mode: 'comparison' | 'waterfall') => {
      updateVisualInStore(visual.id, {
        format: { ...(visual.format || {}), ibcsMainChartMode: mode },
      })
      setDirty(true)
    }
    return (
      <IBCSBarChart
        columns={ibcsColumns}
        rows={ibcsRows}
        orientation={ibcsOrientation as 'horizontal' | 'vertical'}
        labelPosition={ibcsLabelPos as 'top-inside' | 'top-outside' | 'middle' | 'bottom'}
        fontSize={ibcsFontSize}
        dataLabelFontSize={ibcsDataLabelFontSize}
        fontFamily={ibcsFontFamily}
        xAxisRotation={ibcsXAxisRotation}
        canvasPaddingH={ibcsCanvasPaddingH}
        canvasPaddingV={ibcsCanvasPaddingV}
        showVariancePanels={ibcsShowVariancePanels}
        mainChartMode={ibcsMainChartMode}
        onMainChartModeChange={handleIBCSMainModeChange}
        isDark={isDark}
        onBarClick={onChartClick ? (value, isMulti) => onChartClick(value, isMulti) : undefined}
      />
    )
  }

  // Route generic 'line' to IBCSLineChart when ibcsMode format flag is set
  if (visualType === 'line' && visual.format?.ibcsMode) {
    const ibcsColumns = renderData.columns || []
    const ibcsRows = renderData.rows || []
    const isDark = document.documentElement.classList.contains('dark')
    return (
      <IBCSLineChart
        columns={ibcsColumns}
        rows={ibcsRows}
        isDark={isDark}
        onPointClick={onChartClick ? (value, isMulti) => onChartClick(value, isMulti) : undefined}
      />
    )
  }

  // All Plotly-rendered visual types (plotly_express + graph_objects)
  const PLOTLY_TYPES = new Set([
    'bar', 'column', 'line', 'scatter', 'area', 'pie', 'combo',
    'histogram', 'box', 'violin', 'strip', 'ecdf',
    'funnel', 'funnel_area',
    'density_contour', 'density_heatmap',
    'treemap', 'sunburst', 'icicle',
    'scatter_polar', 'line_polar', 'bar_polar',
    'bubble', 'bubble_3d', 'scatter_3d', 'line_3d',
    'candlestick', 'ohlc', 'waterfall', 'gauge', 'sankey',
  ])

  // Chart visuals - use Plotly if data available
  if (PLOTLY_TYPES.has(visualType)) {
    // When the server returned a highlight response that was already merged
    // (baseline + overlay traces), skip client-side opacity to avoid double-dimming.
    const isHighlightMerged = !!(renderData as Record<string, unknown>)._highlight_merged
    const chartSelectedValues = isHighlightMerged ? null : selectedValues
    const chartSelectedPoints = isHighlightMerged ? null : selectedPointIndices

    // Backend may provide plotly_data directly
    if (renderData.plotly_data && renderData.plotly_data.length > 0) {
      return (
        <Suspense fallback={<ChartLoadingPlaceholder />}>
          <PlotlyChart 
            data={renderData.plotly_data} 
            layout={renderData.plotly_layout}
            onChartClick={onChartClick}
            onRightClick={onPlotlyRightClick}
            selectedValues={chartSelectedValues}
            selectedPointIndices={chartSelectedPoints}
            onTooltipHover={onTooltipHover}
            onTooltipUnhover={onTooltipUnhover}
          />
        </Suspense>
      )
    }
    
    // Generate simple chart from rows/columns
    if (renderData.rows && renderData.columns && renderData.columns.length >= 2) {
      return (
        <Suspense fallback={<ChartLoadingPlaceholder />}>
          <SimpleChart 
            visualType={visualType}
            columns={renderData.columns}
            rows={renderData.rows}
            onChartClick={onChartClick}
            onRightClick={onPlotlyRightClick}
            selectedValues={chartSelectedValues}
            selectedPointIndices={chartSelectedPoints}
            onTooltipHover={onTooltipHover}
            onTooltipUnhover={onTooltipUnhover}
          />
        </Suspense>
      )
    }

    // Fallback placeholder
    return (
      <div className="flex flex-col items-center justify-center h-full text-muted-foreground p-4">
        <span className="text-xs">{visualType} chart</span>
        <span className="text-[10px] mt-1">No data to render</span>
      </div>
    )
  }

  // Unknown visual type - show raw data info
  return (
    <div className="flex flex-col items-center justify-center h-full text-muted-foreground p-4">
      <span className="text-xs">{visualType}</span>
      {renderData.columns && (
        <span className="text-[10px] mt-1">{renderData.columns.length} columns</span>
      )}
      {renderData.rows && (
        <span className="text-[10px]">{renderData.rows.length} rows</span>
      )}
    </div>
  )
}

// Loading placeholder for charts
function ChartLoadingPlaceholder() {
  return (
    <div className="flex items-center justify-center h-full">
      <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
    </div>
  )
}

// Plotly chart wrapper when backend provides plotly_data
interface PlotlyChartProps {
  data: unknown[]
  layout?: Record<string, unknown>
  onChartClick?: (value: unknown, isMultiSelect: boolean, pointIndex?: number) => void
  onRightClick?: (pos: { x: number; y: number }, hoveredValue: unknown) => void
  selectedValues?: unknown[] | null
  selectedPointIndices?: number[] | null
  /** Tooltip page hover: fires with mouse position + extracted value */
  onTooltipHover?: (mouseX: number, mouseY: number, value: unknown) => void
  onTooltipUnhover?: () => void
}

function PlotlyChart({ data, layout, onChartClick, onRightClick, selectedValues, selectedPointIndices, onTooltipHover, onTooltipUnhover }: PlotlyChartProps) {
  const { effectiveTheme } = useTheme()
  const isDark = effectiveTheme === 'dark'
  const themeChart = useThemeStore((s) => s.reportingTheme.chart)
  const themeFont = useThemeStore((s) => s.reportingTheme.font)
  const dataColors = useThemeStore((s) => s.reportingTheme.dataColors)

  // Track the currently hovered data point value for right-click drill
  const hoveredValueRef = useRef<unknown>(null)

  // Use a ref to always read the latest callback.  react-plotly-js's
  // shouldComponentUpdate only checks data/layout/config — when only the
  // onClick prop changes (e.g. after a crossfilter toggle) the component
  // skips the update and the old handler persists.  The ref ensures the
  // stable handler below always calls the current callback, so a second
  // click on the same datapoint correctly toggles the selection off.
  const onChartClickRef = useRef(onChartClick)
  onChartClickRef.current = onChartClick

  // Apply theme data colors to traces + opacity-based highlighting
  // If the server provided an explicit colorway (user-chosen palette from format panel),
  // use those colors instead of the theme's dataColors.
  const serverColorway = layout?.colorway as string[] | undefined
  const effectiveColors = serverColorway && serverColorway.length > 0 ? serverColorway : dataColors
  const themedData = useMemo(() => {
    const selSet = selectedValues && selectedValues.length > 0
      ? new Set(selectedValues.map(v => String(v)))
      : null
    // Point-index set for scatter-level highlighting (single data point)
    const selPtSet = selectedPointIndices && selectedPointIndices.length > 0
      ? new Set(selectedPointIndices)
      : null

    return (data as Plotly.Data[]).map((trace, i) => {
      const raw = trace as Record<string, unknown>
      const markerRaw = typeof raw.marker === 'object' && raw.marker !== null ? raw.marker as Record<string, unknown> : {}
      // Apply effective colors (theme dataColors or user-chosen palette)
      const traceColor = effectiveColors[i % effectiveColors.length]

      // Also override line.color for scatter/line traces and ensure minimum width
      const lineRaw = typeof raw.line === 'object' && raw.line !== null ? raw.line as Record<string, unknown> : undefined
      const isLineType = raw.type === 'scatter' || raw.type === 'scattergl'
      const lineWidth = lineRaw ? Math.max(Number(lineRaw.width) || 2.5, 2.5) : 2.5
      // Preserve gradient coloring: if the server set marker.colorscale (gradient),
      // keep the original marker.color (numeric array) instead of overriding with theme color.
      const hasColorscale = Boolean(markerRaw.colorscale)
      const lineHasColorscale = lineRaw && Boolean((lineRaw as Record<string, unknown>).colorscale)
      const themed: Record<string, unknown> = {
        ...raw,
        marker: { ...markerRaw, ...(hasColorscale ? {} : { color: traceColor }) },
        ...(lineRaw || isLineType ? { line: { ...(lineRaw ?? {}), ...(lineHasColorscale ? {} : { color: traceColor }), width: lineWidth } } : {}),
      }

      // Apply per-point marker.opacity to dim unselected points.
      // Strategy:
      //  1. If selSet matches a trace NAME (legend entry) → trace-level selection
      //     (matching traces fully opaque, non-matching traces dimmed)
      //  2. If selSet matches x-values / categories → per-point selection
      //  3. If selSet matches NOTHING on this trace type → skip (no dimming)
      if (selSet) {
        const isScatterType = raw.type === 'scatter' || raw.type === 'scattergl'
        const modeStr = String(raw.mode ?? '')
        const isLineTrace = isScatterType && (modeStr.includes('lines') || !modeStr)
        const isBarType = raw.type === 'bar'
        const isHBar = isBarType && raw.orientation === 'h'
        const traceName = String(raw.name ?? '')
        const catArr = Array.isArray(raw.labels) ? raw.labels
          : isHBar && Array.isArray(raw.y) ? raw.y
          : Array.isArray(raw.x) ? raw.x
          : null
        if (catArr) {
          // Check if selSet matches any trace name across ALL traces
          // (trace-level selection: e.g., clicking "Clothing" should highlight
          //  the entire Clothing trace, not try to match dates on x-axis)
          const allTraceNames = (data as Plotly.Data[]).map(t => String((t as Record<string, unknown>).name ?? ''))
          const hasTraceNameMatch = allTraceNames.some(n => n && selSet.has(n))
          // Also check if selSet matches any x-value across ALL traces
          const hasXValueMatch = (data as Plotly.Data[]).some(t => {
            const tr = t as Record<string, unknown>
            const xArr = Array.isArray(tr.labels) ? tr.labels
              : (tr.type === 'bar' && tr.orientation === 'h' && Array.isArray(tr.y)) ? tr.y
              : Array.isArray(tr.x) ? tr.x : null
            return xArr?.some((v: unknown) => selSet.has(String(v)))
          })

          let opacities: number[] | null = null

          if (hasTraceNameMatch && !hasXValueMatch) {
            // Trace-level selection: entire trace on or off based on name
            const traceMatches = traceName && selSet.has(traceName)
            opacities = new Array(catArr.length).fill(traceMatches ? 1.0 : 0.3)
          } else if (hasXValueMatch) {
            // Per-point selection by x-value / category
            opacities = new Array(catArr.length)
            if (isLineTrace) {
              for (let j = 0; j < catArr.length; j++) {
                opacities[j] = selSet.has(String(catArr[j])) ? 1.0 : 0.3
              }
            } else if (isScatterType && selPtSet) {
              for (let j = 0; j < catArr.length; j++) {
                opacities[j] = selPtSet.has(j) ? 1.0 : 0.3
              }
            } else {
              for (let j = 0; j < catArr.length; j++) {
                opacities[j] = selSet.has(String(catArr[j])) ? 1.0 : 0.3
              }
            }
          }
          // else: selSet matches nothing on this chart → skip highlighting entirely

          if (opacities) {
            const markerUpdate: Record<string, unknown> = { ...(themed.marker as Record<string, unknown>), opacity: opacities }
            // Only add per-point sizes for scatter/line (NOT bars — marker.size distorts bar rendering)
            if (isScatterType) {
              const baseSize = typeof markerRaw.size === 'number' ? markerRaw.size : 6
              markerUpdate.size = opacities.map(o => o >= 1.0 ? baseSize * 2.5 : baseSize)
            }
            themed.marker = markerUpdate
            // For line/area traces: force markers visible so selected points show.
            if (isScatterType && !modeStr.includes('markers')) {
              themed.mode = modeStr ? modeStr + '+markers' : 'lines+markers'
            }
          }
        }
      }

      return themed as Plotly.Data
    })
  }, [data, effectiveColors, selectedValues, selectedPointIndices])

  const plotLayout = useMemo(() => {
    const fontColor = isDark ? '#e0e4ec' : (themeFont.colorBody || '#1e293b')
    const gridColor = isDark ? 'rgba(255,255,255,0.08)' : (themeChart.gridlineColor || 'rgba(0,0,0,0.06)')
    const axisColor = isDark ? 'rgba(255,255,255,0.15)' : (themeChart.axisColor || gridColor)
    const plotBg = themeChart.plotBackground || 'transparent'
    const fontSize = themeFont.sizeBody || 10

    // Lock category axis order to prevent reordering on click.
    // Extract unique categories from the first trace's x (or y for h-bar).
    const firstTrace = (data as Plotly.Data[])?.[0] as Record<string, unknown> | undefined
    const isHBar = firstTrace?.type === 'bar' && firstTrace?.orientation === 'h'
    const catSrc = isHBar
      ? (Array.isArray(firstTrace?.y) ? firstTrace!.y as unknown[] : null)
      : (Array.isArray(firstTrace?.x) ? firstTrace!.x as unknown[] : null)
    // Preserve order of first occurrence (do not sort — keeps server order)
    const catArray = catSrc ? [...new Map(catSrc.map((v, i) => [String(v), i])).keys()] : null

    const xAxisExtra = layout?.xaxis as Record<string, unknown> ?? {}
    const yAxisExtra = layout?.yaxis as Record<string, unknown> ?? {}

    return {
      autosize: true,
      margin: { l: 40, r: 20, t: 30, b: 40 },
      paper_bgcolor: 'transparent',
      plot_bgcolor: plotBg,
      font: { size: fontSize, color: fontColor, ...(themeFont.family ? { family: themeFont.family } : {}) },
      colorway: effectiveColors,
      xaxis: {
        gridcolor: themeChart.showGridlines ? gridColor : 'transparent',
        zerolinecolor: axisColor,
        ...xAxisExtra,
        // Lock category order LAST so nothing can override it
        ...(catArray && !isHBar ? { categoryorder: 'array' as const, categoryarray: catArray } : {}),
      },
      yaxis: {
        gridcolor: themeChart.showGridlines ? gridColor : 'transparent',
        zerolinecolor: axisColor,
        ...yAxisExtra,
        // Lock category order LAST so nothing can override it
        ...(catArray && isHBar ? { categoryorder: 'array' as const, categoryarray: catArray } : {}),
      },
      legend: { font: { color: fontColor }, ...(layout?.legend as Record<string, unknown> ?? {}) },
      // Dark mode: override hoverlabel to use dark background instead of white
      hoverlabel: isDark
        ? { bgcolor: '#1a1a2e', font: { color: '#e0e4ec' }, bordercolor: 'rgba(255,255,255,0.15)', ...(layout?.hoverlabel as Record<string, unknown> ?? {}) }
        : (layout?.hoverlabel as Record<string, unknown> ?? {}),
      // Merge remaining layout props WITHOUT clobbering xaxis/yaxis (they have categoryorder)
      ...Object.fromEntries(
        Object.entries(layout ?? {}).filter(([k]) => !['xaxis', 'yaxis', 'font', 'legend', 'hoverlabel'].includes(k))
      ),
      // Re-apply theme colors after user layout (theme wins for bg/font base)
      ...(layout?.font ? {} : { font: { size: fontSize, color: fontColor, ...(themeFont.family ? { family: themeFont.family } : {}) } }),
    }
  }, [data, layout, isDark, themeChart, themeFont, dataColors])

  // Stable handler — never changes reference, reads latest callback from ref.
  const handlePlotlyClick = useCallback((event: Plotly.PlotMouseEvent) => {
    const cb = onChartClickRef.current
    if (!cb || !event.points || event.points.length === 0) return
    
    const point = event.points[0] as Plotly.PlotDatum & { label?: string }
    const pointAny = point as unknown as Record<string, unknown>
    // Extract the categorical value from the clicked point.
    // - Pie / treemap / sunburst / icicle / funnel_area: use label
    // - Horizontal bars have categories on y axis, so use point.y
    // - Polar charts: use theta (angular dimension)
    // - Default (vertical bar, scatter, etc.) use point.x
    const trace = (data as Plotly.Data[])?.[point.curveNumber ?? 0]
    const isHorizontalBar = trace && (trace as Record<string, unknown>).type === 'bar' && (trace as Record<string, unknown>).orientation === 'h'
    let value: unknown
    if (point.label !== undefined) {
      value = point.label  // pie, treemap, sunburst, icicle, funnel_area
    } else if (pointAny.theta !== undefined) {
      value = pointAny.theta  // polar charts
    } else if (isHorizontalBar) {
      value = point.y      // horizontal bar: categories on y
    } else {
      value = point.x !== undefined ? point.x : point.y
    }
    
    if (value === undefined || value === null) return
    
    // Check if Ctrl/Cmd key was held for multi-select
    const isMultiSelect = !!(event.event && (event.event.ctrlKey || event.event.metaKey))
    
    // Pass the point index for scatter-level single-point selection
    const ptIndex = point.pointIndex ?? point.pointNumber
    cb(value, isMultiSelect, ptIndex)
  }, [data])  // depends on data to read trace orientation

  // Track hovered data point for right-click context menu + tooltip pages
  const onTooltipHoverRef = useRef(onTooltipHover)
  onTooltipHoverRef.current = onTooltipHover
  const onTooltipUnhoverRef = useRef(onTooltipUnhover)
  onTooltipUnhoverRef.current = onTooltipUnhover

  const handlePlotlyHover = useCallback((event: Plotly.PlotHoverEvent) => {
    if (!event.points || event.points.length === 0) {
      hoveredValueRef.current = null
      return
    }
    const point = event.points[0] as Plotly.PlotDatum & { label?: string }
    const pointAny = point as unknown as Record<string, unknown>
    const trace = (data as Plotly.Data[])?.[point.curveNumber ?? 0]
    const isHBar = trace && (trace as Record<string, unknown>).type === 'bar' && (trace as Record<string, unknown>).orientation === 'h'
    if (point.label !== undefined) {
      hoveredValueRef.current = point.label
    } else if (pointAny.theta !== undefined) {
      hoveredValueRef.current = pointAny.theta
    } else if (isHBar) {
      hoveredValueRef.current = point.y
    } else {
      hoveredValueRef.current = point.x !== undefined ? point.x : point.y
    }
    // Notify tooltip page popup with mouse position from the native event
    if (onTooltipHoverRef.current && hoveredValueRef.current != null) {
      const nativeEvt = (event as unknown as { event?: MouseEvent }).event
      const mx = nativeEvt?.clientX ?? 0
      const my = nativeEvt?.clientY ?? 0
      onTooltipHoverRef.current(mx, my, hoveredValueRef.current)
    }
  }, [data])

  const handlePlotlyUnhover = useCallback(() => {
    hoveredValueRef.current = null
    onTooltipUnhoverRef.current?.()
  }, [])

  // Right-click handler on the chart wrapper
  const handleContextMenu = useCallback((e: React.MouseEvent) => {
    if (!onRightClick) return
    e.preventDefault()
    e.stopPropagation()
    onRightClick({ x: e.clientX, y: e.clientY }, hoveredValueRef.current)
  }, [onRightClick])

  return (
    <div className="w-full h-full" data-testid="plotly-chart" onContextMenu={handleContextMenu}>
      <Plot
        data={themedData as Plotly.Data[]}
        layout={plotLayout as Partial<Plotly.Layout>}
        config={{ 
          displayModeBar: false, 
          responsive: true,
        }}
        style={{ width: '100%', height: '100%' }}
        useResizeHandler
        onClick={handlePlotlyClick}
        onHover={handlePlotlyHover}
        onUnhover={handlePlotlyUnhover}
      />
    </div>
  )
}

// Simple chart generation from rows/columns
interface SimpleChartProps {
  visualType: string
  columns: string[]
  rows: Array<Record<string, unknown>>
  onChartClick?: (value: unknown, isMultiSelect: boolean, pointIndex?: number) => void
  onRightClick?: (pos: { x: number; y: number }, hoveredValue: unknown) => void
  selectedValues?: unknown[] | null
  selectedPointIndices?: number[] | null
  onTooltipHover?: (mouseX: number, mouseY: number, value: unknown) => void
  onTooltipUnhover?: () => void
}

function SimpleChart({ visualType, columns, rows, onChartClick, onRightClick, selectedValues, selectedPointIndices, onTooltipHover, onTooltipUnhover }: SimpleChartProps) {
  const { effectiveTheme } = useTheme()
  const isDark = effectiveTheme === 'dark'
  const themeChart = useThemeStore((s) => s.reportingTheme.chart)
  const themeFont = useThemeStore((s) => s.reportingTheme.font)
  const dataColors = useThemeStore((s) => s.reportingTheme.dataColors)

  const chartData = useMemo(() => {
    // First column is typically the category/x-axis
    // Remaining columns are values/y-axis
    const categoryCol = columns[0]
    const valueCols = columns.slice(1)
    
    // Sort rows for consistent rendering order.
    // For bar/column/combo charts, Power BI sorts by value descending
    // by default. For other chart types, sort alphabetically by category.
    const isBarLike = ['bar', 'column', 'combo'].includes(visualType)
    const sortedRows = [...rows].sort((a, b) => {
      if (isBarLike && valueCols.length > 0) {
        // Sort by first value column descending (Power BI default)
        const na = Number(a[valueCols[0]] ?? 0)
        const nb = Number(b[valueCols[0]] ?? 0)
        return nb - na
      }
      const va = String(a[categoryCol] ?? '')
      const vb = String(b[categoryCol] ?? '')
      return va.localeCompare(vb)
    })
    
    const categories = sortedRows.map(r => String(r[categoryCol] ?? ''))
    
    if (visualType === 'pie') {
      // Pie chart uses first value column
      const values = sortedRows.map(r => Number(r[valueCols[0]] ?? 0))
      const pieTrace: Record<string, unknown> = {
        type: 'pie' as const,
        labels: categories,
        values: values,
        textinfo: 'percent' as const,
        textposition: 'inside' as const,
        marker: { colors: dataColors },
      }
      // Apply pull-out effect to highlight selected pie slices
      const selSetPie = selectedValues && selectedValues.length > 0
        ? new Set(selectedValues.map(v => String(v)))
        : null
      if (selSetPie) {
        pieTrace.pull = categories.map(c => selSetPie.has(c) ? 0.1 : 0)
        // Dim unselected slices by setting per-slice opacity via RGBA
        pieTrace.marker = {
          colors: categories.map((c, ci) => {
            const base = dataColors[ci % dataColors.length]
            return selSetPie.has(c) ? base : `${base}4D`  // 30% opacity hex suffix
          })
        }
      }
      return [pieTrace] as Plotly.Data[]
    }
    
    // For bar/column/line/area/scatter — apply theme colors per trace
    const traces: Plotly.Data[] = valueCols.map((col, i) => {
      const values = sortedRows.map(r => Number(r[col] ?? 0))
      const traceColor = dataColors[i % dataColors.length]
      
      const baseTrace = {
        x: categories,
        y: values,
        name: col,
        marker: { color: traceColor },
      }
      
      switch (visualType) {
        case 'bar':
          return { ...baseTrace, type: 'bar' as const, orientation: 'h' as const }
        case 'column':
          return { ...baseTrace, type: 'bar' as const }
        case 'line':
          return { ...baseTrace, type: 'scatter' as const, mode: 'lines+markers' as const, line: { color: traceColor } }
        case 'area':
          return { ...baseTrace, type: 'scatter' as const, fill: 'tozeroy' as const, line: { color: traceColor } }
        case 'scatter':
          return { ...baseTrace, type: 'scatter' as const, mode: 'markers' as const }
        case 'combo':
          // First series as bars, rest as lines
          return valueCols.indexOf(col) === 0
            ? { ...baseTrace, type: 'bar' as const }
            : { ...baseTrace, type: 'scatter' as const, mode: 'lines' as const, yaxis: 'y2' as const, line: { color: traceColor } }
        default:
          return { ...baseTrace, type: 'bar' as const }
      }
    })
    
    // Apply per-point marker.opacity to dim unselected points.
    // Same strategy as PlotlyChart:
    //  1. If selSet matches trace name → trace-level selection
    //  2. If selSet matches x-values → per-point selection
    //  3. If selSet matches nothing → skip
    const selSet = selectedValues && selectedValues.length > 0
      ? new Set(selectedValues.map(v => String(v)))
      : null
    const selPtSet = selectedPointIndices && selectedPointIndices.length > 0
      ? new Set(selectedPointIndices)
      : null

    if (selSet) {
      // Pre-compute whether selSet matches trace names or x-values
      const allTraceNames = traces.map(t => String((t as Record<string, unknown>).name ?? ''))
      const hasTraceNameMatch = allTraceNames.some(n => n && selSet.has(n))
      const hasXValueMatch = traces.some(t => {
        const tr = t as Record<string, unknown>
        const xArr = Array.isArray(tr.x) ? tr.x : Array.isArray(tr.labels) ? tr.labels : null
        return xArr?.some((v: unknown) => selSet.has(String(v)))
      })

      for (const trace of traces) {
        const t = trace as Record<string, unknown>
        const isScatterType = t.type === 'scatter' || t.type === 'scattergl'
        const isBarType = t.type === 'bar'
        const modeStr = String(t.mode ?? '')
        const isLineTrace = isScatterType && (modeStr.includes('lines') || !modeStr)
        const traceName = String(t.name ?? '')
        const axis = Array.isArray(t.x) ? t.x : Array.isArray(t.labels) ? t.labels : null
        if (axis) {
          let opacities: number[] | null = null

          if (hasTraceNameMatch && !hasXValueMatch) {
            // Trace-level selection
            const traceMatches = traceName && selSet.has(traceName)
            opacities = new Array(axis.length).fill(traceMatches ? 1.0 : 0.3)
          } else if (hasXValueMatch) {
            opacities = new Array(axis.length)
            if (isLineTrace) {
              for (let j = 0; j < axis.length; j++) {
                opacities[j] = selSet.has(String(axis[j])) ? 1.0 : 0.3
              }
            } else if (isScatterType && selPtSet) {
              for (let j = 0; j < axis.length; j++) {
                opacities[j] = selPtSet.has(j) ? 1.0 : 0.3
              }
            } else {
              for (let j = 0; j < axis.length; j++) {
                opacities[j] = selSet.has(String(axis[j])) ? 1.0 : 0.3
              }
            }
          }

          if (opacities) {
            const markerObj = (t.marker as Record<string, unknown>) ?? {}
            const markerUpdate: Record<string, unknown> = { ...markerObj, opacity: opacities }
            // Only add per-point sizes for scatter/line (NOT bars)
            if (isScatterType) {
              const baseSize = typeof markerObj.size === 'number' ? markerObj.size : 6
              markerUpdate.size = opacities.map(o => o >= 1.0 ? baseSize * 2.5 : baseSize)
            }
            t.marker = markerUpdate
            if (isScatterType && !modeStr.includes('markers')) {
              t.mode = modeStr ? modeStr + '+markers' : 'lines+markers'
            }
          }
        }
      }
    }

    return traces
  }, [visualType, columns, rows, dataColors, selectedValues, selectedPointIndices])

  const layout = useMemo(() => {
    const fontColor = themeFont.colorBody || (isDark ? '#e0e4ec' : '#1e293b')
    const gridColor = themeChart.gridlineColor || (isDark ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.06)')
    const axisColor = themeChart.axisColor || gridColor
    const plotBg = themeChart.plotBackground || 'transparent'
    const fontSize = themeFont.sizeBody || 10

    // Lock category axis order to prevent reordering on click.
    const isHBar = visualType === 'bar'
    const firstTrace = chartData[0] as Record<string, unknown> | undefined
    const catSrc = firstTrace
      ? (isHBar && Array.isArray(firstTrace.y) ? firstTrace.y as unknown[]
        : Array.isArray(firstTrace.x) ? firstTrace.x as unknown[]
        : null)
      : null
    // Preserve order of first occurrence
    const catArray = catSrc ? [...new Map(catSrc.map((v, i) => [String(v), i])).keys()] : null

    const base: Partial<Plotly.Layout> = {
      autosize: true,
      margin: { l: 50, r: 20, t: 20, b: 50 },
      paper_bgcolor: 'transparent',
      plot_bgcolor: plotBg,
      font: { size: fontSize, color: fontColor, ...(themeFont.family ? { family: themeFont.family } : {}) },
      colorway: dataColors,
      xaxis: {
        gridcolor: themeChart.showGridlines ? gridColor : 'transparent',
        zerolinecolor: axisColor,
        ...(catArray && !isHBar ? { categoryorder: 'array' as const, categoryarray: catArray } : {}),
      },
      yaxis: {
        gridcolor: themeChart.showGridlines ? gridColor : 'transparent',
        zerolinecolor: axisColor,
        ...(catArray && isHBar ? { categoryorder: 'array' as const, categoryarray: catArray } : {}),
      },
      showlegend: chartData.length > 1,
      legend: { orientation: 'h' as const, y: -0.2, font: { color: fontColor } },
    }
    
    if (visualType === 'combo') {
      return {
        ...base,
        yaxis2: {
          overlaying: 'y' as const,
          side: 'right' as const,
        },
      }
    }
    
    return base
  }, [visualType, chartData.length, isDark, themeChart, themeFont, dataColors])

  // Stable ref-based handler — same pattern as PlotlyChart to avoid stale
  // closures when react-plotly-js skips re-binding event handlers.
  const onChartClickRef = useRef(onChartClick)
  onChartClickRef.current = onChartClick

  const handlePlotlyClick = useCallback((event: Plotly.PlotMouseEvent) => {
    const cb = onChartClickRef.current
    if (!cb || !event.points || event.points.length === 0) return
    
    const point = event.points[0] as Plotly.PlotDatum & { label?: string }
    const pointAny = point as unknown as Record<string, unknown>
    // For horizontal bars (orientation: 'h'), categories are on y axis
    const trace = chartData[point.curveNumber ?? 0]
    const isHorizontalBar = trace && (trace as Record<string, unknown>).type === 'bar' && (trace as Record<string, unknown>).orientation === 'h'
    let value: unknown
    if (point.label !== undefined) {
      value = point.label  // pie, treemap, sunburst, icicle
    } else if (pointAny.theta !== undefined) {
      value = pointAny.theta  // polar charts
    } else if (isHorizontalBar) {
      value = point.y      // horizontal bar: categories on y
    } else {
      value = point.x !== undefined ? point.x : point.y
    }
    
    if (value === undefined || value === null) return
    
    const isMultiSelect = !!(event.event && (event.event.ctrlKey || event.event.metaKey))
    // Pass point index for scatter-level single-point selection
    const ptIndex = point.pointIndex ?? point.pointNumber
    cb(value, isMultiSelect, ptIndex)
  }, [chartData])  // depends on chartData to read trace orientation

  // Track hovered data point for right-click context menu + tooltip pages
  const hoveredValueRef = useRef<unknown>(null)
  const onTooltipHoverRef = useRef(onTooltipHover)
  onTooltipHoverRef.current = onTooltipHover
  const onTooltipUnhoverRef = useRef(onTooltipUnhover)
  onTooltipUnhoverRef.current = onTooltipUnhover

  const handleHover = useCallback((event: Plotly.PlotHoverEvent) => {
    if (!event.points || event.points.length === 0) { hoveredValueRef.current = null; return }
    const point = event.points[0] as Plotly.PlotDatum & { label?: string }
    const pointAny = point as unknown as Record<string, unknown>
    const trace = chartData[point.curveNumber ?? 0]
    const isHBar = trace && (trace as Record<string, unknown>).type === 'bar' && (trace as Record<string, unknown>).orientation === 'h'
    if (point.label !== undefined) hoveredValueRef.current = point.label
    else if (pointAny.theta !== undefined) hoveredValueRef.current = pointAny.theta
    else if (isHBar) hoveredValueRef.current = point.y
    else hoveredValueRef.current = point.x !== undefined ? point.x : point.y
    // Notify tooltip page popup
    if (onTooltipHoverRef.current && hoveredValueRef.current != null) {
      const nativeEvt = (event as unknown as { event?: MouseEvent }).event
      const mx = nativeEvt?.clientX ?? 0
      const my = nativeEvt?.clientY ?? 0
      onTooltipHoverRef.current(mx, my, hoveredValueRef.current)
    }
  }, [chartData])

  const handleUnhover = useCallback(() => {
    hoveredValueRef.current = null
    onTooltipUnhoverRef.current?.()
  }, [])

  const handleContextMenu = useCallback((e: React.MouseEvent) => {
    if (!onRightClick) return
    e.preventDefault()
    e.stopPropagation()
    onRightClick({ x: e.clientX, y: e.clientY }, hoveredValueRef.current)
  }, [onRightClick])

  return (
    <div className="w-full h-full" data-testid="simple-chart" onContextMenu={handleContextMenu}>
      <Plot
        data={chartData}
        layout={layout}
        config={{ 
          displayModeBar: false, 
          responsive: true,
        }}
        style={{ width: '100%', height: '100%' }}
        useResizeHandler
        onClick={handlePlotlyClick}
        onHover={handleHover}
        onUnhover={handleUnhover}
      />
    </div>
  )
}

/** Convert a color string to an rgba() with the given opacity (for dimming lines/areas). */
function dimColor(color: string, opacity: number): string {
  const hex = color.match(/^#?([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i)
  if (hex) {
    return `rgba(${parseInt(hex[1], 16)}, ${parseInt(hex[2], 16)}, ${parseInt(hex[3], 16)}, ${opacity})`
  }
  const rgb = color.match(/^rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)/)
  if (rgb) {
    return `rgba(${rgb[1]}, ${rgb[2]}, ${rgb[3]}, ${opacity})`
  }
  return color
}

function formatCellValue(value: unknown): string {
  if (value === null || value === undefined) return '-'
  if (typeof value === 'number') {
    // Format numbers with locale
    return Number.isInteger(value) 
      ? value.toLocaleString()
      : value.toLocaleString(undefined, { maximumFractionDigits: 2 })
  }
  if (typeof value === 'boolean') return value ? 'Yes' : 'No'
  return String(value)
}

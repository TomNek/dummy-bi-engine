/**
 * MatrixVisual - React component for rendering tablix/matrix visuals
 * 
 * Renders the TablixPlan grid structure with:
 * - Row and column headers
 * - Body cells with values
 * - Subtotals and grand totals
 * - Expand/collapse for row hierarchies
 * - Sticky headers
 * - Virtual scrolling for large matrices (50+ body rows)
 */
import { useMemo, useCallback, useState, useRef, useEffect } from 'react'
import { useVirtualizer } from '@tanstack/react-virtual'
import { cn } from '@/lib/utils'
import { ChevronDown, ChevronRight } from 'lucide-react'
import type { TablixPlan, TablixCell, CellRole, CellFormattingRule, CellFormattingStyle } from '@/types/matrix'
import { getCellClasses as getSharedCellClasses, getCellInlineStyle, type CellStyleContext } from '@/lib/matrix-cell-styles'
import { MatrixContextMenu, type MatrixCellInfo } from '@/components/matrix'
import { useColumnResize, ResizeHandle, type ColumnWidths, useRowResize, RowResizeHandle, type RowHeights } from '@/hooks/useColumnResize'
import type { CellFormat } from '@/components/visuals/DesignCellEditor'
import { ExplanationColumnHeader, ExplanationCell, type ExplanationData, type ExplNode } from './ExplanationColumn'
import { hasTablixData, getRowHeaderPaddingLeft, normalizeIbcsGraphic, getStableColumnKey } from './matrix-helpers'
import { designCellIdFromTablixCell, normalizeDesignCellFormats, parseDesignCellId } from '@/lib/matrix-design-ids'
import { buildInitialMatrixColumnWidths, getMatrixColumnWidthStyle, normalizeMatrixColumnWidthMode } from '@/lib/matrix-column-widths'
import { useMatrixStore } from '@/hooks'

/** Body row count threshold above which virtual scrolling is enabled */
const VIRTUAL_ROW_THRESHOLD = 50
/** Estimated row height in pixels for virtual scroll sizing */
const ESTIMATED_ROW_HEIGHT = 28

/** IBCS graphic renderers */
function IbcsVarianceArrow({ value }: { value: number }) {
  const isPos = value >= 0
  return (
    <span className={cn('inline-flex items-center text-[10px]', isPos ? 'text-green-600' : 'text-red-600')}>
      {isPos ? '▲' : '▼'} {Math.abs(value).toFixed(1)}%
    </span>
  )
}

function IbcsStatusDot({ value, thresholds }: { value: number; thresholds?: { red?: number; yellow?: number } }) {
  const red = thresholds?.red ?? 0.5
  const yellow = thresholds?.yellow ?? 0.8
  const color = value < red ? 'bg-red-500' : value < yellow ? 'bg-yellow-500' : 'bg-green-500'
  return <span className={cn('inline-block w-2.5 h-2.5 rounded-full', color)} />
}

function IbcsDeviationBar({ value, maxAbs }: { value: number; maxAbs?: number }) {
  const max = maxAbs || 100
  const pct = Math.min(Math.abs(value) / max * 100, 100)
  const isPos = value >= 0
  return (
    <div className="relative flex items-center h-3 w-full">
      <div className="absolute left-1/2 w-px h-full bg-border" />
      <div
        className={cn('absolute h-2.5', isPos ? 'bg-green-500/40' : 'bg-red-500/40')}
        style={{
          width: `${pct / 2}%`,
          ...(isPos ? { left: '50%' } : { right: '50%' }),
        }}
      />
    </div>
  )
}

function IbcsProgressBar({ value, target }: { value: number; target?: number }) {
  const t = target || 1
  const pct = Math.min((value / t) * 100, 100)
  return (
    <div className="relative h-3 w-full bg-muted/30 rounded-sm overflow-hidden">
      <div
        className={cn('absolute h-full', pct >= 100 ? 'bg-green-500/50' : 'bg-primary/30')}
        style={{ width: `${Math.max(pct, 0)}%` }}
      />
    </div>
  )
}

/** Power BI conditional formatting KPI icon mapping */
const PBI_ICON_MAP: Record<string, { symbol: string; color: string }> = {
  // Traffic light / circles
  CircleHigh: { symbol: '●', color: '#107C10' },
  CircleMedium: { symbol: '●', color: '#FF8C00' },
  CircleLow: { symbol: '●', color: '#D13438' },
  // Arrows / signs / flags
  SignHigh: { symbol: '▲', color: '#107C10' },
  SignMedium: { symbol: '◆', color: '#FF8C00' },
  SignLow: { symbol: '▼', color: '#D13438' },
  // Checkmarks / crosses
  CheckHigh: { symbol: '✔', color: '#107C10' },
  CheckMedium: { symbol: '!', color: '#FF8C00' },
  CheckLow: { symbol: '✖', color: '#D13438' },
  // Triangles
  TriangleUp: { symbol: '▲', color: '#107C10' },
  TriangleDash: { symbol: '—', color: '#FF8C00' },
  TriangleDown: { symbol: '▼', color: '#D13438' },
}

function CondFmtIcon({ iconName }: { iconName: string }) {
  const entry = PBI_ICON_MAP[iconName]
  if (!entry) {
    // Fallback: render text with neutral color
    return <span className="text-xs text-muted-foreground">{iconName}</span>
  }
  return (
    <span className="inline-flex items-center text-xs" style={{ color: entry.color }}>
      {entry.symbol}
    </span>
  )
}

interface MatrixVisualProps {
  data: TablixPlan
  visualId?: string
  /** Truncation info from server when safety caps were applied */
  truncationInfo?: { rows?: boolean; cols?: boolean; max_rows?: number | null; max_cols?: number | null } | null
  onExpand?: (rowPath: string[], expanded: boolean, ctx?: { blockIndex?: number }) => void
  onColExpand?: (colPath: string[], expanded: boolean, ctx?: { blockIndex?: number }) => void
  onCellClick?: (cell: TablixCell) => void
  onDrillAction?: (action: string, cellInfo: MatrixCellInfo) => void
  columnWidths?: ColumnWidths
  onColumnWidthsChange?: (widths: ColumnWidths) => void
  rowHeights?: RowHeights
  onRowHeightsChange?: (heights: RowHeights) => void
  /** Design cell formats from tablix editor (applied to body/header cells) */
  designCells?: Record<string, CellFormat>
  /** Callback when a band is resized via drag on the canvas */
  onBandResize?: (axis: 'row' | 'col', bandIndex: number, newSize: number) => void
  /** Explanation data from ExplanationRef bindings (Phase 10.9) */
  explanationData?: ExplanationData | null
  /** Imported Power BI row header outline style (for example Frame/Stepped). */
  rowHeaderOutlineStyle?: string
  className?: string
}

export function MatrixVisual({ data, visualId, truncationInfo, onExpand, onColExpand, onCellClick, onDrillAction, columnWidths: externalWidths, onColumnWidthsChange, rowHeights: externalRowHeights, onRowHeightsChange, designCells, onBandResize, explanationData, rowHeaderOutlineStyle, className }: MatrixVisualProps) {
  const normalizedDesignCells = useMemo(
    () => normalizeDesignCellFormats(designCells),
    [designCells],
  )

  // Context menu state
  const [ctxMenu, setCtxMenu] = useState<{ cellInfo: MatrixCellInfo; position: { x: number; y: number } } | null>(null)

  // Drill state for context menu enable/disable
  // CRITICAL: do NOT call getDrillState() inside selector — it creates a new
  // defaultDrillState() object when no state exists, causing infinite re-renders.
  const drillState = useMatrixStore(s => visualId ? (s.drillState[visualId] ?? null) : null)
  const currentRowDrillLevel = drillState?.drillRowFilters?.length ?? 0
  const currentColDrillLevel = drillState?.drillColFilters?.length ?? 0

  // Explanation column state (Phase 10.9)
  const [explExpandedRows, setExplExpandedRows] = useState<Set<number>>(new Set())
  const explPerRow: (ExplNode | null)[] | null = useMemo(() => {
    if (!explanationData?.explanations?.length) return null
    const expl = explanationData.explanations[0]
    return expl?.per_row ?? expl?.nodes ?? null
  }, [explanationData])
  const hasExplanation = explPerRow != null && explPerRow.length > 0
  const handleExplToggle = useCallback((rowIndex: number) => {
    setExplExpandedRows(prev => {
      const next = new Set(prev)
      if (next.has(rowIndex)) next.delete(rowIndex); else next.add(rowIndex)
      return next
    })
  }, [])
  const handleExplExpandAll = useCallback(() => {
    const bodyCount = (data.numRows || 0) - (data.numColHeaderRows || 0)
    setExplExpandedRows(new Set(Array.from({ length: bodyCount }, (_, i) => i)))
  }, [data.numRows, data.numColHeaderRows])
  const handleExplCollapseAll = useCallback(() => {
    setExplExpandedRows(new Set())
  }, [])

  // Build a 2D grid from sparse cell list + precompute spanned positions
  const { grid, spannedOver } = useMemo(() => {
    const g: (TablixCell | null)[][] = Array.from(
      { length: data.numRows },
      () => Array(data.numCols).fill(null)
    )
    const spanned = new Set<string>()
    
    for (const cell of data.cells) {
      if (cell.row >= 0 && cell.row < data.numRows && cell.col >= 0 && cell.col < data.numCols) {
        g[cell.row][cell.col] = cell
        // Mark all positions covered by this cell's spans (except the cell itself)
        const rs = cell.rowSpan || 1
        const cs = cell.colSpan || 1
        for (let dr = 0; dr < rs; dr++) {
          for (let dc = 0; dc < cs; dc++) {
            if (dr === 0 && dc === 0) continue
            spanned.add(`${cell.row + dr}:${cell.col + dc}`)
          }
        }
      }
    }
    
    return { grid: g, spannedOver: spanned }
  }, [data])

  // Handle expand/collapse click
  const handleExpandClick = useCallback((cell: TablixCell, e: React.MouseEvent) => {
    e.stopPropagation()
    if (cell.isExpandable && cell.rowPath && onExpand) {
      const ctx = cell.rowBlockIndex !== undefined ? { blockIndex: cell.rowBlockIndex } : undefined
      onExpand(cell.rowPath, !cell.isExpanded, ctx)
    }
  }, [onExpand])

  const handleColExpandClick = useCallback((cell: TablixCell, e: React.MouseEvent) => {
    e.stopPropagation()
    if (cell.isExpandable && cell.colPath && onColExpand) {
      const ctx = cell.colBlockIndex !== undefined ? { blockIndex: cell.colBlockIndex } : undefined
      onColExpand(cell.colPath, !cell.isExpanded, ctx)
    }
  }, [onColExpand])

  // Handle cell right-click for context menu
  const handleCellContextMenu = useCallback((cell: TablixCell, e: React.MouseEvent) => {
    e.preventDefault()
    e.stopPropagation()
    const role = cell.role as CellRole
    if (role === 'row_header' || role === 'row_group' || role === 'col_header' || role === 'col_group' || role === 'body' || role === 'detail') {
      const axis: 'rows' | 'cols' = role === 'col_header' || role === 'col_group' ? 'cols' : 'rows'
      setCtxMenu({
        cellInfo: {
          axis,
          level: cell.indent ?? 0,
          key: cell.rowKey ?? cell.colKey ?? '',
          value: cell.formatted ?? cell.label ?? String(cell.value ?? ''),
          rowPath: cell.rowPath,
          colPath: cell.colPath,
        },
        position: { x: e.clientX, y: e.clientY },
      })
    }
  }, [])

  // Handle cell click for interaction
  const handleCellClick = useCallback((cell: TablixCell) => {
    if (cell.isInteractive !== false && onCellClick) {
      onCellClick(cell)
    }
  }, [onCellClick])

  // Extract tablix properties for gridlines, density, autofit, cell rules
  const tablixProps = data.properties
  const gridlineMode = tablixProps?.gridlines ?? 'light'
  const densityMode = tablixProps?.density ?? 'normal'
  const columnHeaderBackColor = tablixProps?.columnHeaderBackColor ?? null
  const autofitCols = tablixProps?.autofitColumns !== false
  const snapToFit = tablixProps?.snapColumnsToFit !== false
  const defaultColWidth = tablixProps?.defaultColumnWidth ?? 100
  const defaultRowHeight = tablixProps?.defaultRowHeight ?? 32
  const cellRules = tablixProps?.cellRules ?? []
  const columnWidthMode = useMemo(() => normalizeMatrixColumnWidthMode(tablixProps), [tablixProps])
  const moreGranularColumnWidths = tablixProps?.moreGranularColumnWidths === true
  const hasMobileColumnWidths = Boolean(tablixProps?.mobileColumnWidths && Object.keys(tablixProps.mobileColumnWidths).length > 0)
  const importedColWidths = useMemo(
    () => buildInitialMatrixColumnWidths(data.cells, tablixProps, getStableColumnKey),
    [data.cells, tablixProps],
  )
  const initialColWidths = useMemo(
    () => ({ ...importedColWidths, ...(externalWidths || {}) }),
    [importedColWidths, externalWidths],
  )

  // Column resize support
  const { widths: colWidths, handleResizeStart } = useColumnResize({
    initialWidths: initialColWidths,
    minWidth: 40,
    maxWidth: 600,
    onWidthsChange: (w) => onColumnWidthsChange?.(w),
  })
  const hasColWidths = Object.keys(colWidths).length > 0

  // Row resize support
  const { heights: rowHeights, getHeight: getRowHeight, handleResizeStart: handleRowResizeStart } = useRowResize({
    initialHeights: externalRowHeights || {},
    minHeight: 20,
    maxHeight: 300,
    onHeightsChange: (h) => onRowHeightsChange?.(h),
  })

  const tableLayoutMode = columnWidthMode === 'fit_to_content' && !hasColWidths ? 'auto' : 'fixed'
  const tableWidth = columnWidthMode === 'grow_to_fit' || snapToFit ? '100%' : 'auto'

  // Band sizing: extract configured widths/heights from band definitions
  const rowBandWidths = useMemo(() => {
    const bands = tablixProps?.rowHeaderBands ?? []
    return bands.map(b => (b.width && b.width > 0) ? b.width : undefined)
  }, [tablixProps])
  const colBandHeights = useMemo(() => {
    const bands = tablixProps?.colHeaderBands ?? []
    return bands.map(b => (b.height && b.height > 0) ? b.height : undefined)
  }, [tablixProps])
  const numBandCols = data.numRowHeaderBandCols ?? 0
  const numBandRows = data.numColHeaderBandRows ?? 0

  // Band resize drag state
  const bandResizeRef = useRef<{ axis: 'row' | 'col'; bandIndex: number; startPos: number; startSize: number } | null>(null)
  const [bandResizeDelta, setBandResizeDelta] = useState<{ axis: 'row' | 'col'; bandIndex: number; delta: number } | null>(null)

  const handleBandResizeStart = useCallback((axis: 'row' | 'col', bandIndex: number, e: React.MouseEvent) => {
    e.preventDefault()
    e.stopPropagation()
    const startPos = axis === 'row' ? e.clientX : e.clientY
    // Measure current rendered size from the DOM
    const target = e.currentTarget.parentElement
    const startSize = target ? (axis === 'row' ? target.offsetWidth : target.offsetHeight) : 60
    bandResizeRef.current = { axis, bandIndex, startPos, startSize }

    const handleMouseMove = (moveEvent: MouseEvent) => {
      if (!bandResizeRef.current) return
      const delta = (axis === 'row' ? moveEvent.clientX : moveEvent.clientY) - bandResizeRef.current.startPos
      setBandResizeDelta({ axis, bandIndex, delta })
    }
    const handleMouseUp = (upEvent: MouseEvent) => {
      document.removeEventListener('mousemove', handleMouseMove)
      document.removeEventListener('mouseup', handleMouseUp)
      if (bandResizeRef.current) {
        const delta = (axis === 'row' ? upEvent.clientX : upEvent.clientY) - bandResizeRef.current.startPos
        const newSize = Math.max(20, bandResizeRef.current.startSize + delta)
        onBandResize?.(axis, bandIndex, Math.round(newSize))
        bandResizeRef.current = null
        setBandResizeDelta(null)
      }
    }
    document.addEventListener('mousemove', handleMouseMove)
    document.addEventListener('mouseup', handleMouseUp)
  }, [onBandResize])

  // Level-based aggregate detection for rows.
  // Iterate over the full rowSpan of each header cell so that every row
  // underneath a multi-span parent gets a level entry.  Keep the deepest
  // (highest numeric) level per row — rows at a lower level than maxLevel
  // represent aggregates and get coloring.
  const { rowLevelMap, maxRowLevel } = useMemo(() => {
    let maxLevel = -1
    const levelByRow = new Map<number, number>()
    for (const cell of data.cells) {
      if ((cell.role === 'row_header' || cell.role === 'row_group' || cell.role === 'row_block') && cell.level != null) {
        maxLevel = Math.max(maxLevel, cell.level)
        const span = cell.rowSpan ?? 1
        for (let r = cell.row; r < cell.row + span; r++) {
          const prev = levelByRow.get(r)
          if (prev == null || cell.level > prev) {
            levelByRow.set(r, cell.level)
          }
        }
      }
    }
    // Also capture subtotal rows — they have a level indicating which hierarchy level they summarize
    for (const cell of data.cells) {
      if (cell.isSubtotal && cell.level != null && !levelByRow.has(cell.row)) {
        const span = cell.rowSpan ?? 1
        for (let r = cell.row; r < cell.row + span; r++) {
          if (!levelByRow.has(r)) {
            levelByRow.set(r, cell.level)
          }
        }
      }
    }
    return { rowLevelMap: levelByRow, maxRowLevel: maxLevel }
  }, [data])

  // Level-based aggregate detection for columns (same approach).
  // Iterate over the full colSpan of each header cell so that every column
  // underneath a multi-span parent gets a level entry.  Keep the deepest
  // (highest numeric) level per column — that represents the leaf-most
  // header that covers it; lower-level columns indicate aggregates.
  const { colLevelMap, maxColLevel } = useMemo(() => {
    let maxLevel = -1
    const levelByCol = new Map<number, number>()
    for (const cell of data.cells) {
      if ((cell.role === 'col_header' || cell.role === 'col_group') && cell.level != null) {
        maxLevel = Math.max(maxLevel, cell.level)
        const span = cell.colSpan ?? 1
        for (let c = cell.col; c < cell.col + span; c++) {
          const prev = levelByCol.get(c)
          if (prev == null || cell.level > prev) {
            levelByCol.set(c, cell.level)
          }
        }
      }
    }
    return { colLevelMap: levelByCol, maxColLevel: maxLevel }
  }, [data])

  const subtotalCols = useMemo(() => {
    const cols = new Set<number>()
    for (const cell of data.cells) {
      if (!cell.isSubtotal || cell.isGrandTotal) continue
      if (cell.row >= (data.numColHeaderRows || 0)) continue
      const span = cell.colSpan ?? 1
      for (let c = cell.col; c < cell.col + span; c++) cols.add(c)
    }
    return cols
  }, [data])

  // Shared cell-class context for getCellClasses
  const cellStyleCtx: CellStyleContext = useMemo(() => ({
    densityMode,
    gridlineMode,
    columnHeaderBackColor,
    rowLevelMap,
    maxRowLevel,
    colLevelMap,
    maxColLevel,
    subtotalCols,
    numColHeaderRows: data.numColHeaderRows || 0,
    numRowHeaderBandCols: data.numRowHeaderBandCols ?? 0,
    numRowHeaderCols: data.numRowHeaderCols ?? 1,
  }), [densityMode, gridlineMode, columnHeaderBackColor, rowLevelMap, maxRowLevel, colLevelMap, maxColLevel, subtotalCols, data])

  // Get CSS class for cell role — delegates to shared module
  const getCellClasses = (cell: TablixCell): string => {
    return getSharedCellClasses(cell, cellStyleCtx)
  }

  // Format cell display value, with optional text sanitization
  const formatValue = (cell: TablixCell): string => {
    if (cell.formatted !== undefined && cell.formatted !== null) {
      return cell.formatted
    }
    if (cell.label !== undefined && cell.label !== null) {
      // Sanitize: strip trailing colon (common in headers like "Category:")
      return cell.label.replace(/:\s*$/, '')
    }
    if (cell.value === null || cell.value === undefined) {
      return ''
    }
    if (typeof cell.value === 'number') {
      return cell.value.toLocaleString(undefined, { maximumFractionDigits: 2 })
    }
    return String(cell.value)
  }

  // Match cell formatting rules from TablixProperties against a cell.
  // Returns the accumulated CellFormattingStyle from all matching rules.
  const matchCellRules = useCallback((cell: TablixCell): CellFormattingStyle | undefined => {
    if (!cellRules || cellRules.length === 0) return undefined

    const role = cell.role as CellRole
    let matched: CellFormattingStyle | undefined

    for (const rule of cellRules) {
      if (!rule.enabled) continue

      // Region filter
      if (rule.region && rule.region !== role) continue

      // Role filter (Python side uses 'body', 'header' etc.)
      if (rule.role) {
        const roleCategory =
          role === 'body' || role === 'detail' ? 'body' :
          role === 'row_header' || role === 'row_group' || role === 'col_header' || role === 'col_group' ? 'header' :
          role === 'row_subtotal' || role === 'col_subtotal' || role === 'cross_subtotal' || role === 'subtotal' ? 'subtotal' :
          role === 'grand_total' || role === 'col_total' ? 'total' :
          role
        if (rule.role !== roleCategory && rule.role !== role) continue
      }

      // Measure filter
      if (rule.measureId && cell.measureName !== rule.measureId) continue

      // Row path prefix filter
      if (rule.rowPathPrefix && rule.rowPathPrefix.length > 0) {
        const rp = cell.rowPath ?? []
        const prefixMatches = rule.rowPathPrefix.every((seg, i) => rp[i] === seg)
        if (!prefixMatches) continue
      }

      // Col path prefix filter
      if (rule.colPathPrefix && rule.colPathPrefix.length > 0) {
        const cp = cell.colPath ?? []
        const prefixMatches = rule.colPathPrefix.every((seg, i) => cp[i] === seg)
        if (!prefixMatches) continue
      }

      // Rule matches — accumulate style
      if (rule.style) {
        matched = matched ? { ...matched, ...rule.style } : { ...rule.style }
      }
    }

    return matched
  }, [cellRules])

  // Map a data view cell to a design cell region for design cell formatting lookup.
  // Returns the matching CellFormat if designCells are provided, or undefined.
  const getDesignCellFormat = useCallback((cell: TablixCell): CellFormat | undefined => {
    if (!normalizedDesignCells || Object.keys(normalizedDesignCells).length === 0) return undefined

    // Design-cell ID must use ONLY the cell's own flags.
    // Row/column def inference (rowDef?.isSubtotal, colDef?.isGrandTotal, etc.)
    // is unreliable because row indices shift when columns are expanded
    // (extra header rows are inserted), causing cell.row to map to the
    // wrong rowDef.  Column def inference was already removed (subtotal
    // columns must share the same design-cell ID as the parent column).
    const normalizedCell = cell

    const exactKey = designCellIdFromTablixCell(normalizedCell)
    const exact = normalizedDesignCells[exactKey]
    if (exact) return exact

    const parsedExact = parseDesignCellId(exactKey)
    if (!parsedExact) return undefined

    if (parsedExact.region === 'value') {
      return undefined
    }

    let fallbackMatch: CellFormat | undefined
    let anySlotMatch: CellFormat | undefined
    for (const [key, fmt] of Object.entries(normalizedDesignCells)) {
      if (!fmt) continue
      const parsed = parseDesignCellId(key)
      if (!parsed) continue

      if (parsed.bandType !== parsedExact.bandType) continue
      if ((parsed.bandId ?? null) !== (parsedExact.bandId ?? null)) continue
      if (parsed.region !== parsedExact.region) continue
      if (parsed.axis !== parsedExact.axis) continue
      if (parsed.level !== parsedExact.level) continue
      if (parsed.kind !== parsedExact.kind) continue

      if (!anySlotMatch) anySlotMatch = fmt
      if (parsed.slot === 0) {
        fallbackMatch = fmt
        break
      }
    }

    return fallbackMatch ?? anySlotMatch
  }, [normalizedDesignCells])

  // Render cell content
  const renderCellContent = (cell: TablixCell) => {
    const displayValue = formatValue(cell)

    // Check for IBCS graphic from cell rules (lower priority)
    const ruleStyle = matchCellRules(cell)
    if (ruleStyle?.ibcsGraphic) {
      const numVal = typeof cell.value === 'number' ? cell.value : parseFloat(displayValue) || 0
      // Normalize camelCase (backend) to snake_case (renderer)
      const graphicKey = normalizeIbcsGraphic(ruleStyle.ibcsGraphic as string)
      switch (graphicKey) {
        case 'variance_arrow':
          return <IbcsVarianceArrow value={numVal} />
        case 'status_dot':
          return <IbcsStatusDot value={numVal} />
        case 'deviation_bar':
          return <IbcsDeviationBar value={numVal} />
        case 'progress_bar':
          return <IbcsProgressBar value={numVal} />
      }
    }

    // Check for IBCS graphic from design cell format (higher priority)
    const dcFmt = getDesignCellFormat(cell)
    if (dcFmt?.ibcsGraphic) {
      const numVal = typeof cell.value === 'number' ? cell.value : parseFloat(displayValue) || 0
      const graphicKey = normalizeIbcsGraphic(dcFmt.ibcsGraphic)
      switch (graphicKey) {
        case 'variance_arrow':
          return <IbcsVarianceArrow value={numVal} />
        case 'status_dot':
          return <IbcsStatusDot value={numVal} />
        case 'deviation_bar':
          return <IbcsDeviationBar value={numVal} />
        case 'progress_bar':
          return <IbcsProgressBar value={numVal} />
      }
    }
    
    // Expandable row header (also applies to row_block label cells)
    if (cell.isExpandable && (cell.role === 'row_header' || cell.role === 'row_group' || cell.role === 'row_block')) {
      return (
        <div className="flex items-center gap-1">
          <button
            onClick={(e) => handleExpandClick(cell, e)}
            className="flex-shrink-0 p-0.5 hover:bg-accent rounded"
            data-testid="matrix-expand-toggle"
            data-row-key={cell.rowKey}
          >
            {cell.isExpanded ? (
              <ChevronDown className="h-3 w-3" />
            ) : (
              <ChevronRight className="h-3 w-3" />
            )}
          </button>
          <span className="truncate">{displayValue}</span>
        </div>
      )
    }

    if (cell.isExpandable && (cell.role === 'col_header' || cell.role === 'col_group')) {
      return (
        <div className="flex items-center justify-center gap-1">
          <button
            onClick={(e) => handleColExpandClick(cell, e)}
            className="flex-shrink-0 p-0.5 hover:bg-accent rounded"
            data-testid="matrix-col-expand-toggle"
            data-col-key={cell.colKey}
          >
            {cell.isExpanded ? (
              <ChevronDown className="h-3 w-3" />
            ) : (
              <ChevronRight className="h-3 w-3" />
            )}
          </button>
          <span className="truncate">{displayValue}</span>
        </div>
      )
    }
    
    // Value cell with bar spec (IBCS bars or conditional formatting data bars)
    if (cell.barSpec && (cell.barSpec.pct !== undefined || cell.barSpec.width !== undefined)) {
      const pct = cell.barSpec.width ?? (Math.abs(cell.barSpec.pct ?? 0) * 100)
      const isPositive = cell.barSpec.direction === 'right' || (cell.barSpec.positive !== false && (cell.barSpec.value ?? 0) >= 0)
      const barColor = cell.barSpec.color || (isPositive ? '#333333' : '#cc0000')
      const hideText = cell.condFmt?.hideText === true
      
      return (
        <div className="relative flex items-center">
          <div 
            className="absolute h-3 opacity-30"
            style={{ 
              width: `${Math.min(pct, 100)}%`,
              backgroundColor: barColor,
              left: isPositive ? 0 : 'auto',
              right: isPositive ? 'auto' : 0,
            }}
          />
          {!hideText && <span className="relative z-10 w-full text-right">{displayValue}</span>}
        </div>
      )
    }

    // Conditional formatting icon (KPI indicators)
    if (cell.condFmt?.icon) {
      const iconEl = <CondFmtIcon iconName={cell.condFmt.icon} />
      const layout = cell.condFmt.iconLayout || 'left'
      if (layout === 'right') {
        return (
          <span className="inline-flex items-center gap-1 truncate">
            <span className="truncate">{displayValue}</span>
            {iconEl}
          </span>
        )
      }
      return (
        <span className="inline-flex items-center gap-1 truncate">
          {iconEl}
          <span className="truncate">{displayValue}</span>
        </span>
      )
    }
    
    return <span className="truncate">{displayValue}</span>
  }

  // Check if we should skip rendering a cell (spanned over by another)
  // Uses precomputed Set for O(1) lookup instead of O(n²) scan
  const isSpannedOverFn = useCallback((rowIdx: number, colIdx: number): boolean => {
    return spannedOver.has(`${rowIdx}:${colIdx}`)
  }, [spannedOver])

  if (!hasTablixData(data)) {
    return (
      <div className="flex items-center justify-center h-full text-muted-foreground" data-testid="matrix-empty">
        <span className="text-xs">No data</span>
      </div>
    )
  }

  // Split grid into header rows and body rows
  const numHeaderRows = data.numColHeaderRows || 0
  const headerRows = grid.slice(0, numHeaderRows)
  const bodyRows = grid.slice(numHeaderRows)

  const useVirtual = bodyRows.length > VIRTUAL_ROW_THRESHOLD

  const renderRow = (row: (TablixCell | null)[], rowIdx: number, isHeader: boolean) => {
    // Find the first cell in the row to get row metadata
    const firstCell = row.find(c => c != null)
    const rowKey = firstCell?.rowKey ?? `row-${rowIdx}`
    const rowHeightStyle = !isHeader ? { height: getRowHeight(rowKey) } : undefined
    let isFirstCellInRow = true
    return (
    <tr
      key={rowIdx}
      data-testid="matrix-row"
      data-row-key={firstCell?.rowKey}
      data-row-level={firstCell?.level}
      style={rowHeightStyle}
    >
      {row.map((cell, colIdx) => {
        // Skip cells that are spanned over by other cells
        if (isSpannedOverFn(rowIdx, colIdx)) {
          return null
        }
        
        if (!cell) {
          // Empty cell
          const Tag = isHeader ? 'th' : 'td'
          return (
            <Tag key={colIdx} className="px-2 py-1 text-xs border-b border-r">
              &nbsp;
            </Tag>
          )
        }
        
        const Tag = isHeader ? 'th' : 'td'
        // Apply column width if set — use semantic key for stability across expand/collapse
        const colKey = getStableColumnKey(cell, colIdx)
        const cellStyle: React.CSSProperties = getMatrixColumnWidthStyle({
          columnKey: colKey,
          widths: colWidths,
          mode: columnWidthMode,
          defaultWidth: defaultColWidth,
          minWidth: 40,
        })

        // Apply custom column header / corner background color via inline style
        const headerInlineStyle = getCellInlineStyle(cell, cellStyleCtx)
        if (headerInlineStyle) Object.assign(cellStyle, headerInlineStyle)

        const isRowHeaderCell = cell.role === 'row_header' || cell.role === 'row_group' || cell.role === 'row_block'
        const outlineKind = rowHeaderOutlineStyle?.trim().toLowerCase()
        if (isRowHeaderCell && outlineKind) {
          if (outlineKind.includes('frame')) {
            cellStyle.borderLeft = '2px solid hsl(var(--border))'
            cellStyle.borderRight = '2px solid hsl(var(--border))'
          } else if (outlineKind.includes('stepped')) {
            cellStyle.borderLeft = `${Math.max(1, (cell.level ?? 0) + 1)}px solid hsl(var(--border))`
          } else if (outlineKind.includes('none')) {
            cellStyle.borderLeft = 'none'
          } else {
            cellStyle.borderLeft = '1px solid hsl(var(--border))'
          }
        }

        // Apply indent padding via inline style (replaces dynamic Tailwind classes)
        if ((cell.role === 'row_header' || cell.role === 'row_group' || cell.role === 'row_block') && cell.indent && cell.indent > 0) {
          cellStyle.paddingLeft = getRowHeaderPaddingLeft(cell.indent, densityMode)
        }

        // Band sizing: apply configured width/height from band definitions
        const isBandCol = colIdx < numBandCols && (cell.role === 'row_header_band' || cell.role === 'corner')
        const isBandRow = rowIdx < numBandRows && (cell.role === 'col_header_band' || cell.role === 'corner')
        if (isBandCol && rowBandWidths[colIdx] != null) {
          const bw = bandResizeDelta?.axis === 'row' && bandResizeDelta.bandIndex === colIdx
            ? Math.max(20, (rowBandWidths[colIdx]!) + bandResizeDelta.delta)
            : rowBandWidths[colIdx]!
          cellStyle.width = bw
          cellStyle.minWidth = bw
          cellStyle.maxWidth = bw
        }
        if (isBandRow && colBandHeights[rowIdx] != null) {
          const bh = bandResizeDelta?.axis === 'col' && bandResizeDelta.bandIndex === rowIdx
            ? Math.max(20, (colBandHeights[rowIdx]!) + bandResizeDelta.delta)
            : colBandHeights[rowIdx]!
          cellStyle.height = bh
          cellStyle.minHeight = bh
        }

        // Apply cell rule formatting (lower priority — overridden by design cells)
        const ruleStyle = matchCellRules(cell)
        if (ruleStyle?.bold) cellStyle.fontWeight = 'bold'
        if (ruleStyle?.align) cellStyle.textAlign = ruleStyle.align as React.CSSProperties['textAlign']
        if (ruleStyle?.bg) cellStyle.backgroundColor = ruleStyle.bg
        if (ruleStyle?.fg) cellStyle.color = ruleStyle.fg
        if (ruleStyle?.fontFamily) cellStyle.fontFamily = ruleStyle.fontFamily

        // Apply design cell formatting (highest priority — overrides cell rules)
        const dcFmt = getDesignCellFormat(cell)
        if (dcFmt?.fontWeight === 'bold') cellStyle.fontWeight = 'bold'
        if (dcFmt?.fontStyle === 'italic') cellStyle.fontStyle = 'italic'
        if (dcFmt?.backgroundColor) cellStyle.backgroundColor = dcFmt.backgroundColor
        if (dcFmt?.textColor) cellStyle.color = dcFmt.textColor

        // Apply conditional formatting (server-computed, highest priority for colors)
        if (cell.condFmt) {
          if (cell.condFmt.backColor) cellStyle.backgroundColor = cell.condFmt.backColor
          if (cell.condFmt.fontColor) cellStyle.color = cell.condFmt.fontColor
        }
        // Rotate text for row header bands with rotate flag
        // Uses vertical-rl + 180° rotation to read bottom-to-top
        if (cell.rotate) {
          cellStyle.writingMode = 'vertical-rl'
          cellStyle.transform = 'rotate(180deg)'
          cellStyle.textAlign = 'center'
          cellStyle.verticalAlign = 'middle'
        }
        // Show resize handle on header cells in the last header row (the row just before body)
        const showResizeHandle = isHeader && rowIdx === numHeaderRows - 1
        // Show row resize handle on the first visible cell of each body row
        const showRowResizeHandle = !isHeader && isFirstCellInRow
        if (showRowResizeHandle) isFirstCellInRow = false
        // Band resize handles: right edge for band columns, bottom edge for band rows
        const showBandColResize = isBandCol && cell.role === 'row_header_band' && onBandResize != null
        const showBandRowResize = isBandRow && cell.role === 'col_header_band' && onBandResize != null
        const needsRelative = showResizeHandle || showRowResizeHandle || showBandColResize || showBandRowResize
        return (
          <Tag
            key={colIdx}
            rowSpan={cell.rowSpan || 1}
            colSpan={cell.colSpan || 1}
            className={cn(getCellClasses(cell), needsRelative && 'relative')}
            style={cellStyle}
            onClick={() => handleCellClick(cell)}
            onContextMenu={(e) => handleCellContextMenu(cell, e)}
            data-testid={cell.role === 'row_header' ? 'matrix-rowhdr-cell' : cell.role === 'col_header' ? 'matrix-colhdr-cell' : 'matrix-value-cell'}
            data-role={cell.role}
            data-row-key={cell.rowKey}
            data-col-key={cell.colKey}
            data-measure-name={cell.measureName}
            data-row-level={cell.level}
            data-row-block-index={cell.rowBlockIndex}
            data-col-block-index={cell.colBlockIndex}
            data-row-header-outline={isRowHeaderCell && rowHeaderOutlineStyle ? rowHeaderOutlineStyle : undefined}
          >
            {renderCellContent(cell)}
            {showResizeHandle && (
              <ResizeHandle columnKey={colKey} onResizeStart={handleResizeStart} />
            )}
            {showRowResizeHandle && (
              <RowResizeHandle rowKey={rowKey} onResizeStart={handleRowResizeStart} />
            )}
            {showBandColResize && (
              <div
                className="absolute right-0 top-0 bottom-0 w-1 cursor-col-resize hover:bg-primary/50 z-10"
                onMouseDown={(e) => handleBandResizeStart('row', colIdx, e)}
                data-testid={`band-col-resize-${colIdx}`}
              />
            )}
            {showBandRowResize && (
              <div
                className="absolute left-0 right-0 bottom-0 h-1 cursor-row-resize hover:bg-primary/50 z-10"
                onMouseDown={(e) => handleBandResizeStart('col', rowIdx, e)}
                data-testid={`band-row-resize-${rowIdx}`}
              />
            )}
          </Tag>
        )
      })}
      {/* Explanation column (Phase 10.9) */}
      {hasExplanation && (
        isHeader ? (
          rowIdx === numHeaderRows - 1 ? (
            <ExplanationColumnHeader
              onExpandAll={handleExplExpandAll}
              onCollapseAll={handleExplCollapseAll}
            />
          ) : (
            <th className="bg-amber-50/30 border-b" />
          )
        ) : (
          <ExplanationCell
            node={explPerRow?.[rowIdx - numHeaderRows] ?? null}
            rowIndex={rowIdx - numHeaderRows}
            expanded={explExpandedRows.has(rowIdx - numHeaderRows)}
            onToggle={handleExplToggle}
          />
        )
      )}
    </tr>
    )
  }

  // Build truncation warning message
  const truncationMsg = useMemo(() => {
    if (!truncationInfo) return null
    const parts: string[] = []
    if (truncationInfo.rows && truncationInfo.max_rows) {
      parts.push(`${truncationInfo.max_rows.toLocaleString()} rows`)
    }
    if (truncationInfo.cols && truncationInfo.max_cols) {
      parts.push(`${truncationInfo.max_cols.toLocaleString()} columns`)
    }
    return parts.length > 0 ? `Results limited to ${parts.join(' / ')} for performance safety` : null
  }, [truncationInfo])

  return (
    <div className={cn('h-full overflow-hidden flex flex-col', className)} data-testid="matrix-root">
      {truncationMsg && (
        <div
          className="flex items-center gap-1.5 px-2 py-1 text-xs bg-amber-50 dark:bg-amber-950/30 text-amber-700 dark:text-amber-400 border-b border-amber-200 dark:border-amber-800 shrink-0"
          data-testid="matrix-truncation-warning"
        >
          <span>⚠</span>
          <span>{truncationMsg}</span>
        </div>
      )}
      <div className="flex-1 min-h-0 overflow-hidden">
      {useVirtual ? (
        <VirtualMatrixBody
          headerRows={headerRows}
          bodyRows={bodyRows}
          numHeaderRows={numHeaderRows}
          numCols={data.numCols}
          renderRow={renderRow}
          data={data}
          ctxMenu={ctxMenu}
          setCtxMenu={setCtxMenu}
          visualId={visualId}
          onDrillAction={onDrillAction}
          tableLayoutMode={tableLayoutMode}
          tableWidth={tableWidth}
          columnWidthMode={columnWidthMode}
          moreGranularColumnWidths={moreGranularColumnWidths}
          hasMobileColumnWidths={hasMobileColumnWidths}
          currentRowLevel={currentRowDrillLevel}
          currentColLevel={currentColDrillLevel}
        />
      ) : (
        <div data-testid="matrix-scroll" className="h-full overflow-auto">
          <table
            className="border-collapse text-xs"
            data-testid="matrix-table"
            data-column-width-mode={columnWidthMode}
            data-more-granular-column-widths={moreGranularColumnWidths ? 'true' : 'false'}
            data-mobile-column-widths-preserved={hasMobileColumnWidths ? 'true' : 'false'}
            style={{
              tableLayout: tableLayoutMode,
              width: tableWidth,
            }}
          >
            {numHeaderRows > 0 && (
              <thead className="sticky top-0 z-10 bg-background" data-testid="matrix-thead">
                {headerRows.map((row, rowIdx) => renderRow(row, rowIdx, true))}
              </thead>
            )}
            <tbody data-testid="matrix-tbody">
              {bodyRows.map((row, rowIdx) => renderRow(row, rowIdx + numHeaderRows, false))}
            </tbody>
          </table>
        </div>
      )}

      {/* Cell-level context menu for drill operations (non-virtual mode) */}
      {!useVirtual && (
        <MatrixContextMenu
          visualId={visualId ?? ''}
          cellInfo={ctxMenu?.cellInfo ?? null}
          position={ctxMenu?.position ?? null}
          onClose={() => setCtxMenu(null)}
          onAction={(action, info) => {
            onDrillAction?.(action, info)
            setCtxMenu(null)
          }}
          maxRowLevel={(data.rowDefs?.length ?? 1) - 1}
          maxColLevel={(data.colDefs?.length ?? 1) - 1}
          currentRowLevel={currentRowDrillLevel}
          currentColLevel={currentColDrillLevel}
        />
      )}
      </div>
    </div>
  )
}

/**
 * VirtualMatrixBody — renders header + virtualized body rows via @tanstack/react-virtual.
 * Only used when body row count exceeds VIRTUAL_ROW_THRESHOLD.
 */
function VirtualMatrixBody({
  headerRows,
  bodyRows,
  numHeaderRows,
  numCols: _numCols,
  renderRow,
  data,
  ctxMenu,
  setCtxMenu,
  visualId,
  onDrillAction,
  tableLayoutMode,
  tableWidth,
  columnWidthMode,
  moreGranularColumnWidths,
  hasMobileColumnWidths,
  currentRowLevel,
  currentColLevel,
}: {
  headerRows: (TablixCell | null)[][]
  bodyRows: (TablixCell | null)[][]
  numHeaderRows: number
  numCols: number
  renderRow: (row: (TablixCell | null)[], rowIdx: number, isHeader: boolean) => React.ReactElement
  data: TablixPlan
  ctxMenu: { cellInfo: MatrixCellInfo; position: { x: number; y: number } } | null
  setCtxMenu: (v: { cellInfo: MatrixCellInfo; position: { x: number; y: number } } | null) => void
  visualId?: string
  onDrillAction?: (action: string, cellInfo: MatrixCellInfo) => void
  tableLayoutMode: 'auto' | 'fixed'
  tableWidth: '100%' | 'auto'
  columnWidthMode: string
  moreGranularColumnWidths: boolean
  hasMobileColumnWidths: boolean
  currentRowLevel: number
  currentColLevel: number
}) {
  const scrollRef = useRef<HTMLDivElement>(null)
  const lastScrollTopRef = useRef(0)

  const handleScroll = useCallback((e: React.UIEvent<HTMLDivElement>) => {
    lastScrollTopRef.current = e.currentTarget.scrollTop
  }, [])

  const rowVirtualizer = useVirtualizer({
    count: bodyRows.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => ESTIMATED_ROW_HEIGHT,
    overscan: 10,
  })

  const virtualItems = rowVirtualizer.getVirtualItems()
  const totalSize = rowVirtualizer.getTotalSize()
  const paddingTop = virtualItems.length > 0 ? (virtualItems[0]?.start ?? 0) : 0
  const paddingBottom = virtualItems.length > 0
    ? Math.max(0, totalSize - (virtualItems[virtualItems.length - 1]?.end ?? 0))
    : 0

  useEffect(() => {
    const el = scrollRef.current
    if (!el) return
    if (lastScrollTopRef.current > 0 && Math.abs(el.scrollTop - lastScrollTopRef.current) > 1) {
      el.scrollTop = lastScrollTopRef.current
    }
  }, [bodyRows.length, totalSize])

  return (
    <div
      ref={scrollRef}
      data-testid="matrix-scroll"
      className="h-full overflow-auto"
      onScroll={handleScroll}
    >
      <table
        className="border-collapse text-xs"
        data-testid="matrix-table"
        data-column-width-mode={columnWidthMode}
        data-more-granular-column-widths={moreGranularColumnWidths ? 'true' : 'false'}
        data-mobile-column-widths-preserved={hasMobileColumnWidths ? 'true' : 'false'}
        style={{
          tableLayout: tableLayoutMode,
          width: tableWidth,
        }}
      >
        {headerRows.length > 0 && (
          <thead className="sticky top-0 z-10 bg-background" data-testid="matrix-thead">
            {headerRows.map((row, rowIdx) => renderRow(row, rowIdx, true))}
          </thead>
        )}
        <tbody
          data-testid="matrix-tbody"
          style={{ height: `${totalSize}px` }}
        >
          {virtualItems.length > 0 && (
            <tr
              aria-hidden
              style={{
                height: `${paddingTop}px`,
                visibility: 'hidden',
              }}
            >
              <td colSpan={Math.max(1, _numCols)} style={{ padding: 0, border: 0 }} />
            </tr>
          )}
          {virtualItems.map((virtualRow) => {
            const bodyIdx = virtualRow.index
            const row = bodyRows[bodyIdx]
            return renderRow(row, bodyIdx + numHeaderRows, false)
          })}
          {virtualItems.length > 0 && (
            <tr
              aria-hidden
              style={{
                height: `${paddingBottom}px`,
                visibility: 'hidden',
              }}
            >
              <td colSpan={Math.max(1, _numCols)} style={{ padding: 0, border: 0 }} />
            </tr>
          )}
        </tbody>
      </table>

      <MatrixContextMenu
        visualId={visualId ?? ''}
        cellInfo={ctxMenu?.cellInfo ?? null}
        position={ctxMenu?.position ?? null}
        onClose={() => setCtxMenu(null)}
        onAction={(action, info) => {
          onDrillAction?.(action, info)
          setCtxMenu(null)
        }}
        maxRowLevel={(data.rowDefs?.length ?? 1) - 1}
        maxColLevel={(data.colDefs?.length ?? 1) - 1}
        currentRowLevel={currentRowLevel}
        currentColLevel={currentColLevel}
      />
    </div>
  )
}

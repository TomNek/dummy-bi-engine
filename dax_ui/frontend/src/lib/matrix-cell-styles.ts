/**
 * Shared cell styling for matrix/tablix visuals.
 *
 * Both MatrixVisual (view mode) and MatrixEditMode (edit mode) import
 * `getCellClasses` from this module so that styling changes are applied
 * consistently across both modes.
 */
import { cn } from '@/lib/utils'
import type { TablixCell, CellRole } from '@/types/matrix'
import type React from 'react'

// ---------------------------------------------------------------------------
// Context that getCellClasses needs from the surrounding component
// ---------------------------------------------------------------------------
export interface CellStyleContext {
  /** 'compact' uses smaller padding/font, 'normal' is default */
  densityMode: 'compact' | 'normal'
  /** Gridline rendering: 'none' | 'light' (default) | 'full' */
  gridlineMode: 'none' | 'light' | 'full'
  /** Row-level map (row index → deepest header level covering that row) */
  rowLevelMap: Map<number, number>
  /** Maximum row header level (deepest leaf in the row hierarchy) */
  maxRowLevel: number
  /** Column-level map (col index → deepest header level covering that column) */
  colLevelMap: Map<number, number>
  /** Maximum column header level */
  maxColLevel: number
  /** Column indexes that represent subtotal columns (derived from header cells) */
  subtotalCols?: Set<number>
  /** Number of column-header rows at the top of the grid */
  numColHeaderRows: number
  /** Number of row-header-band columns on the left */
  numRowHeaderBandCols: number
  /** Number of row-header columns */
  numRowHeaderCols: number
  /** Custom column header background color (from PBI import) */
  columnHeaderBackColor?: string | null
}

/**
 * Compute Tailwind CSS classes for a TablixCell based on its role, level,
 * grand-total status, block membership and aggregate context.
 *
 * This is the single source of truth for tablix cell styling.
 */
export function getCellClasses(cell: TablixCell, ctx: CellStyleContext): string {
  const {
    densityMode,
    gridlineMode,
    rowLevelMap,
    maxRowLevel,
    colLevelMap,
    maxColLevel,
    subtotalCols,
    numColHeaderRows,
    numRowHeaderBandCols,
    numRowHeaderCols,
  } = ctx

  // Base padding/text size from density
  const densityClasses = densityMode === 'compact'
    ? ['px-1', 'py-0.5', 'text-[10px]']
    : ['px-2', 'py-1', 'text-xs']

  // Gridline classes
  const gridlineClasses = gridlineMode === 'none'
    ? []
    : gridlineMode === 'full'
      ? ['border', 'border-border']
      : ['border-b', 'border-r', 'border-border/50'] // light (default)

  const classes: string[] = [...densityClasses, ...gridlineClasses]

  const role = cell.role as CellRole
  const isCMB = cell.colBlockIndex !== undefined && cell.colBlockIndex >= 0
  const isRMB = role === 'row_block' || (cell.rowBlockIndex !== undefined && cell.rowBlockIndex >= 0)

  // Corner region: the main corner cell + any band corner/header cells in the
  // top-left area should appear as one unified cell without inner borders.
  const isCornerRegion = role === 'corner'
    || (role === 'row_header_band' && cell.label === '' && cell.row < numColHeaderRows)
    || (role === 'col_header_band' && cell.label === '' && cell.col < numRowHeaderBandCols + numRowHeaderCols)

  switch (role) {
    case 'corner':
      // If custom column header back color is set, skip Tailwind bg (inline style used instead)
      if (!ctx.columnHeaderBackColor) {
        classes.push('bg-muted/60')
      }
      classes.push('font-medium')
      break
    case 'col_header': {
      if (cell.isSubtotal) {
        classes.push('font-bold', 'text-center', 'bg-blue-50/60', 'dark:bg-blue-900/15')
        break
      }
      // If custom back color is set via import, skip Tailwind bg (inline style used instead)
      if (!ctx.columnHeaderBackColor) {
        const headerLevel = cell.level ?? 0
        const bandBg = headerLevel % 2 === 0 ? 'bg-muted' : 'bg-muted/80'
        classes.push(bandBg)
      }
      classes.push('font-medium', 'text-center')
      break
    }
    case 'row_header': {
      // Alternating band backgrounds per row header level (mirrors col_header)
      const rowHeaderLevel = cell.level ?? 0
      const rowBandBg = rowHeaderLevel % 2 === 0 ? 'bg-muted/40' : 'bg-muted/25'
      classes.push(rowBandBg, 'font-medium', 'sticky', 'left-0', 'z-5')
      break
    }
    case 'body':
    case 'detail':
      if (isCMB && isRMB) {
        // Overlap cell (CMB × RMB) — subtle muted tint
        classes.push('bg-muted/10', 'text-right', 'tabular-nums')
      } else {
        classes.push('text-right', 'tabular-nums')
      }
      // CMB grand total columns / base-block (no extra cols/rows) should be bold
      if (cell.isGrandTotal || cell.isBaseBlock) classes.push('font-bold')
      break
    case 'row_subtotal':
    case 'col_subtotal':
    case 'cross_subtotal':
      classes.push('font-bold', 'text-right', 'tabular-nums')
      break
    case 'grand_total':
    case 'col_total': {
      // Grand total cells fall into 3 categories:
      // 1. Column grand total header (in colHeader region) → centered like col headers
      // 2. Row grand total label ("Grand Total" row header) → left-aligned
      // 3. Value cells → right-aligned with tabular numbers
      const hasLabel = cell.label !== undefined
      const hasValue = cell.value !== undefined && cell.value !== null
      const isInHeaderRegion = cell.row < numColHeaderRows
      if (hasLabel && !hasValue && isInHeaderRegion) {
        classes.push('font-bold', 'text-center')
      } else if (hasLabel && !hasValue) {
        classes.push('font-bold')
      } else {
        classes.push('font-bold', 'text-right', 'tabular-nums')
      }
      break
    }
    case 'static_header':
      classes.push('bg-muted', 'font-medium')
      break
    case 'static_value':
      classes.push('text-right', 'tabular-nums')
      break
    case 'col_header_band':
      classes.push('bg-muted/60', 'font-medium', 'text-center', 'italic')
      break
    case 'row_header_band':
      classes.push('bg-muted/60', 'font-medium')
      break
    case 'subtotal':
      classes.push('font-bold', 'text-right', 'tabular-nums')
      break
    case 'col_group':
      if (cell.isSubtotal) {
        classes.push('font-bold', 'text-center', 'bg-blue-50/60', 'dark:bg-blue-900/15')
      } else {
        classes.push('bg-muted', 'font-medium', 'text-center')
      }
      break
    case 'row_group': {
      if (cell.isSubtotal) {
        classes.push('font-bold', 'bg-blue-50/60', 'dark:bg-blue-900/15', 'sticky', 'left-0', 'z-5')
        break
      }
      // Alternating band backgrounds per row group level (mirrors col_header)
      const rowGroupLevel = cell.level ?? 0
      const rowGroupBg = rowGroupLevel % 2 === 0 ? 'bg-muted/40' : 'bg-muted/25'
      classes.push(rowGroupBg, 'font-medium', 'sticky', 'left-0', 'z-5')
      break
    }
    case 'row_block': {
      // Distinguish between label cell (row header) and value cells
      const isLabelCell = cell.label !== undefined && cell.colKey === undefined
      if (isLabelCell) {
        classes.push('bg-muted/30', 'font-medium', 'sticky', 'left-0', 'z-5')
        if (cell.isGrandTotal || cell.isBaseBlock) classes.push('font-bold')
      } else if (isCMB) {
        classes.push('bg-muted/10', 'text-right', 'tabular-nums')
        if (cell.isGrandTotal || cell.isBaseBlock) classes.push('font-bold')
      } else {
        classes.push('text-right', 'tabular-nums')
        if (cell.isGrandTotal || cell.isBaseBlock) classes.push('font-bold')
      }
      break
    }
  }

  // Unified aggregate coloring — one consistent color for all aggregates.
  const isDataLike = role !== 'corner' && role !== 'col_header' && role !== 'col_group'
    && role !== 'row_header_band' && role !== 'col_header_band'
    && role !== 'static_header' && !cell.isBreaker

  if (isDataLike) {
    const rowLevel = rowLevelMap.get(cell.row)
    const colLevel = colLevelMap.get(cell.col)

    const isRowAgg = cell.isGrandTotal
      || cell.isSubtotal
      || (maxRowLevel > 0 && rowLevel != null && rowLevel < maxRowLevel)

    const isSubtotalColumn = !!subtotalCols?.has(cell.col)
    const isColAgg = isSubtotalColumn || (maxColLevel > 0 && colLevel != null && colLevel < maxColLevel)

    const isGrandTotalContext = cell.isGrandTotal
      || role === 'grand_total' || role === 'col_total'
      || cell.isBaseBlock

    if (isGrandTotalContext) {
      for (let i = classes.length - 1; i >= 0; i--) {
        if (classes[i].startsWith('bg-')) classes.splice(i, 1)
      }
      classes.push('bg-blue-100/60', 'dark:bg-blue-900/25')
    } else if (isRowAgg || isColAgg) {
      classes.push('bg-blue-50/60', 'dark:bg-blue-900/15')
    }
  }

  // Breaker cell styling (blank mode CMBs)
  if (cell.isBreaker) {
    classes.push('bg-transparent', 'border-transparent')
  }

  // Interactive styling (view mode only — edit mode handles its own hover/cursor)
  if (cell.isInteractive !== false && (role === 'row_header' || role === 'row_group' || role === 'body' || role === 'detail')) {
    classes.push('cursor-pointer', 'hover:bg-accent/50')
  }

  // Corner region: suppress inner borders so the entire top-left corner looks
  // like one unified cell.
  if (isCornerRegion) {
    const filtered = classes.filter(c => !c.startsWith('border') && !c.startsWith('bg-'))
    filtered.push('border-0', 'bg-muted/60', 'border-r', 'border-b', 'border-border')
    return cn(...filtered)
  }

  return cn(...classes)
}

// ---------------------------------------------------------------------------
// Inline styles for cells needing custom colors (not expressible via Tailwind)
// ---------------------------------------------------------------------------

/**
 * Compute inline styles for cells that need custom colors.
 * Returns undefined when no inline style override is needed.
 */
export function getCellInlineStyle(cell: TablixCell, ctx: CellStyleContext): React.CSSProperties | undefined {
  const role = cell.role as CellRole
  if (role === 'col_header' && !cell.isSubtotal && ctx.columnHeaderBackColor) {
    return { backgroundColor: ctx.columnHeaderBackColor }
  }
  if (role === 'corner' && ctx.columnHeaderBackColor) {
    return { backgroundColor: ctx.columnHeaderBackColor }
  }
  return undefined
}

// ---------------------------------------------------------------------------
// DesignCell → TablixCell conversion for edit mode
// ---------------------------------------------------------------------------

/** Map edit-mode region names to TablixCell CellRole values */
const REGION_TO_ROLE: Record<string, CellRole> = {
  corner: 'corner',
  colHeader: 'col_header',
  rowHeader: 'row_header',
  value: 'body',
  subtotal: 'subtotal',
  grandTotal: 'grand_total',
  colBand: 'col_header_band',
  rowBand: 'row_header_band',
  cmbHeader: 'col_header',
  rmbHeader: 'row_block',
}

/**
 * Minimal DesignCell shape needed for conversion.
 * Import the full type from MatrixEditMode if desired.
 */
export interface DesignCellLike {
  row: number
  col: number
  rowSpan: number
  colSpan: number
  region: string
  text: string
  level?: number
  expandKey?: string
  isExpanded?: boolean
  bandType?: string
  bandId?: string | number | null
}

/**
 * Convert an edit-mode DesignCell to a pseudo-TablixCell suitable for
 * getCellClasses().  Fields not relevant to styling are left undefined.
 */
export function designCellToTablixCell(dc: DesignCellLike): TablixCell {
  const role = REGION_TO_ROLE[dc.region] || 'body'
  const isGT = dc.region === 'grandTotal'
  const isST = dc.region === 'subtotal'

  // For rmbHeader region, the label should be set and colKey left undefined
  // so row_block styling path picks it up as a label cell.
  const isRmbLabel = dc.region === 'rmbHeader'

  return {
    row: dc.row,
    col: dc.col,
    role,
    rowSpan: dc.rowSpan,
    colSpan: dc.colSpan,
    label: dc.text || undefined,
    value: isGT || isST ? undefined : null,
    level: dc.level,
    isExpandable: dc.expandKey !== undefined,
    isExpanded: dc.isExpanded,
    colBlockIndex: dc.bandType === 'colBlock' ? (dc.bandId as number) : undefined,
    rowBlockIndex: dc.bandType === 'rowBlock' ? (dc.bandId as number) : undefined,
    isGrandTotal: isGT,
    isSubtotal: isST,
    isBaseBlock: false,
    // For rmbHeader label cells, leave colKey undefined so row_block label path works
    colKey: isRmbLabel ? undefined : undefined,
  } as TablixCell
}

/**
 * Build a CellStyleContext from a grid of DesignCells.
 */
export function buildEditModeStyleContext(
  grid: DesignCellLike[][],
): CellStyleContext {
  const rowLevelMap = new Map<number, number>()
  let maxRowLevel = -1
  const colLevelMap = new Map<number, number>()
  let maxColLevel = -1

  // Count header rows / band cols
  let numColHeaderRows = 0
  let numRowHeaderBandCols = 0
  let numRowHeaderCols = 0

  for (const row of grid) {
    for (const dc of row) {
      // Row level map from row headers
      if ((dc.region === 'rowHeader' || dc.region === 'rmbHeader') && dc.level != null) {
        maxRowLevel = Math.max(maxRowLevel, dc.level)
        const span = dc.rowSpan ?? 1
        for (let r = dc.row; r < dc.row + span; r++) {
          const prev = rowLevelMap.get(r)
          if (prev == null || dc.level > prev) {
            rowLevelMap.set(r, dc.level)
          }
        }
      }
      // Subtotal rows
      if (dc.region === 'subtotal' && dc.level != null) {
        const span = dc.rowSpan ?? 1
        for (let r = dc.row; r < dc.row + span; r++) {
          if (!rowLevelMap.has(r)) {
            rowLevelMap.set(r, dc.level)
          }
        }
      }
      // Col level map from col headers
      if ((dc.region === 'colHeader' || dc.region === 'cmbHeader') && dc.level != null) {
        maxColLevel = Math.max(maxColLevel, dc.level)
        const span = dc.colSpan ?? 1
        for (let c = dc.col; c < dc.col + span; c++) {
          const prev = colLevelMap.get(c)
          if (prev == null || dc.level > prev) {
            colLevelMap.set(c, dc.level)
          }
        }
      }
      // Count regions for layout metadata
      if (dc.region === 'colHeader' || dc.region === 'cmbHeader' || dc.region === 'colBand' || dc.region === 'corner') {
        numColHeaderRows = Math.max(numColHeaderRows, dc.row + 1)
      }
      if (dc.region === 'rowBand') {
        numRowHeaderBandCols = Math.max(numRowHeaderBandCols, dc.col + 1)
      }
      if (dc.region === 'rowHeader') {
        numRowHeaderCols = Math.max(numRowHeaderCols, dc.col - numRowHeaderBandCols + 1)
      }
    }
  }

  return {
    densityMode: 'normal',
    gridlineMode: 'light',
    rowLevelMap,
    maxRowLevel,
    colLevelMap,
    maxColLevel,
    numColHeaderRows,
    numRowHeaderBandCols,
    numRowHeaderCols: Math.max(numRowHeaderCols, 1),
  }
}

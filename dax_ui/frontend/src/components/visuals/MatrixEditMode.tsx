/**
 * MatrixEditMode - Matrix Template Editor (TablixPlan-based)
 *
 * Renders the SAME TablixPlan grid that MatrixVisual (view mode) uses,
 * guaranteeing 1:1 structural parity for header bands, row/column layout,
 * subtotals, grand totals, and block positioning.
 *
 * Body cell values are replaced with metadata labels (measure names,
 * field names) to indicate the layout structure rather than data.
 *
 * Edit affordances:
 * - Cell selection (click, Ctrl+click, Shift+click, arrow keys)
 * - Design cell formatting (Bold, Italic, Color, Format Cell panel)
 * - Cell rules editor
 * - Inline text editing (double-click / Enter)
 */
import { useCallback, useMemo, useRef, useEffect, useState } from 'react'
import { cn } from '@/lib/utils'
import { useMatrixState } from '@/hooks/useMatrixState'
import { DesignCellEditor, type CellFormat } from '@/components/visuals/DesignCellEditor'
import { CellRulesEditor } from '@/components/visuals/CellRulesEditor'
import { useReportStore, useAppStore } from '@/stores'
import type { VisualInfo } from '@/lib/api'
import type { TablixPlan, TablixCell, CellRole } from '@/types/matrix'
import { designCellIdFromTablixCell, normalizeDesignCellFormats, parseDesignCellId } from '@/lib/matrix-design-ids'
import { getCellClasses as getSharedCellClasses, type CellStyleContext } from '@/lib/matrix-cell-styles'
import { getRowHeaderPaddingLeft } from './matrix-helpers'

interface MatrixEditModeProps {
  visual: VisualInfo
  tablixPlan?: TablixPlan | null
  className?: string
  onToolbarAction?: (action: string, axis?: 'rows' | 'cols') => void
  onExpand?: (rowPath: string[], expanded: boolean, ctx?: { blockIndex?: number }) => void
  onColExpand?: (colPath: string[], expanded: boolean, ctx?: { blockIndex?: number }) => void
}

/**
 * Re-export parseDesignCellId as parseCellIdentity for backward compatibility.
 */
export { parseDesignCellId as parseCellIdentity } from '@/lib/matrix-design-ids'

// ---------------------------------------------------------------------------
// Position-based cell keys (unique per grid position, used for selection)
// ---------------------------------------------------------------------------

function cellPosKey(row: number, col: number): string {
  return `r${row}c${col}`
}

function parseCellPosKey(key: string): { row: number; col: number } | null {
  const m = key.match(/^r(\d+)c(\d+)$/)
  if (!m) return null
  return { row: parseInt(m[1]), col: parseInt(m[2]) }
}

// ---------------------------------------------------------------------------
// TablixCell → design cell ID mapping
// ---------------------------------------------------------------------------

/** Map CellRole → readable region name for the editor panel label */
const ROLE_TO_DISPLAY_REGION: Partial<Record<CellRole, string>> = {
  corner: 'Corner',
  col_header: 'Column Header',
  col_group: 'Column Group',
  row_header: 'Row Header',
  row_group: 'Row Group',
  body: 'Value',
  detail: 'Detail',
  row_subtotal: 'Row Subtotal',
  col_subtotal: 'Column Subtotal',
  cross_subtotal: 'Subtotal',
  grand_total: 'Grand Total',
  col_total: 'Column Total',
  subtotal: 'Subtotal',
  static_header: 'Static Header',
  static_value: 'Static Value',
  col_header_band: 'Column Band',
  row_header_band: 'Row Band',
  row_block: 'Row Block',
}

/**
 * Derive a design cell ID from a TablixCell for formatting persistence.
 * Multiple data cells may share the same design ID (formatting applies to the category).
 */
function tablixCellToDesignId(cell: TablixCell): string {
  return designCellIdFromTablixCell(cell)
}

// ---------------------------------------------------------------------------
// Edit-mode display text
// ---------------------------------------------------------------------------

/**
 * Get the text to show in edit mode for a TablixCell.
 * Body cells show measure names; headers show field names from the interaction metadata.
 */
function editModeText(
  cell: TablixCell,
  interaction?: { row_columns?: Array<{ column: string }>; col_columns?: Array<{ column: string }> } | null,
): string {
  // Helper: look up the field name for a row hierarchy level
  const rowFieldName = (level?: number): string => {
    if (level != null && interaction?.row_columns?.[level]?.column) {
      return interaction.row_columns[level].column
    }
    return 'Row'
  }
  // Helper: look up the field name for a col hierarchy level
  const colFieldName = (level?: number): string => {
    if (level != null && interaction?.col_columns?.[level]?.column) {
      return interaction.col_columns[level].column
    }
    return 'Column'
  }

  switch (cell.role) {
    case 'corner':
    case 'col_header_band':
    case 'row_header_band':
    case 'static_header':
      return cell.label || cell.formatted || ''
    case 'col_header':
    case 'col_group':
      if (cell.isGrandTotal) return 'Grand Total'
      if (cell.isSubtotal) {
        // Column subtotal cell sits at the child level (e.g., Category=1)
        // but represents the parent group subtotal (Brand=0).
        const parentLevel = Math.max(0, (cell.level ?? 1) - 1)
        return `${colFieldName(parentLevel)} Subtotal`
      }
      // CMB header with no additional column grouping — show measure name
      if (cell.colBlockIndex != null && cell.colKey === '__all__') {
        return `[${cell.label || cell.measureName || 'Measure'}]`
      }
      return colFieldName(cell.level)
    case 'row_header':
    case 'row_group':
      if (cell.isGrandTotal) return 'Grand Total'
      if (cell.isSubtotal) return `${rowFieldName(cell.level)} Subtotal`
      return rowFieldName(cell.level)
    case 'row_block':
      // RMB cells use ROW_BLOCK role for both row headers and body cells.
      // Body cells have measureName set; show metadata instead of values.
      if (cell.isGrandTotal && cell.measureName) return `Σ [${cell.measureName}]`
      if (cell.isSubtotal && cell.measureName) return `Σ [${cell.measureName}]`
      if (cell.measureName && cell.value != null) return `[${cell.measureName}]`
      // RMB measure-only row (no additional row grouping) — show measure name
      if (cell.measureName && cell.label === cell.measureName) return `[${cell.measureName}]`
      // RMB row header — show field name in template
      if (cell.isGrandTotal) return 'Grand Total'
      if (cell.isSubtotal) return `${rowFieldName(cell.level)} Subtotal`
      return rowFieldName(cell.level)
      
    case 'body':
    case 'detail':
    case 'static_value':
      if (cell.measureName) return `[${cell.measureName}]`
      return cell.formatted || String(cell.value ?? '')
    case 'row_subtotal':
    case 'subtotal':
      // Row subtotal header (no measureName) → use field name
      if (cell.measureName) return `Σ [${cell.measureName}]`
      return `${rowFieldName(cell.level)} Subtotal`
    case 'col_subtotal':
      if (cell.measureName) return `Σ [${cell.measureName}]`
      return `${colFieldName(cell.level)} Subtotal`
    case 'cross_subtotal':
      if (cell.measureName) return `Σ [${cell.measureName}]`
      return 'Subtotal'
    case 'grand_total':
    case 'col_total':
      if (cell.measureName) return `Σ [${cell.measureName}]`
      return 'Grand Total'
    default:
      return cell.label || cell.formatted || ''
  }
}

// ---------------------------------------------------------------------------
// Template grid builder — deduplicates rows/columns for skeleton view
// ---------------------------------------------------------------------------

/**
 * Build a template grid from the full data grid by collapsing duplicate
 * rows (keeping one per hierarchy level) and columns (one per dimension).
 * Cells keep their original .row/.col properties for style lookups;
 * only spans are adjusted.
 */
function buildTemplateGrid(
  fullGrid: (TablixCell | null)[][],
  cells: TablixCell[],
  numHeaderRows: number,
  numRows: number,
  numCols: number,
  numRowHeaderCols: number,
  numRowHeaderBandCols: number,
): { grid: (TablixCell | null)[][]; spannedOver: Set<string> } {
  if (numRows === 0 || numCols === 0) {
    return { grid: [], spannedOver: new Set() }
  }

  // --- Column-owner map for header rows (accounts for colSpan) ---
  const columnOwner: (TablixCell | null)[][] = Array.from(
    { length: numHeaderRows },
    () => Array(numCols).fill(null),
  )
  for (const cell of cells) {
    if (cell.row >= 0 && cell.row < numHeaderRows) {
      const cs = cell.colSpan || 1
      for (let dc = 0; dc < cs; dc++) {
        const cc = cell.col + dc
        if (cc >= 0 && cc < numCols) columnOwner[cell.row][cc] = cell
      }
    }
  }

  // --- Row deduplication (body rows only) ---
  const totalLeftCols = numRowHeaderBandCols + numRowHeaderCols

  function getRowSig(r: number): string {
    const row = fullGrid[r]
    if (!row) return '__empty__'

    // Aggregate structural properties from ROW HEADER area cells only
    // (cols < totalLeftCols). Data-area cells in subtotal/grand_total
    // rows share the same role but always have level=0, which would
    // mask the true hierarchy level of the structural cell.
    let minLevel = Infinity
    let isSub = false
    let isGrand = false
    let bandIdx = -1
    let rowKeyClass = 'none'
    let rowPathDepth = -1
    let hasRowBlock = false
    let hasMeasure = false
    let foundStructural = false

    for (let c = 0; c < row.length; c++) {
      const cell = row[c]
      if (!cell) continue
      const role = cell.role
      // Subtotal/grand-total flags can appear on data-area cells even when
      // structural cells do not carry the flag. Track these across the full
      // row to prevent subtotal rows from being deduped as regular rows.
      if (cell.isSubtotal) isSub = true
      if (cell.isGrandTotal) isGrand = true
      // Only structural-area cells contribute to level determination.
      // Data-area cells can still set flags (isSub, isGrand, etc.)
      // but their level is ignored to avoid collapsing different
      // hierarchy levels into one signature.
      const isStructuralCol = c < totalLeftCols
      if (isStructuralCol && typeof cell.rowKey === 'string' && cell.rowKey) {
        if (cell.rowKey === '__grand_total__') rowKeyClass = 'grand'
        else if (cell.rowKey.endsWith('__subtotal')) rowKeyClass = 'subtotal'
        else rowKeyClass = 'leaf'
      }
      if (isStructuralCol && Array.isArray(cell.rowPath)) {
        rowPathDepth = Math.max(rowPathDepth, cell.rowPath.length)
      }
      if (role === 'row_header' || role === 'row_group') {
        foundStructural = true
        if (isStructuralCol) {
          const lvl = cell.level ?? 0
          if (lvl < minLevel) minLevel = lvl
        }
        if (cell.rowBlockIndex != null && cell.rowBlockIndex >= 0) bandIdx = cell.rowBlockIndex
      } else if (role === 'row_block') {
        foundStructural = true
        hasRowBlock = true
        if (isStructuralCol) {
          const lvl = cell.level ?? 0
          if (lvl < minLevel) minLevel = lvl
        }
        if (cell.rowBlockIndex != null && cell.rowBlockIndex >= 0) bandIdx = cell.rowBlockIndex
        if (cell.measureName) hasMeasure = true
      } else if (role === 'subtotal' || role === 'row_subtotal' || role === 'col_subtotal' || role === 'cross_subtotal') {
        foundStructural = true
        if (isStructuralCol) {
          const lvl = cell.level ?? 0
          if (lvl < minLevel) minLevel = lvl
        }
        if (cell.rowBlockIndex != null && cell.rowBlockIndex >= 0) bandIdx = cell.rowBlockIndex
        if (cell.measureName) hasMeasure = true
      } else if (role === 'grand_total' || role === 'col_total') {
        foundStructural = true
        if (isStructuralCol) {
          const lvl = cell.level ?? 0
          if (lvl < minLevel) minLevel = lvl
        }
        if (cell.rowBlockIndex != null && cell.rowBlockIndex >= 0) bandIdx = cell.rowBlockIndex
        if (cell.measureName) hasMeasure = true
      } else if (role === 'row_header_band') {
        if (cell.rowBlockIndex != null && cell.rowBlockIndex >= 0) bandIdx = cell.rowBlockIndex
      }
    }

    if (!foundStructural) {
      // Fallback for rows with no structural cells
      const parts: string[] = []
      for (const cell of row) {
        if (cell) parts.push(`${cell.role}:${cell.isSubtotal}:${cell.isGrandTotal}`)
      }
      return parts.join('|')
    }

    return `${hasRowBlock ? 'rb' : 'rh'}:lvl${minLevel === Infinity ? -1 : minLevel}:sub${isSub}:grand${isGrand}:band${bandIdx}:meas${hasMeasure}:rk${rowKeyClass}:rp${rowPathDepth}`
  }

  const keptBodyRows: number[] = []
  const seenRowSigs = new Set<string>()
  for (let r = numHeaderRows; r < numRows; r++) {
    const sig = getRowSig(r)
    if (!seenRowSigs.has(sig)) {
      seenRowSigs.add(sig)
      keptBodyRows.push(r)
    }
  }
  const keptRows = [...Array.from({ length: numHeaderRows }, (_, i) => i), ...keptBodyRows]
  const keptRowSet = new Set(keptRows)

  // --- Column deduplication (data columns only) ---
  function getColSig(c: number): string {
    if (c < totalLeftCols) return `_struct_${c}` // Always keep structural columns
    const parts: string[] = []
    for (let r = 0; r < numHeaderRows; r++) {
      const owner = columnOwner[r]?.[c]
      if (owner) {
        parts.push(`${owner.role}:${owner.level ?? 0}:${owner.isSubtotal ?? false}:${owner.isGrandTotal ?? false}:${owner.colBlockIndex ?? -1}`)
      } else {
        parts.push('_')
      }
    }
    // Factor in body cell band/measure pattern
    if (keptBodyRows.length > 0) {
      const bodyCell = fullGrid[keptBodyRows[0]]?.[c]
      if (bodyCell) {
        parts.push(`bd:${bodyCell.colBlockIndex ?? -1}:${bodyCell.rowBlockIndex ?? -1}`)
      }
    }
    return parts.join('|')
  }

  const keptCols: number[] = []
  const seenColSigs = new Set<string>()
  for (let c = 0; c < numCols; c++) {
    const sig = getColSig(c)
    if (!seenColSigs.has(sig)) {
      seenColSigs.add(sig)
      keptCols.push(c)
    }
  }
  const keptColSet = new Set(keptCols)

  // --- Build template grid ---
  const newNumRows = keptRows.length
  const newNumCols = keptCols.length
  const newGrid: (TablixCell | null)[][] = Array.from(
    { length: newNumRows },
    () => Array(newNumCols).fill(null),
  )
  const newSpanned = new Set<string>()

  for (let newR = 0; newR < keptRows.length; newR++) {
    const oldR = keptRows[newR]
    const origRow = fullGrid[oldR]
    if (!origRow) continue
    for (let newC = 0; newC < keptCols.length; newC++) {
      const oldC = keptCols[newC]
      const cell = origRow[oldC]
      if (!cell) continue

      // Adjust spans: count how many originally-spanned rows/cols survived
      const origRS = cell.rowSpan || 1
      const origCS = cell.colSpan || 1
      let newRS = 0
      for (let dr = 0; dr < origRS; dr++) {
        if (keptRowSet.has(oldR + dr)) newRS++
      }
      let newCS = 0
      for (let dc = 0; dc < origCS; dc++) {
        if (keptColSet.has(oldC + dc)) newCS++
      }
      if (newRS <= 0) newRS = 1
      if (newCS <= 0) newCS = 1

      // Clone cell with adjusted spans (keep original .row/.col for style lookups)
      const templateCell: TablixCell = { ...cell, rowSpan: newRS, colSpan: newCS }
      newGrid[newR][newC] = templateCell

      // Mark spanned-over positions
      for (let dr = 0; dr < newRS; dr++) {
        for (let dc = 0; dc < newCS; dc++) {
          if (dr === 0 && dc === 0) continue
          const sr = newR + dr
          const sc = newC + dc
          if (sr < newNumRows && sc < newNumCols) {
            newSpanned.add(`${sr}:${sc}`)
          }
        }
      }
    }
  }

  return { grid: newGrid, spannedOver: newSpanned }
}

// ---------------------------------------------------------------------------
// Helpers (outside component to avoid re-creation)
// ---------------------------------------------------------------------------

/** Build inline style for a cell, combining format overrides and structural styles */
function buildCellStyle(
  cell: TablixCell,
  fmt: CellFormat | undefined,
  densityMode: 'compact' | 'normal'
): React.CSSProperties {
  const style: React.CSSProperties = {}

  // Design cell format overrides
  if (fmt?.fontFamily) style.fontFamily = fmt.fontFamily
  if (fmt?.fontSize) style.fontSize = fmt.fontSize
  if (fmt?.fontWeight === 'bold') style.fontWeight = 'bold'
  if (fmt?.fontStyle === 'italic') style.fontStyle = 'italic'
  if (fmt?.backgroundColor) style.backgroundColor = fmt.backgroundColor
  if (fmt?.textColor) style.color = fmt.textColor

  // Row header indentation
  if (cell.indent && cell.indent > 0) {
    style.paddingLeft = `${getRowHeaderPaddingLeft(cell.indent, densityMode)}px`
  }

  // Band cell rotation
  if (cell.rotate) {
    style.writingMode = 'vertical-lr'
    style.transform = 'rotate(180deg)'
  }

  return style
}

/** Render the inner content of a cell */
function renderCellContent(
  cell: TablixCell,
  displayText: string,
  isEditing: boolean,
  editingText: string,
  setEditingText: (text: string) => void,
  commitInlineEdit: () => void,
  cancelInlineEdit: () => void,
  designId: string,
  onExpandClick?: (cell: TablixCell, e: React.MouseEvent) => void,
): React.ReactNode {
  // Row/col expandable chevron — must be a real clickable button
  const isRowExpandable = cell.isExpandable &&
    (cell.role === 'row_header' || cell.role === 'row_group' || cell.role === 'row_block')
  const isColExpandable = cell.isExpandable &&
    (cell.role === 'col_header' || cell.role === 'col_group')
  const showChevron = isRowExpandable || isColExpandable

  return (
    <span className="flex items-center overflow-hidden whitespace-nowrap gap-1">
      {/* Expand/collapse chevron — clickable */}
      {showChevron && (
        <button
          className="flex-shrink-0 p-0.5 hover:bg-accent rounded pointer-events-auto"
          onClick={(e) => {
            e.stopPropagation() // Don't trigger cell selection
            onExpandClick?.(cell, e)
          }}
          data-testid={isColExpandable ? 'matrix-col-expand-toggle' : 'matrix-expand-toggle'}
        >
          <span className="inline-flex items-center justify-center w-3 h-3 text-[10px] text-muted-foreground">
            {cell.isExpanded ? '▾' : '▸'}
          </span>
        </button>
      )}
      <span className="overflow-hidden text-ellipsis pointer-events-none">
        {isEditing ? (
          <input
            type="text"
            className="w-full bg-white text-xs border border-primary rounded px-1 py-0 outline-none pointer-events-auto"
            value={editingText}
            onChange={(e) => setEditingText(e.target.value)}
            onKeyDown={(e) => {
              e.stopPropagation()
              if (e.key === 'Enter') commitInlineEdit()
              else if (e.key === 'Escape') cancelInlineEdit()
            }}
            onBlur={commitInlineEdit}
            autoFocus
            data-testid={`inline-edit-${designId}`}
          />
        ) : (
          displayText || '\u00A0'
        )}
      </span>
    </span>
  )
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function MatrixEditMode({ visual, tablixPlan, className, onToolbarAction, onExpand, onColExpand }: MatrixEditModeProps) {
  const rootRef = useRef<HTMLDivElement>(null)
  const cancellingRef = useRef(false)

  const {
    selectedCells,
    selectCell,
    selectRange,
    clearSelection,
    setEditMode,
  } = useMatrixState({ visualId: visual.id })

  // Auto-focus root on mount for keyboard shortcuts
  useEffect(() => { rootRef.current?.focus() }, [])

  // Expand/collapse click on row/col headers
  const handleExpandClick = useCallback((cell: TablixCell, e: React.MouseEvent) => {
    e.stopPropagation()
    const isRow = cell.role === 'row_header' || cell.role === 'row_group' || cell.role === 'row_block'
    if (isRow && cell.isExpandable && cell.rowPath && onExpand) {
      const ctx = cell.rowBlockIndex !== undefined ? { blockIndex: cell.rowBlockIndex } : undefined
      onExpand(cell.rowPath, !cell.isExpanded, ctx)
    } else if (!isRow && cell.isExpandable && cell.colPath && onColExpand) {
      const ctx = cell.colBlockIndex !== undefined ? { blockIndex: cell.colBlockIndex } : undefined
      onColExpand(cell.colPath, !cell.isExpanded, ctx)
    }
  }, [onExpand, onColExpand])

  // ---------------------------------------------------------------------------
  // Build 2D grid from TablixPlan cells (same logic as MatrixVisual)
  // ---------------------------------------------------------------------------

  const hasPlan = !!(tablixPlan && tablixPlan.cells && tablixPlan.cells.length > 0)

  const withDerivedTotals = useCallback((cell: TablixCell): TablixCell => {
    // Design-cell ID must use ONLY the cell's own flags.
    // Row/col def inference is unreliable because row indices shift when
    // columns are expanded (extra header rows inserted), and column-level
    // subtotal flags must not change the design-cell ID.
    return cell
  }, [])

  const { grid, spannedOver } = useMemo(() => {
    if (!hasPlan) return { grid: [] as (TablixCell | null)[][], spannedOver: new Set<string>() }
    const tp = tablixPlan!
    const g: (TablixCell | null)[][] = Array.from(
      { length: tp.numRows },
      () => Array(tp.numCols).fill(null)
    )
    const spanned = new Set<string>()
    for (const cell of tp.cells) {
      if (cell.row >= 0 && cell.row < tp.numRows && cell.col >= 0 && cell.col < tp.numCols) {
        g[cell.row][cell.col] = cell
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
  }, [tablixPlan, hasPlan])

  const isSpannedOver = useCallback(
    (r: number, c: number) => spannedOver.has(`${r}:${c}`),
    [spannedOver]
  )

  // ---------------------------------------------------------------------------
  // Cell style context (same as MatrixVisual)
  // ---------------------------------------------------------------------------

  const { rowLevelMap, maxRowLevel } = useMemo(() => {
    if (!hasPlan) return { rowLevelMap: new Map<number, number>(), maxRowLevel: -1 }
    let maxLevel = -1
    const levelByRow = new Map<number, number>()
    for (const cell of tablixPlan!.cells) {
      if ((cell.role === 'row_header' || cell.role === 'row_group' || cell.role === 'row_block') && cell.level != null) {
        maxLevel = Math.max(maxLevel, cell.level)
        const span = cell.rowSpan ?? 1
        for (let r = cell.row; r < cell.row + span; r++) {
          const prev = levelByRow.get(r)
          if (prev == null || cell.level > prev) levelByRow.set(r, cell.level)
        }
      }
    }
    for (const cell of tablixPlan!.cells) {
      if (cell.isSubtotal && cell.level != null && !levelByRow.has(cell.row)) {
        const span = cell.rowSpan ?? 1
        for (let r = cell.row; r < cell.row + span; r++) {
          if (!levelByRow.has(r)) levelByRow.set(r, cell.level!)
        }
      }
    }
    return { rowLevelMap: levelByRow, maxRowLevel: maxLevel }
  }, [tablixPlan, hasPlan])

  const { colLevelMap, maxColLevel } = useMemo(() => {
    if (!hasPlan) return { colLevelMap: new Map<number, number>(), maxColLevel: -1 }
    let maxLevel = -1
    const levelByCol = new Map<number, number>()
    for (const cell of tablixPlan!.cells) {
      if ((cell.role === 'col_header' || cell.role === 'col_group') && cell.level != null) {
        maxLevel = Math.max(maxLevel, cell.level)
        const span = cell.colSpan ?? 1
        for (let c = cell.col; c < cell.col + span; c++) {
          const prev = levelByCol.get(c)
          if (prev == null || cell.level > prev) levelByCol.set(c, cell.level)
        }
      }
    }
    return { colLevelMap: levelByCol, maxColLevel: maxLevel }
  }, [tablixPlan, hasPlan])

  const subtotalCols = useMemo(() => {
    const cols = new Set<number>()
    if (!hasPlan) return cols
    const headerRows = tablixPlan?.numColHeaderRows || 0
    for (const cell of tablixPlan!.cells) {
      if (!cell.isSubtotal || cell.isGrandTotal) continue
      if (cell.row >= headerRows) continue
      const span = cell.colSpan ?? 1
      for (let c = cell.col; c < cell.col + span; c++) cols.add(c)
    }
    return cols
  }, [tablixPlan, hasPlan])

  const densityMode = (tablixPlan?.properties?.density ?? 'compact') as 'compact' | 'normal'
  const gridlineMode = (tablixPlan?.properties?.gridlines ?? 'light') as 'none' | 'light' | 'full'

  const cellStyleCtx: CellStyleContext = useMemo(() => ({
    densityMode,
    gridlineMode,
    rowLevelMap,
    maxRowLevel,
    colLevelMap,
    maxColLevel,
    subtotalCols,
    numColHeaderRows: tablixPlan?.numColHeaderRows || 0,
    numRowHeaderBandCols: tablixPlan?.numRowHeaderBandCols ?? 0,
    numRowHeaderCols: tablixPlan?.numRowHeaderCols ?? 1,
  }), [densityMode, gridlineMode, rowLevelMap, maxRowLevel, colLevelMap, maxColLevel, subtotalCols, tablixPlan])

  // ---------------------------------------------------------------------------
  // Selection state
  // ---------------------------------------------------------------------------

  const anchorCell = useRef<{ row: number; col: number } | null>(null)
  const focusCell = useRef<{ row: number; col: number } | null>(null)

  // ---------------------------------------------------------------------------
  // Cell format state — initialized from persisted designCells
  // ---------------------------------------------------------------------------

  const initialFormats = useMemo(() => {
    const encodings = visual.encodings as Record<string, unknown> | undefined
    const tablix = encodings?.tablix as Record<string, unknown> | undefined
    const designCells = tablix?.designCells as Record<string, CellFormat> | undefined
    return normalizeDesignCellFormats(designCells)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []) // Initialize once
  const [cellFormats, setCellFormats] = useState<Record<string, CellFormat>>(initialFormats)
  const [showEditor, setShowEditor] = useState(false)
  const [showRulesEditor, setShowRulesEditor] = useState(false)

  // Auto-open Format Cell editor when exactly 1 cell is selected
  const prevSelectedCount = useRef(0)
  useEffect(() => {
    const count = selectedCells.length
    if (count === 1 && prevSelectedCount.current !== 1 && !showRulesEditor) {
      setShowEditor(true)
    }
    if (count === 0) setShowEditor(false)
    prevSelectedCount.current = count
  }, [selectedCells.length, showRulesEditor])

  // Inline editing state
  const [editingCellId, setEditingCellId] = useState<string | null>(null)
  const [editingText, setEditingText] = useState('')
  const updateVisual = useReportStore(s => s.updateVisual)

  // Sync cellFormats to visual encodings in-memory (save-only persistence)
  const isInitialRender = useRef(true)
  useEffect(() => {
    if (isInitialRender.current) { isInitialRender.current = false; return }
    const encodings = (visual.encodings ?? {}) as Record<string, unknown>
    const tablix = (encodings.tablix ?? {}) as Record<string, unknown>
    const prevDesignCells = tablix.designCells as Record<string, CellFormat> | undefined
    if (JSON.stringify(prevDesignCells ?? {}) === JSON.stringify(cellFormats)) return
    const newTablix = { ...tablix, designCells: cellFormats }
    const newEncodings = { ...encodings, tablix: newTablix }
    updateVisual(visual.id, { encodings: newEncodings } as Partial<VisualInfo>)
    useAppStore.getState().setVisualsDirty(true)
  }, [cellFormats, visual.id, updateVisual, visual.encodings])

  // ---------------------------------------------------------------------------
  // Helpers
  // ---------------------------------------------------------------------------

  const getDesignIdAtPos = useCallback((row: number, col: number): string | null => {
    const cell = grid[row]?.[col]
    if (!cell) return null
    return tablixCellToDesignId(cell)
  }, [grid])

  const getSelectedDesignIds = useCallback((): string[] => {
    const ids: string[] = []
    for (const posKey of selectedCells) {
      const pos = parseCellPosKey(posKey)
      if (pos) {
        const designId = getDesignIdAtPos(pos.row, pos.col)
        if (designId) ids.push(designId)
      }
    }
    return [...new Set(ids)]
  }, [selectedCells, getDesignIdAtPos])

  // ---------------------------------------------------------------------------
  // Cell click handler
  // ---------------------------------------------------------------------------

  const handleCellClick = useCallback((posKey: string, e: React.MouseEvent) => {
    e.preventDefault()
    const isMulti = e.ctrlKey || e.metaKey
    const isShift = e.shiftKey
    const pos = parseCellPosKey(posKey)

    if (isShift && anchorCell.current && pos) {
      const { row: r1, col: c1 } = anchorCell.current
      const { row: r2, col: c2 } = pos
      const minR = Math.min(r1, r2), maxR = Math.max(r1, r2)
      const minC = Math.min(c1, c2), maxC = Math.max(c1, c2)
      const rangeIds: string[] = []
      for (let r = minR; r <= maxR; r++) {
        for (let c = minC; c <= maxC; c++) {
          if (!isSpannedOver(r, c) && grid[r]?.[c]) {
            rangeIds.push(cellPosKey(r, c))
          }
        }
      }
      selectRange(rangeIds)
      focusCell.current = pos
    } else {
      selectCell(posKey, isMulti)
      if (pos) { anchorCell.current = pos; focusCell.current = pos }
      if (!isMulti) { setShowEditor(true); setShowRulesEditor(false) }
    }
  }, [selectCell, selectRange, grid, isSpannedOver])

  // Row handle click for row selection
  const handleRowHandleClick = useCallback((rowIdx: number, e: React.MouseEvent) => {
    e.preventDefault()
    const isMulti = e.ctrlKey || e.metaKey
    const cellIds: string[] = []
    const numCols = grid[rowIdx]?.length ?? 0
    for (let c = 0; c < numCols; c++) {
      if (!isSpannedOver(rowIdx, c) && grid[rowIdx][c]) {
        cellIds.push(cellPosKey(rowIdx, c))
      }
    }
    if (isMulti) {
      const existing = new Set(selectedCells)
      cellIds.forEach(id => existing.add(id))
      selectRange(Array.from(existing))
    } else {
      selectRange(cellIds)
    }
  }, [grid, selectedCells, selectRange, isSpannedOver])

  // Column handle click for column selection
  const handleColHandleClick = useCallback((colIdx: number, e: React.MouseEvent) => {
    e.preventDefault()
    const isMulti = e.ctrlKey || e.metaKey
    const cellIds: string[] = []
    const numRows = grid.length
    for (let r = 0; r < numRows; r++) {
      if (!isSpannedOver(r, colIdx) && grid[r]?.[colIdx]) {
        cellIds.push(cellPosKey(r, colIdx))
      }
    }
    if (isMulti) {
      const existing = new Set(selectedCells)
      cellIds.forEach(id => existing.add(id))
      selectRange(Array.from(existing))
    } else {
      selectRange(cellIds)
    }
  }, [grid, selectedCells, selectRange, isSpannedOver])

  // Corner click for select all
  const handleSelectAll = useCallback((e: React.MouseEvent) => {
    e.preventDefault()
    const cellIds: string[] = []
    for (let r = 0; r < grid.length; r++) {
      const numCols = grid[r]?.length ?? 0
      for (let c = 0; c < numCols; c++) {
        if (!isSpannedOver(r, c) && grid[r][c]) {
          cellIds.push(cellPosKey(r, c))
        }
      }
    }
    selectRange(cellIds)
  }, [grid, selectRange, isSpannedOver])

  // ---------------------------------------------------------------------------
  // Keyboard navigation
  // ---------------------------------------------------------------------------

  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (editingCellId) return

    if (e.key === 'Escape') {
      if (showEditor || showRulesEditor) {
        setShowEditor(false); setShowRulesEditor(false)
      } else if (selectedCells.length > 0) {
        clearSelection()
        anchorCell.current = null; focusCell.current = null
      } else {
        setEditMode(false)
      }
      rootRef.current?.focus()
      e.preventDefault()
      return
    }

    // Enter: start inline editing on single selected cell
    if (e.key === 'Enter' && selectedCells.length === 1) {
      const pos = parseCellPosKey(selectedCells[0])
      if (pos) {
        const cell = grid[pos.row]?.[pos.col]
        if (cell) {
          const designId = tablixCellToDesignId(cell)
          setEditingCellId(designId)
          setEditingText(cellFormats[designId]?.label || editModeText(cell, tablixPlan?._interaction))
          e.preventDefault()
          return
        }
      }
    }

    const dirMap: Record<string, { dr: number; dc: number }> = {
      ArrowUp: { dr: -1, dc: 0 },
      ArrowDown: { dr: 1, dc: 0 },
      ArrowLeft: { dr: 0, dc: -1 },
      ArrowRight: { dr: 0, dc: 1 },
    }
    const dir = dirMap[e.key]
    if (!dir) return

    e.preventDefault()
    const extend = e.shiftKey
    let focus = focusCell.current ?? anchorCell.current
    if (!focus && selectedCells.length > 0) {
      focus = parseCellPosKey(selectedCells[0])
    }
    if (!focus) {
      // Nothing selected — start at top-left non-spanned cell
      if (grid.length > 0 && grid[0]?.length > 0) {
        selectCell(cellPosKey(0, 0), false)
        anchorCell.current = { row: 0, col: 0 }
        focusCell.current = { row: 0, col: 0 }
      }
      return
    }

    const numRows = grid.length
    const numCols = grid[0]?.length ?? 0

    // Step in the direction, skipping spanned-over cells
    let tR = focus.row + dir.dr
    let tC = focus.col + dir.dc
    while (tR >= 0 && tR < numRows && tC >= 0 && tC < numCols && isSpannedOver(tR, tC)) {
      tR += dir.dr
      tC += dir.dc
    }
    if (tR < 0 || tR >= numRows || tC < 0 || tC >= numCols) return
    if (isSpannedOver(tR, tC)) return

    if (extend) {
      const anchor = anchorCell.current ?? focus
      const minR = Math.min(anchor.row, tR), maxR = Math.max(anchor.row, tR)
      const minC = Math.min(anchor.col, tC), maxC = Math.max(anchor.col, tC)
      const rangeIds: string[] = []
      for (let r = minR; r <= maxR; r++) {
        for (let c = minC; c <= maxC; c++) {
          if (!isSpannedOver(r, c) && grid[r]?.[c]) rangeIds.push(cellPosKey(r, c))
        }
      }
      selectRange(rangeIds)
      focusCell.current = { row: tR, col: tC }
    } else {
      selectCell(cellPosKey(tR, tC), false)
      anchorCell.current = { row: tR, col: tC }
      focusCell.current = { row: tR, col: tC }
      setShowEditor(true); setShowRulesEditor(false)
    }
  }, [editingCellId, clearSelection, selectedCells, grid, selectCell, selectRange,
      showEditor, showRulesEditor, setEditMode, isSpannedOver, cellFormats])

  // ---------------------------------------------------------------------------
  // Inline editing
  // ---------------------------------------------------------------------------

  const commitInlineEdit = useCallback(() => {
    if (!editingCellId || cancellingRef.current) return
    setCellFormats(prev => ({
      ...prev,
      [editingCellId]: { ...(prev[editingCellId] ?? {}), label: editingText }
    }))
    setEditingCellId(null)
    setEditingText('')
    rootRef.current?.focus()
  }, [editingCellId, editingText])

  const cancelInlineEdit = useCallback(() => {
    cancellingRef.current = true
    setEditingCellId(null)
    setEditingText('')
    rootRef.current?.focus()
    requestAnimationFrame(() => { cancellingRef.current = false })
  }, [])

  // ---------------------------------------------------------------------------
  // Selection info
  // ---------------------------------------------------------------------------

  const selectionInfo = useMemo(() => {
    const count = selectedCells.length
    if (count === 0) return 'No selection'
    if (count === 1) {
      const pos = parseCellPosKey(selectedCells[0])
      if (pos) {
        const cell = grid[pos.row]?.[pos.col]
        if (cell) {
          const region = ROLE_TO_DISPLAY_REGION[cell.role] || cell.role
          return `${region}: ${editModeText(cell, tablixPlan?._interaction)}`
        }
      }
      return '1 cell selected'
    }
    return `${count} cells selected`
  }, [selectedCells, grid])

  // Primary selected cell for the editor
  const singleSelectedCell = useMemo<{
    cell: TablixCell
    designId: string
    displayRegion: string
  } | null>(() => {
    if (selectedCells.length === 0) return null
    const pos = parseCellPosKey(selectedCells[0])
    if (!pos) return null
    const cell = grid[pos.row]?.[pos.col]
    if (!cell) return null
    return {
      cell,
      designId: tablixCellToDesignId(cell),
      displayRegion: ROLE_TO_DISPLAY_REGION[cell.role] || cell.role,
    }
  }, [selectedCells, grid])

  // ---------------------------------------------------------------------------
  // Format change handler — applies to design IDs
  // ---------------------------------------------------------------------------

  const handleFormatChange = useCallback((cellId: string, format: CellFormat) => {
    setCellFormats(prev => {
      const next = { ...prev, [cellId]: format }
      // Apply to all other selected cells too (multi-select support)
      if (selectedCells.length > 1) {
        for (const posKey of selectedCells) {
          const pos = parseCellPosKey(posKey)
          if (pos) {
            const designId = getDesignIdAtPos(pos.row, pos.col)
            if (designId && designId !== cellId) {
              next[designId] = { ...(next[designId] || {}), ...format }
            }
          }
        }
      }
      return next
    })
  }, [selectedCells, getDesignIdAtPos])

  // ---------------------------------------------------------------------------
  // Toolbar actions
  // ---------------------------------------------------------------------------

  const toggleBold = useCallback(() => {
    const ids = getSelectedDesignIds()
    if (ids.length === 0) return
    setCellFormats(prev => {
      const next = { ...prev }
      const anyBold = ids.some(id => prev[id]?.fontWeight === 'bold')
      const newWeight = anyBold ? 'normal' : 'bold'
      for (const id of ids) next[id] = { ...(next[id] || {}), fontWeight: newWeight as 'normal' | 'bold' }
      return next
    })
  }, [getSelectedDesignIds])

  const toggleItalic = useCallback(() => {
    const ids = getSelectedDesignIds()
    if (ids.length === 0) return
    setCellFormats(prev => {
      const next = { ...prev }
      const anyItalic = ids.some(id => prev[id]?.fontStyle === 'italic')
      const newStyle = anyItalic ? 'normal' : 'italic'
      for (const id of ids) next[id] = { ...(next[id] || {}), fontStyle: newStyle as 'normal' | 'italic' }
      return next
    })
  }, [getSelectedDesignIds])

  const cycleColor = useCallback(() => {
    const ids = getSelectedDesignIds()
    if (ids.length === 0) return
    const colorCycle = [undefined, '#fef3c7', '#dbeafe', '#dcfce7', '#fce7f3', '#f3e8ff']
    setCellFormats(prev => {
      const next = { ...prev }
      const firstColor = prev[ids[0]]?.backgroundColor
      const currentIdx = colorCycle.indexOf(firstColor)
      const nextColor = colorCycle[(currentIdx + 1) % colorCycle.length]
      for (const id of ids) next[id] = { ...(next[id] || {}), backgroundColor: nextColor }
      return next
    })
  }, [getSelectedDesignIds])

  // Grid selection routing: band/corner cells trigger row/col/all selection
  const getGridSelectionHandler = useCallback((cell: TablixCell, rowIdx: number, colIdx: number):
    ((e: React.MouseEvent) => void) | null => {
    if (cell.role === 'corner') return handleSelectAll
    if (cell.role === 'row_header_band') return (e) => handleRowHandleClick(rowIdx, e)
    if (cell.role === 'col_header_band') return (e) => handleColHandleClick(colIdx, e)
    // Fallback for layouts without explicit band cells: use left-most row headers
    // and top header rows as selection gutters.
    if ((cell.role === 'row_header' || cell.role === 'row_group' || cell.role === 'row_block') && colIdx === 0) {
      return (e) => handleRowHandleClick(rowIdx, e)
    }
    if ((cell.role === 'col_header' || cell.role === 'col_group') && rowIdx === 0) {
      return (e) => handleColHandleClick(colIdx, e)
    }
    return null
  }, [handleSelectAll, handleRowHandleClick, handleColHandleClick])

  const hasSelection = selectedCells.length > 0
  const selectionIsBold = hasSelection && getSelectedDesignIds().every(id => cellFormats[id]?.fontWeight === 'bold')
  const selectionIsItalic = hasSelection && getSelectedDesignIds().every(id => cellFormats[id]?.fontStyle === 'italic')
  const selectionHasColor = hasSelection && getSelectedDesignIds().some(id => cellFormats[id]?.backgroundColor)

  // ---------------------------------------------------------------------------
  // Cell class builder
  // ---------------------------------------------------------------------------

  const getCellClasses = useCallback((cell: TablixCell, posKey: string): string => {
    const base = getSharedCellClasses(cell, cellStyleCtx)
    const editClasses = [
      base,
      'cursor-cell', 'relative', 'select-none', 'transition-colors',
      'hover:ring-1', 'hover:ring-primary/40', 'hover:bg-primary/5',
    ]
    if (selectedCells.includes(posKey)) {
      editClasses.push('selected', 'ring-2', 'ring-primary', 'ring-inset', 'bg-primary/10')
    }
    return cn(...editClasses)
  }, [cellStyleCtx, selectedCells])

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  const numHeaderRows = tablixPlan?.numColHeaderRows || 0

  return (
    <div
      ref={rootRef}
      className={cn(
        'flex flex-col h-full overflow-hidden bg-background border border-border rounded',
        'focus:outline-2 focus:outline-primary',
        className
      )}
      data-testid="matrix-edit-mode-root"
      tabIndex={0}
      onKeyDown={handleKeyDown}
      onClick={(e) => e.stopPropagation()}
    >
      {/* Toolbar */}
      <div
        className="flex items-center gap-2 px-2 py-1.5 border-b bg-muted/30 flex-shrink-0"
        data-testid="matrix-edit-mode-toolbar"
        onClick={(e) => e.stopPropagation()}
      >
        <button
          className="px-2 py-1 text-xs border rounded disabled:opacity-50 disabled:cursor-not-allowed hover:bg-muted"
          disabled={!hasSelection}
          onClick={() => {
            const cellIds = [...selectedCells]
            const cols = cellIds
              .map(id => parseCellPosKey(id)?.col)
              .filter((c): c is number => c !== undefined)
            const uniqueCols = [...new Set(cols)]
            const encodings = (visual.encodings ?? {}) as Record<string, unknown>
            const tablix = (encodings.tablix ?? {}) as Record<string, unknown>
            const newTablix = {
              ...tablix,
              headerDefine: {
                ...(tablix.headerDefine as Record<string, unknown> ?? {}),
                row: { columns: uniqueCols, cellIds },
              },
            }
            updateVisual(visual.id, { encodings: { ...encodings, tablix: newTablix } } as Partial<VisualInfo>)
            useAppStore.getState().setVisualsDirty(true)
          }}
          data-testid="matrix-edit-mode-btn-define-row-header"
          title={hasSelection ? 'Define selected cells as row headers' : 'Select cells first'}
        >
          Define Row Header
        </button>
        <button
          className="px-2 py-1 text-xs border rounded disabled:opacity-50 disabled:cursor-not-allowed hover:bg-muted"
          disabled={!hasSelection}
          onClick={() => {
            const cellIds = [...selectedCells]
            const rows = cellIds
              .map(id => parseCellPosKey(id)?.row)
              .filter((r): r is number => r !== undefined)
            const uniqueRows = [...new Set(rows)]
            const encodings = (visual.encodings ?? {}) as Record<string, unknown>
            const tablix = (encodings.tablix ?? {}) as Record<string, unknown>
            const newTablix = {
              ...tablix,
              headerDefine: {
                ...(tablix.headerDefine as Record<string, unknown> ?? {}),
                column: { rows: uniqueRows, cellIds },
              },
            }
            updateVisual(visual.id, { encodings: { ...encodings, tablix: newTablix } } as Partial<VisualInfo>)
            useAppStore.getState().setVisualsDirty(true)
          }}
          data-testid="matrix-edit-mode-btn-define-col-header"
          title={hasSelection ? 'Define selected cells as column headers' : 'Select cells first'}
        >
          Define Column Header
        </button>
        <button
          className={cn(
            'px-2 py-1 text-xs border rounded disabled:opacity-50 disabled:cursor-not-allowed hover:bg-muted',
            showEditor && 'bg-accent'
          )}
          disabled={selectedCells.length === 0}
          onClick={() => { setShowEditor(prev => !prev); if (!showEditor) setShowRulesEditor(false) }}
          title={selectedCells.length >= 1 ? 'Open cell format editor' : 'Select cells to format'}
          data-testid="matrix-edit-mode-btn-format-cell"
        >
          Format Cell
        </button>
        <button
          className={cn(
            'px-2 py-1 text-xs border rounded hover:bg-muted',
            showRulesEditor && 'bg-accent'
          )}
          onClick={() => { setShowRulesEditor(prev => !prev); if (!showRulesEditor) setShowEditor(false) }}
          title="Manage cell formatting rules"
          data-testid="matrix-edit-mode-btn-cell-rules"
        >
          Rules
        </button>
        <div className="w-px h-5 bg-border mx-1" />
        <button
          className={cn(
            'px-2 py-1 text-xs border rounded disabled:opacity-50 disabled:cursor-not-allowed hover:bg-muted font-bold',
            selectionIsBold && 'bg-accent'
          )}
          disabled={!hasSelection}
          onClick={toggleBold}
          data-testid="matrix-edit-mode-btn-bold"
          title="Toggle Bold"
          aria-label="Toggle bold"
          aria-pressed={selectionIsBold}
        >
          B
        </button>
        <button
          className={cn(
            'px-2 py-1 text-xs border rounded disabled:opacity-50 disabled:cursor-not-allowed hover:bg-muted italic',
            selectionIsItalic && 'bg-accent'
          )}
          disabled={!hasSelection}
          onClick={toggleItalic}
          data-testid="matrix-edit-mode-btn-italic"
          title="Toggle Italic"
          aria-label="Toggle italic"
          aria-pressed={selectionIsItalic}
        >
          I
        </button>
        <button
          className={cn(
            'px-2 py-1 text-xs border rounded disabled:opacity-50 disabled:cursor-not-allowed hover:bg-muted',
            selectionHasColor && 'ring-2 ring-primary'
          )}
          disabled={!hasSelection}
          onClick={cycleColor}
          data-testid="matrix-edit-mode-btn-color"
          title="Cycle Background Color"
          aria-label="Cycle background color"
        >
          🎨
        </button>
        {onToolbarAction && (
          <>
            <div className="w-px h-5 bg-border mx-1" />
            <button
              className="px-2 py-1 text-xs border rounded hover:bg-muted"
              onClick={() => { onToolbarAction('expand-all') }}
              data-testid="matrix-edit-mode-btn-expand-all"
              title="Expand All"
              aria-label="Expand all rows and columns"
            >
              ⊞ Expand All
            </button>
            <button
              className="px-2 py-1 text-xs border rounded hover:bg-muted"
              onClick={() => { onToolbarAction('collapse-all') }}
              data-testid="matrix-edit-mode-btn-collapse-all"
              title="Collapse All"
              aria-label="Collapse all rows and columns"
            >
              ⊟ Collapse All
            </button>
          </>
        )}
        <span
          className="ml-auto text-xs text-muted-foreground"
          data-testid="matrix-edit-mode-selection-info"
        >
          {selectionInfo}
        </span>
        {selectedCells.length === 0 && (
          <span className="text-xs text-muted-foreground/70 italic" data-testid="matrix-edit-mode-hint">
            Click a cell to select and format it · Esc to exit
          </span>
        )}
        <div className="w-px h-5 bg-border mx-1" />
        <button
          className="px-2 py-1 text-xs border rounded hover:bg-destructive/10 hover:text-destructive hover:border-destructive/30 text-muted-foreground"
          onClick={() => setEditMode(false)}
          data-testid="matrix-edit-mode-btn-exit"
          title="Exit Edit Mode (Esc)"
          aria-label="Exit edit mode"
        >
          ✕ Exit
        </button>
      </div>

      {/* Table + Editor row */}
      <div className="flex flex-row flex-1 overflow-hidden">
        {/* Table container */}
        <div className="flex-1 overflow-auto">
          {!hasPlan ? (
            <div className="flex items-center justify-center h-full text-muted-foreground text-sm">
              Render the visual first to enter edit mode.
            </div>
          ) : (
            <table
              className="border-collapse text-xs"
              style={{ tableLayout: 'auto' }}
              data-testid="matrix-edit-mode-table"
            >
              <thead className="sticky top-0 z-10 bg-background">
                {grid.slice(0, numHeaderRows).map((row, rowIdx) => (
                  <tr key={rowIdx} data-testid="matrix-row">
                    {row.map((cell, colIdx) => {
                      if (isSpannedOver(rowIdx, colIdx)) return null
                      if (!cell) {
                        return <th key={colIdx} className="px-2 py-1 text-xs border-b border-r">&nbsp;</th>
                      }
                      const posKey = cellPosKey(rowIdx, colIdx)
                      const designId = tablixCellToDesignId(withDerivedTotals(cell))
                      const fmt = cellFormats[designId]
                      const cellStyle = buildCellStyle(cell, fmt, densityMode)
                      const displayText = fmt?.label || editModeText(cell, tablixPlan?._interaction)
                      const isEditing = editingCellId === designId
                      const gridSelHandler = getGridSelectionHandler(cell, rowIdx, colIdx)

                      return (
                        <th
                          key={colIdx}
                          rowSpan={cell.rowSpan || 1}
                          colSpan={cell.colSpan || 1}
                          className={cn(
                            getCellClasses(cell, posKey),
                            gridSelHandler && 'cursor-pointer hover:bg-accent/30'
                          )}
                          style={cellStyle}
                          data-testid={`matrix-edit-mode-cell-${rowIdx}-${colIdx}`}
                          data-design-cell-id={designId}
                          data-role={cell.role}
                          data-row-key={cell.rowKey}
                          data-col-key={cell.colKey}
                          data-row-block-index={cell.rowBlockIndex}
                          data-col-block-index={cell.colBlockIndex}
                          onClick={gridSelHandler ?? ((e) => handleCellClick(posKey, e))}
                          onDoubleClick={() => {
                            setEditingCellId(designId)
                            setEditingText(fmt?.label || displayText)
                          }}
                        >
                          {renderCellContent(cell, displayText, isEditing, editingText, setEditingText, commitInlineEdit, cancelInlineEdit, designId, handleExpandClick)}
                        </th>
                      )
                    })}
                  </tr>
                ))}
              </thead>
              <tbody>
                {grid.slice(numHeaderRows).map((row, bodyRowIdx) => {
                  const rowIdx = bodyRowIdx + numHeaderRows
                  return (
                    <tr key={rowIdx} data-testid="matrix-row">
                      {row.map((cell, colIdx) => {
                        if (isSpannedOver(rowIdx, colIdx)) return null
                        if (!cell) {
                          return <td key={colIdx} className="px-2 py-1 text-xs border-b border-r">&nbsp;</td>
                        }
                        const posKey = cellPosKey(rowIdx, colIdx)
                        const designId = tablixCellToDesignId(withDerivedTotals(cell))
                        const fmt = cellFormats[designId]
                        const cellStyle = buildCellStyle(cell, fmt, densityMode)
                        const displayText = fmt?.label || editModeText(cell, tablixPlan?._interaction)
                        const isEditing = editingCellId === designId
                        const gridSelHandler = getGridSelectionHandler(cell, rowIdx, colIdx)

                        return (
                          <td
                            key={colIdx}
                            rowSpan={cell.rowSpan || 1}
                            colSpan={cell.colSpan || 1}
                            className={cn(
                              getCellClasses(cell, posKey),
                              gridSelHandler && 'cursor-pointer hover:bg-accent/30'
                            )}
                            style={cellStyle}
                            data-testid={`matrix-edit-mode-cell-${rowIdx}-${colIdx}`}
                            data-design-cell-id={designId}
                            data-role={cell.role}
                            data-row-key={cell.rowKey}
                            data-col-key={cell.colKey}
                            data-row-block-index={cell.rowBlockIndex}
                            data-col-block-index={cell.colBlockIndex}
                            onClick={gridSelHandler ?? ((e) => handleCellClick(posKey, e))}
                            onDoubleClick={() => {
                              setEditingCellId(designId)
                              setEditingText(fmt?.label || displayText)
                            }}
                          >
                            {renderCellContent(cell, displayText, isEditing, editingText, setEditingText, commitInlineEdit, cancelInlineEdit, designId, handleExpandClick)}
                          </td>
                        )
                      })}
                    </tr>
                  )
                })}
              </tbody>
            </table>
          )}
        </div>

        {/* Design Cell Editor sidebar */}
        {singleSelectedCell && showEditor && (
          <div className="w-64 border-l overflow-auto flex-shrink-0" data-testid="design-cell-editor-panel">
            <DesignCellEditor
              cellId={singleSelectedCell.designId}
              cellRegion={singleSelectedCell.displayRegion}
              cellText={editModeText(singleSelectedCell.cell, tablixPlan?._interaction)}
              format={cellFormats[singleSelectedCell.designId] || {}}
              onChange={handleFormatChange}
              onClose={() => { setShowEditor(false); rootRef.current?.focus() }}
            />
          </div>
        )}
        {/* Cell Rules Editor sidebar */}
        {showRulesEditor && (
          <div className="w-72 border-l overflow-auto flex-shrink-0" data-testid="cell-rules-editor-panel">
            <CellRulesEditor
              visual={visual}
              onClose={() => { setShowRulesEditor(false); rootRef.current?.focus() }}
            />
          </div>
        )}
      </div>
    </div>
  )
}

/**
 * matrix-helpers.ts — Extracted helper functions for MatrixVisual
 *
 * Fixes and improvements:
 * 1. Correct hierarchy depth calculation
 * 2. Proper row header width computation (inline styles, not dynamic Tailwind)
 * 3. Cell click context builder for crossfiltering
 * 4. Empty data guard
 * 5. Column key builder (semantic keys surviving expand/collapse)
 * 6. IBCS graphic name normalization
 */
import type { TablixPlan, TablixCell, CellRole } from '@/types/matrix'

// ---------------------------------------------------------------------------
// 1. Hierarchy Depth Calculation
// ---------------------------------------------------------------------------

/**
 * Compute the maximum hierarchy depth from cell data.
 * Walks all row_header / row_group cells and returns the deepest level found.
 * Returns 0 when there are no row headers (flat table).
 */
export function computeHierarchyDepth(cells: TablixCell[]): number {
  let maxLevel = 0
  for (const cell of cells) {
    if (
      (cell.role === 'row_header' || cell.role === 'row_group') &&
      cell.level != null
    ) {
      maxLevel = Math.max(maxLevel, cell.level)
    }
  }
  return maxLevel
}

/**
 * Compute the maximum column hierarchy depth from cell data.
 */
export function computeColHierarchyDepth(cells: TablixCell[]): number {
  let maxLevel = 0
  for (const cell of cells) {
    if (
      (cell.role === 'col_header' || cell.role === 'col_group') &&
      cell.level != null
    ) {
      maxLevel = Math.max(maxLevel, cell.level)
    }
  }
  return maxLevel
}

// ---------------------------------------------------------------------------
// 2. Row Header Width — inline paddingLeft instead of dynamic Tailwind classes
// ---------------------------------------------------------------------------

/** Base left padding in px for un-indented cells (density: normal) */
const BASE_PADDING_NORMAL = 8 // px-2 = 0.5rem = 8px
/** Base left padding for compact density */
const BASE_PADDING_COMPACT = 4 // px-1 = 0.25rem = 4px
/** Additional padding per indent level */
const INDENT_STEP = 16 // 1rem per level

/**
 * Calculate the inline paddingLeft for a row header cell based on its indent
 * level and density setting.
 *
 * This replaces the dynamic Tailwind class `pl-${value}` pattern which does
 * not work with Tailwind JIT (JIT only detects literal class strings in source).
 */
export function getRowHeaderPaddingLeft(
  indent: number,
  density: 'compact' | 'normal' = 'normal'
): number {
  const basePad = density === 'compact' ? BASE_PADDING_COMPACT : BASE_PADDING_NORMAL
  return basePad + indent * INDENT_STEP
}

// ---------------------------------------------------------------------------
// 3. Cell Click Context Builder
// ---------------------------------------------------------------------------

export interface CrossfilterContext {
  /** The row path segments (e.g., ["Bikes", "Mountain"]) */
  rowPath: string[]
  /** The column path segments (e.g., ["2023"]) */
  colPath: string[]
  /** The row key (e.g., "Bikes__Mountain") */
  rowKey: string | undefined
  /** The column key */
  colKey: string | undefined
  /** The measure name for value cells */
  measureName: string | undefined
  /** The cell role */
  role: CellRole
  /** Whether this cell represents a subtotal */
  isSubtotal: boolean
  /** Whether this cell represents a grand total */
  isGrandTotal: boolean
  /** The raw value */
  value: unknown
}

/**
 * Build a structured crossfilter context from a TablixCell click.
 * Normalizes missing fields and validates that the cell has enough
 * information for meaningful crossfiltering.
 *
 * Returns null if the cell is not suitable for crossfiltering
 * (e.g., corner cells, band headers, breaker cells).
 */
export function buildCrossfilterContext(cell: TablixCell): CrossfilterContext | null {
  const role = cell.role as CellRole

  // Non-interactive roles that should never produce crossfilter events
  const nonInteractiveRoles: CellRole[] = [
    'corner',
    'col_header_band',
    'row_header_band',
  ]
  if (nonInteractiveRoles.includes(role)) return null
  if (cell.isBreaker) return null
  if (cell.isInteractive === false) return null

  return {
    rowPath: cell.rowPath ?? [],
    colPath: cell.colPath ?? [],
    rowKey: cell.rowKey ?? undefined,
    colKey: cell.colKey ?? undefined,
    measureName: cell.measureName ?? undefined,
    role,
    isSubtotal: cell.isSubtotal ?? false,
    isGrandTotal: cell.isGrandTotal ?? false,
    value: cell.value,
  }
}

// ---------------------------------------------------------------------------
// 4. Empty Data Guard
// ---------------------------------------------------------------------------

/**
 * Check whether a TablixPlan contains renderable data.
 * Returns false when:
 * - numRows or numCols is 0
 * - cells array is empty or missing
 * - all cells equal to null (defensive)
 */
export function hasTablixData(data: TablixPlan | null | undefined): boolean {
  if (!data) return false
  if (data.numRows <= 0 || data.numCols <= 0) return false
  if (!data.cells || data.cells.length === 0) return false
  return true
}

// ---------------------------------------------------------------------------
// 5. Semantic Column Key Builder
// ---------------------------------------------------------------------------

/**
 * Build a stable column key for resize state that survives expand/collapse.
 *
 * Uses the cell's colKey (semantic, e.g. "2023__Q1") when available,
 * falling back to positional "col-{index}" only for cells without keys
 * (corner cells, band cells).
 *
 * This prevents the issue where positional keys (col-0, col-1, ...)
 * shift when columns are inserted/removed during expand/collapse,
 * causing stored resize widths to misalign.
 */
export function getStableColumnKey(cell: TablixCell | null, colIdx: number): string {
  if (cell?.colKey) return `ck-${cell.colKey}`
  if (cell?.measureName && cell?.colPath?.length) {
    return `ck-${cell.colPath.join('__')}__${cell.measureName}`
  }
  // Fallback: positional key (only for header/corner cells without semantic keys)
  return `col-${colIdx}`
}

// ---------------------------------------------------------------------------
// 6. IBCS Graphic Name Normalization
// ---------------------------------------------------------------------------

/**
 * Normalize IBCS graphic names between camelCase (backend serialization)
 * and snake_case.
 *
 * The backend sends camelCase values (varianceArrow, statusDot, etc.)
 * matching the Python dataclass field naming convention.
 * This function maps them to a canonical form for the renderer.
 */
const IBCS_GRAPHIC_MAP: Record<string, string> = {
  // camelCase (backend canonical) → renderer key
  varianceArrow: 'variance_arrow',
  statusDot: 'status_dot',
  deviationBar: 'deviation_bar',
  progressBar: 'progress_bar',
  // snake_case passthrough (defensive)
  variance_arrow: 'variance_arrow',
  status_dot: 'status_dot',
  deviation_bar: 'deviation_bar',
  progress_bar: 'progress_bar',
}

/**
 * Normalize an IBCS graphic name to the renderer's internal form.
 * Accepts both camelCase and snake_case inputs.
 * Returns undefined if the name is not recognized.
 */
export function normalizeIbcsGraphic(name: string | undefined): string | undefined {
  if (!name) return undefined
  return IBCS_GRAPHIC_MAP[name]
}

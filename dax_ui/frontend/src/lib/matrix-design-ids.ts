/**
 * matrix-design-ids.ts
 *
 * Single source of truth for matrix design-cell IDs.
 * Ported from the legacy vanilla JS module `dax_ui/static/matrix_design_ids.js`.
 *
 * Design-cell IDs use an 8-part string format:
 *   dc:<bandType>:<bandId>:<region>:<axis>:<level>:<slot>:<kind>
 *
 * Both edit mode (MatrixEditMode) and view mode (MatrixVisual) import from
 * this module. No DOM or React dependencies — pure utility.
 */

// ---------------------------------------------------------------------------
// String literal union types (replace Object.freeze enums from JS)
// ---------------------------------------------------------------------------

/** Logical region of a cell within, the matrix grid. */
export type CellRegion =
  | 'corner'
  | 'rowHeader'
  | 'colHeader'
  | 'value'
  | 'subtotal'
  | 'grandTotal'

/** Band (repetition block) the cell belongs to. */
export type BandType = 'main' | 'rowBlock' | 'colBlock'

/** Axis a header cell is aligned to. */
export type CellAxis = 'none' | 'row' | 'col'

/** Semantic kind of the cell content. */
export type CellKind = 'label' | 'value' | 'placeholder'

// ---------------------------------------------------------------------------
// Interfaces
// ---------------------------------------------------------------------------

/**
 * Parameters accepted by {@link generateDesignCellId}.
 * Every field is optional; sensible defaults are applied.
 */
export interface DesignCellIdParams {
  bandType?: BandType | string
  bandId?: string | number | null
  region?: CellRegion | string
  axis?: CellAxis | string
  level?: number
  slot?: number
  kind?: CellKind | string
}

/**
 * Structured result returned by {@link parseDesignCellId}.
 */
export interface ParsedDesignCellId {
  bandType: string
  bandId: string | null
  region: string
  axis: string
  level: number
  slot: number
  kind: string
}

type LooseRegion =
  | CellRegion
  | 'rowBand'
  | 'colBand'
  | 'rmbHeader'

type LooseKind = CellKind | 'subtotal' | 'grandTotal'

// ---------------------------------------------------------------------------
// Enum-like constant objects (convenience for iteration / lookup)
// ---------------------------------------------------------------------------

/** All valid {@link CellRegion} values. */
export const CELL_REGIONS: readonly CellRegion[] = [
  'corner',
  'rowHeader',
  'colHeader',
  'value',
  'subtotal',
  'grandTotal',
] as const

/** All valid {@link BandType} values. */
export const BAND_TYPES: readonly BandType[] = [
  'main',
  'rowBlock',
  'colBlock',
] as const

/** All valid {@link CellAxis} values. */
export const CELL_AXES: readonly CellAxis[] = ['none', 'row', 'col'] as const

/** All valid {@link CellKind} values. */
export const CELL_KINDS: readonly CellKind[] = [
  'label',
  'value',
  'placeholder',
] as const

// ---------------------------------------------------------------------------
// Core functions
// ---------------------------------------------------------------------------

/**
 * Generate an 8-part design-cell ID string.
 *
 * Format: `dc:<bandType>:<bandId>:<region>:<axis>:<level>:<slot>:<kind>`
 *
 * @param params - Partial cell descriptor. Missing fields receive defaults:
 *   - `bandType`  → `'main'`
 *   - `bandId`    → `'-'` (encoded as dash in the string)
 *   - `region`    → `'value'`
 *   - `axis`      → `'none'`
 *   - `level`     → `0`
 *   - `slot`      → `0`
 *   - `kind`      → `'label'`
 * @returns The encoded design-cell ID string.
 *
 * @example
 * ```ts
 * generateDesignCellId({ region: 'rowHeader', axis: 'row', level: 1 })
 * // => 'dc:main:-:rowHeader:row:1:0:label'
 * ```
 */
export function generateDesignCellId(params: DesignCellIdParams): string {
  const bandType = params.bandType || 'main'
  const bandId =
    params.bandId !== null && params.bandId !== undefined
      ? String(params.bandId)
      : '-'
  const region = params.region || 'value'
  const axis = params.axis || 'none'
  const level =
    params.level !== undefined && params.level !== null
      ? Number(params.level)
      : 0
  const slot =
    params.slot !== undefined && params.slot !== null ? Number(params.slot) : 0
  const kind = params.kind || 'label'

  return `dc:${bandType}:${bandId}:${region}:${axis}:${level}:${slot}:${kind}`
}

/**
 * Parse an 8-part (or legacy 7-part) design-cell ID back into its components.
 *
 * @param id - The design-cell ID string to parse.
 * @returns The parsed components, or `null` if the string is not a valid
 *          design-cell ID.
 *
 * @example
 * ```ts
 * parseDesignCellId('dc:main:-:value:none:0:0:value')
 * // => { bandType: 'main', bandId: null, region: 'value',
 * //      axis: 'none', level: 0, slot: 0, kind: 'value' }
 * ```
 */
export function parseDesignCellId(
  id: string | null | undefined,
): ParsedDesignCellId | null {
  if (!id || typeof id !== 'string') return null
  if (!id.startsWith('dc:')) return null

  const parts = id.slice(3).split(':')

  if (parts.length < 7) {
    // Accept legacy 6-element payload (7 parts minus the `dc:` prefix) with
    // missing kind — default to 'label'.
    if (parts.length === 6) {
      return {
        bandType: parts[0] || 'main',
        bandId: parts[1] === '-' ? null : parts[1],
        region: parts[2] || 'value',
        axis: parts[3] || 'none',
        level: parseInt(parts[4], 10) || 0,
        slot: parseInt(parts[5], 10) || 0,
        kind: 'label',
      }
    }
    return null
  }

  return {
    bandType: parts[0] || 'main',
    bandId: parts[1] === '-' ? null : parts[1],
    region: parts[2] || 'value',
    axis: parts[3] || 'none',
    level: parseInt(parts[4], 10) || 0,
    slot: parseInt(parts[5], 10) || 0,
    kind: parts[6] || 'label',
  }
}

// ---------------------------------------------------------------------------
// Region normalization
// ---------------------------------------------------------------------------

/** Map of loose/alternative region strings to their canonical values. */
const REGION_ALIASES: Record<string, CellRegion> = {
  values: 'value',
  rowhdr: 'rowHeader',
  row_header: 'rowHeader',
  colhdr: 'colHeader',
  col_header: 'colHeader',
  'grand-total': 'grandTotal',
  grand_total: 'grandTotal',
  grandtotal: 'grandTotal',
  'sub-total': 'subtotal',
  sub_total: 'subtotal',
}

function normalizeLooseRegion(raw: string): LooseRegion {
  const lower = String(raw || '').toLowerCase()
  if (lower in REGION_ALIASES) return REGION_ALIASES[lower]
  if (lower === 'rowband' || lower === 'row_band') return 'rowBand'
  if (lower === 'colband' || lower === 'col_band') return 'colBand'
  if (lower === 'rmbheader' || lower === 'rmb_header' || lower === 'rowblock' || lower === 'row_block') return 'rmbHeader'
  return (raw || 'value') as LooseRegion
}

/**
 * Normalize a region string to its canonical {@link CellRegion} value.
 *
 * Handles common alternative spellings such as `'values'` → `'value'`,
 * `'grand-total'` → `'grandTotal'`, etc.
 *
 * @param raw - The raw region string (may use dashes, underscores, or
 *              lowercase variants).
 * @returns The canonical CellRegion string.
 */
export function normalizeRegion(raw: string): CellRegion {
  const lower = raw.toLowerCase()
  if (lower in REGION_ALIASES) {
    return REGION_ALIASES[lower]
  }
  // Return as-is if it already matches a known region
  return raw as CellRegion
}

// ---------------------------------------------------------------------------
// Axis / Kind inference helpers
// ---------------------------------------------------------------------------

/**
 * Infer the default axis from a normalized region when no explicit axis is
 * provided.
 *
 * | Region        | Default axis |
 * |---------------|-------------|
 * | `colHeader`   | `'col'`     |
 * | `rowHeader`   | `'row'`     |
 * | `corner`      | `'none'`    |
 * | `value`       | `'none'`    |
 * | `subtotal`    | `'none'`    |
 * | `grandTotal`  | `'none'`    |
 */
function inferAxis(region: string): CellAxis {
  switch (region) {
    case 'colHeader':
    case 'colBand':
      return 'col'
    case 'rowHeader':
    case 'rowBand':
    case 'rmbHeader':
      return 'row'
    default:
      return 'none'
  }
}

/**
 * Infer the default kind from a normalized region when no explicit kind is
 * provided.
 *
 * | Region        | Default kind     |
 * |---------------|-----------------|
 * | `rowHeader`   | `'label'`       |
 * | `colHeader`   | `'label'`       |
 * | `corner`      | `'label'`       |
 * | `value`       | `'value'`       |
 * | `subtotal`    | `'placeholder'` |
 * | `grandTotal`  | `'placeholder'` |
 */
function inferKind(region: string): CellKind {
  switch (region) {
    case 'rowHeader':
    case 'colHeader':
    case 'corner':
      return 'label'
    case 'value':
      return 'value'
    case 'subtotal':
    case 'grandTotal':
      return 'placeholder'
    default:
      return 'label'
  }
}

function normalizeKind(kind: string, region: string): LooseKind {
  const lower = String(kind || '').toLowerCase()
  if (!lower || lower === 'placeholder') {
    if (region === 'subtotal') return 'subtotal'
    if (region === 'grandTotal') return 'grandTotal'
    return inferKind(region)
  }
  if (lower === 'subtotal') return 'subtotal'
  if (lower === 'grandtotal' || lower === 'grand_total') return 'grandTotal'
  if (lower === 'value') return 'value'
  return 'label'
}

function stableSlotFromText(text: string): number {
  let hash = 2166136261
  for (let i = 0; i < text.length; i++) {
    hash ^= text.charCodeAt(i)
    hash = Math.imul(hash, 16777619)
  }
  return Math.abs(hash >>> 0) % 1000000
}

function classifyKey(key: string | undefined): string {
  if (!key) return 'none'
  const lower = key.toLowerCase()
  if (lower === '__col_grand_total__' || lower.includes('grand_total')) return 'grand_total'
  if (lower === '__all__') return 'all'
  if (lower.includes('subtotal') || lower.includes('__sub')) return 'subtotal'
  return 'member'
}

function normalizeMeasureBlockColKey(key: string): string {
  if (!key) return ''
  const lower = key.toLowerCase()
  if (lower === '__col_grand_total__' || lower === '__all__') return lower
  const sep = key.indexOf('__')
  if (sep > 0) return key.slice(0, sep)
  return key
}

function baseColBucket(colKey: string): 'parent' | 'child' {
  if (!colKey) return 'parent'
  const lower = colKey.toLowerCase()
  // System keys like __col_grand_total__, __all__ are never leaf children
  if (lower.startsWith('__')) return 'parent'
  // Expanded leaf columns have form "Parent__Child" (separator after pos 0)
  const sep = lower.indexOf('__')
  if (sep > 0 && !lower.includes('__subtotal')) return 'child'
  return 'parent'
}

function valueScopeSignature(cell: {
  role: string
  level?: number
  isSubtotal?: boolean
  isGrandTotal?: boolean
  measureName?: string
  colKey?: string
  rowPath?: string[]
  colPath?: string[]
  rowBlockIndex?: number
  colBlockIndex?: number
}): string {
  // Normalize subtotal roles to 'detail' so expanded subtotal columns
  // produce the same slot hash as their parent column in edit mode.
  // The region redirect already maps subtotal → value; the role used in
  // the slot hash must also match so the painted format is found.
  let role = String(cell.role || '')
  if (role === 'subtotal' || role === 'col_subtotal' || role === 'cross_subtotal') {
    role = 'detail'
  }
  const level = Number.isFinite(cell.level) ? Number(cell.level) : -1
  const subtotal = 0
  const grandTotal = cell.isGrandTotal ? 1 : 0
  const measure = typeof cell.measureName === 'string' ? cell.measureName : ''
  const colKey = typeof cell.colKey === 'string' ? cell.colKey : ''
  // normalizedColKey is always '' so ALL columns in the same row share one
  // design-cell ID (painting one column paints all).
  const normalizedColKey = ''
  const colKeyClass = grandTotal ? classifyKey(colKey) : 'member'
  // Use colBucket for ALL cells (including measure blocks) so that expanded
  // leaf columns get a different slot from parent/subtotal columns.
  const colBucket = baseColBucket(colKey)

  return [
    `role=${role}`,
    `level=${level}`,
    `subtotal=${subtotal}`,
    `grand=${grandTotal}`,
    // rowDepth/colDepth are always -1 so that expanding a column does not
    // change the slot hash.  The colBucket field already differentiates
    // expanded leaves from parents/subtotals.
    `rowDepth=${-1}`,
    `colDepth=${-1}`,
    `colBucket=${colBucket}`,
    `colKeyClass=${colKeyClass}`,
    `colKey=${normalizedColKey}`,
    `measure=${measure}`,
    `rbi=${cell.rowBlockIndex ?? -1}`,
    `cbi=${cell.colBlockIndex ?? -1}`,
  ].join('|')
}

// ---------------------------------------------------------------------------
// cellIdentity() convenience wrapper
// ---------------------------------------------------------------------------

/**
 * High-level convenience wrapper that accepts simpler, more forgiving
 * parameters and produces a full 8-part design-cell ID.
 *
 * Features beyond raw {@link generateDesignCellId}:
 * - **Region normalization**: `'values'` → `'value'`, `'grand-total'` →
 *   `'grandTotal'`, etc.
 * - **Axis inference**: if `axis` is omitted, it is inferred from the region
 *   (e.g. `colHeader` → `'col'`).
 * - **Kind inference**: if `kind` is omitted, it is inferred from the region
 *   (e.g. `value` → `'value'`, `subtotal` → `'placeholder'`).
 *
 * @param params - Cell descriptor with at minimum a `region`.
 * @returns The encoded 8-part design-cell ID string.
 *
 * @example
 * ```ts
 * cellIdentity({ region: 'rowHeader', level: 2 })
 * // => 'dc:main:-:rowHeader:row:2:0:label'
 *
 * cellIdentity({ region: 'grand-total' })
 * // => 'dc:main:-:grandTotal:none:0:0:placeholder'
 *
 * cellIdentity({ region: 'values', slot: 1 })
 * // => 'dc:main:-:value:none:0:1:value'
 * ```
 */
export function cellIdentity(params: {
  region: string
  bandType?: string
  bandId?: string | number | null
  axis?: string
  level?: number
  slot?: number
  kind?: string
}): string {
  const region = normalizeRegion(params.region)
  const axis = params.axis ?? inferAxis(region)
  const kind = params.kind ?? inferKind(region)

  return generateDesignCellId({
    bandType: params.bandType,
    bandId: params.bandId,
    region,
    axis,
    level: params.level,
    slot: params.slot,
    kind,
  })
}

// ---------------------------------------------------------------------------
// Migration helper
// ---------------------------------------------------------------------------

/**
 * Attempt to detect and migrate old 4-part format IDs
 * (`dc:<region>:<rowKey>:<colKey>`) to the new 8-part format.
 *
 * Returns the original ID unchanged if it is already in 8-part format or if
 * the string is unrecognized.
 *
 * Since the old format lacks explicit bandType / axis / level / slot / kind,
 * reasonable defaults are applied:
 * - `bandType` → `'main'`
 * - `bandId`   → `null` (`'-'` in the encoded string)
 * - `axis`     → inferred from region
 * - `level`    → `0`
 * - `slot`     → `0`
 * - `kind`     → inferred from region
 *
 * @param oldId - A design-cell ID that may be in old 4-part or new 8-part
 *                format.
 * @returns A design-cell ID guaranteed to be in 8-part format (best-effort
 *          for old IDs), or the original string if migration is not possible.
 *
 * @example
 * ```ts
 * migrateOldCellId('dc:value:row0:col1')
 * // => 'dc:main:-:value:none:0:0:value'
 *
 * migrateOldCellId('dc:main:-:value:none:0:0:value')
 * // => 'dc:main:-:value:none:0:0:value'  (unchanged)
 * ```
 */
export function migrateOldCellId(oldId: string): string {
  if (!oldId || typeof oldId !== 'string' || !oldId.startsWith('dc:')) {
    return oldId
  }

  const parts = oldId.slice(3).split(':')

  // Already 8-part (7 segments after removing `dc:` prefix) or 7-part legacy
  if (parts.length >= 6) {
    return oldId
  }

  // Old compact formats (best-effort):
  // - dc:<region>:<rowKey>:<colKey>         → 3 segments
  // - dc:<region>:<a>:<b>:<c>               → 4 segments
  if (parts.length === 3 || parts.length === 4) {
    const rawRegion = parts[0]
    const region = normalizeLooseRegion(rawRegion)
    const axis = inferAxis(region)
    const kind = normalizeKind('', region)

    return generateDesignCellId({
      bandType: 'main',
      bandId: null,
      region,
      axis,
      level: 0,
      slot: 0,
      kind,
    })
  }

  // Unrecognized part count — return as-is
  return oldId
}

export function normalizeDesignCellFormats<T>(
  raw: Record<string, T> | null | undefined,
): Record<string, T> {
  if (!raw || typeof raw !== 'object') return {}
  const out: Record<string, T> = {}

  for (const [rawKey, value] of Object.entries(raw)) {
    const migrated = migrateOldCellId(rawKey)
    const parsed = parseDesignCellId(migrated)
    if (!parsed) {
      out[rawKey] = value
      continue
    }

    const region = normalizeLooseRegion(parsed.region)
    const axisRaw = String(parsed.axis || '').toLowerCase()
    const axis = axisRaw === 'row' || axisRaw === 'col' || axisRaw === 'none'
      ? (axisRaw as CellAxis)
      : inferAxis(region)
    const kind = normalizeKind(parsed.kind, region)
    const rawLevel = Number.isFinite(parsed.level) ? Math.max(0, parsed.level) : 0
    const level = region === 'value' ? 0 : rawLevel
    const slot = Number.isFinite(parsed.slot) ? Math.max(0, parsed.slot) : 0

    const canonical = generateDesignCellId({
      bandType: parsed.bandType || 'main',
      bandId: parsed.bandId,
      region,
      axis,
      level,
      slot,
      kind,
    })
    out[canonical] = value
  }

  return out
}

export function designCellIdFromTablixCell(cell: {
  role: string
  rowKey?: string
  colKey?: string
  rowPath?: string[]
  colPath?: string[]
  level?: number
  value?: unknown
  formatted?: string
  isSubtotal?: boolean
  isGrandTotal?: boolean
  measureName?: string
  rowBlockIndex?: number
  colBlockIndex?: number
}): string {
  const role = String(cell.role || '')
  const isSubtotal = !!cell.isSubtotal
  const isGrandTotal = !!cell.isGrandTotal

  let bandType: string = 'main'
  let bandId: string | number | null = null
  if (cell.rowBlockIndex != null && cell.rowBlockIndex >= 0) {
    bandType = 'rowBlock'
    bandId = cell.rowBlockIndex
  } else if (cell.colBlockIndex != null && cell.colBlockIndex >= 0) {
    bandType = 'colBlock'
    bandId = cell.colBlockIndex
  }

  const isMeasureBlock = (cell.rowBlockIndex ?? -1) >= 0 || (cell.colBlockIndex ?? -1) >= 0

  const rowBlockValue = role === 'row_block'
    && (cell.colKey != null || cell.value !== undefined || cell.formatted !== undefined)

  let region: LooseRegion
  switch (role) {
    case 'corner': region = 'corner'; break
    case 'col_header':
    case 'col_group':
    case 'static_header': region = 'colHeader'; break
    case 'row_header':
    case 'row_group': region = 'rowHeader'; break
    case 'row_header_band': region = 'rowBand'; break
    case 'col_header_band': region = 'colBand'; break
    case 'row_block': region = rowBlockValue ? 'value' : 'rmbHeader'; break
    case 'row_subtotal':
    case 'col_subtotal':
    case 'cross_subtotal':
    case 'subtotal': region = 'subtotal'; break
    case 'grand_total':
    case 'col_total': region = 'grandTotal'; break
    case 'body':
    case 'detail':
    case 'static_value':
    default: region = 'value'; break
  }

  // Column-subtotal value cells: the backend promotes expanded subtotal
  // column cells to role SUBTOTAL / COL_SUBTOTAL, which maps them to
  // region 'subtotal'.  Edit mode has no 'subtotal' region, so these cells
  // would never match any painted format.  Redirect them to 'value' so
  // they share the same design-cell ID family as regular value cells.
  // The colBucket ('parent' vs 'child') already differentiates subtotal
  // columns from expanded leaf columns in the slot hash.
  if (region === 'subtotal') {
    region = 'value'
  }
  // CMB/RMB grand-total column cells: the backend promotes them to
  // GRAND_TOTAL role.  In measure blocks this is wrong — redirect to
  // 'value'.  In the main band, grandTotal is a paintable edit-mode
  // region so we keep it.
  if (isMeasureBlock && region === 'grandTotal') {
    region = 'value'
  }

  let axis: CellAxis = inferAxis(region)
  if (region === 'value') axis = 'none'

  // Kind logic:
  // - 'value' region → always kind 'value' (subtotal/GT columns share the
  //   parent column's design-cell ID via the colBucket mechanism).
  // - 'grandTotal' region → matching kind so it can be painted
  //   independently from regular cells.
  // - All header-like regions (colHeader, rowHeader, rmbHeader, corner,
  //   colBand, rowBand) → always kind 'label'.  The isGrandTotal /
  //   isSubtotal cell flags must NOT bleed into the kind for headers,
  //   otherwise subtotal/GT column headers get a different design-cell ID
  //   from their non-subtotal siblings (can't paint them together).
  // Note: 'subtotal' region is always redirected to 'value' above, so
  // it never reaches this point.
  let kind: LooseKind = 'label'
  if (region === 'value') {
    kind = 'value'
  } else if (region === 'grandTotal') {
    kind = 'grandTotal'
  }

  let slot = 0
  if (region === 'value') {
    slot = stableSlotFromText(valueScopeSignature(cell))
  }

  const level = region === 'value' ? 0 : (cell.level ?? 0)

  return generateDesignCellId({
    bandType,
    bandId,
    region,
    axis,
    level,
    slot,
    kind,
  })
}

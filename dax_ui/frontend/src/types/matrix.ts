/**
 * Matrix/Tablix data types from the backend
 * These match the TablixPlan Python dataclass structure
 */

// Cell roles - matches Python CellRole enum
export type CellRole = 
  | 'corner'
  | 'col_header'
  | 'col_group'
  | 'row_header'
  | 'row_group'
  | 'body'
  | 'detail'
  | 'row_subtotal'
  | 'col_subtotal'
  | 'cross_subtotal'
  | 'subtotal'
  | 'grand_total'
  | 'col_total'
  | 'static_header'
  | 'static_value'
  | 'col_header_band'
  | 'row_header_band'
  | 'row_block'

export interface TablixCell {
  row: number
  col: number
  role: CellRole
  rowSpan?: number
  colSpan?: number
  rowPath?: string[]
  colPath?: string[]
  rowKey?: string
  colKey?: string
  value?: unknown
  formatted?: string
  label?: string
  level?: number
  indent?: number
  isExpandable?: boolean
  isExpanded?: boolean
  isSubtotal?: boolean
  isGrandTotal?: boolean
  isInteractive?: boolean
  measureName?: string
  formatString?: string
  rowBlockIndex?: number
  colBlockIndex?: number
  barSpec?: {
    pct?: number
    width?: number
    value?: number
    min?: number
    max?: number
    positive?: boolean
    direction?: 'left' | 'right'
    color?: string
  }
  isBreaker?: boolean
  rotate?: boolean
  /** True for CMB/RMB cells in base/base_calc mode (grand-total-equivalent coloring) */
  isBaseBlock?: boolean
  /** Conditional formatting applied by the backend engine */
  condFmt?: {
    fontColor?: string
    backColor?: string
    icon?: string
    iconLayout?: string
    hideText?: boolean
  }
}

export interface TablixRegion {
  startRow: number
  startCol: number
  endRow: number
  endCol: number
}

export interface TablixRowDef {
  index: number
  rowKey?: string
  level?: number
  isSubtotal?: boolean
  isGrandTotal?: boolean
  rowPath?: string[]
}

export interface TablixColDef {
  index: number
  colKey?: string
  level?: number
  isSubtotal?: boolean
  isGrandTotal?: boolean
  colPath?: string[]
  measureName?: string
}

/** Style properties for cell formatting rules */
export interface CellFormattingStyle {
  text?: string
  bold?: boolean
  align?: 'left' | 'center' | 'right'
  bg?: string
  fg?: string
  fontFamily?: string
  numberStyle?: 'decimal' | 'currency' | 'percent'
  decimalPlaces?: number
  ibcsGraphic?: 'varianceArrow' | 'statusDot' | 'deviationBar' | 'progressBar' | 'variance_arrow' | 'status_dot' | 'deviation_bar' | 'progress_bar'
}

/** Declarative cell formatting rule — matched against cells by region/role/measure/path */
export interface CellFormattingRule {
  id: string
  label?: string
  enabled?: boolean
  region?: string
  role?: string
  measureId?: string
  rowPathPrefix?: string[]
  colPathPrefix?: string[]
  style?: CellFormattingStyle
}

/** Band definition for row header band columns */
export interface RowHeaderBandDef {
  bandType?: string
  label?: string
  pathLevel?: number
  measureId?: string
  width?: number
  appliesTo?: string[]
  spanScope?: 'main' | 'all'
  spanBlocks?: string[]
  merge?: boolean
  rotate?: boolean
  displayLevel?: number
}

/** Band definition for col header band rows */
export interface ColHeaderBandDef {
  bandType?: string
  label?: string
  pathLevel?: number
  measureId?: string
  height?: number
  spanScope?: 'main' | 'all'
  spanBlocks?: string[]
  displayLevel?: number
}

export interface TablixProperties {
  showRowGrandTotal?: boolean
  showColGrandTotal?: boolean
  showSubtotals?: boolean
  showColSubtotals?: boolean
  suppressBlankCols?: boolean
  rowGrandTotalPosition?: 'first' | 'last'
  colGrandTotalPosition?: 'first' | 'last'
  subtotalPosition?: 'before' | 'after'
  subtotalPlacement?: 'before_children' | 'after_children'
  grandTotalVisibility?: 'both' | 'rows' | 'cols' | 'none'
  repeatRowHeaders?: boolean
  repeatColumnHeaders?: boolean
  gridlines?: 'none' | 'light' | 'full'
  density?: 'compact' | 'normal'
  rowHeaderWidthMode?: 'auto' | 'fixed'
  columnWidthMode?: 'fit_to_content' | 'grow_to_fit' | 'fixed' | string
  moreGranularColumnWidths?: boolean
  autofitColumns?: boolean
  autofitRows?: boolean
  snapColumnsToFit?: boolean
  defaultColumnWidth?: number
  defaultRowHeight?: number
  /** Column header background color (from PBI import or user setting) */
  columnHeaderBackColor?: string | null
  /** Initial column widths from PBI import (key: "Table.Field" → width in px) */
  initialColumnWidths?: Record<string, number>
  /** Explicit runtime/editor column widths keyed by stable column key or imported metadata key */
  columnWidths?: Record<string, number>
  /** Preserved Report Documentation matrix column widths */
  matrixColumnWidths?: Record<string, number>
  /** More Granular leaf-level column widths keyed by imported leaf/path keys */
  leafColumnWidths?: Record<string, number>
  /** Mobile layout column widths are preserved but do not affect desktop rendering */
  mobileColumnWidths?: Record<string, number>
  /** Row header band column definitions */
  rowHeaderBands?: RowHeaderBandDef[]
  /** Column header band row definitions */
  colHeaderBands?: ColHeaderBandDef[]
  /** Declarative cell formatting rules — applied in order, later rules override */
  cellRules?: CellFormattingRule[]
}

export interface TablixInteraction {
  row_columns: Array<{ type: string; table: string; column: string }>
  col_columns: Array<{ type: string; table: string; column: string }>
  key_joiner: string
  subtotal_suffix: string
  row_grand_total_key: string
  col_grand_total_key: string
  all_key: string
}

export interface TablixPlan {
  numRows: number
  numCols: number
  numColHeaderRows: number
  numRowHeaderCols: number
  numStaticLeftCols?: number
  numStaticRightCols?: number
  numRowHeaderBandCols?: number
  numColHeaderBandRows?: number
  cells: TablixCell[]
  corner?: TablixRegion
  colHeaders?: TablixRegion
  rowHeaders?: TablixRegion
  body?: TablixRegion
  staticLeft?: TablixRegion
  staticRight?: TablixRegion
  rowHeaderBands?: TablixRegion
  colHeaderBands?: TablixRegion
  rowDefs?: TablixRowDef[]
  colDefs?: TablixColDef[]
  properties?: TablixProperties
  _interaction?: TablixInteraction
  debug?: Record<string, unknown>
}

// Extended matrix response that includes tablix/tablix_plan
export interface MatrixRenderResponse {
  tablix_plan?: TablixPlan
  tablix?: TablixPlan
  columns?: string[]
  rows?: Array<Record<string, unknown>>
  _interaction?: TablixInteraction
  error?: string
}

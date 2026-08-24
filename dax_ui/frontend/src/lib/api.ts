/**
 * API client for the DAX runtime backend
 * All requests go through Vite's proxy at /runtime/*
 */

const BASE_URL = '/runtime'

/**
 * Desktop token injected by the Python backend into the HTML <head>.
 * Present only in desktop (Tauri/PyInstaller) mode; empty in dev.
 */
function getDesktopToken(): string {
  return (window as any).__DESKTOP_TOKEN__ ?? ''
}

interface ApiResponse<T> {
  data?: T
  error?: string
  status?: number
}

// ── Request deduplication ──────────────────────────────────────────────
// Multiple React components often mount simultaneously and fire identical
// GET requests (e.g., /runtime/slicers, /runtime/field_parameters).
// This layer ensures that concurrent identical GET requests share a single
// in-flight fetch, and caches the result for a short TTL so that
// near-simultaneous callers avoid redundant network round-trips.

const DEDUP_TTL_MS = 2_000 // cache resolved value for 2 s

interface DedupEntry<T> {
  promise: Promise<ApiResponse<T>>
  resolvedAt?: number          // timestamp when the promise resolved
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const _dedupCache = new Map<string, DedupEntry<any>>()

/** Evict stale entries lazily (called on every dedup-eligible request). */
function _dedupEvict() {
  const now = Date.now()
  for (const [key, entry] of _dedupCache) {
    if (entry.resolvedAt !== undefined && now - entry.resolvedAt > DEDUP_TTL_MS) {
      _dedupCache.delete(key)
    }
  }
}

/** Force-clear the dedup cache (e.g. after Save All or project switch). */
export function clearApiDedupCache() {
  _dedupCache.clear()
}

async function apiRequest<T>(
  endpoint: string,
  options: RequestInit = {}
): Promise<ApiResponse<T>> {
  const url = `${BASE_URL}${endpoint}`
  const desktopToken = getDesktopToken()
  const method = (options.method || 'GET').toUpperCase()

  // Dedup only pure GET requests (no body, no special headers beyond auth)
  const isDedup = method === 'GET' && !options.body
  if (isDedup) {
    _dedupEvict()
    const cached = _dedupCache.get(url)
    if (cached) {
      // Still in-flight or within TTL — reuse the same promise
      if (cached.resolvedAt === undefined || Date.now() - cached.resolvedAt < DEDUP_TTL_MS) {
        return cached.promise as Promise<ApiResponse<T>>
      }
      _dedupCache.delete(url)
    }
  }

  const fetchPromise = (async (): Promise<ApiResponse<T>> => {
    try {
      const response = await fetch(url, {
        ...options,
        headers: {
          'Content-Type': 'application/json',
          'X-Requested-With': 'XMLHttpRequest',
          ...(desktopToken ? { 'X-Desktop-Token': desktopToken } : {}),
          ...options.headers,
        },
      })

      if (!response.ok) {
        const errorText = await response.text()
        return { error: errorText || `HTTP ${response.status}`, status: response.status }
      }

      const data = await response.json()
      // Backend wraps responses in { ok: true, data: ... } or { ok: false, error: ... }
      if (data.ok === false) {
        return { error: data.error || 'Unknown error', status: response.status }
      }
      return { data: data.data ?? data, status: response.status }
    } catch (err) {
      return { error: err instanceof Error ? err.message : 'Unknown error' }
    }
  })()

  if (isDedup) {
    const entry: DedupEntry<T> = { promise: fetchPromise }
    _dedupCache.set(url, entry)
    fetchPromise.then(() => { entry.resolvedAt = Date.now() })
  }

  return fetchPromise
}

// Types for API responses
export interface TableColumn {
  name: string
  data_type?: string
}

export interface TableInfo {
  name: string
  columns: string[]
  table_type?: string | null
  is_calculated?: boolean
  storage_mode?: string | null
  virtual?: boolean
  semantic_type?: string | null
  param_name?: string
  group_name?: string
}

export interface MeasureInfo {
  name: string
  table?: string
  expression?: string
}

export interface PageInfo {
  id: string
  title: string
  order?: number
  page_type?: string
  placeholder_containers?: string[]
  drillthrough?: boolean
  drillthrough_columns?: Array<{ table: string; column: string }>
  hidden?: boolean
  width?: number
  height?: number
}

export interface HierarchyLevel {
  column: string
  name: string
}

export interface HierarchyDef {
  table: string
  levels: HierarchyLevel[]
}

export type HierarchiesMap = Record<string, HierarchyDef>

export interface ColumnRef {
  type: 'ColumnRef'
  table: string
  column: string
}

export interface SlotSpec {
  kind: 'dimension' | 'measure' | 'any'
  required: boolean
  multi: boolean
}

/** Action that fires when a static visual (button/shape) is clicked. */
export interface StaticAction {
  type: 'none' | 'bookmark' | 'url' | 'page' | 'back' | 'drillthrough' | 'apply-all-slicers' | 'clear-all-slicers'
  target?: string   // bookmark id, URL, page id, or drillthrough page id
}

export interface StaticContent {
  // textbox
  text?: string
  fontSize?: number
  fontWeight?: string
  textAlign?: string
  color?: string
  backgroundColor?: string
  // button
  label?: string
  url?: string
  style?: string
  borderRadius?: number
  buttonType?: string   // blank, back, left-arrow, right-arrow, reset, information, help, bookmark, apply-all-slicers, clear-all-slicers, navigator
  // shape
  shapeType?: string    // rectangle, rounded-rectangle, snip-corner, beveled, circle, ellipse, triangle, diamond, pentagon, hexagon, octagon, heart, parallelogram, trapezoid, chevron, arrow-right, arrow-left, arrow-up, arrow-down, line
  fill?: string
  stroke?: string
  strokeWidth?: number
  opacity?: number
  // image
  alt?: string
  fit?: string
  objectPosition?: string
  rotation?: number
  richText?: Array<{ text?: string; color?: string; fontWeight?: string; fontStyle?: string }>
  // action (button/shape click behavior)
  action?: StaticAction
}

export interface VisualTypeInfo {
  key: string
  label: string
  renderer: string
  px_func?: string
  slots: Record<string, SlotSpec>
  static?: boolean
}

export interface VisualEncodings {
  x?: ColumnRef | unknown
  y?: ColumnRef | unknown
  color?: ColumnRef | unknown
  [key: string]: unknown
}

export interface VisualInteractions {
  affects_others?: boolean
  is_affected?: boolean
  mode?: 'filter' | 'highlight'
  interaction_targets?: Record<string, 'filter' | 'highlight' | 'none'>
}

export interface VisualLayout {
  x: number
  y: number
  w: number
  h: number
  z?: number
  tabOrder?: number
}

export interface FormatOptions {
  // Title
  showTitle?: boolean
  title?: string
  titleFontSize?: number
  titleFontColor?: string

  // Subtitle
  showSubtitle?: boolean
  subtitleFontSize?: number
  subtitleFontColor?: string

  // Legend
  showLegend?: boolean
  legendPosition?: 'right' | 'bottom' | 'top' | 'left'

  // X Axis
  showXAxis?: boolean
  xAxisLabel?: string
  xAxisTickAngle?: number
  showXAxisGridlines?: boolean

  // Y Axis
  showYAxis?: boolean
  yAxisLabel?: string
  yAxisTickAngle?: number
  showYAxisGridlines?: boolean

  // Data Labels
  showDataLabels?: boolean
  dataLabelPosition?: 'inside' | 'outside' | 'auto'
  dataLabelFontSize?: number
  dataLabelFontFamily?: string
  dataLabelDisplayUnits?: 'auto' | 'none' | 'thousands' | 'millions' | 'billions' | 'trillions'
  dataLabelPrecision?: number
  dataLabelShowBlankAs?: '' | '(Blank)' | '0' | '-'
  dataLabelTransparency?: number

  // Sorting
  categorySort?: 'asc' | 'desc' | 'default'

  // Bar-specific
  barMode?: 'group' | 'stack' | 'relative'
  orientation?: 'v' | 'h'

  // IBCS-specific
  ibcsOrientation?: 'vertical' | 'horizontal'
  ibcsLabelPosition?: 'top-inside' | 'top-outside' | 'middle' | 'bottom'
  ibcsFontSize?: number
  ibcsDataLabelFontSize?: number
  ibcsFontFamily?: string
  ibcsXAxisRotation?: number
  ibcsCanvasPaddingH?: number
  ibcsCanvasPaddingV?: number
  ibcsShowVariancePanels?: boolean
  ibcsMainChartMode?: 'comparison' | 'waterfall'
  ibcsCardShowGraphic?: boolean
  ibcsCardGraphicSourceType?: 'custom' | 'generated'
  ibcsCardGraphicPosition?: 'top' | 'right' | 'bottom' | 'left'
  ibcsCardDiPosition?: 'top' | 'right' | 'bottom' | 'left'
  ibcsCardEduPosition?: 'top' | 'right' | 'bottom' | 'left'
  ibcsCardShowEduSummary?: boolean
  ibcsCardShowSignals?: boolean
  ibcsCardGraphicSvg?: string
  ibcsCardGraphicVisualId?: string
  ibcsCardGraphicGeneratedType?: 'ibcs_bar' | 'ibcs_line' | 'ibcs_waterfall'
  ibcsCardGraphicCategoryLabel?: string
  ibcsCardGraphicEncodingCategory?: Record<string, unknown> | null
  ibcsCardGraphicEncodingAC?: Record<string, unknown> | null
  ibcsCardGraphicEncodingPY?: Record<string, unknown> | null
  ibcsCardGraphicEncodingPL?: Record<string, unknown> | null
  ibcsCardGraphicEncodingFC?: Record<string, unknown> | null
  ibcsCardGraphicGeneratedOrientation?: 'horizontal' | 'vertical'
  ibcsCardGraphicGeneratedScenario?: 'ac' | 'py' | 'pl' | 'fc'
  ibcsCardGraphicGeneratedShowTotals?: boolean
  ibcsCardGraphicEditorOpen?: boolean
  ibcsCardGraphicIbcsMainChartMode?: 'comparison' | 'waterfall'
  ibcsCardGraphicIbcsLabelPosition?: 'top-inside' | 'top-outside' | 'middle' | 'bottom'
  ibcsCardGraphicIbcsFontSize?: number
  ibcsCardGraphicIbcsDataLabelFontSize?: number
  ibcsCardGraphicIbcsFontFamily?: string
  ibcsCardGraphicIbcsXAxisRotation?: number
  ibcsCardGraphicIbcsShowVariancePanels?: boolean
  ibcsCardGraphicIbcsWaterfallShowConnectors?: boolean
  ibcsCardGraphicIbcsCanvasPaddingH?: number
  ibcsCardGraphicIbcsCanvasPaddingV?: number
  ibcsWaterfallShowTotals?: boolean
  ibcsWaterfallScenario?: 'ac' | 'py' | 'pl' | 'fc'
  ibcsWaterfallSubtotalLabels?: string
  ibcsWaterfallShowConnectors?: boolean
  ibcsWaterfallAllowSubtotalToggle?: boolean

  // Visual canvas
  showVisualHeader?: boolean
  showVisualBorder?: boolean
  showHeaderBorder?: boolean
  visualHeaderFontSize?: number
  headerFontFamily?: string
  headerBgColor?: string
  visualBgColor?: string
  visualBgImage?: string
  visualBorderRadius?: number
  /** Transparent background — true when PBI VCO background.show=false */
  transparentBg?: boolean

  // PBI transfer properties (VCO)
  /** Background show/hide from PBI VCO */
  background_show?: boolean
  /** Background color from PBI VCO */
  backgroundColor?: string
  /** Border show/hide from PBI VCO (maps to showVisualBorder) */
  border_show?: boolean
  /** Border color from PBI VCO */
  borderColor?: string
  /** Border radius from PBI VCO */
  border_radius?: number
  /** Border width from PBI VCO */
  border_width?: number
  /** Drop shadow from PBI VCO */
  drop_shadow?: { show?: boolean; preset?: string; shadowBlur?: number; shadowDistance?: number; shadowSpread?: number; transparency?: number; shadowColor?: string }
  /** Padding from PBI VCO */
  padding?: { top?: number; left?: number; right?: number; bottom?: number }

  // Line-specific
  lineShape?: 'linear' | 'spline' | 'hv' | 'vh' | 'hvh' | 'vhv'
  showMarkers?: boolean

  // Scatter-specific
  markerSize?: number

  // Colors
  colorSequence?: string
  plotBgColor?: string
  paperBgColor?: string

  // Legacy compat
  showGridlines?: boolean

  // IBCS mode / small multiples
  ibcsMode?: boolean
  groupByColumn?: string
  smallMultiplesChartType?: string
  smallMultiplesMaxColumns?: number
  smallMultiplesSyncScale?: boolean

  // Slicer format (promoted from slicer_config)
  slicerRowCount?: number
  slicerColumnCount?: number
  slicerStyle?: string
  slicerOrientation?: number
  slicerCustomizePadding?: boolean
  slicerTileShape?: string
  slicerRoundedCurve?: number
  slicerRoundedCurveCustom?: boolean
  slicerValueAlignment?: string
  slicerValueFontSize?: number
  slicerOverflowStyle?: number
  slicerOverflowDirection?: number
  slicerImageFit?: string
  slicerImagePadding?: number
  slicerImageAsBackground?: boolean
  slicerImageIgnorePadding?: boolean
  slicerImagePosition?: string
  slicerImageSaturation?: number
  slicerPaddingSelection?: string
  slicerPaddingTop?: number
  slicerPaddingBottom?: number
  slicerFillCustomShow?: boolean

  // Matrix format (promoted from chart_objects)
  matrixLayout?: string
  matrixSteppedIndentation?: number
  matrixGridHorizontal?: boolean
  matrixColumnHeaderBg?: string
  matrixColumnHeaderWordWrap?: boolean
  matrixColumnHeaderOutline?: number
  matrixAutoSizeColumns?: boolean

  // Card format (promoted from chart_objects)
  cardValueFontSize?: number
  cardCategoryLabelsShow?: boolean
  cardCategoryFontSize?: number
  cardCategoryColor?: string
  cardValueColor?: string
  cardBarColor?: string
  cardBarWeight?: number
  cardDataLabelsFontFamily?: string
  cardDataLabelsFontSize?: number

  // Chart extras (promoted from chart_objects)
  chartFontSize?: number
  dataLabelColor?: string
  categoryAxisType?: string
  categoryAxisInnerPadding?: number
  legendShowGradient?: boolean
  dataPointBorderShow?: boolean
  showXAxisTitle?: boolean
  showYAxisTitle?: boolean

  // Shape outline (promoted from shape_properties)
  shape_outline_color?: string
  shape_outline_weight?: number
  shape_outline_show?: boolean
}

export interface VisualCalculationDef {
  name: string
  expression: string
}

export interface RenderBlockedInfo {
  reason?: string
  message?: string
  [key: string]: unknown
}

export interface UnsupportedVisualInfo {
  source_visual_id?: string
  source_visual_type?: string
  preservation_status?: string
  unsupported_reason?: string
  source?: Record<string, unknown>
  [key: string]: unknown
}

export type DocumentationSidecarObject = Record<string, unknown>
export type DocumentationSidecarRows = Array<Record<string, unknown>>

export interface VisualInfo {
  id: string
  title: string
  subtitle?: string
  visual_type: string
  page_id: string
  x?: number
  y?: number
  width?: number
  height?: number
  layout?: VisualLayout
  encodings?: VisualEncodings
  interactions?: VisualInteractions
  format?: FormatOptions
  advanced_plotly_patch?: Record<string, unknown>
  static_content?: StaticContent
  options?: Record<string, unknown>
  decision_overlays?: unknown[]
  pack_summary?: Record<string, unknown>
  overlay_meta?: Record<string, unknown>
  tooltip_page_id?: string | null
  dynamic_title?: Record<string, unknown>
  dynamic_subtitle?: Record<string, unknown>
  sparklines?: unknown[]
  render_blocked?: RenderBlockedInfo
  unsupported_visual?: UnsupportedVisualInfo
  query_options?: DocumentationSidecarObject
  visual_header?: DocumentationSidecarObject
  visual_actions?: DocumentationSidecarRows
  container_format?: DocumentationSidecarObject
  tooltip?: DocumentationSidecarObject
  selection_state?: DocumentationSidecarObject
  slicer_state?: DocumentationSidecarObject
  static_asset?: DocumentationSidecarObject
  static_resources?: DocumentationSidecarRows
  analytics?: DocumentationSidecarRows
  conditional_formatting?: DocumentationSidecarRows
  table_matrix_format?: DocumentationSidecarObject
  documentation_parameters?: DocumentationSidecarRows
  visual_calculations?: VisualCalculationDef[]
  /** PBI transfer: visual is hidden (not rendered) */
  hidden?: boolean
  /** PBI transfer: parent group visual ID */
  parent_group?: string
  /** PBI transfer: group properties (for group-type visuals) */
  group_properties?: { display_name?: string; group_mode?: string }
  /** PBI transfer: slicer configuration */
  slicer_config?: { mode?: string; single_select?: boolean; is_advanced?: boolean; style?: string; [key: string]: unknown }
}

// Backend returns SecurityRole in this format
export interface SecurityRoleRaw {
  name: string
  rls?: Array<{ table: string; filter: string }>
  ols?: {
    tables?: string[]
    measures?: string[]
    columns?: Record<string, string[]>
  }
}

// Normalized format for UI
export interface SecurityRole {
  name: string
  rls?: Record<string, string>  // table -> filter expression
  ols?: Record<string, string[]>  // table -> hidden columns
}

export interface ImportConnectorParam {
  name: string
  label?: string
  required?: boolean
  kind?: 'text' | 'path' | 'bool' | 'select'
  placeholder?: string
  options?: string[]
}

export interface ImportConnector {
  type: string
  label?: string
  category?: string
  status?: string
  params?: ImportConnectorParam[]
}

export interface ImportSource {
  type: string
  path?: string
  format?: string
  auth_mode?: string
  table?: string
  schema?: string
  delimiter?: string
  header?: boolean
  encoding?: string
  nullstr?: string | string[]
}

export interface ImportPreviewResult {
  columns: Array<{ name: string }>
  rows: unknown[]
  row_count?: number
}

export interface ImportTableInfo {
  name: string
  source?: ImportSource
  columns?: Array<{ name: string; type?: string }>
}

export interface PowerQueryStep {
  id: string
  operation?: string
  expression?: string
  dependencies?: string[]
  functions?: string[]
  compatibility_level?: string
  source_span?: { start?: number; end?: number }
}

export interface PowerQueryDiagnostic {
  severity?: string
  code?: string
  message: string
  step_id?: string
  function_name?: string
}

export interface PowerQueryCompatibilityReport {
  query_id?: string
  table_name?: string
  partition_name?: string
  compatibility_level?: string
  execution_status?: string
  unsupported_functions?: string[]
  diagnostics?: PowerQueryDiagnostic[]
  steps?: PowerQueryStep[]
}

export interface PowerQuerySourceMapping {
  source_type?: string
  source_block?: Record<string, unknown>
  confidence?: string
  reason?: string
  raw_function?: string
  connector_id?: string
  privacy_level?: string
  credential_required?: boolean
  pushdown_support?: string
  folding_status?: string
  firewall_partition?: string
}

export interface PowerQuerySourcePolicy {
  source_count?: number
  sources?: PowerQuerySourceMapping[]
  native_query_count?: number
  native_queries?: Array<Record<string, unknown>>
  folder_source_count?: number
  combine_file_pattern_count?: number
  combine_file_patterns?: Array<Record<string, unknown>>
  privacy_levels?: string[]
  privacy_partitions?: string[]
  firewall_status?: string
  credential_required_count?: number
  duckdb_pushdown_ready_count?: number
  adapter_pending_count?: number
  events?: Array<Record<string, unknown>>
}

export type PowerQueryExecutionStrategy =
  | 'folded_sql'
  | 'connector_folded'
  | 'hybrid_schema_probe'
  | 'local_exact'
  | 'blocked_missing_capability'
  | string

export interface PowerQueryCapabilityEvidence {
  capability?: string
  status?: string
  source?: string
  reason?: string
}

export interface PowerQueryTransformPlanStep {
  id: string
  operation?: string
  ir_node_id?: string
  source_operation?: string
  dependencies?: string[]
  functions?: string[]
  foldable?: boolean
  execution_lane?: string
  blockers?: string[]
  relational_blockers?: string[]
  duckdb_blockers?: string[]
  expression?: string
  execution_strategy?: PowerQueryExecutionStrategy
  parity_status?: string
  schema_probe_required?: boolean
  capability_evidence?: PowerQueryCapabilityEvidence[]
  local_evaluator_reason?: string | null
}

export interface PowerQueryTransformIRNode {
  id: string
  op: string
  inputs?: string[]
  args?: Record<string, unknown>
  m_step_id?: string
  m_operation?: string
  functions?: string[]
  foldable?: boolean
  execution_lane?: string
  blockers?: string[]
  source_expression?: string
}

export interface PowerQueryRelationalAst {
  version?: string
  status?: string
  source?: Record<string, unknown> | null
  projection?: Array<{ source?: string; alias?: string }> | null
  filters?: Array<Record<string, unknown>>
  casts?: Array<Record<string, unknown>>
  computed_columns?: Array<Record<string, unknown>>
  transformed_columns?: Array<Record<string, unknown>>
  column_name_transforms?: Array<Record<string, unknown>>
  constant_tables?: Array<Record<string, unknown>>
  folder_sources?: Array<Record<string, unknown>>
  duplicated_columns?: Array<Record<string, unknown>>
  index_columns?: Array<Record<string, unknown>>
  removed_columns?: string[]
  append_sources?: Array<Record<string, unknown>>
  append_relations?: Array<Record<string, unknown>>
  joins?: Array<Record<string, unknown>>
  expanded_nested_joins?: Array<Record<string, unknown>>
  expanded_record_columns?: Array<Record<string, unknown>>
  expanded_list_columns?: Array<Record<string, unknown>>
  unpivots?: Array<Record<string, unknown>>
  pivots?: Array<Record<string, unknown>>
  split_columns?: Array<Record<string, unknown>>
  header_operations?: Array<Record<string, unknown>>
  replacements?: Array<Record<string, unknown>>
  error_replacements?: Array<Record<string, unknown>>
  error_row_filters?: Array<Record<string, unknown>>
  native_queries?: Array<Record<string, unknown>>
  missing_field_policies?: Array<Record<string, unknown>>
  type_annotations?: Array<Record<string, unknown>>
  table_keys?: Array<Record<string, unknown>>
  fold_barriers?: Array<Record<string, unknown>>
  group_by?: string[]
  aggregations?: Array<Record<string, unknown>>
  renames?: Array<Record<string, unknown>>
  distinct?: boolean
  order_by?: Array<Record<string, unknown>>
  limit?: number | null
  offset?: number | null
  operations?: Array<Record<string, unknown>>
  transforms?: Array<Record<string, unknown>>
  blockers?: Array<{ step_id?: string; reason?: string }>
}

export interface PowerQueryDialectSql {
  dialect?: string
  status?: string
  sql?: string | null
  blockers?: Array<{ step_id?: string; reason?: string }>
}

export interface PowerQueryConnectorNativePlan {
  status?: string
  plans?: Array<Record<string, unknown>>
  blockers?: Array<{ step_id?: string; reason?: string }>
}

export interface PowerQueryTranspileOptions {
  schema_probe_mode?: 'plan' | 'execute' | 'off' | string
  credential_profile_id?: string
  fixture_mode?: boolean
  execution_target?: string
}

export interface PowerQueryTransformPlan {
  ir_version?: string
  relational_ast_version?: string
  status?: string
  result_expression?: string | null
  ir?: PowerQueryTransformIRNode[]
  relational_ast?: PowerQueryRelationalAst
  duckdb_sql?: PowerQueryDialectSql
  connector_native_plan?: PowerQueryConnectorNativePlan
  source_policy?: PowerQuerySourcePolicy
  execution_strategy?: PowerQueryExecutionStrategy
  parity_status?: string
  schema_probe_required?: boolean
  schema_probe?: {
    required?: boolean
    status?: string
    mode?: string
    candidate_count?: number
    resolved_count?: number
    candidates?: Array<Record<string, unknown>>
    resolved_columns_by_step?: Record<string, string[]>
  }
  capability_evidence?: PowerQueryCapabilityEvidence[]
  local_evaluator_reason?: string | null
  fold_frontier?: {
    status?: string
    foldable_step_ids?: string[]
    first_blocked_step_id?: string | null
    blockers?: Array<{ step_id?: string; reason?: string }>
  }
  editor_hints?: {
    parse_diagnostics?: PowerQueryDiagnostic[]
    source_count?: number
    credential_required_count?: number
    first_blocked_step_id?: string | null
    foldable_step_count?: number
    execution_strategy?: PowerQueryExecutionStrategy
    parity_status?: string
    schema_probe_required?: boolean
    local_evaluator_reason?: string | null
    suggested_next_action?: string
  }
  steps?: PowerQueryTransformPlanStep[]
  blockers?: Array<{ step_id?: string; reason?: string }>
  diagnostics?: PowerQueryDiagnostic[]
}

export interface PowerQueryAppliedStepEditPreview {
  operation?: string
  step_id?: string | null
  draft?: boolean
  save_required?: boolean
  dependency_impact?: {
    removed_step_ids?: string[]
    added_step_ids?: string[]
    reordered?: boolean
    direct_dependents_before?: string[]
    direct_dependents_after?: string[]
  }
  parse_diagnostics?: PowerQueryDiagnostic[]
  fold_frontier?: PowerQueryTransformPlan['fold_frontier']
  source_bindings?: Array<Record<string, unknown>>
  source_binding_count?: number
  parity_gap_summary?: Record<string, number>
  parity_gap_groups?: Record<string, Array<Record<string, unknown>>>
}

export interface PowerQueryStepDraftResponse {
  project: string
  query_id: string
  step_id?: string
  new_step_id?: string
  settings?: Record<string, unknown>
  raw_m: string
  query: PowerQueryQuery
  step?: PowerQueryStep
  applied_step_edit_preview?: PowerQueryAppliedStepEditPreview
  draft?: boolean
}

export interface PowerQueryParityGapReport {
  version?: string
  definition?: string
  summary?: Record<string, number>
  groups?: Record<string, Array<Record<string, unknown>>>
  source_bindings?: Array<Record<string, unknown>>
  unresolved_query_references?: Array<Record<string, unknown>>
  schema_probe_results_by_binding?: Array<Record<string, unknown>>
  folder_combine_bundle?: Record<string, unknown>
  m_error_provenance?: Record<string, unknown>
  culture_timezone_profile?: Record<string, unknown>
  applied_step_edit_preview?: PowerQueryAppliedStepEditPreview | null
  fold_frontier?: PowerQueryTransformPlan['fold_frontier']
  execution_strategy?: PowerQueryExecutionStrategy
  parity_status?: string
}

export interface PowerQueryIntellisenseCompletion {
  label: string
  kind: 'function' | 'step' | 'query' | 'parameter' | string
  insert_text: string
  detail?: string
  documentation?: string
  score?: number
}

export interface PowerQueryIntellisenseResponse {
  prefix: string
  replace_start: number
  replace_end: number
  step_context?: PowerQueryStep | null
  result_expression?: string | null
  completions: PowerQueryIntellisenseCompletion[]
  help?: PowerQueryIntellisenseCompletion | null
  diagnostics?: PowerQueryDiagnostic[]
  source_hints?: PowerQuerySourceMapping[]
}

export interface PowerQueryGraphNode {
  id: string
  label?: string
  kind?: 'table' | 'parameter' | 'function' | 'query' | string
  table_name?: string
  partition_name?: string
  mode?: string
  load_enabled?: boolean
  refresh_enabled?: boolean
  load_state?: 'loaded' | 'referenced_only' | 'staging_only' | 'parameter' | 'function' | string
  group?: string
  description?: string
  compatibility_level?: string
  execution_status?: string
  source_type?: string
  connector_id?: string
  privacy_level?: string
  folding_status?: string
  firewall_status?: string
  references?: string[]
  referenced_by?: string[]
  function_parameters?: string[]
  parameter?: {
    is_parameter?: boolean
    required?: boolean
    type?: string
    suggested_values?: string[]
  }
}

export interface PowerQueryGraphEdge {
  from: string
  to: string
  kind?: string
}

export interface PowerQueryGraph {
  nodes: PowerQueryGraphNode[]
  edges: PowerQueryGraphEdge[]
  summary?: {
    query_count?: number
    edge_count?: number
    kind_counts?: Record<string, number>
    load_state_counts?: Record<string, number>
  }
}

export interface PowerQueryQuery {
  query_id: string
  table_name?: string
  partition_name?: string
  mode?: string
  raw_m?: string
  steps?: PowerQueryStep[]
  functions?: string[]
  diagnostics?: PowerQueryDiagnostic[]
  source_mapping?: PowerQuerySourceMapping
  compatibility_report?: PowerQueryCompatibilityReport
  additional_queries?: PowerQueryQuery[]
}

export interface PowerQueryPreview {
  columns: Array<{ name: string }>
  rows: unknown[][]
  row_count?: number
  applied_steps?: string[]
  blocked_steps?: string[]
  diagnostics?: PowerQueryDiagnostic[]
  execution_scope?: string
  result_step_id?: string
}

export interface PowerQueryProfileColumn {
  name: string
  data_type?: string
  quality?: Record<string, number>
  statistics?: Record<string, unknown>
  top_values?: Array<{ value: unknown; count: number }>
}

export interface PowerQueryFunctionMetadata {
  name: string
  category?: string
  compatibility_level?: string
  status?: string
  execution?: string
  notes?: string
}

export interface PowerQueryRuntimeAdapterDescriptor {
  adapter_key: string
  connector_id: string
  execution_state: string
  capabilities: Record<string, boolean>
  result_contract: string[]
  credential_required: boolean
  approval_required: boolean
  diagnostic_code: string
  blocked_reason: string
  fixture_execution_status: string
  live_execution_status: string
  acceptance_test: string
  c3_promotion_reason: string
  live_diagnostic_code: string
  live_blocked_reason: string
  live_certification?: PowerQueryLiveCertification
  live_certification_state?: string
}

export interface PowerQueryLiveCertification {
  state: string
  family: string
  profile_env_var?: string
  sdk_status?: string
  auth_status?: string
  discovery_status?: string
  preview_status?: string
  last_certified_at?: string | null
  optional_live_test_marker?: string
}

export interface PowerQueryCredentialProfile {
  profile_id: string
  connector_id: string
  display_name: string
  privacy_level: string
  auth_type: string
  properties?: Record<string, unknown>
  secret_ref?: string
  created_at?: string
  updated_at?: string
  live_certification?: string
  last_certified_at?: string | null
  last_certification_result?: Record<string, unknown>
  certified_functions?: string[]
  missing_permissions?: string[]
  missing_sdk?: string[]
  smoke_resource?: Record<string, unknown>
}

export interface PowerQueryCredentialReadiness {
  live_certification: string
  sdk_status: string
  auth_status: string
  discovery_status: string
  preview_status: string
  last_certified_at?: string | null
  provider?: string
  oauth?: Record<string, unknown>
}

export interface PowerQueryLiveConnectorSetup {
  id: string
  label: string
  connector_id: string
  provider: string
  oauth: boolean
  auth_modes: string[]
  required_fields: string[]
  optional_fields: string[]
  credential_fields: string[]
  sdk_packages: string[]
  sdk_status: Record<string, string>
  permissions: string[]
  smoke_function: string
  smoke_options: Record<string, unknown>
  supported_functions: string[]
}

export interface PowerQueryLiveConnectorSetupManifest {
  version: string
  default_auth: string
  connectors: PowerQueryLiveConnectorSetup[]
}

export interface PowerQueryOAuthStartResult {
  state_id: string
  connector_id: string
  connector_setup: string
  provider: string
  auth_mode: string
  authorization_url?: string
  verification_uri?: string
  user_code?: string
  device_code?: string
  expires_in?: number
  requires_external_consent?: boolean
  diagnostics?: Array<Record<string, unknown>>
}

export interface PowerQueryAdapterExecutionOptions {
  fixture_mode?: boolean
  credential_profile_id?: string
  approval_record?: Record<string, unknown>
  adapter_options?: Record<string, unknown>
}

export interface PowerQueryFunctionCatalogRow {
  function: string
  category: string
  implementation_status: string
  compatibility_level: string
  execution_lane: string
  registry_execution: string
  official_reference: boolean
  official_description: string
  official_url: string
  source_mapping: boolean
  foldable_table_transform: boolean
  local_evaluator: boolean
  literal_constructor: boolean
  duckdb_row_expression: boolean
  native_query_review: boolean
  preserve_only: boolean
  duckdb_sql_equivalent: string
  risk: string
  notes: string
  support_status: string
  support_track: string
  required_to_support: string[]
  first_acceptance_test: string
  runtime_adapter: PowerQueryRuntimeAdapterDescriptor
}

export interface PowerQueryFunctionCatalog {
  version: string
  summary: Record<string, unknown>
  functions: PowerQueryFunctionCatalogRow[]
}

export interface PowerQueryDiagnosticsPhase {
  phase: string
  status?: string
  step_count?: number
  function_count?: number
  diagnostic_count?: number
  unsupported_function_count?: number
  source_type?: string | null
  connector_id?: string | null
  privacy_level?: string | null
  folding_status?: string | null
  firewall_status?: string | null
  source_count?: number | null
  credential_required_count?: number | null
  confidence?: string | null
  source_row_count?: number | null
  foldable_step_count?: number
  blocked_step_count?: number
  row_count?: number | null
  applied_steps?: string[]
}

export interface PowerQueryDiagnosticsEvent {
  phase: string
  severity: string
  code: string
  message: string
  step_id?: string
}

export interface PowerQueryDiagnosticsReport {
  query_id: string
  table_name?: string | null
  partition_name?: string | null
  draft?: boolean
  target_step_id?: string | null
  result_expression?: string | null
  summary?: Record<string, unknown>
  phases?: PowerQueryDiagnosticsPhase[]
  events?: PowerQueryDiagnosticsEvent[]
  source_mapping?: PowerQuerySourceMapping | null
  source_policy?: PowerQuerySourcePolicy | null
  transform_plan?: PowerQueryTransformPlan
  preview?: {
    columns?: Array<{ name: string }>
    row_count?: number | null
    applied_steps?: string[]
    blocked_steps?: Array<Record<string, unknown>>
    error?: string | null
    source_sql?: string
    execution_scope?: string
    adapter_result?: Record<string, unknown> | null
    result_step_id?: string | null
  }
  timings_ms?: Record<string, number>
}

export interface RelationshipDef {
  from_table: string
  from_column: string
  to_table: string
  to_column: string
  active: boolean
  rel_id?: string
  cross_filter_direction?: 'single' | 'both'
  cardinality?: string | null
}

export interface RuntimeStateResponse {
  project: string
  pages: PageInfo[]
  current_page: string
  visuals: VisualInfo[]
  filters: unknown[]
  hierarchies?: HierarchiesMap
  explanations?: unknown
  fields: {
    tables: TableInfo[]
    measures: string[]
  }
  visual_types?: Record<string, VisualTypeInfo>
  model_layouts?: ModelLayoutPayload[]
  security: {
    roles: string[]
    default_role: string | null
    active_role: string | null
  }
  calc_groups?: unknown
  calc_group_selections?: unknown
  field_parameters?: unknown
  field_parameter_selections?: unknown
  relationships?: RelationshipDef[]
}

export interface RuntimeMetaResponse {
  active_project: string | null
  active_project_source: 'query' | 'env' | null
  projects: string[]
  errors: string[]
  ready?: boolean
  version?: string
  build?: string
  mode?: 'author' | 'server'
  user_role?: 'admin' | 'editor' | 'viewer'
}

// Main state endpoint - loads everything needed for the UI
export async function getRuntimeState(params: {
  project?: string
  page?: string
  role?: string
}) {
  const searchParams = new URLSearchParams()
  if (params.project) searchParams.set('project', params.project)
  if (params.page) searchParams.set('page', params.page)
  
  const headers: Record<string, string> = {}
  if (params.role) headers['X-Role'] = params.role
  
  const queryStr = searchParams.toString()
  return apiRequest<RuntimeStateResponse>(`${queryStr ? '?' + queryStr : ''}`, { headers })
}

export async function getRuntimeMeta(params: { project?: string } = {}) {
  const searchParams = new URLSearchParams()
  if (params.project) searchParams.set('project', params.project)
  const queryStr = searchParams.toString()
  return apiRequest<RuntimeMetaResponse>(`/meta${queryStr ? '?' + queryStr : ''}`)
}

// Hierarchies
export async function getHierarchies(project?: string, role?: string) {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  const headers: Record<string, string> = {}
  if (role) headers['X-Role'] = role
  return apiRequest<{ hierarchies: HierarchiesMap }>(`/hierarchies${params}`, { headers })
}

export async function updateHierarchies(hierarchies: HierarchiesMap, project?: string) {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  return apiRequest<{ hierarchies: HierarchiesMap }>(`/hierarchies${params}`, {
    method: 'PUT',
    body: JSON.stringify({ hierarchies }),
  })
}

// Data import endpoints
export async function getImportConnectors() {
  return apiRequest<{ connectors: ImportConnector[] }>(`/data_sources/connectors`)
}

export async function listImportTables(project?: string) {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  return apiRequest<{ tables: ImportTableInfo[] }>(`/tables/sources${params}`)
}

export async function inspectImportSource(
  payload: { source: ImportSource },
  project?: string
) {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  return apiRequest<{ tables: Array<{ schema?: string | null; name: string }> }>(
    `/data_sources/inspect${params}`,
    {
      method: 'POST',
      body: JSON.stringify(payload),
    }
  )
}

export async function previewImportSource(
  payload: { source: ImportSource; limit?: number },
  project?: string
) {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  return apiRequest<ImportPreviewResult>(`/data_sources/preview${params}`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export async function importPhysicalTable(
  payload: { name: string; source: ImportSource; storage_mode?: string },
  project?: string
) {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  return apiRequest<{ ok: boolean }>(`/tables/import${params}`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

// Power Query M Transform Studio endpoints
export async function listPowerQueryQueries(project?: string) {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  return apiRequest<{ project: string; queries: PowerQueryQuery[] }>(`/power_query/queries${params}`)
}

export async function getPowerQueryQuery(queryId: string, project?: string) {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  return apiRequest<{ project: string; query: PowerQueryQuery }>(`/power_query/queries/${encodeURIComponent(queryId)}${params}`)
}

export async function getPowerQueryGraph(project?: string) {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  return apiRequest<{ project: string; graph: PowerQueryGraph }>(`/power_query/graph${params}`)
}

export async function updatePowerQueryQuery(queryId: string, rawM: string, project?: string) {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  return apiRequest<{ project: string; query: PowerQueryQuery; path?: string }>(
    `/power_query/queries/${encodeURIComponent(queryId)}${params}`,
    {
      method: 'PUT',
      body: JSON.stringify({ raw_m: rawM }),
    }
  )
}

export async function parsePowerQueryQuery(queryId: string, rawM?: string, project?: string) {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  return apiRequest<{ project: string; query: PowerQueryQuery }>(
    `/power_query/queries/${encodeURIComponent(queryId)}/parse${params}`,
    {
      method: 'POST',
      body: JSON.stringify(rawM !== undefined ? { raw_m: rawM } : {}),
    }
  )
}

export async function patchPowerQueryStepExpression(
  queryId: string,
  stepId: string,
  expression: string,
  rawM?: string,
  project?: string
) {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  const body: Record<string, unknown> = { expression }
  if (rawM !== undefined) body.raw_m = rawM
  return apiRequest<PowerQueryStepDraftResponse>(
    `/power_query/queries/${encodeURIComponent(queryId)}/steps/${encodeURIComponent(stepId)}/patch${params}`,
    {
      method: 'POST',
      body: JSON.stringify(body),
    }
  )
}

export async function addPowerQueryStep(
  queryId: string,
  payload: { step_id: string; expression: string; after_step_id?: string; make_result?: boolean; raw_m?: string },
  project?: string
) {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  return apiRequest<PowerQueryStepDraftResponse>(
    `/power_query/queries/${encodeURIComponent(queryId)}/steps/add${params}`,
    {
      method: 'POST',
      body: JSON.stringify(payload),
    }
  )
}

export async function deletePowerQueryStep(
  queryId: string,
  stepId: string,
  rawM?: string,
  project?: string
) {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  return apiRequest<PowerQueryStepDraftResponse>(
    `/power_query/queries/${encodeURIComponent(queryId)}/steps/${encodeURIComponent(stepId)}/delete${params}`,
    {
      method: 'POST',
      body: JSON.stringify(rawM !== undefined ? { raw_m: rawM } : {}),
    }
  )
}

export async function renamePowerQueryStep(
  queryId: string,
  stepId: string,
  newStepId: string,
  rawM?: string,
  project?: string
) {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  const body: Record<string, unknown> = { new_step_id: newStepId }
  if (rawM !== undefined) body.raw_m = rawM
  return apiRequest<PowerQueryStepDraftResponse>(
    `/power_query/queries/${encodeURIComponent(queryId)}/steps/${encodeURIComponent(stepId)}/rename${params}`,
    {
      method: 'POST',
      body: JSON.stringify(body),
    }
  )
}

export async function reorderPowerQueryStep(
  queryId: string,
  payload: { step_id: string; before_step_id?: string; after_step_id?: string; raw_m?: string },
  project?: string
) {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  return apiRequest<PowerQueryStepDraftResponse>(
    `/power_query/queries/${encodeURIComponent(queryId)}/steps/reorder${params}`,
    {
      method: 'POST',
      body: JSON.stringify(payload),
    }
  )
}

export async function patchPowerQuerySettings(
  queryId: string,
  payload: { step_id?: string; expression?: string; settings?: Record<string, unknown>; raw_m?: string },
  project?: string
) {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  return apiRequest<PowerQueryStepDraftResponse>(
    `/power_query/queries/${encodeURIComponent(queryId)}/settings/patch${params}`,
    {
      method: 'POST',
      body: JSON.stringify(payload),
    }
  )
}

export async function patchPowerQueryParameterExpression(
  queryId: string,
  expression: string,
  rawM?: string,
  project?: string
) {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  const body: Record<string, unknown> = { expression }
  if (rawM !== undefined) body.raw_m = rawM
  return apiRequest<{ project: string; query_id: string; raw_m: string; query: PowerQueryQuery; draft?: boolean }>(
    `/power_query/queries/${encodeURIComponent(queryId)}/parameter/patch${params}`,
    {
      method: 'POST',
      body: JSON.stringify(body),
    }
  )
}

export async function mapPowerQuerySource(queryId: string, rawM?: string, project?: string) {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  return apiRequest<{ project: string; query_id: string; source_mapping: PowerQuerySourceMapping | null }>(
    `/power_query/queries/${encodeURIComponent(queryId)}/map-source${params}`,
    {
      method: 'POST',
      body: JSON.stringify(rawM !== undefined ? { raw_m: rawM } : {}),
    }
  )
}

export async function getPowerQueryIntellisense(
  queryId: string,
  rawM: string,
  cursorOffset: number,
  project?: string,
  stepId?: string
) {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  const body: Record<string, unknown> = { raw_m: rawM, cursor_offset: cursorOffset }
  if (stepId) body.step_id = stepId
  return apiRequest<{
    project: string
    query_id: string
    intellisense: PowerQueryIntellisenseResponse
    draft?: boolean
  }>(
    `/power_query/queries/${encodeURIComponent(queryId)}/intellisense${params}`,
    {
      method: 'POST',
      body: JSON.stringify(body),
    }
  )
}

export async function transpilePowerQueryQuery(
  queryId: string,
  rawM?: string,
  project?: string,
  options?: PowerQueryTranspileOptions
) {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  const body: Record<string, unknown> = { ...(options || {}) }
  if (rawM !== undefined) body.raw_m = rawM
  return apiRequest<{
    project: string
    query_id: string
    plan: PowerQueryTransformPlan
    execution_scope?: string
    message?: string
  }>(
    `/power_query/queries/${encodeURIComponent(queryId)}/transpile${params}`,
    {
      method: 'POST',
      body: JSON.stringify(body),
    }
  )
}

export async function getPowerQueryParityGapReport(
  queryId: string,
  rawM?: string,
  project?: string,
  options?: PowerQueryTranspileOptions
) {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  const body: Record<string, unknown> = { ...(options || {}) }
  if (rawM !== undefined) body.raw_m = rawM
  return apiRequest<{
    project: string
    query_id: string
    parity_gap_report: PowerQueryParityGapReport
  }>(
    `/power_query/queries/${encodeURIComponent(queryId)}/parity-gap-report${params}`,
    {
      method: 'POST',
      body: JSON.stringify(body),
    }
  )
}

export async function previewPowerQueryQuery(
  queryId: string,
  rawM?: string,
  project?: string,
  limit = 50,
  stepId?: string,
  adapterOptions?: PowerQueryAdapterExecutionOptions
) {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  const body: Record<string, unknown> = { limit, ...(adapterOptions || {}) }
  if (rawM !== undefined) body.raw_m = rawM
  if (stepId) body.step_id = stepId
  return apiRequest<{ project: string; preview: PowerQueryPreview; execution_scope?: string; message?: string; adapter_result?: Record<string, unknown> }>(
    `/power_query/queries/${encodeURIComponent(queryId)}/preview${params}`,
    {
      method: 'POST',
      body: JSON.stringify(body),
    }
  )
}

export async function profilePowerQueryQuery(
  queryId: string,
  rawM?: string,
  project?: string,
  limit = 1000,
  stepId?: string,
  adapterOptions?: PowerQueryAdapterExecutionOptions
) {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  const body: Record<string, unknown> = { limit, ...(adapterOptions || {}) }
  if (rawM !== undefined) body.raw_m = rawM
  if (stepId) body.step_id = stepId
  return apiRequest<{
    project: string
    profile: { columns: PowerQueryProfileColumn[] }
    applied_steps?: string[]
    blocked_steps?: string[]
    execution_scope?: string
    adapter_result?: Record<string, unknown>
    step_id?: string | null
    result_step_id?: string | null
  }>(
    `/power_query/queries/${encodeURIComponent(queryId)}/profile${params}`,
    {
      method: 'POST',
      body: JSON.stringify(body),
    }
  )
}

export async function getPowerQueryCompatibilityReport(project?: string) {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  return apiRequest<{ project: string; reports: PowerQueryCompatibilityReport[] }>(`/power_query/compatibility-report${params}`)
}

export async function runPowerQueryDiagnostics(
  queryId: string,
  rawM?: string,
  project?: string,
  limit = 100,
  stepId?: string,
  adapterOptions?: PowerQueryAdapterExecutionOptions
) {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  const body: Record<string, unknown> = { limit, ...(adapterOptions || {}) }
  if (rawM !== undefined) body.raw_m = rawM
  if (stepId) body.step_id = stepId
  return apiRequest<{ project: string; query_id: string; diagnostics: PowerQueryDiagnosticsReport }>(
    `/power_query/queries/${encodeURIComponent(queryId)}/diagnostics${params}`,
    {
      method: 'POST',
      body: JSON.stringify(body),
    }
  )
}

export async function listPowerQueryFunctions() {
  return apiRequest<{ functions: PowerQueryFunctionMetadata[] }>(`/power_query/functions`)
}

export async function getPowerQueryFunctionCatalog() {
  return apiRequest<{ catalog: PowerQueryFunctionCatalog }>(`/power_query/function-catalog`)
}

export async function listPowerQueryCredentialProfiles(project?: string) {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  return apiRequest<{ project: string; profiles: PowerQueryCredentialProfile[] }>(`/power_query/credential-profiles${params}`)
}

export async function upsertPowerQueryCredentialProfile(
  payload: Partial<PowerQueryCredentialProfile> & { connector_id: string; secrets?: Record<string, unknown> },
  project?: string
) {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  const method = payload.profile_id ? 'PATCH' : 'POST'
  const path = payload.profile_id
    ? `/power_query/credential-profiles/${encodeURIComponent(payload.profile_id)}${params}`
    : `/power_query/credential-profiles${params}`
  return apiRequest<{ project: string; profile: PowerQueryCredentialProfile }>(path, {
    method,
    body: JSON.stringify(payload),
  })
}

export async function deletePowerQueryCredentialProfile(profileId: string, project?: string) {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  return apiRequest<{ project: string; deleted: boolean; profile_id: string }>(
    `/power_query/credential-profiles/${encodeURIComponent(profileId)}${params}`,
    { method: 'DELETE' }
  )
}

export async function testPowerQueryCredentialProfile(
  profileId: string,
  payload: { function_name?: string; operation?: string; adapter_options?: Record<string, unknown>; approval_record?: Record<string, unknown> } = {},
  project?: string
) {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  return apiRequest<{
    project: string
    profile: PowerQueryCredentialProfile
    result: Record<string, unknown>
    readiness?: PowerQueryCredentialReadiness
    live_certification?: string
    sdk_status?: string
    auth_status?: string
    discovery_status?: string
    preview_status?: string
    last_certified_at?: string | null
  }>(
    `/power_query/credential-profiles/${encodeURIComponent(profileId)}/test${params}`,
    {
      method: 'POST',
      body: JSON.stringify(payload),
    }
  )
}

export async function getPowerQueryLiveConnectorSetupManifest() {
  return apiRequest<{ manifest: PowerQueryLiveConnectorSetupManifest }>(`/power_query/live-connectors/setup-manifest`)
}

export async function startPowerQueryLiveConnectorOAuth(payload: {
  connector_id: string
  properties?: Record<string, unknown>
  client_id?: string
  tenant_id?: string
  scopes?: string[]
  mock_oauth?: boolean
}) {
  return apiRequest<{ oauth: PowerQueryOAuthStartResult }>(`/power_query/live-connectors/oauth/start`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export async function completePowerQueryLiveConnectorOAuth(
  payload: {
    connector_id: string
    profile_connector_id?: string
    profile_id?: string
    display_name?: string
    privacy_level?: string
    auth_type?: string
    properties?: Record<string, unknown>
    secrets?: Record<string, unknown>
    mock_oauth?: boolean
  },
  project?: string
) {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  return apiRequest<{ project: string; profile: PowerQueryCredentialProfile; connector: PowerQueryLiveConnectorSetup }>(
    `/power_query/live-connectors/oauth/complete${params}`,
    {
      method: 'POST',
      body: JSON.stringify(payload),
    }
  )
}

export async function certifyPowerQueryLiveConnectorProfile(
  profileId: string,
  payload: { connector_id?: string; function_name?: string; operation?: string; adapter_options?: Record<string, unknown>; approval_record?: Record<string, unknown> } = {},
  project?: string
) {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  return apiRequest<{
    project: string
    profile: PowerQueryCredentialProfile
    result: Record<string, unknown>
    readiness?: PowerQueryCredentialReadiness
    live_certification?: string
    sdk_status?: string
    auth_status?: string
    discovery_status?: string
    preview_status?: string
    last_certified_at?: string | null
  }>(
    `/power_query/live-connectors/${encodeURIComponent(profileId)}/certify${params}`,
    {
      method: 'POST',
      body: JSON.stringify(payload),
    }
  )
}

// Phase 22: Data source management endpoints
export async function updateTableSource(
  tableName: string,
  payload: { source: ImportSource; storage_mode?: string },
  project?: string
) {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  return apiRequest<{
    table: {
      name: string
      columns: Array<{ name: string; type?: string }>
      source: ImportSource
      storage_mode: string
    }
  }>(`/tables/${encodeURIComponent(tableName)}/source${params}`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  })
}

export async function deletePhysicalTable(
  tableName: string,
  project?: string
) {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  return apiRequest<{ deleted: string }>(`/tables/${encodeURIComponent(tableName)}${params}`, {
    method: 'DELETE',
  })
}

export async function testDataSource(
  payload: { source: ImportSource },
  project?: string
) {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  return apiRequest<{
    connected: boolean
    columns?: Array<{ name: string; type?: string }>
    column_count?: number
    error?: string
    source?: ImportSource
  }>(`/data_sources/test${params}`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export async function refreshTable(
  tableName: string,
  project?: string
) {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  return apiRequest<{
    table: string
    storage_mode: string
    action: string
    message: string
  }>(`/tables/${encodeURIComponent(tableName)}/refresh${params}`, {
    method: 'POST',
  })
}

export async function refreshAllTables(project?: string) {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  return apiRequest<{
    tables: Array<{ name: string; storage_mode: string; action: string }>
    message: string
  }>(`/refresh_all${params}`, {
    method: 'POST',
  })
}

// Security endpoints
export async function getSecurityRoles(project?: string) {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  return apiRequest<{
    default_role: string | null
    roles: SecurityRoleRaw[]
  }>(`/security/roles${params}`)
}

export async function updateSecurityRoles(
  roles: SecurityRoleRaw[],
  defaultRole: string | null,
  project?: string
) {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  return apiRequest<{
    default_role: string | null
    roles: SecurityRoleRaw[]
  }>(`/security/roles${params}`, {
    method: 'PUT',
    body: JSON.stringify({
      roles,
      default_role: defaultRole,
    }),
  })
}

// Render endpoint
export interface RenderRequest {
  render_mode?: 'normal' | 'highlight'
  filters?: Array<{
    column: unknown
    operator?: string
    values: unknown[]
    scope?: string
    table?: string
  }>
  interaction_filters?: Array<{
    source_visual_id: string
    table: string
    column: string
    values: unknown[]
  }>
  slicer_defs?: unknown
  calc_group_selections?: unknown
  field_parameter_selections?: unknown
  what_if_selections?: unknown
  /** Inline visual definition for unsaved visuals (created client-side, not yet persisted via Save All). */
  visual_definition?: Record<string, unknown>
  // Matrix-specific: tablix properties (subtotals, placement, etc.)
  tablixProperties?: Record<string, unknown>
  // Matrix expansion state
  expanded_rows?: string[][]
  expanded_cols?: string[][]
  // Matrix performance safety caps
  matrix_caps?: { max_rows?: number; max_cols?: number; max_cells?: number }
  // Explanation narrative depth
  narrative_depth?: 'children' | 'leaf' | 'all'
  // Drill state
  drill_row_level?: number
  drill_col_level?: number
  drill_row_mode?: string
  drill_col_mode?: string
  drill_row_filters?: unknown[]
  drill_col_filters?: unknown[]
  // Expand-all toggles
  expand_all_rows?: boolean
  expand_all_cols?: boolean
  // Data bars
  include_bars?: boolean
  // CMB/RMB expansion depth
  cmb_expand_depth?: number
  rmb_expand_depth?: number
  // Chart hierarchy drill state
  drill_level?: number
  drill_filters?: Array<{ table: string; column: string; value: unknown }>
  // Expand multiple hierarchy levels at once
  expand_levels?: number
}

export interface DrillMeta {
  hierarchy_name: string
  table: string
  levels: Array<{ column: string; name: string }>
  current_level: number
  max_level: number
  can_drill_down: boolean
  can_drill_up: boolean
  expand_levels?: number
  can_expand?: boolean
}

export interface RenderResponse {
  visual_id: string
  type: string
  title: string
  columns?: string[]
  rows?: Array<Record<string, unknown>>
  decision_overlays?: unknown[]
  pack_summary?: Record<string, unknown>
  overlay_meta?: Record<string, unknown>
  query?: {
    sql: string
    row_count?: number
    execution_ms?: number
    filters?: unknown[]
    ir?: Record<string, unknown> | null
  }
  plotly_data?: unknown[]
  plotly_layout?: Record<string, unknown>
  figure?: { data?: unknown[]; layout?: Record<string, unknown> }
  error?: string
  blocked?: boolean
  hidden_refs?: Array<{ kind: string; table?: string; column?: string; name?: string }>
  drill?: DrillMeta
}

export async function renderVisual(
  visualId: string, 
  renderRequest: RenderRequest = {}, 
  params: { project?: string; role?: string; signal?: AbortSignal } = {}
) {
  const searchParams = new URLSearchParams()
  if (params.project) searchParams.set('project', params.project)
  
  const headers: Record<string, string> = {}
  if (params.role) headers['X-Role'] = params.role
  
  const queryStr = searchParams.toString()
  return apiRequest<RenderResponse>(`/visuals/${encodeURIComponent(visualId)}/render${queryStr ? '?' + queryStr : ''}`, {
    method: 'POST',
    headers,
    body: JSON.stringify(renderRequest),
    signal: params.signal,
  })
}

// Matrix render endpoint (for tablix/matrix visuals)
export async function renderMatrix(
  visualId: string,
  renderRequest: RenderRequest = {},
  params: { project?: string; role?: string; signal?: AbortSignal } = {}
) {
  const searchParams = new URLSearchParams()
  if (params.project) searchParams.set('project', params.project)
  
  const headers: Record<string, string> = {}
  if (params.role) headers['X-Role'] = params.role
  
  const queryStr = searchParams.toString()
  return apiRequest<RenderResponse>(`/visuals/${encodeURIComponent(visualId)}/matrix${queryStr ? '?' + queryStr : ''}`, {
    method: 'POST',
    headers,
    body: JSON.stringify(renderRequest),
    signal: params.signal,
  })
}

// Batch render — render multiple visuals in a single HTTP request
export interface BatchRenderRequest {
  visual_ids: string[]
  filters?: Array<{
    column: unknown
    operator?: string
    values: unknown[]
    scope?: string
    target?: string
    keep?: boolean
  }>
  interaction_filters?: Array<{
    source_visual_id: string
    table: string
    column: string
    values: unknown[]
  }>
}

export interface BatchRenderResponse {
  ok: boolean
  results: Record<string, RenderResponse & { skip?: boolean; reason?: string; static?: boolean }>
  total_ms: number
  visual_count: number
}

export async function renderBatch(
  batchRequest: BatchRenderRequest,
  params: { project?: string; role?: string; signal?: AbortSignal } = {}
) {
  const searchParams = new URLSearchParams()
  if (params.project) searchParams.set('project', params.project)

  const headers: Record<string, string> = {}
  if (params.role) headers['X-Role'] = params.role

  const queryStr = searchParams.toString()
  return apiRequest<BatchRenderResponse>(`/render-batch${queryStr ? '?' + queryStr : ''}`, {
    method: 'POST',
    headers,
    body: JSON.stringify(batchRequest),
    signal: params.signal,
  })
}

// Tooltip page render — renders all visuals on a tooltip page with hover filter context
export interface TooltipPageRenderRequest {
  filter_context?: Record<string, unknown>
  filters?: Array<{
    column: unknown
    operator?: string
    values: unknown[]
    scope?: string
    table?: string
  }>
}

export interface TooltipPageVisualResult {
  visual_id: string
  type?: string
  title?: string
  columns?: string[]
  rows?: Array<Record<string, unknown>>
  figure?: { data?: unknown[]; layout?: Record<string, unknown> }
  layout?: { x?: number; y?: number; width?: number; height?: number }
  query?: { sql?: string; row_count?: number; execution_ms?: number }
  error?: string
  figure_error?: string
  plotly_not_installed?: boolean
}

export interface TooltipPageRenderResponse {
  ok: boolean
  page_id: string
  page_title: string
  visuals: TooltipPageVisualResult[]
  error?: string
}

export async function renderTooltipPage(
  pageId: string,
  req: TooltipPageRenderRequest = {},
  params: { project?: string; role?: string } = {}
) {
  const searchParams = new URLSearchParams()
  if (params.project) searchParams.set('project', params.project)

  const headers: Record<string, string> = {}
  if (params.role) headers['X-Role'] = params.role

  const queryStr = searchParams.toString()
  return apiRequest<TooltipPageRenderResponse>(`/tooltip-page/${encodeURIComponent(pageId)}/render${queryStr ? '?' + queryStr : ''}`, {
    method: 'POST',
    headers,
    body: JSON.stringify(req),
  })
}

// Filters endpoints
export interface FilterDef {
  id?: string
  table: string
  column: string
  values: unknown[]
  operator?: string
  scope?: 'report' | 'page' | 'visual'
  visual_id?: string
  page_id?: string
}

export interface FiltersResponse {
  filters: FilterDef[]
  report_filters?: FilterDef[]
  page_filters?: Record<string, FilterDef[]>
  visual_filters?: Record<string, FilterDef[]>
}

export async function getFilters(project?: string) {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  return apiRequest<FiltersResponse>(`/filters${params}`)
}

export async function saveFilters(
  payload: {
    report_filters?: FilterDef[]
    page_filters?: Record<string, FilterDef[]>
    visual_filters?: Record<string, FilterDef[]>
  },
  project?: string
) {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  return apiRequest<FiltersResponse>(`/filters${params}`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  })
}

// Get distinct values for a column (for filter dropdowns)
export interface DistinctValuesResponse {
  table: string
  column: string
  values: unknown[]
}

export async function getDistinctValues(
  table: string, 
  column: string, 
  params: { project?: string; role?: string; limit?: number } = {}
) {
  const searchParams = new URLSearchParams()
  searchParams.set('table', table)
  searchParams.set('column', column)
  if (params.project) searchParams.set('project', params.project)
  if (params.limit) searchParams.set('limit', String(params.limit))
  
  const headers: Record<string, string> = {}
  if (params.role) headers['X-Role'] = params.role
  
  return apiRequest<DistinctValuesResponse>(`/columns/distinct?${searchParams}`, { headers })
}

// === Measures API ===

export interface MeasureDetail {
  name: string
  dax: string
  table?: string
  description?: string
  folder?: string
  format?: string
}

export async function listMeasures(project?: string, role?: string) {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  const headers: Record<string, string> = {}
  if (role) headers['X-Role'] = role
  
  return apiRequest<{ measures: MeasureDetail[] }>(`/measures${params}`, { headers })
}

export async function getMeasure(name: string, project?: string, role?: string) {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  const headers: Record<string, string> = {}
  if (role) headers['X-Role'] = role
  
  return apiRequest<{ measure: MeasureDetail }>(`/measures/${encodeURIComponent(name)}${params}`, { headers })
}

export async function createMeasure(measure: MeasureDetail, project?: string) {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  return apiRequest<{ measure: MeasureDetail }>(`/measures${params}`, {
    method: 'POST',
    body: JSON.stringify(measure),
  })
}

export async function updateMeasure(name: string, measure: Partial<MeasureDetail>, project?: string) {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  return apiRequest<{ measure: MeasureDetail }>(`/measures/${encodeURIComponent(name)}${params}`, {
    method: 'PUT',
    body: JSON.stringify(measure),
  })
}

export async function deleteMeasure(name: string, project?: string) {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  return apiRequest<{ success: boolean }>(`/measures/${encodeURIComponent(name)}${params}`, {
    method: 'DELETE',
  })
}

export async function validateMeasure(dax: string, project?: string, role?: string) {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  const headers: Record<string, string> = {}
  if (role) headers['X-Role'] = role
  
  return apiRequest<{ valid: boolean; error?: string; compiled_sql?: string }>(`/measures/validate${params}`, {
    method: 'POST',
    headers,
    body: JSON.stringify({ dax }),
  })
}

// === Calculated Tables API ===

export interface CalcTableDetail {
  name: string
  expression: string
  dax?: string
  description?: string
  is_calculated?: boolean
  folder?: string | null
  columns?: { name: string; type: string; expression?: string | null; is_calculated: boolean }[]
}

export async function listCalcTables(project?: string, role?: string) {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  const headers: Record<string, string> = {}
  if (role) headers['X-Role'] = role
  
  return apiRequest<{ tables: CalcTableDetail[] }>(`/calculated_tables${params}`, { headers })
}

export async function getCalcTable(name: string, project?: string, role?: string) {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  const headers: Record<string, string> = {}
  if (role) headers['X-Role'] = role
  
  return apiRequest<{ calculated_table: CalcTableDetail }>(`/calculated_tables/${encodeURIComponent(name)}${params}`, { headers })
}

export async function createCalcTable(calcTable: CalcTableDetail, project?: string) {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  return apiRequest<{ calculated_table: CalcTableDetail }>(`/calculated_tables${params}`, {
    method: 'POST',
    body: JSON.stringify(calcTable),
  })
}

export async function updateCalcTable(name: string, calcTable: Partial<CalcTableDetail>, project?: string) {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  return apiRequest<{ calculated_table: CalcTableDetail }>(`/calculated_tables/${encodeURIComponent(name)}${params}`, {
    method: 'PUT',
    body: JSON.stringify(calcTable),
  })
}

export async function deleteCalcTable(name: string, project?: string) {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  return apiRequest<{ success: boolean }>(`/calculated_tables/${encodeURIComponent(name)}${params}`, {
    method: 'DELETE',
  })
}

export async function previewCalcTable(dax: string, project?: string, role?: string, limit = 100) {
  const searchParams = new URLSearchParams()
  if (project) searchParams.set('project', project)
  searchParams.set('limit', String(limit))
  
  const headers: Record<string, string> = {}
  if (role) headers['X-Role'] = role
  
  return apiRequest<{ columns: string[]; rows: Array<Record<string, unknown>>; row_count: number }>(`/calculated_tables/preview?${searchParams}`, {
    method: 'POST',
    headers,
    body: JSON.stringify({ dax }),
  })
}

// === Calculated Columns API ===

export interface CalcColumnDetail {
  table: string
  column: string
  dax: string
  description?: string
}

export async function listCalcColumns(project?: string, role?: string) {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  const headers: Record<string, string> = {}
  if (role) headers['X-Role'] = role
  
  return apiRequest<{ calculated_columns: CalcColumnDetail[] }>(`/calculated_columns${params}`, { headers })
}

export async function createCalcColumn(calcColumn: CalcColumnDetail, project?: string) {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  return apiRequest<{ calculated_column: CalcColumnDetail }>(`/calculated_columns${params}`, {
    method: 'POST',
    body: JSON.stringify(calcColumn),
  })
}

export async function updateCalcColumn(table: string, column: string, calcColumn: Partial<CalcColumnDetail>, project?: string) {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  return apiRequest<{ calculated_column: CalcColumnDetail }>(`/calculated_columns/${encodeURIComponent(table)}/${encodeURIComponent(column)}${params}`, {
    method: 'PUT',
    body: JSON.stringify(calcColumn),
  })
}

export async function deleteCalcColumn(table: string, column: string, project?: string) {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  return apiRequest<{ success: boolean }>(`/calculated_columns/${encodeURIComponent(table)}/${encodeURIComponent(column)}${params}`, {
    method: 'DELETE',
  })
}

// Visual CRUD endpoints
export async function createVisual(
  visual: Partial<VisualInfo>,
  params: { project?: string; page?: string } = {}
) {
  const searchParams = new URLSearchParams()
  if (params.project) searchParams.set('project', params.project)
  if (params.page) searchParams.set('page', params.page)
  
  const queryStr = searchParams.toString()
  return apiRequest<VisualInfo>(`/visuals${queryStr ? '?' + queryStr : ''}`, {
    method: 'POST',
    body: JSON.stringify(visual),
  })
}

export async function updateVisual(
  visualId: string,
  updates: Partial<VisualInfo>,
  project?: string
) {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  return apiRequest<VisualInfo>(`/visuals/${encodeURIComponent(visualId)}${params}`, {
    method: 'PUT',
    body: JSON.stringify(updates),
  })
}

export async function deleteVisual(visualId: string, project?: string) {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  return apiRequest<{ success: boolean }>(`/visuals/${encodeURIComponent(visualId)}${params}`, {
    method: 'DELETE',
  })
}

// === Visual Calculations ===

export async function getVisualCalculations(visualId: string, project?: string) {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  return apiRequest<{ visual_calculations: VisualCalculationDef[] }>(
    `/visuals/${encodeURIComponent(visualId)}/visual-calculations${params}`
  )
}

export async function putVisualCalculations(
  visualId: string,
  calculations: VisualCalculationDef[],
  project?: string
) {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  return apiRequest<{ visual_calculations: VisualCalculationDef[] }>(
    `/visuals/${encodeURIComponent(visualId)}/visual-calculations${params}`,
    {
      method: 'PUT',
      body: JSON.stringify({ visual_calculations: calculations }),
    }
  )
}

export async function validateVisualCalculation(
  visualId: string,
  name: string,
  expression: string,
  project?: string
) {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  return apiRequest<{ valid: boolean; name: string; expression: string }>(
    `/visuals/${encodeURIComponent(visualId)}/visual-calculations/validate${params}`,
    {
      method: 'POST',
      body: JSON.stringify({ name, expression }),
    }
  )
}

// === Page CRUD ===

export async function createPage(
  payload: { title?: string; id?: string; page_type?: string },
  project?: string
) {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  return apiRequest<PageInfo>(`/pages${params}`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export async function updatePage(
  pageId: string,
  updates: Partial<Pick<PageInfo, 'title' | 'order' | 'hidden' | 'page_type'>>,
  project?: string
) {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  return apiRequest<PageInfo>(`/pages/${encodeURIComponent(pageId)}${params}`, {
    method: 'PUT',
    body: JSON.stringify(updates),
  })
}

export async function deletePage(pageId: string, project?: string) {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  return apiRequest<{ id: string; remaining: number }>(`/pages/${encodeURIComponent(pageId)}${params}`, {
    method: 'DELETE',
  })
}

export async function reorderPages(pageIds: string[], project?: string) {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  return apiRequest<{ pages: PageInfo[] }>(`/pages/reorder${params}`, {
    method: 'PUT',
    body: JSON.stringify({ page_ids: pageIds }),
  })
}

// Measures endpoints
export async function getMeasures(project?: string) {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  return apiRequest<MeasureInfo[]>(`/measures${params}`)
}

// Tables/columns endpoints
export async function getTableColumns(table: string, project?: string) {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  return apiRequest<{ columns: TableColumn[] }>(`/tables/${encodeURIComponent(table)}/columns${params}`)
}

export async function setTableType(table: string, tableType: 'fact' | 'dim' | 'bridge' | null, project?: string) {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  return apiRequest<{ table: string; table_type: string | null }>(
    `/tables/${encodeURIComponent(table)}/table_type${params}`,
    { method: 'PUT', body: JSON.stringify({ table_type: tableType }), headers: { 'Content-Type': 'application/json' } }
  )
}

export async function setColumnSortBy(table: string, column: string, sortByColumn: string | null, project?: string) {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  return apiRequest<{ table: string; column: string; sort_by_column: string | null }>(
    `/tables/${encodeURIComponent(table)}/columns/${encodeURIComponent(column)}/sort_by${params}`,
    { method: 'PUT', body: JSON.stringify({ sort_by_column: sortByColumn }), headers: { 'Content-Type': 'application/json' } }
  )
}

export async function setColumnDataType(table: string, column: string, type: string, decimalPlaces?: number | null, project?: string) {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  return apiRequest<{ table: string; column: string; type: string; decimal_places: number | null }>(
    `/tables/${encodeURIComponent(table)}/columns/${encodeURIComponent(column)}/data_type${params}`,
    { method: 'PUT', body: JSON.stringify({ type, decimal_places: decimalPlaces ?? null }), headers: { 'Content-Type': 'application/json' } }
  )
}

export async function getRelationships(project?: string) {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  return apiRequest<{ relationships: RelationshipDef[] }>(`/relationships${params}`)
}

export async function createRelationship(
  payload: Omit<RelationshipDef, 'rel_id'> & { rel_id?: string },
  project?: string
) {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  return apiRequest<{ relationship: RelationshipDef; relationships: RelationshipDef[] }>(`/relationships${params}`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export async function updateRelationship(
  relId: string,
  payload: Partial<RelationshipDef>,
  project?: string
) {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  return apiRequest<{ relationship: RelationshipDef; relationships: RelationshipDef[] }>(
    `/relationships/${encodeURIComponent(relId)}${params}`,
    {
      method: 'PUT',
      body: JSON.stringify(payload),
    }
  )
}

export async function deleteRelationship(relId: string, project?: string) {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  return apiRequest<{ deleted: RelationshipDef; relationships: RelationshipDef[] }>(
    `/relationships/${encodeURIComponent(relId)}${params}`,
    { method: 'DELETE' }
  )
}

export async function detectRelationshipCardinality(
  payload: {
    from_table: string
    from_column: string
    to_table: string
    to_column: string
  },
  project?: string
) {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  return apiRequest<{ cardinality: string | null; cardinality_display: string | null }>(
    `/relationships/cardinality/detect${params}`,
    {
      method: 'POST',
      body: JSON.stringify(payload),
    }
  )
}

// === Model View Layouts API ===

export interface ModelLayoutPayload {
  id: string
  name: string
  visibleTables: string[] | null
  nodePositions: Record<string, { x: number; y: number }>
}

export async function getModelLayouts(project?: string) {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  return apiRequest<{ layouts: ModelLayoutPayload[] }>(`/model-layouts${params}`)
}

export async function saveModelLayouts(layouts: ModelLayoutPayload[], project?: string) {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  return apiRequest<{ saved: number }>(`/model-layouts${params}`, {
    method: 'PUT',
    body: JSON.stringify({ layouts }),
  })
}

// === Field Parameters API ===

export interface FieldParameterItem {
  name: string
  ref_type?: string
  sort?: number
}

export interface FieldParameterMeta {
  name: string
  default_item?: string
  items: FieldParameterItem[]
}

export interface FieldParameterDef {
  default_item?: string
  items?: Array<{
    name: string
    ref?: { type: string; table?: string; column?: string; name?: string }
    sort?: number
    sortColumn?: string  // Optional column reference for sorting (e.g., "Table[Column]")
    [key: string]: unknown  // Custom properties (e.g., locale, category)
  }>
}

export async function getFieldParameters(project?: string, role?: string) {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  const headers: Record<string, string> = {}
  if (role) headers['X-Role'] = role
  
  return apiRequest<{ 
    field_parameters: FieldParameterMeta[]
    field_parameters_defs: Record<string, FieldParameterDef> 
  }>(`/field_parameters${params}`, { headers })
}

export async function updateFieldParameters(defs: Record<string, FieldParameterDef>, project?: string) {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  return apiRequest<{ 
    field_parameters: FieldParameterMeta[]
    field_parameters_defs: Record<string, FieldParameterDef> 
  }>(`/field_parameters${params}`, {
    method: 'PUT',
    body: JSON.stringify({ field_parameters_defs: defs }),
  })
}

export async function getFieldParameterSelections(project?: string, role?: string) {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  const headers: Record<string, string> = {}
  if (role) headers['X-Role'] = role
  
  return apiRequest<{ 
    field_parameter_selections: Record<string, string>
    selections: Record<string, string>
  }>(`/field_parameter_selections${params}`, { headers })
}

export async function updateFieldParameterSelections(selections: Record<string, string>, project?: string) {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  return apiRequest<{ 
    field_parameter_selections: Record<string, string>
    selections: Record<string, string>
  }>(`/field_parameter_selections${params}`, {
    method: 'PUT',
    body: JSON.stringify({ field_parameter_selections: selections }),
  })
}

// === Calculation Groups API ===

export interface CalcGroupItem {
  name: string
  expression?: string
  format_string_expression?: string
}

export interface CalcGroupMeta {
  name: string
  precedence?: number
  items: CalcGroupItem[]
}

// Calculation groups definitions (for CRUD)
export interface CalcGroupDef {
  precedence?: number
  items: Array<{
    name: string
    expression: string
    format_string_expression?: string
  }>
}

export async function getCalculationGroups(project?: string) {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  return apiRequest<{ 
    calculation_groups: Record<string, CalcGroupDef>
  }>(`/calculation_groups${params}`)
}

export async function updateCalculationGroups(defs: Record<string, CalcGroupDef>, project?: string) {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  return apiRequest<{ 
    calculation_groups: Record<string, CalcGroupDef>
  }>(`/calculation_groups${params}`, {
    method: 'PUT',
    body: JSON.stringify({ calculation_groups: defs }),
  })
}

export async function getCalcGroupSelections(project?: string) {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  return apiRequest<{ 
    calc_group_selections: Record<string, string>
    selections: Record<string, string>
  }>(`/calc_group_selections${params}`)
}

export async function updateCalcGroupSelections(selections: Record<string, string>, project?: string) {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  return apiRequest<{ 
    calc_group_selections: Record<string, string>
    selections: Record<string, string>
  }>(`/calc_group_selections${params}`, {
    method: 'PUT',
    body: JSON.stringify({ calc_group_selections: selections }),
  })
}

// === What-If Parameters API ===

export interface WhatIfParameterMeta {
  name: string
  min: number
  max: number
  step: number
  default: number
  format?: string
}

export interface WhatIfParameterDef {
  min: number
  max: number
  step: number
  default: number
  format?: string
}

export async function getWhatIfParameters(project?: string, role?: string) {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  const headers: Record<string, string> = {}
  if (role) headers['X-Role'] = role
  
  return apiRequest<{ 
    what_if_parameters: WhatIfParameterMeta[]
    what_if_parameters_defs: Record<string, WhatIfParameterDef> 
  }>(`/what_if_parameters${params}`, { headers })
}

export async function updateWhatIfParameters(defs: Record<string, WhatIfParameterDef>, project?: string) {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  return apiRequest<{ 
    what_if_parameters: WhatIfParameterMeta[]
    what_if_parameters_defs: Record<string, WhatIfParameterDef> 
  }>(`/what_if_parameters${params}`, {
    method: 'PUT',
    body: JSON.stringify({ what_if_parameters_defs: defs }),
  })
}

export async function getWhatIfSelections(project?: string) {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  return apiRequest<{ 
    what_if_selections: Record<string, number>
    selections: Record<string, number>
  }>(`/what_if_selections${params}`)
}

export async function updateWhatIfSelections(selections: Record<string, number>, project?: string) {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  return apiRequest<{ 
    what_if_selections: Record<string, number>
    selections: Record<string, number>
  }>(`/what_if_selections${params}`, {
    method: 'PUT',
    body: JSON.stringify({ what_if_selections: selections }),
  })
}

export function getReportResourceUrl(resource: string, project?: string): string {
  const params = new URLSearchParams()
  params.set('resource', resource)
  if (project) params.set('project', project)
  return `${BASE_URL}/report_resource?${params.toString()}`
}

// === Slicers API ===

// Shared column reference for slicers
export interface SlicerColumnDef {
  table: string
  column: string
}

export interface SlicerDefaults {
  mode?: 'none' | 'measure' | 'measure_set'
  apply_on_load?: boolean
  measure?: { type: string; name: string }
  date_range?: {
    start_measure?: { type: string; name: string }
    end_measure?: { type: string; name: string }
  }
}

// --- Unified Slicer Model (authoritative) ---

/** Per-page entry: visibility, sync, and layout */
export interface SlicerPageEntry {
  visible: boolean
  sync: boolean
  layout: { x: number; y: number; w: number; h: number }
}

export interface SlicerSelection {
  mode?: 'all' | 'values' | 'range' | 'relative' | string
  values?: unknown[]
  start?: string | null
  end?: string | null
  direction?: 'last' | 'next' | 'this' | string
  count?: number
  unit?: 'minute' | 'hour' | 'day' | 'week' | 'month' | 'quarter' | 'year' | string
  include_today?: boolean
  include_current?: boolean
  window?: 'rolling' | 'calendar' | string
  anchor?: string
}

/** A slicer with per-page placement (replaces old def + instance split) */
export interface SlicerImageUi {
  image_fit?: 'cover' | 'contain' | 'fill' | 'none' | 'scale-down' | string
  image_position?: string
  image_saturation?: number | string
  image_background?: string
  image_padding?: number | string
}

export interface UnifiedSlicer {
  id: string
  name: string
  column: SlicerColumnDef
  type?: 'list' | 'dropdown' | 'date_range' | 'button' | 'tile' | 'input' | 'relative_date' | 'relative_time'
  behavior?: { apply_to?: string; auto_apply?: boolean; force_selection?: boolean }
  selection?: SlicerSelection
  ui?: ({ multi?: boolean; search?: boolean; style?: string; show_select_all?: boolean; paste_values?: boolean; leaf_only?: boolean; filter_operator?: string; input_mode?: 'filter' | 'input' | string } & SlicerImageUi)
  sync_group?: string
  defaults?: SlicerDefaults
  title?: string
  pages: Record<string, SlicerPageEntry>
}

export interface UnifiedSlicersPayload {
  slicers: UnifiedSlicer[]
}

// --- Legacy types (backward-compat projections) ---

/** @deprecated Use UnifiedSlicer instead */
export interface SlicerDef {
  id: string
  name: string
  column: SlicerColumnDef
  table?: string
  type?: 'list' | 'dropdown' | 'date_range' | 'button' | 'tile' | 'input' | 'relative_date' | 'relative_time'
  page_id?: string
  sync_group?: string
  selection_type?: 'single' | 'multi'
  show_select_all?: boolean
  search_enabled?: boolean
  auto_apply?: boolean
  force_selection?: boolean
  apply_to?: string
  style?: string
  paste_values?: boolean
  leaf_only?: boolean
  image_fit?: string
  image_position?: string
  image_saturation?: number | string
  image_background?: string
  image_padding?: number | string
  filter_operator?: string
  input_mode?: 'filter' | 'input' | string
  selection?: SlicerSelection
  defaults?: SlicerDefaults
  pages?: Record<string, SlicerPageEntry>
}

/** @deprecated Use UnifiedSlicersPayload instead */
export interface SlicerDefsPayload {
  defs: SlicerDef[]
}

/** @deprecated Use UnifiedSlicer.pages instead */
export interface SlicerInstance {
  id: string
  def_id: string
  page_id: string
  x?: number
  y?: number
  width?: number
  height?: number
  selected_values?: unknown[]
}

/** @deprecated Use UnifiedSlicersPayload instead */
export interface SlicerInstancesPayload {
  instances: SlicerInstance[]
}

// Slicer Values response (for dropdown/list population)
export interface SlicerValuesResponse {
  values: unknown[]
  total?: number
  has_more?: boolean
}

// Get all slicer definitions
export async function getSlicerDefs(project?: string): Promise<ApiResponse<SlicerDefsPayload>> {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  return apiRequest<SlicerDefsPayload>(`/slicers/defs${params}`)
}

// Save all slicer definitions (bulk replace)
export async function saveSlicerDefs(defs: SlicerDefsPayload, project?: string): Promise<ApiResponse<SlicerDefsPayload>> {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  return apiRequest<SlicerDefsPayload>(`/slicers/defs${params}`, {
    method: 'PUT',
    body: JSON.stringify(defs),
  })
}

// Create a single slicer definition
export async function createSlicerDef(def: Omit<SlicerDef, 'id'> & { id?: string }, project?: string): Promise<ApiResponse<SlicerDefsPayload>> {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  return apiRequest<SlicerDefsPayload>(`/slicers/defs${params}`, {
    method: 'POST',
    body: JSON.stringify({ def }),
  })
}

// Update a slicer definition
export async function updateSlicerDef(defId: string, def: Partial<SlicerDef>, project?: string): Promise<ApiResponse<SlicerDefsPayload>> {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  return apiRequest<SlicerDefsPayload>(`/slicers/defs/${encodeURIComponent(defId)}${params}`, {
    method: 'PUT',
    body: JSON.stringify({ def }),
  })
}

// Delete a slicer definition
export async function deleteSlicerDef(defId: string, project?: string): Promise<ApiResponse<SlicerDefsPayload>> {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  return apiRequest<SlicerDefsPayload>(`/slicers/defs/${encodeURIComponent(defId)}${params}`, {
    method: 'DELETE',
  })
}

// Get all slicer instances
export async function getSlicerInstances(project?: string): Promise<ApiResponse<SlicerInstancesPayload>> {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  return apiRequest<SlicerInstancesPayload>(`/slicers/instances${params}`)
}

// Save all slicer instances (bulk replace)
export async function saveSlicerInstances(instances: SlicerInstancesPayload, project?: string): Promise<ApiResponse<SlicerInstancesPayload>> {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  return apiRequest<SlicerInstancesPayload>(`/slicers/instances${params}`, {
    method: 'PUT',
    body: JSON.stringify(instances),
  })
}

// Create a slicer instance
export async function createSlicerInstance(instance: Omit<SlicerInstance, 'id'> & { id?: string }, project?: string): Promise<ApiResponse<SlicerInstancesPayload>> {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  return apiRequest<SlicerInstancesPayload>(`/slicers/instances${params}`, {
    method: 'POST',
    body: JSON.stringify({ instance }),
  })
}

// Update a slicer instance
export async function updateSlicerInstance(instanceId: string, instance: Partial<SlicerInstance>, project?: string): Promise<ApiResponse<SlicerInstancesPayload>> {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  return apiRequest<SlicerInstancesPayload>(`/slicers/instances/${encodeURIComponent(instanceId)}${params}`, {
    method: 'PUT',
    body: JSON.stringify({ instance }),
  })
}

// Delete a slicer instance
export async function deleteSlicerInstance(instanceId: string, project?: string): Promise<ApiResponse<SlicerInstancesPayload>> {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  return apiRequest<SlicerInstancesPayload>(`/slicers/instances/${encodeURIComponent(instanceId)}${params}`, {
    method: 'DELETE',
  })
}

// --- Unified Slicer API (authoritative) ------------------------------------

/** Get all slicers in unified format */
export async function getUnifiedSlicers(project?: string): Promise<ApiResponse<UnifiedSlicersPayload>> {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  return apiRequest<UnifiedSlicersPayload>(`/slicers${params}`)
}

/** Bulk-replace all slicers */
export async function saveUnifiedSlicers(slicers: UnifiedSlicersPayload, project?: string): Promise<ApiResponse<UnifiedSlicersPayload>> {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  return apiRequest<UnifiedSlicersPayload>(`/slicers${params}`, {
    method: 'PUT',
    body: JSON.stringify(slicers),
  })
}

/** Create a single slicer */
export async function createUnifiedSlicer(slicer: Omit<UnifiedSlicer, 'id'> & { id?: string }, project?: string): Promise<ApiResponse<UnifiedSlicersPayload>> {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  return apiRequest<UnifiedSlicersPayload>(`/slicers/create${params}`, {
    method: 'POST',
    body: JSON.stringify({ slicer }),
  })
}

/** Update a single slicer */
export async function updateUnifiedSlicer(slicerId: string, slicer: Partial<UnifiedSlicer>, project?: string): Promise<ApiResponse<UnifiedSlicersPayload>> {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  return apiRequest<UnifiedSlicersPayload>(`/slicers/${encodeURIComponent(slicerId)}${params}`, {
    method: 'PUT',
    body: JSON.stringify({ slicer }),
  })
}

/** Delete a single slicer */
export async function deleteUnifiedSlicer(slicerId: string, project?: string): Promise<ApiResponse<UnifiedSlicersPayload>> {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  return apiRequest<UnifiedSlicersPayload>(`/slicers/${encodeURIComponent(slicerId)}${params}`, {
    method: 'DELETE',
  })
}

// --- Slicer Sync -----------------------------------------------------------

export interface SlicerSyncPageConfig {
  sync: boolean
  visible: boolean
}

export interface SlicerSyncEntry {
  sync_group?: string
  sync_pages: Record<string, SlicerSyncPageConfig>
}

export interface SlicerSyncPayload {
  sync: Record<string, SlicerSyncEntry>
  pages: Array<{ id: string; title: string }>
}

export async function getSlicerSync(project?: string): Promise<ApiResponse<SlicerSyncPayload>> {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  return apiRequest<SlicerSyncPayload>(`/slicers/sync${params}`)
}

export async function updateSlicerSync(
  defId: string,
  syncConfig: { sync_pages: Record<string, SlicerSyncPageConfig>; sync_group?: string },
  project?: string
): Promise<ApiResponse<{ status: string }>> {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  return apiRequest<{ status: string }>(`/slicers/sync/${encodeURIComponent(defId)}${params}`, {
    method: 'PUT',
    body: JSON.stringify(syncConfig),
  })
}

// Get slicer values for a given definition (with optional filter context)
export interface SlicerValuesRequest {
  def_id: string
  exclude_def_id?: string
  page_id?: string
  q?: string  // search query
  limit?: number
  offset?: number
  filters?: unknown[]
  slicer_defs?: SlicerDefsPayload  // unsaved override
}

export async function getSlicerValues(
  request: SlicerValuesRequest,
  project?: string,
  role?: string
): Promise<ApiResponse<SlicerValuesResponse>> {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  const headers: Record<string, string> = {}
  if (role) headers['X-Role'] = role
  
  return apiRequest<SlicerValuesResponse>(`/slicers/values${params}`, {
    method: 'POST',
    headers,
    body: JSON.stringify(request),
  })
}

// ============================================================================
// Selection State Engine (Phase 23D)
// ============================================================================

export interface SelectionStateRequest {
  filters?: unknown[]
  slicer_defs?: SlicerDefsPayload
  page_id?: string
  affected_fields?: Array<{ table: string; column: string }>
  include_counts?: boolean
}

export interface FieldSelectionState {
  all_values: unknown[]
  possible: unknown[]
  excluded: unknown[]
  counts?: Record<string, number>
  error?: string
}

export interface SelectionStateResponse {
  fields: Record<string, FieldSelectionState>
  elapsed_ms: number
}

export async function getSelectionState(
  request: SelectionStateRequest,
  project?: string,
  role?: string
): Promise<ApiResponse<SelectionStateResponse>> {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  const headers: Record<string, string> = {}
  if (role) headers['X-Role'] = role

  return apiRequest<SelectionStateResponse>(`/selection/state${params}`, {
    method: 'POST',
    headers,
    body: JSON.stringify(request),
  })
}

// ============================================================================
// Save All
// ============================================================================

// Save all project state (filters, visuals, security)
// NOTE: Slicers are persisted via unified /runtime/slicers endpoints, not Save All.
export interface SaveAllPayload {
  roles?: unknown[]
  default_role?: string | null
  filters?: unknown[]
  calc_group_selections_payload?: unknown
  field_parameter_selections_payload?: unknown
  visuals?: unknown[]
  model_layouts?: ModelLayoutPayload[]
  reporting_theme?: unknown
}

export async function saveAll(
  payload: SaveAllPayload,
  project?: string,
  role?: string
): Promise<ApiResponse<{ ok: boolean }>> {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  const headers: Record<string, string> = {}
  if (role) headers['X-Role'] = role

  return apiRequest<{ ok: boolean }>(`/save_all${params}`, {
    method: 'POST',
    headers,
    body: JSON.stringify(payload),
  })
}

// ============================================================================
// Export to Excel
// ============================================================================

// Download a blob file (used for Excel exports)
async function downloadBlob(url: string, filename: string, role?: string): Promise<void> {
  const headers: Record<string, string> = {}
  if (role) headers['X-Role'] = role

  const res = await fetch(url, { headers })
  if (!res.ok) {
    let msg = `HTTP ${res.status}`
    try {
      const data = await res.json()
      if (data && data.ok === false && data.error) msg = data.error
    } catch {
      // ignore
    }
    throw new Error(msg)
  }
  const blob = await res.blob()
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(a.href)
}

// Export a visual to Excel
export async function exportVisual(
  visualId: string,
  project?: string,
  role?: string
): Promise<void> {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  const url = `${BASE_URL}/visuals/${encodeURIComponent(visualId)}/export.xlsx${params}`
  return downloadBlob(url, `${visualId}.xlsx`, role)
}

// Export a page to Excel
export async function exportPage(
  pageId: string,
  project?: string,
  role?: string
): Promise<void> {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  const url = `${BASE_URL}/pages/${encodeURIComponent(pageId)}/export.xlsx${params}`
  return downloadBlob(url, `${pageId}.xlsx`, role)
}

// Fingerprint / build stamp
export interface FingerprintResponse {
  ok: boolean
  server_file: string
  cwd: string
  python: string
  git_head: string | null
  runtime_js_path: string
  runtime_js_size: number
  runtime_js_sha1: string | null
}

export async function getFingerprint(): Promise<ApiResponse<FingerprintResponse>> {
  return apiRequest<FingerprintResponse>('/_fingerprint')
}

// DAX Autocomplete
export interface AutocompleteResponse {
  prefix: string
  tables: string[]
  columns: string[]
  measures: string[]
  field_parameters: string[]
  calculation_groups: string[]
  functions: string[]
}

export async function getAutocomplete(
  prefix: string,
  project?: string,
  role?: string
): Promise<ApiResponse<AutocompleteResponse>> {
  const params = new URLSearchParams()
  if (prefix) params.set('prefix', prefix)
  if (project) params.set('project', project)
  const qs = params.toString()
  const headers: Record<string, string> = {}
  if (role) headers['X-Role'] = role
  return apiRequest<AutocompleteResponse>(`/autocomplete${qs ? '?' + qs : ''}`, { headers })
}

// ── Data View ──────────────────────────────────────────────────

export interface DataViewColumnInfo {
  name: string
  type: string
  is_calculated: boolean
  expression: string | null
  description: string | null
  sort_by_column?: string | null
}

export interface DataViewTableInfo {
  name: string
  columns: DataViewColumnInfo[]
  row_count: number
  column_count: number
  is_calculated: boolean
}

export interface DataViewRowsResponse {
  table: string
  columns: string[]
  rows: Record<string, unknown>[]
  page: number
  page_size: number
  total_rows: number
  total_pages: number
}

export interface ColumnProfile {
  name: string
  type: string
  is_calculated?: boolean
  total_count?: number
  non_null_count?: number
  null_count: number
  distinct_count: number
  completeness: number
  top_values: { value: string; count: number }[]
  min?: unknown
  max?: unknown
  mean?: number
  median?: number
  stddev?: number
  sum?: number
  p25?: number
  p75?: number
  date_range_days?: number
  avg_length?: number
  min_length?: number
  max_length?: number
  true_count?: number
  false_count?: number
}

export interface DataViewProfileResponse {
  table: string
  profiles: ColumnProfile[]
}

export async function getDataViewTables(
  project?: string,
  role?: string
): Promise<ApiResponse<{ tables: DataViewTableInfo[] }>> {
  const params = new URLSearchParams()
  if (project) params.set('project', project)
  const qs = params.toString()
  const headers: Record<string, string> = {}
  if (role) headers['X-Role'] = role
  return apiRequest<{ tables: DataViewTableInfo[] }>(`/data/tables${qs ? '?' + qs : ''}`, { headers })
}

export async function getDataViewRows(
  tableName: string,
  opts: {
    project?: string
    role?: string
    page?: number
    pageSize?: number
    sortColumn?: string
    sortDir?: string
    filters?: Record<string, unknown>
  } = {}
): Promise<ApiResponse<DataViewRowsResponse>> {
  const params = new URLSearchParams()
  if (opts.project) params.set('project', opts.project)
  if (opts.page) params.set('page', String(opts.page))
  if (opts.pageSize) params.set('page_size', String(opts.pageSize))
  if (opts.sortColumn) params.set('sort_column', opts.sortColumn)
  if (opts.sortDir) params.set('sort_dir', opts.sortDir)
  if (opts.filters) params.set('filters', JSON.stringify(opts.filters))
  const qs = params.toString()
  const headers: Record<string, string> = {}
  if (opts.role) headers['X-Role'] = opts.role
  return apiRequest<DataViewRowsResponse>(
    `/data/table/${encodeURIComponent(tableName)}/rows${qs ? '?' + qs : ''}`,    
    { headers }
  )
}

export async function getDataViewProfile(
  tableName: string,
  project?: string,
  role?: string
): Promise<ApiResponse<DataViewProfileResponse>> {
  const params = new URLSearchParams()
  if (project) params.set('project', project)
  const qs = params.toString()
  const headers: Record<string, string> = {}
  if (role) headers['X-Role'] = role
  return apiRequest<DataViewProfileResponse>(
    `/data/table/${encodeURIComponent(tableName)}/profile${qs ? '?' + qs : ''}`,    
    { headers }
  )
}

export async function getDataViewColumnValues(
  tableName: string,
  columnName: string,
  opts: { project?: string; role?: string; q?: string; limit?: number } = {}
): Promise<ApiResponse<{ values: string[] }>> {
  const params = new URLSearchParams()
  if (opts.project) params.set('project', opts.project)
  if (opts.q) params.set('q', opts.q)
  if (opts.limit) params.set('limit', String(opts.limit))
  const qs = params.toString()
  const headers: Record<string, string> = {}
  if (opts.role) headers['X-Role'] = opts.role
  return apiRequest<{ values: string[] }>(
    `/data/table/${encodeURIComponent(tableName)}/column/${encodeURIComponent(columnName)}/values${qs ? '?' + qs : ''}`,    
    { headers }
  )
}

// Export the request function for custom endpoints
export { apiRequest }

// ============================================================================
// Reporting Theme
// ============================================================================

import type { ReportingTheme } from '@/lib/theme-defaults'

export async function getReportingTheme(
  project?: string,
): Promise<ApiResponse<ReportingTheme>> {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  return apiRequest<ReportingTheme>(`/reporting_theme${params}`)
}

export async function saveReportingTheme(
  theme: ReportingTheme,
  project?: string,
): Promise<ApiResponse<{ ok: boolean }>> {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  return apiRequest<{ ok: boolean }>(`/reporting_theme${params}`, {
    method: 'PUT',
    body: JSON.stringify(theme),
  })
}

// ============================================================================
// Bookmarks (Phase 1.5)
// ============================================================================

export interface Bookmark {
  id: string
  name: string
  description?: string
  created_at?: string
  updated_at?: string
  current_page_id: string
  filters: Record<string, unknown>[]
  slicer_selections: Record<string, unknown[]>
  interaction_selections: Record<string, unknown>[]
  // Power BI-style capture options
  capture_page?: boolean
  capture_data?: boolean
  capture_display?: boolean
  capture_visual_layout?: boolean
  capture_visual_design?: boolean
  // Visual visibility map: visual_id → visible
  visual_visibility?: Record<string, boolean>
  // Visual layout: positions & sizes
  visual_layout?: Record<string, { x: number; y: number; width: number; height: number }>
  // Visual design: formatting metadata
  visual_design?: Record<string, { format?: Record<string, unknown>; advanced_plotly_patch?: Record<string, unknown> }>
}

export interface BookmarksPayload {
  bookmarks: Bookmark[]
}

export interface BookmarkApplyResponse {
  bookmark: Bookmark
  current_page_id: string
  filters: Record<string, unknown>[]
  slicer_selections: Record<string, unknown[]>
  interaction_selections: Record<string, unknown>[]
  visual_visibility?: Record<string, boolean>
  capture_page?: boolean
  capture_data?: boolean
  capture_display?: boolean
  capture_visual_layout?: boolean
  capture_visual_design?: boolean
  visual_layout?: Record<string, { x: number; y: number; width: number; height: number }>
  visual_design?: Record<string, { format?: Record<string, unknown>; advanced_plotly_patch?: Record<string, unknown> }>
}

// List all bookmarks
export async function getBookmarks(project?: string): Promise<ApiResponse<BookmarksPayload>> {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  return apiRequest<BookmarksPayload>(`/bookmarks${params}`)
}

// Bulk-replace all bookmarks
export async function saveBookmarks(payload: BookmarksPayload, project?: string): Promise<ApiResponse<BookmarksPayload>> {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  return apiRequest<BookmarksPayload>(`/bookmarks${params}`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  })
}

// Create a new bookmark
export async function createBookmark(bookmark: Omit<Bookmark, 'id'> & { id?: string }, project?: string): Promise<ApiResponse<BookmarksPayload>> {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  return apiRequest<BookmarksPayload>(`/bookmarks${params}`, {
    method: 'POST',
    body: JSON.stringify({ bookmark }),
  })
}

// Update an existing bookmark
export async function updateBookmark(bookmarkId: string, bookmark: Partial<Bookmark>, project?: string): Promise<ApiResponse<BookmarksPayload>> {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  return apiRequest<BookmarksPayload>(`/bookmarks/${encodeURIComponent(bookmarkId)}${params}`, {
    method: 'PUT',
    body: JSON.stringify({ bookmark }),
  })
}

// Delete a bookmark
export async function deleteBookmark(bookmarkId: string, project?: string): Promise<ApiResponse<BookmarksPayload>> {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  return apiRequest<BookmarksPayload>(`/bookmarks/${encodeURIComponent(bookmarkId)}${params}`, {
    method: 'DELETE',
  })
}

// Apply a bookmark (returns captured state for client to restore in-memory)
export async function applyBookmark(bookmarkId: string, project?: string): Promise<ApiResponse<BookmarkApplyResponse>> {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  return apiRequest<BookmarkApplyResponse>(`/bookmarks/${encodeURIComponent(bookmarkId)}/apply${params}`, {
    method: 'POST',
  })
}

// ── Explanation Playbook API ──────────────────────────────────────────

export interface PlaybookDetail {
  name: string
  version: string
  description: string
  default_materiality: { abs_threshold: number; rel_threshold: number; top_n: number }
  entry_edus: Array<{
    id: string
    metric: string
    comparator: string
    grain?: Record<string, string>
    description?: string
  }>
  drivers: Array<{
    id: string
    parent_edu_id: string
    mode: string
    child_metrics?: string[]
    dimension_table?: string
    dimension_column?: string
    effects?: string[]
    priority?: number
    description?: string
    materiality?: { abs_threshold: number; rel_threshold: number; top_n: number }
  }>
  evidence_providers?: Array<{
    id: string
    name: string
    description?: string
    table?: string
    columns?: string[]
    measure?: string
    grain?: string[]
  }>
  metadata?: Record<string, unknown>
}

export async function listPlaybooks(project?: string) {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  return apiRequest<{ playbooks: Array<{ name: string; version: string; description: string; entry_edu_count: number; driver_count: number }> }>(
    `/explanations/playbooks${params}`
  )
}

export async function getPlaybook(name: string, project?: string) {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  return apiRequest<{ playbook: PlaybookDetail }>(`/explanations/playbooks/${encodeURIComponent(name)}${params}`)
}

export async function savePlaybook(name: string, playbook: Partial<PlaybookDetail>, project?: string) {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  return apiRequest<{ playbook: PlaybookDetail }>(`/explanations/playbooks/${encodeURIComponent(name)}${params}`, {
    method: 'PUT',
    body: JSON.stringify(playbook),
  })
}

export async function deletePlaybook(name: string, project?: string) {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  return apiRequest<{ deleted: string }>(`/explanations/playbooks/${encodeURIComponent(name)}${params}`, {
    method: 'DELETE',
  })
}

// ── Playbook Graph (EDU Diagram) ──────────────────────────────────────

export interface EDUGraphNode {
  id: string
  name: string
  metric: string
  comparator: string
  driver_count: number
  is_entry: boolean
  description: string
}

export interface EDUGraphEdge {
  from: string
  to: string
  mode: 'additive' | 'dimensional' | 'effect'
  child_metric: string
  sign: string
  driver_id: string
  description: string
}

export interface EDUGraphResponse {
  nodes: EDUGraphNode[]
  edges: EDUGraphEdge[]
}

export async function getPlaybookGraph(name: string, project?: string) {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  return apiRequest<EDUGraphResponse>(
    `/explanations/playbooks/${encodeURIComponent(name)}/graph${params}`
  )
}

export async function executePlaybook(name: string, options?: { filters?: unknown; role?: string; grain_overrides?: Record<string, string> }, project?: string) {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  return apiRequest<{ playbook_name: string; playbook_version: string; nodes: unknown[]; metadata: Record<string, unknown> }>(
    `/explanations/execute/${encodeURIComponent(name)}${params}`,
    {
      method: 'POST',
      body: JSON.stringify(options || {}),
    }
  )
}

// ── EDU Virtual Fields API (Phase 10.14) ──────────────────────────────

export interface VirtualFieldDescriptor {
  name: string
  playbook_name: string
  edu_id: string
  field_type: 'Value' | 'Description'
  semantic_type: 'measure' | 'dimension'
  data_type: 'Decimal' | 'Text'
  description: string
}

export interface VirtualFieldDataRow {
  description: string
  value: number | null
}

export async function listVirtualFields(playbookName: string, project?: string) {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  return apiRequest<{ playbook: string; fields: VirtualFieldDescriptor[] }>(
    `/explanations/virtual-fields/${encodeURIComponent(playbookName)}${params}`
  )
}

export async function getVirtualFieldData(
  playbookName: string,
  body: { field: 'Value' | 'Description'; edu_id: string; filters?: Record<string, string> },
  project?: string,
) {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  return apiRequest<{ edu_id: string; value?: number | null; rows?: VirtualFieldDataRow[] }>(
    `/explanations/virtual-fields/${encodeURIComponent(playbookName)}/data${params}`,
    {
      method: 'POST',
      body: JSON.stringify(body),
    }
  )
}

// ── Forecast API (Phase 13.3) ─────────────────────────────────────────

export interface ForecastRow {
  grain_value: string
  forecast_value: number
  forecast_lower: number
  forecast_upper: number
}

export interface ForecastResult {
  measure: string
  algorithm: string
  cv_rmse: number | null
  cv_mape: number | null
  horizon: number
  grain: string
  version?: number
  model_artifacts?: {
    table: string
    measure: string
  }
  selection_reason?: string
  selection_factors?: {
    observations: number
    short_series_threshold: number
    seasonal_min_observations: number
    detected_seasonality_period: number | null
    is_stationary: boolean
    history_periods_requested?: number | null
    preprocessing_applied?: {
      robust_preprocess: boolean
      log_transform: boolean
      winsorize_quantile: number
      clipped_points: number
      clipped_share: number
    }
    algorithm_selection_mode?: 'heuristic' | 'cv_auto'
    candidate_algorithms?: string[]
  }
  quality_indicator?: {
    level: 'excellent' | 'good' | 'fair' | 'weak' | 'unknown'
    label: string
    summary: string
  }
  rows: ForecastRow[]
}

export interface ForecastTriggerOptions {
  history_periods?: number
  robust_preprocess?: boolean
  log_transform?: boolean
  algorithm_selection_mode?: 'heuristic' | 'cv_auto'
}

export async function triggerForecast(
  measure: string,
  horizon: number = 6,
  grain?: string,
  project?: string,
  options?: ForecastTriggerOptions,
): Promise<ForecastResult> {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  const body: Record<string, unknown> = { measure, horizon }
  if (grain) body.grain = grain
  if (typeof options?.history_periods === 'number') body.history_periods = options.history_periods
  if (typeof options?.robust_preprocess === 'boolean') body.robust_preprocess = options.robust_preprocess
  if (typeof options?.log_transform === 'boolean') body.log_transform = options.log_transform
  if (options?.algorithm_selection_mode) body.algorithm_selection_mode = options.algorithm_selection_mode
  const resp = await apiRequest<ForecastResult>(
    `/explanations/forecast${params}`,
    {
      method: 'POST',
      body: JSON.stringify(body),
    }
  )
  if (resp.error) throw new Error(resp.error)
  return resp.data as ForecastResult
}

export async function getForecast(
  measure: string,
  project?: string,
): Promise<ForecastResult> {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  const resp = await apiRequest<ForecastResult>(
    `/explanations/forecast/${encodeURIComponent(measure)}${params}`
  )
  if (resp.error) throw new Error(resp.error)
  return resp.data as ForecastResult
}
// ── Regime Change Detection API (Phase 13.4) ─────────────────────────

export interface RegimeChangeEvent {
  driver: string
  old_rank: number
  new_rank: number
  period: number
  confidence: number
  measure?: string | null
}

export interface RegimeChangeDetectorDetails {
  algorithm: string
  algorithm_description: string
  cost_model: string
  min_periods: number
  penalty_formula: string
  penalty_multiplier: number
  confidence_formula: string
  informational_only: boolean
}

export interface RegimeChangeAnalysisDetails {
  playbook: string
  measure: string | null
  drivers_considered: number
  periods_evaluated: number
  inferred_date_column?: string | null
  effective_date_column?: string | null
  grain_inferred?: string | null
  grain_effective?: string | null
  date_overridden?: boolean
  grain_overridden?: boolean
  date_column_options?: Array<{ table: string; column: string; ref: string; type: string }>
  grain_options?: string[]
}

export interface RegimeChangeResponse {
  regime_changes: RegimeChangeEvent[]
  detector: RegimeChangeDetectorDetails
  analysis: RegimeChangeAnalysisDetails
}

export interface RegimeChangeRequestOptions {
  dateTable?: string
  dateColumn?: string
  grain?: string
}

export async function fetchRegimeChanges(
  playbook: string,
  project?: string,
  options?: RegimeChangeRequestOptions,
): Promise<RegimeChangeResponse> {
  const queryParams = new URLSearchParams()
  if (project) queryParams.set('project', project)
  if (options?.dateTable) queryParams.set('date_table', options.dateTable)
  if (options?.dateColumn) queryParams.set('date_column', options.dateColumn)
  if (options?.grain) queryParams.set('grain', options.grain)
  const params = queryParams.toString() ? `?${queryParams.toString()}` : ''
  const resp = await apiRequest<RegimeChangeResponse>(
    `/explanations/regime-changes/${encodeURIComponent(playbook)}${params}`
  )
  if (resp.error) throw new Error(resp.error)
  return {
    regime_changes: resp.data?.regime_changes ?? [],
    detector: resp.data?.detector ?? {
      algorithm: 'Unknown',
      algorithm_description: '',
      cost_model: 'unknown',
      min_periods: 0,
      penalty_formula: '',
      penalty_multiplier: 0,
      confidence_formula: '',
      informational_only: true,
    },
    analysis: resp.data?.analysis ?? {
      playbook,
      measure: null,
      drivers_considered: 0,
      periods_evaluated: 0,
      inferred_date_column: null,
      effective_date_column: null,
      grain_inferred: 'Month',
      grain_effective: 'Month',
      date_overridden: false,
      grain_overridden: false,
      date_column_options: [],
      grain_options: ['Day', 'Week', 'Month', 'Quarter', 'Year'],
    },
  }
}

// ── Report Auto-Generation Wizard API (Phase 12) ─────────────────────

// --- Autogen types ---

export interface AutogenColumnInfo {
  name: string
  type: string
  is_calculated: boolean
}

export interface AutogenTableInfo {
  name: string
  column_count: number
  is_calculated: boolean
  table_type: string | null
}

export interface AutogenMeasureInfo {
  name: string
  expression: string
  description?: string | null
  format?: string | null
}

export interface AutogenRelationship {
  from_table: string
  from_column: string
  to_table: string
  to_column: string
  active: boolean
}

export interface AutogenDateTable {
  table: string
  date_column: string
  has_year: boolean
  has_month: boolean
  has_quarter: boolean
}

export interface AutogenDimensionSuggestion {
  table: string
  column: string
  cardinality: number | null
}

export interface AutogenValueMeasure {
  name: string
  expression: string
  table: string
  column: string
}

export interface AutogenIntrospection {
  tables: AutogenTableInfo[]
  columns: Record<string, AutogenColumnInfo[]>
  measures: AutogenMeasureInfo[]
  relationships: AutogenRelationship[]
  date_table: AutogenDateTable | null
  value_measures: AutogenValueMeasure[]
  dimension_suggestions: Record<string, AutogenDimensionSuggestion[]>
}

export interface TargetMeasure {
  name: string
  expression?: string | null
  is_value_measure: boolean
  quantity_column?: string | null
  decomposition?: Array<{ metric: string; sign: number }> | null
  dimensions?: Array<{ table: string; column: string }> | null
}

export interface WizardInput {
  targets: TargetMeasure[]
  comparator: string
  date_table: string
  date_column: string
}

export interface WizardOutput {
  measures: Array<Record<string, unknown>>
  playbook: Record<string, unknown>
  field_parameters: Array<Record<string, unknown>>
  pages: Array<Record<string, unknown>>
  summary: string
}

export interface AutogenValidationResult {
  valid: boolean
  errors: string[]
}

// --- Autogen API helpers ---

async function autogenRequest<T>(
  endpoint: string,
  options: RequestInit = {}
): Promise<ApiResponse<T>> {
  const url = `/autogen${endpoint}`
  const desktopToken = getDesktopToken()
  try {
    const response = await fetch(url, {
      ...options,
      headers: {
        'Content-Type': 'application/json',
        ...(desktopToken ? { 'X-Desktop-Token': desktopToken } : {}),
        ...options.headers,
      },
    })
    if (!response.ok) {
      const errorText = await response.text()
      return { error: errorText || `HTTP ${response.status}`, status: response.status }
    }
    const data = await response.json()
    if (data.ok === false) {
      return { error: data.error || 'Unknown error', status: response.status }
    }
    return { data: data as T, status: response.status }
  } catch (err) {
    return { error: err instanceof Error ? err.message : 'Unknown error' }
  }
}

export async function fetchAutogenIntrospect(project?: string): Promise<ApiResponse<AutogenIntrospection>> {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  return autogenRequest<AutogenIntrospection>(`/introspect${params}`, {
    method: 'POST',
    body: JSON.stringify({}),
  })
}

export async function validateAutogenInput(input: WizardInput, project?: string): Promise<ApiResponse<AutogenValidationResult>> {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  return autogenRequest<AutogenValidationResult>(`/validate${params}`, {
    method: 'POST',
    body: JSON.stringify(input),
  })
}

export async function runAutogenGenerate(input: WizardInput, project?: string): Promise<ApiResponse<WizardOutput>> {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  return autogenRequest<WizardOutput>(`/generate${params}`, {
    method: 'POST',
    body: JSON.stringify(input),
  })
}

export async function runAutogenPreview(input: WizardInput, project?: string): Promise<ApiResponse<Record<string, unknown>>> {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  return autogenRequest<Record<string, unknown>>(`/preview${params}`, {
    method: 'POST',
    body: JSON.stringify(input),
  })
}

// ── EDU Decomposition Suggestions ─────────────────────────────────────

export interface DecompositionChild {
  metric?: string
  sign?: number
  table?: string
  column?: string
}

export interface DecompositionSuggestion {
  mode: 'additive' | 'multiplicative' | 'dimensional'
  children: DecompositionChild[]
  reason: string
}

export interface SuggestDecompositionResult {
  measure: string
  suggestions: DecompositionSuggestion[]
  error?: string
}

export async function suggestDecomposition(
  measureName: string,
  project?: string
): Promise<ApiResponse<SuggestDecompositionResult>> {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  return apiRequest<SuggestDecompositionResult>(
    `/explanations/suggest-decomposition${params}`,
    {
      method: 'POST',
      body: JSON.stringify({ measure_name: measureName }),
    }
  )
}

// ── Product Subscription API (Phase 11.7) ─────────────────────────────

const SERVER_BASE_URL = '/server'

async function serverApiRequest<T>(
  endpoint: string,
  options: RequestInit = {}
): Promise<ApiResponse<T>> {
  const url = `${SERVER_BASE_URL}${endpoint}`
  const desktopToken = getDesktopToken()

  try {
    const response = await fetch(url, {
      ...options,
      headers: {
        'Content-Type': 'application/json',
        ...(desktopToken ? { 'X-Desktop-Token': desktopToken } : {}),
        ...options.headers,
      },
    })

    if (!response.ok) {
      const errorText = await response.text()
      return { error: errorText || `HTTP ${response.status}`, status: response.status }
    }

    const data = await response.json()
    if (data.ok === false) {
      return { error: data.error || 'Unknown error', status: response.status }
    }
    return { data: data, status: response.status }
  } catch (err) {
    return { error: err instanceof Error ? err.message : 'Unknown error' }
  }
}

export interface ProductSubscription {
  id: string
  configuration_id: string
  subscriber_email: string
  subscriber_name?: string | null
  created_by: string
  parameter_values: Record<string, string[]>
  schedule: string
  schedule_timezone: string
  delivery_format: string
  recipients: string[]
  enabled: boolean
  created_at: string
  last_delivered_at?: string | null
  visual_ids?: string[]
  page_ids?: string[]
}

export interface SubscriptionPreview {
  delivery_format: string
  recipient_count: number
  recipients: string[]
  subscriber_email: string
  scope: {
    mode: 'all' | 'pages' | 'visuals'
    page_ids: string[]
    visual_ids: string[]
  }
  parameter_values: Record<string, string[]>
  attachment: {
    filename: string
    format: string
    content_type: string
  }
  notes?: string[]
}

export interface SendNowResult {
  sent: boolean
  delivery_status: string
  delivered_at?: string | null
  subscription: ProductSubscription
  preview: SubscriptionPreview
}

export interface SubscriptionSmtpConfig {
  host: string
  port: number
  user: string
  from_addr: string
  use_ssl: boolean
  starttls: boolean
  password_set: boolean
  env_overrides?: Record<string, boolean>
}

export interface SubscriptionSmtpConfigUpdateInput {
  host: string
  port: number
  user?: string
  from_addr?: string
  use_ssl?: boolean
  starttls?: boolean
  password?: string
  clear_password?: boolean
}

export interface DispatchDueResult {
  due_count: number
  dispatched_count: number
  failed_count: number
  dispatched: Array<{ id: string; configuration_id: string; delivery_status: string; delivered_at?: string | null }>
  failures: Array<{ id: string; configuration_id: string; error: string }>
}

export interface ParameterDefinition {
  name: string
  display_name: string
  description?: string | null
  source_type: string
  source_table: string
  source_column: string
  value_source: string
  available_values?: string[] | null
  default_values: string[]
  required: boolean
  multi_select: boolean
  depends_on?: string | null
}

export interface SubscriptionCreateInput {
  configuration_id: string
  subscriber_email: string
  subscriber_name?: string
  created_by?: string
  parameter_values?: Record<string, string[]>
  schedule?: string
  schedule_timezone?: string
  delivery_format?: string
  recipients: string[]
  enabled?: boolean
  visual_ids?: string[]
  page_ids?: string[]
}

export interface SubscriptionUpdateInput {
  parameter_values?: Record<string, string[]>
  schedule?: string
  schedule_timezone?: string
  delivery_format?: string
  recipients?: string[]
  enabled?: boolean
  subscriber_name?: string
  visual_ids?: string[]
  page_ids?: string[]
}

export async function listSubscriptions(
  configurationId?: string,
  subscriber?: string,
  project?: string,
): Promise<ApiResponse<{ subscriptions: ProductSubscription[] }>> {
  const params = new URLSearchParams()
  if (configurationId) params.set('configuration_id', configurationId)
  if (subscriber) params.set('subscriber', subscriber)
  if (project) params.set('project', project)
  const qs = params.toString() ? `?${params.toString()}` : ''
  return serverApiRequest<{ subscriptions: ProductSubscription[] }>(`/subscriptions${qs}`)
}

export async function getSubscription(
  subId: string,
  project?: string,
): Promise<ApiResponse<{ subscription: ProductSubscription }>> {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  return serverApiRequest<{ subscription: ProductSubscription }>(`/subscriptions/${encodeURIComponent(subId)}${params}`)
}

export async function createSubscription(
  input: SubscriptionCreateInput,
  project?: string,
): Promise<ApiResponse<{ subscription: ProductSubscription }>> {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  return serverApiRequest<{ subscription: ProductSubscription }>(`/subscriptions${params}`, {
    method: 'POST',
    body: JSON.stringify(input),
  })
}

export async function updateSubscription(
  subId: string,
  input: SubscriptionUpdateInput,
  project?: string,
): Promise<ApiResponse<{ subscription: ProductSubscription }>> {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  return serverApiRequest<{ subscription: ProductSubscription }>(`/subscriptions/${encodeURIComponent(subId)}${params}`, {
    method: 'PUT',
    body: JSON.stringify(input),
  })
}

export async function deleteSubscription(
  subId: string,
  project?: string,
): Promise<ApiResponse<{ deleted: string }>> {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  return serverApiRequest<{ deleted: string }>(`/subscriptions/${encodeURIComponent(subId)}${params}`, {
    method: 'DELETE',
  })
}

export async function toggleSubscription(
  subId: string,
  enabled: boolean,
  project?: string,
): Promise<ApiResponse<{ subscription: ProductSubscription }>> {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  return serverApiRequest<{ subscription: ProductSubscription }>(`/subscriptions/${encodeURIComponent(subId)}/toggle${params}`, {
    method: 'POST',
    body: JSON.stringify({ enabled }),
  })
}

export async function getDueSubscriptions(
  project?: string,
): Promise<ApiResponse<{ subscriptions: ProductSubscription[] }>> {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  return serverApiRequest<{ subscriptions: ProductSubscription[] }>(`/subscriptions/due${params}`)
}

export async function getParameters(
  configurationId: string,
  project?: string,
): Promise<ApiResponse<{ configuration_id: string; parameters: ParameterDefinition[] }>> {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  return serverApiRequest<{ configuration_id: string; parameters: ParameterDefinition[] }>(
    `/parameters/${encodeURIComponent(configurationId)}${params}`
  )
}

export async function getParameterValues(
  configurationId: string,
  parameterName: string,
  parentSelections?: Record<string, string[]>,
  project?: string,
): Promise<ApiResponse<{ parameter_name: string; values: string[] }>> {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  return serverApiRequest<{ parameter_name: string; values: string[] }>(
    `/parameters/${encodeURIComponent(configurationId)}/values${params}`,
    {
      method: 'POST',
      body: JSON.stringify({
        parameter_name: parameterName,
        parent_selections: parentSelections || {},
      }),
    }
  )
}

export async function previewSubscription(
  subId: string,
  project?: string,
): Promise<ApiResponse<{ subscription: ProductSubscription; preview: SubscriptionPreview }>> {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  return serverApiRequest<{ subscription: ProductSubscription; preview: SubscriptionPreview }>(
    `/subscriptions/${encodeURIComponent(subId)}/preview${params}`
  )
}

export async function sendNowSubscription(
  subId: string,
  previewOnly = false,
  project?: string,
): Promise<ApiResponse<SendNowResult>> {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  return serverApiRequest<SendNowResult>(`/subscriptions/${encodeURIComponent(subId)}/send_now${params}`, {
    method: 'POST',
    body: JSON.stringify({ preview_only: previewOnly }),
  })
}

export async function getSubscriptionSmtpConfig(
  project?: string,
): Promise<ApiResponse<{ smtp_config: SubscriptionSmtpConfig }>> {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  return serverApiRequest<{ smtp_config: SubscriptionSmtpConfig }>(`/subscriptions/smtp/config${params}`)
}

export async function updateSubscriptionSmtpConfig(
  input: SubscriptionSmtpConfigUpdateInput,
  project?: string,
): Promise<ApiResponse<{ smtp_config: SubscriptionSmtpConfig }>> {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  return serverApiRequest<{ smtp_config: SubscriptionSmtpConfig }>(`/subscriptions/smtp/config${params}`, {
    method: 'PUT',
    body: JSON.stringify(input),
  })
}

export async function dispatchDueSubscriptions(
  limit = 100,
  project?: string,
): Promise<ApiResponse<DispatchDueResult>> {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  return serverApiRequest<DispatchDueResult>(`/subscriptions/dispatch_due${params}`, {
    method: 'POST',
    body: JSON.stringify({ limit }),
  })
}

// ── ML Status & Candidate Pruning API (Phase 13 UI) ──────────────────

export interface MLStatus {
  capabilities: {
    pruning: boolean
    forecast: boolean
    regime_change: boolean
  }
}

export interface CandidateScoreItem {
  dimension: string
  table: string
  eta_squared: number
  marginal_gain: number
  rank: number
  cramers_v_max: number
  skipped: boolean
  skip_reason: string | null
}

export interface CandidatePruningResult {
  target_measure: string
  selected_dimensions: CandidateScoreItem[]
  rejected_dimensions: CandidateScoreItem[]
  cumulative_variance_explained: number
  total_candidates_screened: number
}

export interface ForecastVersionSummary {
  version: number
  algorithm: string | null
  generated_ts: string | null
  is_active: boolean
  cv_rmse: number | null
  cv_mape: number | null
  row_count: number
}

export async function fetchMLStatus(): Promise<ApiResponse<MLStatus>> {
  return apiRequest<MLStatus>('/ml/status')
}

export async function runCandidatePruning(
  measure: string,
  candidates: string[],
  project?: string,
): Promise<ApiResponse<CandidatePruningResult>> {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  return apiRequest<CandidatePruningResult>(`/explanations/prune-candidates${params}`, {
    method: 'POST',
    body: JSON.stringify({ measure, candidates }),
  })
}

export async function listForecastVersions(
  measure: string,
  project?: string,
): Promise<ApiResponse<{ measure: string; versions: ForecastVersionSummary[] }>> {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  return apiRequest<{ measure: string; versions: ForecastVersionSummary[] }>(
    `/forecast/versions/${encodeURIComponent(measure)}${params}`
  )
}

export async function setActiveForecastVersion(
  measure: string,
  version: number,
  project?: string,
): Promise<ApiResponse<{ measure: string; active_version: number }>> {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  return apiRequest<{ measure: string; active_version: number }>(
    `/forecast/versions/${encodeURIComponent(measure)}/active${params}`,
    {
      method: 'PUT',
      body: JSON.stringify({ version }),
    }
  )
}

export async function deleteForecastVersion(
  measure: string,
  version: number,
  project?: string,
): Promise<ApiResponse<{ measure: string; deleted_version: number }>> {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  return apiRequest<{ measure: string; deleted_version: number }>(
    `/forecast/versions/${encodeURIComponent(measure)}/${version}${params}`,
    { method: 'DELETE' }
  )
}

export async function getForecastVersion(
  measure: string,
  version: number,
  project?: string,
): Promise<ForecastResult> {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  const resp = await apiRequest<ForecastResult>(
    `/forecast/versions/${encodeURIComponent(measure)}/${version}${params}`
  )
  if (resp.error) throw new Error(resp.error)
  return resp.data as ForecastResult
}

// ---------------------------------------------------------------------------
// Phase 18: Hypothesis Simulation
// ---------------------------------------------------------------------------

export interface SimulationOverrideInput {
  driver_id: string
  mode: 'delta' | 'target'
  value: number
}

export interface SimulationRequest {
  kpi_id: string
  overrides: SimulationOverrideInput[]
  comparator_context?: Record<string, unknown>
  context_fingerprint?: string
  role_context?: string
  project?: string
}

export interface SimulationResultResponse {
  projected_kpi_value: number
  projected_variance_vs_comparator: number
  projected_parent_impacts: Array<Record<string, unknown>>
  uncertainty_band: 'Narrow' | 'Medium' | 'Wide'
  confidence_tier: 'High' | 'Medium' | 'Low'
  simulation_mode: string
  computability_state: 'Computable' | 'Degraded' | 'NonComputable'
  computability_reasons: string[]
  scenario_status_detail: 'Computable' | 'DirectionalOnly' | 'InsufficientData'
  why_trace: Array<{
    driver_id: string
    contribution: number
    path: string[]
    description: string
  }>
  assumptions: string[]
  provenance: Record<string, unknown>
}

export async function simulateScenario(
  body: SimulationRequest,
): Promise<ApiResponse<{ simulation: SimulationResultResponse }>> {
  return apiRequest<{ simulation: SimulationResultResponse }>(
    '/decision/simulate',
    { method: 'POST', body: JSON.stringify(body) },
  )
}

export async function validateScenario(
  body: SimulationRequest,
): Promise<ApiResponse<{ valid: boolean; reasons: string[] }>> {
  return apiRequest<{ valid: boolean; reasons: string[] }>(
    '/decision/simulate/validate',
    { method: 'POST', body: JSON.stringify(body) },
  )
}

export async function getSimulationDetails(
  project?: string,
): Promise<ApiResponse<{ details: Record<string, unknown> }>> {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  return apiRequest<{ details: Record<string, unknown> }>(
    `/decision/simulate/details${params}`,
  )
}

// ---------------------------------------------------------------------------
// Signal configuration
// ---------------------------------------------------------------------------

export interface SignalRuleConfig {
  enabled: boolean
  severity_override: string | null
  description: string
  thresholds: Record<string, unknown>
}

export interface SignalConfig {
  signal_rules: Record<string, SignalRuleConfig>
  global_settings: {
    max_signals_per_kpi: number
    contradiction_pairs: string[][]
    severity_downgrade_on_degraded: boolean
  }
}

export async function getSignalConfig(
  project?: string,
): Promise<ApiResponse<{ config: SignalConfig }>> {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  return apiRequest<{ config: SignalConfig }>(
    `/decision/signals/config${params}`,
  )
}

export async function saveSignalConfig(
  config: SignalConfig,
  project?: string,
): Promise<ApiResponse<{ config: SignalConfig }>> {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  return apiRequest<{ config: SignalConfig }>(
    `/decision/signals/config${params}`,
    { method: 'PUT', body: JSON.stringify({ config }) },
  )
}

// ---------------------------------------------------------------------------
// Phase 19: Project Management
// ---------------------------------------------------------------------------

export interface RecentProject {
  path: string
  name: string
  last_opened: string
}

export interface DirectoryItem {
  name: string
  path: string
  is_project: boolean
}

export interface BrowseResult {
  current: string
  items: DirectoryItem[]
}

export async function getRecentProjects(): Promise<ApiResponse<{ projects: RecentProject[] }>> {
  return apiRequest<{ projects: RecentProject[] }>('/project/recent')
}

export async function addRecentProject(
  path: string,
  name?: string,
): Promise<ApiResponse<{ projects: RecentProject[] }>> {
  return apiRequest<{ projects: RecentProject[] }>('/project/recent/add', {
    method: 'POST',
    body: JSON.stringify({ path, name }),
  })
}

export async function removeRecentProject(
  path: string,
): Promise<ApiResponse<{ projects: RecentProject[] }>> {
  return apiRequest<{ projects: RecentProject[] }>('/project/recent/remove', {
    method: 'POST',
    body: JSON.stringify({ path }),
  })
}

export async function browseDirectories(
  path?: string,
): Promise<ApiResponse<BrowseResult>> {
  const params = path ? `?path=${encodeURIComponent(path)}` : ''
  return apiRequest<BrowseResult>(`/project/browse${params}`)
}

export async function createProject(
  path: string,
  name?: string,
): Promise<ApiResponse<{ project: string; name: string }>> {
  return apiRequest<{ project: string; name: string }>('/project/create', {
    method: 'POST',
    body: JSON.stringify({ path, name }),
  })
}

export async function saveProjectAs(
  source: string,
  target: string,
): Promise<ApiResponse<{ project: string; name: string }>> {
  return apiRequest<{ project: string; name: string }>('/project/save_as', {
    method: 'POST',
    body: JSON.stringify({ source, target }),
  })
}

export function getProjectExportUrl(project: string): string {
  return `${BASE_URL}/project/export?project=${encodeURIComponent(project)}`
}

export async function importProjectZip(
  file: File,
  target: string,
): Promise<ApiResponse<{ project: string; name: string }>> {
  const formData = new FormData()
  formData.append('file', file)
  const url = `${BASE_URL}/project/import?target=${encodeURIComponent(target)}`
  const desktopToken = getDesktopToken()
  try {
    const response = await fetch(url, {
      method: 'POST',
      headers: {
        ...(desktopToken ? { 'X-Desktop-Token': desktopToken } : {}),
      },
      body: formData,
    })
    if (!response.ok) {
      const errorText = await response.text()
      return { error: errorText || `HTTP ${response.status}`, status: response.status }
    }
    const data = await response.json()
    if (data.ok === false) {
      return { error: data.error || 'Unknown error', status: response.status }
    }
    return { data: data.data ?? data, status: response.status }
  } catch (err) {
    return { error: err instanceof Error ? err.message : 'Unknown error' }
  }
}

export async function refreshProjectData(
  project: string,
): Promise<ApiResponse<{ sources: Array<{ name: string; path: string }> }>> {
  return apiRequest<{ sources: Array<{ name: string; path: string }> }>(
    '/project/refresh',
    { method: 'POST', body: JSON.stringify({ project }) },
  )
}

// ─── TMDL Converter ──────────────────────────────────────────────────

export interface TmdlTablePreview {
  name: string
  columns: number
  measures: number
  hierarchies: number
  is_calculated: boolean
  is_hidden: boolean
  has_calc_group: boolean
  csv_source: string | null
  csv_exists: boolean
  will_skip: boolean
}

export interface TmdlPreviewResult {
  definition_path: string
  tables: TmdlTablePreview[]
  relationships: Array<{ from: string; to: string; active: boolean }>
  roles: Array<{ name: string; rules: number }>
  summary: {
    total_tables: number
    importable_tables: number
    skipped_tables: number
    total_relationships: number
    total_roles: number
    total_measures: number
    data_sources_found: number
    data_sources_missing: number
  }
}

export interface TmdlConvertResult {
  project_path: string
  tables_created: string[]
  measures_created: number
  relationships_created: number
  hierarchies_created: number
  roles_created: number
  calc_groups_created: number
  data_files_copied: string[]
  data_files_missing: string[]
  skipped_tables: string[]
  warnings: string[]
}

export async function previewTmdl(
  definitionPath: string,
): Promise<ApiResponse<TmdlPreviewResult>> {
  return apiRequest<TmdlPreviewResult>('/tmdl/preview', {
    method: 'POST',
    body: JSON.stringify({ definition_path: definitionPath }),
  })
}

export async function convertTmdl(opts: {
  definition_path: string
  output_path: string
  project_name?: string
  copy_data?: boolean
  skip_hidden_tables?: boolean
}): Promise<ApiResponse<TmdlConvertResult>> {
  return apiRequest<TmdlConvertResult>('/tmdl/convert', {
    method: 'POST',
    body: JSON.stringify(opts),
  })
}

// ============================================================================
// Stories (Phase 23E — Story/Navigation Layer)
// ============================================================================

export interface CapturedState {
  filters: Record<string, unknown>[]
  slicer_selections: Record<string, unknown[]>
  interaction_selections: Record<string, unknown>[]
  visual_visibility: Record<string, boolean>
}

export interface Slide {
  id: string
  page_id: string
  title: string
  narration: string
  captured_state?: CapturedState
  bookmark_id?: string
  /** Optional positioned annotation overlay text */
  annotation?: string
}

export interface Story {
  id: string
  name: string
  description?: string
  slides: Slide[]
  /** Presentation tab style: compact | normal | wide */
  navigator_style?: 'compact' | 'normal' | 'wide'
  /** Story content sizing: auto | fill | contained */
  sizing?: 'auto' | 'fill' | 'contained'
}

export interface StoriesPayload {
  stories: Story[]
}

export interface SlideApplyResponse {
  slide: Slide
  state: CapturedState & { page_id: string }
  source: 'captured_state' | 'bookmark' | 'empty'
}

// List all stories
export async function getStories(project?: string): Promise<ApiResponse<StoriesPayload>> {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  return apiRequest<StoriesPayload>(`/stories${params}`)
}

// Create a new story
export async function createStory(
  story: Omit<Story, 'id'> & { id?: string },
  project?: string,
): Promise<ApiResponse<StoriesPayload>> {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  return apiRequest<StoriesPayload>(`/stories${params}`, {
    method: 'POST',
    body: JSON.stringify({ story }),
  })
}

// Update a story
export async function updateStory(
  storyId: string,
  story: Partial<Story>,
  project?: string,
): Promise<ApiResponse<StoriesPayload>> {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  return apiRequest<StoriesPayload>(`/stories/${encodeURIComponent(storyId)}${params}`, {
    method: 'PUT',
    body: JSON.stringify({ story }),
  })
}

// Delete a story
export async function deleteStory(
  storyId: string,
  project?: string,
): Promise<ApiResponse<StoriesPayload>> {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  return apiRequest<StoriesPayload>(`/stories/${encodeURIComponent(storyId)}${params}`, {
    method: 'DELETE',
  })
}

// Apply a slide (resolve its state for client to restore in-memory)
export async function applySlide(
  storyId: string,
  slideId: string,
  project?: string,
): Promise<ApiResponse<SlideApplyResponse>> {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  return apiRequest<SlideApplyResponse>(
    `/stories/${encodeURIComponent(storyId)}/apply_slide${params}`,
    {
      method: 'POST',
      body: JSON.stringify({ slide_id: slideId }),
    },
  )
}

// Capture current view into a slide's captured_state (explicit save)
export async function captureSlide(
  storyId: string,
  slideId: string,
  state: CapturedState & { page_id: string },
  project?: string,
): Promise<ApiResponse<StoriesPayload>> {
  const params = project ? `?project=${encodeURIComponent(project)}` : ''
  return apiRequest<StoriesPayload>(
    `/stories/${encodeURIComponent(storyId)}/capture_slide${params}`,
    {
      method: 'POST',
      body: JSON.stringify({
        slide_id: slideId,
        ...state,
      }),
    },
  )
}

// ─── Report Transfer (PBIR → Project) ────────────────────────────────

export interface ReportTransferVisualPreview {
  visual_id: string
  visual_type_pbi: string
  visual_type_project: string
  page: string
  page_id: string
  title: string
  x: number
  y: number
  width: number
  height: number
  field_count: number
  filter_count: number
  is_supported: boolean
}

export interface ReportTransferPagePreview {
  page_id: string
  name: string
  order: number
  width: number
  height: number
  hidden: boolean
  is_drillthrough: boolean
}

export interface ReportTransferPreviewResult {
  report_name: string
  report_dir: string
  pages: ReportTransferPagePreview[]
  visuals: ReportTransferVisualPreview[]
  summary: {
    total_pages: number
    total_visuals: number
    supported_visuals: number
    unsupported_visuals: number
    unsupported_types: string[]
    total_fields: number
    total_visual_filters: number
    report_filters: number
    page_filters: number
    bookmarks: number
  }
}

export interface ReportTransferResult {
  project_path: string
  pages_created: number
  visuals_created: number
  filters_transferred: number
  bookmarks_transferred: number
  interactions_transferred: number
  warnings: string[]
  unsupported_visual_types: string[]
}

export async function previewReportTransfer(
  reportDir: string,
): Promise<ApiResponse<ReportTransferPreviewResult>> {
  return apiRequest<ReportTransferPreviewResult>('/report-transfer/preview', {
    method: 'POST',
    body: JSON.stringify({ report_dir: reportDir }),
  })
}

export async function executeReportTransfer(opts: {
  report_dir: string
  output_project?: string
  skip_unsupported?: boolean
  merge_existing?: boolean
}): Promise<ApiResponse<ReportTransferResult>> {
  return apiRequest<ReportTransferResult>('/report-transfer/execute', {
    method: 'POST',
    body: JSON.stringify(opts),
  })
}

// ─── Theme Transfer (PBI → Project) ────────────────────────────────

export interface PbiThemeMeta {
  foreground: string
  background: string
  tableAccent: string
  good: string
  bad: string
  neutral: string
  hyperlink: string
  allDataColors: string[]
}

export interface PbiThemeResult {
  name: string
  dataColors: string[]
  visualCard: Record<string, unknown>
  font: Record<string, unknown>
  chart: Record<string, unknown>
  canvas: Record<string, unknown>
  defaultSize: Record<string, unknown>
  _pbi_meta?: PbiThemeMeta
}

export async function extractPbiTheme(
  reportDir: string,
  apply?: boolean,
): Promise<ApiResponse<PbiThemeResult>> {
  return apiRequest<PbiThemeResult>('/report-transfer/theme', {
    method: 'POST',
    body: JSON.stringify({ report_dir: reportDir, apply: apply ?? false }),
  })
}

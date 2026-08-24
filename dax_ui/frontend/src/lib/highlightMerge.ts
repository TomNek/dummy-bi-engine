/**
 * Highlight overlay merge utility.
 *
 * Ports the old UI's `_mergeHighlightOverlayFigure()` logic:
 * when the server returns { baseline, highlight } for render_mode='highlight',
 * this module merges the two Plotly figures into a single figure
 * with the baseline faded and the highlight overlay on top.
 *
 * Supported visual types:
 * - bar: baseline traces at opacity 0.35, selected overlay at full opacity
 * - scatter: baseline at opacity 0.25, selected points as second trace
 * - card: baseline value shown, with "(sel: <value>)" appended to title
 */

/** Shape of a single side (baseline or highlight) from the server */
export interface HighlightSection {
  ok?: boolean
  sql?: string
  columns?: string[]
  rows?: Array<Record<string, unknown>>
  figure?: {
    data?: unknown[]
    layout?: Record<string, unknown>
    config?: Record<string, unknown>
  }
  error?: string
}

/** Full dual-query response from the server */
export interface HighlightResponse {
  ok?: boolean
  visual_id?: string
  baseline?: HighlightSection
  highlight?: HighlightSection
  query?: Record<string, unknown>
}

/** Plotly trace type (minimal) */
interface PlotlyTrace {
  x?: unknown[] | { bdata: string; dtype: string }
  y?: unknown[] | { bdata: string; dtype: string }
  name?: string
  opacity?: number
  marker?: Record<string, unknown>
  mode?: string
  type?: string
  [key: string]: unknown
}

/** Merged figure result */
export interface MergedFigure {
  data: PlotlyTrace[]
  layout: Record<string, unknown>
  config?: Record<string, unknown>
}

/**
 * Check whether a render response is a highlight dual-query response.
 */
export function isHighlightResponse(data: unknown): data is HighlightResponse {
  if (!data || typeof data !== 'object') return false
  const d = data as Record<string, unknown>
  return (
    d.baseline !== undefined &&
    d.highlight !== undefined &&
    typeof d.baseline === 'object' &&
    typeof d.highlight === 'object'
  )
}

/**
 * Decode a Plotly bdata-encoded array to a plain JS array.
 */
function decodePlotlyBdata(arrObj: unknown): unknown[] | null {
  if (!arrObj || typeof arrObj !== 'object') return null
  const obj = arrObj as { bdata?: string; dtype?: string }
  if (typeof obj.bdata !== 'string' || !obj.bdata) return null
  try {
    const raw = atob(obj.bdata)
    const bytes = new Uint8Array(raw.length)
    for (let i = 0; i < raw.length; i++) bytes[i] = raw.charCodeAt(i) & 0xff
    const dt = String(obj.dtype || '').toLowerCase()
    if (dt === 'f8') return Array.from(new Float64Array(bytes.buffer, bytes.byteOffset, bytes.byteLength / 8))
    if (dt === 'f4') return Array.from(new Float32Array(bytes.buffer, bytes.byteOffset, bytes.byteLength / 4))
    if (dt === 'i4') return Array.from(new Int32Array(bytes.buffer, bytes.byteOffset, bytes.byteLength / 4))
    if (dt === 'u4') return Array.from(new Uint32Array(bytes.buffer, bytes.byteOffset, bytes.byteLength / 4))
    if (dt === 'i2') return Array.from(new Int16Array(bytes.buffer, bytes.byteOffset, bytes.byteLength / 2))
    if (dt === 'u2') return Array.from(new Uint16Array(bytes.buffer, bytes.byteOffset, bytes.byteLength / 2))
    if (dt === 'i1') return Array.from(new Int8Array(bytes.buffer, bytes.byteOffset, bytes.byteLength))
    if (dt === 'u1') return Array.from(new Uint8Array(bytes.buffer, bytes.byteOffset, bytes.byteLength))
  } catch {
    // ignore decode errors
  }
  return null
}

/**
 * Normalize a Plotly array value — could be plain JS array or bdata-encoded.
 */
function toJsArray(v: unknown): unknown[] | null {
  if (Array.isArray(v)) return v
  if (v && typeof v === 'object') {
    const decoded = decodePlotlyBdata(v)
    if (decoded) return decoded
  }
  return null
}

/**
 * Merge highlight overlay for bar charts.
 * Baseline traces get opacity 0.35; a "Selected" overlay trace is added at full opacity,
 * aligned to baseline's x categories.
 */
function mergeBar(
  baseTraces: PlotlyTrace[],
  hiTraces: PlotlyTrace[],
  layout: Record<string, unknown>
): MergedFigure {
  const out: PlotlyTrace[] = baseTraces
    .filter(t => String(t?.name ?? '') !== 'Selected')
    .map(t => ({ ...t }))
  const baseTrace = out[0]
  const hiTrace = hiTraces[0]
  const baseX = baseTrace ? toJsArray(baseTrace.x) : null
  const hiX = hiTrace ? toJsArray(hiTrace.x) : null
  const hiY = hiTrace ? toJsArray(hiTrace.y) : null

  if (baseX && hiX && hiY) {
    const map = new Map<string, unknown>()
    for (let i = 0; i < hiX.length; i++) map.set(String(hiX[i]), hiY[i])
    const selectedY = baseX.map(x => (map.has(String(x)) ? map.get(String(x)) : null))

    // Fade baseline
    if (baseTrace) baseTrace.opacity = 0.35

    // Selected overlay
    const selectedTrace: PlotlyTrace = {
      ...(baseTrace ? { ...baseTrace } : {}),
      name: 'Selected',
      x: baseX,
      y: selectedY as unknown[],
      opacity: 1.0,
      marker: { ...((baseTrace?.marker ?? {}) as Record<string, unknown>), line: { width: 1 } },
    }
    out.push(selectedTrace)

    // Ensure baseline legend name
    if (out.length >= 2 && out[0] && !out[0].name) out[0].name = 'Total'
  }

  return {
    data: out,
    layout: { ...layout, barmode: 'overlay' },
  }
}

/**
 * Merge highlight overlay for scatter charts.
 * Baseline gets opacity 0.25; selected points shown as a second trace.
 */
function mergeScatter(
  baseTraces: PlotlyTrace[],
  hiTraces: PlotlyTrace[],
  layout: Record<string, unknown>
): MergedFigure {
  const out: PlotlyTrace[] = baseTraces
    .filter(t => String(t?.name ?? '') !== 'Selected')
    .map(t => ({ ...t }))
  const baseTrace = out[0]
  const hiTrace = hiTraces[0]
  const hiX = hiTrace ? toJsArray(hiTrace.x) : null
  const hiY = hiTrace ? toJsArray(hiTrace.y) : null

  if (baseTrace) baseTrace.opacity = 0.25

  if (hiX && hiY) {
    const selectedTrace: PlotlyTrace = {
      ...(baseTrace ? { ...baseTrace } : {}),
      type: 'scatter',
      mode: (baseTrace?.mode as string) || (hiTrace?.mode as string) || 'markers',
      x: hiX,
      y: hiY,
      name: 'Selected',
      opacity: 1.0,
      marker: { ...((baseTrace?.marker ?? {}) as Record<string, unknown>), symbol: 'circle-open' },
    }
    out.push(selectedTrace)
    if (out.length >= 2 && out[0] && !out[0].name) out[0].name = 'Total'
  }

  return { data: out, layout: { ...layout } }
}

/**
 * Merge highlight overlay for card visuals.
 * Shows baseline value with "(sel: <value>)" in the title.
 */
function mergeCard(
  baseline: HighlightSection,
  highlight: HighlightSection,
  layout: Record<string, unknown>
): { layout: Record<string, unknown>; rows: Array<Record<string, unknown>> } {
  const baseRows = Array.isArray(baseline?.rows) ? baseline.rows : []
  const hiRows = Array.isArray(highlight?.rows) ? highlight.rows : []
  const baseVal = baseRows[0] && typeof baseRows[0] === 'object' ? Object.values(baseRows[0])[0] : null
  const selVal = hiRows[0] && typeof hiRows[0] === 'object' ? Object.values(hiRows[0])[0] : null

  const outLayout = { ...layout }
  // Plotly serialises title as {text: "..."} — normalise to plain string
  if (outLayout.title && typeof outLayout.title === 'object' && (outLayout.title as Record<string, unknown>).text !== undefined) {
    outLayout.title = String((outLayout.title as Record<string, unknown>).text)
  }
  if (selVal !== null && selVal !== undefined) {
    outLayout.title = `${baseVal} (sel: ${selVal})`
  }

  return { layout: outLayout, rows: baseRows }
}

/**
 * Merge highlight overlay for line charts.
 * Baseline traces get opacity 0.25; highlight traces are rendered
 * at full opacity using the same trace colors.
 * If a baseline trace has no corresponding highlight trace, it stays dimmed.
 */
function mergeLine(
  baseTraces: PlotlyTrace[],
  hiTraces: PlotlyTrace[],
  layout: Record<string, unknown>
): MergedFigure {
  // Build a map of highlight trace names → highlight trace
  const hiByName = new Map<string, PlotlyTrace>()
  for (const t of hiTraces) {
    const name = String(t.name ?? '')
    if (name) hiByName.set(name, t)
  }

  const out: PlotlyTrace[] = []
  for (const base of baseTraces) {
    const name = String(base.name ?? '')
    const hi = name ? hiByName.get(name) : undefined

    // Always include the full baseline trace (dimmed)
    out.push({
      ...base,
      opacity: 0.25,
      showlegend: true,
    })

    // If there's a highlight match, overlay the highlighted portion
    if (hi) {
      out.push({
        ...hi,
        opacity: 1.0,
        showlegend: false,
        // Inherit color from baseline so consistent colors
        line: {
          ...((base.line ?? {}) as Record<string, unknown>),
          ...((hi.line ?? {}) as Record<string, unknown>),
        },
        marker: {
          ...((base.marker ?? {}) as Record<string, unknown>),
          ...((hi.marker ?? {}) as Record<string, unknown>),
        },
      })
    }
  }

  return { data: out, layout: { ...layout } }
}

/**
 * Main merge function: takes the dual-query response and produces merged render data
 * that the VisualCard can use directly.
 *
 * @param visualType - one of 'bar', 'scatter', 'card', etc.
 * @param response - the highlight dual-query response from the server
 * @returns merged render data with plotly_data / plotly_layout / rows / columns
 */
export function mergeHighlightResponse(
  visualType: string,
  response: HighlightResponse
): Record<string, unknown> {
  const baseline = response.baseline
  const highlight = response.highlight
  if (!baseline) return {}

  const baseFigData = baseline.figure?.data as PlotlyTrace[] | undefined
  const baseFigLayout = baseline.figure?.layout ?? {}
  const hiFigData = (highlight?.ok && highlight.figure?.data) ? highlight.figure.data as PlotlyTrace[] : null

  const vt = visualType.trim().toLowerCase()

  // Card: special handling (no Plotly chart, just value + title)
  if (vt === 'card') {
    const merged = mergeCard(baseline, highlight ?? {}, baseFigLayout)
    return {
      columns: baseline.columns,
      rows: merged.rows,
      plotly_layout: merged.layout,
      // Carry the original figure for fallback
      figure: baseline.figure,
      query: response.query,
      _highlight_merged: true,
      _card_title: merged.layout.title,
    }
  }

  // Table: show highlight rows when available, otherwise baseline.
  // Matches old UI behavior: tables in highlight mode display only the
  // filtered/highlighted rows rather than a merged overlay.
  if (vt === 'table') {
    const hiRows = Array.isArray(highlight?.rows) ? highlight!.rows : []
    const hiCols = Array.isArray(highlight?.columns) ? highlight!.columns : []
    const useHighlight = !!(highlight?.ok && hiRows.length > 0)
    return {
      columns: useHighlight ? hiCols : baseline.columns,
      rows: useHighlight ? hiRows : baseline.rows,
      plotly_data: undefined,
      plotly_layout: baseFigLayout,
      figure: baseline.figure,
      query: response.query,
      _highlight_merged: true,
    }
  }

  // No figure data — return baseline as-is
  if (!baseFigData || !hiFigData) {
    return {
      columns: baseline.columns,
      rows: baseline.rows,
      plotly_data: baseFigData,
      plotly_layout: baseFigLayout,
      figure: baseline.figure,
      query: response.query,
    }
  }

  // Bar charts
  if (vt === 'bar' || vt === 'column') {
    const merged = mergeBar(baseFigData, hiFigData, baseFigLayout)
    return {
      columns: baseline.columns,
      rows: baseline.rows,
      plotly_data: merged.data,
      plotly_layout: merged.layout,
      query: response.query,
      _highlight_merged: true,
    }
  }

  // Scatter
  if (vt === 'scatter') {
    const merged = mergeScatter(baseFigData, hiFigData, baseFigLayout)
    return {
      columns: baseline.columns,
      rows: baseline.rows,
      plotly_data: merged.data,
      plotly_layout: merged.layout,
      query: response.query,
      _highlight_merged: true,
    }
  }

  // Line / area charts (Plotly uses scatter with mode=lines)
  if (vt === 'line' || vt === 'area') {
    const merged = mergeLine(baseFigData, hiFigData, baseFigLayout)
    return {
      columns: baseline.columns,
      rows: baseline.rows,
      plotly_data: merged.data,
      plotly_layout: merged.layout,
      query: response.query,
      _highlight_merged: true,
    }
  }

  // Fallback: return baseline figure as-is
  return {
    columns: baseline.columns,
    rows: baseline.rows,
    plotly_data: baseFigData,
    plotly_layout: baseFigLayout,
    figure: baseline.figure,
    query: response.query,
  }
}

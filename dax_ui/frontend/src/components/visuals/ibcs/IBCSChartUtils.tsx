/**
 * IBCSChartUtils — Shared utilities for IBCS SVG chart renderers.
 *
 * Provides:
 * - Color tokens (IBCS-compliant)
 * - Number formatting (compact: K/M/B)
 * - Linear scale helper
 * - SVG pattern definitions (scenario fills)
 * - Variance helpers
 */

// ─── IBCS Color Tokens ──────────────────────────────────────────────────────

export const IBCS = {
  // Scenario colors
  actual:       '#404040',
  plan:         '#404040',      // outline only (fill=none, stroke=plan)
  previousYear: '#F5F5F5',
  forecast:     '#404040',      // diagonal hatch fill

  // Variance
  positive:     '#7ACA00',
  negative:     '#FF0000',

  // Text
  textPrimary:  '#404040',
  textSecondary:'#666666',
  textMuted:    '#999999',

  // Grid / structure
  gridLine:     '#e8e8e8',
  headerBg:     '#f5f5f5',
  totalBorder:  '#404040',

  // Dark-mode overrides (CSS custom properties preferred, these are fallbacks)
  dark: {
    actual:       '#e0e0e0',
    plan:         '#e0e0e0',
    previousYear: '#888888',
    forecast:     '#e0e0e0',
    textPrimary:  '#e0e0e0',
    textSecondary:'#aaaaaa',
    textMuted:    '#777777',
    gridLine:     '#333333',
    headerBg:     '#222222',
    totalBorder:  '#e0e0e0',
    positive:     '#2ecc71',
    negative:     '#e74c3c',
  },
} as const

// ─── Number Formatting ──────────────────────────────────────────────────────

/** Format a number in compact notation: 1200 → "1.2K", 2500000 → "2.5M" */
export function formatCompact(value: number, decimals = 1): string {
  const abs = Math.abs(value)
  if (abs >= 1e9)  return (value / 1e9).toFixed(decimals) + 'B'
  if (abs >= 1e6)  return (value / 1e6).toFixed(decimals) + 'M'
  if (abs >= 1e3)  return (value / 1e3).toFixed(decimals) + 'K'
  if (abs >= 1)    return value.toFixed(abs === Math.floor(abs) ? 0 : decimals)
  if (abs === 0)   return '0'
  return value.toFixed(decimals)
}

/** Format percentage: 0.125 → "+12.5%", -0.03 → "−3.0%" */
export function formatPercent(value: number, decimals = 1): string {
  const pct = value * 100
  const sign = pct > 0 ? '+' : pct < 0 ? '−' : ''
  return `${sign}${Math.abs(pct).toFixed(decimals)}%`
}

/** Format variance with sign: 200 → "+200", -150 → "−150" */
export function formatVariance(value: number, decimals = 1): string {
  const formatted = formatCompact(Math.abs(value), decimals)
  if (value > 0) return `+${formatted}`
  if (value < 0) return `−${formatted}`
  return formatted
}

// ─── Scale Helpers ──────────────────────────────────────────────────────────

export interface LinearScale {
  (value: number): number
  domain: [number, number]
  range: [number, number]
}

/** Create a simple linear scale: domain → range */
export function linearScale(domain: [number, number], range: [number, number]): LinearScale {
  const [d0, d1] = domain
  const [r0, r1] = range
  const span = d1 - d0 || 1
  const fn = ((value: number) => r0 + ((value - d0) / span) * (r1 - r0)) as LinearScale
  fn.domain = domain
  fn.range = range
  return fn
}

/** Compute nice axis domain from data values (includes zero for bar charts) */
export function niceExtent(values: number[], includeZero = true): [number, number] {
  if (values.length === 0) return [0, 1]
  let min = Math.min(...values)
  let max = Math.max(...values)
  if (includeZero) {
    min = Math.min(0, min)
    max = Math.max(0, max)
  }
  // Add 10% padding
  const pad = (max - min) * 0.1 || 1
  return [min - (min < 0 ? pad : 0), max + pad]
}

/** Generate nice tick values for an axis */
export function niceTicks(extent: [number, number], maxTicks = 5): number[] {
  const [min, max] = extent
  const range = max - min
  if (range === 0) return [min]

  const roughStep = range / maxTicks
  const mag = Math.pow(10, Math.floor(Math.log10(roughStep)))
  let step: number
  const norm = roughStep / mag
  if (norm <= 1.5) step = mag
  else if (norm <= 3) step = 2 * mag
  else if (norm <= 7) step = 5 * mag
  else step = 10 * mag

  const ticks: number[] = []
  const start = Math.ceil(min / step) * step
  for (let v = start; v <= max + step * 0.001; v += step) {
    ticks.push(Math.round(v * 1e10) / 1e10) // avoid float drift
  }
  return ticks
}

// ─── Variance Color ─────────────────────────────────────────────────────────

/** Return green/red color based on value sign */
export function varianceColor(value: number, isDark = false): string {
  const c = isDark ? IBCS.dark : IBCS
  if (value > 0) return c.positive
  if (value < 0) return c.negative
  return isDark ? IBCS.dark.textMuted : IBCS.textMuted
}

// ─── SVG Pattern Defs ───────────────────────────────────────────────────────

/**
 * SVG `<defs>` block with IBCS scenario fill patterns.
 * Include once per SVG element, then reference via `fill="url(#ibcs-forecast)"`, etc.
 */
export function IBCSPatternDefs({ isDark = false }: { isDark?: boolean }) {
  const color = isDark ? IBCS.dark.actual : IBCS.actual
  const pyColor = isDark ? IBCS.dark.previousYear : IBCS.previousYear
  return (
    <defs>
      {/* Forecast: diagonal hatch */}
      <pattern id="ibcs-forecast" patternUnits="userSpaceOnUse" width="6" height="6" patternTransform="rotate(45)">
        <line x1="0" y1="0" x2="0" y2="6" stroke={color} strokeWidth="1.5" />
      </pattern>
      {/* Previous Year: solid gray */}
      <pattern id="ibcs-py" patternUnits="userSpaceOnUse" width="4" height="4">
        <rect width="4" height="4" fill={pyColor} />
      </pattern>
    </defs>
  )
}

// ─── Data Helpers ───────────────────────────────────────────────────────────

/**
 * Chronological month ordering for time-series sorting.
 * Supports full names, 3-letter abbreviations, and common variants.
 */
const MONTH_ORDER: Record<string, number> = {
  jan: 0, january: 0,
  feb: 1, february: 1,
  mar: 2, march: 2,
  apr: 3, april: 3,
  may: 4,
  jun: 5, june: 5,
  jul: 6, july: 6,
  aug: 7, august: 7,
  sep: 8, sept: 8, september: 8,
  oct: 9, october: 9,
  nov: 10, november: 10,
  dec: 11, december: 11,
}

/** Detect if categories look like month names and return sort indices, or null */
function detectMonthOrder(categories: string[]): number[] | null {
  if (categories.length < 2) return null
  const indices = categories.map(c => MONTH_ORDER[c.trim().toLowerCase()])
  // If >70% match month names, use chronological order
  const matched = indices.filter(i => i !== undefined).length
  if (matched / categories.length < 0.7) return null
  return indices.map(i => i ?? 99)
}

/** Extract category + value arrays from rows/columns (first col = category, rest = values).
 *  Automatically sorts by chronological month order when categories are month names.
 */
export function extractSeriesData(
  columns: string[],
  rows: Array<Record<string, unknown>>,
) {
  const categoryCol = columns[0]
  const valueCols = columns.slice(1)
  const categories = rows.map(r => String(r[categoryCol] ?? ''))
  const series = valueCols.map(col => ({
    name: col,
    values: rows.map(r => {
      const v = r[col]
      return typeof v === 'number' ? v : v == null ? 0 : Number(v) || 0
    }),
  }))

  // ── Auto-sort by month when applicable ──
  const monthIndices = detectMonthOrder(categories)
  if (monthIndices) {
    // Build sort permutation
    const order = categories.map((_, i) => i)
    order.sort((a, b) => (monthIndices[a] ?? 99) - (monthIndices[b] ?? 99))

    // Apply permutation
    const sortedCats = order.map(i => categories[i])
    const sortedSeries = series.map(s => ({
      ...s,
      values: order.map(i => s.values[i]),
    }))
    return { categories: sortedCats, series: sortedSeries, categoryCol, valueCols }
  }

  return { categories, series, categoryCol, valueCols }
}

// ─── Tooltip State ──────────────────────────────────────────────────────────

export interface TooltipData {
  x: number
  y: number
  label: string
  values: Array<{ name: string; value: number; formatted: string }>
}

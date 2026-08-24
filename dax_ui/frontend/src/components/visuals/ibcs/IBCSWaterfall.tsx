/**
 * IBCSWaterfall — IBCS-compliant SVG waterfall / bridge chart.
 *
 * Features:
 * - Start bar → contributor bars → end/total bar
 * - Connector lines between segments (solid thin lines)
 * - Green/red variance coloring based on contribution direction
 * - Subtotal bars (full-height from zero, distinct styling)
 * - Direct data labels on each bar segment
 * - Optional total bar at the end
 * - Scenario fill patterns (AC solid, PL outline, FC hatched)
 * - Tooltip on hover with value, delta, and percentage
 * - Responsive sizing via ResizeObserver
 * - Dark mode support
 * - data-testid attributes on all interactive elements
 */

import { useMemo, useState, useCallback, useRef } from 'react'
import {
  IBCS,
  IBCSPatternDefs,
  formatCompact,
  linearScale,
  niceExtent,
  varianceColor,
  type TooltipData,
} from './IBCSChartUtils'

export interface IBCSWaterfallProps {
  columns: string[]
  rows: Array<Record<string, unknown>>
  /** Explicit AC measure column */
  acColumnName?: string
  /** Explicit measure column to use (preferred over scenario heuristics) */
  valueColumnName?: string
  width?: number
  height?: number
  isDark?: boolean
  /** If true, auto-detect or append total bars */
  showTotals?: boolean
  /** Scenario value source + styling */
  scenario?: 'ac' | 'py' | 'pl' | 'fc'
  /** Show connector lines between contributor bars */
  showConnectors?: boolean
  /** Allow Shift+click to toggle a contributor bar as subtotal (view-only until Save) */
  allowSubtotalToggle?: boolean
  /** Additional category labels treated as subtotals */
  subtotalLabels?: string[]
  /** Global axis label font size */
  fontSize?: number
  /** Data label font size */
  dataLabelFontSize?: number
  /** Chart font family */
  fontFamily?: string
  /** Category axis label rotation (degrees) */
  xAxisRotation?: number
  onBarClick?: (value: unknown, isMultiSelect: boolean) => void
}

const MARGIN = { top: 24, right: 16, bottom: 60, left: 50 }
const BAR_PAD = 0.2
const LABEL_FONT = 10
const AXIS_FONT = 9
const CONNECTOR_WIDTH = 0.75
const DEFAULT_AXIS_FONT = 9
const DEFAULT_LABEL_FONT = 10

/** Default labels recognized as total rows */
const DEFAULT_TOTAL_LABELS = new Set([
  'total', 'net', 'result', 'net income', 'net profit', 'grand total',
])

/** Default labels recognized as subtotal rows */
function isSubtotalLabel(label: string): boolean {
  const l = label.toLowerCase()
  return l.startsWith('subtotal') || l.startsWith('sub-total') || l.includes('subtotal')
}

function classifySeries(name: string): 'ac' | 'py' | 'pl' | 'fc' | 'unknown' {
  const n = name.toUpperCase()
  if (/ PY$/.test(n) || n.includes('PRIOR') || n.includes('PREVIOUS') || / LY$/.test(n)) return 'py'
  if (/ FC$/.test(n) || n.includes('FORECAST')) return 'fc'
  if (/ BUD$/.test(n) || n.includes('BUDGET') || / PL$/.test(n) || n.includes('PLAN')) return 'pl'
  if (/ AC$/.test(n) || n.includes('ACTUAL')) return 'ac'
  return 'unknown'
}

function pickMeasureColumn(columns: string[], scenario: 'ac' | 'py' | 'pl' | 'fc'): string | null {
  if (columns.length < 2) return null
  const measureCols = columns.slice(1)
  const byClass = measureCols.find((c) => classifySeries(c) === scenario)
  if (byClass) return byClass
  return measureCols[0] ?? null
}

export interface WaterfallBar {
  label: string
  value: number       // the delta (contributor bars) or abs value (total/subtotal)
  start: number       // bottom edge of the bar
  end: number         // top edge of the bar
  runningTotal: number // running total after this bar
  isTotal: boolean
  isSubtotal: boolean
}

export function IBCSWaterfall({
  columns,
  rows,
  acColumnName,
  valueColumnName,
  width: containerWidth,
  height: containerHeight,
  isDark = false,
  showTotals = true,
  scenario = 'ac',
  showConnectors = true,
  allowSubtotalToggle = false,
  subtotalLabels,
  fontSize,
  dataLabelFontSize,
  fontFamily,
  xAxisRotation,
  onBarClick,
}: IBCSWaterfallProps) {
  const [tooltip, setTooltip] = useState<TooltipData | null>(null)
  const [manualSubtotals, setManualSubtotals] = useState<Set<string>>(new Set())
  const AXIS_FONT = fontSize || DEFAULT_AXIS_FONT
  const LABEL_FONT = dataLabelFontSize || fontSize || DEFAULT_LABEL_FONT
  const svgFontFamily = fontFamily || 'system-ui, -apple-system, sans-serif'

  // ─── Responsive container sizing ──────────────────────────────────────
  const [observedSize, setObservedSize] = useState({ w: 0, h: 0 })
  const roRef = useRef<ResizeObserver | null>(null)
  const setContainerRef = useCallback((el: HTMLDivElement | null) => {
    if (roRef.current) { roRef.current.disconnect(); roRef.current = null }
    if (el) {
      const ro = new ResizeObserver((entries) => {
        const { width, height } = entries[0].contentRect
        if (width > 0 && height > 0) setObservedSize({ w: Math.round(width), h: Math.round(height) })
      })
      ro.observe(el)
      roRef.current = ro
    }
  }, [])

  // Build subtotal set from prop
  const extraSubtotals = useMemo(
    () => new Set((subtotalLabels ?? []).map(s => s.toLowerCase())),
    [subtotalLabels],
  )

  // ─── Data processing ──────────────────────────────────────────────────

  const bars = useMemo<WaterfallBar[]>(() => {
    if (rows.length === 0 || columns.length < 2) return []

    const catCol = columns[0]
    const resolvedAcCol = (acColumnName && columns.includes(acColumnName))
      ? acColumnName
      : (pickMeasureColumn(columns, 'ac') || columns[1])
    const fallbackComparisonCol = columns.slice(1).find((c) => c !== resolvedAcCol)
    const valCol = (valueColumnName && columns.includes(valueColumnName))
      ? valueColumnName
      : (scenario === 'ac' && fallbackComparisonCol ? fallbackComparisonCol : pickMeasureColumn(columns, scenario))
    if (!valCol) return []

    const hasComparisonBaseline = resolvedAcCol !== valCol

    if (hasComparisonBaseline) {
      const baselineTotal = rows.reduce((acc, row) => acc + Number(row[valCol] ?? 0), 0)
      const acTotal = rows.reduce((acc, row) => acc + Number(row[resolvedAcCol] ?? 0), 0)
      const baselineClass = classifySeries(valCol)
      const baselineLabel = baselineClass === 'unknown' ? 'Baseline' : baselineClass.toUpperCase()

      const items: WaterfallBar[] = []
      let running = baselineTotal

      if (showTotals) {
        items.push({
          label: baselineLabel,
          value: baselineTotal,
          start: 0,
          end: baselineTotal,
          runningTotal: baselineTotal,
          isTotal: true,
          isSubtotal: false,
        })
      }

      for (const row of rows) {
        const label = String(row[catCol] ?? '')
        const acVal = Number(row[resolvedAcCol] ?? 0)
        const baseVal = Number(row[valCol] ?? 0)
        const delta = acVal - baseVal
        const start = running
        running += delta
        items.push({
          label,
          value: delta,
          start,
          end: running,
          runningTotal: running,
          isTotal: false,
          isSubtotal: false,
        })
      }

      if (showTotals) {
        items.push({
          label: 'AC',
          value: acTotal,
          start: 0,
          end: acTotal,
          runningTotal: acTotal,
          isTotal: true,
          isSubtotal: false,
        })
      }

      return items
    }

    const items: WaterfallBar[] = []
    let running = 0

    for (let i = 0; i < rows.length; i++) {
      const label = String(rows[i][catCol] ?? '')
      const value = Number(rows[i][valCol] ?? 0)
      const labelLower = label.toLowerCase()

      // Detect totals / subtotals by name convention (NOT by position)
      const isTotalRow = showTotals && DEFAULT_TOTAL_LABELS.has(labelLower)
      const isSubtotalRow = isSubtotalLabel(label) || extraSubtotals.has(labelLower) || manualSubtotals.has(labelLower)

      if (isTotalRow || isSubtotalRow) {
        if (isSubtotalRow) {
          // Subtotal — full bar from zero at current running total
          items.push({ label, value: running, start: 0, end: running, runningTotal: running, isTotal: false, isSubtotal: true })
        } else if (i === 0) {
          // First row is a starting baseline total
          items.push({ label, value, start: 0, end: value, runningTotal: value, isTotal: true, isSubtotal: false })
          running = value
        } else {
          // Ending or mid-stream total — full bar from zero
          items.push({ label, value, start: 0, end: value, runningTotal: value, isTotal: true, isSubtotal: false })
        }
      } else {
        // Contributor bar
        const start = running
        running += value
        items.push({ label, value, start, end: running, runningTotal: running, isTotal: false, isSubtotal: false })
      }
    }

    // Auto-append total bar if needed
    if (showTotals && items.length > 0 && !items[items.length - 1].isTotal) {
      items.push({ label: 'Total', value: running, start: 0, end: running, runningTotal: running, isTotal: true, isSubtotal: false })
    }

    return items
  }, [columns, rows, acColumnName, valueColumnName, scenario, showTotals, extraSubtotals, manualSubtotals])

  // ─── Derived: grand total for percentage calculations ─────────────────

  const grandTotal = useMemo(() => {
    const lastTotal = bars.findLast(b => b.isTotal)
    return lastTotal ? Math.abs(lastTotal.value) : Math.abs(bars[bars.length - 1]?.runningTotal ?? 1)
  }, [bars])

  // ─── Layout ───────────────────────────────────────────────────────────

  const vw = observedSize.w || containerWidth || 500
  const vh = observedSize.h || containerHeight || 300

  // Compact mode for embedded card contexts
  const isCompact = vw < 360 || vh < 260
  const margin = isCompact
    ? { top: 8, right: 8, bottom: 20, left: 12 }
    : MARGIN
  const plotW = vw - margin.left - margin.right
  const plotH = vh - margin.top - margin.bottom

  // In compact mode, show labels only on totals + biggest contributor
  const compactLabelVisible = useMemo<Set<number> | null>(() => {
    if (!isCompact || bars.length === 0) return null  // null = show all
    const visible = new Set<number>()
    // Always show totals/subtotals
    bars.forEach((b, i) => { if (b.isTotal || b.isSubtotal) visible.add(i) })
    // Find the largest absolute contributor delta and show it
    let maxAbsIdx = -1
    let maxAbs = 0
    bars.forEach((b, i) => {
      if (!b.isTotal && !b.isSubtotal && Math.abs(b.value) > maxAbs) {
        maxAbs = Math.abs(b.value)
        maxAbsIdx = i
      }
    })
    if (maxAbsIdx >= 0) visible.add(maxAbsIdx)
    return visible
  }, [isCompact, bars])

  const allEdges = useMemo(
    () => bars.flatMap(b => [b.start, b.end]),
    [bars],
  )
  const valueExtent = useMemo(() => niceExtent(allEdges, true), [allEdges])

  const yScale = useMemo(
    () => linearScale(valueExtent, [plotH, 0]),
    [valueExtent, plotH],
  )

  const bandWidth = plotW / Math.max(bars.length, 1)
  const barWidth = bandWidth * (1 - BAR_PAD)

  // ─── Colors ─────────────────────────────────────────────────────────────

  const colors = isDark ? IBCS.dark : IBCS
  const totalColor = colors.actual
  const subtotalColor = isDark ? IBCS.dark.previousYear : '#d0d0d0'

  // ─── Scenario fill ────────────────────────────────────────────────────

  const scenarioFill = useCallback((baseFill: string): string => {
    switch (scenario) {
      case 'fc': return 'url(#ibcs-forecast)'
      case 'pl': return 'none' // outline only
      default:   return baseFill
    }
  }, [scenario])

  const scenarioStroke = useCallback((baseFill: string): string | undefined => {
    return scenario === 'pl' ? baseFill : undefined
  }, [scenario])

  const scenarioStrokeWidth = scenario === 'pl' ? 1.5 : undefined

  // ─── Event handlers ─────────────────────────────────────────────────────

  const handleMouseEnter = useCallback(
    (e: React.MouseEvent, bar: WaterfallBar) => {
      const pct = grandTotal !== 0 ? (bar.value / grandTotal) * 100 : 0
      const pctStr = (pct >= 0 ? '+' : '') + pct.toFixed(1) + '%'
      setTooltip({
        x: e.clientX,
        y: e.clientY,
        label: bar.label,
        values: [
          { name: bar.isTotal || bar.isSubtotal ? 'Value' : 'Delta', value: bar.value, formatted: formatCompact(bar.value) },
          { name: 'Running total', value: bar.runningTotal, formatted: formatCompact(bar.runningTotal) },
          ...(!bar.isTotal && !bar.isSubtotal
            ? [{ name: '% of total', value: pct, formatted: pctStr }]
            : []),
        ],
      })
    },
    [grandTotal],
  )

  const handleMouseMove = useCallback((e: React.MouseEvent) => {
    setTooltip(prev => prev ? { ...prev, x: e.clientX, y: e.clientY } : null)
  }, [])

  const handleMouseLeave = useCallback(() => setTooltip(null), [])

  // ─── Render ─────────────────────────────────────────────────────────────

  if (bars.length === 0) {
    return (
      <div ref={setContainerRef} className="relative w-full h-full flex items-center justify-center" data-testid="ibcs-waterfall">
        <span className="text-muted-foreground text-sm">No data</span>
      </div>
    )
  }

  return (
    <div ref={setContainerRef} className="relative w-full h-full overflow-hidden" data-testid="ibcs-waterfall">
      <svg
        viewBox={`0 0 ${vw} ${vh}`}
        width="100%"
        height="100%"
        preserveAspectRatio="xMidYMid meet"
        style={{ fontFamily: svgFontFamily }}
      >
        <IBCSPatternDefs isDark={isDark} />

        <g transform={`translate(${margin.left}, ${margin.top})`}>
          {/* Connector lines between bars */}
          {showConnectors && bars.map((bar, i) => {
            if (i === bars.length - 1) return null
            const nextBar = bars[i + 1]
            // Connect from right edge of current bar to left edge of next bar
            const fromX = i * bandWidth + (bandWidth + barWidth) / 2
            const toX = (i + 1) * bandWidth + (bandWidth - barWidth) / 2
            // Connector at the END level of the current bar
            const y = yScale(bar.end)
            // Keep connector into final totals, but skip connectors into subtotal bars.
            // Subtotals are drawn as full-height checkpoints and should visually reset.
            if (nextBar.isSubtotal) return null
            const isFinalConnector = i === bars.length - 2 && nextBar.isTotal
            return (
              <line
                key={`conn-${i}`}
                data-testid={isFinalConnector ? 'waterfall-connector-final' : `waterfall-connector-${i}`}
                x1={fromX} x2={toX}
                y1={y} y2={y}
                stroke={colors.textMuted}
                strokeWidth={CONNECTOR_WIDTH}
              />
            )
          })}

          {/* Bars */}
          {bars.map((bar, i) => {
            const x = i * bandWidth + (bandWidth - barWidth) / 2
            const top = Math.min(yScale(bar.start), yScale(bar.end))
            const bottom = Math.max(yScale(bar.start), yScale(bar.end))
            const h = Math.max(bottom - top, 1)

            let baseFill: string
            if (bar.isTotal) {
              baseFill = totalColor
            } else if (bar.isSubtotal) {
              baseFill = subtotalColor
            } else {
              baseFill = varianceColor(bar.value, isDark)
            }

            const fill = scenarioFill(baseFill)
            const stroke = scenarioStroke(baseFill)

            // Label position: above if positive, below if negative
            const labelY = bar.value >= 0 || bar.isTotal || bar.isSubtotal
              ? top - 4
              : bottom + LABEL_FONT + 2

            return (
              <g
                key={`bar-${i}`}
                data-testid={`waterfall-bar-${i}`}
                onMouseEnter={(e) => handleMouseEnter(e, bar)}
                onMouseMove={handleMouseMove}
                onMouseLeave={handleMouseLeave}
                onClick={(e) => {
                  if (allowSubtotalToggle && e.shiftKey && !bar.isTotal) {
                    const key = bar.label.toLowerCase()
                    setManualSubtotals((prev) => {
                      const next = new Set(prev)
                      if (next.has(key)) next.delete(key)
                      else next.add(key)
                      return next
                    })
                    return
                  }
                  onBarClick?.(bar.label, e.ctrlKey || e.metaKey)
                }}
                style={{ cursor: (onBarClick || allowSubtotalToggle) ? 'pointer' : 'default' }}
              >
                <rect
                  x={x} y={top}
                  width={barWidth} height={h}
                  fill={fill}
                  stroke={stroke}
                  strokeWidth={scenarioStrokeWidth}
                  rx={1}
                  data-testid={`waterfall-rect-${i}`}
                  data-bar-type={bar.isTotal ? 'total' : bar.isSubtotal ? 'subtotal' : 'contributor'}
                  data-bar-value={bar.value}
                  data-manual-subtotal={manualSubtotals.has(bar.label.toLowerCase()) ? 'true' : 'false'}
                />
                {/* Total/subtotal border marker (thin top border) */}
                {(bar.isTotal || bar.isSubtotal) && (
                  <line
                    x1={x} x2={x + barWidth}
                    y1={top} y2={top}
                    stroke={colors.totalBorder}
                    strokeWidth={1.5}
                  />
                )}
                {/* Data label — hidden in compact mode for non-key bars */}
                {(compactLabelVisible === null || compactLabelVisible.has(i)) && (
                  <text
                    x={x + barWidth / 2}
                    y={labelY}
                    textAnchor="middle"
                    fontSize={isCompact ? Math.max(LABEL_FONT - 1, 7) : LABEL_FONT}
                    fill={colors.textPrimary}
                    fontWeight={bar.isTotal ? 700 : 400}
                    style={{ fontVariantNumeric: 'tabular-nums' }}
                    data-testid={`waterfall-label-${i}`}
                  >
                    {bar.isTotal || bar.isSubtotal
                      ? formatCompact(bar.value)
                      : (bar.value >= 0 ? '+' : '') + formatCompact(bar.value)}
                  </text>
                )}
              </g>
            )
          })}

          {/* Category axis labels */}
          {bars.map((bar, i) => {
            // In compact mode, only show axis labels for totals
            if (isCompact && !bar.isTotal && !bar.isSubtotal) return null
            const x = i * bandWidth + bandWidth / 2
            const maxChars = isCompact ? 6 : 12
            return (
              <text
                key={`cat-${i}`}
                data-testid={`waterfall-category-${i}`}
                x={x}
                y={plotH + (isCompact ? 6 : 14)}
                textAnchor="middle"
                fontSize={isCompact ? Math.max(AXIS_FONT - 1, 7) : AXIS_FONT}
                fill={bar.isTotal ? colors.textPrimary : colors.textSecondary}
                fontWeight={bar.isTotal ? 600 : 400}
                transform={!isCompact && xAxisRotation != null ? `rotate(${xAxisRotation}, ${x}, ${plotH + 14})` : (!isCompact && bars.length > 8 ? `rotate(-30, ${x}, ${plotH + 14})` : undefined)}
              >
                {bar.label.length > maxChars ? bar.label.slice(0, maxChars - 1) + '…' : bar.label}
              </text>
            )
          })}

        </g>
      </svg>

      {/* Tooltip */}
      {tooltip && (
        <div
          className="fixed pointer-events-none z-50 bg-popover border border-border rounded px-2 py-1 shadow-md text-xs"
          data-testid="waterfall-tooltip"
          style={{
            left: tooltip.x, top: tooltip.y,
            transform: 'translate(-50%, -100%) translateY(-8px)',
          }}
        >
          <div className="font-medium">{tooltip.label}</div>
          {tooltip.values.map(v => (
            <div key={v.name} className="flex justify-between gap-3">
              <span className="text-muted-foreground">{v.name}</span>
              <span style={{ fontVariantNumeric: 'tabular-nums' }}>{v.formatted}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

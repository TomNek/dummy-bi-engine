/**
 * IBCSBarChart — IBCS-compliant SVG bar/column chart with Zebra BI-style
 * integrated variance panels.
 *
 * Vertical column layout (3 stacked panels, top to bottom):
 *   ┌─────────────────────────────────┐
 *   │  ΔPL% lollipop — pin chart     │  relative deviation
 *   │  with green/red pins on a       │
 *   │  horizontal baseline            │
 *   ├─────────────────────────────────┤
 *   │  ΔPL absolute deviation bars   │  green/red small bars
 *   ├─────────────────────────────────┤
 *   │  Main bar chart                 │  AC solid + PY pin + PL dashed
 *   │  with direct data labels        │
 *   └─────────────────────────────────┘
 *
 * Horizontal bar mode uses a simpler single-panel with inline variance column.
 */

import { useMemo, useState, useCallback, useRef } from 'react'
import {
  IBCS,
  IBCSPatternDefs,
  formatCompact,
  formatVariance,
  linearScale,
  niceExtent,
  extractSeriesData,
  type TooltipData,
} from './IBCSChartUtils'

export interface IBCSBarChartProps {
  columns: string[]
  rows: Array<Record<string, unknown>>
  width?: number
  height?: number
  orientation?: 'horizontal' | 'vertical'
  isDark?: boolean
  labelPosition?: 'top-inside' | 'top-outside' | 'middle' | 'bottom'
  fontSize?: number
  dataLabelFontSize?: number
  fontFamily?: string
  xAxisRotation?: number
  canvasPaddingH?: number
  canvasPaddingV?: number
  showVariancePanels?: boolean
  mainChartMode?: 'comparison' | 'waterfall'
  onMainChartModeChange?: (mode: 'comparison' | 'waterfall') => void
  onBarClick?: (value: unknown, isMultiSelect: boolean) => void
}

type HWaterfallRow = {
  label: string
  kind: 'context' | 'start' | 'variance' | 'total'
  start: number
  end: number
  delta?: number
  value: number
  categoryIndex?: number
}

// ─── Constants ──────────────────────────────────────────────────────────────

const DEFAULT_LABEL_FONT = 16
const DEFAULT_AXIS_FONT = 16
const DEFAULT_DEV_FONT = 14
const BAR_PAD = 0.25
const MIN_LABEL_WIDTH = 30
const APPROX_CHAR_WIDTH = 7  // rough px per char at default font
// Panel height ratios for 3-panel vertical mode
const PANEL_REL_PCT = 0.18     // ΔPL% lollipop height
const PANEL_ABS_PCT = 0.14     // ΔPL bar height
const PANEL_GAP = 4            // gap between panels in px
const WATERFALL_VARIANCE_THICKNESS = 0.7
const VERTICAL_WATERFALL_VARIANCE_THICKNESS = 0.9
const V_WATERFALL_COMPARE_PANEL_FRAC = 0.22

/** Classify a measure name into AC/PY/PL by suffix conventions */
function classifySeries(name: string): 'ac' | 'py' | 'pl' | 'unknown' {
  const n = name.toUpperCase()
  if (/ PY$/.test(n) || n.includes('PRIOR') || n.includes('PREVIOUS') || / LY$/.test(n)) return 'py'
  if (/ BUD$/.test(n) || n.includes('BUDGET') || / PL$/.test(n) || n.includes('PLAN') || / FC$/.test(n) || n.includes('FORECAST')) return 'pl'
  if (/ AC$/.test(n) || n.includes('ACTUAL')) return 'ac'
  return 'unknown'
}

export function IBCSBarChart({
  columns,
  rows,
  width: containerWidth,
  height: containerHeight,
  orientation = 'horizontal',
  isDark = false,
  labelPosition = 'top-inside',
  fontSize,
  dataLabelFontSize,
  fontFamily,
  xAxisRotation,
  canvasPaddingH,
  canvasPaddingV,
  showVariancePanels,
  mainChartMode = 'comparison',
  onMainChartModeChange,
  onBarClick,
}: IBCSBarChartProps) {
  // Derive font sizes from format option
  const LABEL_FONT = dataLabelFontSize || fontSize || DEFAULT_LABEL_FONT
  const AXIS_FONT = fontSize || DEFAULT_AXIS_FONT
  const DEV_FONT = Math.max((fontSize || DEFAULT_DEV_FONT) - 2, 7)
  const svgFontFamily = fontFamily || 'system-ui, -apple-system, sans-serif'

  const [tooltip, setTooltip] = useState<TooltipData | null>(null)
  const isHorizontal = orientation === 'horizontal'

  // ─── Container measurement ──────────────────────────────────────────────
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

  // ─── Extract & classify series ──────────────────────────────────────────

  const { categories, series } = useMemo(
    () => extractSeriesData(columns, rows),
    [columns, rows],
  )

  const seriesMap = useMemo(() => {
    const map: { ac: typeof series[0] | null; py: typeof series[0] | null; pl: typeof series[0] | null } = { ac: null, py: null, pl: null }
    for (const s of series) {
      const cls = classifySeries(s.name)
      if (cls === 'ac' && !map.ac) map.ac = s
      else if (cls === 'py' && !map.py) map.py = s
      else if (cls === 'pl' && !map.pl) map.pl = s
    }
    if (!map.ac && series.length > 0) map.ac = series[0]
    if (!map.py && !map.pl) {
      for (const s of series) {
        if (s === map.ac) continue
        if (!map.py) { map.py = s; continue }
        if (!map.pl) { map.pl = s; continue }
      }
    }
    return map
  }, [series])

  const acSeries = seriesMap.ac || series[0]
  // primary comparison: prefer PL, fall back to PY
  const cmpSeries = seriesMap.pl || seriesMap.py
  const waterfallBaseSeries = seriesMap.py || cmpSeries
  const plSeries = seriesMap.pl
  const hasVariance = !!cmpSeries
  const useWaterfallMain = mainChartMode === 'waterfall'

  const waterfallBaseTotal = useMemo(
    () => (waterfallBaseSeries ? waterfallBaseSeries.values.reduce((sum, v) => sum + v, 0) : 0),
    [waterfallBaseSeries],
  )

  const waterfallDeltas = useMemo(() => {
    if (waterfallBaseSeries) {
      return acSeries.values.map((v, i) => v - waterfallBaseSeries.values[i])
    }
    return acSeries.values.slice()
  }, [acSeries, waterfallBaseSeries])

  const waterfallSegments = useMemo(() => {
    let running = waterfallBaseTotal
    return waterfallDeltas.map((delta) => {
      const start = running
      running += delta
      return { start, end: running, delta }
    })
  }, [waterfallBaseTotal, waterfallDeltas])

  const cmpLabel = useMemo(() => {
    if (!cmpSeries) return ''
    const cls = classifySeries(cmpSeries.name)
    return cls === 'py' ? 'PY' : cls === 'pl' ? 'PL' : 'CMP'
  }, [cmpSeries])

  const waterfallCmpLabel = useMemo(() => {
    if (!waterfallBaseSeries) return cmpLabel
    const cls = classifySeries(waterfallBaseSeries.name)
    return cls === 'py' ? 'PY' : cls === 'pl' ? 'PL' : cmpLabel
  }, [waterfallBaseSeries, cmpLabel])

  const waterfallRows = useMemo(() => {
    if (!useWaterfallMain) return [] as HWaterfallRow[]

    const rowsOut: HWaterfallRow[] = []
    const plTotal = seriesMap.pl ? seriesMap.pl.values.reduce((sum, v) => sum + v, 0) : null
    const pyTotal = seriesMap.py ? seriesMap.py.values.reduce((sum, v) => sum + v, 0) : null
    const acTotal = acSeries.values.reduce((sum, v) => sum + v, 0)
    const startLabel = waterfallCmpLabel || 'Base'
    const showPlanContext = plTotal !== null && startLabel !== 'PL'

    if (showPlanContext) {
      rowsOut.push({ label: 'PL', kind: 'context', start: 0, end: plTotal, value: plTotal })
    }

    let running = waterfallBaseTotal
    rowsOut.push({ label: startLabel, kind: 'start', start: 0, end: running, value: running })

    for (let i = 0; i < categories.length; i++) {
      const delta = waterfallDeltas[i] ?? 0
      const start = running
      running += delta
      rowsOut.push({
        label: categories[i],
        kind: 'variance',
        start,
        end: running,
        delta,
        value: delta,
        categoryIndex: i,
      })
    }

    rowsOut.push({ label: 'AC', kind: 'total', start: 0, end: acTotal, value: acTotal })

    const startRowIndex = rowsOut.findIndex((row) => row.kind === 'start')
    if (pyTotal !== null && startRowIndex >= 0 && rowsOut[startRowIndex].label === 'PY') {
      rowsOut[startRowIndex] = { ...rowsOut[startRowIndex], value: pyTotal, end: pyTotal }
    }

    return rowsOut
  }, [useWaterfallMain, seriesMap.pl, seriesMap.py, acSeries.values, categories, waterfallBaseTotal, waterfallCmpLabel, waterfallDeltas])

  // ─── Colors ─────────────────────────────────────────────────────────────

  const barColor = isDark ? IBCS.dark.actual : IBCS.actual
  const pyColor = isDark ? IBCS.dark.previousYear : IBCS.previousYear
  const txtColor = isDark ? IBCS.dark.textPrimary : IBCS.textPrimary
  const gridColor = isDark ? IBCS.dark.gridLine : IBCS.gridLine
  const mutedColor = isDark ? IBCS.dark.textMuted : IBCS.textMuted
  const posColor = isDark ? IBCS.dark.positive : IBCS.positive
  const negColor = isDark ? IBCS.dark.negative : IBCS.negative

  // ─── Layout ─────────────────────────────────────────────────────────────

  const vw = observedSize.w || containerWidth || 500
  const vh = observedSize.h || containerHeight || 300
  const dataLabelScale = Math.min(1, Math.max(0.62, Math.min(vw / 760, vh / 420)))
  const DATA_LABEL_FONT = Math.max(8, Math.round(LABEL_FONT * dataLabelScale))

  // ─── Event handlers ─────────────────────────────────────────────────────

  const handleBarClick = useCallback(
    (cat: string, e: React.MouseEvent) => {
      if (onBarClick) onBarClick(cat, e.ctrlKey || e.metaKey)
    },
    [onBarClick],
  )
  const handleMouseEnter = useCallback(
    (x: number, y: number, cat: string, vals: Array<{ name: string; value: number }>) => {
      setTooltip({
        x, y, label: cat,
        values: vals.map(v => ({ ...v, formatted: formatCompact(v.value) })),
      })
    },
    [],
  )
  const handleMouseLeave = useCallback(() => setTooltip(null), [])

  // ═══════════════════════════════════════════════════════════════════════
  //  VERTICAL COLUMN MODE — 3-panel Zebra BI layout
  // ═══════════════════════════════════════════════════════════════════════

  if (!isHorizontal) {
    // Responsive margins — shrink for small charts
    const isCompact = vh < 200 || vw < 300
    // In compact mode, show data labels only for max/min bars
    const vLabelVisibleSet = (() => {
      if (!isCompact) return null // null = show all
      const vals = acSeries.values
      if (vals.length === 0) return new Set<number>()
      let minIdx = 0, maxIdx = 0
      for (let i = 1; i < vals.length; i++) {
        if (vals[i] > vals[maxIdx]) maxIdx = i
        if (vals[i] < vals[minIdx]) minIdx = i
      }
      return new Set([minIdx, maxIdx])
    })()
    // In compact waterfall mode, show labels only on totals + biggest delta
    const wfLabelVisibleSet = (() => {
      if (!isCompact || !useWaterfallMain) return null  // null = show all
      const visible = new Set<number>()
      let maxAbsIdx = -1
      let maxAbs = 0
      waterfallRows.forEach((row, i) => {
        if (row.kind === 'start' || row.kind === 'total' || row.kind === 'context') {
          visible.add(i)
        } else if (row.kind === 'variance' && Math.abs(row.delta ?? 0) > maxAbs) {
          maxAbs = Math.abs(row.delta ?? 0)
          maxAbsIdx = i
        }
      })
      if (maxAbsIdx >= 0) visible.add(maxAbsIdx)
      return visible
    })()
    const padH = canvasPaddingH ?? (isCompact ? 6 : 10)
    const padV = canvasPaddingV ?? (isCompact ? 6 : 10)
    // Left margin must fit panel labels (ΔPL%, ΔPL, AC) — need ~48px minimum
    const mLeft = isCompact ? 8 : Math.max(48, padH)
    const waterfallBaselineRightReserve = (useWaterfallMain && hasVariance && !isCompact && vw >= 760 && vh >= 260)
      ? Math.max(132, DEV_FONT * 8)
      : 0
    const mRight = (isCompact ? 6 : Math.max(16, padH)) + waterfallBaselineRightReserve
    // Compute effective rotation so we know bottom-margin need
    const effectiveRotation = xAxisRotation !== undefined ? xAxisRotation : (categories.length > 6 ? -30 : 0)
    // Bottom space for category labels — kept compact so chart fills the visual
    const catLabelH = isCompact ? 14 : 20
    // Fixed top margin — extra space so Δ% labels aren't clipped
    const mTop = Math.max(padV + 10, isCompact ? 6 : 28)
    // Bottom margin: just enough for labels, not proportional to rotation
    const mBottom = isCompact ? 24 : Math.max(catLabelH + 6, padV + catLabelH)
    const totalH = vh - mTop - mBottom
    const plotW = vw - mLeft - mRight

    // Responsive: hide pct% panel first (needs more height), then abs panel
    // Format option can force-hide all variance panels
    const varianceEnabled = showVariancePanels !== false
    const showPctPanel = varianceEnabled && hasVariance && vh >= 400
    const showAbsPanel = varianceEnabled && hasVariance && vh >= 300 && !useWaterfallMain

    // Panel heights
    const pctPanelH = showPctPanel ? Math.max(totalH * PANEL_REL_PCT, 36) : 0
    const absPanelH = showAbsPanel ? Math.max(totalH * PANEL_ABS_PCT, 28) : 0
    const showBottomComparePanel = false
    const bottomComparePanelH = showBottomComparePanel ? Math.max(totalH * V_WATERFALL_COMPARE_PANEL_FRAC, 42) : 0
    const visiblePanels = (showPctPanel ? 1 : 0) + (showAbsPanel ? 1 : 0) + (showBottomComparePanel ? 1 : 0)
    const gapTotal = visiblePanels > 0 ? visiblePanels * PANEL_GAP : 0
    const mainPanelH = Math.max(totalH - pctPanelH - absPanelH - bottomComparePanelH - gapTotal, 40)

    // Y offsets (stack visible panels from top; main panel starts after last visible panel + gap)
    let yCursor = 0
    const pctPanelY = showPctPanel ? yCursor : 0
    if (showPctPanel) yCursor += pctPanelH + PANEL_GAP
    const absPanelY = showAbsPanel ? yCursor : 0
    if (showAbsPanel) yCursor += absPanelH + PANEL_GAP
    const mainPanelY = yCursor
    yCursor += mainPanelH
    const bottomComparePanelY = showBottomComparePanel ? yCursor + PANEL_GAP : 0

    const vRowLabels = useWaterfallMain ? waterfallRows.map((row) => row.label) : categories

    // Band (category axis) — shared across all 3 panels
    const bandWidth = plotW / Math.max(vRowLabels.length, 1)
    const bw = bandWidth * (1 - BAR_PAD)

    // ─── Compute deltas ───────────────────────────────────────────────────
    const deltas = cmpSeries
      ? acSeries.values.map((v, i) => v - cmpSeries.values[i])
      : [] as number[]

    const deltaPcts = cmpSeries
      ? acSeries.values.map((v, i) => {
        const base = cmpSeries.values[i]
        return base !== 0 ? (v - base) / Math.abs(base) : 0
      })
      : [] as number[]

    const vVarianceRows = useWaterfallMain
      ? waterfallRows.map((row) => {
          if (row.kind !== 'variance' || row.categoryIndex == null) return null
          const catIndex = row.categoryIndex
          const delta = waterfallDeltas[catIndex] ?? row.delta ?? 0
          const baseVal = waterfallBaseSeries ? waterfallBaseSeries.values[catIndex] : 0
          const pct = baseVal !== 0 ? delta / Math.abs(baseVal) : 0
          const acVal = acSeries.values[catIndex] ?? 0
          return { catIndex, delta, pct, acVal, baseVal }
        })
      : categories.map((_, i) => {
          const delta = deltas[i] ?? 0
          const baseVal = cmpSeries ? cmpSeries.values[i] : 0
          const pct = deltaPcts[i] ?? 0
          const acVal = acSeries.values[i] ?? 0
          return { catIndex: i, delta, pct, acVal, baseVal }
        })

    // ─── Main panel scale ─────────────────────────────────────────────────
    const mainLabelTopPad = hasVariance ? DEV_FONT + 6 : DEV_FONT + 4
    const mainLabelBottomPad = 4
    const mainDrawTop = Math.min(mainLabelTopPad, Math.max(mainPanelH - 8, 0))
    const mainDrawBottom = Math.max(mainDrawTop + 1, mainPanelH - mainLabelBottomPad)
    const mainExtent = (() => {
      if (useWaterfallMain) {
        const vals = [0]
        for (const row of waterfallRows) {
          vals.push(row.start, row.end)
        }
        return niceExtent(vals, true)
      }
      const vals = acSeries.values.slice()
      if (seriesMap.py) vals.push(...seriesMap.py.values)
      if (plSeries) vals.push(...plSeries.values)
      // Only positive deviations extend above the bar (negative goes into)
      if (cmpSeries) {
        for (let i = 0; i < acSeries.values.length; i++) {
          const delta = acSeries.values[i] - cmpSeries.values[i]
          if (delta > 0) vals.push(acSeries.values[i] + delta)
        }
      }
      return niceExtent(vals, true)
    })()
    const mainScale = linearScale(mainExtent, [mainDrawBottom, mainDrawTop])
    const mainZeroY = mainScale(0)

    // ─── ΔAbs panel scale ─────────────────────────────────────────────────
    const absLabelTopPad = DEV_FONT + 2
    const absLabelBottomPad = DEV_FONT + 2
    const absDrawTop = Math.min(absLabelTopPad, Math.max(absPanelH - 8, 0))
    const absDrawBottom = Math.max(absDrawTop + 1, absPanelH - absLabelBottomPad)
    const absVals = vVarianceRows.filter((x): x is { catIndex: number; delta: number; pct: number; acVal: number; baseVal: number } => x !== null).map((x) => x.delta)
    const absExtent = niceExtent(absVals, true)
    const absScale = linearScale(absExtent, [absDrawBottom, absDrawTop])
    const absZeroY = absVals.length > 0 ? absScale(0) : (absDrawTop + absDrawBottom) / 2

    // ─── Δ% panel scale (lollipop) ────────────────────────────────────────
    const pctLabelTopPad = DEV_FONT + 4
    const pctLabelBottomPad = DEV_FONT + 4
    const pctDrawTop = Math.min(pctLabelTopPad, Math.max(pctPanelH - 8, 0))
    const pctDrawBottom = Math.max(pctDrawTop + 1, pctPanelH - pctLabelBottomPad)
    const pctVals = vVarianceRows.filter((x): x is { catIndex: number; delta: number; pct: number; acVal: number; baseVal: number } => x !== null).map((x) => x.pct * 100)
    const pctExtent = niceExtent(pctVals, true)
    const pctScale = linearScale(pctExtent, [pctDrawBottom, pctDrawTop])
    const pctZeroY = pctVals.length > 0 ? pctScale(0) : (pctDrawTop + pctDrawBottom) / 2

    const bottomCompareVals = vVarianceRows.filter((x): x is { catIndex: number; delta: number; pct: number; acVal: number; baseVal: number } => x !== null)
      .flatMap((x) => [x.acVal, x.baseVal])
    const bottomExtent = niceExtent(bottomCompareVals.length > 0 ? bottomCompareVals : [0], true)
    const bottomTopPad = DEV_FONT + 2
    const bottomBottomPad = DEV_FONT + 2
    const bottomDrawTop = Math.min(bottomTopPad, Math.max(bottomComparePanelH - 8, 0))
    const bottomDrawBottom = Math.max(bottomDrawTop + 1, bottomComparePanelH - bottomBottomPad)
    const bottomScale = linearScale(bottomExtent, [bottomDrawBottom, bottomDrawTop])
    const bottomZeroY = bottomScale(0)

    const acRowIndex = useWaterfallMain ? waterfallRows.findIndex((row) => row.kind === 'total' && row.label === 'AC') : -1
    const acRow = useWaterfallMain && acRowIndex >= 0 ? waterfallRows[acRowIndex] : null
    const baselineLinkRows = useWaterfallMain
      ? waterfallRows
        .map((row, idx) => ({ row, idx }))
        .filter(({ row }) => row.kind === 'context' || row.kind === 'start')
      : []
    const hideWaterfallBaselineAnnotations = waterfallBaselineRightReserve === 0 || mainPanelH < 110 || plotW < 280
    const hidePyBaselineConnector = isCompact || mainPanelH < 130 || plotW < 360
    const showEmbeddedCompare = useWaterfallMain && hasVariance

    return (
      <div ref={setContainerRef} className="relative w-full h-full overflow-hidden" data-testid="ibcs-bar-chart">
        <svg
          viewBox={`0 0 ${vw} ${vh}`}
          width="100%" height="100%"
          preserveAspectRatio="xMidYMid meet"
          style={{ fontFamily: svgFontFamily }}
        >
          <IBCSPatternDefs isDark={isDark} />

          <g transform={`translate(${mLeft}, ${mTop})`}>

            {/* ═══════ PANEL 1: Δ% lollipop (top) ═══════ */}
            {showPctPanel && (
              <g transform={`translate(0, ${pctPanelY})`}>
                {/* Panel label */}
                <text
                  x={-6} y={pctPanelH / 2}
                  dy="0.35em" fontSize={DEV_FONT} fill={mutedColor}
                  textAnchor="end" fontWeight={600}
                >
                  Δ{useWaterfallMain ? waterfallCmpLabel : cmpLabel}%
                </text>

                {/* Baseline — prominent dark line */}
                <line x1={0} x2={plotW} y1={pctZeroY} y2={pctZeroY}
                  stroke={barColor} strokeWidth={1.5} />

                {/* Lollipop pins: black heads, colored stems, muted labels */}
                {vVarianceRows.map((entry, i) => {
                  if (!entry) return null
                  const dp = entry.pct
                  const cx = i * bandWidth + bandWidth / 2
                  const pctVal = dp * 100
                  const pinY = pctScale(pctVal)
                  const stemColor = dp >= 0 ? posColor : negColor
                  const above = dp >= 0
                  const labelY = above ? pinY - 8 : pinY + DEV_FONT + 4

                  return (
                    <g key={`pct-${i}`}>
                      {/* Stem — green/red, thin */}
                      <line
                        x1={cx} y1={pctZeroY} x2={cx} y2={pinY}
                        stroke={stemColor} strokeWidth={1.5}
                      />
                      {/* Pin head — black filled triangle */}
                      <polygon
                        points={above
                          ? `${cx},${pinY} ${cx - 4},${pinY + 6} ${cx + 4},${pinY + 6}`
                          : `${cx},${pinY} ${cx - 4},${pinY - 6} ${cx + 4},${pinY - 6}`}
                        fill={stemColor}
                      />
                      {/* Label — muted */}
                      <text
                        x={cx} y={labelY}
                        fontSize={DEV_FONT} fill={mutedColor}
                        textAnchor="middle"
                        style={{ fontVariantNumeric: 'tabular-nums' }}
                      >
                        {dp >= 0 ? '+' : ''}{pctVal.toFixed(1)}%
                      </text>
                    </g>
                  )
                })}
              </g>
            )}

            {/* ═══════ PANEL 2: ΔAbs bars (middle) — only when tall enough ═══════ */}
            {showAbsPanel && (
              <g transform={`translate(0, ${absPanelY})`}>
                {/* Panel label */}
                <text
                  x={-6} y={absPanelH / 2}
                  dy="0.35em" fontSize={DEV_FONT} fill={mutedColor}
                  textAnchor="end" fontWeight={600}
                >
                  Δ{useWaterfallMain ? waterfallCmpLabel : cmpLabel}
                </text>

                {/* Baseline — dark line */}
                <line x1={0} x2={plotW} y1={absZeroY} y2={absZeroY}
                  stroke={barColor} strokeWidth={1.5} />

                {/* Deviation bars */}
                {vVarianceRows.map((entry, i) => {
                  if (!entry) return null
                  const d = entry.delta
                  const cx = i * bandWidth + (bandWidth - bw) / 2
                  const color = d >= 0 ? posColor : negColor
                  const devBarH = Math.abs(absScale(d) - absZeroY)
                  const barY = d >= 0 ? absScale(d) : absZeroY
                  const labelY = d >= 0 ? barY - 3 : barY + devBarH + DEV_FONT + 1
                  const safeLabelY = Math.min(Math.max(labelY, DEV_FONT), absPanelH - 2)
                  const panelDevW = useWaterfallMain ? bw * WATERFALL_VARIANCE_THICKNESS : bw
                  const panelDevX = cx + (bw - panelDevW) / 2

                  return (
                    <g key={`abs-${i}`}>
                      <rect
                        x={panelDevX} y={barY}
                        width={panelDevW} height={Math.max(devBarH, 1)}
                        fill={color} rx={1}
                      />
                      <text
                        x={panelDevX + panelDevW / 2} y={safeLabelY}
                        fontSize={DEV_FONT} fill={mutedColor}
                        textAnchor="middle"
                        style={{ fontVariantNumeric: 'tabular-nums' }}
                      >
                        {formatVariance(d)}
                      </text>
                    </g>
                  )
                })}
              </g>
            )}

            {/* ═══════ PANEL 3: Main bar chart with integrated deviation ═══════ */}
            <g transform={`translate(0, ${mainPanelY})`}>
              {/* Panel labels on left (stacked: ΔPL / AC) — only when panels visible */}
              {showPctPanel && (
                <>
                  <text
                    x={-6} y={mainPanelH * 0.25}
                    dy="0.35em" fontSize={DEV_FONT} fill={mutedColor}
                    textAnchor="end" fontWeight={600}
                  >
                    Δ{cmpLabel}
                  </text>
                  <text
                    x={-6} y={mainPanelH * 0.55}
                    dy="0.35em" fontSize={DEV_FONT} fill={mutedColor}
                    textAnchor="end" fontWeight={600}
                  >
                    AC
                  </text>
                </>
              )}

              {/* Zero line */}
              <line x1={0} x2={plotW} y1={mainZeroY} y2={mainZeroY}
                stroke={barColor} strokeWidth={1} />

              {/* Main mode marker for UI tests */}
              <g data-testid={useWaterfallMain ? 'ibcs-main-waterfall-mode' : 'ibcs-main-comparison-mode'} />

              {/* Waterfall connectors (vertical mode) */}
              {useWaterfallMain && waterfallRows.map((row, i) => {
                if (i >= waterfallRows.length - 1) return null
                const next = waterfallRows[i + 1]
                const rowHasRunning = row.kind === 'start' || row.kind === 'variance'
                const nextHasRunning = next.kind === 'variance' || next.kind === 'total'
                if (!rowHasRunning || !nextHasRunning) return null
                const cx = i * bandWidth + bandWidth / 2
                const nextCx = (i + 1) * bandWidth + bandWidth / 2
                const rowW = row.kind === 'variance' ? bw * VERTICAL_WATERFALL_VARIANCE_THICKNESS : bw
                const nextW = next.kind === 'variance' ? bw * VERTICAL_WATERFALL_VARIANCE_THICKNESS : bw
                const y = mainScale(row.end)
                return (
                  <line
                    key={`wf-v-conn-${i}-${row.label}`}
                    x1={cx + rowW / 2}
                    x2={nextCx - nextW / 2}
                    y1={y}
                    y2={y}
                    stroke={mutedColor}
                    strokeWidth={1}
                    strokeDasharray="2 2"
                  />
                )
              })}

              {useWaterfallMain && acRow && acRowIndex >= 0 && baselineLinkRows.map(({ row, idx }, linkOrder) => {
                if (hideWaterfallBaselineAnnotations) return null
                const x = idx * bandWidth + bandWidth / 2
                const acX = acRowIndex * bandWidth + bandWidth / 2
                const rowY = mainScale(row.end)
                const acY = mainScale(acRow.end)
                const diff = acRow.value - row.value
                const diffLabel = formatVariance(diff)
                const isPyBaseline = row.kind === 'start' || row.label.toUpperCase() === 'PY'
                if (isPyBaseline && hidePyBaselineConnector) return null
                const baselineRightEdge = plotW + waterfallBaselineRightReserve - 12
                const markerX = Math.min(Math.max(acX + 52 + (linkOrder * 6), 2), baselineRightEdge)
                const markerColor = diff >= 0 ? posColor : negColor
                const linkX1 = Math.min(x, markerX)
                const linkX2 = Math.max(x, markerX)
                const labelX = Math.min(Math.max(markerX + 7, 2), baselineRightEdge)
                const labelY = Math.min(Math.max(((rowY + acY) / 2) + 4, DEV_FONT), mainPanelH - 2)
                const ringW = Math.max((diffLabel.length * 7) + 10, 22)
                const ringCx = Math.min(Math.max(labelX + ringW / 2, 2), baselineRightEdge)
                return (
                  <g key={`wf-v-link-${row.label}-${idx}`} data-testid="ibcs-waterfall-baseline-link">
                    <line x1={linkX1} y1={rowY} x2={linkX2} y2={rowY} stroke={mutedColor} strokeWidth={1} />
                    <line
                      x1={markerX}
                      y1={rowY}
                      x2={markerX}
                      y2={acY}
                      stroke={markerColor}
                      strokeWidth={2}
                      data-testid="ibcs-waterfall-baseline-terminal"
                    />
                    <line
                      x1={markerX}
                      y1={acY}
                      x2={acX}
                      y2={acY}
                      stroke={mutedColor}
                      strokeWidth={1}
                      data-testid="ibcs-waterfall-baseline-return"
                    />
                    {isPyBaseline && (
                      <ellipse
                        cx={ringCx}
                        cy={labelY - 2}
                        rx={ringW / 2}
                        ry={Math.max(DEV_FONT * 0.7, 8)}
                        fill="none"
                        stroke="#1f6feb"
                        strokeWidth={1.5}
                        data-testid="ibcs-waterfall-baseline-label-ring"
                      />
                    )}
                    <text
                      x={labelX}
                      y={labelY}
                      fontSize={Math.max(DEV_FONT - 2, 8)}
                      fill={txtColor}
                      textAnchor="start"
                      style={{ fontVariantNumeric: 'tabular-nums' }}
                    >
                      {diffLabel}
                    </text>
                  </g>
                )
              })}

              {/* Column bars: PY grey bar behind, AC dark, integrated ΔPL on top */}
              {(useWaterfallMain
                ? waterfallRows
                : categories.map((cat, i) => ({ label: cat, kind: 'variance' as const, categoryIndex: i, start: 0, end: 0, delta: 0, value: acSeries.values[i] ?? 0 }))
              ).map((row, i) => {
                const cat = row.label
                const catIndex = row.categoryIndex ?? i
                const value = acSeries.values[catIndex] ?? 0
                const varianceEntry = vVarianceRows[i]
                const x = i * bandWidth + (bandWidth - bw) / 2
                const wfStart = row.start ?? 0
                const wfEnd = row.end ?? 0
                const wfDelta = row.delta ?? 0
                const wfStartY = mainScale(wfStart)
                const wfEndY = mainScale(wfEnd)
                const waterfallRawY = Math.min(wfStartY, wfEndY)
                const waterfallRawH = Math.abs(wfEndY - wfStartY)
                const waterfallMinH = useWaterfallMain && row.kind === 'variance' ? 4 : 0
                const waterfallH = Math.max(waterfallRawH, waterfallMinH)
                const waterfallY = (() => {
                  if (!(useWaterfallMain && row.kind === 'variance') || waterfallRawH >= waterfallMinH) {
                    return waterfallRawY
                  }
                  if (wfEndY <= wfStartY) {
                    return wfEndY
                  }
                  return wfEndY - waterfallMinH
                })()
                const waterfallW = useWaterfallMain && row.kind === 'variance' ? bw * VERTICAL_WATERFALL_VARIANCE_THICKNESS : bw
                const waterfallX = x + (bw - waterfallW) / 2
                const waterfallColor = row.kind === 'context'
                  ? (isDark ? '#111111' : '#ffffff')
                  : row.kind === 'start'
                    ? pyColor
                    : row.kind === 'total'
                      ? barColor
                      : (wfDelta >= 0 ? posColor : negColor)

                const colH = useWaterfallMain ? waterfallH : Math.abs(mainScale(value) - mainZeroY)
                const y = useWaterfallMain
                  ? waterfallY
                  : (value >= 0 ? mainScale(value) : mainZeroY)

                const embeddedCompareBars = (showEmbeddedCompare && useWaterfallMain && row.kind === 'variance' && varianceEntry)
                  ? (() => {
                      const baseVal = varianceEntry.baseVal
                      const acVal = varianceEntry.acVal
                      const baseH = Math.abs(mainScale(baseVal) - mainZeroY)
                      const baseY = baseVal >= 0 ? mainScale(baseVal) : mainZeroY
                      const acH = Math.abs(mainScale(acVal) - mainZeroY)
                      const acY = acVal >= 0 ? mainScale(acVal) : mainZeroY
                      const acW = bw * 0.54
                      const baseW = acW + 3
                      const acX = x + (bw - acW) / 2
                      const baseX = acX - 3
                      const labelY = Math.min(Math.max(acY - 4, DEV_FONT), mainPanelH - 2)
                      return (
                        <g data-testid="ibcs-waterfall-embedded-compare">
                          <rect
                            x={baseX}
                            y={baseY}
                            width={baseW}
                            height={Math.max(baseH, 1)}
                            fill={pyColor}
                            stroke="#9F9F9F"
                            strokeWidth={1}
                            rx={1}
                          />
                          <rect
                            x={acX}
                            y={acY}
                            width={acW}
                            height={Math.max(acH, 1)}
                            fill={barColor}
                            rx={1}
                          />
                          <text
                            x={acX + acW / 2}
                            y={labelY}
                            fontSize={Math.max(DATA_LABEL_FONT - 1, 8)}
                            fill={txtColor}
                            textAnchor="middle"
                            data-testid="ibcs-waterfall-embedded-compare-label"
                            style={{ fontVariantNumeric: 'tabular-nums' }}
                          >
                            {formatCompact(acVal)}
                          </text>
                        </g>
                      )
                    })()
                  : null
                const delta = useWaterfallMain ? wfDelta : (cmpSeries ? value - cmpSeries.values[catIndex] : 0)
                const hasDev = !useWaterfallMain && hasVariance && Math.abs(delta) > 0.001 && value >= 0
                const isWaterfallVariance = useWaterfallMain && row.kind === 'variance'
                // Label position driven by format option
                const labelInsideDefault = hasDev && colH > 14
                const effectiveLabelPos = isWaterfallVariance
                  ? 'top-outside'
                  : labelPosition === 'top-outside'
                  ? 'top-outside'
                  : labelPosition === 'middle'
                    ? 'middle'
                    : labelPosition === 'bottom'
                      ? 'bottom'
                      : (labelInsideDefault ? 'top-inside' : 'top-outside')
                const labelY = isWaterfallVariance
                  ? (wfDelta >= 0 ? y - 4 : y + colH + DATA_LABEL_FONT + 2)
                  : effectiveLabelPos === 'top-inside'
                  ? y + 12
                  : effectiveLabelPos === 'top-outside'
                    ? (value >= 0 ? y - 4 : y + colH + DATA_LABEL_FONT + 2)
                    : effectiveLabelPos === 'middle'
                      ? y + colH / 2 + DATA_LABEL_FONT / 2 - 1
                      : y + colH - 4 // bottom
                const safeLabelY = Math.min(Math.max(labelY, 2), mainPanelH - 2)
                const labelFill = isWaterfallVariance
                  ? txtColor
                  : (useWaterfallMain && (row.kind === 'context' || row.kind === 'start'))
                  ? txtColor
                  : (effectiveLabelPos === 'top-outside' ? txtColor : '#fff')

                // PY grey bar behind AC (shifted left, only visible on left edge)
                const pyBar = (!useWaterfallMain && seriesMap.py) ? (() => {
                  const pyVal = seriesMap.py!.values[catIndex]
                  const pyH = Math.abs(mainScale(pyVal) - mainZeroY)
                  const pyY = pyVal >= 0 ? mainScale(pyVal) : mainZeroY
                  return (
                    <rect
                      x={x - 5} y={pyY}
                      width={bw + 2} height={pyH}
                      fill={pyColor}
                      stroke="#9F9F9F" strokeWidth={1}
                      rx={1}
                    />
                  )
                })() : null

                // Integrated deviation: right-aligned, neg goes into bar
                const devBarW = bw * 0.7
                const devBarX = x + bw - devBarW
                const devEl = hasDev ? (() => {
                  const devColor = delta >= 0 ? posColor : negColor
                  if (delta >= 0) {
                    // Positive (AC > BUD): green goes INTO bar from top
                    const devH = Math.min(Math.max(mainScale(value - delta) - y, 1), colH)
                    const safeDevLabelY = Math.min(Math.max(y - 3, 2), mainPanelH - 2)
                    return (
                      <g>
                        <rect
                          x={devBarX} y={y}
                          width={devBarW} height={devH}
                          fill={devColor} rx={1}
                        />
                        {!isCompact && (
                          <text
                            x={x + bw / 2} y={safeDevLabelY}
                            fontSize={DEV_FONT} fill={devColor}
                            textAnchor="middle"
                            style={{ fontVariantNumeric: 'tabular-nums' }}
                          >
                            {formatVariance(delta)}
                          </text>
                        )}
                      </g>
                    )
                  } else {
                    // Negative (AC < BUD): red extends ABOVE bar
                    const devTop = mainScale(value - delta)
                    const devH = Math.max(y - devTop, 1)
                    const devLabelY = devTop - 3
                    const safeDevLabelY = Math.min(Math.max(devLabelY, 2), mainPanelH - 2)
                    return (
                      <g>
                        <rect
                          x={devBarX} y={devTop}
                          width={devBarW} height={devH}
                          fill={devColor} rx={1}
                        />
                        {!isCompact && (
                          <text
                            x={x + bw / 2} y={safeDevLabelY}
                            fontSize={DEV_FONT} fill={devColor}
                            textAnchor="middle"
                            style={{ fontVariantNumeric: 'tabular-nums' }}
                          >
                            {formatVariance(delta)}
                          </text>
                        )}
                      </g>
                    )
                  }
                })() : null

                return (
                  <g
                    key={cat}
                    onClick={(e) => handleBarClick(cat, e)}
                    onMouseEnter={(e) => {
                      const svgRect = (e.target as SVGElement).closest('svg')?.getBoundingClientRect()
                      handleMouseEnter(
                        (svgRect?.left ?? 0) + mLeft + x + bw / 2,
                        (svgRect?.top ?? 0) + mTop + mainPanelY + y,
                        cat,
                        [
                          ...(useWaterfallMain
                            ? [
                                { name: cat, value: row.value },
                                ...(row.kind === 'variance' ? [{ name: `Δ${waterfallCmpLabel}`, value: wfDelta }] : []),
                              ]
                            : [
                                { name: acSeries.name, value },
                                ...(cmpSeries ? [{ name: cmpSeries.name, value: cmpSeries.values[catIndex] }] : []),
                                ...(seriesMap.py && seriesMap.py !== cmpSeries ? [{ name: seriesMap.py.name, value: seriesMap.py.values[catIndex] }] : []),
                              ]),
                        ],
                      )
                    }}
                    onMouseLeave={handleMouseLeave}
                    style={{ cursor: onBarClick ? 'pointer' : 'default' }}
                  >
                    {embeddedCompareBars}
                    {pyBar}
                    <rect
                      x={useWaterfallMain ? waterfallX : x} y={y}
                      width={useWaterfallMain ? waterfallW : bw} height={colH}
                      fill={useWaterfallMain ? waterfallColor : barColor}
                      rx={isWaterfallVariance ? 0 : 1}
                      stroke={useWaterfallMain && row.kind === 'context' ? txtColor : undefined}
                      strokeWidth={useWaterfallMain && row.kind === 'context' ? 1.25 : undefined}
                    />
                    {devEl}
                    {/* AC value label — in compact mode, show only for key bars */}
                    {(useWaterfallMain
                      ? (wfLabelVisibleSet === null || wfLabelVisibleSet.has(i))
                      : (vLabelVisibleSet === null || vLabelVisibleSet.has(catIndex))
                    ) && (
                      <text
                        x={(useWaterfallMain ? waterfallX + waterfallW / 2 : x + bw / 2)} y={safeLabelY}
                        fontSize={DATA_LABEL_FONT} fill={labelFill} textAnchor="middle"
                        data-testid={useWaterfallMain ? `ibcs-waterfall-row-value-${i}` : undefined}
                        style={{ fontVariantNumeric: 'tabular-nums' }}
                      >
                        {useWaterfallMain
                          ? (row.kind === 'variance' ? formatVariance(wfDelta) : formatCompact(row.value))
                          : formatCompact(value)}
                      </text>
                    )}
                  </g>
                )
              })}

            </g>

            {/* ═══════ PANEL 4: Bottom category comparison bars (waterfall mode) ═══════ */}
            {showBottomComparePanel && (
              <g transform={`translate(0, ${bottomComparePanelY})`} data-testid="ibcs-waterfall-bottom-compare">
                <line x1={0} x2={plotW} y1={bottomZeroY} y2={bottomZeroY} stroke={barColor} strokeWidth={1} />
                {vVarianceRows.map((entry, i) => {
                  if (!entry) return null
                  const cx = i * bandWidth + (bandWidth - bw) / 2
                  const baseVal = entry.baseVal
                  const acVal = entry.acVal
                  const acH = Math.abs(bottomScale(acVal) - bottomZeroY)
                  const acY = acVal >= 0 ? bottomScale(acVal) : bottomZeroY
                  const pyY = bottomScale(baseVal)
                  const acW = bw * 0.72
                  const acX = cx + (bw - acW) / 2
                  const valueY = Math.max(8, acY - 4)
                  return (
                    <g key={`v-bottom-${i}`}>
                      <rect
                        x={acX}
                        y={acY}
                        width={acW}
                        height={Math.max(acH, 1)}
                        fill={barColor}
                        rx={1}
                      />
                      <line
                        x1={acX - 2}
                        x2={acX + acW + 2}
                        y1={pyY}
                        y2={pyY}
                        stroke={pyColor}
                        strokeWidth={2}
                      />
                      <text
                        x={acX + acW / 2}
                        y={valueY}
                        fontSize={Math.max(9, DEV_FONT - 1)}
                        fill={txtColor}
                        textAnchor="middle"
                        style={{ fontVariantNumeric: 'tabular-nums' }}
                      >
                        {formatCompact(acVal)}
                      </text>
                    </g>
                  )
                })}
              </g>
            )}

            {/* Category labels */}
            {vRowLabels.map((cat, i) => {
              // In compact waterfall mode, only show labels for totals/start rows
              if (useWaterfallMain && isCompact && waterfallRows[i]) {
                const rowKind = waterfallRows[i].kind
                if (rowKind !== 'start' && rowKind !== 'total' && rowKind !== 'context') return null
              }
              const cx = i * bandWidth + bandWidth / 2
              const catFontSize = isCompact ? 7 : Math.min(AXIS_FONT, 12)
              const catYBase = showBottomComparePanel
                ? bottomComparePanelY + bottomComparePanelH + (isCompact ? 8 : 12)
                : mainPanelY + mainPanelH + (isCompact ? 8 : 12)
              const rotation = (!isCompact && xAxisRotation !== undefined) ? xAxisRotation : (!isCompact && categories.length > 6 ? -30 : 0)
              const anchor = rotation !== 0 ? 'end' : 'middle'
              const availDiag = rotation !== 0 ? mBottom / Math.max(Math.sin(Math.abs(rotation) * Math.PI / 180), 0.3) : bandWidth
              const maxChars = isCompact ? 5 : Math.max(6, Math.min(Math.round(availDiag / (catFontSize * 0.6)), 30))
              const displayText = cat.length > maxChars ? cat.slice(0, maxChars - 1) + '…' : cat
              return (
                <text
                  key={`${cat}-${i}`} x={cx} y={catYBase}
                  fontSize={catFontSize} fill={txtColor}
                  textAnchor={anchor}
                  dominantBaseline="hanging"
                  data-testid={useWaterfallMain ? `ibcs-waterfall-row-label-${i}` : undefined}
                  transform={rotation !== 0 ? `rotate(${rotation}, ${cx}, ${catYBase})` : undefined}
                >
                  {displayText}
                </text>
              )
            })}
          </g>
        </svg>

        {tooltip && (
          <div
            className="fixed pointer-events-none z-50 bg-popover border border-border rounded px-2 py-1 shadow-md text-xs"
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

  // ═══════════════════════════════════════════════════════════════════════
  //  HORIZONTAL BAR MODE — 3-panel layout matching column chart
  //  Layout (left to right): category labels | main bars | Δ% lollipop | ΔAbs bars
  // ═══════════════════════════════════════════════════════════════════════

  const padH = canvasPaddingH ?? 10
  const padV = canvasPaddingV ?? 10
  // Adaptive category label width — based on longest label, clamped
  const maxCatLen = categories.reduce((mx, c) => Math.max(mx, c.length), 0)
  const catLabelW = Math.min(Math.max(maxCatLen * APPROX_CHAR_WIDTH + 12, 50), 160)
  const m = { top: padV + 4, right: padH + 8, bottom: padV + 4, left: padH + catLabelW }

  // Responsive: show deviation panels on right side if wide enough
  // Format option can force-hide all variance panels
  const varianceEnabledH = showVariancePanels !== false
  let showPctPanel = varianceEnabledH && hasVariance && vw >= 600
  let showAbsPanel = varianceEnabledH && hasVariance && vw >= 500 && !useWaterfallMain

  // Panel widths for deviation columns on the right
  const PANEL_PCT_W_FRAC = 0.16  // fraction of available width for Δ%
  const PANEL_ABS_W_FRAC = 0.14  // fraction for ΔAbs
  const panelGap = 6

  const availW = vw - m.left - m.right
  const calcMainW = (showAbs: boolean, showPct: boolean) => {
    const absW = showAbs ? Math.max(availW * PANEL_ABS_W_FRAC, 50) : 0
    const pctW = showPct ? Math.max(availW * PANEL_PCT_W_FRAC, 60) : 0
    const gapCount = (showAbs ? 1 : 0) + (showPct ? 1 : 0)
    const gaps = gapCount * panelGap
    return availW - absW - pctW - gaps
  }

  const minMainPanelW = (useWaterfallMain && hasVariance) ? 270 : 120
  if (calcMainW(showAbsPanel, showPctPanel) < minMainPanelW && showPctPanel) showPctPanel = false
  if (calcMainW(showAbsPanel, showPctPanel) < minMainPanelW && showAbsPanel) showAbsPanel = false

  const pctPanelW = showPctPanel ? Math.max(availW * PANEL_PCT_W_FRAC, 60) : 0
  const absPanelW = showAbsPanel ? Math.max(availW * PANEL_ABS_W_FRAC, 50) : 0
  const gapsW = ((showAbsPanel ? 1 : 0) + (showPctPanel ? 1 : 0)) * panelGap
  const mainPanelW = Math.max(availW - pctPanelW - absPanelW - gapsW, 80)

  const plotH = vh - m.top - m.bottom

  const hRowLabels = useWaterfallMain ? waterfallRows.map((r) => r.label) : categories
  const hBaselineBottomReserve = useWaterfallMain && hasVariance ? Math.max(32, DEV_FONT + 14) : 0
  const bandPlotH = Math.max(plotH - hBaselineBottomReserve, 40)
  const bandWidth = bandPlotH / Math.max(hRowLabels.length, 1)
  const bw = bandWidth * (1 - BAR_PAD)
  const hDevFont = categories.length > 10 ? Math.max(9, DEV_FONT - 3) : DEV_FONT
  // In compact/embedded mode, only show data labels for max and min bars
  const isCompactH = vw < 500 || vh < 350
  const showInlineDeviationLabels = !useWaterfallMain && !isCompactH

  // Determine which bar indices should show data labels (all when full-size, min/max when compact)
  const hLabelVisibleSet = (() => {
    if (!isCompactH) return null // null = show all
    const vals = acSeries.values
    if (vals.length === 0) return new Set<number>()
    let minIdx = 0, maxIdx = 0
    for (let i = 1; i < vals.length; i++) {
      if (vals[i] > vals[maxIdx]) maxIdx = i
      if (vals[i] < vals[minIdx]) minIdx = i
    }
    return new Set([minIdx, maxIdx])
  })()

  // Panel X offsets (left to right: main bars, gap, ΔAbs, gap, Δ%)
  const mainPanelX = 0
  const absPanelX = mainPanelX + mainPanelW + panelGap
  const pctPanelX = absPanelX + (showAbsPanel ? absPanelW + panelGap : 0)

  // ─── Compute deltas ───────────────────────────────────────────────────
  const hDeltas = cmpSeries
    ? acSeries.values.map((v, i) => v - cmpSeries.values[i])
    : [] as number[]

  const hDeltaPcts = cmpSeries
    ? acSeries.values.map((v, i) => {
      const base = cmpSeries.values[i]
      return base !== 0 ? (v - base) / Math.abs(base) : 0
    })
    : [] as number[]

  const hVarianceRows = useWaterfallMain
    ? waterfallRows.map((row) => {
        if (row.kind !== 'variance' || row.categoryIndex == null) return null
        const catIndex = row.categoryIndex
        const delta = row.delta ?? waterfallDeltas[catIndex] ?? 0
        const baseVal = waterfallBaseSeries ? waterfallBaseSeries.values[catIndex] : 0
        const pct = baseVal !== 0 ? delta / Math.abs(baseVal) : 0
        const acVal = acSeries.values[catIndex] ?? 0
        return { catIndex, delta, pct, baseVal, acVal }
      })
    : categories.map((_, i) => ({
        catIndex: i,
        delta: hDeltas[i] ?? 0,
        pct: hDeltaPcts[i] ?? 0,
        baseVal: cmpSeries ? cmpSeries.values[i] : 0,
        acVal: acSeries.values[i] ?? 0,
      }))

  // ─── Main panel scale ─────────────────────────────────────────────────
  const allValues = (() => {
    if (useWaterfallMain) {
      const vals = [0]
      for (const row of waterfallRows) {
        vals.push(row.start, row.end)
      }
      return vals
    }
    const vals = acSeries.values.slice()
    if (seriesMap.py) vals.push(...seriesMap.py.values)
    if (cmpSeries) vals.push(...cmpSeries.values)
    return vals
  })()

  const valueExtent = niceExtent(allValues, true)
  const mainDrawLeftPad = 2
  const mainDrawRightPad = hasVariance ? DEV_FONT + 8 : DEV_FONT + 6
  const mainDrawLeft = Math.min(mainDrawLeftPad, Math.max(mainPanelW - 8, 0))
  const mainDrawRight = Math.max(mainDrawLeft + 1, mainPanelW - mainDrawRightPad)
  const showEmbeddedCompare = useWaterfallMain && hasVariance
  const valueScale = linearScale(valueExtent, [mainDrawLeft, mainDrawRight])
  const zeroPos = valueScale(0)

  // ─── ΔAbs panel scale ─────────────────────────────────────────────────
  const absDrawLeftPad = DEV_FONT + 5
  const absDrawRightPad = DEV_FONT + 5
  const absDrawLeft = Math.min(absDrawLeftPad, Math.max(absPanelW - 8, 0))
  const absDrawRight = Math.max(absDrawLeft + 1, absPanelW - absDrawRightPad)
  const absVals = hVarianceRows.filter((x): x is { catIndex: number; delta: number; pct: number; baseVal: number; acVal: number } => x !== null).map((x) => x.delta)
  const absExtent = niceExtent(absVals, true)
  const absScale = linearScale(absExtent, [absDrawLeft, absDrawRight])
  const absZeroX = absVals.length > 0 ? absScale(0) : (absDrawLeft + absDrawRight) / 2

  // ─── Δ% panel scale (lollipop, horizontal) ────────────────────────────
  const pctDrawLeftPad = DEV_FONT + 8
  const pctDrawRightPad = DEV_FONT + 8
  const pctDrawLeft = Math.min(pctDrawLeftPad, Math.max(pctPanelW - 8, 0))
  const pctDrawRight = Math.max(pctDrawLeft + 1, pctPanelW - pctDrawRightPad)
  const pctVals = hVarianceRows.filter((x): x is { catIndex: number; delta: number; pct: number; baseVal: number; acVal: number } => x !== null).map((x) => x.pct * 100)
  const pctExtent = niceExtent(pctVals, true)
  const pctScale = linearScale(pctExtent, [pctDrawLeft, pctDrawRight])
  const pctZeroX = pctVals.length > 0 ? pctScale(0) : (pctDrawLeft + pctDrawRight) / 2

  const acRowIndex = useWaterfallMain ? waterfallRows.findIndex((row) => row.kind === 'total' && row.label === 'AC') : -1
  const acRow = useWaterfallMain && acRowIndex >= 0 ? waterfallRows[acRowIndex] : null
  const baselineLinkRows = useWaterfallMain
    ? waterfallRows
      .map((row, idx) => ({ row, idx }))
      .filter(({ row }) => row.kind === 'context' || row.kind === 'start')
    : []

  return (
    <div ref={setContainerRef} className="relative w-full h-full overflow-hidden" data-testid="ibcs-bar-chart">
      <svg
        viewBox={`0 0 ${vw} ${vh}`}
        width="100%" height="100%"
        preserveAspectRatio="xMidYMid meet"
        style={{ fontFamily: svgFontFamily }}
      >
        <IBCSPatternDefs isDark={isDark} />

        <g transform={`translate(${m.left}, ${m.top})`}>

          {/* ═══════ PANEL: Main horizontal bars ═══════ */}
          <g transform={`translate(${mainPanelX}, 0)`}>
            {/* Panel label */}
            {showPctPanel && (
              <text
                x={mainPanelW / 2} y={-6}
                dy="0.35em" fontSize={DEV_FONT} fill={mutedColor}
                textAnchor="middle" fontWeight={600}
              >
                AC
              </text>
            )}

            {/* Zero line */}
            <line x1={zeroPos} x2={zeroPos} y1={0} y2={plotH} stroke={barColor} strokeWidth={1} />

            {/* Main mode marker for UI tests */}
            <g data-testid={useWaterfallMain ? 'ibcs-main-waterfall-mode' : 'ibcs-main-comparison-mode'} />

            {/* Waterfall connectors (horizontal mode) */}
            {useWaterfallMain && waterfallRows.map((row, i) => {
              if (i >= waterfallRows.length - 1) return null
              const next = waterfallRows[i + 1]
              const rowHasRunning = row.kind === 'start' || row.kind === 'variance'
              const nextHasRunning = next.kind === 'variance' || next.kind === 'total'
              if (!rowHasRunning || !nextHasRunning) return null
              const cy = i * bandWidth + bandWidth / 2
              const nextCy = (i + 1) * bandWidth + bandWidth / 2
              const rowH = row.kind === 'variance' ? bw * WATERFALL_VARIANCE_THICKNESS : bw
              const nextH = next.kind === 'variance' ? bw * WATERFALL_VARIANCE_THICKNESS : bw
              const x = valueScale(row.end)
              return (
                <line
                  key={`wf-h-conn-${i}-${row.label}`}
                  x1={x}
                  x2={x}
                  y1={cy + rowH / 2}
                  y2={nextCy - nextH / 2}
                  stroke={mutedColor}
                  strokeWidth={1}
                  strokeDasharray="2 2"
                />
              )
            })}

            {/* Context/start baseline links to AC total */}
            {useWaterfallMain && acRow && acRowIndex >= 0 && baselineLinkRows.map(({ row, idx }, linkOrder) => {
              const y = idx * bandWidth + bandWidth / 2
              const acY = acRowIndex * bandWidth + bandWidth / 2
              const rowX = valueScale(row.end)
              const diff = acRow.value - row.value
              const diffLabel = formatVariance(diff)
              const isPyBaseline = row.kind === 'start' || row.label.toUpperCase() === 'PY'
              const acX = valueScale(acRow.end)
              const deviationY = Math.min(plotH - 10, acY + 24 + (linkOrder * 12))
              const deviationColor = diff >= 0 ? posColor : negColor
              const devX1 = Math.min(rowX, acX)
              const devX2 = Math.max(rowX, acX)
              const rightLabelX = devX2 + 7
              const rightLabelMax = mainPanelW - 4
              const labelWouldOverflow = rightLabelX + ((diffLabel.length * 6) + 6) > rightLabelMax
              const labelX = labelWouldOverflow
                ? Math.min(Math.max(devX2 - 7, 2), rightLabelMax)
                : Math.min(Math.max(rightLabelX, 2), rightLabelMax)
              const labelAnchor = labelWouldOverflow ? 'end' : 'start'
              const labelY = Math.min(Math.max(deviationY + 4, DEV_FONT), plotH - 2)
              const ringW = Math.max((diffLabel.length * 7) + 10, 22)
              const ringCxRaw = labelAnchor === 'end' ? labelX - ringW / 2 : labelX + ringW / 2
              const ringCx = Math.min(Math.max(ringCxRaw, 2), mainPanelW - 2)
              return (
                <g key={`wf-link-${row.label}-${idx}`} data-testid="ibcs-waterfall-baseline-link">
                  <line x1={rowX} y1={y} x2={rowX} y2={deviationY} stroke={mutedColor} strokeWidth={1} />
                  <line
                    x1={devX1}
                    y1={deviationY}
                    x2={devX2}
                    y2={deviationY}
                    stroke={deviationColor}
                    strokeWidth={2}
                    data-testid="ibcs-waterfall-baseline-terminal"
                  />
                  <line
                    x1={acX}
                    y1={deviationY}
                    x2={acX}
                    y2={acY}
                    stroke={mutedColor}
                    strokeWidth={1}
                    data-testid="ibcs-waterfall-baseline-return"
                  />
                  {isPyBaseline && (
                    <ellipse
                      cx={ringCx}
                      cy={labelY - 2}
                      rx={ringW / 2}
                      ry={Math.max(DEV_FONT * 0.7, 8)}
                      fill="none"
                      stroke="#1f6feb"
                      strokeWidth={1.5}
                      data-testid="ibcs-waterfall-baseline-label-ring"
                    />
                  )}
                  <text
                    x={labelX}
                    y={labelY}
                    fontSize={Math.max(DEV_FONT - 1, 9)}
                    fill={txtColor}
                    textAnchor={labelAnchor}
                    style={{ fontVariantNumeric: 'tabular-nums' }}
                  >
                    {diffLabel}
                  </text>
                </g>
              )
            })}

            {/* Horizontal bars */}
            {(useWaterfallMain
              ? waterfallRows
              : categories.map((cat, i) => ({
                  label: cat,
                  kind: 'variance' as const,
                  categoryIndex: i,
                  start: 0,
                  end: 0,
                  delta: 0,
                  value: acSeries.values[i] ?? 0,
                }))
            ).map((row, i) => {
              const cat = row.label
              const catIndex = row.categoryIndex ?? i
              const value = acSeries.values[catIndex] ?? 0
              const bandStart = i * bandWidth + (bandWidth - bw) / 2
              const wfStart = row.start ?? 0
              const wfEnd = row.end ?? 0
              const wfDelta = row.delta ?? 0
              const varianceEntry = hVarianceRows[i]
              const waterfallX = Math.min(valueScale(wfStart), valueScale(wfEnd))
              const waterfallW = Math.abs(valueScale(wfEnd) - valueScale(wfStart))
              const waterfallH = useWaterfallMain && row.kind === 'variance' ? bw * WATERFALL_VARIANCE_THICKNESS : bw
              const waterfallColor = row.kind === 'context'
                ? (isDark ? '#111111' : '#ffffff')
                : row.kind === 'start'
                  ? pyColor
                  : row.kind === 'total'
                    ? barColor
                    : (wfDelta >= 0 ? posColor : negColor)

              const barX = useWaterfallMain
                ? waterfallX
                : ((acSeries.values[catIndex] >= 0) ? zeroPos : valueScale(acSeries.values[catIndex]))
              const barW = useWaterfallMain
                ? waterfallW
                : Math.abs(valueScale(acSeries.values[catIndex]) - zeroPos)
              const y = useWaterfallMain ? (bandStart + (bw - waterfallH) / 2) : bandStart

              const embeddedCompareBars = (showEmbeddedCompare && useWaterfallMain && row.kind === 'variance' && varianceEntry)
                ? (() => {
                    const baseVal = varianceEntry.baseVal
                    const acVal = varianceEntry.acVal
                    const baseX = baseVal >= 0 ? zeroPos : valueScale(baseVal)
                    const baseW = Math.abs(valueScale(baseVal) - zeroPos)
                    const acX = acVal >= 0 ? zeroPos : valueScale(acVal)
                    const acW = Math.abs(valueScale(acVal) - zeroPos)
                    const acH = bw * 0.62
                    const baseH = acH + 3
                    const acY = bandStart + (bw - acH) / 2
                    const baseY = acY - 3
                    const compareEndX = Math.max(baseX + Math.max(baseW, 1), acX + Math.max(acW, 1))
                    const compareLabelX = Math.min(Math.max(compareEndX + 4, 2), mainPanelW - 2)
                    return (
                      <g data-testid="ibcs-waterfall-embedded-compare">
                        <rect
                          x={baseX}
                          y={baseY}
                          width={Math.max(baseW, 1)}
                          height={baseH}
                          fill={pyColor}
                          stroke="#9F9F9F"
                          strokeWidth={1}
                          rx={1}
                        />
                        <rect
                          x={acX}
                          y={acY}
                          width={Math.max(acW, 1)}
                          height={acH}
                          fill={barColor}
                          rx={1}
                        />
                        <text
                          x={compareLabelX}
                          y={bandStart + bw / 2}
                          dy="0.35em"
                          fontSize={Math.max(DATA_LABEL_FONT - 1, 8)}
                          fill={txtColor}
                          textAnchor="start"
                          data-testid="ibcs-waterfall-embedded-compare-label"
                          style={{ fontVariantNumeric: 'tabular-nums' }}
                        >
                          {formatCompact(acVal)}
                        </text>
                      </g>
                    )
                  })()
                : null

              // Label position driven by format option
              const effectiveLabelPos = labelPosition || 'top-inside'
              const labelInside = effectiveLabelPos === 'top-inside' || effectiveLabelPos === 'middle' || effectiveLabelPos === 'bottom'
                ? barW > MIN_LABEL_WIDTH
                : false
              const labelX = effectiveLabelPos === 'top-outside'
                ? barX + barW + 4
                : effectiveLabelPos === 'middle'
                  ? barX + barW / 2
                  : effectiveLabelPos === 'bottom'
                    ? barX + 4
                    : (labelInside ? barX + barW - 4 : barX + barW + 4)
              const labelAnchor = effectiveLabelPos === 'top-outside'
                ? 'start'
                : effectiveLabelPos === 'middle'
                  ? 'middle'
                  : effectiveLabelPos === 'bottom'
                    ? 'start'
                    : (labelInside ? 'end' : 'start')
              const labelColor = (effectiveLabelPos === 'top-outside' || !labelInside)
                ? txtColor
                : (useWaterfallMain && (row.kind === 'context' || row.kind === 'start') ? txtColor : (isDark ? '#111' : '#fff'))
              const safeLabelX = Math.min(Math.max(labelX, 2), mainPanelW - 2)

              // PY grey bar behind AC (shifted up)
              const pyBar = (!useWaterfallMain && seriesMap.py) ? (() => {
                const pyVal = seriesMap.py!.values[catIndex]
                const pyX = pyVal >= 0 ? zeroPos : valueScale(pyVal)
                const pyW = Math.abs(valueScale(pyVal) - zeroPos)
                return (
                  <rect
                    x={pyX} y={y - 5}
                    width={pyW} height={bw + 2}
                    fill={pyColor}
                    stroke="#9F9F9F" strokeWidth={1}
                    rx={1}
                  />
                )
              })() : null

              // Integrated deviation sub-bar on AC bar
              const delta = useWaterfallMain ? wfDelta : (cmpSeries ? acSeries.values[catIndex] - cmpSeries.values[catIndex] : 0)
              const hasDev = !useWaterfallMain && hasVariance && Math.abs(delta) > 0.001 && acSeries.values[catIndex] >= 0
              const devBarH = bw * 0.7
              const devBarY = y + bw - devBarH  // bottom-aligned
              const devEl = hasDev ? (() => {
                const devColor = delta >= 0 ? posColor : negColor
                const barEndX = barX + barW
                if (delta >= 0) {
                  // Positive (AC > BUD): green goes INTO bar from right end
                  const devExtentX = valueScale(value - delta)
                  const devW = Math.min(Math.max(barEndX - devExtentX, 1), barW)
                  // Label always to the right of the bar end
                  const posRightLabelX = barEndX + 3
                  const posRightLabelMax = mainPanelW - 4
                  return (
                    <g>
                      <rect
                        x={barEndX - devW} y={devBarY}
                        width={devW} height={devBarH}
                        fill={devColor} rx={1}
                      />
                      {showInlineDeviationLabels && (
                        <text
                          x={Math.min(Math.max(posRightLabelX, 2), posRightLabelMax)} y={y + bw / 2}
                          dy="0.35em" fontSize={hDevFont} fill={devColor}
                          textAnchor="start"
                          style={{ fontVariantNumeric: 'tabular-nums' }}
                        >
                          {formatVariance(delta)}
                        </text>
                      )}
                    </g>
                  )
                } else {
                  // Negative (AC < BUD): red extends to the RIGHT beyond bar end
                  const devEndX = valueScale(value - delta)
                  const devW = Math.max(devEndX - barEndX, 1)
                  const devRenderW = Math.min(devW, mainPanelW - barEndX)
                  const rightLabelMax = mainPanelW - 4
                  const rightLabelX = barEndX + devRenderW + 3
                  const labelWouldOverflow = rightLabelX + ((formatVariance(delta).length * 6) + 6) > rightLabelMax
                  const devLabelX = labelWouldOverflow
                    ? Math.min(Math.max(barEndX - 3, 2), rightLabelMax)
                    : Math.min(Math.max(rightLabelX, 2), rightLabelMax)
                  const devLabelAnchor = labelWouldOverflow ? 'end' : 'start'
                  return (
                    <g>
                      <rect
                        x={barEndX} y={devBarY}
                        width={devRenderW} height={devBarH}
                        fill={devColor} rx={1}
                      />
                      {showInlineDeviationLabels && (
                        <text
                          x={devLabelX} y={devBarY + devBarH / 2}
                          dy="0.35em" fontSize={hDevFont} fill={devColor}
                          textAnchor={devLabelAnchor}
                          style={{ fontVariantNumeric: 'tabular-nums' }}
                        >
                          {formatVariance(delta)}
                        </text>
                      )}
                    </g>
                  )
                }
              })() : null

              return (
                <g
                  key={cat}
                  onClick={(e) => handleBarClick(cat, e)}
                  onMouseEnter={(e) => {
                    const svgRect = (e.target as SVGElement).closest('svg')?.getBoundingClientRect()
                    handleMouseEnter(
                      (svgRect?.left ?? 0) + m.left + barX + barW,
                      (svgRect?.top ?? 0) + m.top + y + (useWaterfallMain ? waterfallH / 2 : bw / 2),
                      cat,
                      [
                        ...(useWaterfallMain
                          ? [
                              { name: cat, value: row.value },
                              ...(row.kind === 'variance' ? [{ name: `Δ${waterfallCmpLabel}`, value: wfDelta }] : []),
                            ]
                          : [
                              { name: acSeries.name, value: acSeries.values[catIndex] },
                              ...(cmpSeries ? [{ name: cmpSeries.name, value: cmpSeries.values[catIndex] }] : []),
                              ...(seriesMap.py && seriesMap.py !== cmpSeries ? [{ name: seriesMap.py.name, value: seriesMap.py.values[catIndex] }] : []),
                            ]),
                      ],
                    )
                  }}
                  onMouseLeave={handleMouseLeave}
                  style={{ cursor: onBarClick ? 'pointer' : 'default' }}
                >
                  {embeddedCompareBars}
                  {pyBar}
                  <rect
                    x={barX}
                    y={y}
                    width={barW}
                    height={useWaterfallMain ? waterfallH : bw}
                    fill={useWaterfallMain ? waterfallColor : barColor}
                    stroke={useWaterfallMain && row.kind === 'context' ? txtColor : undefined}
                    strokeWidth={useWaterfallMain && row.kind === 'context' ? 1.25 : undefined}
                    rx={1}
                  />
                  {devEl}
                  {/* Data label: in compact mode, show only for min/max bars */}
                  {(hLabelVisibleSet === null || hLabelVisibleSet.has(catIndex) || useWaterfallMain) && (
                    <text x={safeLabelX} y={y + (useWaterfallMain ? waterfallH / 2 : bw / 2)} dy="0.35em" fontSize={DATA_LABEL_FONT}
                      fill={labelColor} textAnchor={labelAnchor}
                      data-testid={useWaterfallMain ? `ibcs-waterfall-row-value-${i}` : undefined}
                      style={{ fontVariantNumeric: 'tabular-nums' }}>
                      {useWaterfallMain
                        ? (row.kind === 'variance' ? formatVariance(wfDelta) : formatCompact(row.value))
                        : formatCompact(acSeries.values[catIndex])}
                    </text>
                  )}
                </g>
              )
            })}
          </g>

          {/* ═══════ PANEL: ΔAbs bars (right of main) ═══════ */}
          {showAbsPanel && (
            <g transform={`translate(${absPanelX}, 0)`} data-testid={useWaterfallMain ? 'ibcs-waterfall-abs-panel' : undefined}>
              {/* Panel label */}
              <text
                x={absPanelW / 2} y={-6}
                dy="0.35em" fontSize={DEV_FONT} fill={mutedColor}
                textAnchor="middle" fontWeight={600}
              >
                Δ{useWaterfallMain ? waterfallCmpLabel : cmpLabel}
              </text>

              {/* Baseline */}
              <line x1={absZeroX} x2={absZeroX} y1={0} y2={plotH}
                stroke={barColor} strokeWidth={1.5} />

              {/* Deviation bars */}
              {hVarianceRows.map((entry, i) => {
                if (!entry) return null
                const d = entry.delta
                const bandStart = i * bandWidth + (bandWidth - bw) / 2
                const color = d >= 0 ? posColor : negColor
                const devBarW = Math.abs(absScale(d) - absZeroX)
                const barX = d >= 0 ? absZeroX : absScale(d)
                // Always place label to the right of the deviation bar
                const labelX = d >= 0 ? barX + devBarW + 3 : barX + devBarW + 3
                const safeLabelX = Math.min(Math.max(labelX, 2), absPanelW - 2)
                const labelAnchor = 'start'
                const devH = (useWaterfallMain ? bw * WATERFALL_VARIANCE_THICKNESS : bw) * 0.6
                const devY = bandStart + (bw - devH) / 2
                return (
                  <g key={`abs-${i}`}>
                    <rect
                      x={barX} y={devY}
                      width={Math.max(devBarW, 1)} height={devH}
                      fill={color} rx={1}
                    />
                    <text
                      x={safeLabelX} y={bandStart + (useWaterfallMain ? (bw * WATERFALL_VARIANCE_THICKNESS) / 2 : bw / 2)}
                      dy="0.35em" fontSize={hDevFont} fill={mutedColor}
                      textAnchor={labelAnchor}
                      style={{ fontVariantNumeric: 'tabular-nums' }}
                    >
                      {formatVariance(d)}
                    </text>
                  </g>
                )
              })}
            </g>
          )}

          {/* ═══════ PANEL: Δ% lollipop (rightmost) ═══════ */}
          {showPctPanel && (
            <g transform={`translate(${pctPanelX}, 0)`}>
              {/* Panel label */}
              <text
                x={pctPanelW / 2} y={-6}
                dy="0.35em" fontSize={DEV_FONT} fill={mutedColor}
                textAnchor="middle" fontWeight={600}
              >
                Δ{useWaterfallMain ? waterfallCmpLabel : cmpLabel}%
              </text>

              {/* Baseline */}
              <line x1={pctZeroX} x2={pctZeroX} y1={0} y2={plotH}
                stroke={barColor} strokeWidth={1.5} />

              {/* Lollipop pins: horizontal stems + triangle heads */}
              {hVarianceRows.map((entry, i) => {
                if (!entry) return null
                const dp = entry.pct
                const cy = i * bandWidth + bandWidth / 2
                const pctVal = dp * 100
                const pinX = pctScale(pctVal)
                const stemColor = dp >= 0 ? posColor : negColor
                const right = dp >= 0
                const labelX = right ? pinX + 8 : pinX - 8
                const safeLabelX = Math.min(Math.max(labelX, 2), pctPanelW - 2)

                return (
                  <g key={`pct-${i}`}>
                    {/* Stem */}
                    <line
                      x1={pctZeroX} y1={cy} x2={pinX} y2={cy}
                      stroke={stemColor} strokeWidth={1.5}
                    />
                    {/* Triangle head */}
                    <polygon
                      points={right
                        ? `${pinX},${cy} ${pinX - 6},${cy - 4} ${pinX - 6},${cy + 4}`
                        : `${pinX},${cy} ${pinX + 6},${cy - 4} ${pinX + 6},${cy + 4}`}
                      fill={stemColor}
                    />
                    {/* Label */}
                    <text
                      x={safeLabelX} y={cy}
                      dy="0.35em" fontSize={hDevFont} fill={mutedColor}
                      textAnchor={right ? 'start' : 'end'}
                      style={{ fontVariantNumeric: 'tabular-nums' }}
                    >
                      {dp >= 0 ? '+' : ''}{pctVal.toFixed(1)}%
                    </text>
                  </g>
                )
              })}
            </g>
          )}

          {/* Category labels (left side) */}
          {hRowLabels.map((cat, i) => {
            const pos = i * bandWidth + bandWidth / 2
            const rotation = xAxisRotation ?? 0
            const anchor = rotation !== 0 ? 'end' : 'end'
            const maxChars = Math.abs(rotation) >= 45 ? 24 : 16
            return (
              <text key={cat} x={-8} y={pos} dy="0.35em" fontSize={AXIS_FONT}
                fill={txtColor} textAnchor={anchor}
                data-testid={useWaterfallMain ? `ibcs-waterfall-row-label-${i}` : undefined}
                transform={rotation !== 0 ? `rotate(${rotation}, ${-8}, ${pos})` : undefined}
              >
                {cat.length > maxChars ? cat.slice(0, maxChars - 1) + '…' : cat}
              </text>
            )
          })}
        </g>
      </svg>

      {/* Tooltip */}
      {tooltip && (
        <div
          className="fixed pointer-events-none z-50 bg-popover border border-border rounded px-2 py-1 shadow-md text-xs"
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

/**
 * IBCSLineChart — IBCS-compliant SVG line chart.
 *
 * Features:
 * - Scenario detection from column names (AC, PY, PL, FC)
 * - Scenario styling: AC = solid, PL = dashed, PY = dotted, FC = dash-dot
 * - Hills & valleys variance fill (green where AC > comparison, red where below)
 * - Direct end labels (no legend for ≤4 series)
 * - Minimal data point markers (first, last, min, max)
 * - Clean axis with grid lines
 * - Hover tooltip with crosshair
 * - Responsive sizing via ResizeObserver
 * - Dark mode support
 */

import { useMemo, useState, useCallback, useRef } from 'react'
import {
  IBCS,
  IBCSPatternDefs,
  formatCompact,
  linearScale,
  niceExtent,
  niceTicks,
  extractSeriesData,
} from './IBCSChartUtils'

export interface IBCSLineChartProps {
  columns: string[]
  rows: Array<Record<string, unknown>>
  width?: number
  height?: number
  isDark?: boolean
  showVarianceFill?: boolean
  onPointClick?: (value: unknown, isMultiSelect: boolean) => void
}

const MARGIN = { top: 20, right: 80, bottom: 36, left: 50 }
const LABEL_FONT = 10
const AXIS_FONT = 9
const LINE_WIDTH = 2
const MARKER_R = 3.5

// ─── Scenario Detection ─────────────────────────────────────────────────────

type ScenarioCode = 'ac' | 'py' | 'pl' | 'fc' | 'unknown'

/** Classify a series name into AC/PY/PL/FC by suffix conventions */
function classifyScenario(name: string): ScenarioCode {
  const n = name.toUpperCase()
  if (/ PY$/.test(n) || n.includes('PRIOR') || n.includes('PREVIOUS') || / LY$/.test(n)) return 'py'
  if (/ BUD$/.test(n) || n.includes('BUDGET') || / PL$/.test(n) || n.includes('PLAN')) return 'pl'
  if (/ FC$/.test(n) || n.includes('FORECAST')) return 'fc'
  if (/ AC$/.test(n) || n.includes('ACTUAL')) return 'ac'
  return 'unknown'
}

/** Extract metric name without scenario suffix: "Revenue AC" → "Revenue" */
function extractMetricName(colName: string): string {
  const sc = classifyScenario(colName)
  if (sc === 'unknown') return colName
  // Strip last word (the scenario tag)
  return colName.replace(/\s+\S+$/, '').trim() || colName
}

interface ScenarioStyle {
  stroke: string
  dash: string
  width: number
  label: string
  scenario: ScenarioCode
}

export function IBCSLineChart({
  columns,
  rows,
  width: containerWidth,
  height: containerHeight,
  isDark = false,
  showVarianceFill = true,
  onPointClick,
}: IBCSLineChartProps) {
  const svgRef = useRef<SVGSVGElement>(null)
  const [hoverIndex, setHoverIndex] = useState<number | null>(null)

  // ─── Responsive container measurement ───────────────────────────────────
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

  const { categories, series } = useMemo(
    () => extractSeriesData(columns, rows),
    [columns, rows],
  )

  // Prefer observed size > explicit props > defaults
  const vw = observedSize.w || containerWidth || 500
  const vh = observedSize.h || containerHeight || 300
  const plotW = vw - MARGIN.left - MARGIN.right
  const plotH = vh - MARGIN.top - MARGIN.bottom

  // ─── Scenario classification & styling ──────────────────────────────────

  const colors = isDark ? IBCS.dark : IBCS

  const classifiedSeries = useMemo(() => {
    // Classify each series by scenario
    const classified = series.map(s => ({
      ...s,
      scenario: classifyScenario(s.name),
      metricName: extractMetricName(s.name),
    }))

    // Sort: AC first, then PY, PL, FC, then unknown
    const order: Record<ScenarioCode, number> = { ac: 0, py: 1, pl: 2, fc: 3, unknown: 4 }
    classified.sort((a, b) => order[a.scenario] - order[b.scenario])

    // If none detected as AC, treat first as AC
    if (classified.length > 0 && !classified.some(s => s.scenario === 'ac')) {
      classified[0].scenario = 'ac'
    }
    return classified
  }, [series])

  /** Build scenario-based line style */
  const getSeriesStyle = useCallback((scenario: ScenarioCode, index: number): ScenarioStyle => {
    switch (scenario) {
      case 'ac':
        return { stroke: colors.actual, dash: '', width: LINE_WIDTH, label: 'AC', scenario }
      case 'py':
        return { stroke: isDark ? colors.previousYear : '#a0a0a0', dash: '3,3', width: 1.5, label: 'PY', scenario }
      case 'pl':
        return { stroke: colors.actual, dash: '8,4', width: LINE_WIDTH, label: 'PL', scenario }
      case 'fc':
        return { stroke: colors.actual, dash: '8,3,2,3', width: LINE_WIDTH, label: 'FC', scenario }
      default: {
        // Fallback styling by position
        const fallbacks: ScenarioStyle[] = [
          { stroke: colors.actual, dash: '', width: LINE_WIDTH, label: '', scenario: 'unknown' },
          { stroke: isDark ? colors.previousYear : '#a0a0a0', dash: '3,3', width: 1.5, label: '', scenario: 'unknown' },
          { stroke: colors.actual, dash: '8,4', width: LINE_WIDTH, label: '', scenario: 'unknown' },
        ]
        return fallbacks[index % fallbacks.length]
      }
    }
  }, [colors, isDark])

  const seriesStyles = useMemo(
    () => classifiedSeries.map((s, i) => getSeriesStyle(s.scenario, i)),
    [classifiedSeries, getSeriesStyle],
  )

  // ─── Scales ─────────────────────────────────────────────────────────────

  const allValues = useMemo(
    () => classifiedSeries.flatMap(s => s.values),
    [classifiedSeries],
  )
  const valueExtent = useMemo(() => niceExtent(allValues, false), [allValues])
  const ticks = useMemo(() => niceTicks(valueExtent, 5), [valueExtent])

  const xScale = useMemo(
    () => linearScale([0, Math.max(categories.length - 1, 1)], [0, plotW]),
    [categories.length, plotW],
  )
  const yScale = useMemo(
    () => linearScale(valueExtent, [plotH, 0]),
    [valueExtent, plotH],
  )

  // ─── Path generators ───────────────────────────────────────────────────

  const buildPath = useCallback(
    (values: number[]) =>
      values
        .map((v, i) => `${i === 0 ? 'M' : 'L'}${xScale(i).toFixed(1)},${yScale(v).toFixed(1)}`)
        .join(' '),
    [xScale, yScale],
  )

  // ─── Variance fill path (hills & valleys) ──────────────────────────────
  // Fills between AC line and first comparison (PY/PL) line.

  const varianceFills = useMemo(() => {
    if (!showVarianceFill || classifiedSeries.length < 2) return null
    const acSeries = classifiedSeries.find(s => s.scenario === 'ac') ?? classifiedSeries[0]
    const cmpSeries = classifiedSeries.find(s => s.scenario !== 'ac' && s.scenario !== 'unknown') ?? classifiedSeries[1]
    if (!acSeries || !cmpSeries) return null

    const ac = acSeries.values
    const cmp = cmpSeries.values
    if (ac.length !== cmp.length || ac.length < 2) return null

    const fills: Array<{ path: string; positive: boolean }> = []

    // Build segments between crossover points
    let i = 0
    while (i < ac.length - 1) {
      const segments: Array<[number, number, number]> = [] // [x, acY, cmpY]
      const startPositive = ac[i] >= cmp[i]

      for (let j = i; j < ac.length; j++) {
        const isPositive = ac[j] >= cmp[j]
        if (j > i && isPositive !== startPositive) {
          // Approximate crossover point via linear interpolation
          const prevDiff = ac[j - 1] - cmp[j - 1]
          const currDiff = ac[j] - cmp[j]
          const t = prevDiff / (prevDiff - currDiff)
          const crossX = xScale(j - 1 + t)
          const crossY = yScale(ac[j - 1] + t * (ac[j] - ac[j - 1]))
          segments.push([crossX, crossY, crossY])

          // Build closed path for this segment
          const pts = segments.map(s => s)
          const fwd = pts.map(p => `${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(' L')
          const bwd = [...pts].reverse().map(p => `${p[0].toFixed(1)},${p[2].toFixed(1)}`).join(' L')
          fills.push({ path: `M${fwd} L${bwd} Z`, positive: startPositive })

          i = j
          break
        }
        segments.push([xScale(j), yScale(ac[j]), yScale(cmp[j])])
        if (j === ac.length - 1) {
          const fwd = segments.map(p => `${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(' L')
          const bwd = [...segments].reverse().map(p => `${p[0].toFixed(1)},${p[2].toFixed(1)}`).join(' L')
          fills.push({ path: `M${fwd} L${bwd} Z`, positive: startPositive })
          i = ac.length
        }
      }
    }
    return fills
  }, [classifiedSeries, showVarianceFill, xScale, yScale])

  // ─── Key points for markers (first, last, min, max) ────────────────────

  const keyPoints = useMemo(() => {
    return classifiedSeries.map(s => {
      const vals = s.values
      if (vals.length === 0) return { set: new Set<number>(), types: new Map<number, string>() }
      const pts = new Set<number>()
      const types = new Map<number, string>()

      pts.add(0);              types.set(0, 'first')
      pts.add(vals.length - 1); types.set(vals.length - 1, 'last')

      let minI = 0, maxI = 0
      for (let i = 1; i < vals.length; i++) {
        if (vals[i] < vals[minI]) minI = i
        if (vals[i] > vals[maxI]) maxI = i
      }
      pts.add(minI); types.set(minI, 'min')
      pts.add(maxI); types.set(maxI, 'max')
      return { set: pts, types }
    })
  }, [classifiedSeries])

  // ─── Hover ──────────────────────────────────────────────────────────────

  const handleMouseMove = useCallback(
    (e: React.MouseEvent<SVGRectElement>) => {
      const svg = svgRef.current
      if (!svg) return
      const rect = svg.getBoundingClientRect()
      // Account for viewBox → actual-pixel scaling
      const scaleX = vw / rect.width
      const mouseX = (e.clientX - rect.left) * scaleX - MARGIN.left
      // Find nearest category index
      const idx = Math.round(
        ((mouseX / plotW) * (categories.length - 1)),
      )
      setHoverIndex(Math.max(0, Math.min(idx, categories.length - 1)))
    },
    [plotW, categories.length, vw],
  )

  const handleMouseLeave = useCallback(() => setHoverIndex(null), [])

  const handleClick = useCallback(
    (e: React.MouseEvent) => {
      if (hoverIndex != null && onPointClick) {
        onPointClick(categories[hoverIndex], e.ctrlKey || e.metaKey)
      }
    },
    [hoverIndex, onPointClick, categories],
  )

  // ─── Tooltip box content ───────────────────────────────────────────────

  const tooltipContent = useMemo(() => {
    if (hoverIndex == null) return null
    return {
      category: categories[hoverIndex],
      values: classifiedSeries.map((s, si) => ({
        name: s.name,
        value: s.values[hoverIndex],
        style: seriesStyles[si],
      })),
    }
  }, [hoverIndex, categories, classifiedSeries, seriesStyles])

  // ─── Render ─────────────────────────────────────────────────────────────

  if (categories.length === 0 || classifiedSeries.length === 0) {
    return (
      <div ref={setContainerRef} className="relative w-full h-full flex items-center justify-center" data-testid="ibcs-line-chart">
        <span className="text-xs text-muted-foreground">No data</span>
      </div>
    )
  }

  return (
    <div ref={setContainerRef} className="relative w-full h-full" data-testid="ibcs-line-chart">
      <svg
        ref={svgRef}
        data-testid="line-chart-svg"
        viewBox={`0 0 ${vw} ${vh}`}
        width="100%"
        height="100%"
        preserveAspectRatio="xMidYMid meet"
        style={{ fontFamily: 'system-ui, -apple-system, sans-serif' }}
      >
        <IBCSPatternDefs isDark={isDark} />

        <g transform={`translate(${MARGIN.left}, ${MARGIN.top})`}>
          {/* Grid lines */}
          {ticks.map(t => (
            <line
              key={t}
              x1={0} x2={plotW}
              y1={yScale(t)} y2={yScale(t)}
              stroke={colors.gridLine}
              strokeWidth={0.5}
            />
          ))}

          {/* Variance fills (hills & valleys) */}
          {varianceFills && varianceFills.length > 0 && (
            <g data-testid="hills-valleys-fill">
              {varianceFills.map((f, i) => (
                <path
                  key={i}
                  d={f.path}
                  fill={f.positive ? colors.positive : (isDark ? IBCS.dark.negative : IBCS.negative)}
                  opacity={0.22}
                />
              ))}
            </g>
          )}

          {/* Lines */}
          {classifiedSeries.map((s, si) => {
            const style = seriesStyles[si]
            return (
              <path
                key={s.name}
                data-testid={`line-path-${si}`}
                d={buildPath(s.values)}
                fill="none"
                stroke={style.stroke}
                strokeWidth={style.width}
                strokeDasharray={style.dash || undefined}
                strokeLinejoin="round"
                strokeLinecap="round"
              />
            )
          })}

          {/* Key-point markers (first, last, min, max) */}
          {classifiedSeries.map((s, si) => {
            const style = seriesStyles[si]
            const kp = keyPoints[si]
            return s.values.map((v, i) =>
              kp.set.has(i) ? (
                <circle
                  key={`${s.name}-${i}`}
                  data-testid={`marker-${kp.types.get(i) || 'point'}`}
                  cx={xScale(i)}
                  cy={yScale(v)}
                  r={MARKER_R}
                  fill={style.stroke}
                  stroke={isDark ? '#1a1a1a' : '#fff'}
                  strokeWidth={1.5}
                />
              ) : null,
            )
          })}

          {/* Direct end labels */}
          {classifiedSeries.map((s, si) => {
            const style = seriesStyles[si]
            const lastVal = s.values[s.values.length - 1]
            const scenarioLabel = style.label || s.metricName || s.name
            return (
              <g key={`label-${s.name}`} data-testid={`line-end-label-${si}`}>
                <text
                  x={plotW + 6}
                  y={yScale(lastVal)}
                  dy="-0.2em"
                  fontSize={LABEL_FONT}
                  fill={style.stroke}
                  style={{ fontVariantNumeric: 'tabular-nums', fontWeight: s.scenario === 'ac' ? 600 : 400 }}
                >
                  {formatCompact(lastVal)}
                </text>
                <text
                  x={plotW + 6}
                  y={yScale(lastVal)}
                  dy="0.95em"
                  fontSize={AXIS_FONT - 1}
                  fill={isDark ? colors.textMuted : '#888'}
                  style={{ fontWeight: 400 }}
                >
                  {scenarioLabel}
                </text>
              </g>
            )
          })}

          {/* Hover crosshair + tooltip values */}
          {hoverIndex != null && tooltipContent && (
            <g data-testid="line-chart-tooltip">
              <line
                x1={xScale(hoverIndex)} x2={xScale(hoverIndex)}
                y1={0} y2={plotH}
                stroke={colors.textMuted}
                strokeWidth={0.5}
                strokeDasharray="3,3"
              />
              {/* Tooltip background box */}
              {(() => {
                const boxX = xScale(hoverIndex) + 10
                const boxY = 4
                const boxW = 110
                const boxH = 16 + tooltipContent.values.length * 14
                const flipX = boxX + boxW > plotW ? xScale(hoverIndex) - boxW - 10 : boxX
                return (
                  <g>
                    <rect
                      x={flipX} y={boxY}
                      width={boxW} height={boxH}
                      rx={3} ry={3}
                      fill={isDark ? '#2a2a2a' : '#fff'}
                      stroke={isDark ? '#555' : '#ddd'}
                      strokeWidth={0.5}
                      opacity={0.95}
                    />
                    <text
                      x={flipX + 6} y={boxY + 12}
                      fontSize={AXIS_FONT}
                      fill={colors.textPrimary}
                      fontWeight={600}
                    >
                      {tooltipContent.category}
                    </text>
                    {tooltipContent.values.map((v, vi) => (
                      <text
                        key={vi}
                        x={flipX + 6} y={boxY + 12 + (vi + 1) * 14}
                        fontSize={AXIS_FONT}
                        fill={v.style.stroke}
                        style={{ fontVariantNumeric: 'tabular-nums' }}
                      >
                        {v.style.label || v.name}: {formatCompact(v.value)}
                      </text>
                    ))}
                  </g>
                )
              })()}
              {/* Highlight dots on all lines at crosshair */}
              {classifiedSeries.map((s, si) => {
                const v = s.values[hoverIndex]
                const style = seriesStyles[si]
                return (
                  <circle
                    key={`hover-${s.name}`}
                    cx={xScale(hoverIndex)}
                    cy={yScale(v)}
                    r={4}
                    fill={style.stroke}
                    stroke={isDark ? '#1a1a1a' : '#fff'}
                    strokeWidth={2}
                  />
                )
              })}
            </g>
          )}

          {/* Category axis labels */}
          {categories.map((cat, i) => {
            // Show all if ≤12, otherwise every Nth
            const step = categories.length > 12 ? Math.ceil(categories.length / 10) : 1
            if (i % step !== 0 && i !== categories.length - 1) return null
            return (
              <text
                key={cat}
                x={xScale(i)}
                y={plotH + 14}
                textAnchor="middle"
                fontSize={AXIS_FONT}
                fill={colors.textMuted}
              >
                {cat.length > 10 ? cat.slice(0, 9) + '…' : cat}
              </text>
            )
          })}

          {/* Value axis tick labels */}
          {ticks.map(t => (
            <text
              key={t}
              x={-8}
              y={yScale(t)}
              dy="0.35em"
              textAnchor="end"
              fontSize={AXIS_FONT}
              fill={colors.textMuted}
              style={{ fontVariantNumeric: 'tabular-nums' }}
            >
              {formatCompact(t, 0)}
            </text>
          ))}

          {/* Invisible hover rect */}
          <rect
            x={0} y={0}
            width={plotW} height={plotH}
            fill="transparent"
            onMouseMove={handleMouseMove}
            onMouseLeave={handleMouseLeave}
            onClick={handleClick}
            style={{ cursor: onPointClick ? 'pointer' : 'crosshair' }}
          />
        </g>
      </svg>
    </div>
  )
}

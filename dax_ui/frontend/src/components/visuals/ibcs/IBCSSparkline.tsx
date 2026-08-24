/**
 * IBCSSparkline — Miniature inline SVG line/area chart for KPI trend visualization.
 *
 * Features:
 * - Compact SVG rendering (no axes, no labels)
 * - Optional area fill beneath the line
 * - Last-value dot indicator
 * - Dark mode support
 * - data-testid for testability
 */

import { useMemo } from 'react'
import { IBCS, varianceColor } from './IBCSChartUtils'

export interface IBCSSparklineProps {
  /** Numeric data values for the sparkline */
  values: number[]
  /** Width of the SVG (default: 80) */
  width?: number
  /** Height of the SVG (default: 24) */
  height?: number
  /** Whether to fill the area beneath the line */
  showArea?: boolean
  /** Dark mode */
  isDark?: boolean
  /** Optional color override; defaults to IBCS actual gray */
  color?: string
  /** Whether the last value represents a positive or negative trend (colors the end dot) */
  trendDirection?: 'up' | 'down' | 'neutral'
}

export function IBCSSparkline({
  values,
  width = 80,
  height = 24,
  showArea = false,
  isDark = false,
  color,
  trendDirection = 'neutral',
}: IBCSSparklineProps) {
  const { points, areaPath, linePath, lastPoint, lineColor } = useMemo(() => {
    if (values.length === 0) {
      return { points: [], areaPath: '', linePath: '', lastPoint: null, lineColor: '' }
    }

    const lc = color ?? (isDark ? IBCS.dark.actual : IBCS.actual)
    const padding = 2
    const usableW = width - padding * 2
    const usableH = height - padding * 2

    const min = Math.min(...values)
    const max = Math.max(...values)
    const range = max - min || 1

    const pts = values.map((v, i) => ({
      x: padding + (values.length > 1 ? (i / (values.length - 1)) * usableW : usableW / 2),
      y: padding + usableH - ((v - min) / range) * usableH,
    }))

    const lp = pts.map(p => `${p.x},${p.y}`).join(' L ')
    const line = `M ${lp}`

    let area = ''
    if (showArea && pts.length > 1) {
      area = `M ${pts[0].x},${padding + usableH} L ${lp} L ${pts[pts.length - 1].x},${padding + usableH} Z`
    }

    const last = pts[pts.length - 1] ?? null

    return { points: pts, areaPath: area, linePath: line, lastPoint: last, lineColor: lc }
  }, [values, width, height, showArea, isDark, color])

  if (values.length === 0) {
    return <svg width={width} height={height} data-testid="kpi-sparkline" />
  }

  // End-dot color: if trend direction is known, use variance color
  const dotColor =
    trendDirection === 'up'
      ? varianceColor(1, isDark)
      : trendDirection === 'down'
        ? varianceColor(-1, isDark)
        : lineColor

  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      data-testid="kpi-sparkline"
      style={{ display: 'block' }}
    >
      {/* Area fill */}
      {showArea && areaPath && (
        <path
          d={areaPath}
          fill={lineColor}
          fillOpacity={0.12}
        />
      )}
      {/* Line */}
      <path
        d={linePath}
        fill="none"
        stroke={lineColor}
        strokeWidth={1.5}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      {/* Last-value dot */}
      {lastPoint && (
        <circle
          cx={lastPoint.x}
          cy={lastPoint.y}
          r={2.5}
          fill={dotColor}
        />
      )}
    </svg>
  )
}

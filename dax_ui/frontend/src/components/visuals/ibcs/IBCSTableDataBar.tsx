/**
 * IBCSTableDataBar — Inline SVG data bar for IBCS table cells.
 *
 * Renders a small horizontal bar proportional to value/maxValue.
 * Uses IBCS colors: dark gray for positive, red for negative.
 */

import { IBCS } from './IBCSChartUtils'

export interface IBCSTableDataBarProps {
  value: number
  maxValue: number
  width?: number
  height?: number
  color?: string
  isDark?: boolean
}

export function IBCSTableDataBar({
  value,
  maxValue,
  width = 60,
  height = 14,
  color,
  isDark = false,
}: IBCSTableDataBarProps) {
  if (maxValue === 0) return null

  const ratio = Math.min(Math.abs(value) / maxValue, 1)
  const barWidth = ratio * width
  const isNegative = value < 0

  const defaultColor = isNegative
    ? (isDark ? IBCS.dark.negative : IBCS.negative)
    : (isDark ? IBCS.dark.actual : IBCS.actual)

  const fillColor = color ?? defaultColor

  return (
    <svg
      data-testid="ibcs-data-bar"
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      className="inline-block align-middle"
      style={{ minWidth: width }}
    >
      {/* Background track */}
      <rect
        x={0}
        y={2}
        width={width}
        height={height - 4}
        fill={isDark ? '#333' : '#f0f0f0'}
        rx={1}
      />
      {/* Value bar */}
      <rect
        x={isNegative ? width - barWidth : 0}
        y={2}
        width={barWidth}
        height={height - 4}
        fill={fillColor}
        rx={1}
        opacity={0.85}
      />
    </svg>
  )
}

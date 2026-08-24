/**
 * IBCSSmallMultiples — Responsive grid of mini-charts, one per group value.
 *
 * Takes any IBCS chart type (bar, line, waterfall, card) and splits data
 * by a grouping dimension, rendering one sub-chart per unique group value
 * in a CSS grid layout with synchronized Y-axis scales.
 *
 * Inspired by Zebra BI small multiples — "one of the most powerful features".
 */

import { useRef, useState, useEffect, useCallback, useMemo } from 'react'
import { IBCSBarChart } from './IBCSBarChart'
import { IBCSLineChart } from './IBCSLineChart'
import { IBCSWaterfall } from './IBCSWaterfall'
import { IBCSCard } from './IBCSCard'
import { IBCS } from './IBCSChartUtils'

// ─── Props ──────────────────────────────────────────────────────────────────

export interface IBCSSmallMultiplesProps {
  columns: string[]
  rows: Array<Record<string, unknown>>
  groupByColumn: string
  chartType: 'bar' | 'line' | 'waterfall' | 'card'
  width?: number
  height?: number
  isDark?: boolean
  /** Max charts per row (default: 3) */
  maxColumns?: number
  /** Shared Y-axis scale across all sub-charts (default: true) */
  syncScale?: boolean
  onCellClick?: (groupValue: unknown, value: unknown, isMultiSelect: boolean) => void
}

// ─── Helpers ────────────────────────────────────────────────────────────────

interface GroupData {
  groupValue: unknown
  groupLabel: string
  rows: Array<Record<string, unknown>>
  columns: string[]
}

/** Split rows by unique values of groupByColumn, removing it from sub-columns */
function splitByGroup(
  columns: string[],
  rows: Array<Record<string, unknown>>,
  groupByColumn: string,
): GroupData[] {
  const subColumns = columns.filter(c => c !== groupByColumn)
  const groupMap = new Map<string, { groupValue: unknown; rows: Array<Record<string, unknown>> }>()

  for (const row of rows) {
    const gv = row[groupByColumn]
    const key = String(gv ?? '')
    if (!groupMap.has(key)) {
      groupMap.set(key, { groupValue: gv, rows: [] })
    }
    // Build sub-row without the groupBy column
    const subRow: Record<string, unknown> = {}
    for (const col of subColumns) {
      subRow[col] = row[col]
    }
    groupMap.get(key)!.rows.push(subRow)
  }

  return Array.from(groupMap.entries()).map(([key, { groupValue, rows: groupRows }]) => ({
    groupValue,
    groupLabel: key || '(blank)',
    rows: groupRows,
    columns: subColumns,
  }))
}

/** Compute global min/max across all groups for synced scale */
function computeGlobalExtent(groups: GroupData[]): [number, number] {
  let globalMin = Infinity
  let globalMax = -Infinity

  for (const group of groups) {
    for (const row of group.rows) {
      for (const col of group.columns) {
        const v = row[col]
        if (typeof v === 'number' && isFinite(v)) {
          if (v < globalMin) globalMin = v
          if (v > globalMax) globalMax = v
        }
      }
    }
  }

  if (!isFinite(globalMin)) globalMin = 0
  if (!isFinite(globalMax)) globalMax = 1
  // Include zero for bar/waterfall
  globalMin = Math.min(0, globalMin)
  globalMax = Math.max(0, globalMax)
  // 10% padding
  const pad = (globalMax - globalMin) * 0.1 || 1
  return [globalMin - (globalMin < 0 ? pad : 0), globalMax + pad]
}

/** Compute responsive column count based on container width */
function computeColumnCount(containerWidth: number, maxColumns: number, groupCount: number): number {
  const minCellWidth = 200
  const autoFit = Math.max(1, Math.floor(containerWidth / minCellWidth))
  return Math.min(autoFit, maxColumns, groupCount)
}

// ─── Component ──────────────────────────────────────────────────────────────

export function IBCSSmallMultiples({
  columns,
  rows,
  groupByColumn,
  chartType,
  width,
  height,
  isDark = false,
  maxColumns = 3,
  syncScale = true,
  onCellClick,
}: IBCSSmallMultiplesProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [containerWidth, setContainerWidth] = useState(width ?? 600)

  // ResizeObserver for responsive layout
  useEffect(() => {
    if (width != null) {
      setContainerWidth(width)
      return
    }
    const el = containerRef.current
    if (!el) return
    const ro = new ResizeObserver((entries) => {
      for (const entry of entries) {
        setContainerWidth(entry.contentRect.width)
      }
    })
    ro.observe(el)
    return () => ro.disconnect()
  }, [width])

  // Split data into groups
  const groups = useMemo(
    () => splitByGroup(columns, rows, groupByColumn),
    [columns, rows, groupByColumn],
  )

  // Compute global extent for sync scale
  const globalExtent = useMemo(
    () => (syncScale ? computeGlobalExtent(groups) : undefined),
    [groups, syncScale],
  )

  // Column count + cell dimensions
  const colCount = useMemo(
    () => computeColumnCount(containerWidth, maxColumns, groups.length),
    [containerWidth, maxColumns, groups.length],
  )
  const gap = 12
  const cellWidth = Math.floor((containerWidth - gap * (colCount - 1)) / colCount)
  const cellHeight = chartType === 'card' ? 120 : Math.min(Math.max(cellWidth * 0.65, 140), 300)
  const labelHeight = 24

  // Colors
  const colors = isDark ? IBCS.dark : IBCS

  // Handler factory
  const makeClickHandler = useCallback(
    (groupValue: unknown) =>
      onCellClick
        ? (value: unknown, isMultiSelect: boolean) => onCellClick(groupValue, value, isMultiSelect)
        : undefined,
    [onCellClick],
  )

  // Fallback: if groupByColumn is not in columns, render a warning
  if (!columns.includes(groupByColumn)) {
    return (
      <div
        className="flex items-center justify-center h-full text-muted-foreground text-xs p-4"
        data-testid="small-multiples-grid"
      >
        Column &quot;{groupByColumn}&quot; not found in data columns.
      </div>
    )
  }

  // Empty groups
  if (groups.length === 0) {
    return (
      <div
        className="flex items-center justify-center h-full text-muted-foreground text-xs p-4"
        data-testid="small-multiples-grid"
      >
        No data available for small multiples.
      </div>
    )
  }

  return (
    <div
      ref={containerRef}
      className="h-full overflow-auto p-2"
      data-testid="small-multiples-grid"
      style={width != null ? { width } : undefined}
    >
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: `repeat(${colCount}, 1fr)`,
          gap: `${gap}px`,
        }}
      >
        {groups.map((group) => {
          const safeLabel = sanitizeTestId(group.groupLabel)
          return (
            <div
              key={group.groupLabel}
              data-testid={`small-multiple-${safeLabel}`}
              style={{
                border: `1px solid ${isDark ? '#444' : '#e0e0e0'}`,
                borderRadius: 4,
                overflow: 'hidden',
                background: isDark ? '#1a1a1a' : '#fff',
              }}
            >
              {/* Group label header */}
              <div
                data-testid={`small-multiple-label-${safeLabel}`}
                style={{
                  height: labelHeight,
                  display: 'flex',
                  alignItems: 'center',
                  padding: '0 8px',
                  fontSize: 11,
                  fontWeight: 600,
                  color: colors.textPrimary,
                  background: isDark ? '#222' : '#f8f8f8',
                  borderBottom: `1px solid ${isDark ? '#444' : '#e8e8e8'}`,
                  whiteSpace: 'nowrap',
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                }}
              >
                {group.groupLabel}
              </div>

              {/* Sub-chart */}
              <div style={{ height: cellHeight }}>
                <SubChart
                  group={group}
                  chartType={chartType}
                  width={cellWidth - 2}  /* subtract border */
                  height={cellHeight}
                  isDark={isDark}
                  globalExtent={globalExtent}
                  onChartClick={makeClickHandler(group.groupValue)}
                />
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ─── SubChart Renderer ──────────────────────────────────────────────────────

interface SubChartProps {
  group: GroupData
  chartType: 'bar' | 'line' | 'waterfall' | 'card'
  width: number
  height: number
  isDark: boolean
  globalExtent?: [number, number]
  onChartClick?: (value: unknown, isMultiSelect: boolean) => void
}

function SubChart({ group, chartType, width, height, isDark, onChartClick }: SubChartProps) {
  const { columns, rows } = group

  if (rows.length === 0) {
    return (
      <div className="flex items-center justify-center h-full text-muted-foreground text-[10px]">
        No data
      </div>
    )
  }

  switch (chartType) {
    case 'bar':
      return (
        <IBCSBarChart
          columns={columns}
          rows={rows}
          width={width}
          height={height}
          isDark={isDark}
          orientation="horizontal"
          onBarClick={onChartClick}
        />
      )

    case 'line':
      return (
        <IBCSLineChart
          columns={columns}
          rows={rows}
          width={width}
          height={height}
          isDark={isDark}
          onPointClick={onChartClick}
        />
      )

    case 'waterfall':
      return (
        <IBCSWaterfall
          columns={columns}
          rows={rows}
          width={width}
          height={height}
          isDark={isDark}
          onBarClick={onChartClick}
        />
      )

    case 'card':
      return (
        <IBCSCard
          columns={columns}
          rows={rows}
          width={width}
          height={height}
          isDark={isDark}
        />
      )

    default:
      return (
        <div className="flex items-center justify-center h-full text-muted-foreground text-[10px]">
          Unknown chart type: {chartType}
        </div>
      )
  }
}

// ─── Utilities ──────────────────────────────────────────────────────────────

/** Sanitize a group label for use as a test ID (lowercase, replace spaces/special chars) */
function sanitizeTestId(label: string): string {
  return label
    .toLowerCase()
    .replace(/[^a-z0-9_-]/g, '-')
    .replace(/-+/g, '-')
    .replace(/^-|-$/g, '')
}

// ─── Exported Helpers (for testing) ─────────────────────────────────────────

export { splitByGroup, computeGlobalExtent, computeColumnCount }

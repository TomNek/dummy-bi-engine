/**
 * IBCSTable — IBCS-styled table visual consuming TablixPlan data.
 *
 * Features:
 * - Hierarchical row expand/collapse (tree structure via level/depth fields)
 * - Multi-level grouped column headers (via IBCSTableHeader)
 * - Inline SVG data bars for numeric cells (via IBCSTableDataBar)
 * - Scenario-styled column headers (AC/PY/PL/FC)
 * - Sticky header row
 * - IBCS typography: grayscale, monospace for numbers, green/red for variance
 * - Variance columns: ΔAbs and Δ% auto-detected and colored
 * - Zebra striping: subtle alternating row backgrounds
 * - Compact number formatting (K, M, B)
 */

import { useMemo, useState, useCallback } from 'react'
import { IBCS, formatCompact, varianceColor } from './IBCSChartUtils'
import { IBCSTableDataBar } from './IBCSTableDataBar'
import { IBCSTableHeader } from './IBCSTableHeader'

export interface IBCSTableProps {
  columns: string[]
  rows: Array<Record<string, unknown>>
  width?: number
  height?: number
  isDark?: boolean
}

// ─── Detection Helpers ──────────────────────────────────────────────────────

/** Check if a column contains mostly numeric values */
function isNumericColumn(rows: Array<Record<string, unknown>>, col: string): boolean {
  if (rows.length === 0) return false
  let numCount = 0
  const sample = rows.slice(0, Math.min(rows.length, 50))
  for (const row of sample) {
    const v = row[col]
    if (v == null) continue
    if (typeof v === 'number') { numCount++; continue }
    if (typeof v === 'string' && v.trim() !== '' && !isNaN(Number(v))) { numCount++; continue }
  }
  return numCount > sample.length * 0.5
}

/** Detect if a column is a variance column (ΔAbs, Δ%, VAR, etc.) */
function isVarianceColumn(col: string): boolean {
  const n = col.toLowerCase()
  return /[δΔ]/.test(col)
    || n.includes('variance')
    || n.includes('var ')
    || n.includes('var%')
    || n.includes('δabs')
    || n.includes('δ%')
    || n.includes('delta')
    || /\babs\b/.test(n)
    || n.endsWith(' var')
    || n.endsWith(' diff')
    || n.endsWith(' deviation')
}

/** Detect if a column is a percentage-type column */
function isPercentColumn(col: string): boolean {
  const n = col.toLowerCase()
  return n.includes('%') || n.includes('pct') || n.includes('percent') || n.endsWith('ratio')
}

/** Detect IBCS scenario from column name for styling */
function detectScenario(col: string): 'ac' | 'py' | 'pl' | 'fc' | 'none' {
  const n = col.toUpperCase()
  if (/ AC$/.test(n) || n === 'AC' || n.includes('ACTUAL')) return 'ac'
  if (/ PY$/.test(n) || n === 'PY' || n.includes('PREVIOUS') || / LY$/.test(n)) return 'py'
  if (/ PL$/.test(n) || n === 'PL' || n.includes('PLAN') || / BUD$/.test(n) || n.includes('BUDGET')) return 'pl'
  if (/ FC$/.test(n) || n === 'FC' || n.includes('FORECAST')) return 'fc'
  return 'none'
}

/** Get max absolute value for a numeric column (for data bar scaling) */
function columnMaxAbs(rows: Array<Record<string, unknown>>, col: string): number {
  let max = 0
  for (const row of rows) {
    const v = row[col]
    const n = typeof v === 'number' ? v : Number(v)
    if (!isNaN(n)) max = Math.max(max, Math.abs(n))
  }
  return max
}

/** Detect hierarchical row level from row data */
function getRowLevel(row: Record<string, unknown>): number {
  // Support multiple conventions for hierarchy level
  if (typeof row.__level === 'number') return row.__level
  if (typeof row._level === 'number') return row._level
  if (typeof row.level === 'number') return row.level
  if (typeof row.__depth === 'number') return row.__depth
  if (typeof row._depth === 'number') return row._depth
  if (typeof row.depth === 'number') return row.depth
  if (typeof row.__indent === 'number') return row.__indent
  return 0
}

/** Check if a row has children (for expand/collapse) */
function hasChildren(row: Record<string, unknown>): boolean {
  if (row.__has_children === true || row._has_children === true) return true
  if (row.__is_leaf === false || row._is_leaf === false) return true
  return false
}

/** Check if a row is a total/subtotal row */
function isTotalRow(row: Record<string, unknown>): boolean {
  if (row.__is_total === true || row._is_total === true) return true
  if (row.__is_subtotal === true || row._is_subtotal === true) return true
  // Check if first text column contains "Total"
  return false
}

// ─── Main Component ─────────────────────────────────────────────────────────

export function IBCSTable({
  columns,
  rows,
  width,
  height,
  isDark = false,
}: IBCSTableProps) {
  const [expandedRows, setExpandedRows] = useState<Set<number>>(new Set())
  const [sortColumn, setSortColumn] = useState<string | null>(null)
  const [sortDirection, setSortDirection] = useState<'asc' | 'desc'>('asc')

  const c = isDark ? IBCS.dark : IBCS

  // ─── Column analysis ─────────────────────────────────────────────────
  const columnInfo = useMemo(() => {
    return columns.map(col => ({
      name: col,
      isNumeric: isNumericColumn(rows, col),
      isVariance: isVarianceColumn(col),
      isPercent: isPercentColumn(col),
      scenario: detectScenario(col),
      maxAbs: columnMaxAbs(rows, col),
    }))
  }, [columns, rows])

  // ─── Row hierarchy analysis ───────────────────────────────────────────
  const hasHierarchy = useMemo(() => {
    return rows.some(r => getRowLevel(r) > 0 || hasChildren(r))
  }, [rows])

  // ─── Toggle row expansion ────────────────────────────────────────────
  const toggleRow = useCallback((rowIndex: number) => {
    setExpandedRows(prev => {
      const next = new Set(prev)
      if (next.has(rowIndex)) {
        next.delete(rowIndex)
      } else {
        next.add(rowIndex)
      }
      return next
    })
  }, [])

  // ─── Sorting ─────────────────────────────────────────────────────────
  const handleColumnClick = useCallback((col: string) => {
    setSortColumn(prev => {
      if (prev === col) {
        setSortDirection(d => d === 'asc' ? 'desc' : 'asc')
        return col
      }
      setSortDirection('asc')
      return col
    })
  }, [])

  // ─── Filtered & sorted rows ──────────────────────────────────────────
  const visibleRows = useMemo(() => {
    let result = [...rows]

    // Filter by hierarchy expansion
    if (hasHierarchy) {
      const visible: Array<Record<string, unknown>> = []
      const parentExpanded = new Map<number, boolean>() // level -> expanded

      for (let i = 0; i < result.length; i++) {
        const level = getRowLevel(result[i])
        if (level === 0) {
          visible.push(result[i])
          // Initialize: initial state is all collapsed unless explicitly expanded
        } else {
          // Check if all ancestor levels are expanded
          let show = true
          // Simple heuristic: check if previous visible row at level-1 is expanded
          let parentIdx = -1
          for (let j = visible.length - 1; j >= 0; j--) {
            if (getRowLevel(visible[j]) < level) {
              parentIdx = rows.indexOf(visible[j])
              break
            }
          }
          if (parentIdx >= 0 && !expandedRows.has(parentIdx)) {
            show = false
          }
          if (show) visible.push(result[i])
        }
      }
      result = visible
    }

    // Apply sorting
    if (sortColumn) {
      const info = columnInfo.find(ci => ci.name === sortColumn)
      result.sort((a, b) => {
        const va = a[sortColumn!]
        const vb = b[sortColumn!]
        let cmp = 0
        if (info?.isNumeric) {
          const na = typeof va === 'number' ? va : Number(va) || 0
          const nb = typeof vb === 'number' ? vb : Number(vb) || 0
          cmp = na - nb
        } else {
          cmp = String(va ?? '').localeCompare(String(vb ?? ''))
        }
        return sortDirection === 'asc' ? cmp : -cmp
      })
    }

    return result
  }, [rows, hasHierarchy, expandedRows, sortColumn, sortDirection, columnInfo])

  // ─── Cell formatting ─────────────────────────────────────────────────
  const formatCell = useCallback((value: unknown, info: typeof columnInfo[number]): string => {
    if (value == null || value === '') return '—'
    if (!info.isNumeric) return String(value)
    const num = typeof value === 'number' ? value : Number(value)
    if (isNaN(num)) return String(value)

    if (info.isPercent) {
      const pct = Math.abs(num) < 1 ? num * 100 : num
      const sign = pct > 0 ? '+' : pct < 0 ? '−' : ''
      return `${sign}${Math.abs(pct).toFixed(1)}%`
    }
    if (info.isVariance) {
      const sign = num > 0 ? '+' : num < 0 ? '−' : ''
      return `${sign}${formatCompact(Math.abs(num))}`
    }
    return formatCompact(num)
  }, [])

  // ─── Cell color ──────────────────────────────────────────────────────
  const cellColor = useCallback((value: unknown, info: typeof columnInfo[number]): string | undefined => {
    if (!info.isVariance && !info.isPercent) return undefined
    const num = typeof value === 'number' ? value : Number(value)
    if (isNaN(num) || num === 0) return undefined
    return varianceColor(num, isDark)
  }, [isDark])

  // ─── Container styles ────────────────────────────────────────────────
  const containerStyle: React.CSSProperties = {
    width: width ?? '100%',
    height: height ?? '100%',
    overflow: 'auto',
    fontFamily: 'system-ui, -apple-system, sans-serif',
    fontSize: 12,
    color: c.textPrimary,
    position: 'relative',
  }

  const tableStyle: React.CSSProperties = {
    width: '100%',
    borderCollapse: 'collapse',
    tableLayout: 'auto',
  }

  if (columns.length === 0) {
    return (
      <div data-testid="ibcs-table" style={containerStyle} className="flex items-center justify-center">
        <span style={{ color: c.textMuted, fontSize: 13 }}>No data</span>
      </div>
    )
  }

  return (
    <div data-testid="ibcs-table" style={containerStyle}>
      <table style={tableStyle}>
        <IBCSTableHeader
          columns={columns}
          isDark={isDark}
          onColumnClick={handleColumnClick}
        />
        <tbody>
          {visibleRows.map((row, rowIdx) => {
            const originalIdx = rows.indexOf(row)
            const level = getRowLevel(row)
            const isTotal = isTotalRow(row)
            const canExpand = hasHierarchy && hasChildren(row)
            const isExpanded = expandedRows.has(originalIdx)
            const isEven = rowIdx % 2 === 0

            return (
              <tr
                key={originalIdx}
                data-testid={`ibcs-table-row-${rowIdx}`}
                style={{
                  backgroundColor: isTotal
                    ? (isDark ? '#2a2a2a' : '#f5f5f5')
                    : isEven
                    ? (isDark ? '#1e1e1e' : '#ffffff')
                    : (isDark ? '#242424' : '#fafafa'),
                  borderBottom: isTotal
                    ? `2px solid ${c.totalBorder}`
                    : `1px solid ${c.gridLine}`,
                  fontWeight: isTotal ? 600 : 400,
                }}
              >
                {columnInfo.map((info, colIdx) => {
                  const value = row[info.name]
                  const formatted = formatCell(value, info)
                  const color = cellColor(value, info)
                  const isFirstCol = colIdx === 0
                  const showDataBar = info.isNumeric && !info.isVariance && !info.isPercent && info.maxAbs > 0

                  return (
                    <td
                      key={colIdx}
                      data-testid={`ibcs-table-cell-${rowIdx}-${colIdx}`}
                      style={{
                        padding: '4px 8px',
                        textAlign: info.isNumeric ? 'right' : 'left',
                        fontFamily: info.isNumeric ? '"SF Mono", "Cascadia Code", "Consolas", monospace' : 'inherit',
                        fontSize: 12,
                        color: color ?? c.textPrimary,
                        fontWeight: (info.isVariance && color) ? 600 : 'inherit',
                        whiteSpace: 'nowrap',
                        paddingLeft: isFirstCol ? `${8 + level * 16}px` : '8px',
                        verticalAlign: 'middle',
                      }}
                    >
                      {/* Expand/collapse toggle for hierarchical first column */}
                      {isFirstCol && canExpand && (
                        <button
                          onClick={(e) => { e.stopPropagation(); toggleRow(originalIdx) }}
                          style={{
                            background: 'none',
                            border: 'none',
                            cursor: 'pointer',
                            padding: '0 4px 0 0',
                            fontSize: 10,
                            color: c.textMuted,
                            verticalAlign: 'middle',
                          }}
                          aria-label={isExpanded ? 'Collapse' : 'Expand'}
                        >
                          {isExpanded ? '▼' : '▶'}
                        </button>
                      )}
                      {isFirstCol && !canExpand && hasHierarchy && (
                        <span style={{ display: 'inline-block', width: 14 }} />
                      )}
                      <span>{formatted}</span>
                      {/* Inline data bar for non-variance numeric columns */}
                      {showDataBar && typeof value === 'number' && (
                        <span style={{ marginLeft: 6, display: 'inline-block', verticalAlign: 'middle' }} data-testid="ibcs-table-data-bar">
                          <IBCSTableDataBar
                            value={value}
                            maxValue={info.maxAbs}
                            width={48}
                            height={12}
                            isDark={isDark}
                          />
                        </span>
                      )}
                    </td>
                  )
                })}
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

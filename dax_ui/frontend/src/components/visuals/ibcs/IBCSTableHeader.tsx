/**
 * IBCSTableHeader — Multi-level grouped column header for IBCS tables.
 *
 * Detects grouped headers using "|" delimiter (e.g., "Revenue|AC", "Revenue|PY")
 * and renders a two-row header: group labels spanning columns, then leaf labels
 * with scenario-specific IBCS styling.
 */

import { IBCS } from './IBCSChartUtils'

export interface IBCSTableHeaderProps {
  columns: string[]
  isDark?: boolean
  /** Callback when a column header is clicked (for sorting) */
  onColumnClick?: (column: string) => void
}

/** Parsed header structure */
export interface HeaderGroup {
  label: string
  span: number
  startIndex: number
}

export interface LeafHeader {
  /** The full original column name */
  fullName: string
  /** Display label (after "|" if grouped, or full name) */
  label: string
  /** Detected IBCS scenario */
  scenario: 'ac' | 'py' | 'pl' | 'fc' | 'none'
  /** Index into original columns array */
  index: number
}

/** Classify a column name fragment into an IBCS scenario */
function classifyScenario(name: string): 'ac' | 'py' | 'pl' | 'fc' | 'none' {
  const n = name.trim().toUpperCase()
  if (n === 'AC' || n === 'ACTUAL' || n.endsWith(' AC')) return 'ac'
  if (n === 'PY' || n === 'PREVIOUS YEAR' || n.endsWith(' PY') || n.endsWith(' LY')) return 'py'
  if (n === 'PL' || n === 'PLAN' || n === 'BUD' || n === 'BUDGET' || n.endsWith(' PL') || n.endsWith(' BUD')) return 'pl'
  if (n === 'FC' || n === 'FORECAST' || n.endsWith(' FC')) return 'fc'
  return 'none'
}

/** Parse columns into group rows and leaf rows */
export function parseHeaderGroups(columns: string[]): { groups: HeaderGroup[]; leaves: LeafHeader[]; hasGroups: boolean } {
  const leaves: LeafHeader[] = []
  const groupMap: { label: string; startIndex: number; count: number }[] = []

  let hasAnyGroup = false

  columns.forEach((col, i) => {
    const pipeIdx = col.indexOf('|')
    if (pipeIdx >= 0) {
      hasAnyGroup = true
      const groupLabel = col.substring(0, pipeIdx).trim()
      const leafLabel = col.substring(pipeIdx + 1).trim()
      leaves.push({ fullName: col, label: leafLabel, scenario: classifyScenario(leafLabel), index: i })

      // Extend existing group or start new one
      const last = groupMap[groupMap.length - 1]
      if (last && last.label === groupLabel && last.startIndex + last.count === i) {
        last.count++
      } else {
        groupMap.push({ label: groupLabel, startIndex: i, count: 1 })
      }
    } else {
      leaves.push({ fullName: col, label: col, scenario: classifyScenario(col), index: i })
      groupMap.push({ label: '', startIndex: i, count: 1 })
    }
  })

  const groups: HeaderGroup[] = groupMap.map(g => ({
    label: g.label,
    span: g.count,
    startIndex: g.startIndex,
  }))

  return { groups, leaves, hasGroups: hasAnyGroup }
}

/** Get scenario-specific styles for an IBCS header cell */
function scenarioStyle(scenario: 'ac' | 'py' | 'pl' | 'fc' | 'none', isDark: boolean): React.CSSProperties {
  const c = isDark ? IBCS.dark : IBCS
  switch (scenario) {
    case 'ac':
      return {
        fontWeight: 700,
        color: c.textPrimary,
        borderBottom: `2px solid ${c.actual}`,
      }
    case 'py':
      return {
        fontWeight: 400,
        color: c.textSecondary,
        backgroundColor: isDark ? '#2a2a2a' : '#fafafa',
        borderBottom: `2px solid ${isDark ? '#555' : '#ccc'}`,
      }
    case 'pl':
      return {
        fontWeight: 400,
        fontStyle: 'italic',
        color: c.textSecondary,
        borderBottom: `2px dashed ${c.actual}`,
      }
    case 'fc':
      return {
        fontWeight: 400,
        color: c.textSecondary,
        borderBottom: `2px solid ${c.actual}`,
        backgroundImage: isDark
          ? 'repeating-linear-gradient(45deg, transparent, transparent 3px, rgba(255,255,255,0.05) 3px, rgba(255,255,255,0.05) 6px)'
          : 'repeating-linear-gradient(45deg, transparent, transparent 3px, rgba(0,0,0,0.03) 3px, rgba(0,0,0,0.03) 6px)',
      }
    default:
      return { fontWeight: 500, color: c.textPrimary }
  }
}

export function IBCSTableHeader({ columns, isDark = false, onColumnClick }: IBCSTableHeaderProps) {
  const { groups, leaves, hasGroups } = parseHeaderGroups(columns)
  const c = isDark ? IBCS.dark : IBCS

  const baseHeaderStyle: React.CSSProperties = {
    fontSize: 11,
    fontFamily: 'system-ui, -apple-system, sans-serif',
    whiteSpace: 'nowrap',
    padding: '6px 8px',
    borderBottom: `1px solid ${c.gridLine}`,
    textAlign: 'left',
    userSelect: 'none',
  }

  return (
    <thead data-testid="ibcs-table-header" style={{ position: 'sticky', top: 0, zIndex: 2 }}>
      {/* Group row (only when pipe-delimited groups detected) */}
      {hasGroups && (
        <tr style={{ backgroundColor: isDark ? '#1a1a1a' : '#f8f8f8' }}>
          {groups.map((g, gi) => (
            <th
              key={`grp-${gi}`}
              colSpan={g.span}
              data-testid={g.label ? `ibcs-table-header-group-${g.label.replace(/\s+/g, '-').toLowerCase()}` : undefined}
              style={{
                ...baseHeaderStyle,
                textAlign: 'center',
                fontWeight: 600,
                fontSize: 12,
                color: c.textPrimary,
                borderBottom: g.label ? `2px solid ${c.actual}` : `1px solid ${c.gridLine}`,
              }}
            >
              {g.label}
            </th>
          ))}
        </tr>
      )}
      {/* Leaf header row */}
      <tr style={{ backgroundColor: isDark ? IBCS.dark.headerBg : IBCS.headerBg }}>
        {leaves.map((leaf) => (
          <th
            key={leaf.index}
            onClick={onColumnClick ? () => onColumnClick(leaf.fullName) : undefined}
            style={{
              ...baseHeaderStyle,
              ...scenarioStyle(leaf.scenario, isDark),
              cursor: onColumnClick ? 'pointer' : 'default',
            }}
          >
            {leaf.label}
          </th>
        ))}
      </tr>
    </thead>
  )
}

/**
 * DataGrid — Main data table with sortable columns, filter buttons,
 * type badges, completeness bar, and click-to-copy cells.
 */
import { useRef, useCallback, useState } from 'react'
import { ArrowUp, ArrowDown, ArrowUpDown, Filter, Loader2, Copy, Check } from 'lucide-react'
import { cn } from '@/lib/utils'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { DataColumnFilter } from './DataColumnFilter'
import type { ColumnFilter } from '@/hooks/useDataView'
import type { DataViewProfileResponse } from '@/lib/api'

interface Props {
  columns: string[]
  rows: Record<string, unknown>[]
  loading: boolean
  error: string | null
  sortColumn: string | null
  sortDir: 'asc' | 'desc' | null
  onToggleSort: (column: string) => void
  filters: Record<string, ColumnFilter>
  onSetFilter: (column: string, filter: ColumnFilter | null) => void
  selectedColumn: string | null
  onSelectColumn: (col: string | null) => void
  profile: DataViewProfileResponse | null
  filterValues: string[]
  filterValuesLoading: boolean
  onLoadFilterValues: (column: string, search?: string) => void
  page: number
  pageSize: number
  /** Map of column name → sort_by_column name (from model metadata) */
  sortByMap?: Record<string, string | null>
  /** All column names in the current table (for sort-by-column picker) */
  allTableColumns?: string[]
  /** Callback to set sort-by-column for a column */
  onSetSortByColumn?: (column: string, sortByColumn: string | null) => void
}

function TypeBadge({ dtype }: { dtype: string }) {
  const label = (dtype || 'unknown').toLowerCase()
  let color = 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400'
  if (/int|float|double|decimal|numeric/.test(label)) {
    color = 'bg-blue-100 text-blue-700 dark:bg-blue-900 dark:text-blue-300'
  } else if (/varchar|text|string|char/.test(label)) {
    color = 'bg-green-100 text-green-700 dark:bg-green-900 dark:text-green-300'
  } else if (/date|time|timestamp/.test(label)) {
    color = 'bg-purple-100 text-purple-700 dark:bg-purple-900 dark:text-purple-300'
  } else if (/bool/.test(label)) {
    color = 'bg-amber-100 text-amber-700 dark:bg-amber-900 dark:text-amber-300'
  }
  return (
    <span className={cn('text-[10px] px-1.5 py-0.5 rounded font-mono', color)}>
      {dtype}
    </span>
  )
}

function CompletenessBar({ value }: { value: number }) {
  return (
    <div className="w-full h-1 bg-muted rounded-full overflow-hidden mt-1" title={`${value.toFixed(1)}% complete`}>
      <div
        className={cn(
          'h-full rounded-full transition-all',
          value >= 95 ? 'bg-green-500' : value >= 70 ? 'bg-amber-500' : 'bg-red-500'
        )}
        style={{ width: `${Math.min(value, 100)}%` }}
      />
    </div>
  )
}

function CellValue({ value }: { value: unknown }) {
  const [copied, setCopied] = useState(false)

  const text = value === null || value === undefined
    ? ''
    : typeof value === 'object'
      ? JSON.stringify(value)
      : String(value)

  const isNull = value === null || value === undefined

  const handleCopy = useCallback(() => {
    if (!text) return
    navigator.clipboard.writeText(text).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 1200)
    })
  }, [text])

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span
          className={cn(
            'cursor-pointer truncate block',
            isNull && 'text-muted-foreground italic'
          )}
          onClick={handleCopy}
        >
          {isNull ? 'null' : text}
          {copied && <Check className="inline h-3 w-3 ml-1 text-green-500" />}
        </span>
      </TooltipTrigger>
      <TooltipContent side="bottom" className="max-w-xs">
        <div className="flex items-center gap-1 text-xs">
          <Copy className="h-3 w-3" /> Click to copy
        </div>
      </TooltipContent>
    </Tooltip>
  )
}

export function DataGrid({
  columns,
  rows,
  loading,
  error,
  sortColumn,
  sortDir,
  onToggleSort,
  filters,
  onSetFilter,
  selectedColumn,
  onSelectColumn,
  profile,
  filterValues,
  filterValuesLoading,
  onLoadFilterValues,
  page,
  pageSize,
  sortByMap,
  allTableColumns,
  onSetSortByColumn,
}: Props) {
  const scrollRef = useRef<HTMLDivElement>(null)
  const [filterPopoverCol, setFilterPopoverCol] = useState<string | null>(null)
  const [sortByMenuCol, setSortByMenuCol] = useState<string | null>(null)

  const getColProfile = (col: string) =>
    profile?.profiles.find(p => p.name === col) || null

  if (error) {
    return (
      <div className="flex-1 flex items-center justify-center p-4" data-testid="data-grid-error">
        <div className="text-sm text-destructive bg-destructive/10 border border-destructive rounded-md p-4 max-w-md">
          {error}
        </div>
      </div>
    )
  }

  return (
    <div className="flex-1 overflow-hidden relative" data-testid="data-grid">
      {loading && (
        <div className="absolute inset-0 bg-background/60 flex items-center justify-center z-10">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        </div>
      )}
      <div ref={scrollRef} className="overflow-auto h-full">
        <table className="w-full border-collapse text-sm">
          <thead className="sticky top-0 z-[5] bg-muted">
            <tr>
              {/* Row number header */}
              <th className="px-3 py-2 text-right text-xs font-medium text-muted-foreground border-b border-r w-12 sticky left-0 bg-muted z-[6]">
                #
              </th>
              {columns.map(col => {
                const cp = getColProfile(col)
                const isActive = filters[col] !== undefined
                const isSorted = sortColumn === col
                const isSelected = selectedColumn === col

                return (
                  <th
                    key={col}
                    className={cn(
                      'px-3 py-1.5 text-left border-b border-r min-w-[140px] max-w-[300px]',
                      'select-none',
                      isSelected && 'bg-accent/50'
                    )}
                    data-testid={`data-grid-header-${col}`}
                    onContextMenu={(e) => {
                      if (onSetSortByColumn && allTableColumns) {
                        e.preventDefault()
                        setSortByMenuCol(sortByMenuCol === col ? null : col)
                      }
                    }}
                  >
                    {/* Column name + sort */}
                    <div className="flex items-center gap-1">
                      <button
                        className="flex items-center gap-1 hover:text-foreground text-xs font-medium truncate flex-1 text-left"
                        onClick={() => onSelectColumn(isSelected ? null : col)}
                        title={col}
                      >
                        {col}
                      </button>
                      {/* Sort-by-column indicator */}
                      {sortByMap?.[col] && (
                        <Tooltip>
                          <TooltipTrigger asChild>
                            <span className="text-[9px] text-primary/70 shrink-0">↕{sortByMap[col]}</span>
                          </TooltipTrigger>
                          <TooltipContent>Sorted by: {sortByMap[col]}</TooltipContent>
                        </Tooltip>
                      )}
                      <button
                        className="shrink-0 p-0.5 rounded hover:bg-background/60"
                        onClick={() => onToggleSort(col)}
                        title={isSorted ? `Sorted ${sortDir}` : 'Sort'}
                      >
                        {isSorted && sortDir === 'asc' ? (
                          <ArrowUp className="h-3.5 w-3.5 text-primary" />
                        ) : isSorted && sortDir === 'desc' ? (
                          <ArrowDown className="h-3.5 w-3.5 text-primary" />
                        ) : (
                          <ArrowUpDown className="h-3.5 w-3.5 text-muted-foreground" />
                        )}
                      </button>
                      <div className="relative">
                        <button
                          className={cn(
                            'shrink-0 p-0.5 rounded hover:bg-background/60',
                            isActive && 'text-primary'
                          )}
                          onClick={() => {
                            setFilterPopoverCol(filterPopoverCol === col ? null : col)
                            onLoadFilterValues(col)
                          }}
                          title="Filter"
                        >
                          <Filter className={cn('h-3.5 w-3.5', isActive ? 'text-primary fill-primary/20' : 'text-muted-foreground')} />
                        </button>
                        {filterPopoverCol === col && (
                          <DataColumnFilter
                            column={col}
                            currentFilter={filters[col] || null}
                            values={filterValues}
                            valuesLoading={filterValuesLoading}
                            onSearchValues={(q) => onLoadFilterValues(col, q)}
                            onApply={(filter) => {
                              onSetFilter(col, filter)
                              setFilterPopoverCol(null)
                            }}
                            onClear={() => {
                              onSetFilter(col, null)
                              setFilterPopoverCol(null)
                            }}
                            onClose={() => setFilterPopoverCol(null)}
                          />
                        )}
                      </div>
                    </div>
                    {/* Sort-by-column context menu */}
                    {sortByMenuCol === col && onSetSortByColumn && allTableColumns && (
                      <div
                        className="absolute z-50 mt-1 w-48 bg-popover border rounded-lg shadow-lg text-xs"
                        onClick={(e) => e.stopPropagation()}
                      >
                        <div className="px-3 py-1.5 border-b font-semibold text-muted-foreground">Sort by Column</div>
                        <div className="max-h-48 overflow-auto py-1">
                          <button
                            className={cn(
                              'w-full text-left px-3 py-1 hover:bg-accent',
                              !sortByMap?.[col] && 'text-primary font-medium'
                            )}
                            onClick={() => { onSetSortByColumn(col, null); setSortByMenuCol(null) }}
                          >
                            (None — sort by self)
                          </button>
                          {allTableColumns.filter(c => c !== col).map(c => (
                            <button
                              key={c}
                              className={cn(
                                'w-full text-left px-3 py-1 hover:bg-accent truncate',
                                sortByMap?.[col] === c && 'text-primary font-medium'
                              )}
                              onClick={() => { onSetSortByColumn(col, c); setSortByMenuCol(null) }}
                            >
                              {c}
                            </button>
                          ))}
                        </div>
                      </div>
                    )}
                    {/* Type badge + completeness */}
                    {cp && (
                      <div className="mt-1">
                        <TypeBadge dtype={cp.type || 'UNKNOWN'} />
                        <CompletenessBar value={cp.completeness ?? 0} />
                      </div>
                    )}
                  </th>
                )
              })}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, rowIdx) => (
              <tr
                key={rowIdx}
                className={cn(
                  'hover:bg-accent/30 transition-colors',
                  rowIdx % 2 === 1 && 'bg-muted/30'
                )}
              >
                {/* Row number */}
                <td className="px-3 py-1.5 text-right text-xs text-muted-foreground border-r sticky left-0 bg-background font-mono tabular-nums">
                  {(page - 1) * pageSize + rowIdx + 1}
                </td>
                {columns.map(col => (
                  <td
                    key={col}
                    className={cn(
                      'px-3 py-1.5 border-r text-sm max-w-[300px]',
                      selectedColumn === col && 'bg-accent/20'
                    )}
                  >
                    <CellValue value={row[col]} />
                  </td>
                ))}
              </tr>
            ))}
            {rows.length === 0 && !loading && (
              <tr>
                <td colSpan={columns.length + 1} className="text-center py-8 text-muted-foreground text-sm">
                  No data
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}

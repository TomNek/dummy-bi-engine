/**
 * DataFooter — Status bar with row/column count, filter info,
 * page-size selector, and pagination controls.
 */
import { ChevronLeft, ChevronRight, ChevronsLeft, ChevronsRight, FilterX } from 'lucide-react'
import { Button } from '@/components/ui/button'

interface Props {
  totalRows: number
  totalColumns: number
  filterCount: number
  page: number
  pageSize: number
  totalPages: number
  onSetPage: (page: number) => void
  onSetPageSize: (size: number) => void
  onClearFilters: () => void
}

const PAGE_SIZES = [50, 100, 250, 500, 1000]

export function DataFooter({
  totalRows,
  totalColumns,
  filterCount,
  page,
  pageSize,
  totalPages,
  onSetPage,
  onSetPageSize,
  onClearFilters,
}: Props) {
  return (
    <div className="h-9 border-t px-3 flex items-center justify-between bg-muted/50 text-xs text-muted-foreground shrink-0" data-testid="data-footer">
      {/* Left: stats */}
      <div className="flex items-center gap-3">
        <span>{totalRows.toLocaleString()} rows</span>
        <span>{totalColumns} columns</span>
        {filterCount > 0 && (
          <button
            onClick={onClearFilters}
            className="flex items-center gap-1 text-primary hover:underline"
            title="Clear all filters"
          >
            <FilterX className="h-3 w-3" />
            {filterCount} filter{filterCount !== 1 ? 's' : ''}
          </button>
        )}
      </div>

      {/* Right: pagination */}
      <div className="flex items-center gap-2">
        {/* Page size */}
        <span className="text-[11px]">Rows:</span>
        <select
          value={pageSize}
          onChange={e => onSetPageSize(Number(e.target.value))}
          className="h-6 text-xs border rounded px-1 bg-background"
          data-testid="data-page-size"
        >
          {PAGE_SIZES.map(s => (
            <option key={s} value={s}>{s}</option>
          ))}
        </select>

        <span className="mx-1">
          Page {page} of {totalPages || 1}
        </span>

        <div className="flex items-center gap-0.5">
          <Button
            variant="ghost"
            size="icon"
            className="h-6 w-6"
            disabled={page <= 1}
            onClick={() => onSetPage(1)}
            title="First page"
          >
            <ChevronsLeft className="h-3.5 w-3.5" />
          </Button>
          <Button
            variant="ghost"
            size="icon"
            className="h-6 w-6"
            disabled={page <= 1}
            onClick={() => onSetPage(page - 1)}
            title="Previous page"
          >
            <ChevronLeft className="h-3.5 w-3.5" />
          </Button>
          <Button
            variant="ghost"
            size="icon"
            className="h-6 w-6"
            disabled={page >= totalPages}
            onClick={() => onSetPage(page + 1)}
            title="Next page"
          >
            <ChevronRight className="h-3.5 w-3.5" />
          </Button>
          <Button
            variant="ghost"
            size="icon"
            className="h-6 w-6"
            disabled={page >= totalPages}
            onClick={() => onSetPage(totalPages)}
            title="Last page"
          >
            <ChevronsRight className="h-3.5 w-3.5" />
          </Button>
        </div>
      </div>
    </div>
  )
}

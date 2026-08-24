/**
 * DataTableList — Sidebar listing all tables with search + metadata.
 */
import { useState, useMemo } from 'react'
import { Table2, Calculator, Search, Loader2 } from 'lucide-react'
import { Input } from '@/components/ui/input'
import { ScrollArea } from '@/components/ui/scroll-area'
import { cn } from '@/lib/utils'
import type { DataViewTableInfo } from '@/lib/api'

interface Props {
  tables: DataViewTableInfo[]
  loading: boolean
  error: string | null
  selectedTable: string | null
  onSelectTable: (name: string | null) => void
}

export function DataTableList({ tables, loading, error, selectedTable, onSelectTable }: Props) {
  const [search, setSearch] = useState('')

  const filtered = useMemo(() => {
    if (!search.trim()) return tables
    const q = search.toLowerCase()
    return tables.filter(t => t.name.toLowerCase().includes(q))
  }, [tables, search])

  return (
    <div className="w-64 border-r flex flex-col bg-background" data-testid="data-table-list">
      {/* Search */}
      <div className="p-3 border-b">
        <div className="relative">
          <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
          <Input
            placeholder="Search tables..."
            value={search}
            onChange={e => setSearch(e.target.value)}
            className="pl-8 h-9 text-sm"
            data-testid="data-table-search"
          />
        </div>
      </div>

      {/* Table list */}
      <ScrollArea className="flex-1">
        {loading && (
          <div className="flex items-center justify-center py-8" data-testid="data-table-loading">
            <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
          </div>
        )}

        {error && (
          <div className="p-3 text-sm text-destructive" data-testid="data-table-error">
            {error}
          </div>
        )}

        {!loading && !error && filtered.length === 0 && (
          <div className="p-3 text-sm text-muted-foreground" data-testid="data-table-empty">
            {search ? 'No tables match your search' : 'No tables found'}
          </div>
        )}

        <div className="p-1">
          {filtered.map(table => (
            <button
              key={table.name}
              onClick={() => onSelectTable(table.name)}
              className={cn(
                'w-full text-left px-3 py-2 rounded-md text-sm transition-colors',
                'hover:bg-accent hover:text-accent-foreground',
                'flex items-start gap-2',
                selectedTable === table.name && 'bg-accent text-accent-foreground font-medium'
              )}
              data-testid={`data-table-item-${table.name}`}
            >
              {table.is_calculated ? (
                <Calculator className="h-4 w-4 mt-0.5 shrink-0 text-amber-500" />
              ) : (
                <Table2 className="h-4 w-4 mt-0.5 shrink-0 text-blue-500" />
              )}
              <div className="min-w-0 flex-1">
                <div className="truncate">{table.name}</div>
                <div className="text-xs text-muted-foreground">
                  {table.row_count.toLocaleString()} rows · {table.column_count} cols
                </div>
              </div>
            </button>
          ))}
        </div>
      </ScrollArea>

      {/* Summary */}
      <div className="p-3 border-t text-xs text-muted-foreground" data-testid="data-table-summary">
        {tables.length} table{tables.length !== 1 ? 's' : ''}
        {search && filtered.length !== tables.length && ` (${filtered.length} shown)`}
      </div>
    </div>
  )
}

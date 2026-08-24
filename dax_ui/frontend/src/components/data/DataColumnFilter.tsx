/**
 * DataColumnFilter — Filter popover for a single column.
 * Two modes: value-based (checkboxes) and condition-based (operator + value).
 */
import { useState, useMemo, useCallback, useRef, useEffect } from 'react'
import { Search, Loader2, X } from 'lucide-react'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { ScrollArea } from '@/components/ui/scroll-area'
import { cn } from '@/lib/utils'
import type { ColumnFilter } from '@/hooks/useDataView'

interface Props {
  column: string
  currentFilter: ColumnFilter | null
  values: string[]
  valuesLoading: boolean
  onSearchValues: (query: string) => void
  onApply: (filter: ColumnFilter) => void
  onClear: () => void
  onClose: () => void
}

type FilterMode = 'values' | 'condition'

const OPERATORS = [
  { value: 'eq', label: '=' },
  { value: 'neq', label: '≠' },
  { value: 'gt', label: '>' },
  { value: 'gte', label: '≥' },
  { value: 'lt', label: '<' },
  { value: 'lte', label: '≤' },
  { value: 'contains', label: 'Contains' },
  { value: 'startswith', label: 'Starts with' },
]

export function DataColumnFilter({
  column,
  currentFilter,
  values,
  valuesLoading,
  onSearchValues,
  onApply,
  onClear,
  onClose,
}: Props) {
  const popoverRef = useRef<HTMLDivElement>(null)
  const [mode, setMode] = useState<FilterMode>(
    currentFilter?.op ? 'condition' : 'values'
  )
  const [search, setSearch] = useState('')
  const [selectedValues, setSelectedValues] = useState<Set<string>>(
    new Set(currentFilter?.values || [])
  )
  const [operator, setOperator] = useState(currentFilter?.op || 'eq')
  const [condValue, setCondValue] = useState(currentFilter?.value || '')

  // Close on click outside
  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (popoverRef.current && !popoverRef.current.contains(e.target as Node)) {
        onClose()
      }
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [onClose])

  const filteredValues = useMemo(() => {
    if (!search.trim()) return values
    const q = search.toLowerCase()
    return values.filter(v => String(v).toLowerCase().includes(q))
  }, [values, search])

  const handleSearchChange = useCallback((val: string) => {
    setSearch(val)
    onSearchValues(val)
  }, [onSearchValues])

  const toggleValue = useCallback((v: string) => {
    setSelectedValues(prev => {
      const next = new Set(prev)
      if (next.has(v)) next.delete(v)
      else next.add(v)
      return next
    })
  }, [])

  const selectAll = useCallback(() => {
    setSelectedValues(new Set(filteredValues))
  }, [filteredValues])

  const deselectAll = useCallback(() => {
    setSelectedValues(new Set())
  }, [])

  const handleApply = useCallback(() => {
    if (mode === 'values') {
      if (selectedValues.size === 0) {
        onClear()
      } else {
        onApply({ values: Array.from(selectedValues) })
      }
    } else {
      if (!condValue.trim()) {
        onClear()
      } else {
        onApply({ op: operator, value: condValue })
      }
    }
  }, [mode, selectedValues, operator, condValue, onApply, onClear])

  return (
    <div
      ref={popoverRef}
      className="absolute top-full right-0 mt-1 w-64 bg-popover border rounded-md shadow-lg z-50 p-3"
      data-testid={`data-filter-popover-${column}`}
    >
      {/* Header */}
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs font-medium truncate flex-1" title={column}>
          Filter: {column}
        </span>
        <button onClick={onClose} className="p-0.5 rounded hover:bg-accent">
          <X className="h-3.5 w-3.5" />
        </button>
      </div>

      {/* Mode tabs */}
      <div className="flex gap-1 mb-2">
        <button
          className={cn(
            'flex-1 text-xs py-1 rounded transition-colors',
            mode === 'values' ? 'bg-primary text-primary-foreground' : 'bg-muted hover:bg-accent'
          )}
          onClick={() => setMode('values')}
        >
          Values
        </button>
        <button
          className={cn(
            'flex-1 text-xs py-1 rounded transition-colors',
            mode === 'condition' ? 'bg-primary text-primary-foreground' : 'bg-muted hover:bg-accent'
          )}
          onClick={() => setMode('condition')}
        >
          Condition
        </button>
      </div>

      {mode === 'values' ? (
        <>
          {/* Search */}
          <div className="relative mb-2">
            <Search className="absolute left-2 top-2 h-3.5 w-3.5 text-muted-foreground" />
            <Input
              placeholder="Search values..."
              value={search}
              onChange={e => handleSearchChange(e.target.value)}
              className="pl-7 h-8 text-xs"
            />
          </div>

          {/* Select all / none */}
          <div className="flex gap-2 mb-1 text-xs">
            <button className="text-primary hover:underline" onClick={selectAll}>All</button>
            <button className="text-primary hover:underline" onClick={deselectAll}>None</button>
          </div>

          {/* Value list */}
          <ScrollArea className="h-40 border rounded-md">
            {valuesLoading ? (
              <div className="flex items-center justify-center py-4">
                <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
              </div>
            ) : (
              <div className="p-1 space-y-0.5">
                {filteredValues.map(v => (
                  <label
                    key={v}
                    className="flex items-center gap-2 px-2 py-1 rounded hover:bg-accent text-xs cursor-pointer"
                  >
                    <Checkbox
                      checked={selectedValues.has(v)}
                      onCheckedChange={() => toggleValue(v)}
                      className="h-3.5 w-3.5"
                    />
                    <span className="truncate">{String(v)}</span>
                  </label>
                ))}
                {filteredValues.length === 0 && !valuesLoading && (
                  <p className="text-xs text-muted-foreground py-2 text-center">No values</p>
                )}
              </div>
            )}
          </ScrollArea>
        </>
      ) : (
        <>
          {/* Operator */}
          <select
            value={operator}
            onChange={e => setOperator(e.target.value)}
            className="w-full h-8 text-xs border rounded-md px-2 mb-2 bg-background"
          >
            {OPERATORS.map(op => (
              <option key={op.value} value={op.value}>{op.label}</option>
            ))}
          </select>

          {/* Value */}
          <Input
            placeholder="Value..."
            value={condValue}
            onChange={e => setCondValue(e.target.value)}
            className="h-8 text-xs mb-2"
            onKeyDown={e => e.key === 'Enter' && handleApply()}
          />
        </>
      )}

      {/* Actions */}
      <div className="flex gap-2 mt-2">
        <Button size="sm" variant="outline" className="flex-1 h-7 text-xs" onClick={onClear}>
          Clear
        </Button>
        <Button size="sm" className="flex-1 h-7 text-xs" onClick={handleApply}>
          Apply
        </Button>
      </div>
    </div>
  )
}

import { useState, useEffect, useMemo } from 'react'
import { 
  Dialog, 
  DialogContent, 
  DialogHeader, 
  DialogTitle, 
  DialogFooter,
  DialogDescription
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { 
  Select, 
  SelectContent, 
  SelectItem, 
  SelectTrigger, 
  SelectValue 
} from '@/components/ui/select'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Loader2, Search } from 'lucide-react'
import { useAppStore } from '@/stores'
import { useFilters } from '@/hooks'

interface FilterEditorProps {
  open: boolean
  onClose: () => void
  scope: 'report' | 'page' | 'visual'
  scopeId?: string // pageId or visualId
  editFilter?: {
    id: string
    table: string
    column: string
    values: unknown[]
    operator?: string
  }
}

/** All operators supported by the backend */
const FILTER_OPERATORS = [
  { value: '=',           label: '=' },
  { value: '!=',          label: '≠' },
  { value: '>',           label: '>' },
  { value: '>=',          label: '≥' },
  { value: '<',           label: '<' },
  { value: '<=',          label: '≤' },
  { value: 'contains',    label: 'contains' },
  { value: 'startswith',  label: 'starts with' },
  { value: 'endswith',    label: 'ends with' },
  { value: 'isblank',     label: 'is blank' },
  { value: 'isnotblank',  label: 'is not blank' },
  { value: 'in',          label: 'in' },
] as const

/** Operators that don't use the values selector */
const NO_VALUES_OPERATORS = ['isblank', 'isnotblank']

export function FilterEditor({ 
  open, 
  onClose, 
  scope, 
  scopeId,
  editFilter 
}: FilterEditorProps) {
  const tables = useAppStore(s => s.tables)
  const { addNewFilter, updateFilterValues, fetchDistinctValues } = useFilters()

  const [selectedTable, setSelectedTable] = useState<string>(editFilter?.table || '')
  const [selectedColumn, setSelectedColumn] = useState<string>(editFilter?.column || '')
  const [selectedOperator, setSelectedOperator] = useState<string>(editFilter?.operator || 'in')
  const [selectedValues, setSelectedValues] = useState<Set<unknown>>(
    new Set(editFilter?.values || [])
  )
  const [distinctValues, setDistinctValues] = useState<unknown[]>([])
  const [loadingValues, setLoadingValues] = useState(false)
  const [searchTerm, setSearchTerm] = useState('')

  // Sync state when editFilter prop changes (e.g. dialog reused without remount)
  useEffect(() => {
    setSelectedTable(editFilter?.table || '')
    setSelectedColumn(editFilter?.column || '')
    setSelectedOperator(editFilter?.operator || 'in')
    setSelectedValues(new Set(editFilter?.values || []))
    setSearchTerm('')
  }, [editFilter])

  // Get columns for selected table
  const columns = useMemo(() => {
    const table = tables.find(t => t.name === selectedTable)
    return table?.columns || []
  }, [tables, selectedTable])

  // Load distinct values when column changes
  useEffect(() => {
    if (selectedTable && selectedColumn) {
      setLoadingValues(true)
      fetchDistinctValues(selectedTable, selectedColumn)
        .then(values => {
          setDistinctValues(values)
        })
        .finally(() => setLoadingValues(false))
    } else {
      setDistinctValues([])
    }
  }, [selectedTable, selectedColumn, fetchDistinctValues])

  // Filter values by search term
  const filteredValues = useMemo(() => {
    if (!searchTerm) return distinctValues
    const term = searchTerm.toLowerCase()
    return distinctValues.filter(v => 
      String(v).toLowerCase().includes(term)
    )
  }, [distinctValues, searchTerm])

  const handleTableChange = (table: string) => {
    setSelectedTable(table)
    setSelectedColumn('')
    setSelectedValues(new Set())
    setSearchTerm('')
  }

  const handleColumnChange = (column: string) => {
    setSelectedColumn(column)
    setSelectedValues(new Set())
    setSearchTerm('')
  }

  const handleValueToggle = (value: unknown) => {
    const newValues = new Set(selectedValues)
    if (newValues.has(value)) {
      newValues.delete(value)
    } else {
      newValues.add(value)
    }
    setSelectedValues(newValues)
  }

  const handleSelectAll = () => {
    setSelectedValues(new Set(filteredValues))
  }

  const handleClearAll = () => {
    setSelectedValues(new Set())
  }

  const handleSave = () => {
    const values = Array.from(selectedValues)
    
    if (editFilter) {
      // Update existing filter
      updateFilterValues(editFilter.id, values, selectedOperator)
    } else {
      // Add new filter
      addNewFilter(scope, selectedTable, selectedColumn, values, scopeId, selectedOperator)
    }
    
    onClose()
  }

  const needsValues = !NO_VALUES_OPERATORS.includes(selectedOperator)
  const isValid = selectedTable && selectedColumn && selectedOperator && (needsValues ? selectedValues.size > 0 : true)

  const scopeLabel = scope === 'report' ? 'All Pages' : scope === 'page' ? 'This Page' : 'This Visual'

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-md" data-testid="filter-editor-dialog">
        <DialogHeader>
          <DialogTitle>
            {editFilter ? 'Edit Filter' : 'Add Filter'}
          </DialogTitle>
          <DialogDescription>
            {editFilter 
              ? `Editing filter on ${editFilter.table}[${editFilter.column}]`
              : `Add a filter to ${scopeLabel.toLowerCase()}`
            }
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-4">
          {/* Table selector */}
          <div className="space-y-2">
            <Label htmlFor="filter-table">Table</Label>
            <Select 
              value={selectedTable} 
              onValueChange={handleTableChange}
            >
              <SelectTrigger id="filter-table" data-testid="filter-table-select">
                <SelectValue placeholder="Select a table" />
              </SelectTrigger>
              <SelectContent>
                {tables.map(t => (
                  <SelectItem key={t.name} value={t.name}>
                    {t.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {/* Column selector */}
          <div className="space-y-2">
            <Label htmlFor="filter-column">Column</Label>
            <Select 
              value={selectedColumn} 
              onValueChange={handleColumnChange}
              disabled={!selectedTable}
            >
              <SelectTrigger id="filter-column" data-testid="filter-column-select">
                <SelectValue placeholder="Select a column" />
              </SelectTrigger>
              <SelectContent>
                {columns.map(col => (
                  <SelectItem key={col} value={col}>
                    {col}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {/* Operator selector */}
          <div className="space-y-2">
            <Label htmlFor="filter-operator">Operator</Label>
            <Select
              value={selectedOperator}
              onValueChange={setSelectedOperator}
            >
              <SelectTrigger id="filter-operator" data-testid="filter-operator-select">
                <SelectValue placeholder="Select operator" />
              </SelectTrigger>
              <SelectContent>
                {FILTER_OPERATORS.map(op => (
                  <SelectItem key={op.value} value={op.value}>
                    {op.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {/* Values selector */}
          {selectedColumn && needsValues && (
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <Label>Values ({selectedValues.size} selected)</Label>
                <div className="flex gap-2">
                  <Button 
                    variant="ghost" 
                    size="sm" 
                    onClick={handleSelectAll}
                    className="text-xs h-7"
                  >
                    Select All
                  </Button>
                  <Button 
                    variant="ghost" 
                    size="sm" 
                    onClick={handleClearAll}
                    className="text-xs h-7"
                  >
                    Clear
                  </Button>
                </div>
              </div>

              {/* Search */}
              <div className="relative">
                <Search className="absolute left-2 top-2.5 h-4 w-4 text-muted-foreground" />
                <Input
                  placeholder="Search values..."
                  value={searchTerm}
                  onChange={e => setSearchTerm(e.target.value)}
                  className="pl-8"
                  data-testid="filter-values-search"
                />
              </div>

              {/* Values list */}
              <ScrollArea className="h-48 border rounded-md">
                {loadingValues ? (
                  <div className="flex items-center justify-center h-full">
                    <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
                  </div>
                ) : filteredValues.length === 0 ? (
                  <div className="flex items-center justify-center h-full text-muted-foreground text-sm">
                    No values found
                  </div>
                ) : (
                  <div className="p-2 space-y-1">
                    {filteredValues.map((value, i) => (
                      <label
                        key={i}
                        className="flex items-center gap-2 px-2 py-1.5 hover:bg-accent rounded cursor-pointer"
                      >
                        <Checkbox
                          checked={selectedValues.has(value)}
                          onCheckedChange={() => handleValueToggle(value)}
                          data-testid={`filter-value-${i}`}
                        />
                        <span className="text-sm truncate">
                          {value === null ? '(Blank)' : String(value)}
                        </span>
                      </label>
                    ))}
                  </div>
                )}
              </ScrollArea>
            </div>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button 
            onClick={handleSave} 
            disabled={!isValid}
            data-testid="filter-save-btn"
          >
            {editFilter ? 'Update' : 'Add Filter'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

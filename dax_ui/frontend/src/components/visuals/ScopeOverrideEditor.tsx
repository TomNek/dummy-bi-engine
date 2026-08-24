/**
 * ScopeOverrideEditor — UI for editing scope overrides on measure encodings.
 *
 * Scope overrides control the filter context for a specific measure
 * (e.g. "ignore all filters", "fix Year=2024", "remove filters on a column").
 */

import { useState } from 'react'
import { Filter, Plus, Trash2 } from 'lucide-react'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from '@/components/ui/tooltip'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type ScopeOverrideMode =
  | 'remove_all'
  | 'remove_specific'
  | 'ignore_except'
  | 'ignore_visual'
  | 'keep_intersect'
  | 'fixed_value'
  | 'cross_table'

export interface ScopeOverride {
  mode: ScopeOverrideMode
  table?: string
  column?: string
  columns?: string[]
  value?: string
  values?: string[]
  target_table?: string
  target_column?: string
}

export interface ScopeOverrideEditorProps {
  overrides: ScopeOverride[]
  onChange: (overrides: ScopeOverride[]) => void
  tables: Array<{ name: string; columns: string[] }>
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const MODE_LABELS: Record<ScopeOverrideMode, string> = {
  remove_all: 'Remove All Filters',
  remove_specific: 'Remove Column Filter',
  ignore_except: 'Keep Only These Filters',
  ignore_visual: 'Ignore Visual Filters',
  keep_intersect: 'Keep Matching Values',
  fixed_value: 'Fix Column Value',
  cross_table: 'Cross-Table Filter (TREATAS)',
}

const ALL_MODES: ScopeOverrideMode[] = [
  'remove_all',
  'remove_specific',
  'ignore_except',
  'ignore_visual',
  'keep_intersect',
  'fixed_value',
  'cross_table',
]

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Build a short human-readable label for an existing override. */
function overrideLabel(o: ScopeOverride): string {
  switch (o.mode) {
    case 'remove_all':
      return 'Remove All Filters'
    case 'remove_specific':
      return `Remove ${o.table || '?'}[${o.column || '?'}]`
    case 'ignore_except':
      return `Keep only: ${(o.columns ?? []).map(c => `${o.table || '?'}[${c}]`).join(', ') || '(none)'}`
    case 'ignore_visual':
      return 'Ignore Visual Filters'
    case 'keep_intersect':
      return `Keep matching ${o.table || '?'}[${o.column || '?'}]`
    case 'fixed_value':
      return `Fix ${o.table || '?'}[${o.column || '?'}] = ${o.value ?? '?'}`
    case 'cross_table':
      return `TREATAS → ${o.target_table || '?'}[${o.target_column || '?'}]`
    default:
      return String(o.mode)
  }
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

/** Renders a single existing override as a card with a remove button. */
function OverrideCard({
  override,
  index,
  onRemove,
}: {
  override: ScopeOverride
  index: number
  onRemove: () => void
}) {
  return (
    <div
      className="flex items-start justify-between gap-2 rounded border p-2 text-xs"
      data-testid={`scope-override-card-${index}`}
    >
      <div className="min-w-0 flex-1">
        <span className="font-medium">{MODE_LABELS[override.mode]}</span>
        <p className="text-muted-foreground truncate">{overrideLabel(override)}</p>
      </div>
      <Button
        variant="ghost"
        size="icon"
        className="h-6 w-6 shrink-0"
        onClick={onRemove}
        aria-label={`Remove override ${index}`}
        data-testid={`scope-override-remove-${index}`}
      >
        <Trash2 className="h-3 w-3" />
      </Button>
    </div>
  )
}

/** Form for adding a new override. */
function AddOverrideForm({
  tables,
  onAdd,
}: {
  tables: Array<{ name: string; columns: string[] }>
  onAdd: (o: ScopeOverride) => void
}) {
  const [mode, setMode] = useState<ScopeOverrideMode | ''>('')
  const [table, setTable] = useState('')
  const [column, setColumn] = useState('')
  const [columns, setColumns] = useState('')
  const [value, setValue] = useState('')
  const [values, setValues] = useState('')
  const [targetTable, setTargetTable] = useState('')
  const [targetColumn, setTargetColumn] = useState('')

  const selectedTable = tables.find(t => t.name === table)
  const targetTableObj = tables.find(t => t.name === targetTable)

  const reset = () => {
    setMode('')
    setTable('')
    setColumn('')
    setColumns('')
    setValue('')
    setValues('')
    setTargetTable('')
    setTargetColumn('')
  }

  const canAdd = (): boolean => {
    if (!mode) return false
    switch (mode) {
      case 'remove_all':
      case 'ignore_visual':
        return true
      case 'remove_specific':
        return !!table && !!column
      case 'ignore_except':
        return !!table && columns.trim().length > 0
      case 'keep_intersect':
        return !!table && !!column
      case 'fixed_value':
        return !!table && !!column && value.trim().length > 0
      case 'cross_table':
        return !!targetTable && !!targetColumn && values.trim().length > 0
      default:
        return false
    }
  }

  const handleAdd = () => {
    if (!mode || !canAdd()) return

    const override: ScopeOverride = { mode }

    switch (mode) {
      case 'remove_specific':
        override.table = table
        override.column = column
        break
      case 'ignore_except':
        override.table = table
        override.columns = columns.split(',').map(s => s.trim()).filter(Boolean)
        break
      case 'keep_intersect':
        override.table = table
        override.column = column
        if (values.trim()) {
          override.values = values.split(',').map(s => s.trim()).filter(Boolean)
        }
        break
      case 'fixed_value':
        override.table = table
        override.column = column
        override.value = value.trim()
        break
      case 'cross_table':
        override.target_table = targetTable
        override.target_column = targetColumn
        override.values = values.split(',').map(s => s.trim()).filter(Boolean)
        break
      // remove_all & ignore_visual need no extra fields
    }

    onAdd(override)
    reset()
  }

  // Determine which fields to show based on mode
  const needsTableColumn = ['remove_specific', 'keep_intersect', 'fixed_value'].includes(mode)
  const needsTable = needsTableColumn || mode === 'ignore_except'
  const needsColumn = needsTableColumn
  const needsColumns = mode === 'ignore_except'
  const needsValue = mode === 'fixed_value'
  const needsValues = mode === 'keep_intersect' || mode === 'cross_table'
  const needsTarget = mode === 'cross_table'

  return (
    <div className="space-y-3 rounded border border-dashed p-3" data-testid="scope-override-add-form">
      <Label className="text-xs font-medium">Add Override</Label>

      {/* Mode selector */}
      <Select
        value={mode}
        onValueChange={(v) => {
          setMode(v as ScopeOverrideMode)
          // Reset dependent fields when mode changes
          setTable('')
          setColumn('')
          setColumns('')
          setValue('')
          setValues('')
          setTargetTable('')
          setTargetColumn('')
        }}
      >
        <SelectTrigger className="h-8 text-xs" data-testid="scope-override-mode-select">
          <SelectValue placeholder="Select override mode…" />
        </SelectTrigger>
        <SelectContent>
          {ALL_MODES.map(m => (
            <SelectItem key={m} value={m} data-testid={`scope-override-mode-${m}`}>
              {MODE_LABELS[m]}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>

      {/* Table selector (shared by several modes) */}
      {needsTable && (
        <div className="space-y-1">
          <Label className="text-[10px]">Table</Label>
          <Select value={table} onValueChange={(v) => { setTable(v); setColumn(''); setColumns('') }}>
            <SelectTrigger className="h-8 text-xs" data-testid="scope-override-table-select">
              <SelectValue placeholder="Select table…" />
            </SelectTrigger>
            <SelectContent>
              {tables.map(t => (
                <SelectItem key={t.name} value={t.name}>{t.name}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      )}

      {/* Single column selector */}
      {needsColumn && (
        <div className="space-y-1">
          <Label className="text-[10px]">Column</Label>
          <Select value={column} onValueChange={setColumn} disabled={!selectedTable}>
            <SelectTrigger className="h-8 text-xs" data-testid="scope-override-column-select">
              <SelectValue placeholder="Select column…" />
            </SelectTrigger>
            <SelectContent>
              {(selectedTable?.columns ?? []).map(c => (
                <SelectItem key={c} value={c}>{c}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      )}

      {/* Multiple columns (comma-separated) */}
      {needsColumns && (
        <div className="space-y-1">
          <Label className="text-[10px]">Columns (comma-separated)</Label>
          <Input
            className="h-8 text-xs"
            placeholder="e.g. Year, Month"
            value={columns}
            onChange={(e) => setColumns(e.target.value)}
            data-testid="scope-override-columns-input"
          />
        </div>
      )}

      {/* Fixed value */}
      {needsValue && (
        <div className="space-y-1">
          <Label className="text-[10px]">Value</Label>
          <Input
            className="h-8 text-xs"
            placeholder="e.g. 2024"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            data-testid="scope-override-value-input"
          />
        </div>
      )}

      {/* Values (comma-separated) for keep_intersect and cross_table */}
      {needsValues && (
        <div className="space-y-1">
          <Label className="text-[10px]">Values (comma-separated)</Label>
          <Input
            className="h-8 text-xs"
            placeholder="e.g. 2023, 2024"
            value={values}
            onChange={(e) => setValues(e.target.value)}
            data-testid="scope-override-values-input"
          />
        </div>
      )}

      {/* Target table/column for cross_table */}
      {needsTarget && (
        <>
          <div className="space-y-1">
            <Label className="text-[10px]">Target Table</Label>
            <Select value={targetTable} onValueChange={(v) => { setTargetTable(v); setTargetColumn('') }}>
              <SelectTrigger className="h-8 text-xs" data-testid="scope-override-target-table-select">
                <SelectValue placeholder="Select target table…" />
              </SelectTrigger>
              <SelectContent>
                {tables.map(t => (
                  <SelectItem key={t.name} value={t.name}>{t.name}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1">
            <Label className="text-[10px]">Target Column</Label>
            <Select value={targetColumn} onValueChange={setTargetColumn} disabled={!targetTableObj}>
              <SelectTrigger className="h-8 text-xs" data-testid="scope-override-target-column-select">
                <SelectValue placeholder="Select target column…" />
              </SelectTrigger>
              <SelectContent>
                {(targetTableObj?.columns ?? []).map(c => (
                  <SelectItem key={c} value={c}>{c}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </>
      )}

      {/* Add button */}
      <Button
        size="sm"
        className="h-7 text-xs w-full"
        disabled={!canAdd()}
        onClick={handleAdd}
        data-testid="scope-override-add-btn"
      >
        <Plus className="h-3 w-3 mr-1" />
        Add Override
      </Button>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function ScopeOverrideEditor({ overrides, onChange, tables }: ScopeOverrideEditorProps) {
  const count = overrides.length

  const handleRemove = (index: number) => {
    const next = [...overrides]
    next.splice(index, 1)
    onChange(next)
  }

  const handleAdd = (o: ScopeOverride) => {
    onChange([...overrides, o])
  }

  return (
    <Dialog>
      <Tooltip>
        <TooltipTrigger asChild>
          <DialogTrigger asChild>
            <button
              type="button"
              className={cn(
                'relative inline-flex items-center justify-center rounded p-0.5',
                'hover:bg-muted transition-colors',
                count > 0 && 'text-primary'
              )}
              aria-label="Edit scope overrides"
              data-testid="scope-override-trigger"
            >
              <Filter className="h-3 w-3" />
              {count > 0 && (
                <span
                  className="absolute -top-1 -right-1 flex h-3.5 w-3.5 items-center justify-center rounded-full bg-primary text-[8px] font-bold text-primary-foreground"
                  data-testid="scope-override-badge"
                >
                  {count}
                </span>
              )}
            </button>
          </DialogTrigger>
        </TooltipTrigger>
        <TooltipContent side="top" className="text-xs">
          {count > 0 ? `${count} scope override(s)` : 'Add scope overrides'}
        </TooltipContent>
      </Tooltip>

      <DialogContent className="max-w-md max-h-[80vh] overflow-y-auto" data-testid="scope-override-dialog">
        <DialogHeader>
          <DialogTitle className="text-sm">Scope Overrides</DialogTitle>
        </DialogHeader>

        <div className="space-y-3 py-2">
          {/* Existing overrides */}
          {count === 0 ? (
            <p className="text-xs text-muted-foreground" data-testid="scope-override-empty">
              No overrides. This measure uses the default filter context.
            </p>
          ) : (
            <div className="space-y-2" data-testid="scope-override-list">
              {overrides.map((o, i) => (
                <OverrideCard
                  key={i}
                  override={o}
                  index={i}
                  onRemove={() => handleRemove(i)}
                />
              ))}
            </div>
          )}

          {/* Add new override */}
          <AddOverrideForm tables={tables} onAdd={handleAdd} />
        </div>
      </DialogContent>
    </Dialog>
  )
}

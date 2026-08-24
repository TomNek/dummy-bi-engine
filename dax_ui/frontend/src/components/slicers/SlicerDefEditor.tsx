import { useState, useEffect } from 'react'
import { 
  Dialog, 
  DialogContent, 
  DialogHeader, 
  DialogTitle, 
  DialogFooter,
  DialogDescription
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Checkbox } from '@/components/ui/checkbox'
import { 
  Select, 
  SelectContent, 
  SelectItem, 
  SelectTrigger, 
  SelectValue 
} from '@/components/ui/select'
import { Loader2, AlertCircle } from 'lucide-react'
import { useAppStore } from '@/stores'
import { useSlicers } from '@/hooks'
import type { SlicerDef, SlicerColumnDef, SlicerDefaults } from '@/lib/api'

interface SlicerDefEditorProps {
  open: boolean
  onClose: () => void
  editDef?: SlicerDef
}

type SlicerEditorType = NonNullable<SlicerDef['type']>

export function SlicerDefEditor({ open, onClose, editDef }: SlicerDefEditorProps) {
  const tables = useAppStore(s => s.tables)
  const measures = useAppStore(s => s.measures)
  const { saveDef } = useSlicers()

  // Form state
  const [name, setName] = useState('')
  const [selectedTable, setSelectedTable] = useState('')
  const [selectedColumn, setSelectedColumn] = useState('')
  const [syncGroup, setSyncGroup] = useState('')
  const [selectionType, setSelectionType] = useState<'single' | 'multi'>('multi')
  const [slicerType, setSlicerType] = useState<SlicerEditorType>('list')
  const [showSelectAll, setShowSelectAll] = useState(true)
  const [searchEnabled, setSearchEnabled] = useState(true)
  const [autoApply, setAutoApply] = useState(true)
  const [defaultsMode, setDefaultsMode] = useState<'none' | 'measure' | 'measure_set'>('none')
  const [defaultsApplyOnLoad, setDefaultsApplyOnLoad] = useState(true)
  const [defaultsMeasure, setDefaultsMeasure] = useState('')
  const [defaultsStartMeasure, setDefaultsStartMeasure] = useState('')
  const [defaultsEndMeasure, setDefaultsEndMeasure] = useState('')
  
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Get columns for selected table
  const columns = tables.find(t => t.name === selectedTable)?.columns || []

  // Reset form when opening with edit data
  useEffect(() => {
    if (open) {
      if (editDef) {
        setName(editDef.name)
        setSelectedTable(editDef.column.table)
        setSelectedColumn(editDef.column.column)
        setSyncGroup(editDef.sync_group || '')
        setSelectionType(editDef.selection_type || 'multi')
        setSlicerType(editDef.type || 'list')
        setShowSelectAll(editDef.show_select_all !== false)
        setSearchEnabled(editDef.search_enabled !== false)
        setAutoApply(editDef.auto_apply !== false)
        // Defaults
        const d = editDef.defaults
        setDefaultsMode(d?.mode || 'none')
        setDefaultsApplyOnLoad(d?.apply_on_load !== false)
        setDefaultsMeasure(d?.measure?.name || '')
        setDefaultsStartMeasure(d?.date_range?.start_measure?.name || '')
        setDefaultsEndMeasure(d?.date_range?.end_measure?.name || '')
      } else {
        setName('')
        setSelectedTable('')
        setSelectedColumn('')
        setSyncGroup('')
        setSelectionType('multi')
        setSlicerType('list')
        setShowSelectAll(true)
        setSearchEnabled(true)
        setAutoApply(true)
        setDefaultsMode('none')
        setDefaultsApplyOnLoad(true)
        setDefaultsMeasure('')
        setDefaultsStartMeasure('')
        setDefaultsEndMeasure('')
      }
      setError(null)
    }
  }, [open, editDef])

  // When table changes, reset column
  useEffect(() => {
    if (!editDef) {
      setSelectedColumn('')
    }
  }, [selectedTable, editDef])

  const handleSave = async () => {
    if (!name.trim() || !selectedTable || !selectedColumn) {
      setError('Name, table, and column are required')
      return
    }

    setSaving(true)
    setError(null)

    const column: SlicerColumnDef = {
      table: selectedTable,
      column: selectedColumn,
    }

    const defData: Omit<SlicerDef, 'id'> & { id?: string } = {
      ...(editDef?.id && { id: editDef.id }),
      name: name.trim(),
      column,
      ...(syncGroup.trim() && { sync_group: syncGroup.trim() }),
      selection_type: selectionType,
      type: slicerType,
      show_select_all: showSelectAll,
      search_enabled: searchEnabled,
      auto_apply: autoApply,
      style: slicerType,
    }

    // Build defaults if mode is not 'none'
    if (defaultsMode !== 'none') {
      const defaults: SlicerDefaults = {
        mode: defaultsMode,
        apply_on_load: defaultsApplyOnLoad,
      }
      // For range-like slicers, use start/end measures
      if (slicerType === 'date_range' || slicerType === 'relative_date' || slicerType === 'relative_time') {
        defaults.date_range = {}
        if (defaultsStartMeasure) {
          defaults.date_range.start_measure = { type: 'MeasureRef', name: defaultsStartMeasure }
        }
        if (defaultsEndMeasure) {
          defaults.date_range.end_measure = { type: 'MeasureRef', name: defaultsEndMeasure }
        }
      } else if (defaultsMeasure) {
        defaults.measure = { type: 'MeasureRef', name: defaultsMeasure }
      }
      defData.defaults = defaults
    }

    const result = await saveDef(defData, !editDef)
    
    if (result.success) {
      onClose()
    } else {
      setError(result.error || 'Failed to save slicer definition')
    }
    
    setSaving(false)
  }

  const isValid = name.trim() && selectedTable && selectedColumn

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-lg" data-testid="slicer-def-editor-dialog">
        <DialogHeader>
          <DialogTitle>
            {editDef ? 'Edit Slicer Definition' : 'New Slicer Definition'}
          </DialogTitle>
          <DialogDescription>
            {editDef 
              ? `Editing slicer: ${editDef.name}`
              : 'Create a slicer. Use Sync Slicers to control which pages it appears on.'
            }
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-4">
          {/* Name */}
          <div className="space-y-2">
            <Label htmlFor="slicer-name">Name *</Label>
            <Input
              id="slicer-name"
              value={name}
              onChange={e => setName(e.target.value)}
              placeholder="e.g., Product Category Slicer"
              data-testid="slicer-name-input"
            />
          </div>

          {/* Table selection */}
          <div className="space-y-2">
            <Label htmlFor="slicer-table">Table *</Label>
            <Select 
              value={selectedTable} 
              onValueChange={setSelectedTable}
            >
              <SelectTrigger id="slicer-table" data-testid="slicer-table-select">
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

          {/* Column selection */}
          <div className="space-y-2">
            <Label htmlFor="slicer-column">Column *</Label>
            <Select 
              value={selectedColumn} 
              onValueChange={setSelectedColumn}
              disabled={!selectedTable}
            >
              <SelectTrigger id="slicer-column" data-testid="slicer-column-select">
                <SelectValue placeholder={selectedTable ? "Select a column" : "Select a table first"} />
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

          {/* Sync group */}
          <div className="space-y-2">
            <Label htmlFor="slicer-sync">Sync Group (optional)</Label>
            <Input
              id="slicer-sync"
              value={syncGroup}
              onChange={e => setSyncGroup(e.target.value)}
              placeholder="e.g., date_range"
              data-testid="slicer-sync-input"
            />
            <p className="text-xs text-muted-foreground">
              Slicers in the same sync group share selections across pages.
            </p>
          </div>

          {/* Slicer display type */}
          <div className="space-y-2">
            <Label>Display Type</Label>
            <Select 
              value={slicerType} 
              onValueChange={(v) => setSlicerType(v as SlicerEditorType)}
            >
              <SelectTrigger data-testid="slicer-type-select" aria-label="Slicer display type">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="list">List</SelectItem>
                <SelectItem value="dropdown">Dropdown</SelectItem>
                <SelectItem value="button">Button</SelectItem>
                <SelectItem value="tile">Tile</SelectItem>
                <SelectItem value="input">Input</SelectItem>
                <SelectItem value="date_range">Date Range</SelectItem>
                <SelectItem value="relative_date">Relative Date</SelectItem>
                <SelectItem value="relative_time">Relative Time</SelectItem>
              </SelectContent>
            </Select>
            <p className="text-xs text-muted-foreground">
              How the slicer is displayed: as a list, dropdown, or date range picker.
            </p>
          </div>

          {/* Selection type */}
          <div className="space-y-2">
            <Label>Selection Type</Label>
            <Select 
              value={selectionType} 
              onValueChange={(v) => setSelectionType(v as 'single' | 'multi')}
            >
              <SelectTrigger data-testid="slicer-selection-type">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="multi">Multi-select</SelectItem>
                <SelectItem value="single">Single-select</SelectItem>
              </SelectContent>
            </Select>
          </div>

          {/* Options */}
          <div className="space-y-3">
            <div className="flex items-center gap-2">
              <Checkbox 
                id="show-select-all"
                checked={showSelectAll}
                onCheckedChange={(c) => setShowSelectAll(c === true)}
                data-testid="slicer-select-all-checkbox"
              />
              <Label htmlFor="show-select-all" className="font-normal">
                Show "Select All" option
              </Label>
            </div>
            
            <div className="flex items-center gap-2">
              <Checkbox 
                id="search-enabled"
                checked={searchEnabled}
                onCheckedChange={(c) => setSearchEnabled(c === true)}
                data-testid="slicer-search-checkbox"
              />
              <Label htmlFor="search-enabled" className="font-normal">
                Enable search
              </Label>
            </div>

            <div className="flex items-center gap-2">
              <Checkbox
                id="auto-apply"
                checked={autoApply}
                onCheckedChange={(c) => setAutoApply(c === true)}
                data-testid="slicer-auto-apply-checkbox"
              />
              <Label htmlFor="auto-apply" className="font-normal">
                Apply changes immediately
              </Label>
            </div>
          </div>

          {/* Slicer Defaults */}
          <div className="space-y-2">
            <Label>Default Values</Label>
            <Select
              value={defaultsMode}
              onValueChange={(v) => setDefaultsMode(v as 'none' | 'measure' | 'measure_set')}
            >
              <SelectTrigger data-testid="slicer-defaults-mode">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="none">None</SelectItem>
                <SelectItem value="measure">Measure (single value)</SelectItem>
                <SelectItem value="measure_set">Measure Set</SelectItem>
              </SelectContent>
            </Select>
            <p className="text-xs text-muted-foreground">
              Use a measure to compute default slicer values on load.
            </p>
          </div>

          {defaultsMode !== 'none' && (
            <div className="space-y-3 pl-2 border-l-2 border-muted">
              <div className="flex items-center gap-2">
                <Checkbox
                  id="defaults-apply-on-load"
                  checked={defaultsApplyOnLoad}
                  onCheckedChange={(c) => setDefaultsApplyOnLoad(c === true)}
                  data-testid="slicer-defaults-apply-on-load"
                />
                <Label htmlFor="defaults-apply-on-load" className="font-normal text-xs">
                  Apply on load
                </Label>
              </div>

              {slicerType === 'date_range' || slicerType === 'relative_date' || slicerType === 'relative_time' ? (
                <>
                  <div className="space-y-1">
                    <Label className="text-xs">Start Measure</Label>
                    <Select value={defaultsStartMeasure} onValueChange={setDefaultsStartMeasure}>
                      <SelectTrigger className="h-7 text-xs" data-testid="slicer-defaults-start-measure">
                        <SelectValue placeholder="Select measure" />
                      </SelectTrigger>
                      <SelectContent>
                        {measures.map(name => (
                          <SelectItem key={name} value={name} className="text-xs">
                            [{name}]
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="space-y-1">
                    <Label className="text-xs">End Measure</Label>
                    <Select value={defaultsEndMeasure} onValueChange={setDefaultsEndMeasure}>
                      <SelectTrigger className="h-7 text-xs" data-testid="slicer-defaults-end-measure">
                        <SelectValue placeholder="Select measure" />
                      </SelectTrigger>
                      <SelectContent>
                        {measures.map(name => (
                          <SelectItem key={name} value={name} className="text-xs">
                            [{name}]
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                </>
              ) : (
                <div className="space-y-1">
                  <Label className="text-xs">Measure</Label>
                  <Select value={defaultsMeasure} onValueChange={setDefaultsMeasure}>
                    <SelectTrigger className="h-7 text-xs" data-testid="slicer-defaults-measure">
                      <SelectValue placeholder="Select measure" />
                    </SelectTrigger>
                    <SelectContent>
                      {measures.map(name => (
                        <SelectItem key={name} value={name} className="text-xs">
                          [{name}]
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              )}
            </div>
          )}

          {/* Error */}
          {error && (
            <div className="p-2 rounded bg-red-50 text-red-700 border border-red-200 text-sm">
              <div className="flex items-start gap-2">
                <AlertCircle className="h-4 w-4 mt-0.5" />
                <span>{error}</span>
              </div>
            </div>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button 
            onClick={handleSave} 
            disabled={!isValid || saving}
            data-testid="slicer-def-save-btn"
          >
            {saving && <Loader2 className="h-4 w-4 animate-spin mr-2" />}
            {editDef ? 'Update' : 'Create'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

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
import { Textarea } from '@/components/ui/textarea'
import { DaxAutocompleteTextarea } from '@/components/ui/dax-autocomplete-textarea'
import { 
  Select, 
  SelectContent, 
  SelectItem, 
  SelectTrigger, 
  SelectValue 
} from '@/components/ui/select'
import { Loader2, AlertCircle } from 'lucide-react'
import { useAppStore } from '@/stores'
import { useModelAuthoring } from '@/hooks'
import type { CalcColumnDetail } from '@/lib/api'

interface CalcColumnEditorProps {
  open: boolean
  onClose: () => void
  editCalcColumn?: CalcColumnDetail
}

export function CalcColumnEditor({ open, onClose, editCalcColumn }: CalcColumnEditorProps) {
  const tables = useAppStore(s => s.tables)
  const { saveCalcColumn } = useModelAuthoring()

  const [table, setTable] = useState('')
  const [column, setColumn] = useState('')
  const [dax, setDax] = useState('')
  const [description, setDescription] = useState('')
  
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Reset form when opening with edit data
  useEffect(() => {
    if (open) {
      if (editCalcColumn) {
        setTable(editCalcColumn.table)
        setColumn(editCalcColumn.column)
        setDax(editCalcColumn.dax)
        setDescription(editCalcColumn.description || '')
      } else {
        setTable('')
        setColumn('')
        setDax('')
        setDescription('')
      }
      setError(null)
    }
  }, [open, editCalcColumn])

  const handleSave = async () => {
    if (!table.trim() || !column.trim() || !dax.trim()) {
      setError('Table, column name, and DAX expression are required')
      return
    }

    setSaving(true)
    setError(null)

    const calcColumnData: CalcColumnDetail = {
      table: table.trim(),
      column: column.trim(),
      dax: dax.trim(),
      ...(description.trim() && { description: description.trim() }),
    }

    const result = await saveCalcColumn(calcColumnData, !editCalcColumn)
    
    if (result.success) {
      onClose()
    } else {
      setError(result.error || 'Failed to save calculated column')
    }
    
    setSaving(false)
  }

  const isValid = table.trim() && column.trim() && dax.trim()

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-2xl" data-testid="calc-column-editor-dialog">
        <DialogHeader>
          <DialogTitle>
            {editCalcColumn ? 'Edit Calculated Column' : 'New Calculated Column'}
          </DialogTitle>
          <DialogDescription>
            {editCalcColumn 
              ? `Editing calculated column: ${editCalcColumn.table}[${editCalcColumn.column}]`
              : 'Create a new calculated column with a DAX expression'
            }
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-4">
          {/* Table selection */}
          <div className="space-y-2">
            <Label htmlFor="calccolumn-table">Table *</Label>
            <Select 
              value={table} 
              onValueChange={setTable}
              disabled={!!editCalcColumn}
            >
              <SelectTrigger id="calccolumn-table" data-testid="calccolumn-table-select">
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

          {/* Column name */}
          <div className="space-y-2">
            <Label htmlFor="calccolumn-name">Column Name *</Label>
            <Input
              id="calccolumn-name"
              value={column}
              onChange={e => setColumn(e.target.value)}
              placeholder="e.g., FullName"
              disabled={!!editCalcColumn}
              data-testid="calccolumn-name-input"
            />
          </div>

          {/* DAX Expression */}
          <div className="space-y-2">
            <Label htmlFor="calccolumn-dax">DAX Expression *</Label>
            <DaxAutocompleteTextarea
              id="calccolumn-dax"
              value={dax}
              onChange={v => setDax(v)}
              placeholder={table ? `e.g., ${table}[FirstName] & " " & ${table}[LastName]` : 'e.g., Table[Col1] & " " & Table[Col2]'}
              className="font-mono min-h-[100px]"
              data-testid="calccolumn-dax-input"
            />
            <p className="text-xs text-muted-foreground">
              Calculated columns are evaluated per-row. Reference columns from the same table using the table name prefix.
            </p>
          </div>

          {/* Description */}
          <div className="space-y-2">
            <Label htmlFor="calccolumn-description">Description</Label>
            <Textarea
              id="calccolumn-description"
              value={description}
              onChange={e => setDescription(e.target.value)}
              placeholder="Optional description..."
              className="min-h-[60px]"
              data-testid="calccolumn-description-input"
            />
          </div>

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
            data-testid="calccolumn-save-btn"
          >
            {saving && <Loader2 className="h-4 w-4 animate-spin mr-2" />}
            {editCalcColumn ? 'Update' : 'Create'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

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
import { ScrollArea } from '@/components/ui/scroll-area'
import { Loader2, Play, AlertCircle } from 'lucide-react'
import { useModelAuthoring } from '@/hooks'
import type { CalcTableDetail } from '@/lib/api'

interface CalcTableEditorProps {
  open: boolean
  onClose: () => void
  editCalcTable?: CalcTableDetail
}

export function CalcTableEditor({ open, onClose, editCalcTable }: CalcTableEditorProps) {
  const { saveCalcTable, checkCalcTable } = useModelAuthoring()

  const [name, setName] = useState('')
  const [dax, setDax] = useState('')
  const [description, setDescription] = useState('')
  
  const [saving, setSaving] = useState(false)
  const [previewing, setPreviewing] = useState(false)
  const [previewResult, setPreviewResult] = useState<{
    columns?: string[]
    rows?: Array<Record<string, unknown>>
    rowCount?: number
    error?: string
  } | null>(null)
  const [error, setError] = useState<string | null>(null)

  // Reset form when opening with edit data
  useEffect(() => {
    if (open) {
      if (editCalcTable) {
        setName(editCalcTable.name)
        setDax(editCalcTable.expression || editCalcTable.dax || '')
        setDescription(editCalcTable.description || '')
      } else {
        setName('')
        setDax('')
        setDescription('')
      }
      setPreviewResult(null)
      setError(null)
    }
  }, [open, editCalcTable])

  const handlePreview = async () => {
    if (!dax.trim()) return
    
    setPreviewing(true)
    setPreviewResult(null)
    
    const result = await checkCalcTable(dax, 20)
    if (result.success) {
      setPreviewResult({
        columns: result.columns,
        rows: result.rows,
        rowCount: result.rowCount,
      })
    } else {
      setPreviewResult({ error: result.error })
    }
    setPreviewing(false)
  }

  const handleSave = async () => {
    if (!name.trim() || !dax.trim()) {
      setError('Name and DAX expression are required')
      return
    }

    setSaving(true)
    setError(null)

    const calcTableData: CalcTableDetail = {
      name: name.trim(),
      expression: dax.trim(),
      dax: dax.trim(),
      ...(description.trim() && { description: description.trim() }),
    }

    const result = await saveCalcTable(calcTableData, !editCalcTable)
    
    if (result.success) {
      onClose()
    } else {
      setError(result.error || 'Failed to save calculated table')
    }
    
    setSaving(false)
  }

  const isValid = name.trim() && dax.trim()

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-3xl max-h-[90vh]" data-testid="calc-table-editor-dialog">
        <DialogHeader>
          <DialogTitle>
            {editCalcTable ? 'Edit Calculated Table' : 'New Calculated Table'}
          </DialogTitle>
          <DialogDescription>
            {editCalcTable 
              ? `Editing calculated table: ${editCalcTable.name}`
              : 'Create a new calculated table with a DAX expression'
            }
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-4 overflow-y-auto">
          {/* Name */}
          <div className="space-y-2">
            <Label htmlFor="calctable-name">Name *</Label>
            <Input
              id="calctable-name"
              value={name}
              onChange={e => setName(e.target.value)}
              placeholder="e.g., DateTable"
              disabled={!!editCalcTable}
              data-testid="calctable-name-input"
            />
          </div>

          {/* DAX Expression */}
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <Label htmlFor="calctable-dax">DAX Expression *</Label>
              <Button
                variant="outline"
                size="sm"
                onClick={handlePreview}
                disabled={previewing || !dax.trim()}
                data-testid="calctable-preview-btn"
              >
                {previewing ? (
                  <Loader2 className="h-4 w-4 animate-spin mr-1" />
                ) : (
                  <Play className="h-4 w-4 mr-1" />
                )}
                Preview
              </Button>
            </div>
            <DaxAutocompleteTextarea
              id="calctable-dax"
              value={dax}
              onChange={v => {
                setDax(v)
                setPreviewResult(null)
              }}
              placeholder="e.g., CALENDAR(DATE(2020,1,1), DATE(2025,12,31))"
              className="font-mono min-h-[100px]"
              data-testid="calctable-dax-input"
            />
          </div>

          {/* Preview result */}
          {previewResult && (
            <div className="space-y-2">
              <Label>Preview</Label>
              {previewResult.error ? (
                <div className="p-2 rounded bg-red-50 text-red-700 border border-red-200 text-sm">
                  <div className="flex items-start gap-2">
                    <AlertCircle className="h-4 w-4 mt-0.5" />
                    <span>{previewResult.error}</span>
                  </div>
                </div>
              ) : previewResult.columns && previewResult.rows ? (
                <div className="border rounded">
                  <div className="p-2 bg-muted text-xs text-muted-foreground">
                    {previewResult.rowCount} total rows (showing first {previewResult.rows.length})
                  </div>
                  <ScrollArea className="h-[200px]">
                    <table className="w-full text-xs">
                      <thead className="sticky top-0 bg-muted">
                        <tr>
                          {previewResult.columns.map((col) => (
                            <th key={col} className="px-2 py-1 text-left font-medium border-b">
                              {col}
                            </th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {previewResult.rows.map((row, i) => (
                          <tr key={i} className="hover:bg-muted/50">
                            {previewResult.columns!.map((col) => (
                              <td key={col} className="px-2 py-1 border-b">
                                {formatValue(row[col])}
                              </td>
                            ))}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </ScrollArea>
                </div>
              ) : null}
            </div>
          )}

          {/* Description */}
          <div className="space-y-2">
            <Label htmlFor="calctable-description">Description</Label>
            <Textarea
              id="calctable-description"
              value={description}
              onChange={e => setDescription(e.target.value)}
              placeholder="Optional description..."
              className="min-h-[60px]"
              data-testid="calctable-description-input"
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
            data-testid="calctable-save-btn"
          >
            {saving && <Loader2 className="h-4 w-4 animate-spin mr-2" />}
            {editCalcTable ? 'Update' : 'Create'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function formatValue(value: unknown): string {
  if (value === null || value === undefined) return '-'
  if (typeof value === 'number') {
    return Number.isInteger(value) 
      ? value.toLocaleString()
      : value.toLocaleString(undefined, { maximumFractionDigits: 4 })
  }
  return String(value)
}

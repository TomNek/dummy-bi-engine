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
import { Loader2, Check, AlertCircle } from 'lucide-react'
import { useModelAuthoring } from '@/hooks'
import type { MeasureDetail } from '@/lib/api'

interface MeasureEditorProps {
  open: boolean
  onClose: () => void
  editMeasure?: MeasureDetail
}

export function MeasureEditor({ open, onClose, editMeasure }: MeasureEditorProps) {
  const { saveMeasure, checkMeasure } = useModelAuthoring()

  const [name, setName] = useState('')
  const [dax, setDax] = useState('')
  const [description, setDescription] = useState('')
  const [folder, setFolder] = useState('')
  const [format, setFormat] = useState('')
  
  const [saving, setSaving] = useState(false)
  const [validating, setValidating] = useState(false)
  const [validationResult, setValidationResult] = useState<{
    valid: boolean
    error?: string
    sql?: string
  } | null>(null)
  const [error, setError] = useState<string | null>(null)

  // Reset form when opening with edit data
  useEffect(() => {
    if (open) {
      if (editMeasure) {
        setName(editMeasure.name)
        setDax(editMeasure.dax)
        setDescription(editMeasure.description || '')
        setFolder(editMeasure.folder || '')
        setFormat(editMeasure.format || '')
      } else {
        setName('')
        setDax('')
        setDescription('')
        setFolder('')
        setFormat('')
      }
      setValidationResult(null)
      setError(null)
    }
  }, [open, editMeasure])

  const handleValidate = async () => {
    if (!dax.trim()) return
    
    setValidating(true)
    setValidationResult(null)
    
    const result = await checkMeasure(dax)
    setValidationResult(result)
    setValidating(false)
  }

  const handleSave = async () => {
    if (!name.trim() || !dax.trim()) {
      setError('Name and DAX expression are required')
      return
    }

    setSaving(true)
    setError(null)

    const measureData: MeasureDetail = {
      name: name.trim(),
      dax: dax.trim(),
      ...(description.trim() && { description: description.trim() }),
      ...(folder.trim() && { folder: folder.trim() }),
      ...(format.trim() && { format: format.trim() }),
    }

    const result = await saveMeasure(measureData, !editMeasure)
    
    if (result.success) {
      onClose()
    } else {
      setError(result.error || 'Failed to save measure')
    }
    
    setSaving(false)
  }

  const isValid = name.trim() && dax.trim()

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-2xl" data-testid="measure-editor-dialog">
        <DialogHeader>
          <DialogTitle>
            {editMeasure ? 'Edit Measure' : 'New Measure'}
          </DialogTitle>
          <DialogDescription>
            {editMeasure 
              ? `Editing measure: ${editMeasure.name}`
              : 'Create a new measure with a DAX expression'
            }
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-4">
          {/* Name */}
          <div className="space-y-2">
            <Label htmlFor="measure-name">Name *</Label>
            <Input
              id="measure-name"
              value={name}
              onChange={e => setName(e.target.value)}
              placeholder="e.g., Total Sales"
              disabled={!!editMeasure}
              data-testid="measure-name-input"
            />
          </div>

          {/* DAX Expression */}
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <Label htmlFor="measure-dax">DAX Expression *</Label>
              <Button
                variant="outline"
                size="sm"
                onClick={handleValidate}
                disabled={validating || !dax.trim()}
                data-testid="measure-validate-btn"
              >
                {validating ? (
                  <Loader2 className="h-4 w-4 animate-spin mr-1" />
                ) : (
                  <Check className="h-4 w-4 mr-1" />
                )}
                Validate
              </Button>
            </div>
            <DaxAutocompleteTextarea
              id="measure-dax"
              value={dax}
              onChange={v => {
                setDax(v)
                setValidationResult(null)
              }}
              placeholder="e.g., SUM(Sales[Amount])"
              className="font-mono min-h-[120px]"
              data-testid="measure-dax-input"
            />
            
            {/* Validation result */}
            {validationResult && (
              <div className={`p-2 rounded text-sm ${validationResult.valid ? 'bg-green-50 text-green-700 border border-green-200' : 'bg-red-50 text-red-700 border border-red-200'}`}>
                {validationResult.valid ? (
                  <div className="flex items-center gap-2">
                    <Check className="h-4 w-4" />
                    <span>DAX expression is valid</span>
                  </div>
                ) : (
                  <div className="flex items-start gap-2">
                    <AlertCircle className="h-4 w-4 mt-0.5" />
                    <span>{validationResult.error}</span>
                  </div>
                )}
              </div>
            )}
          </div>

          {/* Description */}
          <div className="space-y-2">
            <Label htmlFor="measure-description">Description</Label>
            <Textarea
              id="measure-description"
              value={description}
              onChange={e => setDescription(e.target.value)}
              placeholder="Optional description..."
              className="min-h-[60px]"
              data-testid="measure-description-input"
            />
          </div>

          {/* Folder */}
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="measure-folder">Folder</Label>
              <Input
                id="measure-folder"
                value={folder}
                onChange={e => setFolder(e.target.value)}
                placeholder="e.g., Sales Measures"
                data-testid="measure-folder-input"
              />
            </div>
            
            {/* Format */}
            <div className="space-y-2">
              <Label htmlFor="measure-format">Format</Label>
              <Input
                id="measure-format"
                value={format}
                onChange={e => setFormat(e.target.value)}
                placeholder="e.g., #,##0.00"
                data-testid="measure-format-input"
              />
            </div>
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
            data-testid="measure-save-btn"
          >
            {saving && <Loader2 className="h-4 w-4 animate-spin mr-2" />}
            {editMeasure ? 'Update' : 'Create'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

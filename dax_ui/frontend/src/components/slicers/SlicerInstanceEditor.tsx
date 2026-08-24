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
import { 
  Select, 
  SelectContent, 
  SelectItem, 
  SelectTrigger, 
  SelectValue 
} from '@/components/ui/select'
import { Loader2, AlertCircle } from 'lucide-react'
import { useReportStore } from '@/stores'
import { useSlicers } from '@/hooks'
import type { SlicerInstance } from '@/lib/api'

interface SlicerInstanceEditorProps {
  open: boolean
  onClose: () => void
  editInstance?: SlicerInstance
  pageId?: string  // Pre-set the page when creating
}

export function SlicerInstanceEditor({ open, onClose, editInstance, pageId: defaultPageId }: SlicerInstanceEditorProps) {
  const pages = useReportStore(s => s.pages)
  const { slicerDefs, saveInstance, loadSlicerDefs } = useSlicers()

  // Form state
  const [defId, setDefId] = useState('')
  const [pageId, setPageId] = useState('')
  const [x, setX] = useState(0)
  const [y, setY] = useState(0)
  const [width, setWidth] = useState(200)
  const [height, setHeight] = useState(300)
  
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Load defs on mount
  useEffect(() => {
    if (open && slicerDefs.length === 0) {
      loadSlicerDefs()
    }
  }, [open, slicerDefs.length, loadSlicerDefs])

  // Reset form when opening with edit data
  useEffect(() => {
    if (open) {
      if (editInstance) {
        setDefId(editInstance.def_id)
        setPageId(editInstance.page_id)
        setX(editInstance.x ?? 0)
        setY(editInstance.y ?? 0)
        setWidth(editInstance.width ?? 200)
        setHeight(editInstance.height ?? 300)
      } else {
        setDefId('')
        setPageId(defaultPageId || (pages[0]?.id || ''))
        setX(0)
        setY(0)
        setWidth(200)
        setHeight(300)
      }
      setError(null)
    }
  }, [open, editInstance, defaultPageId, pages])

  const handleSave = async () => {
    if (!defId || !pageId) {
      setError('Slicer definition and page are required')
      return
    }

    setSaving(true)
    setError(null)

    const instanceData: Omit<SlicerInstance, 'id'> & { id?: string } = {
      ...(editInstance?.id && { id: editInstance.id }),
      def_id: defId,
      page_id: pageId,
      x,
      y,
      width,
      height,
      selected_values: editInstance?.selected_values || [],
    }

    const result = await saveInstance(instanceData, !editInstance)
    
    if (result.success) {
      onClose()
    } else {
      setError(result.error || 'Failed to save slicer instance')
    }
    
    setSaving(false)
  }

  const isValid = defId && pageId

  // All slicers are available for placement on any page
  const availableDefs = slicerDefs

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-md" data-testid="slicer-instance-editor-dialog">
        <DialogHeader>
          <DialogTitle>
            {editInstance ? 'Edit Slicer Placement' : 'Place Slicer on Page'}
          </DialogTitle>
          <DialogDescription>
            {editInstance 
              ? 'Update the slicer position and size'
              : 'Add a slicer to a page'
            }
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-4">
          {/* Page selection */}
          <div className="space-y-2">
            <Label htmlFor="instance-page">Page *</Label>
            <Select 
              value={pageId} 
              onValueChange={setPageId}
              disabled={!!editInstance}
            >
              <SelectTrigger id="instance-page" data-testid="instance-page-select">
                <SelectValue placeholder="Select a page" />
              </SelectTrigger>
              <SelectContent>
                {pages.map(p => (
                  <SelectItem key={p.id} value={p.id}>
                    {p.title}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {/* Slicer definition selection */}
          <div className="space-y-2">
            <Label htmlFor="instance-def">Slicer *</Label>
            <Select 
              value={defId} 
              onValueChange={setDefId}
              disabled={!!editInstance}
            >
              <SelectTrigger id="instance-def" data-testid="instance-def-select">
                <SelectValue placeholder={availableDefs.length ? "Select a slicer" : "No slicers available"} />
              </SelectTrigger>
              <SelectContent>
                {availableDefs.map(d => (
                  <SelectItem key={d.id} value={d.id}>
                    {d.name} ({d.column.table}[{d.column.column}])
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {slicerDefs.length === 0 && (
              <p className="text-xs text-muted-foreground">
                No slicers exist. Create one first.
              </p>
            )}
          </div>

          {/* Position */}
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="instance-x">X Position</Label>
              <Input
                id="instance-x"
                type="number"
                value={x}
                onChange={e => setX(parseInt(e.target.value) || 0)}
                data-testid="instance-x-input"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="instance-y">Y Position</Label>
              <Input
                id="instance-y"
                type="number"
                value={y}
                onChange={e => setY(parseInt(e.target.value) || 0)}
                data-testid="instance-y-input"
              />
            </div>
          </div>

          {/* Size */}
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="instance-width">Width</Label>
              <Input
                id="instance-width"
                type="number"
                value={width}
                onChange={e => setWidth(parseInt(e.target.value) || 200)}
                min={100}
                data-testid="instance-width-input"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="instance-height">Height</Label>
              <Input
                id="instance-height"
                type="number"
                value={height}
                onChange={e => setHeight(parseInt(e.target.value) || 300)}
                min={100}
                data-testid="instance-height-input"
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
            data-testid="slicer-instance-save-btn"
          >
            {saving && <Loader2 className="h-4 w-4 animate-spin mr-2" />}
            {editInstance ? 'Update' : 'Place'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

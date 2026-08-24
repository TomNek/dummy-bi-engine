/**
 * WhatIfParameterEditor - Dialog for creating/editing What-If Parameters
 */

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
import { Loader2 } from 'lucide-react'
import { useAppStore } from '@/stores'
import { updateWhatIfParameters, type WhatIfParameterDef } from '@/lib/api'

interface WhatIfParameterEditorProps {
  open: boolean
  onClose: () => void
  editParam?: { name: string; def: WhatIfParameterDef } | null
  existingDefs: Record<string, WhatIfParameterDef>
}

export function WhatIfParameterEditor({ open, onClose, editParam, existingDefs }: WhatIfParameterEditorProps) {
  const projectPath = useAppStore(s => s.projectPath)
  
  const [name, setName] = useState('')
  const [min, setMin] = useState('')
  const [max, setMax] = useState('')
  const [step, setStep] = useState('')
  const [defaultVal, setDefaultVal] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Reset form when opening
  useEffect(() => {
    if (open) {
      if (editParam) {
        setName(editParam.name)
        setMin(editParam.def.min?.toString() || '0')
        setMax(editParam.def.max?.toString() || '100')
        setStep(editParam.def.step?.toString() || '1')
        setDefaultVal(editParam.def.default?.toString() || '50')
      } else {
        setName('')
        setMin('0')
        setMax('100')
        setStep('1')
        setDefaultVal('50')
      }
      setError(null)
    }
  }, [open, editParam])

  const handleSave = async () => {
    if (!name.trim()) {
      setError('Parameter name is required')
      return
    }

    const minNum = parseFloat(min)
    const maxNum = parseFloat(max)
    const stepNum = parseFloat(step)
    const defaultNum = parseFloat(defaultVal)

    if (isNaN(minNum) || isNaN(maxNum) || isNaN(stepNum) || isNaN(defaultNum)) {
      setError('All numeric fields must be valid numbers')
      return
    }

    if (minNum >= maxNum) {
      setError('Min must be less than Max')
      return
    }

    if (stepNum <= 0) {
      setError('Step must be positive')
      return
    }

    if (defaultNum < minNum || defaultNum > maxNum) {
      setError('Default must be between Min and Max')
      return
    }

    setSaving(true)
    setError(null)

    try {
      // Build new defs map
      const newDefs = { ...existingDefs }
      
      // If editing and name changed, remove old entry
      if (editParam && editParam.name !== name.trim()) {
        delete newDefs[editParam.name]
      }

      // Add/update the parameter
      newDefs[name.trim()] = {
        min: minNum,
        max: maxNum,
        step: stepNum,
        default: defaultNum
      }

      const result = await updateWhatIfParameters(newDefs, projectPath || undefined)
      
      if (result.error) {
        setError(result.error)
      } else {
        onClose()
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async () => {
    if (!editParam) return
    
    if (!confirm(`Delete what-if parameter "${editParam.name}"?`)) return

    setSaving(true)
    setError(null)

    try {
      const newDefs = { ...existingDefs }
      delete newDefs[editParam.name]

      const result = await updateWhatIfParameters(newDefs, projectPath || undefined)
      
      if (result.error) {
        setError(result.error)
      } else {
        onClose()
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setSaving(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-md" data-testid="whatif-editor-dialog">
        <DialogHeader>
          <DialogTitle>{editParam ? 'Edit' : 'New'} What-If Parameter</DialogTitle>
          <DialogDescription>
            What-if parameters allow scenario analysis with slider controls.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-4">
          <div className="space-y-2">
            <Label htmlFor="wi-name">Parameter Name</Label>
            <Input
              id="wi-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g., Discount Rate"
              data-testid="whatif-name-input"
            />
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="wi-min">Minimum</Label>
              <Input
                id="wi-min"
                type="number"
                value={min}
                onChange={(e) => setMin(e.target.value)}
                data-testid="whatif-min-input"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="wi-max">Maximum</Label>
              <Input
                id="wi-max"
                type="number"
                value={max}
                onChange={(e) => setMax(e.target.value)}
                data-testid="whatif-max-input"
              />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="wi-step">Step</Label>
              <Input
                id="wi-step"
                type="number"
                value={step}
                onChange={(e) => setStep(e.target.value)}
                data-testid="whatif-step-input"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="wi-default">Default</Label>
              <Input
                id="wi-default"
                type="number"
                value={defaultVal}
                onChange={(e) => setDefaultVal(e.target.value)}
                data-testid="whatif-default-input"
              />
            </div>
          </div>

          {error && (
            <div className="text-sm text-destructive bg-destructive/10 p-2 rounded" data-testid="whatif-error">
              {error}
            </div>
          )}
        </div>

        <DialogFooter className="gap-2">
          {editParam && (
            <Button
              variant="destructive"
              onClick={handleDelete}
              disabled={saving}
              data-testid="whatif-delete-btn"
            >
              Delete
            </Button>
          )}
          <div className="flex-1" />
          <Button variant="outline" onClick={onClose} disabled={saving}>
            Cancel
          </Button>
          <Button onClick={handleSave} disabled={saving} data-testid="whatif-save-btn">
            {saving && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}
            Save
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

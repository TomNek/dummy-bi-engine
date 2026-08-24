/**
 * CalcGroupEditor - Dialog for creating/editing Calculation Groups
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
import { DaxAutocompleteTextarea } from '@/components/ui/dax-autocomplete-textarea'
import { Loader2, Plus, Trash2 } from 'lucide-react'
import { useAppStore } from '@/stores'
import { updateCalculationGroups, type CalcGroupDef } from '@/lib/api'

interface CalcGroupEditorProps {
  open: boolean
  onClose: () => void
  editGroup?: { name: string; def: CalcGroupDef } | null
  existingDefs: Record<string, CalcGroupDef>
}

interface ItemRow {
  name: string
  expression: string
  formatExpr: string
}

export function CalcGroupEditor({ open, onClose, editGroup, existingDefs }: CalcGroupEditorProps) {
  const projectPath = useAppStore(s => s.projectPath)
  
  const [name, setName] = useState('')
  const [precedence, setPrecedence] = useState('')
  const [items, setItems] = useState<ItemRow[]>([{ name: '', expression: '', formatExpr: '' }])
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Reset form when opening
  useEffect(() => {
    if (open) {
      if (editGroup) {
        setName(editGroup.name)
        setPrecedence(editGroup.def.precedence?.toString() || '')
        const defItems = editGroup.def.items || []
        setItems(defItems.length > 0 
          ? defItems.map(it => ({ 
              name: it.name || '', 
              expression: it.expression || '',
              formatExpr: it.format_string_expression || '',
            }))
          : [{ name: '', expression: '', formatExpr: '' }]
        )
      } else {
        setName('')
        setPrecedence('')
        setItems([{ name: '', expression: '', formatExpr: '' }])
      }
      setError(null)
    }
  }, [open, editGroup])

  const addItem = () => {
    setItems([...items, { name: '', expression: '', formatExpr: '' }])
  }

  const removeItem = (index: number) => {
    if (items.length > 1) {
      setItems(items.filter((_, i) => i !== index))
    }
  }

  const updateItem = (index: number, field: keyof ItemRow, value: string) => {
    const updated = [...items]
    updated[index] = { ...updated[index], [field]: value }
    setItems(updated)
  }

  const handleSave = async () => {
    if (!name.trim()) {
      setError('Group name is required')
      return
    }

    const validItems = items.filter(it => it.name.trim() && it.expression.trim())
    if (validItems.length === 0) {
      setError('At least one item with name and expression is required')
      return
    }

    setSaving(true)
    setError(null)

    try {
      // Build new defs map
      const newDefs = { ...existingDefs }
      
      // If editing and name changed, remove old entry
      if (editGroup && editGroup.name !== name.trim()) {
        delete newDefs[editGroup.name]
      }

      // Add/update the group
      const def: CalcGroupDef = {
        items: validItems.map(it => ({
          name: it.name.trim(),
          expression: it.expression.trim(),
          ...(it.formatExpr.trim() && { format_string_expression: it.formatExpr.trim() }),
        }))
      }
      
      if (precedence.trim()) {
        const p = parseInt(precedence.trim(), 10)
        if (!isNaN(p)) def.precedence = p
      }

      newDefs[name.trim()] = def

      const result = await updateCalculationGroups(newDefs, projectPath || undefined)
      
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
    if (!editGroup) return
    
    if (!confirm(`Delete calculation group "${editGroup.name}"?`)) return

    setSaving(true)
    setError(null)

    try {
      const newDefs = { ...existingDefs }
      delete newDefs[editGroup.name]

      const result = await updateCalculationGroups(newDefs, projectPath || undefined)
      
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
      <DialogContent className="max-w-2xl" data-testid="calc-group-editor-dialog">
        <DialogHeader>
          <DialogTitle>{editGroup ? 'Edit' : 'New'} Calculation Group</DialogTitle>
          <DialogDescription>
            Calculation groups define reusable calculations (like time intelligence).
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-4">
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="cg-name">Group Name</Label>
              <Input
                id="cg-name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="e.g., Time Intelligence"
                data-testid="calc-group-name-input"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="cg-precedence">Precedence (optional)</Label>
              <Input
                id="cg-precedence"
                type="number"
                value={precedence}
                onChange={(e) => setPrecedence(e.target.value)}
                placeholder="e.g., 10"
                data-testid="calc-group-precedence-input"
              />
            </div>
          </div>

          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <Label>Calculation Items</Label>
              <Button variant="ghost" size="sm" onClick={addItem} data-testid="calc-group-add-item">
                <Plus className="h-3 w-3 mr-1" /> Add Item
              </Button>
            </div>
            
            <div className="space-y-3 max-h-72 overflow-y-auto">
              {items.map((item, idx) => (
                <div key={idx} className="border rounded-md p-3 space-y-2">
                  <div className="flex gap-2 items-center">
                    <Input
                      value={item.name}
                      onChange={(e) => updateItem(idx, 'name', e.target.value)}
                      placeholder="Item name (e.g., YTD)"
                      className="h-8 text-sm flex-1"
                      data-testid={`calc-group-item-name-${idx}`}
                    />
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-8 w-8 text-destructive"
                      onClick={() => removeItem(idx)}
                      disabled={items.length === 1}
                      data-testid={`calc-group-remove-item-${idx}`}
                    >
                      <Trash2 className="h-3 w-3" />
                    </Button>
                  </div>
                  <DaxAutocompleteTextarea
                    value={item.expression}
                    onChange={(v) => updateItem(idx, 'expression', v)}
                    placeholder="DAX expression (e.g., CALCULATE(SELECTEDMEASURE(), DATESYTD(...)))"
                    className="text-sm font-mono min-h-[60px]"
                    data-testid={`calc-group-item-expr-${idx}`}
                  />
                  <Input
                    value={item.formatExpr}
                    onChange={(e) => updateItem(idx, 'formatExpr', e.target.value)}
                    placeholder="Format string expression (optional)"
                    className="h-7 text-xs"
                    data-testid={`calc-group-item-format-${idx}`}
                  />
                </div>
              ))}
            </div>
          </div>

          {error && (
            <div className="text-sm text-destructive bg-destructive/10 p-2 rounded">
              {error}
            </div>
          )}
        </div>

        <DialogFooter className="gap-2">
          {editGroup && (
            <Button
              variant="destructive"
              onClick={handleDelete}
              disabled={saving}
              data-testid="calc-group-delete-btn"
            >
              Delete
            </Button>
          )}
          <div className="flex-1" />
          <Button variant="outline" onClick={onClose} disabled={saving}>
            Cancel
          </Button>
          <Button onClick={handleSave} disabled={saving} data-testid="calc-group-save-btn">
            {saving && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}
            Save
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

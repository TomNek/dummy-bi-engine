/**
 * VisualCalculationsPanel — editor for per-visual DAX window calculations.
 *
 * Supports:
 * - Adding/editing/removing visual calculations (name + DAX expression)
 * - Validation against the visual's measure/dimension context
 * - Template shortcuts for common patterns (RUNNINGSUM, MOVINGAVERAGE, etc.)
 */

import { useState, useCallback } from 'react'
import { Plus, X, Check, AlertCircle, Calculator } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { ChevronDown, ChevronRight } from 'lucide-react'
import type { VisualCalculationDef } from '@/lib/api'

// Available template functions  
const VC_TEMPLATES = [
  { label: 'Running Sum', fn: 'RUNNINGSUM', template: 'RUNNINGSUM([measure])' },
  { label: 'Moving Average', fn: 'MOVINGAVERAGE', template: 'MOVINGAVERAGE([measure], 3)' },
  { label: 'Previous Value', fn: 'PREVIOUS', template: 'PREVIOUS([measure])' },
  { label: 'Next Value', fn: 'NEXT', template: 'NEXT([measure])' },
  { label: 'First Value', fn: 'FIRST', template: 'FIRST([measure])' },
  { label: 'Last Value', fn: 'LAST', template: 'LAST([measure])' },
] as const

interface VisualCalculationsPanelProps {
  calculations: VisualCalculationDef[]
  onChange: (calculations: VisualCalculationDef[]) => void
  onValidate?: (name: string, expression: string) => Promise<string | null>
}

interface EditingRow {
  index: number | null // null = new
  name: string
  expression: string
  error: string | null
}

export function VisualCalculationsPanel({
  calculations,
  onChange,
  onValidate,
}: VisualCalculationsPanelProps) {
  const [isOpen, setIsOpen] = useState(false)
  const [editing, setEditing] = useState<EditingRow | null>(null)
  const [validating, setValidating] = useState(false)

  const handleAdd = useCallback(() => {
    setEditing({ index: null, name: '', expression: '', error: null })
  }, [])

  const handleEdit = useCallback((index: number) => {
    const vc = calculations[index]
    setEditing({ index, name: vc.name, expression: vc.expression, error: null })
  }, [calculations])

  const handleRemove = useCallback((index: number) => {
    const updated = calculations.filter((_, i) => i !== index)
    onChange(updated)
  }, [calculations, onChange])

  const handleCancel = useCallback(() => {
    setEditing(null)
  }, [])

  const handleSave = useCallback(async () => {
    if (!editing) return
    const name = editing.name.trim()
    const expression = editing.expression.trim()

    if (!name) {
      setEditing({ ...editing, error: 'Name is required' })
      return
    }
    if (!expression) {
      setEditing({ ...editing, error: 'Expression is required' })
      return
    }

    // Check for duplicate names (excluding current if editing)
    const isDuplicate = calculations.some((vc, i) => {
      if (editing.index !== null && i === editing.index) return false
      return vc.name.toLowerCase() === name.toLowerCase()
    })
    if (isDuplicate) {
      setEditing({ ...editing, error: `A calculation named "${name}" already exists` })
      return
    }

    // Validate expression if validator provided
    if (onValidate) {
      setValidating(true)
      try {
        const error = await onValidate(name, expression)
        if (error) {
          setEditing({ ...editing, error })
          return
        }
      } catch (e: unknown) {
        const msg = e instanceof Error ? e.message : String(e)
        setEditing({ ...editing, error: msg })
        return
      } finally {
        setValidating(false)
      }
    }

    const newVc: VisualCalculationDef = { name, expression }
    if (editing.index !== null) {
      // Update existing
      const updated = [...calculations]
      updated[editing.index] = newVc
      onChange(updated)
    } else {
      // Add new
      onChange([...calculations, newVc])
    }
    setEditing(null)
  }, [editing, calculations, onChange, onValidate])

  const handleTemplate = useCallback((template: typeof VC_TEMPLATES[number]) => {
    setEditing({
      index: null,
      name: template.label,
      expression: template.template,
      error: null,
    })
  }, [])

  return (
    <Collapsible open={isOpen} onOpenChange={setIsOpen}>
      <CollapsibleTrigger asChild>
        <div
          className="flex items-center justify-between px-3 py-2 cursor-pointer hover:bg-accent/50"
          data-testid="visual-calculations-trigger"
        >
          <div className="flex items-center gap-2">
            {isOpen ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
            <Calculator className="h-4 w-4" />
            <span className="text-sm font-medium">Visual Calculations</span>
            {calculations.length > 0 && (
              <span className="text-xs text-muted-foreground">({calculations.length})</span>
            )}
          </div>
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                size="icon"
                variant="ghost"
                className="h-6 w-6"
                onClick={(e) => {
                  e.stopPropagation()
                  handleAdd()
                  if (!isOpen) setIsOpen(true)
                }}
                data-testid="visual-calculations-add"
              >
                <Plus className="h-3.5 w-3.5" />
              </Button>
            </TooltipTrigger>
            <TooltipContent>Add visual calculation</TooltipContent>
          </Tooltip>
        </div>
      </CollapsibleTrigger>

      <CollapsibleContent>
        <div className="px-3 pb-3 space-y-2" data-testid="visual-calculations-panel">
          {/* Existing calculations */}
          {calculations.map((vc, i) => (
            <div
              key={`${vc.name}-${i}`}
              className="flex items-center gap-2 px-2 py-1.5 rounded-md border bg-card text-xs group"
              data-testid={`visual-calculation-item-${i}`}
            >
              <Calculator className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
              <div className="flex-1 min-w-0">
                <div className="font-medium truncate">{vc.name}</div>
                <div className="text-muted-foreground truncate">{vc.expression}</div>
              </div>
              <Button
                size="icon"
                variant="ghost"
                className="h-5 w-5 opacity-0 group-hover:opacity-100 transition-opacity"
                onClick={() => handleEdit(i)}
                data-testid={`visual-calculation-edit-${i}`}
              >
                <span className="text-xs">✏️</span>
              </Button>
              <Button
                size="icon"
                variant="ghost"
                className="h-5 w-5 opacity-0 group-hover:opacity-100 transition-opacity"
                onClick={() => handleRemove(i)}
                data-testid={`visual-calculation-remove-${i}`}
              >
                <X className="h-3 w-3" />
              </Button>
            </div>
          ))}

          {/* Templates (show when no editing and no calcs) */}
          {!editing && calculations.length === 0 && (
            <div className="space-y-1">
              <p className="text-xs text-muted-foreground mb-2">
                Add window functions that operate on the visual's aggregated data.
              </p>
              <div className="flex flex-wrap gap-1">
                {VC_TEMPLATES.map((t) => (
                  <Button
                    key={t.fn}
                    variant="outline"
                    size="sm"
                    className="h-6 text-xs"
                    onClick={() => handleTemplate(t)}
                    data-testid={`vc-template-${t.fn}`}
                  >
                    {t.label}
                  </Button>
                ))}
              </div>
            </div>
          )}

          {/* Template shortcuts (show even when calcs exist, collapsed) */}
          {!editing && calculations.length > 0 && (
            <div className="flex flex-wrap gap-1">
              {VC_TEMPLATES.map((t) => (
                <Button
                  key={t.fn}
                  variant="outline"
                  size="sm"
                  className="h-5 text-[10px] px-1.5"
                  onClick={() => handleTemplate(t)}
                  data-testid={`vc-template-${t.fn}`}
                >
                  + {t.label}
                </Button>
              ))}
            </div>
          )}

          {/* Editing form */}
          {editing && (
            <div className="space-y-2 p-2 rounded-md border border-primary/50 bg-accent/20" data-testid="vc-edit-form">
              <div className="space-y-1">
                <Label className="text-xs">Name</Label>
                <Input
                  value={editing.name}
                  onChange={(e) => setEditing({ ...editing, name: e.target.value, error: null })}
                  placeholder="e.g. Running Total"
                  className="h-7 text-xs"
                  data-testid="vc-edit-name"
                  autoFocus
                />
              </div>
              <div className="space-y-1">
                <Label className="text-xs">Expression (DAX)</Label>
                <Input
                  value={editing.expression}
                  onChange={(e) => setEditing({ ...editing, expression: e.target.value, error: null })}
                  placeholder="e.g. RUNNINGSUM([Total Sales])"
                  className="h-7 text-xs font-mono"
                  data-testid="vc-edit-expression"
                />
              </div>
              {editing.error && (
                <div className="flex items-center gap-1 text-xs text-destructive" data-testid="vc-edit-error">
                  <AlertCircle className="h-3 w-3" />
                  {editing.error}
                </div>
              )}
              <div className="flex items-center gap-1 justify-end">
                <Button size="sm" variant="ghost" className="h-6 text-xs" onClick={handleCancel}>
                  Cancel
                </Button>
                <Button
                  size="sm"
                  className="h-6 text-xs"
                  onClick={handleSave}
                  disabled={validating}
                  data-testid="vc-edit-save"
                >
                  {validating ? 'Validating...' : editing.index !== null ? 'Update' : 'Add'}
                  {!validating && <Check className="h-3 w-3 ml-1" />}
                </Button>
              </div>
            </div>
          )}
        </div>
      </CollapsibleContent>
    </Collapsible>
  )
}

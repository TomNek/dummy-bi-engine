/**
 * FieldWell component for visual encodings (drop zones for fields).
 * Displays pills for assigned fields and supports drag-drop to add fields.
 */

import { useState, useCallback } from 'react'
import { X, GripVertical } from 'lucide-react'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { useMLStore } from '@/stores/ml-store'
import { ScopeOverrideEditor } from './ScopeOverrideEditor'
import type { ScopeOverride } from './ScopeOverrideEditor'

export interface FieldExpr {
  type?: string        // e.g. 'ColumnRef', 'MeasureRef', 'ExplanationRef'
  table?: string
  column?: string
  measure?: string
  name?: string          // MeasureRef uses 'name' for the measure name
  kind?: 'column' | 'measure' | 'expression'
  expression?: string
  playbook?: string      // ExplanationRef: playbook name
  edu_id?: string        // ExplanationRef: EDU identifier
  metric?: string        // ExplanationRef: metric measure name
  scope_overrides?: ScopeOverride[]  // Scope overrides for measure encodings
}

export interface SlotSpec {
  kind: 'dimension' | 'measure' | 'any'
  required: boolean
  multi: boolean
}

interface FieldPillProps {
  expr: FieldExpr
  disabled?: boolean
  onRemove?: () => void
  slotName?: string
  slotKind?: 'dimension' | 'measure' | 'any'
  tables?: Array<{ name: string; columns: string[] }>
  onUpdateScopeOverrides?: (overrides: ScopeOverride[]) => void
  /** Index of this pill within its slot (for multi-slot drag source tracking) */
  sourceIndex?: number
}

function FieldPill({ expr, disabled, onRemove, slotName, slotKind, tables, onUpdateScopeOverrides, sourceIndex }: FieldPillProps) {
  // Resolve display label from either FieldExpr format or server-side encoding format
  const isExplanation = expr.type === 'ExplanationRef'
  const isMeasure = expr.type === 'MeasureRef' || expr.kind === 'measure'
  const measureName = expr.measure || (expr.type === 'MeasureRef' ? expr.name : undefined)
  const hierarchyName = expr.type === 'HierarchyRef' ? expr.name : undefined
  const label = isExplanation
    ? `${expr.playbook || ''}/${expr.edu_id || expr.metric || '?'}`
    : measureName
      ? `[${measureName}]`
      : hierarchyName
        ? hierarchyName
        : expr.table && expr.column
          ? `${expr.table}[${expr.column}]`
          : expr.expression || expr.name || '(unknown)'

  // Build tooltip details
  const tooltipLines: string[] = []
  if (expr.type) tooltipLines.push(`Type: ${expr.type}`)
  if (expr.table) tooltipLines.push(`Table: ${expr.table}`)
  if (expr.column) tooltipLines.push(`Column: ${expr.column}`)
  if (measureName) tooltipLines.push(`Measure: ${measureName}`)
  if (hierarchyName) tooltipLines.push(`Hierarchy: ${hierarchyName}`)
  if (slotName) tooltipLines.push(`Slot: ${slotName}`)
  if (slotKind) tooltipLines.push(`Role: ${slotKind}`)
  if (isExplanation) {
    if (expr.playbook) tooltipLines.push(`Playbook: ${expr.playbook}`)
    if (expr.edu_id) tooltipLines.push(`EDU: ${expr.edu_id}`)
    if (expr.metric) tooltipLines.push(`Metric: ${expr.metric}`)
  }
  if (disabled) tooltipLines.push('⚠ Hidden by OLS')

  const handleDragStart = useCallback((e: React.DragEvent) => {
    if (disabled) {
      e.preventDefault()
      return
    }
    // Encode the field expression + source slot identification for cross-well drag
    const payload = {
      ...expr,
      _sourceSlot: slotName,
      _sourceIndex: sourceIndex ?? 0,
    }
    e.dataTransfer.setData('application/json', JSON.stringify(payload))
    e.dataTransfer.effectAllowed = 'move'
  }, [expr, slotName, sourceIndex, disabled])

  const pill = (
    <span
      className={cn(
        'inline-flex items-center gap-1 px-2 py-0.5 text-xs rounded-full',
        isExplanation
          ? 'bg-amber-100 text-amber-800'
          : 'bg-primary/10 text-primary',
        disabled && 'opacity-50 pointer-events-none'
      )}
      data-testid="field-pill"
      draggable={!disabled}
      onDragStart={handleDragStart}
    >
      {isExplanation && <span className="text-amber-500">💡</span>}
      <GripVertical className="h-3 w-3 cursor-grab" />
      <span className="truncate max-w-[120px]">
        {disabled ? `${label} (Hidden)` : label}
      </span>
      {/* Scope override editor for measure pills */}
      {isMeasure && tables && onUpdateScopeOverrides && !disabled && (
        <ScopeOverrideEditor
          overrides={expr.scope_overrides || []}
          onChange={onUpdateScopeOverrides}
          tables={tables}
        />
      )}
      {onRemove && !disabled && (
        <button
          type="button"
          className="ml-1 hover:text-destructive"
          onClick={onRemove}
          aria-label="Remove field"
          data-testid="field-pill-remove"
        >
          <X className="h-3 w-3" />
        </button>
      )}
    </span>
  )

  if (tooltipLines.length === 0) return pill

  return (
    <Tooltip>
      <TooltipTrigger asChild>{pill}</TooltipTrigger>
      <TooltipContent side="bottom" className="text-xs max-w-[250px]">
        {tooltipLines.map((line, i) => (
          <div key={i}>{line}</div>
        ))}
      </TooltipContent>
    </Tooltip>
  )
}

interface FieldWellProps {
  slotName: string
  slotSpec: SlotSpec
  values: FieldExpr | FieldExpr[] | null
  isHidden?: (expr: FieldExpr) => boolean
  onAdd?: (expr: FieldExpr) => void
  onRemove?: (index: number) => void
  onClear?: () => void
  tables?: Array<{ name: string; columns: string[] }>
  onUpdateExpr?: (index: number, expr: FieldExpr) => void
  /** Called when a pill is moved from another slot into this one */
  onMoveFromSlot?: (sourceSlot: string, sourceIndex: number, expr: FieldExpr) => void
}

export function FieldWell({
  slotName,
  slotSpec,
  values,
  isHidden,
  onAdd,
  onRemove,
  onClear,
  tables,
  onUpdateExpr,
  onMoveFromSlot,
}: FieldWellProps) {
  const [isDragOver, setIsDragOver] = useState(false)
  const [regimeNotice, setRegimeNotice] = useState<string | null>(null)
  const loadRegimeChanges = useMLStore(s => s.loadRegimeChanges)
  const hasRegimeChanges = useMLStore(s => s.hasRegimeChanges)

  // Normalize values to array for consistent rendering
  const items: FieldExpr[] = values
    ? Array.isArray(values)
      ? values
      : [values]
    : []

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault()
    setIsDragOver(true)
  }

  const handleDragLeave = () => {
    setIsDragOver(false)
  }

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setIsDragOver(false)

    const data = e.dataTransfer.getData('application/json')
    if (!data) return

    try {
      const parsed = JSON.parse(data)
      const sourceSlot = parsed._sourceSlot as string | undefined
      const sourceIndex = parsed._sourceIndex as number | undefined

      // Strip internal drag metadata before passing expression forward
      const { _sourceSlot, _sourceIndex, ...expr } = parsed as FieldExpr & { _sourceSlot?: string; _sourceIndex?: number }

      if (sourceSlot && sourceSlot !== slotName && onMoveFromSlot) {
        // Cross-well move: remove from source slot, add to this slot
        onMoveFromSlot(sourceSlot, sourceIndex ?? 0, expr)
      } else if (!sourceSlot && onAdd) {
        // External drop (from left sidebar) — normal add
        onAdd(expr)

        // Auto-detect regime changes when an ExplanationRef is dropped
        if (expr.type === 'ExplanationRef' && expr.playbook) {
          const measure = expr.metric || expr.edu_id || ''
          loadRegimeChanges(expr.playbook).then(() => {
            if (measure && hasRegimeChanges(measure)) {
              setRegimeNotice(`⚡ Regime changes detected for ${measure}. Check ML Analytics for details.`)
              setTimeout(() => setRegimeNotice(null), 6000)
            }
          }).catch(() => {
            // silently ignore
          })
        }
      } else if (onAdd) {
        // Same-slot drop or no move handler — treat as add
        onAdd(expr)
      }
    } catch {
      // Invalid JSON, ignore
    }
  }, [slotName, onAdd, onMoveFromSlot, loadRegimeChanges, hasRegimeChanges])

  // Friendly labels for IBCS and common slot names
  const slotLabels: Record<string, string> = {
    ac: 'AC (Actual)',
    py: 'PY (Prior Year)',
    pl: 'PL (Plan / Budget)',
    fc: 'FC (Forecast)',
    category: 'Category',
    x: 'X Axis',
    y: 'Y Axis',
    value: 'Value',
    values: 'Values',
    columns: 'Columns',
    rows: 'Rows',
    cols: 'Columns',
    color: 'Color',
    size: 'Size',
    tooltip: 'Tooltip',
    names: 'Names',
    facet_row: 'Facet Row',
    facet_col: 'Facet Column',
    small_multiples: 'Small Multiples',
  }
  const displayLabel = slotLabels[slotName] || slotName

  return (
    <div className="space-y-1" data-testid={`field-well-${slotName}`}>
      <div className="flex items-center justify-between">
        <span className="text-xs font-medium">{displayLabel}</span>
        <span className="text-[10px] text-muted-foreground">
          {slotSpec.kind}
          {slotSpec.required && ' *'}
          {slotSpec.multi && ' (multi)'}
        </span>
      </div>

      <div
        className={cn(
          'min-h-[32px] border rounded p-1 transition-colors',
          'flex flex-wrap gap-1 items-center',
          isDragOver && 'border-primary bg-primary/5',
          !isDragOver && 'border-dashed border-muted-foreground/30'
        )}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        data-testid={`field-well-drop-${slotName}`}
      >
        {items.length === 0 ? (
          <span className="text-[10px] text-muted-foreground px-1">
            Drop a field here
          </span>
        ) : (
          items.map((expr, index) => (
            <FieldPill
              key={index}
              expr={expr}
              disabled={isHidden?.(expr)}
              onRemove={onRemove ? () => onRemove(index) : undefined}
              slotName={slotName}
              slotKind={slotSpec.kind}
              tables={tables}
              sourceIndex={index}
              onUpdateScopeOverrides={
                onUpdateExpr
                  ? (overrides) => onUpdateExpr(index, { ...expr, scope_overrides: overrides })
                  : undefined
              }
            />
          ))
        )}
      </div>

      {/* Regime change notification */}
      {regimeNotice && (
        <div
          className="text-[10px] px-2 py-1 rounded bg-amber-50 dark:bg-amber-950/30 text-amber-700 dark:text-amber-400 border border-amber-200 dark:border-amber-800"
          data-testid={`regime-notice-${slotName}`}
        >
          {regimeNotice}
          <button
            className="ml-2 text-amber-500 hover:text-amber-700"
            onClick={() => setRegimeNotice(null)}
            aria-label="Dismiss"
          >
            ×
          </button>
        </div>
      )}

      {items.length > 0 && onClear && (
        <Button
          variant="ghost"
          size="sm"
          className="h-6 text-xs px-2"
          onClick={onClear}
          data-testid={`field-well-clear-${slotName}`}
        >
          Clear
        </Button>
      )}
    </div>
  )
}

interface EncodingsPanelProps {
  slots: Record<string, SlotSpec>
  encodings: Record<string, FieldExpr | FieldExpr[] | null>
  isHidden?: (expr: FieldExpr) => boolean
  onUpdateEncoding?: (slotName: string, value: FieldExpr | FieldExpr[] | null) => void
  tables?: Array<{ name: string; columns: string[] }>
}

export function EncodingsPanel({
  slots,
  encodings,
  isHidden,
  onUpdateEncoding,
  tables,
}: EncodingsPanelProps) {
  if (!slots || Object.keys(slots).length === 0) {
    return (
      <p className="text-xs text-muted-foreground">
        Unknown visual type.
      </p>
    )
  }

  const handleAdd = (slotName: string, slotSpec: SlotSpec, expr: FieldExpr) => {
    if (!onUpdateEncoding) return

    const current = encodings[slotName]
    if (slotSpec.multi) {
      const arr = Array.isArray(current) ? [...current] : current ? [current] : []
      arr.push(expr)
      onUpdateEncoding(slotName, arr)
    } else {
      onUpdateEncoding(slotName, expr)
    }
  }

  const handleRemove = (slotName: string, slotSpec: SlotSpec, index: number) => {
    if (!onUpdateEncoding) return

    const current = encodings[slotName]
    if (slotSpec.multi && Array.isArray(current)) {
      const arr = [...current]
      arr.splice(index, 1)
      onUpdateEncoding(slotName, arr.length > 0 ? arr : null)
    } else {
      onUpdateEncoding(slotName, null)
    }
  }

  const handleClear = (slotName: string, slotSpec: SlotSpec) => {
    if (!onUpdateEncoding) return
    onUpdateEncoding(slotName, slotSpec.multi ? [] : null)
  }

  const handleMoveFromSlot = (
    targetSlot: string,
    sourceSlot: string,
    sourceIndex: number,
    expr: FieldExpr
  ) => {
    if (!onUpdateEncoding) return
    const sourceSpec = slots[sourceSlot]
    const targetSpec = slots[targetSlot]
    if (!sourceSpec || !targetSpec) return

    // Remove from source
    const srcCurrent = encodings[sourceSlot]
    if (sourceSpec.multi && Array.isArray(srcCurrent)) {
      const arr = [...srcCurrent]
      arr.splice(sourceIndex, 1)
      onUpdateEncoding(sourceSlot, arr.length > 0 ? arr : null)
    } else {
      onUpdateEncoding(sourceSlot, null)
    }

    // Add to target
    const tgtCurrent = encodings[targetSlot]
    if (targetSpec.multi) {
      const arr = Array.isArray(tgtCurrent) ? [...tgtCurrent] : tgtCurrent ? [tgtCurrent] : []
      arr.push(expr)
      onUpdateEncoding(targetSlot, arr)
    } else {
      onUpdateEncoding(targetSlot, expr)
    }
  }

  return (
    <div className="space-y-3" data-testid="encodings-panel">
      {Object.entries(slots).map(([slotName, slotSpec]) => (
        <FieldWell
          key={slotName}
          slotName={slotName}
          slotSpec={slotSpec}
          values={encodings[slotName] ?? null}
          isHidden={isHidden}
          onAdd={(expr) => handleAdd(slotName, slotSpec, expr)}
          onRemove={(index) => handleRemove(slotName, slotSpec, index)}
          onClear={() => handleClear(slotName, slotSpec)}
          onMoveFromSlot={(srcSlot, srcIdx, expr) =>
            handleMoveFromSlot(slotName, srcSlot, srcIdx, expr)
          }
          tables={tables}
          onUpdateExpr={
            onUpdateEncoding
              ? (index, updatedExpr) => {
                  const current = encodings[slotName]
                  if (slotSpec.multi && Array.isArray(current)) {
                    const arr = [...current]
                    arr[index] = updatedExpr
                    onUpdateEncoding(slotName, arr)
                  } else {
                    onUpdateEncoding(slotName, updatedExpr)
                  }
                }
              : undefined
          }
        />
      ))}
    </div>
  )
}

/**
 * CellRulesEditor - CRUD UI for CellFormattingRule entries on a visual.
 *
 * Rules live in `visual.encodings.tablix.cellRules` (an array of rule objects).
 * This component provides a panel to list/add/edit/delete/toggle rules.
 *
 * Each rule has:
 *   id, label, enabled,
 *   match dimensions: region, role, measureId,
 *   style: bold, align, bg, fg, fontFamily, numberStyle, decimalPlaces, ibcsGraphic
 *
 * Persistence: Changes are applied in-memory (via updateVisual) and require
 * the user to click Save to persist to disk (Save-only persistence invariant).
 */

import { useCallback, useMemo, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { Separator } from '@/components/ui/separator'
import { useReportStore, useAppStore } from '@/stores'
import type { VisualInfo } from '@/lib/api'

/* ----- Types ----- */

export interface CellRuleStyle {
  bold?: boolean
  align?: 'left' | 'center' | 'right'
  bg?: string
  fg?: string
  fontFamily?: string
  numberStyle?: 'decimal' | 'currency' | 'percent'
  decimalPlaces?: number
  ibcsGraphic?: 'varianceArrow' | 'statusDot' | 'deviationBar' | 'progressBar'
}

export interface CellRule {
  id: string
  label?: string
  enabled: boolean
  region?: string
  role?: string
  measureId?: string
  style: CellRuleStyle
}

interface CellRulesEditorProps {
  visual: VisualInfo
  onClose: () => void
}

/* ----- Helpers ----- */

const REGION_OPTIONS = [
  { value: '', label: '(any)' },
  { value: 'value', label: 'Value' },
  { value: 'rowHeader', label: 'Row Header' },
  { value: 'colHeader', label: 'Col Header' },
  { value: 'subtotal', label: 'Subtotal' },
  { value: 'grandTotal', label: 'Grand Total' },
  { value: 'colBand', label: 'Col Band' },
  { value: 'rowBand', label: 'Row Band' },
]

const ROLE_OPTIONS = [
  { value: '', label: '(any)' },
  { value: 'detail', label: 'Detail' },
  { value: 'subtotal', label: 'Subtotal' },
  { value: 'grand_total', label: 'Grand Total' },
  { value: 'header', label: 'Header' },
  { value: 'band', label: 'Band' },
]

const ALIGN_OPTIONS = [
  { value: '', label: '(none)' },
  { value: 'left', label: 'Left' },
  { value: 'center', label: 'Center' },
  { value: 'right', label: 'Right' },
]

function newRuleId(): string {
  return `rule_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`
}

function createEmptyRule(): CellRule {
  return { id: newRuleId(), enabled: true, style: {} }
}

/* ----- Component ----- */

export function CellRulesEditor({ visual, onClose }: CellRulesEditorProps) {
  const updateVisual = useReportStore((s) => s.updateVisual)

  // Read current rules from visual encodings
  const rules = useMemo<CellRule[]>(() => {
    const enc = visual.encodings as Record<string, unknown> | undefined
    const tablix = (enc?.tablix ?? {}) as Record<string, unknown>
    const raw = (tablix.cellRules ?? []) as CellRule[]
    return raw.map((r) => ({
      id: r.id || newRuleId(),
      label: r.label ?? '',
      enabled: r.enabled !== false,
      region: r.region ?? '',
      role: r.role ?? '',
      measureId: r.measureId ?? '',
      style: r.style ?? {},
    }))
  }, [visual])

  const [localRules, setLocalRules] = useState<CellRule[]>(rules)
  const [editingIdx, setEditingIdx] = useState<number | null>(null)

  // Persist rules to visual encodings (in-memory only — Save commits to disk)
  const persistRules = useCallback(
    (newRules: CellRule[]) => {
      const enc = (visual.encodings ?? {}) as Record<string, unknown>
      const tablix = (enc.tablix ?? {}) as Record<string, unknown>
      // Strip empty optional fields before persisting
      const cleaned = newRules.map((r) => {
        const rule: Record<string, unknown> = {
          id: r.id,
          enabled: r.enabled,
          style: r.style,
        }
        if (r.label) rule.label = r.label
        if (r.region) rule.region = r.region
        if (r.role) rule.role = r.role
        if (r.measureId) rule.measureId = r.measureId
        return rule
      })
      updateVisual(visual.id, {
        encodings: { ...enc, tablix: { ...tablix, cellRules: cleaned } },
      } as Partial<VisualInfo>)
      useAppStore.getState().setVisualsDirty(true)
    },
    [visual, updateVisual],
  )

  const addRule = useCallback(() => {
    const r = createEmptyRule()
    const next = [...localRules, r]
    setLocalRules(next)
    setEditingIdx(next.length - 1)
    persistRules(next)
  }, [localRules, persistRules])

  const deleteRule = useCallback(
    (idx: number) => {
      const next = localRules.filter((_, i) => i !== idx)
      setLocalRules(next)
      if (editingIdx === idx) setEditingIdx(null)
      else if (editingIdx !== null && editingIdx > idx) setEditingIdx(editingIdx - 1)
      persistRules(next)
    },
    [localRules, editingIdx, persistRules],
  )

  const toggleRule = useCallback(
    (idx: number) => {
      const next = localRules.map((r, i) => (i === idx ? { ...r, enabled: !r.enabled } : r))
      setLocalRules(next)
      persistRules(next)
    },
    [localRules, persistRules],
  )

  const updateRule = useCallback(
    (idx: number, patch: Partial<CellRule>) => {
      const next = localRules.map((r, i) => (i === idx ? { ...r, ...patch } : r))
      setLocalRules(next)
      persistRules(next)
    },
    [localRules, persistRules],
  )

  const updateRuleStyle = useCallback(
    (idx: number, stylePatch: Partial<CellRuleStyle>) => {
      const next = localRules.map((r, i) =>
        i === idx ? { ...r, style: { ...r.style, ...stylePatch } } : r,
      )
      setLocalRules(next)
      persistRules(next)
    },
    [localRules, persistRules],
  )

  const moveRule = useCallback(
    (idx: number, dir: -1 | 1) => {
      const targetIdx = idx + dir
      if (targetIdx < 0 || targetIdx >= localRules.length) return
      const next = [...localRules]
      const tmp = next[idx]
      next[idx] = next[targetIdx]
      next[targetIdx] = tmp
      setLocalRules(next)
      if (editingIdx === idx) setEditingIdx(targetIdx)
      else if (editingIdx === targetIdx) setEditingIdx(idx)
      persistRules(next)
    },
    [localRules, editingIdx, persistRules],
  )

  const editingRule = editingIdx !== null ? localRules[editingIdx] : null

  return (
    <div className="flex flex-col h-full overflow-hidden" data-testid="cell-rules-editor">
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2 border-b bg-muted/30">
        <h4 className="font-medium text-sm">Cell Formatting Rules</h4>
        <Button variant="ghost" size="sm" onClick={onClose} title="Close" aria-label="Close rules editor">
          ×
        </Button>
      </div>

      <div className="flex-1 overflow-auto">
        {/* Rule list */}
        <div className="p-2 space-y-1">
          {localRules.length === 0 && (
            <p className="text-xs text-muted-foreground px-2 py-4 text-center">
              No formatting rules. Click <strong>+ Add Rule</strong> to create one.
            </p>
          )}
          {localRules.map((rule, idx) => (
            <div
              key={rule.id}
              className={`flex items-center gap-1 px-2 py-1 rounded text-xs cursor-pointer hover:bg-muted/50 ${
                editingIdx === idx ? 'bg-accent ring-1 ring-primary' : ''
              } ${!rule.enabled ? 'opacity-50' : ''}`}
              onClick={() => setEditingIdx(editingIdx === idx ? null : idx)}
              data-testid={`cell-rule-item-${idx}`}
            >
              <Switch
                checked={rule.enabled}
                onCheckedChange={() => toggleRule(idx)}
                className="scale-75"
                aria-label={`Toggle rule ${rule.label || rule.id}`}
                onClick={(e) => e.stopPropagation()}
              />
              <span className="flex-1 truncate">{rule.label || `Rule ${idx + 1}`}</span>
              <span className="text-muted-foreground text-[10px]">{rule.region || '*'}</span>
              <button
                className="px-1 hover:text-primary"
                title="Move up"
                onClick={(e) => { e.stopPropagation(); moveRule(idx, -1) }}
                disabled={idx === 0}
              >
                ↑
              </button>
              <button
                className="px-1 hover:text-primary"
                title="Move down"
                onClick={(e) => { e.stopPropagation(); moveRule(idx, 1) }}
                disabled={idx === localRules.length - 1}
              >
                ↓
              </button>
              <button
                className="px-1 hover:text-destructive"
                title="Delete rule"
                onClick={(e) => { e.stopPropagation(); deleteRule(idx) }}
                data-testid={`cell-rule-delete-${idx}`}
              >
                ✕
              </button>
            </div>
          ))}
        </div>

        <div className="px-2 pb-2">
          <Button variant="outline" size="sm" className="w-full text-xs" onClick={addRule} data-testid="cell-rule-add">
            + Add Rule
          </Button>
        </div>

        {/* Editing panel for selected rule */}
        {editingRule && editingIdx !== null && (
          <>
            <Separator />
            <div className="p-3 space-y-3" data-testid="cell-rule-edit-panel">
              {/* Label */}
              <div className="space-y-1">
                <Label className="text-xs">Label</Label>
                <Input
                  value={editingRule.label || ''}
                  onChange={(e) => updateRule(editingIdx, { label: e.target.value })}
                  className="h-7 text-xs"
                  placeholder="Rule name"
                  data-testid="cell-rule-label"
                />
              </div>

              {/* Match: Region */}
              <div className="space-y-1">
                <Label className="text-xs">Region</Label>
                <Select
                  value={editingRule.region || ''}
                  onValueChange={(v) => updateRule(editingIdx, { region: v || undefined })}
                >
                  <SelectTrigger className="h-7 text-xs" data-testid="cell-rule-region">
                    <SelectValue placeholder="(any)" />
                  </SelectTrigger>
                  <SelectContent>
                    {REGION_OPTIONS.map((o) => (
                      <SelectItem key={o.value || '_any'} value={o.value || '_any'}>
                        {o.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              {/* Match: Role */}
              <div className="space-y-1">
                <Label className="text-xs">Role</Label>
                <Select
                  value={editingRule.role || ''}
                  onValueChange={(v) => updateRule(editingIdx, { role: v || undefined })}
                >
                  <SelectTrigger className="h-7 text-xs" data-testid="cell-rule-role">
                    <SelectValue placeholder="(any)" />
                  </SelectTrigger>
                  <SelectContent>
                    {ROLE_OPTIONS.map((o) => (
                      <SelectItem key={o.value || '_any'} value={o.value || '_any'}>
                        {o.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              {/* Match: Measure ID */}
              <div className="space-y-1">
                <Label className="text-xs">Measure</Label>
                <Input
                  value={editingRule.measureId || ''}
                  onChange={(e) => updateRule(editingIdx, { measureId: e.target.value || undefined })}
                  className="h-7 text-xs"
                  placeholder="(any)"
                  data-testid="cell-rule-measure"
                />
              </div>

              <Separator />

              {/* Style: Bold */}
              <div className="flex items-center justify-between">
                <Label className="text-xs">Bold</Label>
                <Switch
                  checked={editingRule.style.bold || false}
                  onCheckedChange={(v) => updateRuleStyle(editingIdx, { bold: v || undefined })}
                  data-testid="cell-rule-bold"
                />
              </div>

              {/* Style: Align */}
              <div className="space-y-1">
                <Label className="text-xs">Alignment</Label>
                <Select
                  value={editingRule.style.align || ''}
                  onValueChange={(v) =>
                    updateRuleStyle(editingIdx, {
                      align: (v && v !== '_none' ? v : undefined) as CellRuleStyle['align'],
                    })
                  }
                >
                  <SelectTrigger className="h-7 text-xs" data-testid="cell-rule-align">
                    <SelectValue placeholder="(none)" />
                  </SelectTrigger>
                  <SelectContent>
                    {ALIGN_OPTIONS.map((o) => (
                      <SelectItem key={o.value || '_none'} value={o.value || '_none'}>
                        {o.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              {/* Style: Colors */}
              <div className="grid grid-cols-2 gap-2">
                <div className="space-y-1">
                  <Label className="text-xs">Text Color</Label>
                  <Input
                    type="color"
                    value={editingRule.style.fg || '#000000'}
                    onChange={(e) => updateRuleStyle(editingIdx, { fg: e.target.value })}
                    className="w-full h-7 p-0 border-0"
                    data-testid="cell-rule-fg"
                    aria-label="Text color"
                  />
                </div>
                <div className="space-y-1">
                  <Label className="text-xs">Background</Label>
                  <Input
                    type="color"
                    value={editingRule.style.bg || '#ffffff'}
                    onChange={(e) => updateRuleStyle(editingIdx, { bg: e.target.value })}
                    className="w-full h-7 p-0 border-0"
                    data-testid="cell-rule-bg"
                    aria-label="Background color"
                  />
                </div>
              </div>

              {/* Style: Font family */}
              <div className="space-y-1">
                <Label className="text-xs">Font Family</Label>
                <Input
                  value={editingRule.style.fontFamily || ''}
                  onChange={(e) => updateRuleStyle(editingIdx, { fontFamily: e.target.value || undefined })}
                  className="h-7 text-xs"
                  placeholder="(inherit)"
                  data-testid="cell-rule-font-family"
                />
              </div>

              {/* Style: Decimal places */}
              <div className="space-y-1">
                <Label className="text-xs">Decimal Places</Label>
                <Input
                  type="number"
                  min={0}
                  max={10}
                  value={editingRule.style.decimalPlaces ?? ''}
                  onChange={(e) =>
                    updateRuleStyle(editingIdx, {
                      decimalPlaces: e.target.value ? parseInt(e.target.value) : undefined,
                    })
                  }
                  className="h-7 text-xs"
                  placeholder="(default)"
                  data-testid="cell-rule-decimals"
                />
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  )
}

export default CellRulesEditor

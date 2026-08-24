import { useEffect, useMemo, useState } from 'react'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { detectRelationshipCardinality, type TableInfo, type RelationshipDef } from '@/lib/api'
import { useAppStore } from '@/stores'

interface RelationshipEditorDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  tables: TableInfo[]
  initial?: Partial<RelationshipDef>
  title?: string
  description?: string
  submitLabel?: string
  onSubmit: (payload: Omit<RelationshipDef, 'rel_id'> & { rel_id?: string }) => Promise<void>
}

export function RelationshipEditorDialog({
  open,
  onOpenChange,
  tables,
  initial,
  title = 'Create Relationship',
  description = 'Define the source and target columns for this relationship.',
  submitLabel = 'Create',
  onSubmit,
}: RelationshipEditorDialogProps) {
  const projectPath = useAppStore(s => s.projectPath)

  const [fromTable, setFromTable] = useState('')
  const [fromColumn, setFromColumn] = useState('')
  const [toTable, setToTable] = useState('')
  const [toColumn, setToColumn] = useState('')
  const [crossFilterDirection, setCrossFilterDirection] = useState<'single' | 'both'>('single')
  const [cardinality, setCardinality] = useState('')
  const [detectedCardinality, setDetectedCardinality] = useState<string | null>(null)
  const [enforceDetectedCardinality, setEnforceDetectedCardinality] = useState(true)
  const [detectingCardinality, setDetectingCardinality] = useState(false)
  const [active, setActive] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [detectError, setDetectError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (!open) return
    setFromTable(initial?.from_table ?? '')
    setFromColumn(initial?.from_column ?? '')
    setToTable(initial?.to_table ?? '')
    setToColumn(initial?.to_column ?? '')
    setCrossFilterDirection((initial?.cross_filter_direction as 'single' | 'both') ?? 'single')
    const initialCardinality = (initial?.cardinality ?? '').trim()
    setCardinality(initialCardinality)
    setDetectedCardinality(initial?.cardinality ?? null)
    setEnforceDetectedCardinality(true)
    setDetectingCardinality(false)
    setActive(initial?.active ?? true)
    setError(null)
    setDetectError(null)
    setSaving(false)
  }, [open, initial])

  const sortedTables = useMemo(
    () => [...(tables ?? [])].sort((a, b) => a.name.localeCompare(b.name)),
    [tables]
  )

  const fromColumns = useMemo(() => {
    const table = sortedTables.find(t => t.name === fromTable)
    return table?.columns ?? []
  }, [sortedTables, fromTable])

  const toColumns = useMemo(() => {
    const table = sortedTables.find(t => t.name === toTable)
    return table?.columns ?? []
  }, [sortedTables, toTable])

  const canSubmit = Boolean(fromTable && fromColumn && toTable && toColumn && cardinality) && !saving
  const canDetect = Boolean(fromTable && fromColumn && toTable && toColumn) && !detectingCardinality

  async function runCardinalityDetection(): Promise<string> {
    if (!canDetect) {
      throw new Error('Select both tables and columns to detect cardinality.')
    }

    setDetectingCardinality(true)
    setDetectError(null)
    try {
      const result = await detectRelationshipCardinality(
        {
          from_table: fromTable,
          from_column: fromColumn,
          to_table: toTable,
          to_column: toColumn,
        },
        projectPath ?? undefined,
      )
      if (result.error || !result.data) {
        throw new Error(result.error || 'Failed to detect cardinality')
      }

      const detected = result.data.cardinality || ''
      setDetectedCardinality(detected || null)
      if (detected) {
        setCardinality(detected)
        return detected
      }
      throw new Error('No cardinality could be detected for the selected columns.')
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Failed to detect cardinality'
      setDetectError(msg)
      throw new Error(msg)
    } finally {
      setDetectingCardinality(false)
    }
  }

  async function handleDetectCardinality() {
    try {
      await runCardinalityDetection()
    } catch {
      // Error is already surfaced via detectError.
    }
  }

  async function handleSubmit() {
    if (!canSubmit) {
      setError('Please select both tables/columns and a cardinality.')
      return
    }

    let effectiveDetected = detectedCardinality
    if (enforceDetectedCardinality && !effectiveDetected) {
      try {
        effectiveDetected = await runCardinalityDetection()
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to detect cardinality during Create.')
        return
      }
    }

    if (enforceDetectedCardinality) {
      if (!effectiveDetected) {
        setError('Cardinality enforcement is enabled but no detected value is available.')
        return
      }
      if (cardinality !== effectiveDetected) {
        setError(`Selected cardinality (${cardinality}) differs from detected (${effectiveDetected}). Disable enforce or use detected value.`)
        return
      }
    }

    if (detectError) {
      setError(detectError)
      return
    }
    setSaving(true)
    setError(null)
    try {
      await onSubmit({
        rel_id: initial?.rel_id,
        from_table: fromTable,
        from_column: fromColumn,
        to_table: toTable,
        to_column: toColumn,
        active,
        cross_filter_direction: crossFilterDirection,
        cardinality,
      })
      onOpenChange(false)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save relationship')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent data-testid="relationship-editor-dialog">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>{description}</DialogDescription>
        </DialogHeader>

        <div className="space-y-3">
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label htmlFor="rel-from-table">From table</Label>
              <Select value={fromTable} onValueChange={(value) => { setFromTable(value); setFromColumn('') }}>
                <SelectTrigger id="rel-from-table" data-testid="relationship-from-table">
                  <SelectValue placeholder="Select table" />
                </SelectTrigger>
                <SelectContent>
                  {sortedTables.map((table) => (
                    <SelectItem key={table.name} value={table.name}>{table.name}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="rel-from-column">From column</Label>
              <Select value={fromColumn} onValueChange={setFromColumn} disabled={!fromTable}>
                <SelectTrigger id="rel-from-column" data-testid="relationship-from-column">
                  <SelectValue placeholder="Select column" />
                </SelectTrigger>
                <SelectContent>
                  {fromColumns.map((col) => (
                    <SelectItem key={col} value={col}>{col}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label htmlFor="rel-to-table">To table</Label>
              <Select value={toTable} onValueChange={(value) => { setToTable(value); setToColumn('') }}>
                <SelectTrigger id="rel-to-table" data-testid="relationship-to-table">
                  <SelectValue placeholder="Select table" />
                </SelectTrigger>
                <SelectContent>
                  {sortedTables.map((table) => (
                    <SelectItem key={table.name} value={table.name}>{table.name}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="rel-to-column">To column</Label>
              <Select value={toColumn} onValueChange={setToColumn} disabled={!toTable}>
                <SelectTrigger id="rel-to-column" data-testid="relationship-to-column">
                  <SelectValue placeholder="Select column" />
                </SelectTrigger>
                <SelectContent>
                  {toColumns.map((col) => (
                    <SelectItem key={col} value={col}>{col}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label htmlFor="rel-direction">Cross-filter direction</Label>
              <Select value={crossFilterDirection} onValueChange={(value) => setCrossFilterDirection(value as 'single' | 'both')}>
                <SelectTrigger id="rel-direction" data-testid="relationship-direction">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="single">Single</SelectItem>
                  <SelectItem value="both">Both (bi-directional)</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="rel-cardinality">Cardinality (required)</Label>
              <Select value={cardinality} onValueChange={setCardinality}>
                <SelectTrigger id="rel-cardinality" data-testid="relationship-cardinality">
                  <SelectValue placeholder="Select cardinality" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="one_to_one">1:1</SelectItem>
                  <SelectItem value="one_to_many">1:n</SelectItem>
                  <SelectItem value="many_to_one">n:1</SelectItem>
                  <SelectItem value="many_to_many">n:n</SelectItem>
                </SelectContent>
              </Select>
              <div className="flex items-center gap-2 pt-1">
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  className="h-7 text-xs"
                  disabled={!canDetect}
                  onClick={() => void handleDetectCardinality()}
                  data-testid="relationship-detect-cardinality-btn"
                >
                  {detectingCardinality ? 'Detecting…' : 'Auto-detect'}
                </Button>
                <span className="text-[11px] text-muted-foreground" data-testid="relationship-detected-cardinality">
                  {detectedCardinality ? `Detected: ${detectedCardinality}` : 'No detected value yet'}
                </span>
              </div>
              <div className="flex items-center gap-2 pt-1">
                <input
                  id="rel-enforce-detected-cardinality"
                  type="checkbox"
                  checked={enforceDetectedCardinality}
                  onChange={(e) => setEnforceDetectedCardinality(e.target.checked)}
                  data-testid="relationship-enforce-detected-cardinality"
                  aria-label="Enforce detected cardinality"
                />
                <Label htmlFor="rel-enforce-detected-cardinality">Enforce auto-detected cardinality</Label>
              </div>
              {detectError && (
                <div className="text-xs text-destructive" data-testid="relationship-detect-error">
                  {detectError}
                </div>
              )}
              <div className="text-[11px] text-muted-foreground" data-testid="relationship-join-helper-text">
                Join behavior currently stays LEFT JOIN. Cardinality and cross-filter direction control filter propagation, not SQL join type.
              </div>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <input
              id="rel-active"
              type="checkbox"
              checked={active}
              onChange={(e) => setActive(e.target.checked)}
              data-testid="relationship-active"
              aria-label="Relationship active"
            />
            <Label htmlFor="rel-active">Active</Label>
          </div>

          {error && (
            <div className="text-xs text-destructive" data-testid="relationship-editor-error">
              {error}
            </div>
          )}
        </div>

        <DialogFooter>
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)} data-testid="relationship-cancel-btn">
            Cancel
          </Button>
          <Button type="button" onClick={handleSubmit} disabled={!canSubmit} data-testid="relationship-save-btn">
            {saving ? 'Saving…' : submitLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

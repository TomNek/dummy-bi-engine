/**
 * DataTypeEditor — Right-click context menu / inline editor for column data types.
 * Lets users change the data type and decimal places for a column.
 */
import { useState, useEffect, useRef } from 'react'
import { Button } from '@/components/ui/button'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { setColumnDataType } from '@/lib/api'
import { useAppStore } from '@/stores'

const DATA_TYPES = [
  { value: 'VARCHAR', label: 'Text' },
  { value: 'INTEGER', label: 'Whole Number' },
  { value: 'BIGINT', label: 'Whole Number (64-bit)' },
  { value: 'DOUBLE', label: 'Decimal Number' },
  { value: 'DECIMAL', label: 'Fixed Decimal' },
  { value: 'BOOLEAN', label: 'True / False' },
  { value: 'DATE', label: 'Date' },
  { value: 'TIMESTAMP', label: 'Date/Time' },
] as const

const NUMERIC_TYPES = new Set(['DOUBLE', 'DECIMAL', 'FLOAT'])

interface DataTypeEditorProps {
  table: string
  column: string
  currentType?: string
  position: { x: number; y: number }
  onClose: () => void
  onSaved?: (newType: string) => void
}

export function DataTypeEditor({ table, column, currentType, position, onClose, onSaved }: DataTypeEditorProps) {
  const projectPath = useAppStore(s => s.projectPath)
  const [dataType, setDataType] = useState(currentType?.toUpperCase() || 'VARCHAR')
  const [decimalPlaces, setDecimalPlaces] = useState<number | null>(null)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const ref = useRef<HTMLDivElement>(null)

  // Close on click outside — but ignore clicks inside Radix portals (e.g. Select dropdown)
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      const target = e.target as Node
      if (ref.current && !ref.current.contains(target)) {
        // Radix Select renders its dropdown in a portal. Don't close if
        // the click lands inside a Radix popper/select-content wrapper.
        const el = target instanceof Element ? target : target.parentElement
        if (el?.closest('[data-radix-popper-content-wrapper]')) return
        onClose()
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [onClose])

  // Close on Escape
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [onClose])

  const isNumeric = NUMERIC_TYPES.has(dataType)

  const handleSave = async () => {
    setSaving(true)
    setError(null)
    const res = await setColumnDataType(table, column, dataType, isNumeric ? decimalPlaces : null, projectPath || undefined)
    setSaving(false)
    if (res.error) {
      setError(res.error)
      return
    }
    onSaved?.(dataType)
    onClose()
  }

  // Position the popover so it doesn't overflow the viewport
  const style: React.CSSProperties = {
    position: 'fixed',
    left: Math.min(position.x, window.innerWidth - 280),
    top: Math.min(position.y, window.innerHeight - 280),
    zIndex: 9999,
  }

  return (
    <div
      ref={ref}
      className="w-64 bg-popover border rounded-lg shadow-xl p-3 space-y-3"
      style={style}
      onClick={(e) => e.stopPropagation()}
      data-testid="data-type-editor"
    >
      <div className="text-xs font-semibold text-muted-foreground truncate" title={`${table}[${column}]`}>
        {table}[{column}]
      </div>

      <div className="space-y-1.5">
        <Label className="text-xs">Data Type</Label>
        <Select value={dataType} onValueChange={setDataType}>
          <SelectTrigger className="h-8 text-xs" data-testid="data-type-select">
            <SelectValue />
          </SelectTrigger>
          <SelectContent className="z-[10000]">
            {DATA_TYPES.map(dt => (
              <SelectItem key={dt.value} value={dt.value} className="text-xs">
                {dt.label} ({dt.value})
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {isNumeric && (
        <div className="space-y-1.5">
          <Label className="text-xs">Decimal Places</Label>
          <Input
            type="number"
            min={0}
            max={10}
            value={decimalPlaces ?? ''}
            onChange={(e) => setDecimalPlaces(e.target.value === '' ? null : Number(e.target.value))}
            className="h-8 text-xs"
            placeholder="Auto"
            data-testid="decimal-places-input"
          />
        </div>
      )}

      {error && (
        <div className="text-xs text-destructive">{error}</div>
      )}

      <div className="flex gap-2 justify-end">
        <Button variant="ghost" size="sm" className="h-7 text-xs" onClick={onClose}>
          Cancel
        </Button>
        <Button size="sm" className="h-7 text-xs" onClick={handleSave} disabled={saving}>
          {saving ? 'Saving…' : 'Apply'}
        </Button>
      </div>
    </div>
  )
}

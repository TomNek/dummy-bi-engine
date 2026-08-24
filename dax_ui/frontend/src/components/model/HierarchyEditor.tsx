import { useState, useEffect, useMemo } from 'react'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Plus, Trash2 } from 'lucide-react'
import type { HierarchyDef, HierarchiesMap } from '@/lib/api'

interface HierarchyEditorProps {
  open: boolean
  onClose: () => void
  editHierarchy?: { name: string; def: HierarchyDef } | null
  existingHierarchies: HierarchiesMap
  tables: Array<{ name: string; columns: string[] }>
  onApply: (name: string, def: HierarchyDef, previousName?: string) => void
}

interface LevelRow {
  column: string
  name: string
}

export function HierarchyEditor({
  open,
  onClose,
  editHierarchy,
  existingHierarchies,
  tables,
  onApply,
}: HierarchyEditorProps) {
  const [name, setName] = useState('')
  const [table, setTable] = useState('')
  const [levels, setLevels] = useState<LevelRow[]>([])
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!open) return

    if (editHierarchy) {
      setName(editHierarchy.name)
      setTable(editHierarchy.def.table)
      setLevels(editHierarchy.def.levels.map(l => ({ column: l.column, name: l.name || l.column })))
    } else {
      setName('')
      setTable(tables[0]?.name || '')
      setLevels([
        { column: '', name: '' },
        { column: '', name: '' },
      ])
    }
    setError(null)
  }, [open, editHierarchy, tables])

  const tableColumns = useMemo(() => {
    const match = tables.find(t => t.name === table)
    return match?.columns || []
  }, [tables, table])

  const updateLevel = (index: number, field: keyof LevelRow, value: string) => {
    setLevels((prev) => prev.map((lvl, i) => i === index ? { ...lvl, [field]: value } : lvl))
  }

  const addLevel = () => {
    setLevels((prev) => [...prev, { column: '', name: '' }])
  }

  const removeLevel = (index: number) => {
    setLevels((prev) => prev.filter((_, i) => i !== index))
  }

  const validate = () => {
    const trimmedName = name.trim()
    if (!trimmedName) return 'Hierarchy name is required.'
    if (!table) return 'Hierarchy table is required.'

    const existing = Object.keys(existingHierarchies)
      .filter((n) => n.toLowerCase() !== (editHierarchy?.name || '').toLowerCase())
      .some((n) => n.toLowerCase() === trimmedName.toLowerCase())
    if (existing) return `Hierarchy "${trimmedName}" already exists.`

    if (levels.length < 2) return 'At least 2 levels are required.'

    const normalizedLevels = levels
      .map((lvl) => ({ column: lvl.column.trim(), name: (lvl.name || lvl.column).trim() }))
      .filter((lvl) => lvl.column || lvl.name)

    if (normalizedLevels.length < 2) return 'At least 2 levels with columns are required.'

    const seenCols = new Set<string>()
    const seenNames = new Set<string>()
    for (const lvl of normalizedLevels) {
      if (!lvl.column) return 'Each level must select a column.'
      const colKey = lvl.column.toLowerCase()
      if (seenCols.has(colKey)) return 'Level columns must be unique.'
      seenCols.add(colKey)

      const nameKey = (lvl.name || lvl.column).toLowerCase()
      if (seenNames.has(nameKey)) return 'Level names must be unique.'
      seenNames.add(nameKey)
    }

    return null
  }

  const handleApply = () => {
    const validation = validate()
    if (validation) {
      setError(validation)
      return
    }

    const normalizedLevels = levels
      .map((lvl) => ({ column: lvl.column.trim(), name: (lvl.name || lvl.column).trim() }))
      .filter((lvl) => lvl.column)

    onApply(name.trim(), { table, levels: normalizedLevels }, editHierarchy?.name)
    onClose()
  }

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-xl" data-testid="hierarchy-editor-dialog">
        <DialogHeader>
          <DialogTitle>{editHierarchy ? 'Edit' : 'New'} Hierarchy</DialogTitle>
          <DialogDescription>
            Changes apply in-memory. Use Save to persist them to disk.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-2">
          <div className="space-y-2">
            <Label htmlFor="hierarchy-name">Hierarchy Name</Label>
            <Input
              id="hierarchy-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g., Date Hierarchy"
              data-testid="hierarchy-name-input"
            />
          </div>

          <div className="space-y-2">
            <Label>Table</Label>
            <Select value={table} onValueChange={setTable}>
              <SelectTrigger className="h-8" data-testid="hierarchy-table-select">
                <SelectValue placeholder="Select table" />
              </SelectTrigger>
              <SelectContent>
                {tables.map((t) => (
                  <SelectItem key={t.name} value={t.name}>
                    {t.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <Label>Levels</Label>
              <Button
                variant="ghost"
                size="sm"
                className="h-6 text-xs"
                onClick={addLevel}
                data-testid="hierarchy-add-level"
              >
                <Plus className="h-3 w-3 mr-1" /> Add Level
              </Button>
            </div>
            <div className="space-y-2">
              {levels.map((lvl, idx) => (
                <div key={idx} className="border rounded-md p-2 space-y-2">
                  <div className="grid grid-cols-[1fr,1fr,auto] gap-2 items-center">
                    <Select value={lvl.column} onValueChange={(v) => updateLevel(idx, 'column', v)}>
                      <SelectTrigger className="h-7 text-xs" data-testid={`hierarchy-level-column-${idx}`}>
                        <SelectValue placeholder="Column" />
                      </SelectTrigger>
                      <SelectContent>
                        {tableColumns.map((col) => (
                          <SelectItem key={col} value={col}>
                            {col}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                    <Input
                      value={lvl.name}
                      onChange={(e) => updateLevel(idx, 'name', e.target.value)}
                      placeholder="Level name"
                      className="h-7 text-xs"
                      data-testid={`hierarchy-level-name-${idx}`}
                    />
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-7 w-7 text-destructive"
                      onClick={() => removeLevel(idx)}
                      disabled={levels.length <= 2}
                      data-testid={`hierarchy-remove-level-${idx}`}
                    >
                      <Trash2 className="h-3 w-3" />
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {error && (
            <p className="text-xs text-destructive" data-testid="hierarchy-error">
              {error}
            </p>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={onClose} data-testid="hierarchy-cancel-btn">
            Cancel
          </Button>
          <Button onClick={handleApply} data-testid="hierarchy-apply-btn">
            Apply
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

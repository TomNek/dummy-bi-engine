/**
 * FieldParameterEditor - Dialog for creating/editing Field Parameters
 * Uses dropdown selectors for tables, columns, and measures like Power BI
 */

import { useState, useEffect, useMemo } from 'react'
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
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Loader2, Plus, Trash2, GripVertical } from 'lucide-react'
import { useAppStore } from '@/stores'
import { updateFieldParameters, type FieldParameterDef } from '@/lib/api'

interface FieldParameterEditorProps {
  open: boolean
  onClose: () => void
  editParam?: { name: string; def: FieldParameterDef } | null
  existingDefs: Record<string, FieldParameterDef>
}

interface ItemRow {
  name: string
  refType: 'column' | 'measure'
  refTable: string
  refColumn: string
  refMeasure: string
  sortOrder: number
  sortColumn: string  // Optional sort column reference
  customProps: Record<string, string>  // Custom properties (e.g., locale, category)
}

const emptyItem = (): ItemRow => ({
  name: '',
  refType: 'column',
  refTable: '',
  refColumn: '',
  refMeasure: '',
  sortOrder: 0,
  sortColumn: '',
  customProps: {},
})

export function FieldParameterEditor({ open, onClose, editParam, existingDefs }: FieldParameterEditorProps) {
  const projectPath = useAppStore(s => s.projectPath)
  const tables = useAppStore(s => s.tables)
  const measures = useAppStore(s => s.measures)
  
  const [name, setName] = useState('')
  const [items, setItems] = useState<ItemRow[]>([emptyItem()])
  const [customColumns, setCustomColumns] = useState<string[]>([])  // Custom column names
  const [newColumnName, setNewColumnName] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Build lookup for columns by table
  const columnsByTable = useMemo(() => {
    const map: Record<string, string[]> = {}
    for (const t of tables) {
      map[t.name] = t.columns || []
    }
    return map
  }, [tables])

  // All columns across all tables for sort column dropdown
  const allColumns = useMemo(() => {
    const cols: { table: string; column: string; display: string }[] = []
    for (const t of tables) {
      for (const c of t.columns || []) {
        cols.push({ table: t.name, column: c, display: `${t.name}[${c}]` })
      }
    }
    return cols
  }, [tables])

  // Reset form when opening
  useEffect(() => {
    if (open) {
      if (editParam) {
        setName(editParam.name)
        // Look up the full def from existingDefs to ensure we get table/column
        const fullDef = existingDefs[editParam.name] || editParam.def
        const defItems = fullDef.items || []
        
        // Extract custom column names from items
        const customColSet = new Set<string>()
        for (const it of defItems) {
          const itemObj = it as Record<string, unknown>
          for (const key of Object.keys(itemObj)) {
            if (!['name', 'ref', 'sort', 'sortColumn'].includes(key)) {
              customColSet.add(key)
            }
          }
        }
        setCustomColumns(Array.from(customColSet))
        
        setItems(defItems.length > 0 
          ? defItems.map((it, idx) => {
              const serverType = it.ref?.type
              const isColumn = serverType === 'ColumnRef'
              const itemObj = it as Record<string, unknown>
              // Extract custom properties
              const customProps: Record<string, string> = {}
              for (const key of Object.keys(itemObj)) {
                if (!['name', 'ref', 'sort', 'sortColumn'].includes(key)) {
                  customProps[key] = String(itemObj[key] || '')
                }
              }
              return { 
                name: it.name || '', 
                refType: isColumn ? 'column' : 'measure',
                refTable: it.ref?.table || '',
                refColumn: isColumn ? (it.ref?.column || '') : '',
                refMeasure: !isColumn ? (it.ref?.name || '') : '',
                sortOrder: it.sort ?? idx,
                sortColumn: (it as Record<string, unknown>).sortColumn as string || '',
                customProps,
              }
            })
          : [emptyItem()]
        )
      } else {
        setName('')
        setItems([emptyItem()])
        setCustomColumns([])
      }
      setNewColumnName('')
      setError(null)
    }
  }, [open, editParam, existingDefs])

  const addItem = () => {
    const nextSort = items.length > 0 ? Math.max(...items.map(i => i.sortOrder)) + 1 : 0
    // Initialize custom props with existing column names
    const customProps: Record<string, string> = {}
    for (const col of customColumns) {
      customProps[col] = ''
    }
    setItems([...items, { ...emptyItem(), sortOrder: nextSort, customProps }])
  }

  const addCustomColumn = () => {
    const colName = newColumnName.trim()
    if (!colName || customColumns.includes(colName)) return
    setCustomColumns([...customColumns, colName])
    // Add this column to all existing items
    setItems(items.map(it => ({
      ...it,
      customProps: { ...it.customProps, [colName]: '' }
    })))
    setNewColumnName('')
  }

  const removeCustomColumn = (colName: string) => {
    setCustomColumns(customColumns.filter(c => c !== colName))
    // Remove this column from all items
    setItems(items.map(it => {
      const newProps = { ...it.customProps }
      delete newProps[colName]
      return { ...it, customProps: newProps }
    }))
  }

  const updateCustomProp = (index: number, colName: string, value: string) => {
    const updated = [...items]
    updated[index] = {
      ...updated[index],
      customProps: { ...updated[index].customProps, [colName]: value }
    }
    setItems(updated)
  }

  const removeItem = (index: number) => {
    if (items.length > 1) {
      setItems(items.filter((_, i) => i !== index))
    }
  }

  const updateItem = <K extends keyof ItemRow>(index: number, field: K, value: ItemRow[K]) => {
    const updated = [...items]
    updated[index] = { ...updated[index], [field]: value }
    
    // When table changes for column type, reset column selection
    if (field === 'refTable') {
      updated[index].refColumn = ''
    }
    // When type changes, reset the ref fields
    if (field === 'refType') {
      updated[index].refTable = ''
      updated[index].refColumn = ''
      updated[index].refMeasure = ''
    }
    
    setItems(updated)
  }

  const handleSave = async () => {
    if (!name.trim()) {
      setError('Parameter name is required')
      return
    }

    const validItems = items.filter(it => {
      if (!it.name.trim()) return false
      if (it.refType === 'column') return it.refTable && it.refColumn
      return it.refMeasure
    })
    
    if (validItems.length === 0) {
      setError('At least one item with a valid column or measure is required')
      return
    }

    setSaving(true)
    setError(null)

    try {
      const newDefs = { ...existingDefs }
      
      if (editParam && editParam.name !== name.trim()) {
        delete newDefs[editParam.name]
      }

      newDefs[name.trim()] = {
        items: validItems.map(it => {
          const item: { [key: string]: unknown; name: string; ref?: { type: string; table?: string; column?: string; name?: string }; sort?: number; sortColumn?: string } = {
            name: it.name.trim(),
            ref: it.refType === 'column' 
              ? { type: 'ColumnRef', table: it.refTable, column: it.refColumn }
              : { type: 'MeasureRef', name: it.refMeasure },
            sort: it.sortOrder,
          }
          if (it.sortColumn) {
            item.sortColumn = it.sortColumn
          }
          // Add custom properties
          for (const [key, val] of Object.entries(it.customProps)) {
            if (val && val.trim()) {
              item[key] = val.trim()
            }
          }
          return item
        })
      }

      const result = await updateFieldParameters(newDefs, projectPath || undefined)
      
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
    if (!confirm(`Delete field parameter "${editParam.name}"?`)) return

    setSaving(true)
    setError(null)

    try {
      const newDefs = { ...existingDefs }
      delete newDefs[editParam.name]

      const result = await updateFieldParameters(newDefs, projectPath || undefined)
      
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
      <DialogContent className="max-w-2xl max-h-[90vh] overflow-hidden flex flex-col" data-testid="field-param-editor-dialog">
        <DialogHeader>
          <DialogTitle>{editParam ? 'Edit' : 'New'} Field Parameter</DialogTitle>
          <DialogDescription>
            Field parameters let users switch between columns or measures at runtime.
          </DialogDescription>
        </DialogHeader>

        <div className="flex-1 overflow-y-auto space-y-4 py-4 px-1">
          <div className="space-y-2">
            <Label htmlFor="fp-name">Parameter Name</Label>
            <Input
              id="fp-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g., Metric Selector"
              data-testid="field-param-name-input"
            />
          </div>

          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <Label>Items</Label>
              <Button variant="ghost" size="sm" onClick={addItem} data-testid="field-param-add-item">
                <Plus className="h-3 w-3 mr-1" /> Add Item
              </Button>
            </div>
            
            <div className="space-y-3">
              {items.map((item, idx) => (
                <div key={idx} className="border rounded-md p-3 space-y-3 bg-muted/30">
                  {/* Header row: drag handle, name, delete */}
                  <div className="flex gap-2 items-center">
                    <GripVertical className="h-4 w-4 text-muted-foreground cursor-grab" />
                    <Input
                      value={item.name}
                      onChange={(e) => updateItem(idx, 'name', e.target.value)}
                      placeholder="Display name"
                      className="h-8 text-sm flex-1"
                      data-testid={`field-param-item-name-${idx}`}
                    />
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-8 w-8 text-destructive hover:text-destructive"
                      onClick={() => removeItem(idx)}
                      disabled={items.length === 1}
                      data-testid={`field-param-remove-item-${idx}`}
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </div>
                  
                  {/* Type selector */}
                  <div className="grid grid-cols-[120px_1fr] gap-2 items-center">
                    <Label className="text-xs text-muted-foreground">Type</Label>
                    <Select
                      value={item.refType}
                      onValueChange={(v) => updateItem(idx, 'refType', v as 'column' | 'measure')}
                    >
                      <SelectTrigger className="h-8" data-testid={`field-param-item-type-${idx}`}>
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="column">Column</SelectItem>
                        <SelectItem value="measure">Measure</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>

                  {/* Column selection */}
                  {item.refType === 'column' && (
                    <>
                      <div className="grid grid-cols-[120px_1fr] gap-2 items-center">
                        <Label className="text-xs text-muted-foreground">Table</Label>
                        <Select
                          value={item.refTable}
                          onValueChange={(v) => updateItem(idx, 'refTable', v)}
                        >
                          <SelectTrigger className="h-8" data-testid={`field-param-item-table-${idx}`}>
                            <SelectValue placeholder="Select table..." />
                          </SelectTrigger>
                          <SelectContent>
                            {tables.map(t => (
                              <SelectItem key={t.name} value={t.name}>{t.name}</SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      </div>
                      <div className="grid grid-cols-[120px_1fr] gap-2 items-center">
                        <Label className="text-xs text-muted-foreground">Column</Label>
                        <Select
                          value={item.refColumn}
                          onValueChange={(v) => {
                            updateItem(idx, 'refColumn', v)
                            // Auto-populate name if empty
                            if (!items[idx].name) {
                              setTimeout(() => updateItem(idx, 'name', v), 0)
                            }
                          }}
                          disabled={!item.refTable}
                        >
                          <SelectTrigger className="h-8" data-testid={`field-param-item-column-${idx}`}>
                            <SelectValue placeholder={item.refTable ? "Select column..." : "Select table first"} />
                          </SelectTrigger>
                          <SelectContent>
                            {(columnsByTable[item.refTable] || []).map(c => (
                              <SelectItem key={c} value={c}>{c}</SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      </div>
                    </>
                  )}

                  {/* Measure selection */}
                  {item.refType === 'measure' && (
                    <div className="grid grid-cols-[120px_1fr] gap-2 items-center">
                      <Label className="text-xs text-muted-foreground">Measure</Label>
                      <Select
                        value={item.refMeasure}
                        onValueChange={(v) => {
                          updateItem(idx, 'refMeasure', v)
                          if (!items[idx].name) {
                            setTimeout(() => updateItem(idx, 'name', v), 0)
                          }
                        }}
                      >
                        <SelectTrigger className="h-8" data-testid={`field-param-item-measure-${idx}`}>
                          <SelectValue placeholder="Select measure..." />
                        </SelectTrigger>
                        <SelectContent>
                          {measures.map(m => (
                            <SelectItem key={m} value={m}>{m}</SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>
                  )}

                  {/* Sort order and sort column */}
                  <div className="grid grid-cols-2 gap-3">
                    <div className="grid grid-cols-[60px_1fr] gap-2 items-center">
                      <Label className="text-xs text-muted-foreground">Sort #</Label>
                      <Input
                        type="number"
                        value={item.sortOrder}
                        onChange={(e) => updateItem(idx, 'sortOrder', parseInt(e.target.value) || 0)}
                        className="h-8"
                        data-testid={`field-param-item-sort-${idx}`}
                      />
                    </div>
                    <div className="grid grid-cols-[80px_1fr] gap-2 items-center">
                      <Label className="text-xs text-muted-foreground">Sort By</Label>
                      <Select
                        value={item.sortColumn}
                        onValueChange={(v) => updateItem(idx, 'sortColumn', v === '__none__' ? '' : v)}
                      >
                        <SelectTrigger className="h-8" data-testid={`field-param-item-sortcol-${idx}`}>
                          <SelectValue placeholder="(none)" />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="__none__">(none)</SelectItem>
                          {allColumns.map(c => (
                            <SelectItem key={c.display} value={c.display}>{c.display}</SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>
                  </div>

                  {/* Custom properties */}
                  {customColumns.length > 0 && (
                    <div className="grid grid-cols-2 gap-2">
                      {customColumns.map(colName => (
                        <div key={colName} className="grid grid-cols-[80px_1fr] gap-2 items-center">
                          <Label className="text-xs text-muted-foreground truncate" title={colName}>{colName}</Label>
                          <Input
                            value={item.customProps[colName] || ''}
                            onChange={(e) => updateCustomProp(idx, colName, e.target.value)}
                            placeholder={`Enter ${colName}...`}
                            className="h-8 text-sm"
                          />
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>

          {/* Custom Columns Management */}
          <div className="space-y-2 border-t pt-4">
            <div className="flex items-center justify-between">
              <Label>Custom Columns</Label>
            </div>
            <div className="flex gap-2 items-center">
              <Input
                value={newColumnName}
                onChange={(e) => setNewColumnName(e.target.value)}
                placeholder="e.g., locale, category"
                className="flex-1 h-8"
                onKeyDown={(e) => e.key === 'Enter' && addCustomColumn()}
              />
              <Button variant="outline" size="sm" onClick={addCustomColumn} disabled={!newColumnName.trim()}>
                <Plus className="h-3 w-3 mr-1" /> Add Column
              </Button>
            </div>
            {customColumns.length > 0 && (
              <div className="flex flex-wrap gap-2 mt-2">
                {customColumns.map(col => (
                  <div key={col} className="flex items-center gap-1 bg-muted px-2 py-1 rounded text-sm">
                    <span>{col}</span>
                    <button
                      type="button"
                      onClick={() => removeCustomColumn(col)}
                      className="text-muted-foreground hover:text-destructive ml-1"
                      title={`Remove ${col} column`}
                    >
                      <Trash2 className="h-3 w-3" />
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>

          {error && (
            <div className="text-sm text-destructive bg-destructive/10 p-2 rounded">
              {error}
            </div>
          )}
        </div>

        <DialogFooter className="gap-2 pt-4 border-t">
          {editParam && (
            <Button
              variant="destructive"
              onClick={handleDelete}
              disabled={saving}
              data-testid="field-param-delete-btn"
            >
              Delete
            </Button>
          )}
          <div className="flex-1" />
          <Button variant="outline" onClick={onClose} disabled={saving}>
            Cancel
          </Button>
          <Button onClick={handleSave} disabled={saving} data-testid="field-param-save-btn">
            {saving && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}
            Save
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

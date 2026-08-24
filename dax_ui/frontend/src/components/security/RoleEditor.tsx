/**
 * RoleEditor - Dialog for creating/editing Security Roles (RLS + OLS)
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
import { Textarea } from '@/components/ui/textarea'
import { Checkbox } from '@/components/ui/checkbox'
import { Loader2, Plus, Trash2 } from 'lucide-react'
import { useAppStore } from '@/stores'
import { updateSecurityRoles, type SecurityRoleRaw } from '@/lib/api'

interface RoleEditorProps {
  open: boolean
  onClose: () => void
  editRole?: SecurityRoleRaw | null
  existingRoles: SecurityRoleRaw[]
  defaultRole: string | null
}

interface RlsRule {
  table: string
  filter: string
}

interface OlsState {
  tables: string[]
  measures: string[]
  columns: Record<string, string[]>
}

export function RoleEditor({ open, onClose, editRole, existingRoles, defaultRole }: RoleEditorProps) {
  const projectPath = useAppStore(s => s.projectPath)
  const tables = useAppStore(s => s.tables)
  const measures = useAppStore(s => s.measures)
  
  const [name, setName] = useState('')
  const [rlsRules, setRlsRules] = useState<RlsRule[]>([])
  const [olsState, setOlsState] = useState<OlsState>({ tables: [], measures: [], columns: {} })
  const [isDefault, setIsDefault] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [activeTab, setActiveTab] = useState<'rls' | 'ols'>('rls')

  // Reset form when opening
  useEffect(() => {
    if (open) {
      if (editRole) {
        setName(editRole.name)
        setRlsRules(editRole.rls || [])
        setOlsState({
          tables: editRole.ols?.tables || [],
          measures: editRole.ols?.measures || [],
          columns: editRole.ols?.columns || {}
        })
        setIsDefault(defaultRole === editRole.name)
      } else {
        setName('')
        setRlsRules([])
        setOlsState({ tables: [], measures: [], columns: {} })
        setIsDefault(false)
      }
      setError(null)
      setActiveTab('rls')
    }
  }, [open, editRole, defaultRole])

  const addRlsRule = () => {
    setRlsRules([...rlsRules, { table: '', filter: '' }])
  }

  const removeRlsRule = (index: number) => {
    setRlsRules(rlsRules.filter((_, i) => i !== index))
  }

  const updateRlsRule = (index: number, field: keyof RlsRule, value: string) => {
    const updated = [...rlsRules]
    updated[index] = { ...updated[index], [field]: value }
    setRlsRules(updated)
  }

  const toggleHiddenTable = (tableName: string) => {
    setOlsState(prev => ({
      ...prev,
      tables: prev.tables.includes(tableName)
        ? prev.tables.filter(t => t !== tableName)
        : [...prev.tables, tableName]
    }))
  }

  const toggleHiddenMeasure = (measureName: string) => {
    setOlsState(prev => ({
      ...prev,
      measures: prev.measures.includes(measureName) 
        ? prev.measures.filter(m => m !== measureName)
        : [...prev.measures, measureName]
    }))
  }

  const toggleHiddenColumn = (table: string, column: string) => {
    setOlsState(prev => {
      const currentCols = prev.columns[table] || []
      const newCols = currentCols.includes(column)
        ? currentCols.filter(c => c !== column)
        : [...currentCols, column]
      
      const newColumnsState = { ...prev.columns }
      if (newCols.length > 0) {
        newColumnsState[table] = newCols
      } else {
        delete newColumnsState[table]
      }
      
      return { ...prev, columns: newColumnsState }
    })
  }

  const handleSave = async () => {
    if (!name.trim()) {
      setError('Role name is required')
      return
    }

    // Check for duplicate names (excluding current role if editing)
    const duplicate = existingRoles.find(r => 
      r.name.toLowerCase() === name.trim().toLowerCase() && 
      (!editRole || r.name !== editRole.name)
    )
    if (duplicate) {
      setError(`Role "${name.trim()}" already exists`)
      return
    }

    setSaving(true)
    setError(null)

    try {
      // Build updated roles list
      const validRls = rlsRules.filter(r => r.table.trim() && r.filter.trim())
      const roleToSave: SecurityRoleRaw = {
        name: name.trim(),
        rls: validRls.length > 0 ? validRls : undefined,
        ols: (olsState.tables.length > 0 || olsState.measures.length > 0 || Object.keys(olsState.columns).length > 0)
          ? {
              tables: olsState.tables.length > 0 ? olsState.tables : undefined,
              measures: olsState.measures.length > 0 ? olsState.measures : undefined,
              columns: Object.keys(olsState.columns).length > 0 ? olsState.columns : undefined,
            }
          : undefined
      }

      let newRoles: SecurityRoleRaw[]
      if (editRole) {
        // Replace existing role
        newRoles = existingRoles.map(r => r.name === editRole.name ? roleToSave : r)
      } else {
        // Add new role
        newRoles = [...existingRoles, roleToSave]
      }

      const newDefaultRole = isDefault 
        ? name.trim() 
        : (defaultRole === editRole?.name ? null : defaultRole)

      const result = await updateSecurityRoles(newRoles, newDefaultRole, projectPath || undefined)
      
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
    if (!editRole) return
    
    if (!confirm(`Delete role "${editRole.name}"?`)) return

    setSaving(true)
    setError(null)

    try {
      const newRoles = existingRoles.filter(r => r.name !== editRole.name)
      const newDefaultRole = defaultRole === editRole.name ? null : defaultRole

      const result = await updateSecurityRoles(newRoles, newDefaultRole, projectPath || undefined)
      
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
      <DialogContent className="max-w-3xl max-h-[90vh] overflow-hidden flex flex-col" data-testid="role-editor-dialog">
        <DialogHeader>
          <DialogTitle>{editRole ? 'Edit' : 'New'} Security Role</DialogTitle>
          <DialogDescription>
            Configure Row-Level Security (RLS) and Object-Level Security (OLS) rules.
          </DialogDescription>
        </DialogHeader>

        <div className="flex-1 overflow-y-auto space-y-4 py-4">
          <div className="flex gap-4 items-end">
            <div className="flex-1 space-y-2">
              <Label htmlFor="role-name">Role Name</Label>
              <Input
                id="role-name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="e.g., SalesRep"
                data-testid="role-name-input"
              />
            </div>
            <div className="flex items-center gap-2 pb-2">
              <Checkbox
                id="role-default"
                checked={isDefault}
                onCheckedChange={(checked) => setIsDefault(!!checked)}
                data-testid="role-default-checkbox"
              />
              <Label htmlFor="role-default" className="text-sm">Set as default</Label>
            </div>
          </div>

          {/* Tab buttons */}
          <div className="flex border-b">
            <button
              type="button"
              className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
                activeTab === 'rls' 
                  ? 'border-primary text-primary' 
                  : 'border-transparent text-muted-foreground hover:text-foreground'
              }`}
              onClick={() => setActiveTab('rls')}
              data-testid="role-tab-rls"
            >
              RLS (Row-Level Security)
            </button>
            <button
              type="button"
              className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
                activeTab === 'ols' 
                  ? 'border-primary text-primary' 
                  : 'border-transparent text-muted-foreground hover:text-foreground'
              }`}
              onClick={() => setActiveTab('ols')}
              data-testid="role-tab-ols"
            >
              OLS (Object-Level Security)
            </button>
          </div>

          {/* RLS Tab Content */}
          {activeTab === 'rls' && (
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <Label>Row-Level Security Rules</Label>
                <Button variant="ghost" size="sm" onClick={addRlsRule} data-testid="role-add-rls">
                  <Plus className="h-3 w-3 mr-1" /> Add Rule
                </Button>
              </div>
              
              {rlsRules.length === 0 && (
                <div className="text-sm text-muted-foreground text-center py-4 border rounded-md">
                  No RLS rules defined. Click "Add Rule" to restrict row access.
                </div>
              )}
              
              <div className="space-y-2 max-h-48 overflow-y-auto">
                {rlsRules.map((rule, idx) => (
                  <div key={idx} className="flex gap-2 items-start border rounded-md p-2">
                    <div className="flex-1 space-y-2">
                      <Input
                        value={rule.table}
                        onChange={(e) => updateRlsRule(idx, 'table', e.target.value)}
                        placeholder="Table name"
                        className="h-8 text-sm"
                        list="rls-tables"
                        data-testid={`rls-table-${idx}`}
                      />
                      <Textarea
                        value={rule.filter}
                        onChange={(e) => updateRlsRule(idx, 'filter', e.target.value)}
                        placeholder="DAX filter expression (e.g., [Region] = 'West')"
                        className="text-sm font-mono min-h-[50px]"
                        data-testid={`rls-filter-${idx}`}
                      />
                    </div>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-8 w-8 text-destructive"
                      onClick={() => removeRlsRule(idx)}
                      data-testid={`rls-remove-${idx}`}
                    >
                      <Trash2 className="h-3 w-3" />
                    </Button>
                  </div>
                ))}
              </div>
              
              {/* Datalist for table autocomplete */}
              <datalist id="rls-tables">
                {tables.map(t => <option key={t.name} value={t.name} />)}
              </datalist>
            </div>
          )}

          {/* OLS Tab Content */}
          {activeTab === 'ols' && (
            <div className="space-y-4">
              {/* Hidden Tables */}
              <div className="space-y-2">
                <Label>Hidden Tables</Label>
                {tables.length === 0 ? (
                  <div className="text-sm text-muted-foreground">No tables available</div>
                ) : (
                  <div className="grid grid-cols-3 gap-2 max-h-32 overflow-y-auto border rounded-md p-2">
                    {tables.map(table => (
                      <label key={table.name} className="flex items-center gap-2 text-sm">
                        <Checkbox
                          checked={olsState.tables.includes(table.name)}
                          onCheckedChange={() => toggleHiddenTable(table.name)}
                          data-testid={`ols-table-${table.name}`}
                        />
                        {table.name}
                      </label>
                    ))}
                  </div>
                )}
              </div>

              {/* Hidden Measures */}
              <div className="space-y-2">
                <Label>Hidden Measures</Label>
                {measures.length === 0 ? (
                  <div className="text-sm text-muted-foreground">No measures available</div>
                ) : (
                  <div className="grid grid-cols-3 gap-2 max-h-32 overflow-y-auto border rounded-md p-2">
                    {measures.map(measure => (
                      <label key={measure} className="flex items-center gap-2 text-sm">
                        <Checkbox
                          checked={olsState.measures.includes(measure)}
                          onCheckedChange={() => toggleHiddenMeasure(measure)}
                          data-testid={`ols-measure-${measure}`}
                        />
                        {measure}
                      </label>
                    ))}
                  </div>
                )}
              </div>

              {/* Hidden Columns (per table) */}
              <div className="space-y-2">
                <Label>Hidden Columns</Label>
                <div className="space-y-2 max-h-48 overflow-y-auto border rounded-md p-2">
                  {tables.map(table => (
                    <details key={table.name} className="group">
                      <summary className="cursor-pointer text-sm font-medium py-1">
                        {table.name}
                        {(olsState.columns[table.name]?.length ?? 0) > 0 && (
                          <span className="text-muted-foreground ml-2">
                            ({olsState.columns[table.name]?.length} hidden)
                          </span>
                        )}
                      </summary>
                      <div className="pl-4 grid grid-cols-3 gap-1 py-2">
                        {table.columns.map(col => (
                          <label key={col} className="flex items-center gap-1 text-xs">
                            <Checkbox
                              checked={olsState.columns[table.name]?.includes(col) || false}
                              onCheckedChange={() => toggleHiddenColumn(table.name, col)}
                              data-testid={`ols-col-${table.name}-${col}`}
                            />
                            {col}
                          </label>
                        ))}
                      </div>
                    </details>
                  ))}
                </div>
              </div>
            </div>
          )}

          {error && (
            <div className="text-sm text-destructive bg-destructive/10 p-2 rounded" data-testid="role-error">
              {error}
            </div>
          )}
        </div>

        <DialogFooter className="gap-2">
          {editRole && (
            <Button
              variant="destructive"
              onClick={handleDelete}
              disabled={saving}
              data-testid="role-delete-btn"
            >
              Delete
            </Button>
          )}
          <div className="flex-1" />
          <Button variant="outline" onClick={onClose} disabled={saving}>
            Cancel
          </Button>
          <Button onClick={handleSave} disabled={saving} data-testid="role-save-btn">
            {saving && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}
            Save
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

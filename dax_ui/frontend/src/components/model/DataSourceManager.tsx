import { useCallback, useEffect, useMemo, useState } from 'react'
import { Database, RefreshCw, Trash2, TestTube2, Eye, Save, Plus, AlertCircle, CheckCircle2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Checkbox } from '@/components/ui/checkbox'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { toast } from '@/components/ui/toast'
import { useAppStore } from '@/stores'
import { useRuntimeState } from '@/hooks'
import {
  listImportTables,
  getImportConnectors,
  updateTableSource,
  deletePhysicalTable,
  testDataSource,
  refreshTable,
  refreshAllTables,
  previewImportSource,
  type ImportConnector,
  type ImportConnectorParam,
  type ImportPreviewResult,
  type ImportSource,
  type ImportTableInfo,
} from '@/lib/api'

interface DataSourceManagerProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  onOpenImport?: () => void
}

// Source types that support each storage mode (mirrors ImportDataDialog)
const DIRECT_QUERY_SOURCES = new Set(['duckdb', 'sqlite', 'postgres', 'mysql', 'http', 's3', 'azure_blob', 'cloudflare_r2'])
const DIRECT_LAKE_SOURCES = new Set(['iceberg', 'parquet', 'delta'])

function getAvailableModes(sourceType: string): Array<{ value: string; label: string }> {
  const modes: Array<{ value: string; label: string }> = [
    { value: 'import', label: 'Import' },
  ]
  if (DIRECT_QUERY_SOURCES.has(sourceType)) {
    modes.push({ value: 'direct_query', label: 'DirectQuery' })
  }
  if (DIRECT_LAKE_SOURCES.has(sourceType)) {
    modes.push({ value: 'direct_lake', label: 'DirectLake' })
  }
  return modes
}

function storageModeLabel(mode: string | null | undefined): string {
  if (!mode) return 'Import'
  switch (mode) {
    case 'direct_query': return 'DQ'
    case 'direct_lake': return 'DL'
    case 'import': return 'Import'
    default: return mode
  }
}

function sourceTypeLabel(type: string | null | undefined): string {
  if (!type) return '—'
  return type.toUpperCase()
}

function sourceDetail(src: ImportSource | null | undefined): string {
  if (!src) return '—'
  const parts: string[] = []
  if (src.path) parts.push(src.path)
  if (src.table) parts.push(src.table)
  if (src.schema) parts.push(`schema: ${src.schema}`)
  return parts.join(' · ') || '—'
}

interface EditDraft {
  type: string
  path: string
  format: string
  auth_mode: string
  schema: string
  table: string
  delimiter: string
  header: boolean
  encoding: string
  nullstr: string
  storageMode: string
}

function sourceToEditDraft(src: ImportSource | null | undefined, storageMode: string | null | undefined): EditDraft {
  return {
    type: src?.type || 'csv',
    path: src?.path || '',
    format: src?.format || '',
    auth_mode: src?.auth_mode || '',
    schema: src?.schema || '',
    table: src?.table || '',
    delimiter: src?.delimiter || ',',
    header: src?.header !== false,
    encoding: src?.encoding || '',
    nullstr: Array.isArray(src?.nullstr) ? src.nullstr.join(',') : (src?.nullstr || ''),
    storageMode: storageMode || 'import',
  }
}

function editDraftToSource(draft: EditDraft): ImportSource {
  const src: ImportSource = {
    type: draft.type,
    path: draft.path,
  }
  if (draft.format) src.format = draft.format
  if (draft.auth_mode) src.auth_mode = draft.auth_mode
  if (draft.schema) src.schema = draft.schema
  if (draft.table) src.table = draft.table
  if (draft.type === 'csv') {
    if (draft.delimiter && draft.delimiter !== ',') src.delimiter = draft.delimiter
    src.header = draft.header
    if (draft.encoding) src.encoding = draft.encoding
    if (draft.nullstr) {
      const parts = draft.nullstr.split(',').map(s => s.trim()).filter(Boolean)
      src.nullstr = parts.length > 1 ? parts : parts[0] || undefined
    }
  }
  return src
}

export function DataSourceManager({ open, onOpenChange, onOpenImport }: DataSourceManagerProps) {
  const projectPath = useAppStore((s) => s.projectPath)
  const { reload } = useRuntimeState()

  const [tables, setTables] = useState<ImportTableInfo[]>([])
  const [connectors, setConnectors] = useState<ImportConnector[]>([])
  const [selectedTable, setSelectedTable] = useState<string | null>(null)
  const [editDraft, setEditDraft] = useState<EditDraft | null>(null)
  const [isDirty, setIsDirty] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [preview, setPreview] = useState<ImportPreviewResult | null>(null)
  const [loadingPreview, setLoadingPreview] = useState(false)
  const [testResult, setTestResult] = useState<{ connected: boolean; error?: string; column_count?: number } | null>(null)
  const [loadingTest, setLoadingTest] = useState(false)
  const [loadingSave, setLoadingSave] = useState(false)
  const [loadingRefresh, setLoadingRefresh] = useState(false)
  const [loadingDelete, setLoadingDelete] = useState(false)
  const [deleteConfirm, setDeleteConfirm] = useState<string | null>(null)

  const canUseProject = Boolean(projectPath && projectPath.trim())

  // Load tables and connectors when dialog opens
  const loadTables = useCallback(async () => {
    if (!canUseProject) return
    setLoading(true)
    setError(null)
    try {
      const [tablesRes, connectorsRes] = await Promise.all([
        listImportTables(projectPath || undefined),
        getImportConnectors(),
      ])
      if (tablesRes.error || !tablesRes.data) {
        setError(tablesRes.error || 'Failed to load tables')
        return
      }
      setTables(Array.isArray(tablesRes.data.tables) ? tablesRes.data.tables : [])
      setConnectors(
        connectorsRes.data && Array.isArray(connectorsRes.data.connectors)
          ? connectorsRes.data.connectors
          : []
      )
    } catch (err) {
      setError(String(err))
    } finally {
      setLoading(false)
    }
  }, [canUseProject, projectPath])

  useEffect(() => {
    if (open) {
      loadTables()
      setSelectedTable(null)
      setEditDraft(null)
      setIsDirty(false)
      setPreview(null)
      setTestResult(null)
      setDeleteConfirm(null)
    }
  }, [open, loadTables])

  // Get the connector definition for the current edit type
  const currentConnector = useMemo(() => {
    if (!editDraft) return null
    return connectors.find(c => c.type === editDraft.type) || null
  }, [editDraft, connectors])

  // Select a table and populate the edit form
  const handleSelectTable = useCallback((tableName: string) => {
    const table = tables.find(t => t.name === tableName)
    if (!table) return
    setSelectedTable(tableName)
    setEditDraft(sourceToEditDraft(table.source, (table as any).storage_mode))
    setIsDirty(false)
    setPreview(null)
    setTestResult(null)
    setDeleteConfirm(null)
  }, [tables])

  // Update a draft field
  const updateDraft = useCallback((field: keyof EditDraft, value: string | boolean) => {
    setEditDraft(prev => {
      if (!prev) return prev
      const next = { ...prev, [field]: value }
      setIsDirty(true)
      setTestResult(null)
      return next
    })
  }, [])

  // Test connection
  const handleTest = useCallback(async () => {
    if (!editDraft || !canUseProject) return
    setLoadingTest(true)
    setTestResult(null)
    try {
      const src = editDraftToSource(editDraft)
      const { data, error: apiErr } = await testDataSource({ source: src }, projectPath || undefined)
      if (apiErr || !data) {
        const errMsg = apiErr || 'Test failed'
        setTestResult({ connected: false, error: errMsg })
        toast(errMsg, { variant: 'error' })
        return
      }
      setTestResult({ connected: data.connected, error: data.error, column_count: data.column_count })
      if (data.connected) {
        toast(`Connection OK — ${data.column_count ?? 0} column(s) found`, { variant: 'success' })
      } else {
        toast(`Connection failed: ${data.error || 'Unknown error'}`, { variant: 'error' })
      }
    } catch (err) {
      setTestResult({ connected: false, error: String(err) })
      toast(`Test failed: ${err}`, { variant: 'error' })
    } finally {
      setLoadingTest(false)
    }
  }, [editDraft, canUseProject, projectPath])

  // Preview data
  const handlePreview = useCallback(async () => {
    if (!editDraft || !canUseProject) return
    setLoadingPreview(true)
    setPreview(null)
    try {
      const src = editDraftToSource(editDraft)
      const { data, error: apiErr } = await previewImportSource({ source: src, limit: 20 }, projectPath || undefined)
      if (apiErr || !data) {
        toast(apiErr || 'Preview failed', { variant: 'error' })
        return
      }
      setPreview(data)
    } catch (err) {
      toast(`Preview failed: ${err}`, { variant: 'error' })
    } finally {
      setLoadingPreview(false)
    }
  }, [editDraft, canUseProject, projectPath])

  // Save source changes
  const handleSave = useCallback(async () => {
    if (!editDraft || !selectedTable || !canUseProject) return
    setLoadingSave(true)
    try {
      const src = editDraftToSource(editDraft)
      const { error: apiErr } = await updateTableSource(selectedTable, { source: src, storage_mode: editDraft.storageMode }, projectPath || undefined)
      if (apiErr) {
        toast(`Save failed: ${apiErr}`, { variant: 'error' })
        return
      }
      toast(`Source updated for "${selectedTable}"`, { variant: 'success' })
      setIsDirty(false)
      await loadTables()
      reload()
    } catch (err) {
      toast(`Save failed: ${err}`, { variant: 'error' })
    } finally {
      setLoadingSave(false)
    }
  }, [editDraft, selectedTable, canUseProject, projectPath, loadTables, reload])

  // Refresh table
  const handleRefresh = useCallback(async () => {
    if (!selectedTable || !canUseProject) return
    setLoadingRefresh(true)
    try {
      const { data, error: apiErr } = await refreshTable(selectedTable, projectPath || undefined)
      if (apiErr) {
        toast(`Refresh failed: ${apiErr}`, { variant: 'error' })
        return
      }
      toast(data?.message || `Refreshed "${selectedTable}"`, { variant: 'success' })
      reload()
    } catch (err) {
      toast(`Refresh failed: ${err}`, { variant: 'error' })
    } finally {
      setLoadingRefresh(false)
    }
  }, [selectedTable, canUseProject, projectPath, reload])

  // Refresh all
  const handleRefreshAll = useCallback(async () => {
    if (!canUseProject) return
    setLoadingRefresh(true)
    try {
      const { data, error: apiErr } = await refreshAllTables(projectPath || undefined)
      if (apiErr) {
        toast(`Refresh all failed: ${apiErr}`, { variant: 'error' })
        return
      }
      toast(data?.message || 'All tables refreshed', { variant: 'success' })
      reload()
    } catch (err) {
      toast(`Refresh all failed: ${err}`, { variant: 'error' })
    } finally {
      setLoadingRefresh(false)
    }
  }, [canUseProject, projectPath, reload])

  // Delete table
  const handleDelete = useCallback(async () => {
    if (!selectedTable || !canUseProject) return
    setLoadingDelete(true)
    try {
      const { error: apiErr } = await deletePhysicalTable(selectedTable, projectPath || undefined)
      if (apiErr) {
        toast(`Delete failed: ${apiErr}`, { variant: 'error' })
        return
      }
      toast(`Deleted table "${selectedTable}"`, { variant: 'success' })
      setSelectedTable(null)
      setEditDraft(null)
      setIsDirty(false)
      setDeleteConfirm(null)
      await loadTables()
      reload()
    } catch (err) {
      toast(`Delete failed: ${err}`, { variant: 'error' })
    } finally {
      setLoadingDelete(false)
    }
  }, [selectedTable, canUseProject, projectPath, loadTables, reload])

  // Available connector types for the type dropdown
  const connectorTypes = useMemo(() => {
    if (connectors.length) {
      return connectors.map(c => ({ value: c.type, label: c.label || c.type }))
    }
    return [
      { value: 'csv', label: 'CSV' },
      { value: 'parquet', label: 'Parquet' },
      { value: 'json', label: 'JSON' },
      { value: 'excel', label: 'Excel' },
      { value: 'duckdb', label: 'DuckDB' },
      { value: 'sqlite', label: 'SQLite' },
      { value: 'postgres', label: 'PostgreSQL' },
      { value: 'mysql', label: 'MySQL' },
    ]
  }, [connectors])

  // Parameters for the selected connector type
  const connectorParams = useMemo((): ImportConnectorParam[] => {
    if (!editDraft) return []
    const conn = connectors.find(c => c.type === editDraft.type)
    if (conn?.params) return conn.params
    // Fallback params based on type
    switch (editDraft.type) {
      case 'csv':
        return [
          { name: 'path', label: 'File path', required: true, kind: 'path', placeholder: 'data/file.csv' },
          { name: 'delimiter', label: 'Delimiter', kind: 'text', placeholder: ',' },
          { name: 'header', label: 'Header row', kind: 'bool' },
          { name: 'encoding', label: 'Encoding', kind: 'text', placeholder: 'utf-8' },
          { name: 'nullstr', label: 'Null strings', kind: 'text', placeholder: 'NA,NULL' },
        ]
      case 'parquet':
        return [{ name: 'path', label: 'File path', required: true, kind: 'path', placeholder: 'data/file.parquet' }]
      case 'json':
        return [{ name: 'path', label: 'File path', required: true, kind: 'path', placeholder: 'data/file.json' }]
      case 'excel':
        return [{ name: 'path', label: 'File path', required: true, kind: 'path', placeholder: 'data/file.xlsx' }]
      case 'duckdb':
      case 'postgres':
      case 'mysql':
        return [
          { name: 'path', label: editDraft.type === 'duckdb' ? 'DB file path' : 'Connection string', required: true, kind: 'path' },
          { name: 'schema', label: 'Schema', kind: 'text', placeholder: 'main' },
          { name: 'table', label: 'Table', required: true, kind: 'text' },
        ]
      case 'sqlite':
        return [
          { name: 'path', label: 'DB file path', required: true, kind: 'path' },
          { name: 'table', label: 'Table', required: true, kind: 'text' },
        ]
      default:
        return [{ name: 'path', label: 'Path / URL', required: true, kind: 'path' }]
    }
  }, [editDraft, connectors])

  // Render the parameter form for the selected connector
  const renderParamField = useCallback((param: ImportConnectorParam) => {
    if (!editDraft) return null
    const fieldName = param.name as keyof EditDraft
    const value = editDraft[fieldName]

    if (param.kind === 'bool') {
      return (
        <div key={param.name} className="flex items-center gap-2" data-testid={`dsm-field-${param.name}`}>
          <Checkbox
            id={`dsm-${param.name}`}
            checked={Boolean(value)}
            onCheckedChange={(checked) => updateDraft(fieldName, Boolean(checked))}
          />
          <label htmlFor={`dsm-${param.name}`} className="text-xs cursor-pointer">
            {param.label || param.name}
          </label>
        </div>
      )
    }

    if (param.kind === 'select' && param.options?.length) {
      return (
        <div key={param.name} className="space-y-1" data-testid={`dsm-field-${param.name}`}>
          <label className="text-xs text-muted-foreground">{param.label || param.name}</label>
          <Select
            value={String(value || '')}
            onValueChange={(val) => updateDraft(fieldName, val)}
          >
            <SelectTrigger className="h-7 text-xs">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {param.options.map(opt => (
                <SelectItem key={opt} value={opt}>{opt}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      )
    }

    return (
      <div key={param.name} className="space-y-1" data-testid={`dsm-field-${param.name}`}>
        <label className="text-xs text-muted-foreground">
          {param.label || param.name}
          {param.required && <span className="text-destructive ml-0.5">*</span>}
        </label>
        <Input
          className="h-7 text-xs"
          value={String(value || '')}
          placeholder={param.placeholder || ''}
          onChange={(e) => updateDraft(fieldName, e.target.value)}
        />
      </div>
    )
  }, [editDraft, updateDraft])

  // Preview table render
  const renderPreviewTable = useCallback(() => {
    if (!preview) return null
    const cols = preview.columns || []
    const rows = preview.rows || []
    if (!cols.length) return <div className="text-xs text-muted-foreground">No columns</div>
    return (
      <div className="overflow-auto max-h-[200px]" data-testid="dsm-preview-grid">
        <table className="w-full text-xs border-collapse">
          <thead>
            <tr>
              {cols.map((col, i) => (
                <th key={i} className="border px-2 py-1 text-left bg-muted/50 font-medium whitespace-nowrap">
                  {col.name}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.slice(0, 20).map((row: any, ri) => (
              <tr key={ri}>
                {cols.map((col, ci) => (
                  <td key={ci} className="border px-2 py-0.5 whitespace-nowrap max-w-[200px] truncate">
                    {row?.[col.name] != null ? String(row[col.name]) : ''}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    )
  }, [preview])

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className="max-w-4xl max-h-[85vh] overflow-hidden flex flex-col"
        data-testid="dsm-dialog"
      >
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Database className="h-5 w-5" />
            Data Source Manager
          </DialogTitle>
          <DialogDescription>
            View, edit, refresh, and manage your project's data sources.
          </DialogDescription>
        </DialogHeader>

        {!canUseProject ? (
          <div className="text-sm text-muted-foreground py-8 text-center" data-testid="dsm-no-project">
            No project loaded. Open a project first.
          </div>
        ) : (
          <div className="flex gap-4 flex-1 overflow-hidden min-h-0">
            {/* Left: Table list */}
            <div className="w-[280px] flex-shrink-0 flex flex-col overflow-hidden border rounded-md">
              <div className="px-3 py-2 border-b bg-muted/30 flex items-center justify-between">
                <span className="text-xs font-medium">Tables ({tables.length})</span>
                <div className="flex items-center gap-1">
                  {onOpenImport && (
                    <Button
                      variant="ghost"
                      size="sm"
                      className="h-6 w-6 p-0"
                      onClick={() => { onOpenChange(false); onOpenImport() }}
                      data-testid="dsm-add-table"
                      title="Add new table"
                    >
                      <Plus className="h-3.5 w-3.5" />
                    </Button>
                  )}
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-6 w-6 p-0"
                    onClick={handleRefreshAll}
                    disabled={loadingRefresh}
                    data-testid="dsm-refresh-all"
                    title="Refresh all tables"
                  >
                    <RefreshCw className={`h-3.5 w-3.5 ${loadingRefresh ? 'animate-spin' : ''}`} />
                  </Button>
                </div>
              </div>

              <div className="flex-1 overflow-y-auto" data-testid="dsm-table-list">
                {loading ? (
                  <div className="text-xs text-muted-foreground p-3">Loading…</div>
                ) : error ? (
                  <div className="text-xs text-destructive p-3">{error}</div>
                ) : tables.length === 0 ? (
                  <div className="text-xs text-muted-foreground p-3">No physical tables found.</div>
                ) : (
                  tables.map((t) => {
                    const name = String(t.name || '')
                    const isSelected = selectedTable === name
                    const src = t.source
                    const sm = (t as any).storage_mode
                    return (
                      <button
                        key={name}
                        className={`w-full text-left px-3 py-2 border-b last:border-b-0 hover:bg-accent/50 transition-colors ${
                          isSelected ? 'bg-accent' : ''
                        }`}
                        onClick={() => handleSelectTable(name)}
                        data-testid={`dsm-table-${name.replace(/\s+/g, '-').toLowerCase()}`}
                      >
                        <div className="flex items-center justify-between">
                          <span className="text-xs font-medium truncate">{name}</span>
                          <div className="flex items-center gap-1 flex-shrink-0">
                            {src?.type && (
                              <span className="text-[10px] px-1 py-0.5 rounded bg-muted text-muted-foreground">
                                {sourceTypeLabel(src.type)}
                              </span>
                            )}
                            <span className="text-[10px] px-1 py-0.5 rounded bg-primary/10 text-primary">
                              {storageModeLabel(sm)}
                            </span>
                          </div>
                        </div>
                        <div className="text-[10px] text-muted-foreground truncate mt-0.5">
                          {sourceDetail(src)}
                        </div>
                      </button>
                    )
                  })
                )}
              </div>
            </div>

            {/* Right: Edit form */}
            <div className="flex-1 overflow-y-auto" data-testid="dsm-edit-panel">
              {!selectedTable ? (
                <div className="flex items-center justify-center h-full text-sm text-muted-foreground">
                  Select a table to view or edit its data source.
                </div>
              ) : editDraft ? (
                <div className="space-y-4">
                  {/* Header */}
                  <div className="flex items-center justify-between">
                    <h3 className="text-sm font-semibold">{selectedTable}</h3>
                    {isDirty && (
                      <span className="text-xs text-orange-500 flex items-center gap-1">
                        <AlertCircle className="h-3 w-3" />
                        Unsaved changes
                      </span>
                    )}
                  </div>

                  {/* Source type selector */}
                  <div className="space-y-1" data-testid="dsm-field-type">
                    <label className="text-xs text-muted-foreground">Source Type</label>
                    <Select
                      value={editDraft.type}
                      onValueChange={(val) => updateDraft('type', val)}
                    >
                      <SelectTrigger className="h-7 text-xs" data-testid="dsm-type-select">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {connectorTypes.map(ct => (
                          <SelectItem key={ct.value} value={ct.value}>{ct.label}</SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>

                  {/* Dynamic params */}
                  {connectorParams
                    .filter(p => p.name !== 'type')
                    .map(param => renderParamField(param))
                  }

                  {/* Storage mode */}
                  <div className="space-y-1" data-testid="dsm-field-storage-mode">
                    <label className="text-xs text-muted-foreground">Storage Mode</label>
                    <Select
                      value={editDraft.storageMode}
                      onValueChange={(val) => updateDraft('storageMode', val)}
                    >
                      <SelectTrigger className="h-7 text-xs" data-testid="dsm-storage-mode-select">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {getAvailableModes(editDraft.type).map(m => (
                          <SelectItem key={m.value} value={m.value}>{m.label}</SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>

                  {/* Test result */}
                  {testResult && (
                    <div
                      className={`text-xs p-2 rounded border ${
                        testResult.connected
                          ? 'border-green-500/30 bg-green-500/10 text-green-700 dark:text-green-400'
                          : 'border-destructive/30 bg-destructive/10 text-destructive'
                      }`}
                      data-testid="dsm-test-result"
                    >
                      <div className="flex items-center gap-1">
                        {testResult.connected ? (
                          <><CheckCircle2 className="h-3.5 w-3.5" /> Connected — {testResult.column_count ?? 0} column(s)</>
                        ) : (
                          <><AlertCircle className="h-3.5 w-3.5" /> {testResult.error || 'Connection failed'}</>
                        )}
                      </div>
                    </div>
                  )}

                  {/* Action buttons */}
                  <div className="flex flex-wrap gap-2 pt-2 border-t">
                    <Button
                      variant="outline"
                      size="sm"
                      className="h-7 text-xs"
                      onClick={handleTest}
                      disabled={loadingTest || !editDraft.path}
                      data-testid="dsm-test-btn"
                    >
                      <TestTube2 className={`h-3.5 w-3.5 mr-1 ${loadingTest ? 'animate-spin' : ''}`} />
                      Test Connection
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      className="h-7 text-xs"
                      onClick={handlePreview}
                      disabled={loadingPreview || !editDraft.path}
                      data-testid="dsm-preview-btn"
                    >
                      <Eye className={`h-3.5 w-3.5 mr-1 ${loadingPreview ? 'animate-spin' : ''}`} />
                      Preview Data
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      className="h-7 text-xs"
                      onClick={handleRefresh}
                      disabled={loadingRefresh}
                      data-testid="dsm-refresh-btn"
                    >
                      <RefreshCw className={`h-3.5 w-3.5 mr-1 ${loadingRefresh ? 'animate-spin' : ''}`} />
                      Refresh
                    </Button>
                    <div className="flex-1" />
                    <Button
                      variant="default"
                      size="sm"
                      className="h-7 text-xs"
                      onClick={handleSave}
                      disabled={loadingSave || !isDirty}
                      data-testid="dsm-save-btn"
                    >
                      <Save className={`h-3.5 w-3.5 mr-1 ${loadingSave ? 'animate-spin' : ''}`} />
                      Save Changes
                    </Button>
                    <Button
                      variant="destructive"
                      size="sm"
                      className="h-7 text-xs"
                      onClick={() => setDeleteConfirm(selectedTable)}
                      disabled={loadingDelete}
                      data-testid="dsm-delete-btn"
                    >
                      <Trash2 className="h-3.5 w-3.5 mr-1" />
                      Delete Table
                    </Button>
                  </div>

                  {/* Delete confirmation */}
                  {deleteConfirm && (
                    <div className="border border-destructive/50 rounded-md p-3 bg-destructive/5" data-testid="dsm-delete-confirm">
                      <p className="text-xs text-destructive font-medium mb-2">
                        Are you sure you want to delete "{deleteConfirm}"? This will remove the table definition from the model. This action cannot be undone.
                      </p>
                      <div className="flex gap-2">
                        <Button
                          variant="destructive"
                          size="sm"
                          className="h-7 text-xs"
                          onClick={handleDelete}
                          disabled={loadingDelete}
                          data-testid="dsm-delete-confirm-yes"
                        >
                          {loadingDelete ? 'Deleting…' : 'Yes, Delete'}
                        </Button>
                        <Button
                          variant="outline"
                          size="sm"
                          className="h-7 text-xs"
                          onClick={() => setDeleteConfirm(null)}
                          data-testid="dsm-delete-confirm-no"
                        >
                          Cancel
                        </Button>
                      </div>
                    </div>
                  )}

                  {/* Preview panel */}
                  {preview && (
                    <div className="space-y-1 pt-2" data-testid="dsm-preview-panel">
                      <div className="text-xs text-muted-foreground">
                        Preview ({preview.row_count ?? preview.rows?.length ?? 0} rows, {preview.columns?.length ?? 0} columns)
                      </div>
                      {renderPreviewTable()}
                    </div>
                  )}
                </div>
              ) : null}
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}

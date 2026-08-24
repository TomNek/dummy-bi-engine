import { useCallback, useEffect, useMemo, useState } from 'react'
import { ChevronDown, ChevronRight, Database, RefreshCw } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
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
  getImportConnectors,
  inspectImportSource,
  previewImportSource,
  listImportTables,
  importPhysicalTable,
  type ImportConnector,
  type ImportConnectorParam,
  type ImportPreviewResult,
  type ImportSource,
  type ImportTableInfo,
} from '@/lib/api'

interface ImportDataDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
}

interface ImportDraft {
  type: string
  name: string
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

const DEFAULT_DRAFT: ImportDraft = {
  type: 'csv',
  name: '',
  path: '',
  format: '',
  auth_mode: 'connection_string',
  schema: '',
  table: '',
  delimiter: ',',
  header: true,
  encoding: '',
  nullstr: '',
  storageMode: 'import',
}

// Source types that support each storage mode (mirrors dax_engine/storage_modes.py)
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

const slugify = (value: string) => value.toLowerCase().replace(/\s+/g, '-').replace(/[^a-z0-9_-]/g, '')

export function ImportDataDialog({ open, onOpenChange }: ImportDataDialogProps) {
  const projectPath = useAppStore((s) => s.projectPath)
  const { reload } = useRuntimeState()

  const [connectors, setConnectors] = useState<ImportConnector[]>([])
  const [tables, setTables] = useState<ImportTableInfo[]>([])
  const [inspectTables, setInspectTables] = useState<Array<{ schema?: string | null; name: string }>>([])
  const [preview, setPreview] = useState<ImportPreviewResult | null>(null)
  const [draft, setDraft] = useState<ImportDraft>({ ...DEFAULT_DRAFT })
  const [selectedCategory, setSelectedCategory] = useState<string>('')
  const [connectorSearch, setConnectorSearch] = useState('')
  const [expandedCategories, setExpandedCategories] = useState<string[]>([])
  const [error, setError] = useState<string | null>(null)
  const [inspectError, setInspectError] = useState<string | null>(null)
  const [tablesError, setTablesError] = useState<string | null>(null)
  const [loadingPreview, setLoadingPreview] = useState(false)
  const [loadingInspect, setLoadingInspect] = useState(false)
  const [loadingImport, setLoadingImport] = useState(false)

  const canUseProject = Boolean(projectPath && projectPath.trim())

  const effectiveConnectors = useMemo<ImportConnector[]>(() => {
    if (connectors.length) return connectors
    return [
      {
        type: 'csv',
        label: 'CSV file',
        category: 'File',
        params: [
          { name: 'path', label: 'File path', required: true, kind: 'path', placeholder: 'data/sales.csv' },
          { name: 'delimiter', label: 'Delimiter', required: false, kind: 'text', placeholder: ',' },
          { name: 'header', label: 'Header', required: false, kind: 'bool' },
          { name: 'encoding', label: 'Encoding', required: false, kind: 'text' },
          { name: 'nullstr', label: 'Null strings (comma-separated)', required: false, kind: 'text' },
        ],
      },
      {
        type: 'parquet',
        label: 'Parquet file',
        category: 'File',
        params: [
          { name: 'path', label: 'File path', required: true, kind: 'path', placeholder: 'data/sales.parquet' },
        ],
      },
      {
        type: 'duckdb',
        label: 'DuckDB file',
        category: 'Database',
        params: [
          { name: 'path', label: 'DB file path', required: true, kind: 'path', placeholder: 'data/my.duckdb' },
          { name: 'schema', label: 'Schema', required: false, kind: 'text', placeholder: 'main' },
          { name: 'table', label: 'Table', required: true, kind: 'text' },
        ],
      },
      {
        type: 'sqlite',
        label: 'SQLite file',
        category: 'Database',
        params: [
          { name: 'path', label: 'DB file path', required: true, kind: 'path', placeholder: 'data/my.sqlite' },
          { name: 'table', label: 'Table', required: true, kind: 'text' },
        ],
      },
    ]
  }, [connectors])

  const categories = useMemo(() => {
    const seen = new Set<string>()
    for (const connector of effectiveConnectors) {
      const category = String(connector.category || 'Other').trim() || 'Other'
      seen.add(category)
    }
    return Array.from(seen).sort((a, b) => a.localeCompare(b))
  }, [effectiveConnectors])

  const connectorsByCategory = useMemo(() => {
    const map = new Map<string, ImportConnector[]>()
    for (const connector of effectiveConnectors) {
      const category = String(connector.category || 'Other').trim() || 'Other'
      const list = map.get(category) ?? []
      list.push(connector)
      map.set(category, list)
    }
    return map
  }, [effectiveConnectors])

  const filteredConnectors = useMemo(() => {
    const term = connectorSearch.trim().toLowerCase()
    if (!term) return effectiveConnectors
    return effectiveConnectors.filter((connector) => {
      const label = String(connector.label || connector.type).toLowerCase()
      const type = String(connector.type || '').toLowerCase()
      const category = String(connector.category || '').toLowerCase()
      return label.includes(term) || type.includes(term) || category.includes(term)
    })
  }, [connectorSearch, effectiveConnectors])

  const filteredCategories = useMemo(() => {
    const map = new Map<string, ImportConnector[]>()
    for (const connector of filteredConnectors) {
      const category = String(connector.category || 'Other').trim() || 'Other'
      const list = map.get(category) ?? []
      list.push(connector)
      map.set(category, list)
    }
    return map
  }, [filteredConnectors])

  const visibleCategories = useMemo(() => {
    return Array.from(filteredCategories.keys()).sort((a, b) => a.localeCompare(b))
  }, [filteredCategories])

  const connectorsInCategory = useMemo(() => {
    const category = selectedCategory || categories[0]
    if (!category) return effectiveConnectors
    return connectorsByCategory.get(category) ?? effectiveConnectors
  }, [connectorsByCategory, effectiveConnectors, categories, selectedCategory])

  const selectedConnector = useMemo(() => {
    const isActive = (connector: ImportConnector) => (connector.status ?? 'active') === 'active'
    const matched = effectiveConnectors.find((c) => c.type === draft.type)
    if (matched && isActive(matched)) return matched
    const firstActiveInCategory = connectorsInCategory.find(isActive)
    if (firstActiveInCategory) return firstActiveInCategory
    const firstActive = effectiveConnectors.find(isActive)
    return firstActive || connectorsInCategory[0] || effectiveConnectors[0]
  }, [effectiveConnectors, connectorsInCategory, draft.type])

  const loadConnectors = useCallback(async () => {
    if (!canUseProject) return
    const { data, error: err } = await getImportConnectors()
    if (err || !data) {
      setConnectors([])
      return
    }
    setConnectors(Array.isArray(data.connectors) ? data.connectors : [])
  }, [canUseProject])

  const loadTables = useCallback(async () => {
    if (!canUseProject) return
    const { data, error: err } = await listImportTables(projectPath ?? undefined)
    if (err || !data) {
      setTables([])
      setTablesError(err || 'Failed to load tables')
      return
    }
    setTables(Array.isArray(data.tables) ? data.tables : [])
    setTablesError(null)
  }, [canUseProject, projectPath])

  useEffect(() => {
    if (!open) return
    setError(null)
    setInspectError(null)
    setTablesError(null)
    setPreview(null)
    setInspectTables([])
    void loadConnectors()
    void loadTables()
  }, [open, loadConnectors, loadTables])

  useEffect(() => {
    if (!open) return
    if (!categories.length) return
    setSelectedCategory((prev) => (prev ? prev : categories[0]))
  }, [open, categories])

  useEffect(() => {
    if (!open) return
    if (!visibleCategories.length) return
    setExpandedCategories((prev) => (prev.length ? prev : [visibleCategories[0]]))
  }, [open, visibleCategories])

  useEffect(() => {
    if (!connectorsInCategory.length) return
    const isActive = (connector: ImportConnector) => (connector.status ?? 'active') === 'active'
    const active = connectorsInCategory.find((c) => c.type === draft.type && isActive(c))
    if (!active) {
      const firstActive = connectorsInCategory.find(isActive)
      if (firstActive) {
        setSourceType(firstActive.type)
      }
    }
  }, [connectorsInCategory, draft.type])

  const setDraftField = (field: keyof ImportDraft, value: string | boolean) => {
    setDraft((prev) => ({ ...prev, [field]: value }))
  }

  const setSourceType = (value: string) => {
    const connector = effectiveConnectors.find((item) => item.type === value)
    const formatOptions = connector?.params?.find((param) => param.name === 'format')?.options ?? []
    const authOptions = connector?.params?.find((param) => param.name === 'auth_mode')?.options ?? []
    if (connector && (connector.status ?? 'active') !== 'active') {
      return
    }
    if (connector?.category) {
      setSelectedCategory(connector.category)
      setExpandedCategories((prev) =>
        prev.includes(connector.category as string) ? prev : [...prev, connector.category as string]
      )
    }
    // Reset storage mode if current mode is not valid for new source type
    const newModes = getAvailableModes(value)
    setDraft((prev) => ({
      ...prev,
      type: value,
      format: formatOptions.includes(prev.format) ? prev.format : formatOptions[0] || '',
      auth_mode: authOptions.includes(prev.auth_mode) ? prev.auth_mode : authOptions[0] || prev.auth_mode,
      schema: value === 'duckdb' || value === 'postgres' || value === 'mysql' ? prev.schema : '',
      table: value === 'duckdb' || value === 'sqlite' || value === 'postgres' || value === 'mysql' ? prev.table : '',
      delimiter: value === 'csv' ? (prev.delimiter || ',') : '',
      encoding: value === 'csv' ? prev.encoding : '',
      nullstr: value === 'csv' ? prev.nullstr : '',
      header: value === 'csv' ? prev.header : true,
      storageMode: newModes.some((m) => m.value === prev.storageMode) ? prev.storageMode : 'import',
    }))
  }

  const buildSourcePayload = (): ImportSource => {
    const type = String(draft.type || '').trim().toLowerCase()
    const src: ImportSource = { type }
    const params = selectedConnector?.params ?? []

    for (const param of params) {
      const key = param.name
      if (!key) continue
      if (key === 'path') {
        if (draft.path) src.path = draft.path
        continue
      }
      if (key === 'format' && draft.format) {
        src.format = draft.format
        continue
      }
      if (key === 'auth_mode' && draft.auth_mode) {
        src.auth_mode = draft.auth_mode
        continue
      }
      if (key === 'delimiter' && draft.delimiter) {
        src.delimiter = draft.delimiter
        continue
      }
      if (key === 'header') {
        src.header = Boolean(draft.header)
        continue
      }
      if (key === 'encoding' && draft.encoding) {
        src.encoding = draft.encoding
        continue
      }
      if (key === 'nullstr' && draft.nullstr) {
        const parts = draft.nullstr
          .split(',')
          .map((part) => part.trim())
          .filter(Boolean)
        src.nullstr = parts.length ? parts : draft.nullstr
        continue
      }
      if (key === 'schema' && draft.schema) {
        src.schema = draft.schema
        continue
      }
      if (key === 'table' && draft.table) {
        src.table = draft.table
        continue
      }
    }

    return src
  }

  const validateRequiredParams = (): string | null => {
    const params = selectedConnector?.params ?? []
    for (const param of params) {
      if (!param.required) continue
      const name = param.name
      if (name === 'path' && !draft.path.trim()) {
        return `${param.label || 'Source path'} is required`
      }
      if (name === 'format' && !draft.format.trim()) {
        return `${param.label || 'Format'} is required`
      }
      if (name === 'table' && !draft.table.trim()) {
        return `${param.label || 'Source table'} is required`
      }
      if (name === 'schema' && !draft.schema.trim()) {
        return `${param.label || 'Schema'} is required`
      }
      if (name === 'delimiter' && !draft.delimiter.trim()) {
        return `${param.label || 'Delimiter'} is required`
      }
      if (name === 'encoding' && !draft.encoding.trim()) {
        return `${param.label || 'Encoding'} is required`
      }
      if (name === 'nullstr' && !draft.nullstr.trim()) {
        return `${param.label || 'Null strings'} is required`
      }
    }
    return null
  }

  const handleInspect = async () => {
    if (!canUseProject) return
    setInspectError(null)
    setInspectTables([])
    setLoadingInspect(true)
    try {
      const payload = { source: buildSourcePayload() }
      const { data, error: err } = await inspectImportSource(payload, projectPath ?? undefined)
      if (err || !data) {
        setInspectError(err || 'Inspect failed')
        return
      }
      const rows = Array.isArray(data.tables) ? data.tables : []
      setInspectTables(rows)
    } finally {
      setLoadingInspect(false)
    }
  }

  const handlePreview = async () => {
    if (!canUseProject) return
    setError(null)
    setPreview(null)
    setLoadingPreview(true)
    try {
      const payload = { source: buildSourcePayload(), limit: 50 }
      const { data, error: err } = await previewImportSource(payload, projectPath ?? undefined)
      if (err || !data) {
        setError(err || 'Preview failed')
        return
      }
      setPreview(data)
    } finally {
      setLoadingPreview(false)
    }
  }

  const handleImport = async () => {
    if (!canUseProject) return
    setError(null)
    if (!draft.name.trim()) {
      setError('Table name is required')
      return
    }
    const paramError = validateRequiredParams()
    if (paramError) {
      setError(paramError)
      return
    }

    setLoadingImport(true)
    try {
      const payload = {
        name: draft.name.trim(),
        source: buildSourcePayload(),
        storage_mode: (draft.storageMode && draft.storageMode !== 'import') ? draft.storageMode : undefined,
      }
      const { data, error: err } = await importPhysicalTable(payload, projectPath ?? undefined)
      if (err || !data) {
        setError(err || 'Import failed')
        return
      }
      toast('Import completed', { variant: 'success' })
      await loadTables()
      await reload()
    } finally {
      setLoadingImport(false)
    }
  }

  const handleClear = () => {
    setDraft({ ...DEFAULT_DRAFT })
    setPreview(null)
    setInspectTables([])
    setError(null)
    setInspectError(null)
  }

  const handleRefresh = async () => {
    await loadConnectors()
    await loadTables()
  }

  const renderPreviewTable = () => {
    if (!preview || !preview.columns) return null
    const columns = preview.columns.map((c) => String(c.name || c))
    const rows = Array.isArray(preview.rows) ? preview.rows : []

    return (
      <table className="w-full text-xs border-collapse">
        <thead>
          <tr>
            {columns.map((col) => (
              <th key={col} className="border px-2 py-1 text-left bg-muted/40">
                {col}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, idx) => {
            const values = Array.isArray(row)
              ? row
              : columns.map((col) => (row as Record<string, unknown>)[col])
            return (
              <tr key={idx}>
                {values.map((val, cidx) => (
                  <td key={`${idx}-${cidx}`} className="border px-2 py-1">
                    {val === null || val === undefined ? '' : String(val)}
                  </td>
                ))}
              </tr>
            )
          })}
        </tbody>
      </table>
    )
  }

  const sourceParams = selectedConnector?.params ?? []

  const renderParamField = (param: ImportConnectorParam) => {
    const name = param?.name || ''
    const label = param?.label || name
    const required = Boolean(param?.required)
    const placeholder = param?.placeholder || ''
    const kind = param?.kind || 'text'

    const fieldValue =
      name === 'path'
        ? draft.path
        : name === 'format'
        ? draft.format
        : name === 'auth_mode'
        ? draft.auth_mode
        : name === 'schema'
        ? draft.schema
        : name === 'table'
        ? draft.table
        : name === 'delimiter'
        ? draft.delimiter
        : name === 'encoding'
        ? draft.encoding
        : name === 'nullstr'
        ? draft.nullstr
        : name === 'header'
        ? draft.header
        : ''

    const setValue = (value: string | boolean) => {
      if (name === 'path') return setDraftField('path', value as string)
      if (name === 'format') return setDraftField('format', value as string)
      if (name === 'auth_mode') return setDraftField('auth_mode', value as string)
      if (name === 'schema') return setDraftField('schema', value as string)
      if (name === 'table') return setDraftField('table', value as string)
      if (name === 'delimiter') return setDraftField('delimiter', value as string)
      if (name === 'encoding') return setDraftField('encoding', value as string)
      if (name === 'nullstr') return setDraftField('nullstr', value as string)
      if (name === 'header') return setDraftField('header', Boolean(value))
      return undefined
    }

    if (kind === 'select') {
      const options = param.options ?? []
      return (
        <div key={name}>
          <label className="text-xs text-muted-foreground">
            {label}{required ? ' *' : ''}
          </label>
          <Select value={String(fieldValue ?? '')} onValueChange={(value) => setValue(value)}>
            <SelectTrigger data-testid={`import-${name}`}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {options.map((option) => (
                <SelectItem key={option} value={option}>
                  {option}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      )
    }

    if (name === 'header' || kind === 'bool') {
      return (
        <div key={name}>
          <label className="text-xs text-muted-foreground">
            {label}{required ? ' *' : ''}
          </label>
          <Select
            value={Boolean(fieldValue) ? 'true' : 'false'}
            onValueChange={(value) => setValue(value === 'true')}
          >
            <SelectTrigger data-testid={`import-${name}`}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="true">True</SelectItem>
              <SelectItem value="false">False</SelectItem>
            </SelectContent>
          </Select>
        </div>
      )
    }

    return (
      <div key={name}>
        <label className="text-xs text-muted-foreground">
          {label}{required ? ' *' : ''}
        </label>
        <Input
          value={String(fieldValue ?? '')}
          onChange={(e) => setValue(e.target.value)}
          placeholder={placeholder}
          data-testid={`import-${name}`}
        />
      </div>
    )
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-3xl" data-testid="import-data-dialog">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Database className="h-5 w-5" />
            Import Data
          </DialogTitle>
          <DialogDescription>
            Add physical tables from supported sources. No changes are saved until you click Import.
          </DialogDescription>
        </DialogHeader>

        <div className="flex items-center justify-between">
          <div className="text-xs text-muted-foreground">
            Project: {projectPath || 'Not loaded'}
          </div>
          <Button
            variant="outline"
            size="sm"
            onClick={handleRefresh}
            disabled={!canUseProject}
            data-testid="import-refresh"
          >
            <RefreshCw className="h-4 w-4 mr-1" />
            Refresh
          </Button>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-[220px_1fr] gap-4">
          <div className="space-y-3" data-testid="import-category-panel">
            <div className="text-xs text-muted-foreground">Connectors</div>
            <Input
              value={connectorSearch}
              onChange={(e) => setConnectorSearch(e.target.value)}
              placeholder="Search connectors..."
              data-testid="import-connector-search"
            />
            <div className="border rounded-md p-2" data-testid="import-category-list">
              {visibleCategories.length === 0 ? (
                <div className="text-xs text-muted-foreground">No connectors match this search.</div>
              ) : (
                <div className="space-y-2">
                  {visibleCategories.map((category) => {
                    const isExpanded = expandedCategories.includes(category)
                    const connectors = filteredCategories.get(category) ?? []
                    return (
                      <div key={category} className="space-y-1">
                        <button
                          type="button"
                          className={`w-full flex items-center justify-between text-xs px-2 py-1 rounded border ${
                            selectedCategory === category
                              ? 'bg-muted border-muted-foreground/40'
                              : 'hover:bg-muted'
                          }`}
                          onClick={() => {
                            setSelectedCategory(category)
                            setExpandedCategories((prev) =>
                              prev.includes(category)
                                ? prev.filter((item) => item !== category)
                                : [...prev, category]
                            )
                          }}
                          data-testid={`import-category-${slugify(category)}`}
                          aria-expanded={isExpanded}
                        >
                          <span>{category}</span>
                          {isExpanded ? (
                            <ChevronDown className="h-3 w-3" />
                          ) : (
                            <ChevronRight className="h-3 w-3" />
                          )}
                        </button>
                        {isExpanded && (
                          <div
                            className="grid gap-1 pl-1"
                            data-testid={`import-category-panel-${slugify(category)}`}
                          >
                            {connectors.map((connector) => {
                              const label = connector.label || connector.type
                              const isActive = (connector.status ?? 'active') === 'active'
                              return (
                                <button
                                  key={connector.type}
                                  type="button"
                                  className={`w-full text-left text-xs px-2 py-1 rounded border ${
                                    connector.type === draft.type && isActive
                                      ? 'bg-muted border-muted-foreground/40'
                                      : isActive
                                      ? 'hover:bg-muted'
                                      : 'opacity-60 cursor-not-allowed'
                                  }`}
                                  onClick={() => {
                                    if (isActive) setSourceType(connector.type)
                                  }}
                                  aria-disabled={!isActive}
                                  data-testid={`import-connector-${slugify(label)}`}
                                >
                                  <span>{label}</span>
                                  {!isActive && (
                                    <span className="ml-2 text-[10px] uppercase text-muted-foreground">
                                      Planned
                                    </span>
                                  )}
                                </button>
                              )
                            })}
                          </div>
                        )}
                      </div>
                    )
                  })}
                </div>
              )}
            </div>
          </div>

          <div className="space-y-4">
            <div>
              <label className="text-xs text-muted-foreground">Selected connector</label>
              <div className="text-xs">
                {selectedConnector?.label || selectedConnector?.type || 'None'}
              </div>
            </div>

            <div>
              <label className="text-xs text-muted-foreground">Model table name</label>
              <Input
                value={draft.name}
                onChange={(e) => setDraftField('name', e.target.value)}
                placeholder="Sales"
                data-testid="import-table-name"
              />
            </div>

            <div>
              <label className="text-xs text-muted-foreground">Storage mode</label>
              <Select
                value={draft.storageMode}
                onValueChange={(val) => setDraftField('storageMode', val)}
              >
                <SelectTrigger className="h-8 text-xs" data-testid="import-storage-mode">
                  <SelectValue placeholder="Import" />
                </SelectTrigger>
                <SelectContent>
                  {getAvailableModes(draft.type).map((m) => (
                    <SelectItem key={m.value} value={m.value} data-testid={`import-storage-mode-${m.value}`}>
                      {m.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <div className="text-[11px] text-muted-foreground mt-1">
                {draft.storageMode === 'direct_query'
                  ? 'Data queried live from source (CREATE VIEW)'
                  : draft.storageMode === 'direct_lake'
                    ? 'Data read from lakehouse files on demand (CREATE VIEW)'
                    : 'Data materialized into DuckDB (CREATE TABLE)'}
              </div>
            </div>

            {sourceParams.length > 0 ? (
              <div className="space-y-3" data-testid="import-source-params">
                {sourceParams.map((param) => renderParamField(param))}
              </div>
            ) : (
              <div className="text-xs text-muted-foreground">
                Select a connector to see required fields.
              </div>
            )}

            <div className="flex flex-wrap gap-2">
              <Button
                variant="outline"
                size="sm"
                onClick={handleInspect}
                disabled={!canUseProject || loadingInspect}
                data-testid="import-inspect"
              >
                {loadingInspect ? 'Listing...' : 'List Tables'}
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={handlePreview}
                disabled={!canUseProject || loadingPreview}
                data-testid="import-preview"
              >
                {loadingPreview ? 'Previewing...' : 'Preview'}
              </Button>
              <Button
                size="sm"
                onClick={handleImport}
                disabled={!canUseProject || loadingImport}
                data-testid="import-save"
              >
                {loadingImport ? 'Importing...' : 'Import'}
              </Button>
              <Button
                variant="ghost"
                size="sm"
                onClick={handleClear}
                data-testid="import-clear"
              >
                Clear
              </Button>
            </div>

            {error && (
              <div className="text-xs text-destructive" data-testid="import-error">
                {error}
              </div>
            )}
            {inspectError && (
              <div className="text-xs text-destructive" data-testid="import-inspect-error">
                {inspectError}
              </div>
            )}

            {inspectTables.length > 0 && (
              <div className="border rounded-md p-2" data-testid="import-inspect-list">
                <div className="text-xs text-muted-foreground mb-2">Available source tables</div>
                <div className="space-y-1">
                  {inspectTables.map((item) => {
                    const schema = String(item.schema || '').trim()
                    const name = String(item.name || '').trim()
                    const label = schema ? `${schema}.${name}` : name
                    const testId = `import-inspect-item-${(schema ? schema + '-' : '') + name}`
                      .replace(/\s+/g, '-')
                      .toLowerCase()
                    return (
                      <button
                        key={label}
                        className="w-full text-left text-xs px-2 py-1 rounded hover:bg-muted"
                        onClick={() => {
                          setDraft((prev) => ({
                            ...prev,
                            table: name,
                            schema: schema || prev.schema,
                          }))
                        }}
                        data-testid={testId}
                      >
                        {label}
                      </button>
                    )
                  })}
                </div>
              </div>
            )}
          </div>

          <div className="space-y-4">
            <div className="border rounded-md p-2" data-testid="import-preview-panel" style={{ display: preview ? 'block' : 'none' }}>
              <div className="text-xs text-muted-foreground" data-testid="import-preview-status">
                {preview ? `OK (rows=${preview.row_count ?? 0})` : ''}
              </div>
              <div className="mt-2" data-testid="import-preview-grid">
                {renderPreviewTable()}
              </div>
            </div>

            <div className="border rounded-md p-2">
              <div className="text-xs text-muted-foreground mb-2">Existing Tables</div>
              <div className="space-y-1" data-testid="import-table-list">
                {tables.length === 0 ? (
                  <div className="text-xs text-muted-foreground">No physical tables found.</div>
                ) : (
                  tables.map((t) => {
                    const name = String(t.name || '')
                    const testId = `import-table-item-${name.replace(/\s+/g, '-').toLowerCase()}`
                    const src = t.source
                    let detail = ''
                    if (src?.type === 'csv' || src?.type === 'parquet') {
                      detail = `${src.type} • ${src.path || ''}`
                    } else if (src?.type === 'duckdb' || src?.type === 'sqlite') {
                      detail = `${src.type} • ${src.path || ''}${src.table ? ` • ${src.table}` : ''}`
                    }
                    return (
                      <div key={name} className="rounded border px-2 py-1" data-testid={testId}>
                        <div className="text-xs font-medium">{name}</div>
                        {detail && <div className="text-[11px] text-muted-foreground">{detail}</div>}
                      </div>
                    )
                  })
                )}
              </div>
              {tablesError && (
                <div className="text-xs text-destructive mt-2" data-testid="import-table-error">
                  {tablesError}
                </div>
              )}
            </div>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}

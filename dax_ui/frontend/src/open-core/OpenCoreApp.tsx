import { lazy, Suspense, useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import {
  BarChart3,
  Braces,
  ChevronRight,
  CircleCheck,
  Database,
  FileSpreadsheet,
  LoaderCircle,
  Play,
  RefreshCw,
  Sigma,
  Table2,
  Unplug,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { Textarea } from '@/components/ui/textarea'
import {
  compileDax,
  getConnectors,
  getRows,
  getRuntime,
  getTables,
  importTable,
  type Connector,
  type DataTable,
  type Relationship,
  type RuntimeState,
} from './api'
import { buildTraces, CHART_SPECS, CHART_TYPES, filterRows, type ChartType } from './charts'

const Plot = lazy(() => import('react-plotly.js'))
const EMPTY = '__none__'

function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : 'Unexpected error'
}

function FieldSelect({
  value,
  columns,
  placeholder,
  allowNone = false,
  onChange,
}: {
  value: string
  columns: string[]
  placeholder: string
  allowNone?: boolean
  onChange: (value: string) => void
}) {
  return (
    <Select value={value || (allowNone ? EMPTY : undefined)} onValueChange={(next) => onChange(next === EMPTY ? '' : next)}>
      <SelectTrigger aria-label={placeholder}>
        <SelectValue placeholder={placeholder} />
      </SelectTrigger>
      <SelectContent>
        <SelectGroup>
          {allowNone ? <SelectItem value={EMPTY}>None</SelectItem> : null}
          {columns.map((column) => <SelectItem key={column} value={column}>{column}</SelectItem>)}
        </SelectGroup>
      </SelectContent>
    </Select>
  )
}

function SectionTitle({ icon, children }: { icon: ReactNode; children: ReactNode }) {
  return <h2 className="section-title">{icon}<span>{children}</span></h2>
}

function ModelTree({ state }: { state: RuntimeState | null }) {
  if (!state) return <p className="muted-copy">Open a project to inspect its semantic model.</p>
  return (
    <div className="model-tree">
      {state.fields.tables.map((table) => (
        <details key={table.name} open={state.fields.tables.length < 5}>
          <summary><ChevronRight data-icon="inline-start" /> <Table2 data-icon="inline-start" /> {table.name}</summary>
          <div className="tree-children">
            {table.columns.map((column) => <span key={column}>{column}</span>)}
          </div>
        </details>
      ))}
      <details open>
        <summary><ChevronRight data-icon="inline-start" /> <Sigma data-icon="inline-start" /> Measures</summary>
        <div className="tree-children">
          {state.fields.measures.length
            ? state.fields.measures.map((measure) => <span key={measure}>{measure}</span>)
            : <span className="muted-copy">No measures yet</span>}
        </div>
      </details>
    </div>
  )
}

function RelationshipList({ relationships }: { relationships: Relationship[] }) {
  if (!relationships.length) return <p className="muted-copy">No relationships defined.</p>
  return (
    <div className="relationship-list">
      {relationships.map((rel, index) => (
        <div key={`${rel.from_table}-${rel.from_column}-${index}`}>
          <span>{rel.from_table}.{rel.from_column}</span>
          <ChevronRight />
          <span>{rel.to_table}.{rel.to_column}</span>
        </div>
      ))}
    </div>
  )
}

export function OpenCoreApp() {
  const [project, setProject] = useState('')
  const [state, setState] = useState<RuntimeState | null>(null)
  const [tables, setTables] = useState<DataTable[]>([])
  const [selectedTable, setSelectedTable] = useState('')
  const [rows, setRows] = useState<Record<string, unknown>[]>([])
  const [columns, setColumns] = useState<string[]>([])
  const [chartFields, setChartFields] = useState<Record<string, string>>({})
  const [chartType, setChartType] = useState<ChartType>('column')
  const [title, setTitle] = useState('Data preview')
  const [showLegend, setShowLegend] = useState(true)
  const [filterField, setFilterField] = useState('')
  const [filterOperator, setFilterOperator] = useState('equals')
  const [filterValue, setFilterValue] = useState('')
  const [dax, setDax] = useState('SUM(Sales[Amount])')
  const [sql, setSql] = useState('-- Compile a DAX expression to inspect generated SQL.')
  const [compileValue, setCompileValue] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)
  const [status, setStatus] = useState('Ready')
  const [error, setError] = useState('')
  const [connectors, setConnectors] = useState<Connector[]>([])
  const [connectionType, setConnectionType] = useState('csv')
  const [sourceValues, setSourceValues] = useState<Record<string, unknown>>({ path: 'data/Sales.csv' })
  const [newTableName, setNewTableName] = useState('ImportedData')

  const loadRows = useCallback(async (projectPath: string, tableName: string, metadata: DataTable[]) => {
    const result = await getRows(projectPath, tableName)
    const nextColumns = result.columns
    const tableMeta = metadata.find((item) => item.name === tableName)
    const numeric = tableMeta?.columns.find((column) => /INT|DECIMAL|DOUBLE|FLOAT|NUMERIC|REAL/i.test(column.type))?.name
    setRows(result.rows)
    setColumns(nextColumns)
    const first = nextColumns[0] ?? ''
    const second = numeric ?? nextColumns[1] ?? first
    const third = nextColumns[2] ?? second
    setChartFields({
      x: first, y: second, y2: third, names: first, values: second, path: first,
      r: second, theta: first, z: third, size: second, value: second,
      open: second, high: second, low: second, close: second,
      source: first, target: nextColumns[1] ?? first, reference: third,
    })
    setFilterField('')
    setTitle(`${tableName} preview`)
  }, [])

  const loadProject = useCallback(async (projectPath: string) => {
    setBusy(true)
    setError('')
    setStatus('Loading local project…')
    try {
      const [runtime, tableList, connectorList] = await Promise.all([
        getRuntime(projectPath), getTables(projectPath), getConnectors(),
      ])
      setState(runtime)
      setProject(runtime.project)
      setTables(tableList)
      setConnectors(connectorList)
      const first = tableList[0]?.name ?? runtime.fields.tables[0]?.name ?? ''
      setSelectedTable(first)
      if (first) await loadRows(projectPath, first, tableList)
      setStatus(`Loaded ${runtime.fields.tables.length} tables locally`)
    } catch (loadError) {
      setError(errorMessage(loadError))
      setStatus('Project could not be loaded')
    } finally {
      setBusy(false)
    }
  }, [loadRows])

  useEffect(() => { void loadProject('') }, [loadProject])

  const selectTable = async (tableName: string) => {
    setSelectedTable(tableName)
    setBusy(true)
    setError('')
    try {
      await loadRows(project, tableName, tables)
      setStatus(`Previewing ${tableName}`)
    } catch (loadError) {
      setError(errorMessage(loadError))
    } finally {
      setBusy(false)
    }
  }

  const runCompiler = async () => {
    setBusy(true)
    setError('')
    setStatus('Compiling DAX…')
    try {
      const result = await compileDax(project, dax)
      setSql(result.sql)
      setCompileValue(result.value)
      setStatus('DAX compiled and evaluated')
    } catch (compileError) {
      setError(errorMessage(compileError))
      setStatus('Compilation failed')
    } finally {
      setBusy(false)
    }
  }

  const connectData = async () => {
    setBusy(true)
    setError('')
    setStatus('Importing local data…')
    try {
      await importTable(project, {
        name: newTableName,
        type: connectionType,
        source: Object.fromEntries(Object.entries(sourceValues).filter(([, value]) => value !== '')),
      })
      await loadProject(project)
      setStatus(`${newTableName} imported`)
    } catch (connectionError) {
      setError(errorMessage(connectionError))
      setStatus('Import failed')
      setBusy(false)
    }
  }

  const visibleRows = useMemo(
    () => filterRows(rows, filterField, filterOperator, filterValue),
    [filterField, filterOperator, filterValue, rows],
  )
  const traces = useMemo(() => buildTraces(visibleRows, chartType, chartFields), [chartFields, chartType, visibleRows])
  const selectedConnector = connectors.find((connector) => connector.type === connectionType)

  return (
    <main className="app-shell">
      <header className="topbar">
        <div className="brand">
          <Braces />
          <div><strong>DAX to SQL</strong><span>Open-core workbench</span></div>
        </div>
        <div className="project-picker">
          <Input value={project} onChange={(event) => setProject(event.target.value)} aria-label="Project path" />
          <Button onClick={() => void loadProject(project)} disabled={busy}>
            {busy ? <LoaderCircle data-icon="inline-start" className="spin" /> : <RefreshCw data-icon="inline-start" />}
            Open project
          </Button>
        </div>
        <div className="local-badge"><CircleCheck /> Local only</div>
      </header>

      <div className="workspace">
        <aside className="left-panel">
          <section>
            <SectionTitle icon={<Database />}>Data connection</SectionTitle>
            <p className="muted-copy">All project connectors are available. Credentials are used locally and are never sent as telemetry.</p>
            <label>Source type</label>
            <Select value={connectionType} onValueChange={setConnectionType}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent><SelectGroup>
                {connectors.map((connector) => <SelectItem key={connector.type} value={connector.type}>{connector.label}</SelectItem>)}
              </SelectGroup></SelectContent>
            </Select>
            {selectedConnector?.params.map((param) => <div key={param.name}>
              <label>{param.label}{param.required ? ' *' : ''}</label>
              {param.kind === 'select' && param.options?.length ? (
                <Select value={String(sourceValues[param.name] || param.options[0])} onValueChange={(value) => setSourceValues((current) => ({ ...current, [param.name]: value }))}>
                  <SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent><SelectGroup>{param.options.map((option) => <SelectItem key={option} value={option}>{option}</SelectItem>)}</SelectGroup></SelectContent>
                </Select>
              ) : param.kind === 'bool' ? (
                <div className="switch-row connector-switch">
                  <span>{sourceValues[param.name] ? 'Enabled' : 'Disabled'}</span>
                  <Switch checked={Boolean(sourceValues[param.name])} onCheckedChange={(value) => setSourceValues((current) => ({ ...current, [param.name]: value }))} />
                </div>
              ) : (
                <Input
                  type={param.kind === 'password' ? 'password' : param.kind === 'number' ? 'number' : 'text'}
                  value={String(sourceValues[param.name] ?? '')}
                  onChange={(event) => setSourceValues((current) => ({ ...current, [param.name]: event.target.value }))}
                  placeholder={param.placeholder}
                />
              )}
            </div>)}
            <label>Model table name</label>
            <Input value={newTableName} onChange={(event) => setNewTableName(event.target.value)} />
            <Button className="full-width" variant="outline" onClick={() => void connectData()} disabled={busy || !sourceValues.path || !newTableName}>
              <FileSpreadsheet data-icon="inline-start" /> Connect data
            </Button>
          </section>

          <section className="grow-section">
            <SectionTitle icon={<Table2 />}>Semantic model</SectionTitle>
            <ModelTree state={state} />
          </section>

          <section>
            <SectionTitle icon={<Unplug />}>Relationships</SectionTitle>
            <RelationshipList relationships={state?.relationships ?? []} />
          </section>
        </aside>

        <section className="center-panel">
          <div className="compiler-pane">
            <div className="pane-heading">
              <div><span className="eyebrow">Compiler</span><h1>DAX → SQL</h1></div>
              <Button onClick={() => void runCompiler()} disabled={busy || !dax.trim()}>
                <Play data-icon="inline-start" /> Compile
              </Button>
            </div>
            <div className="editor-grid">
              <div>
                <label>DAX expression</label>
                <Textarea value={dax} onChange={(event) => setDax(event.target.value)} spellCheck={false} />
              </div>
              <div>
                <label>Generated SQL</label>
                <pre>{sql}</pre>
                {compileValue !== null ? <span className="result-pill">Result: {String(compileValue)}</span> : null}
              </div>
            </div>
          </div>

          <div className="chart-pane">
            <div className="pane-heading">
              <div><span className="eyebrow">Plotly preview</span><h2>{title || 'Untitled chart'}</h2></div>
              <span className="row-count">{visibleRows.length} / {rows.length} rows</span>
            </div>
            <div className="plot-wrap">
              {traces.length ? (
                <Suspense fallback={<div className="empty-chart"><LoaderCircle className="spin" /> Loading Plotly…</div>}>
                  <Plot
                    data={traces}
                    layout={{
                      autosize: true,
                      margin: { l: 52, r: 22, t: 12, b: 44 },
                      paper_bgcolor: 'transparent',
                      plot_bgcolor: 'transparent',
                      font: { family: 'Inter, ui-sans-serif, system-ui', color: '#3d3a4c', size: 12 },
                      showlegend: showLegend,
                      legend: { orientation: 'h', y: 1.08 },
                      xaxis: { gridcolor: '#ebe8f4', zerolinecolor: '#d9d4e8' },
                      yaxis: { gridcolor: '#ebe8f4', zerolinecolor: '#d9d4e8' },
                    }}
                    config={{ responsive: true, displaylogo: false, modeBarButtonsToRemove: ['toImage', 'sendDataToCloud'] }}
                    useResizeHandler
                    className="plot"
                  />
                </Suspense>
              ) : <div className="empty-chart"><BarChart3 /> Choose a table and fields to preview a chart.</div>}
            </div>
          </div>

          <div className="data-pane">
            <div className="pane-heading compact">
              <div><span className="eyebrow">Validation</span><h2>Data preview</h2></div>
              <Select value={selectedTable || undefined} onValueChange={(value) => void selectTable(value)}>
                <SelectTrigger className="table-picker"><SelectValue placeholder="Select table" /></SelectTrigger>
                <SelectContent><SelectGroup>
                  {tables.map((table) => <SelectItem key={table.name} value={table.name}>{table.name} ({table.row_count})</SelectItem>)}
                </SelectGroup></SelectContent>
              </Select>
            </div>
            <div className="table-scroll">
              <table>
                <thead><tr>{columns.map((column) => <th key={column}>{column}</th>)}</tr></thead>
                <tbody>{visibleRows.slice(0, 20).map((row, index) => (
                  <tr key={index}>{columns.map((column) => <td key={column}>{String(row[column] ?? '')}</td>)}</tr>
                ))}</tbody>
              </table>
            </div>
          </div>
        </section>

        <aside className="right-panel">
          <section>
            <SectionTitle icon={<BarChart3 />}>Visual</SectionTitle>
            <p className="muted-copy">All {CHART_TYPES.length} existing Plotly visual types are included.</p>
            <Select value={chartType} onValueChange={(value) => setChartType(value as ChartType)}>
              <SelectTrigger aria-label="Plotly visual type"><SelectValue /></SelectTrigger>
              <SelectContent><SelectGroup>
                {CHART_TYPES.map((type) => <SelectItem key={type} value={type}>{CHART_SPECS[type].label}</SelectItem>)}
              </SelectGroup></SelectContent>
            </Select>
          </section>

          <section>
            <SectionTitle icon={<Table2 />}>Fields</SectionTitle>
            {CHART_SPECS[chartType].slots.map((slot) => {
              const optional = ['color', 'size', 'reference', 'measure', 'y2'].includes(slot)
              return <div key={slot}>
                <label>{slot.replace('_', ' ')}</label>
                <FieldSelect
                  value={chartFields[slot] ?? ''}
                  columns={columns}
                  placeholder={`${optional ? 'Optional ' : ''}${slot} field`}
                  allowNone={optional}
                  onChange={(value) => setChartFields((current) => ({ ...current, [slot]: value }))}
                />
              </div>
            })}
          </section>

          <section>
            <SectionTitle icon={<Sigma />}>Filter</SectionTitle>
            <label>Field</label>
            <FieldSelect value={filterField} columns={columns} placeholder="No filter" allowNone onChange={setFilterField} />
            <div className="split-fields">
              <Select value={filterOperator} onValueChange={setFilterOperator}>
                <SelectTrigger aria-label="Filter operator"><SelectValue /></SelectTrigger>
                <SelectContent><SelectGroup>
                  <SelectItem value="equals">Equals</SelectItem>
                  <SelectItem value="contains">Contains</SelectItem>
                  <SelectItem value="gt">Greater than</SelectItem>
                  <SelectItem value="lt">Less than</SelectItem>
                </SelectGroup></SelectContent>
              </Select>
              <Input value={filterValue} onChange={(event) => setFilterValue(event.target.value)} placeholder="Value" />
            </div>
          </section>

          <section>
            <SectionTitle icon={<Braces />}>Format</SectionTitle>
            <label>Chart title</label>
            <Input value={title} onChange={(event) => setTitle(event.target.value)} />
            <div className="switch-row"><span>Show legend</span><Switch checked={showLegend} onCheckedChange={setShowLegend} /></div>
          </section>
        </aside>
      </div>

      <footer className="statusbar">
        <span className={error ? 'error-status' : ''}>{error || status}</span>
        <span>Open-core MVP · Plotly only · No telemetry</span>
      </footer>
    </main>
  )
}

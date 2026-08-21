const BASE_URL = '/runtime'

declare global {
  interface Window {
    __DESKTOP_TOKEN__?: string
  }
}

export interface ModelTable {
  name: string
  columns: string[]
}

export interface Relationship {
  from_table: string
  from_column: string
  to_table: string
  to_column: string
  active: boolean
}

export interface RuntimeState {
  project: string
  fields: { tables: ModelTable[]; measures: string[] }
  relationships?: Relationship[]
}

export interface DataColumn {
  name: string
  type: string
}

export interface DataTable {
  name: string
  columns: DataColumn[]
  row_count: number
}

export interface TableRows {
  table: string
  columns: string[]
  rows: Record<string, unknown>[]
  total_rows: number
}

export interface ConnectorParam {
  name: string
  label: string
  required?: boolean
  kind?: 'text' | 'password' | 'select' | 'number' | 'path' | 'bool'
  placeholder?: string
  options?: string[]
}

export interface Connector {
  type: string
  label: string
  category: string
  status: string
  params: ConnectorParam[]
}

interface Envelope<T> {
  ok?: boolean
  data?: T
  error?: string
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(`${BASE_URL}${path}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      'X-Requested-With': 'open-core-mvp',
      ...(window.__DESKTOP_TOKEN__ ? { 'X-Desktop-Token': window.__DESKTOP_TOKEN__ } : {}),
      ...options.headers,
    },
  })
  const payload = (await response.json().catch(() => ({}))) as Envelope<T>
  if (!response.ok || payload.ok === false) {
    throw new Error(payload.error || `Request failed with HTTP ${response.status}`)
  }
  return (payload.data ?? payload) as T
}

function query(project: string): string {
  return `?project=${encodeURIComponent(project)}`
}

export function getRuntime(project: string) {
  return request<RuntimeState>(query(project))
}

export async function getConnectors(): Promise<Connector[]> {
  const result = await request<{ connectors: Connector[] }>('/data_sources/connectors')
  return result.connectors
}

export async function getTables(project: string): Promise<DataTable[]> {
  const result = await request<{ tables: DataTable[] }>(`/data/tables${query(project)}`)
  return result.tables
}

export function getRows(project: string, table: string) {
  const params = new URLSearchParams({ project, page: '1', page_size: '100' })
  return request<TableRows>(`/data/table/${encodeURIComponent(table)}/rows?${params}`)
}

export function compileDax(project: string, dax: string) {
  return request<{ name: string; sql: string; value: unknown }>(`/measures/validate${query(project)}`, {
    method: 'POST',
    body: JSON.stringify({ dax }),
  })
}

export function importTable(
  project: string,
  input: { name: string; type: string; source: Record<string, unknown> },
) {
  return request<{ table: DataTable }>(`/tables/import${query(project)}`, {
    method: 'POST',
    body: JSON.stringify({
      name: input.name,
      storage_mode: 'import',
      source: { type: input.type, ...input.source },
    }),
  })
}

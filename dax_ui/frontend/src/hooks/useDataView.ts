/**
 * useDataView — Data fetching, pagination, sorting, filtering for Data View
 */
import { useState, useCallback, useRef, useEffect, useMemo } from 'react'
import { useAppStore } from '@/stores'
import {
  getDataViewTables,
  getDataViewRows,
  getDataViewProfile,
  getDataViewColumnValues,
  setColumnSortBy,
  type DataViewTableInfo,
  type DataViewRowsResponse,
  type DataViewProfileResponse,
  type ColumnProfile,
} from '@/lib/api'

export type { ColumnProfile }

export interface ColumnFilter {
  values?: string[]
  op?: string
  value?: string
}

export interface DataViewState {
  tables: DataViewTableInfo[]
  tablesLoading: boolean
  tablesError: string | null
  selectedTable: string | null
  setSelectedTable: (name: string | null) => void
  rows: Record<string, unknown>[]
  columns: string[]
  rowsLoading: boolean
  rowsError: string | null
  page: number
  pageSize: number
  totalRows: number
  totalPages: number
  setPage: (page: number) => void
  setPageSize: (size: number) => void
  sortColumn: string | null
  sortDir: 'asc' | 'desc' | null
  setSorting: (column: string | null, dir: 'asc' | 'desc' | null) => void
  toggleSort: (column: string) => void
  filters: Record<string, ColumnFilter>
  setColumnFilter: (column: string, filter: ColumnFilter | null) => void
  clearAllFilters: () => void
  selectedColumn: string | null
  setSelectedColumn: (col: string | null) => void
  profile: DataViewProfileResponse | null
  profileLoading: boolean
  selectedColumnProfile: ColumnProfile | null
  filterValues: string[]
  filterValuesLoading: boolean
  loadFilterValues: (column: string, search?: string) => void
  refreshTables: () => void
  refreshRows: () => void
  sortByMap: Record<string, string | null>
  allTableColumns: string[]
  handleSetSortByColumn: (column: string, sortByColumn: string | null) => void
}

export function useDataView(): DataViewState {
  const projectPath = useAppStore(s => s.projectPath)
  const currentRole = useAppStore(s => s.currentRole)

  const [tables, setTables] = useState<DataViewTableInfo[]>([])
  const [tablesLoading, setTablesLoading] = useState(false)
  const [tablesError, setTablesError] = useState<string | null>(null)
  const [selectedTable, setSelectedTableRaw] = useState<string | null>(null)
  const [rows, setRows] = useState<Record<string, unknown>[]>([])
  const [columns, setColumns] = useState<string[]>([])
  const [rowsLoading, setRowsLoading] = useState(false)
  const [rowsError, setRowsError] = useState<string | null>(null)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(100)
  const [totalRows, setTotalRows] = useState(0)
  const [totalPages, setTotalPages] = useState(0)
  const [sortColumn, setSortColumn] = useState<string | null>(null)
  const [sortDir, setSortDir] = useState<'asc' | 'desc' | null>(null)
  const [filters, setFilters] = useState<Record<string, ColumnFilter>>({})
  const [selectedColumn, setSelectedColumn] = useState<string | null>(null)
  const [profile, setProfile] = useState<DataViewProfileResponse | null>(null)
  const [profileLoading, setProfileLoading] = useState(false)
  const [filterValues, setFilterValues] = useState<string[]>([])
  const [filterValuesLoading, setFilterValuesLoading] = useState(false)

  const fetchIdRef = useRef(0)

  const refreshTables = useCallback(async () => {
    setTablesLoading(true)
    setTablesError(null)
    const res = await getDataViewTables(projectPath || undefined, currentRole || undefined)
    if (res.error) {
      setTablesError(res.error)
      setTablesLoading(false)
      return
    }
    setTables(res.data?.tables || [])
    setTablesLoading(false)
  }, [projectPath, currentRole])

  const refreshRows = useCallback(async () => {
    if (!selectedTable) return
    const id = ++fetchIdRef.current
    setRowsLoading(true)
    setRowsError(null)

    const filterPayload: Record<string, unknown> = {}
    for (const [col, f] of Object.entries(filters)) {
      if (f.values && f.values.length > 0) {
        filterPayload[col] = f.values
      } else if (f.op && f.value !== undefined) {
        filterPayload[col] = { op: f.op, value: f.value }
      }
    }

    const res = await getDataViewRows(selectedTable, {
      project: projectPath || undefined,
      role: currentRole || undefined,
      page,
      pageSize,
      sortColumn: sortColumn || undefined,
      sortDir: sortDir || undefined,
      filters: Object.keys(filterPayload).length > 0 ? filterPayload : undefined,
    })

    if (id !== fetchIdRef.current) return
    if (res.error) {
      setRowsError(res.error)
      setRowsLoading(false)
      return
    }
    const data = res.data as DataViewRowsResponse | undefined
    if (!data) {
      setRowsError('No data returned')
      setRowsLoading(false)
      return
    }
    setRows(data.rows || [])
    setColumns(data.columns || [])
    setTotalRows(data.total_rows ?? 0)
    setTotalPages(data.total_pages ?? 1)
    setRowsLoading(false)
  }, [selectedTable, projectPath, currentRole, page, pageSize, sortColumn, sortDir, filters])

  const loadProfile = useCallback(async (tableName: string) => {
    setProfileLoading(true)
    const res = await getDataViewProfile(tableName, projectPath || undefined, currentRole || undefined)
    if (res.error) {
      setProfileLoading(false)
      return
    }
    setProfile(res.data || null)
    setProfileLoading(false)
  }, [projectPath, currentRole])

  const loadFilterValues = useCallback(async (column: string, search?: string) => {
    if (!selectedTable) return
    setFilterValuesLoading(true)
    const res = await getDataViewColumnValues(selectedTable, column, {
      project: projectPath || undefined,
      role: currentRole || undefined,
      q: search,
      limit: 100,
    })
    setFilterValues(res.data?.values || [])
    setFilterValuesLoading(false)
  }, [selectedTable, projectPath, currentRole])

  const setSelectedTable = useCallback((name: string | null) => {
    setSelectedTableRaw(name)
    setPage(1)
    setSortColumn(null)
    setSortDir(null)
    setFilters({})
    setSelectedColumn(null)
    setProfile(null)
    setRows([])
    setColumns([])
  }, [])

  useEffect(() => {
    if (projectPath) {
      refreshTables()
    }
  }, [projectPath, currentRole, refreshTables])

  useEffect(() => {
    if (selectedTable) {
      refreshRows()
    }
  }, [selectedTable, page, pageSize, sortColumn, sortDir, filters, refreshRows])

  useEffect(() => {
    if (selectedTable) {
      loadProfile(selectedTable)
    }
  }, [selectedTable, loadProfile])

  const setSorting = useCallback((column: string | null, dir: 'asc' | 'desc' | null) => {
    setSortColumn(column)
    setSortDir(dir)
    setPage(1)
  }, [])

  const toggleSort = useCallback((column: string) => {
    setSortColumn(prev => {
      if (prev === column) {
        setSortDir(prevDir => {
          if (prevDir === 'asc') return 'desc'
          if (prevDir === 'desc') {
            setSortColumn(null)
            return null
          }
          return 'asc'
        })
        return prev
      }
      setSortDir('asc')
      return column
    })
    setPage(1)
  }, [])

  const setColumnFilter = useCallback((column: string, filter: ColumnFilter | null) => {
    setFilters(prev => {
      const next = { ...prev }
      if (filter === null) {
        delete next[column]
      } else {
        next[column] = filter
      }
      return next
    })
    setPage(1)
  }, [])

  const clearAllFilters = useCallback(() => {
    setFilters({})
    setPage(1)
  }, [])

  const selectedColumnProfile = selectedColumn && profile
    ? (profile.profiles.find((p: ColumnProfile) => p.name === selectedColumn) || null)
    : null

  // Compute sort-by-column map from table metadata
  const selectedTableInfo = tables.find(t => t.name === selectedTable)
  const sortByMap = useMemo(() => {
    if (!selectedTableInfo) return {}
    const map: Record<string, string | null> = {}
    for (const col of selectedTableInfo.columns) {
      if (col.sort_by_column) map[col.name] = col.sort_by_column
    }
    return map
  }, [selectedTableInfo])

  const allTableColumns = useMemo(() => {
    if (!selectedTableInfo) return []
    return selectedTableInfo.columns.map(c => c.name)
  }, [selectedTableInfo])

  const handleSetSortByColumn = useCallback(async (column: string, sortByColumn: string | null) => {
    if (!selectedTable) return
    const res = await setColumnSortBy(selectedTable, column, sortByColumn, projectPath || undefined)
    if (res.error) {
      alert(`Sort-by-column error: ${res.error}`)
      return
    }
    // Refresh tables to pick up updated sort_by_column
    refreshTables()
  }, [selectedTable, projectPath, refreshTables])

  return {
    tables,
    tablesLoading,
    tablesError,
    selectedTable,
    setSelectedTable,
    rows,
    columns,
    rowsLoading,
    rowsError,
    page,
    pageSize,
    totalRows,
    totalPages,
    setPage,
    setPageSize,
    sortColumn,
    sortDir,
    setSorting,
    toggleSort,
    filters,
    setColumnFilter,
    clearAllFilters,
    selectedColumn,
    setSelectedColumn,
    profile,
    profileLoading,
    selectedColumnProfile,
    filterValues,
    filterValuesLoading,
    loadFilterValues,
    refreshTables,
    refreshRows,
    sortByMap,
    allTableColumns,
    handleSetSortByColumn,
  }
}

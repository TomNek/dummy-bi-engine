import { useCallback, useState } from 'react'
import { useAppStore } from '@/stores'
import {
  listMeasures,
  createMeasure,
  updateMeasure,
  deleteMeasure,
  validateMeasure,
  listCalcTables,
  createCalcTable,
  updateCalcTable,
  deleteCalcTable,
  previewCalcTable,
  listCalcColumns,
  createCalcColumn,
  updateCalcColumn,
  deleteCalcColumn,
  type MeasureDetail,
  type CalcTableDetail,
  type CalcColumnDetail,
} from '@/lib/api'

export function useModelAuthoring() {
  const projectPath = useAppStore(s => s.projectPath)
  const currentRole = useAppStore(s => s.currentRole)
  
  // Loading states
  const [measuresLoading, setMeasuresLoading] = useState(false)
  const [calcTablesLoading, setCalcTablesLoading] = useState(false)
  const [calcColumnsLoading, setCalcColumnsLoading] = useState(false)
  
  // Data states
  const [measures, setMeasures] = useState<MeasureDetail[]>([])
  const [calcTables, setCalcTables] = useState<CalcTableDetail[]>([])
  const [calcColumns, setCalcColumns] = useState<CalcColumnDetail[]>([])
  
  // Error states
  const [error, setError] = useState<string | null>(null)

  // === Measures ===
  
  const loadMeasures = useCallback(async () => {
    if (!projectPath) return
    
    setMeasuresLoading(true)
    setError(null)
    
    try {
      const { data, error: apiError } = await listMeasures(projectPath, currentRole ?? undefined)
      if (apiError || !data) {
        setError(apiError || 'Failed to load measures')
        return
      }
      setMeasures(data.measures)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load measures')
    } finally {
      setMeasuresLoading(false)
    }
  }, [projectPath, currentRole])

  const saveMeasure = useCallback(async (measure: MeasureDetail, isNew: boolean) => {
    if (!projectPath) return { success: false, error: 'No project loaded' }
    
    try {
      const { data, error: apiError } = isNew
        ? await createMeasure(measure, projectPath)
        : await updateMeasure(measure.name, measure, projectPath)
      
      if (apiError || !data) {
        return { success: false, error: apiError || 'Failed to save measure' }
      }
      
      // Reload measures list
      await loadMeasures()
      return { success: true, measure: data.measure }
    } catch (err) {
      return { success: false, error: err instanceof Error ? err.message : 'Failed to save measure' }
    }
  }, [projectPath, loadMeasures])

  const removeMeasure = useCallback(async (name: string) => {
    if (!projectPath) return { success: false, error: 'No project loaded' }
    
    try {
      const { error: apiError } = await deleteMeasure(name, projectPath)
      if (apiError) {
        return { success: false, error: apiError }
      }
      
      // Reload measures list
      await loadMeasures()
      return { success: true }
    } catch (err) {
      return { success: false, error: err instanceof Error ? err.message : 'Failed to delete measure' }
    }
  }, [projectPath, loadMeasures])

  const checkMeasure = useCallback(async (dax: string) => {
    if (!projectPath) return { valid: false, error: 'No project loaded' }
    
    try {
      const { data, error: apiError } = await validateMeasure(dax, projectPath, currentRole ?? undefined)
      if (apiError || !data) {
        return { valid: false, error: apiError || 'Validation failed' }
      }
      return { valid: data.valid, error: data.error, sql: data.compiled_sql }
    } catch (err) {
      return { valid: false, error: err instanceof Error ? err.message : 'Validation failed' }
    }
  }, [projectPath, currentRole])

  // === Calculated Tables ===
  
  const loadCalcTables = useCallback(async () => {
    if (!projectPath) return
    
    setCalcTablesLoading(true)
    setError(null)
    
    try {
      const { data, error: apiError } = await listCalcTables(projectPath, currentRole ?? undefined)
      if (apiError || !data) {
        setError(apiError || 'Failed to load calculated tables')
        return
      }
      setCalcTables(data.tables)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load calculated tables')
    } finally {
      setCalcTablesLoading(false)
    }
  }, [projectPath, currentRole])

  const saveCalcTable = useCallback(async (calcTable: CalcTableDetail, isNew: boolean) => {
    if (!projectPath) return { success: false, error: 'No project loaded' }
    
    try {
      const { data, error: apiError } = isNew
        ? await createCalcTable(calcTable, projectPath)
        : await updateCalcTable(calcTable.name, calcTable, projectPath)
      
      if (apiError || !data) {
        return { success: false, error: apiError || 'Failed to save calculated table' }
      }
      
      // Reload calc tables list
      await loadCalcTables()
      return { success: true, calcTable: data.calculated_table }
    } catch (err) {
      return { success: false, error: err instanceof Error ? err.message : 'Failed to save calculated table' }
    }
  }, [projectPath, loadCalcTables])

  const removeCalcTable = useCallback(async (name: string) => {
    if (!projectPath) return { success: false, error: 'No project loaded' }
    
    try {
      const { error: apiError } = await deleteCalcTable(name, projectPath)
      if (apiError) {
        return { success: false, error: apiError }
      }
      
      // Reload calc tables list
      await loadCalcTables()
      return { success: true }
    } catch (err) {
      return { success: false, error: err instanceof Error ? err.message : 'Failed to delete calculated table' }
    }
  }, [projectPath, loadCalcTables])

  const checkCalcTable = useCallback(async (dax: string, limit = 100) => {
    if (!projectPath) return { success: false, error: 'No project loaded' }
    
    try {
      const { data, error: apiError } = await previewCalcTable(dax, projectPath, currentRole ?? undefined, limit)
      if (apiError || !data) {
        return { success: false, error: apiError || 'Preview failed' }
      }
      return { 
        success: true, 
        columns: data.columns, 
        rows: data.rows, 
        rowCount: data.row_count 
      }
    } catch (err) {
      return { success: false, error: err instanceof Error ? err.message : 'Preview failed' }
    }
  }, [projectPath, currentRole])

  // === Calculated Columns ===
  
  const loadCalcColumns = useCallback(async () => {
    if (!projectPath) return
    
    setCalcColumnsLoading(true)
    setError(null)
    
    try {
      const { data, error: apiError } = await listCalcColumns(projectPath, currentRole ?? undefined)
      if (apiError || !data) {
        setError(apiError || 'Failed to load calculated columns')
        return
      }
      setCalcColumns(data.calculated_columns)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load calculated columns')
    } finally {
      setCalcColumnsLoading(false)
    }
  }, [projectPath, currentRole])

  const saveCalcColumn = useCallback(async (calcColumn: CalcColumnDetail, isNew: boolean) => {
    if (!projectPath) return { success: false, error: 'No project loaded' }
    
    try {
      const { data, error: apiError } = isNew
        ? await createCalcColumn(calcColumn, projectPath)
        : await updateCalcColumn(calcColumn.table, calcColumn.column, calcColumn, projectPath)
      
      if (apiError || !data) {
        return { success: false, error: apiError || 'Failed to save calculated column' }
      }
      
      // Reload calc columns list
      await loadCalcColumns()
      return { success: true, calcColumn: data.calculated_column }
    } catch (err) {
      return { success: false, error: err instanceof Error ? err.message : 'Failed to save calculated column' }
    }
  }, [projectPath, loadCalcColumns])

  const removeCalcColumn = useCallback(async (table: string, column: string) => {
    if (!projectPath) return { success: false, error: 'No project loaded' }
    
    try {
      const { error: apiError } = await deleteCalcColumn(table, column, projectPath)
      if (apiError) {
        return { success: false, error: apiError }
      }
      
      // Reload calc columns list
      await loadCalcColumns()
      return { success: true }
    } catch (err) {
      return { success: false, error: err instanceof Error ? err.message : 'Failed to delete calculated column' }
    }
  }, [projectPath, loadCalcColumns])

  // Load all model data
  const loadAll = useCallback(async () => {
    await Promise.all([
      loadMeasures(),
      loadCalcTables(),
      loadCalcColumns(),
    ])
  }, [loadMeasures, loadCalcTables, loadCalcColumns])

  return {
    // State
    measures,
    calcTables,
    calcColumns,
    measuresLoading,
    calcTablesLoading,
    calcColumnsLoading,
    error,
    
    // Measures
    loadMeasures,
    saveMeasure,
    removeMeasure,
    checkMeasure,
    
    // Calculated Tables
    loadCalcTables,
    saveCalcTable,
    removeCalcTable,
    checkCalcTable,
    
    // Calculated Columns
    loadCalcColumns,
    saveCalcColumn,
    removeCalcColumn,
    
    // All
    loadAll,
  }
}

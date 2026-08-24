import { useCallback } from 'react'
import { useAppStore, useReportStore, useFilterStore, type Filter } from '@/stores'
import { getFilters, saveFilters, getDistinctValues, type FilterDef } from '@/lib/api'

/**
 * Hook to manage filters across all scopes
 */
export function useFilters() {
  const projectPath = useAppStore(s => s.projectPath)
  const currentRole = useAppStore(s => s.currentRole)
  const currentPageId = useReportStore(s => s.currentPageId)
  const reportFilters = useFilterStore(s => s.reportFilters)
  const pageFilters = useFilterStore(s => s.pageFilters)
  const visualFilters = useFilterStore(s => s.visualFilters)
  const interactionFilters = useFilterStore(s => s.interactionFilters)
  const setReportFilters = useFilterStore(s => s.setReportFilters)
  const setPageFilters = useFilterStore(s => s.setPageFilters)
  const setVisualFilters = useFilterStore(s => s.setVisualFilters)
  const addFilter = useFilterStore(s => s.addFilter)
  const removeFilter = useFilterStore(s => s.removeFilter)
  const updateFilter = useFilterStore(s => s.updateFilter)
  const clearFilters = useFilterStore(s => s.clearFilters)
  const setInteractionFilters = useFilterStore(s => s.setInteractionFilters)
  const clearInteractionFilters = useFilterStore(s => s.clearInteractionFilters)
  const setLoading = useFilterStore(s => s.setLoading)
  const setError = useFilterStore(s => s.setError)

  // Generate a unique filter ID
  const generateFilterId = useCallback(() => {
    return `filter_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`
  }, [])

  // Load filters from backend
  const loadFilters = useCallback(async () => {
    if (!projectPath) return

    setLoading(true)
    setError(null)

    try {
      const { data, error } = await getFilters(projectPath)
      if (error || !data) {
        setError(error || 'Failed to load filters')
        return
      }

      // Process report filters (keep API format — column is a nested ColumnRef object)
      const reportFiltersWithId: Filter[] = (data.report_filters || []).map((f, i) => ({
        ...f,
        id: f.id || `report_${i}`,
        type: 'report' as const,
      } as Filter))
      setReportFilters(reportFiltersWithId)

      // Process page filters
      if (data.page_filters) {
        Object.entries(data.page_filters).forEach(([pageId, filters]) => {
          const pageFiltersWithId: Filter[] = (filters || []).map((f, i) => ({
            ...f,
            id: f.id || `page_${pageId}_${i}`,
            type: 'page' as const,
            visual_id: pageId,
          } as Filter))
          setPageFilters(pageId, pageFiltersWithId)
        })
      }

      // Process visual filters
      if (data.visual_filters) {
        Object.entries(data.visual_filters).forEach(([visualId, filters]) => {
          const visualFiltersWithId: Filter[] = (filters || []).map((f, i) => ({
            ...f,
            id: f.id || `visual_${visualId}_${i}`,
            type: 'visual' as const,
            visual_id: visualId,
          } as Filter))
          setVisualFilters(visualId, visualFiltersWithId)
        })
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load filters')
    } finally {
      setLoading(false)
    }
  }, [projectPath, setReportFilters, setPageFilters, setVisualFilters, setLoading, setError])

  // Save all filters to backend
  const saveAllFilters = useCallback(async () => {
    if (!projectPath) return { success: false, error: 'No project loaded' }

    setLoading(true)

    try {
      // Convert filters to API format
      const reportFiltersApi: FilterDef[] = reportFilters.map(f => ({
        table: f.table,
        column: f.column,
        values: f.values,
        operator: f.operator || 'in',
        scope: 'report',
      }))

      const pageFiltersApi: Record<string, FilterDef[]> = {}
      Object.entries(pageFilters).forEach(([pageId, filters]) => {
        pageFiltersApi[pageId] = filters.map(f => ({
          table: f.table,
          column: f.column,
          values: f.values,
          operator: f.operator || 'in',
          scope: 'page',
          page_id: pageId,
        }))
      })

      const visualFiltersApi: Record<string, FilterDef[]> = {}
      Object.entries(visualFilters).forEach(([visualId, filters]) => {
        visualFiltersApi[visualId] = filters.map(f => ({
          table: f.table,
          column: f.column,
          values: f.values,
          operator: f.operator || 'in',
          scope: 'visual',
          visual_id: visualId,
        }))
      })

      const { data, error } = await saveFilters(
        {
          report_filters: reportFiltersApi,
          page_filters: pageFiltersApi,
          visual_filters: visualFiltersApi,
        },
        projectPath
      )

      if (error) {
        setError(error)
        return { success: false, error }
      }

      return { success: true, data }
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to save filters'
      setError(message)
      return { success: false, error: message }
    } finally {
      setLoading(false)
    }
  }, [projectPath, reportFilters, pageFilters, visualFilters, setLoading, setError])

  // Add a new filter
  const addNewFilter = useCallback((
    scope: 'report' | 'page' | 'visual',
    table: string,
    column: string,
    values: unknown[],
    scopeId?: string, // pageId or visualId
    operator?: string,
  ) => {
    const newFilter: Filter = {
      id: generateFilterId(),
      table,
      column,
      values,
      operator: operator || 'in',
      type: scope,
      scope,
      visual_id: scope === 'visual' ? scopeId : scope === 'page' ? scopeId : undefined,
    }
    addFilter(newFilter)
    return newFilter
  }, [generateFilterId, addFilter])

  // Update filter values
  const updateFilterValues = useCallback((
    filterId: string,
    values: unknown[],
    operator?: string,
  ) => {
    const updates: Partial<Filter> = { values }
    if (operator) updates.operator = operator
    updateFilter(filterId, updates)
  }, [updateFilter])

  // Remove a specific filter
  const removeFilterById = useCallback((
    filterId: string,
    scope: 'report' | 'page' | 'visual',
    scopeId?: string
  ) => {
    removeFilter(filterId, scope, scopeId)
  }, [removeFilter])

  // Get distinct values for a column (for filter dropdowns)
  const fetchDistinctValues = useCallback(async (
    table: string,
    column: string,
    limit = 1000
  ) => {
    if (!projectPath) return []

    try {
      const { data, error } = await getDistinctValues(table, column, {
        project: projectPath,
        role: currentRole ?? undefined,
        limit,
      })

      if (error || !data) return []
      return data.values
    } catch {
      return []
    }
  }, [projectPath, currentRole])

  // Get all filters for render request
  const getFiltersForRender = useCallback((visualId?: string) => {
    // Combine all applicable filters in the format the render endpoint expects:
    // { column: {type: "ColumnRef", table, column}, operator, values, scope }
    // The column field may be a nested ColumnRef object (from API) or flat strings
    //  (from manually created filters). We handle both cases.
    const toRenderFilter = (f: Filter) => {
      const col = f.column
      // If column is already a nested object, pass it through
      const columnRef = (col && typeof col === 'object')
        ? col
        : { type: 'ColumnRef', table: f.table || '', column: String(col || '') }
      return {
        column: columnRef,
        operator: f.operator || 'in',
        values: f.values,
        scope: f.scope || f.type,
      }
    }

    const allFilters: Array<{
      column: unknown
      operator: string
      values: unknown[]
      scope?: string
    }> = []

    // Report filters always apply
    reportFilters.forEach(f => {
      allFilters.push(toRenderFilter(f))
    })

    // Page filters for current page
    if (currentPageId && pageFilters[currentPageId]) {
      pageFilters[currentPageId].forEach(f => {
        allFilters.push(toRenderFilter(f))
      })
    }

    // Visual filters for specific visual
    if (visualId && visualFilters[visualId]) {
      visualFilters[visualId].forEach(f => {
        allFilters.push(toRenderFilter(f))
      })
    }

    return allFilters
  }, [reportFilters, pageFilters, visualFilters, currentPageId])

  // Get interaction filters for render request
  const getInteractionFiltersForRender = useCallback(() => {
    return interactionFilters.map(f => ({
      source_visual_id: f.source_visual_id,
      table: f.table,
      column: f.column,
      operator: f.operator || 'in',
      values: f.values,
    }))
  }, [interactionFilters])

  // Add interaction filter (from cross-filtering)
  const addInteractionFilter = useCallback((
    sourceVisualId: string,
    table: string,
    column: string,
    values: unknown[]
  ) => {
    const newFilters = [
      ...interactionFilters.filter(
        f => !(f.source_visual_id === sourceVisualId && f.table === table && f.column === column)
      ),
      { source_visual_id: sourceVisualId, table, column, values },
    ]
    setInteractionFilters(newFilters)
  }, [interactionFilters, setInteractionFilters])

  // Add slicer filter (similar to interaction filter but with slicer_id)
  const addSlicerFilter = useCallback((
    table: string,
    column: string,
    values: unknown[],
    slicerId: string,
    pageId: string | null,
    operator = 'in',
  ) => {
    // Slicers create filters with source = 'slicer' and slicer_id
    // We use interactionFilters for now, but mark them differently
    const newFilters = [
      ...interactionFilters.filter(
        f => !((f as { slicer_id?: string }).slicer_id === slicerId)
      ),
      { 
        source_visual_id: `slicer_${slicerId}`, 
        table, 
        column, 
        values,
        operator,
        slicer_id: slicerId,
        page_id: pageId,
      },
    ]
    setInteractionFilters(newFilters as typeof interactionFilters)
  }, [interactionFilters, setInteractionFilters])

  // Remove slicer filter
  const removeSlicerFilter = useCallback((slicerId: string) => {
    const newFilters = interactionFilters.filter(
      f => !((f as { slicer_id?: string }).slicer_id === slicerId)
    )
    setInteractionFilters(newFilters)
  }, [interactionFilters, setInteractionFilters])

  // Clear all slicer filters
  const clearSlicerFilters = useCallback(() => {
    const newFilters = interactionFilters.filter(
      f => !((f as { slicer_id?: string }).slicer_id)
    )
    setInteractionFilters(newFilters)
  }, [interactionFilters, setInteractionFilters])

  return {
    // State
    reportFilters,
    pageFilters,
    visualFilters,
    interactionFilters,
    
    // Actions
    loadFilters,
    saveAllFilters,
    addNewFilter,
    updateFilterValues,
    removeFilterById,
    clearFilters,
    clearInteractionFilters,
    fetchDistinctValues,
    
    // For render requests
    getFiltersForRender,
    getInteractionFiltersForRender,
    addInteractionFilter,
    
    // Slicer-specific
    addSlicerFilter,
    removeSlicerFilter,
    clearSlicerFilters,
  }
}

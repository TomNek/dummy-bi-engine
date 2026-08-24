import { create } from 'zustand'
import type { FilterDef } from '@/lib/api'

export interface Filter extends FilterDef {
  id: string
  type: 'report' | 'page' | 'visual' | 'interaction'
}

export interface FilterValue {
  column: string
  table: string
  values: unknown[]
  operator?: 'in' | 'not_in' | 'between' | 'equals'
}

export interface FilterState {
  // Filters organized by scope
  reportFilters: Filter[]
  pageFilters: Record<string, Filter[]> // keyed by page_id
  visualFilters: Record<string, Filter[]> // keyed by visual_id
  
  // Active interaction filters (from crossfiltering)
  interactionFilters: Array<{
    id?: string
    source_visual_id: string
    table: string
    column: string
    values: unknown[]
    operator?: string
    pointIndices?: number[]
  }>
  
  // Loading
  loading: boolean
  error: string | null
  
  // Monotonic counter bumped when report/page/visual filters change via bulk load.
  // Canvas watches this to re-render after deferred filter loading completes.
  filtersVersion: number
  bumpFiltersVersion: () => void
  
  // Actions
  setReportFilters: (filters: Filter[]) => void
  setPageFilters: (pageId: string, filters: Filter[]) => void
  setVisualFilters: (visualId: string, filters: Filter[]) => void
  addFilter: (filter: Filter) => void
  removeFilter: (filterId: string, scope: Filter['type'], scopeId?: string) => void
  updateFilter: (filterId: string, updates: Partial<Filter>) => void
  clearFilters: (type?: Filter['type']) => void
  setInteractionFilters: (filters: FilterState['interactionFilters']) => void
  clearInteractionFilters: (sourceVisualId?: string) => void
  setLoading: (loading: boolean) => void
  setError: (error: string | null) => void
  reset: () => void
  replaceState: (snapshot: FilterSnapshot) => void
}

export interface FilterSnapshot {
  reportFilters: Filter[]
  pageFilters: Record<string, Filter[]>
  visualFilters: Record<string, Filter[]>
}

const initialState = {
  reportFilters: [],
  pageFilters: {},
  visualFilters: {},
  interactionFilters: [],
  filtersVersion: 0,
  loading: false,
  error: null,
}

export const useFilterStore = create<FilterState>((set) => ({
  ...initialState,
  
  // Actions
  bumpFiltersVersion: () => set((state) => ({ filtersVersion: state.filtersVersion + 1 })),
  setReportFilters: (reportFilters) => set({ reportFilters }),
  
  setPageFilters: (pageId, filters) => set((state) => ({
    pageFilters: { ...state.pageFilters, [pageId]: filters }
  })),
  
  setVisualFilters: (visualId, filters) => set((state) => ({
    visualFilters: { ...state.visualFilters, [visualId]: filters }
  })),
  
  addFilter: (filter) => set((state) => {
    if (filter.type === 'report') {
      return { reportFilters: [...state.reportFilters, filter] }
    }
    if (filter.type === 'page' && filter.visual_id) {
      const pageId = filter.visual_id
      return {
        pageFilters: {
          ...state.pageFilters,
          [pageId]: [...(state.pageFilters[pageId] || []), filter]
        }
      }
    }
    if (filter.type === 'visual' && filter.visual_id) {
      return {
        visualFilters: {
          ...state.visualFilters,
          [filter.visual_id]: [...(state.visualFilters[filter.visual_id] || []), filter]
        }
      }
    }
    return state
  }),
  
  removeFilter: (filterId, scope, scopeId) => set((state) => {
    if (scope === 'report') {
      return { reportFilters: state.reportFilters.filter(f => f.id !== filterId) }
    }
    if (scope === 'page' && scopeId) {
      return {
        pageFilters: {
          ...state.pageFilters,
          [scopeId]: (state.pageFilters[scopeId] || []).filter(f => f.id !== filterId)
        }
      }
    }
    if (scope === 'visual' && scopeId) {
      return {
        visualFilters: {
          ...state.visualFilters,
          [scopeId]: (state.visualFilters[scopeId] || []).filter(f => f.id !== filterId)
        }
      }
    }
    return state
  }),
  
  updateFilter: (filterId, updates) => set((state) => ({
    reportFilters: state.reportFilters.map(f => 
      f.id === filterId ? { ...f, ...updates } : f
    ),
    pageFilters: Object.fromEntries(
      Object.entries(state.pageFilters).map(([k, v]) => [
        k,
        v.map(f => f.id === filterId ? { ...f, ...updates } : f)
      ])
    ),
    visualFilters: Object.fromEntries(
      Object.entries(state.visualFilters).map(([k, v]) => [
        k,
        v.map(f => f.id === filterId ? { ...f, ...updates } : f)
      ])
    ),
  })),
  
  clearFilters: (type) => set((state) => {
    if (!type) return initialState
    if (type === 'report') return { ...state, reportFilters: [] }
    if (type === 'page') return { ...state, pageFilters: {} }
    if (type === 'visual') return { ...state, visualFilters: {} }
    if (type === 'interaction') return { ...state, interactionFilters: [] }
    return state
  }),
  
  setInteractionFilters: (interactionFilters) => set({ interactionFilters }),
  
  clearInteractionFilters: (sourceVisualId) => set((state) => {
    if (!sourceVisualId) {
      // Skip state update if already empty — avoids spurious re-renders
      if (state.interactionFilters.length === 0) return state
      return { ...state, interactionFilters: [] }
    }
    const next = state.interactionFilters.filter(f => f.source_visual_id !== sourceVisualId)
    // Skip if nothing was actually removed
    if (next.length === state.interactionFilters.length) return state
    return { ...state, interactionFilters: next }
  }),
  
  setLoading: (loading) => set({ loading }),
  setError: (error) => set({ error, loading: false }),
  reset: () => set(initialState),
  replaceState: (snapshot) => set({
    reportFilters: snapshot.reportFilters,
    pageFilters: snapshot.pageFilters,
    visualFilters: snapshot.visualFilters,
    interactionFilters: [],
  }),
}))

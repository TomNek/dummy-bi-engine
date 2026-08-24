/**
 * useMatrixState - Hook for managing matrix visual state
 * 
 * Tracks:
 * - Expanded rows (for row hierarchies)
 * - Expanded columns (for column groups)
 * - Selected cells (for interaction)
 * - Edit mode state (for SSRS-style tablix template editing)
 */
import { useCallback, useMemo } from 'react'
import { create } from 'zustand'

// Store for matrix expanded state per visual
interface MatrixExpandedState {
  // Map of visualId -> Set of expanded row paths (serialized)
  expandedRows: Record<string, Set<string>>
  // Map of visualId -> Set of expanded col paths (serialized)
  expandedCols: Record<string, Set<string>>
  
  // Edit mode state
  // Map of visualId -> boolean indicating if edit mode is active
  editMode: Record<string, boolean>
  // Map of visualId -> Set of selected design cell IDs
  selectedCells: Record<string, Set<string>>
  // Map of visualId -> selection anchor for range selection
  selectionAnchor: Record<string, string | null>
  
  // Drill state per visual
  drillState: Record<string, DrillState>
  
  // Actions - Expansion
  toggleRowExpanded: (visualId: string, rowPath: string[]) => void
  toggleColExpanded: (visualId: string, colPath: string[]) => void
  setRowExpanded: (visualId: string, rowPath: string[], expanded: boolean) => void
  setColExpanded: (visualId: string, colPath: string[], expanded: boolean) => void
  clearExpanded: (visualId: string) => void
  expandAllRows: (visualId: string) => void
  expandAllCols: (visualId: string) => void
  expandAllBoth: (visualId: string) => void
  collapseAllRows: (visualId: string) => void
  collapseAllCols: (visualId: string) => void
  collapseAllBoth: (visualId: string) => void
  getExpandedRowPaths: (visualId: string) => Array<{ axis: 'rows'; path: string[] }>
  getExpandedColPaths: (visualId: string) => Array<{ axis: 'cols'; path: string[] }>
  
  // Actions - Edit mode
  toggleEditMode: (visualId: string) => void
  setEditMode: (visualId: string, active: boolean) => void
  isEditModeActive: (visualId: string) => boolean
  
  // Actions - Cell selection
  selectCell: (visualId: string, cellId: string, multi?: boolean) => void
  selectRange: (visualId: string, cellIds: string[]) => void
  clearSelection: (visualId: string) => void
  getSelectedCells: (visualId: string) => string[]
  
  // Actions - Drill
  getDrillState: (visualId: string) => DrillState
  drillDown: (visualId: string, axis: 'rows' | 'cols', column: string, value: unknown, level: number) => void
  drillUp: (visualId: string, axis: 'rows' | 'cols') => void
  goToNextLevel: (visualId: string, axis: 'rows' | 'cols') => void
  expandToNextLevel: (visualId: string, axis: 'rows' | 'cols') => void
  resetDrill: (visualId: string) => void
}

export interface DrillFilter {
  column: string
  value: unknown
  level: number
}

export interface DrillState {
  drillRowLevel?: number
  drillColLevel?: number
  drillRowMode: 'expand' | 'drill' | 'flat'
  drillColMode: 'expand' | 'drill' | 'flat'
  drillRowFilters: DrillFilter[]
  drillColFilters: DrillFilter[]
  expandAllRows: boolean
  expandAllCols: boolean
}

const defaultDrillState = (): DrillState => ({
  drillRowMode: 'expand',
  drillColMode: 'expand',
  drillRowFilters: [],
  drillColFilters: [],
  expandAllRows: false,
  expandAllCols: false,
})

/** Frozen singleton defaults — MUST be used in selectors to avoid new-reference re-renders */
const EMPTY_CELLS_ARRAY: readonly string[] = Object.freeze([] as string[])
const DEFAULT_DRILL_STATE: DrillState = Object.freeze(defaultDrillState()) as DrillState

const serializePath = (path: string[]): string => JSON.stringify(path)
const deserializePath = (key: string): string[] => JSON.parse(key)

export const useMatrixStore = create<MatrixExpandedState>((set, get) => ({
  expandedRows: {},
  expandedCols: {},
  editMode: {},
  selectedCells: {},
  selectionAnchor: {},
  drillState: {},
  
  toggleRowExpanded: (visualId, rowPath) => {
    const key = serializePath(rowPath)
    set((state) => {
      const current = state.expandedRows[visualId] || new Set()
      const next = new Set(current)
      if (next.has(key)) {
        // Collapse: remove this key AND all descendants
        // A descendant's serialized path starts with the parent path array prefix
        next.delete(key)
        for (const k of Array.from(next)) {
          try {
            const kPath = deserializePath(k)
            if (kPath.length > rowPath.length &&
                rowPath.every((seg, i) => kPath[i] === seg)) {
              next.delete(k)
            }
          } catch { /* skip malformed keys */ }
        }
      } else {
        next.add(key)
      }
      return { expandedRows: { ...state.expandedRows, [visualId]: next } }
    })
  },
  
  toggleColExpanded: (visualId, colPath) => {
    const key = serializePath(colPath)
    set((state) => {
      const current = state.expandedCols[visualId] || new Set()
      const next = new Set(current)
      if (next.has(key)) {
        // Collapse: remove this key AND all descendants
        next.delete(key)
        for (const k of Array.from(next)) {
          try {
            const kPath = deserializePath(k)
            if (kPath.length > colPath.length &&
                colPath.every((seg, i) => kPath[i] === seg)) {
              next.delete(k)
            }
          } catch { /* skip malformed keys */ }
        }
      } else {
        next.add(key)
      }
      return { expandedCols: { ...state.expandedCols, [visualId]: next } }
    })
  },
  
  setRowExpanded: (visualId, rowPath, expanded) => {
    const key = serializePath(rowPath)
    set((state) => {
      const current = state.expandedRows[visualId] || new Set()
      const next = new Set(current)
      if (expanded) {
        next.add(key)
      } else {
        // Remove this key and all descendants
        next.delete(key)
        for (const k of Array.from(next)) {
          try {
            const kPath = deserializePath(k)
            if (kPath.length > rowPath.length &&
                rowPath.every((seg, i) => kPath[i] === seg)) {
              next.delete(k)
            }
          } catch { /* skip malformed keys */ }
        }
      }
      return { expandedRows: { ...state.expandedRows, [visualId]: next } }
    })
  },
  
  setColExpanded: (visualId, colPath, expanded) => {
    const key = serializePath(colPath)
    set((state) => {
      const current = state.expandedCols[visualId] || new Set()
      const next = new Set(current)
      if (expanded) {
        next.add(key)
      } else {
        // Remove this key and all descendants
        next.delete(key)
        for (const k of Array.from(next)) {
          try {
            const kPath = deserializePath(k)
            if (kPath.length > colPath.length &&
                colPath.every((seg, i) => kPath[i] === seg)) {
              next.delete(k)
            }
          } catch { /* skip malformed keys */ }
        }
      }
      return { expandedCols: { ...state.expandedCols, [visualId]: next } }
    })
  },
  
  clearExpanded: (visualId) => {
    set((state) => ({
      expandedRows: { ...state.expandedRows, [visualId]: new Set() },
      expandedCols: { ...state.expandedCols, [visualId]: new Set() },
    }))
  },
  
  expandAllRows: (visualId) => {
    set((state) => {
      const ds = {
        ...(state.drillState[visualId] || defaultDrillState()),
        expandAllRows: true,
        drillRowMode: 'expand' as const,
        drillRowFilters: [],
        drillRowLevel: undefined,
      }
      return { drillState: { ...state.drillState, [visualId]: ds } }
    })
  },
  
  expandAllCols: (visualId) => {
    set((state) => {
      const ds = {
        ...(state.drillState[visualId] || defaultDrillState()),
        expandAllCols: true,
        drillColMode: 'expand' as const,
        drillColFilters: [],
        drillColLevel: undefined,
      }
      return { drillState: { ...state.drillState, [visualId]: ds } }
    })
  },

  expandAllBoth: (visualId) => {
    set((state) => {
      const ds = {
        ...(state.drillState[visualId] || defaultDrillState()),
        expandAllRows: true,
        expandAllCols: true,
        drillRowMode: 'expand' as const,
        drillColMode: 'expand' as const,
        drillRowFilters: [],
        drillColFilters: [],
        drillRowLevel: undefined,
        drillColLevel: undefined,
      }
      return { drillState: { ...state.drillState, [visualId]: ds } }
    })
  },
  
  collapseAllRows: (visualId) => {
    set((state) => ({
      expandedRows: { ...state.expandedRows, [visualId]: new Set() },
      drillState: {
        ...state.drillState,
        [visualId]: {
          ...(state.drillState[visualId] || defaultDrillState()),
          expandAllRows: false,
          drillRowMode: 'expand',
          drillRowFilters: [],
          drillRowLevel: undefined,
        },
      },
    }))
  },
  
  collapseAllCols: (visualId) => {
    set((state) => ({
      expandedCols: { ...state.expandedCols, [visualId]: new Set() },
      drillState: {
        ...state.drillState,
        [visualId]: {
          ...(state.drillState[visualId] || defaultDrillState()),
          expandAllCols: false,
          drillColMode: 'expand',
          drillColFilters: [],
          drillColLevel: undefined,
        },
      },
    }))
  },

  collapseAllBoth: (visualId) => {
    set((state) => ({
      expandedRows: { ...state.expandedRows, [visualId]: new Set() },
      expandedCols: { ...state.expandedCols, [visualId]: new Set() },
      drillState: {
        ...state.drillState,
        [visualId]: {
          ...(state.drillState[visualId] || defaultDrillState()),
          expandAllRows: false,
          expandAllCols: false,
          drillRowMode: 'expand',
          drillColMode: 'expand',
          drillRowFilters: [],
          drillColFilters: [],
          drillRowLevel: undefined,
          drillColLevel: undefined,
        },
      },
    }))
  },
  
  getExpandedRowPaths: (visualId) => {
    const rows = get().expandedRows[visualId] || new Set()
    return Array.from(rows).map(key => ({ axis: 'rows' as const, path: deserializePath(key) }))
  },
  
  getExpandedColPaths: (visualId) => {
    const cols = get().expandedCols[visualId] || new Set()
    return Array.from(cols).map(key => ({ axis: 'cols' as const, path: deserializePath(key) }))
  },
  
  // Edit mode actions
  toggleEditMode: (visualId) => {
    set((state) => ({
      editMode: {
        ...state.editMode,
        [visualId]: !state.editMode[visualId],
      },
      // Clear selection when exiting edit mode
      selectedCells: state.editMode[visualId] 
        ? { ...state.selectedCells, [visualId]: new Set() }
        : state.selectedCells,
      selectionAnchor: state.editMode[visualId]
        ? { ...state.selectionAnchor, [visualId]: null }
        : state.selectionAnchor,
    }))
  },
  
  setEditMode: (visualId, active) => {
    set((state) => ({
      editMode: { ...state.editMode, [visualId]: active },
      // Clear selection when exiting edit mode
      selectedCells: active ? state.selectedCells : { ...state.selectedCells, [visualId]: new Set() },
      selectionAnchor: active ? state.selectionAnchor : { ...state.selectionAnchor, [visualId]: null },
    }))
  },
  
  isEditModeActive: (visualId) => {
    return get().editMode[visualId] || false
  },
  
  // Cell selection actions
  selectCell: (visualId, cellId, multi = false) => {
    set((state) => {
      const current = state.selectedCells[visualId] || new Set()
      let next: Set<string>
      
      if (multi) {
        // Toggle selection for multi-select
        next = new Set(current)
        if (next.has(cellId)) {
          next.delete(cellId)
        } else {
          next.add(cellId)
        }
      } else {
        // Single selection - replace
        next = new Set([cellId])
      }
      
      return {
        selectedCells: { ...state.selectedCells, [visualId]: next },
        selectionAnchor: { ...state.selectionAnchor, [visualId]: cellId },
      }
    })
  },
  
  selectRange: (visualId, cellIds) => {
    set((state) => ({
      selectedCells: { ...state.selectedCells, [visualId]: new Set(cellIds) },
    }))
  },
  
  clearSelection: (visualId) => {
    set((state) => ({
      selectedCells: { ...state.selectedCells, [visualId]: new Set() },
      selectionAnchor: { ...state.selectionAnchor, [visualId]: null },
    }))
  },
  
  getSelectedCells: (visualId) => {
    const cells = get().selectedCells[visualId] || new Set()
    return Array.from(cells)
  },
  
  // Drill actions
  getDrillState: (visualId) => {
    return get().drillState[visualId] || defaultDrillState()
  },
  
  drillDown: (visualId, axis, column, value, level) => {
    set((state) => {
      const ds = { ...(state.drillState[visualId] || defaultDrillState()) }
      const filter: DrillFilter = { column, value, level }
      if (axis === 'rows') {
        ds.drillRowFilters = [...ds.drillRowFilters, filter]
        ds.drillRowMode = 'drill'
      } else {
        ds.drillColFilters = [...ds.drillColFilters, filter]
        ds.drillColMode = 'drill'
      }
      return {
        drillState: { ...state.drillState, [visualId]: ds },
        // Clear expansion state when drilling
        expandedRows: axis === 'rows'
          ? { ...state.expandedRows, [visualId]: new Set() }
          : state.expandedRows,
        expandedCols: axis === 'cols'
          ? { ...state.expandedCols, [visualId]: new Set() }
          : state.expandedCols,
      }
    })
  },
  
  drillUp: (visualId, axis) => {
    set((state) => {
      const ds = { ...(state.drillState[visualId] || defaultDrillState()) }
      if (axis === 'rows') {
        ds.drillRowFilters = ds.drillRowFilters.slice(0, -1)
        if (ds.drillRowFilters.length === 0) {
          ds.drillRowMode = 'expand'
        }
      } else {
        ds.drillColFilters = ds.drillColFilters.slice(0, -1)
        if (ds.drillColFilters.length === 0) {
          ds.drillColMode = 'expand'
        }
      }
      return {
        drillState: { ...state.drillState, [visualId]: ds },
        expandedRows: axis === 'rows'
          ? { ...state.expandedRows, [visualId]: new Set() }
          : state.expandedRows,
        expandedCols: axis === 'cols'
          ? { ...state.expandedCols, [visualId]: new Set() }
          : state.expandedCols,
      }
    })
  },
  
  goToNextLevel: (visualId, axis) => {
    set((state) => {
      const ds = { ...(state.drillState[visualId] || defaultDrillState()) }
      if (axis === 'rows') {
        ds.drillRowLevel = (ds.drillRowLevel ?? -1) + 1
        ds.drillRowMode = 'flat'
      } else {
        ds.drillColLevel = (ds.drillColLevel ?? -1) + 1
        ds.drillColMode = 'flat'
      }
      return {
        drillState: { ...state.drillState, [visualId]: ds },
        expandedRows: axis === 'rows'
          ? { ...state.expandedRows, [visualId]: new Set() }
          : state.expandedRows,
        expandedCols: axis === 'cols'
          ? { ...state.expandedCols, [visualId]: new Set() }
          : state.expandedCols,
      }
    })
  },
  
  expandToNextLevel: (visualId, axis) => {
    set((state) => {
      const ds = { ...(state.drillState[visualId] || defaultDrillState()) }
      if (axis === 'rows') {
        ds.expandAllRows = true
        ds.drillRowMode = 'expand'
      } else {
        ds.expandAllCols = true
        ds.drillColMode = 'expand'
      }
      return { drillState: { ...state.drillState, [visualId]: ds } }
    })
  },
  
  resetDrill: (visualId) => {
    set((state) => ({
      drillState: { ...state.drillState, [visualId]: defaultDrillState() },
      expandedRows: { ...state.expandedRows, [visualId]: new Set() },
      expandedCols: { ...state.expandedCols, [visualId]: new Set() },
    }))
  },
}))

interface UseMatrixStateOptions {
  visualId: string
}

export function useMatrixState({ visualId }: UseMatrixStateOptions) {
  // Subscribe only to the per-visual slices we need for rendering.
  // All mutators are accessed via getState() to avoid full-store subscriptions.
  const expandedRowsForVisual = useMatrixStore(s => s.expandedRows[visualId])
  const expandedColsForVisual = useMatrixStore(s => s.expandedCols[visualId])
  const selectionAnchorForVisual = useMatrixStore(s => s.selectionAnchor[visualId] || null)
  
  // Check if a row path is expanded
  const isRowExpanded = useCallback((rowPath: string[]): boolean => {
    const key = serializePath(rowPath)
    return expandedRowsForVisual ? expandedRowsForVisual.has(key) : false
  }, [expandedRowsForVisual])
  
  // Check if a column path is expanded
  const isColExpanded = useCallback((colPath: string[]): boolean => {
    const key = serializePath(colPath)
    return expandedColsForVisual ? expandedColsForVisual.has(key) : false
  }, [expandedColsForVisual])
  
  // Toggle row expansion
  const toggleRowExpanded = useCallback((rowPath: string[]) => {
    useMatrixStore.getState().toggleRowExpanded(visualId, rowPath)
  }, [visualId])
  
  // Toggle column expansion
  const toggleColExpanded = useCallback((colPath: string[]) => {
    useMatrixStore.getState().toggleColExpanded(visualId, colPath)
  }, [visualId])
  
  // Set row expansion state
  const setRowExpanded = useCallback((rowPath: string[], expanded: boolean) => {
    useMatrixStore.getState().setRowExpanded(visualId, rowPath, expanded)
  }, [visualId])
  
  // Set column expansion state
  const setColExpanded = useCallback((colPath: string[], expanded: boolean) => {
    useMatrixStore.getState().setColExpanded(visualId, colPath, expanded)
  }, [visualId])
  
  // Clear all expanded state for this visual
  const clearExpanded = useCallback(() => {
    useMatrixStore.getState().clearExpanded(visualId)
  }, [visualId])
  
  // Get all expanded paths for API call
  const expandedPaths = useMemo(() => {
    const s = useMatrixStore.getState()
    return [
      ...s.getExpandedRowPaths(visualId),
      ...s.getExpandedColPaths(visualId),
    ]
  }, [expandedRowsForVisual, expandedColsForVisual, visualId])
  
  // Edit mode state — use direct property access, not method call (avoids get() indirection)
  const isEditMode = useMatrixStore(s => !!s.editMode[visualId])
  
  const toggleEditMode = useCallback(() => {
    useMatrixStore.getState().toggleEditMode(visualId)
  }, [visualId])
  
  const setEditMode = useCallback((active: boolean) => {
    useMatrixStore.getState().setEditMode(visualId, active)
  }, [visualId])
  
  // Cell selection state — access raw Set, then derive array via useMemo
  // CRITICAL: do NOT call getSelectedCells() inside selector — it creates
  // a new Array.from() on every call, causing infinite re-renders.
  const _selectedCellsSet = useMatrixStore(s => s.selectedCells[visualId])
  const selectedCells = useMemo(
    () => _selectedCellsSet ? Array.from(_selectedCellsSet) : (EMPTY_CELLS_ARRAY as string[]),
    [_selectedCellsSet],
  )
  
  const selectCell = useCallback((cellId: string, multi?: boolean) => {
    useMatrixStore.getState().selectCell(visualId, cellId, multi)
  }, [visualId])
  
  const selectRange = useCallback((cellIds: string[]) => {
    useMatrixStore.getState().selectRange(visualId, cellIds)
  }, [visualId])
  
  const clearSelection = useCallback(() => {
    useMatrixStore.getState().clearSelection(visualId)
  }, [visualId])
  
  const selectionAnchor = selectionAnchorForVisual
  
  // Drill state — use direct property access with frozen default
  // CRITICAL: do NOT call getDrillState() inside selector — it creates
  // a new defaultDrillState() object when no state exists, causing infinite re-renders.
  const drillState = useMatrixStore(s => s.drillState[visualId] ?? DEFAULT_DRILL_STATE)
  
  const drillDown = useCallback((axis: 'rows' | 'cols', column: string, value: unknown, level: number) => {
    useMatrixStore.getState().drillDown(visualId, axis, column, value, level)
  }, [visualId])
  
  const drillUp = useCallback((axis: 'rows' | 'cols') => {
    useMatrixStore.getState().drillUp(visualId, axis)
  }, [visualId])
  
  const goToNextLevel = useCallback((axis: 'rows' | 'cols') => {
    useMatrixStore.getState().goToNextLevel(visualId, axis)
  }, [visualId])
  
  const expandToNextLevel = useCallback((axis: 'rows' | 'cols') => {
    useMatrixStore.getState().expandToNextLevel(visualId, axis)
  }, [visualId])
  
  const resetDrill = useCallback(() => {
    useMatrixStore.getState().resetDrill(visualId)
  }, [visualId])
  
  // Expand all / collapse all
  const expandAllRows = useCallback(() => {
    useMatrixStore.getState().expandAllRows(visualId)
  }, [visualId])
  
  const expandAllCols = useCallback(() => {
    useMatrixStore.getState().expandAllCols(visualId)
  }, [visualId])
  
  const collapseAllRows = useCallback(() => {
    useMatrixStore.getState().collapseAllRows(visualId)
  }, [visualId])
  
  const collapseAllCols = useCallback(() => {
    useMatrixStore.getState().collapseAllCols(visualId)
  }, [visualId])
  
  return {
    // Expansion
    isRowExpanded,
    isColExpanded,
    toggleRowExpanded,
    toggleColExpanded,
    setRowExpanded,
    setColExpanded,
    clearExpanded,
    expandedPaths,
    expandAllRows,
    expandAllCols,
    collapseAllRows,
    collapseAllCols,
    // Edit mode
    isEditMode,
    toggleEditMode,
    setEditMode,
    // Selection
    selectedCells,
    selectCell,
    selectRange,
    clearSelection,
    selectionAnchor,
    // Drill
    drillState,
    drillDown,
    drillUp,
    goToNextLevel,
    expandToNextLevel,
    resetDrill,
  }
}

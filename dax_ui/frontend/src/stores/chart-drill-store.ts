import { create } from 'zustand'
import type { DrillMeta } from '@/lib/api'

export interface ChartDrillFilter {
  table: string
  column: string
  value: unknown
}

export interface ChartDrillState {
  /** Per-visual drill level (0 = top level) */
  drillLevels: Record<string, number>
  /** Per-visual drill filters (accumulated as user drills down) */
  drillFilters: Record<string, ChartDrillFilter[]>
  /** Per-visual drill metadata from last render response */
  drillMeta: Record<string, DrillMeta>
  /**
   * Per-visual expand count: how many hierarchy levels are shown simultaneously.
   * Default is 1 (single level). "Expand All Down One Level" increments this.
   * E.g. at drillLevel=0 with expandCount=2 → show Level0 + Level1 concatenated.
   */
  expandCounts: Record<string, number>

  // Actions
  setDrillMeta: (visualId: string, meta: DrillMeta) => void
  clearDrillMeta: (visualId: string) => void

  /**
   * Drill down on a chart visual: increment level and add a filter for the clicked value.
   * @param visualId - The visual ID
   * @param clickedColumn - The column name of the clicked value
   * @param clickedValue - The value the user clicked on
   * @param table - The table name for the filter
   */
  drillDown: (visualId: string, clickedColumn: string, clickedValue: unknown, table: string) => void

  /** Drill up one level: decrement level and remove the last drill filter. */
  drillUp: (visualId: string) => void

  /** Reset drill state for a visual back to top level. */
  resetDrill: (visualId: string) => void

  /** Get drill level for a visual (default 0). */
  getDrillLevel: (visualId: string) => number

  /** Get drill filters for a visual. */
  getDrillFilters: (visualId: string) => ChartDrillFilter[]

  /**
   * Go to the next hierarchy level showing ALL values (no filter added).
   * Like Power BI's "Go to the next level in the hierarchy" button.
   */
  goToNextLevel: (visualId: string) => void

  /**
   * Expand All Down One Level: adds one more hierarchy level to the display.
   * Shows current level(s) + the next level with concatenated axis labels.
   * Like Power BI's "Expand all down one level in the hierarchy" button.
   */
  expandAllDownOneLevel: (visualId: string) => void

  /**
   * Collapse one expanded level: reduces the number of visible hierarchy levels by one.
   */
  collapseOneLevel: (visualId: string) => void

  /** Get expand count for a visual (default 1). */
  getExpandCount: (visualId: string) => number

  /** Check if a visual can expand further down. */
  canExpand: (visualId: string) => boolean

  /** Check if a visual has expanded levels (expandCount > 1). */
  isExpanded: (visualId: string) => boolean

  /** Check if a visual has hierarchy drill capability. */
  hasDrill: (visualId: string) => boolean
}

export const useChartDrillStore = create<ChartDrillState>((set, get) => ({
  drillLevels: {},
  drillFilters: {},
  drillMeta: {},
  expandCounts: {},

  setDrillMeta: (visualId, meta) =>
    set((state) => ({
      drillMeta: { ...state.drillMeta, [visualId]: meta },
    })),

  clearDrillMeta: (visualId) =>
    set((state) => {
      const { [visualId]: _, ...rest } = state.drillMeta
      return { drillMeta: rest }
    }),

  drillDown: (visualId, clickedColumn, clickedValue, table) =>
    set((state) => {
      const currentLevel = state.drillLevels[visualId] ?? 0
      const currentFilters = state.drillFilters[visualId] ?? []
      return {
        drillLevels: { ...state.drillLevels, [visualId]: currentLevel + 1 },
        drillFilters: {
          ...state.drillFilters,
          [visualId]: [...currentFilters, { table, column: clickedColumn, value: clickedValue }],
        },
        // Reset expand on drill down
        expandCounts: { ...state.expandCounts, [visualId]: 1 },
      }
    }),

  drillUp: (visualId) =>
    set((state) => {
      const currentLevel = state.drillLevels[visualId] ?? 0
      if (currentLevel <= 0) return state
      const currentFilters = [...(state.drillFilters[visualId] ?? [])]
      currentFilters.pop()
      return {
        drillLevels: { ...state.drillLevels, [visualId]: currentLevel - 1 },
        drillFilters: { ...state.drillFilters, [visualId]: currentFilters },
        // Reset expand on drill up
        expandCounts: { ...state.expandCounts, [visualId]: 1 },
      }
    }),

  resetDrill: (visualId) =>
    set((state) => ({
      drillLevels: { ...state.drillLevels, [visualId]: 0 },
      drillFilters: { ...state.drillFilters, [visualId]: [] },
      expandCounts: { ...state.expandCounts, [visualId]: 1 },
    })),

  goToNextLevel: (visualId) =>
    set((state) => {
      const currentLevel = state.drillLevels[visualId] ?? 0
      const meta = state.drillMeta[visualId]
      const maxLevel = meta?.max_level ?? 0
      if (currentLevel >= maxLevel) return state
      // Go to next level WITHOUT adding a filter — shows all values
      return {
        drillLevels: { ...state.drillLevels, [visualId]: currentLevel + 1 },
        // Clear drill filters since we're showing ALL values at the new level
        drillFilters: { ...state.drillFilters, [visualId]: [] },
        // Reset expand on go to next level
        expandCounts: { ...state.expandCounts, [visualId]: 1 },
      }
    }),

  expandAllDownOneLevel: (visualId) =>
    set((state) => {
      const currentLevel = state.drillLevels[visualId] ?? 0
      const currentExpand = state.expandCounts[visualId] ?? 1
      const meta = state.drillMeta[visualId]
      const maxLevel = meta?.max_level ?? 0
      // Can only expand if current level + expand count doesn't exceed max
      if (currentLevel + currentExpand > maxLevel) return state
      return {
        expandCounts: { ...state.expandCounts, [visualId]: currentExpand + 1 },
      }
    }),

  collapseOneLevel: (visualId) =>
    set((state) => {
      const currentExpand = state.expandCounts[visualId] ?? 1
      if (currentExpand <= 1) return state
      return {
        expandCounts: { ...state.expandCounts, [visualId]: currentExpand - 1 },
      }
    }),

  getDrillLevel: (visualId) => get().drillLevels[visualId] ?? 0,

  getDrillFilters: (visualId) => get().drillFilters[visualId] ?? [],

  getExpandCount: (visualId) => get().expandCounts[visualId] ?? 1,

  canExpand: (visualId) => {
    const s = get()
    const currentLevel = s.drillLevels[visualId] ?? 0
    const currentExpand = s.expandCounts[visualId] ?? 1
    const meta = s.drillMeta[visualId]
    const maxLevel = meta?.max_level ?? 0
    return currentLevel + currentExpand <= maxLevel
  },

  isExpanded: (visualId) => (get().expandCounts[visualId] ?? 1) > 1,

  hasDrill: (visualId) => {
    const meta = get().drillMeta[visualId]
    return meta != null && meta.max_level > 0
  },
}))

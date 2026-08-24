import { create } from 'zustand'

export interface DrillthroughFilter {
  table: string
  column: string
  value: unknown
}

export interface DrillthroughState {
  /** Whether we are currently viewing a drillthrough target page */
  active: boolean
  /** The page we came from (to navigate back) */
  sourcePageId: string | null
  /** Filters applied to the drillthrough page */
  filters: DrillthroughFilter[]

  // Actions
  /** Navigate to a drillthrough target page with filters from the clicked data point */
  startDrillthrough: (sourcePageId: string, filters: DrillthroughFilter[]) => void
  /** Navigate back to the source page */
  endDrillthrough: () => void
  /** Clear drillthrough state */
  reset: () => void
}

export const useDrillthroughStore = create<DrillthroughState>((set) => ({
  active: false,
  sourcePageId: null,
  filters: [],

  startDrillthrough: (sourcePageId, filters) =>
    set({
      active: true,
      sourcePageId,
      filters,
    }),

  endDrillthrough: () =>
    set({
      active: false,
      sourcePageId: null,
      filters: [],
    }),

  reset: () =>
    set({
      active: false,
      sourcePageId: null,
      filters: [],
    }),
}))

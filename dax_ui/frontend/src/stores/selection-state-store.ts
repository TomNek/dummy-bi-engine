/**
 * Selection State Store — Phase 23D
 *
 * Qlik-inspired 3-state selection model for slicer items:
 * - selected: values explicitly chosen by the user
 * - possible: values that have associated data under current filters
 * - excluded: values that have NO associated data under current filters
 *
 * This store fetches selection state from the backend and provides
 * per-field possible/excluded sets for SlicerVisual rendering.
 */
import { create } from 'zustand'
import { getSelectionState, type FieldSelectionState, type SelectionStateRequest } from '@/lib/api'
import { useAppStore } from './app-store'

/** Per-field selection state with Set-based lookups for O(1) checks */
export interface FieldState {
  allValues: unknown[]
  possible: Set<string>
  excluded: Set<string>
  counts?: Record<string, number>
  error?: string
}

export interface SelectionStateStore {
  /** Per-field state keyed by "Table.Column" */
  fields: Record<string, FieldState>

  /** Loading flag */
  loading: boolean

  /** Last error */
  error: string | null

  /** Last fetch timestamp */
  lastFetchMs: number

  /** Debounce timer ID */
  _debounceTimer: ReturnType<typeof setTimeout> | null

  /**
   * Phase 23F: Exploration mode per page (not persisted).
   * When enabled, 3-state rendering extends to crossfilter interactions
   * and filter pane items — not just slicers.
   */
  explorationMode: Record<string, boolean>

  /**
   * Phase 23F: Toggle exploration mode for a page.
   */
  toggleExplorationMode: (pageId: string) => void

  /**
   * Phase 23F: Check if exploration mode is enabled for a page.
   */
  isExplorationMode: (pageId: string) => boolean

  /**
   * Fetch selection state from the backend.
   * Debounced: waits 200ms after last call before firing.
   */
  fetchSelectionState: (
    request: SelectionStateRequest,
    project?: string,
    role?: string
  ) => void

  /**
   * Immediate fetch (no debounce). Used for initial load.
   */
  fetchSelectionStateNow: (
    request: SelectionStateRequest,
    project?: string,
    role?: string
  ) => Promise<void>

  /**
   * Check if a value is "possible" for a given field.
   * Returns true if selection state hasn't been loaded yet (optimistic).
   */
  isPossible: (tableColumn: string, value: unknown) => boolean

  /**
   * Check if a value is "excluded" for a given field.
   * Returns false if selection state hasn't been loaded yet (optimistic).
   */
  isExcluded: (tableColumn: string, value: unknown) => boolean

  /**
   * Get the field state for a given "Table.Column" key.
   * Returns undefined if not loaded.
   */
  getFieldState: (tableColumn: string) => FieldState | undefined

  /** Clear all selection state (e.g., on project/page change) */
  clear: () => void
}

export const useSelectionStateStore = create<SelectionStateStore>()((set, get) => ({
  fields: {},
  loading: false,
  error: null,
  lastFetchMs: 0,
  _debounceTimer: null,
  explorationMode: {},

  toggleExplorationMode: (pageId: string) => {
    set((state) => ({
      explorationMode: {
        ...state.explorationMode,
        [pageId]: !state.explorationMode[pageId],
      },
    }))
  },

  isExplorationMode: (pageId: string) => {
    return get().explorationMode[pageId] ?? false
  },

  fetchSelectionState: (request, project, role) => {
    const state = get()
    if (state._debounceTimer) {
      clearTimeout(state._debounceTimer)
    }

    const timer = setTimeout(() => {
      get().fetchSelectionStateNow(request, project, role)
    }, 200)

    set({ _debounceTimer: timer })
  },

  fetchSelectionStateNow: async (request, project, role) => {
    set({ loading: true, error: null, _debounceTimer: null })

    try {
      // Use app store project/role if not explicitly provided
      const appState = useAppStore.getState()
      const resolvedProject = project ?? appState.projectPath ?? undefined
      const resolvedRole = role ?? appState.currentRole ?? undefined

      const response = await getSelectionState(request, resolvedProject, resolvedRole)

      if (response.error) {
        set({
          loading: false,
          error: response.error ?? 'Selection state fetch failed',
        })
        return
      }

      const data = response.data
      if (!data?.fields) {
        set({ loading: false, error: 'No fields in response' })
        return
      }

      // Convert arrays to Sets for O(1) lookup
      const newFields: Record<string, FieldState> = {}
      const existingFields = get().fields

      for (const [key, fieldData] of Object.entries(data.fields)) {
        const fd = fieldData as FieldSelectionState
        newFields[key] = {
          allValues: fd.all_values ?? [],
          possible: new Set((fd.possible ?? []).map(String)),
          excluded: new Set((fd.excluded ?? []).map(String)),
          counts: fd.counts,
          error: fd.error,
        }
      }

      // Merge: keep existing fields not in the response (incremental mode)
      const merged = { ...existingFields, ...newFields }

      set({
        fields: merged,
        loading: false,
        error: null,
        lastFetchMs: Date.now(),
      })
    } catch (err) {
      set({
        loading: false,
        error: err instanceof Error ? err.message : String(err),
      })
    }
  },

  isPossible: (tableColumn, value) => {
    const field = get().fields[tableColumn]
    if (!field) return true // optimistic: treat as possible if not loaded
    return field.possible.has(String(value))
  },

  isExcluded: (tableColumn, value) => {
    const field = get().fields[tableColumn]
    if (!field) return false // optimistic
    return field.excluded.has(String(value))
  },

  getFieldState: (tableColumn) => {
    return get().fields[tableColumn]
  },

  clear: () => {
    const state = get()
    if (state._debounceTimer) {
      clearTimeout(state._debounceTimer)
    }
    set({
      fields: {},
      loading: false,
      error: null,
      lastFetchMs: 0,
      _debounceTimer: null,
    })
  },
}))

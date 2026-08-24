import { create } from 'zustand'
import type { PageInfo, VisualInfo } from '@/lib/api'
import type { Filter } from '@/stores/filter-store'

export interface ReportSnapshot {
  pages: PageInfo[]
  currentPageId: string | null
  visuals: VisualInfo[]
  selectedVisualId: string | null
}

export interface FilterSnapshot {
  reportFilters: Filter[]
  pageFilters: Record<string, Filter[]>
  visualFilters: Record<string, Filter[]>
}

export interface UndoSnapshot {
  report: ReportSnapshot
  filters: FilterSnapshot
}

interface HistoryEntry {
  snapshot: UndoSnapshot
  hash: string
}

export interface UndoRedoState {
  past: HistoryEntry[]
  present: HistoryEntry | null
  future: HistoryEntry[]
  maxSize: number
  pushSnapshot: (snapshot: UndoSnapshot, hash: string) => void
  undo: () => UndoSnapshot | null
  redo: () => UndoSnapshot | null
  reset: () => void
}

const initialState = {
  past: [] as HistoryEntry[],
  present: null as HistoryEntry | null,
  future: [] as HistoryEntry[],
  maxSize: 50,
}

export const useUndoRedoStore = create<UndoRedoState>((set, get) => ({
  ...initialState,

  pushSnapshot: (snapshot, hash) => set((state) => {
    if (state.present?.hash === hash) return state

    const entry: HistoryEntry = { snapshot, hash }
    if (!state.present) {
      return { ...state, present: entry }
    }

    const nextPast = [...state.past, state.present]
    const trimmedPast = nextPast.length > state.maxSize
      ? nextPast.slice(nextPast.length - state.maxSize)
      : nextPast

    return {
      ...state,
      past: trimmedPast,
      present: entry,
      future: [],
    }
  }),

  undo: () => {
    const state = get()
    if (!state.present || state.past.length === 0) return null

    const previous = state.past[state.past.length - 1]
    const nextPast = state.past.slice(0, -1)
    const nextFuture = [state.present, ...state.future]

    set({
      past: nextPast,
      present: previous,
      future: nextFuture,
    })

    return previous.snapshot
  },

  redo: () => {
    const state = get()
    if (!state.present || state.future.length === 0) return null

    const next = state.future[0]
    const nextFuture = state.future.slice(1)
    const nextPast = [...state.past, state.present]

    set({
      past: nextPast,
      present: next,
      future: nextFuture,
    })

    return next.snapshot
  },

  reset: () => set({ ...initialState }),
}))

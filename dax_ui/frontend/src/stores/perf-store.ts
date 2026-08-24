import { create } from 'zustand'

/**
 * Performance Analyzer store — tracks render timing events for visuals,
 * modeled after Power BI's Performance Analyzer.
 *
 * Key concepts:
 * - Recording: when enabled, every render event is captured
 * - PerfEvent: one render cycle for a single visual (network + server timing)
 * - Events are listed chronologically, expandable to show SQL + breakdown
 */

export interface PerfEvent {
  /** Monotonically increasing sequence ID */
  id: number
  /** ISO timestamp */
  timestamp: string
  /** Visual ID */
  visualId: string
  /** Visual title (display label) */
  visualTitle: string
  /** Visual type (bar, table, matrix, card, …) */
  visualType: string

  // ── Timing breakdown (all in ms) ──────────────────────
  /** Total round-trip time (client-measured, start-to-finish) */
  totalMs: number
  /** Server-side: IR planning + SQL compilation (from response.query.plan_ms) */
  planMs: number
  /** Server-side: DuckDB execution (from response.query.execution_ms) */
  executeMs: number
  /** Inferred network / other = totalMs - planMs - executeMs */
  otherMs: number

  // ── Query details ─────────────────────────────────────
  /** Compiled SQL (from response.query.sql) */
  sql: string
  /** Row count returned */
  rowCount: number

  /** Whether the render succeeded */
  success: boolean
  /** Error message if render failed */
  error?: string
}

export interface PerfState {
  /** Whether the performance analyzer panel is visible */
  isOpen: boolean
  /** Whether recording is active */
  isRecording: boolean
  /** All captured events (newest first) */
  events: PerfEvent[]
  /** Expanded event IDs (for UI accordion) */
  expandedIds: Set<number>
  /** Monotone counter for event IDs */
  _nextId: number

  // Actions
  toggle: () => void
  open: () => void
  close: () => void
  startRecording: () => void
  stopRecording: () => void
  clearEvents: () => void
  addEvent: (event: Omit<PerfEvent, 'id' | 'timestamp' | 'otherMs'>) => void
  toggleExpanded: (id: number) => void
  expandAll: () => void
  collapseAll: () => void
}

export const usePerfStore = create<PerfState>()((set, get) => ({
  isOpen: false,
  isRecording: false,
  events: [],
  expandedIds: new Set<number>(),
  _nextId: 1,

  toggle: () => set(s => ({ isOpen: !s.isOpen })),
  open: () => set({ isOpen: true }),
  close: () => set({ isOpen: false }),

  startRecording: () => set({ isRecording: true }),
  stopRecording: () => set({ isRecording: false }),

  clearEvents: () => set({ events: [], expandedIds: new Set() }),

  addEvent: (partial) => {
    const state = get()
    if (!state.isRecording) return

    const id = state._nextId
    const otherMs = Math.max(0, partial.totalMs - partial.planMs - partial.executeMs)
    const event: PerfEvent = {
      ...partial,
      id,
      timestamp: new Date().toISOString(),
      otherMs,
    }

    set({
      events: [event, ...state.events],
      _nextId: id + 1,
    })
  },

  toggleExpanded: (id) =>
    set(s => {
      const next = new Set(s.expandedIds)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return { expandedIds: next }
    }),

  expandAll: () =>
    set(s => ({ expandedIds: new Set(s.events.map(e => e.id)) })),

  collapseAll: () => set({ expandedIds: new Set() }),
}))

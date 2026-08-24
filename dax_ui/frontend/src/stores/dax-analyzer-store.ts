import { create } from 'zustand'

export interface MeasureComplexity {
  nesting_depth: number
  filter_contexts: number
  iterator_count: number
  measure_refs: string[]
  tables_referenced: string[]
  pattern: string
}

export interface AnalyzedMeasure {
  name: string
  dax: string
  compiled_sql: string | null
  complexity: MeasureComplexity
  sql_plan: string | null
  suggestions: string[]
  error: string | null
}

export interface DaxAnalyzerState {
  isOpen: boolean
  isAnalyzing: boolean
  selectedMeasures: string[]
  results: AnalyzedMeasure[]
  error: string | null

  toggle: () => void
  open: (measures?: string[]) => void
  close: () => void
  setSelectedMeasures: (measures: string[]) => void
  analyze: () => Promise<void>
  clear: () => void
}

export const useDaxAnalyzerStore = create<DaxAnalyzerState>()((set, get) => ({
  isOpen: false,
  isAnalyzing: false,
  selectedMeasures: [],
  results: [],
  error: null,

  toggle: () => set(s => ({ isOpen: !s.isOpen })),

  open: (measures) => set({
    isOpen: true,
    ...(measures ? { selectedMeasures: measures } : {}),
  }),

  close: () => set({ isOpen: false }),

  setSelectedMeasures: (measures) => set({ selectedMeasures: measures }),

  analyze: async () => {
    const { selectedMeasures } = get()
    if (selectedMeasures.length === 0) {
      set({ error: 'Select at least one measure to analyze.' })
      return
    }

    set({ isAnalyzing: true, error: null })

    try {
      const response = await fetch('/runtime/dax/analyze', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ measures: selectedMeasures }),
      })

      const data = await response.json()

      if (!response.ok || data.ok === false) {
        set({ isAnalyzing: false, error: data.error || `HTTP ${response.status}` })
        return
      }

      set({
        isAnalyzing: false,
        results: data.measures ?? [],
        error: null,
      })
    } catch (err) {
      set({
        isAnalyzing: false,
        error: err instanceof Error ? err.message : 'Analysis failed',
      })
    }
  },

  clear: () => set({ results: [], error: null }),
}))

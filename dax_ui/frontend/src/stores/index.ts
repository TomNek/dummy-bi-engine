// Re-export all stores for convenient imports
export { useAppStore, type AppState, type TableInfo } from './app-store'
export { useReportStore, type ReportState, type VisualInfo, type PageInfo, type VisualGroup } from './report-store'
export { useFilterStore, type FilterState, type Filter, type FilterValue } from './filter-store'
export { useUndoRedoStore, type UndoRedoState, type UndoSnapshot } from './undo-redo-store'
export { useModelViewStore, type ModelViewState, type ModelViewLayout, type NodePosition } from './model-view-store'
export { useThemeStore, type ThemeState } from './theme-store'
export { usePerfStore, type PerfState, type PerfEvent } from './perf-store'
export { useSlicerDockStore, type SlicerDockState, type DockPosition, type SlicerGroup } from './slicer-dock-store'
export { 
  useFormulaBarStore, 
  useFormulaBarSelection,
  useFormulaBarDax,
  useFormulaBarError,
  useFormulaBarLoading,
  useFormulaBarIsDirty,
  type FormulaBarState, 
  type FormulaBarSelection,
  type FormulaBarSelectionKind 
} from './formula-bar-store'
export { useAutogenStore, type AutogenState } from './autogen-store'
export { useSubscriptionStore, type SubscriptionState } from './subscription-store'
export { useMLStore, type MLState, type MLActivity } from './ml-store'
export { useServerStore, type ServerState } from './server-store'
export { useDaxAnalyzerStore, type DaxAnalyzerState, type AnalyzedMeasure, type MeasureComplexity } from './dax-analyzer-store'
export { useSelectionStateStore, type SelectionStateStore, type FieldState } from './selection-state-store'
export { useStoryStore, type StoryState } from './story-store'

// ── Explanation / Playbook types ──────────────────────────────────────
export interface ExplanationEDU {
  id: string
  metric: string
  comparator?: string
  grain?: Record<string, string>
  description?: string
  higher_is_better?: boolean
}

export interface ExplanationDriver {
  id: string
  parent_edu_id: string
  mode: string
  child_metrics?: (string | { metric: string; sign: number })[]
  dimension_table?: string
  dimension_column?: string
  effects?: string[]
  priority?: number
  description?: string
  materiality?: { abs_threshold: number; rel_threshold: number; top_n: number }
}

export interface PlaybookMeta {
  name: string
  version: string
  description: string
  edus: ExplanationEDU[]
  drivers: ExplanationDriver[]
  default_materiality?: { abs_threshold: number; rel_threshold: number; top_n: number }
}

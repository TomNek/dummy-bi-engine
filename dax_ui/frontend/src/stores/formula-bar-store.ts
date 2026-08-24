import { create } from 'zustand'

export type FormulaBarSelectionKind = 
  | 'measure'
  | 'calc_item'
  | 'field_parameter'
  | 'calc_table'
  | 'calc_column'
  | 'what_if_parameter'

export interface FormulaBarSelection {
  kind: FormulaBarSelectionKind
  name?: string
  table?: string
  column?: string
  group?: string
  item?: string
}

export interface FormulaBarState {
  // Selection
  selection: FormulaBarSelection | null
  
  // DAX expression
  dax: string
  originalDax: string // To track dirty state
  
  // Error state
  error: string | null
  
  // Loading state
  loading: boolean
  
  // Dirty state (user has edited DAX)
  isDirty: boolean
  
  // Actions
  setSelection: (selection: FormulaBarSelection | null) => void
  setDax: (dax: string) => void
  setOriginalDax: (dax: string) => void
  setError: (error: string | null) => void
  setLoading: (loading: boolean) => void
  clearSelection: () => void
  reset: () => void
}

const initialState = {
  selection: null,
  dax: '',
  originalDax: '',
  error: null,
  loading: false,
  isDirty: false,
}

export const useFormulaBarStore = create<FormulaBarState>((set) => ({
  ...initialState,
  
  setSelection: (selection) => set({ 
    selection,
    dax: '',
    originalDax: '',
    error: null,
    isDirty: false,
  }),
  
  setDax: (dax) => set((state) => ({
    dax,
    isDirty: dax !== state.originalDax,
  })),
  
  setOriginalDax: (dax) => set({
    dax,
    originalDax: dax,
    isDirty: false,
  }),
  
  setError: (error) => set({ error }),
  
  setLoading: (loading) => set({ loading }),
  
  clearSelection: () => set({
    selection: null,
    dax: '',
    originalDax: '',
    error: null,
    isDirty: false,
  }),
  
  reset: () => set(initialState),
}))

// Selector hooks for convenience
export const useFormulaBarSelection = () => useFormulaBarStore((state) => state.selection)
export const useFormulaBarDax = () => useFormulaBarStore((state) => state.dax)
export const useFormulaBarError = () => useFormulaBarStore((state) => state.error)
export const useFormulaBarLoading = () => useFormulaBarStore((state) => state.loading)
export const useFormulaBarIsDirty = () => useFormulaBarStore((state) => state.isDirty)

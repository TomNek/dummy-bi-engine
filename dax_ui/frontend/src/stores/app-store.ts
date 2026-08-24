import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import type { VisualTypeInfo, HierarchiesMap } from '@/lib/api'

export interface TableInfo {
  name: string
  columns: string[]
  table_type?: string | null
  is_calculated?: boolean
  storage_mode?: string | null
  virtual?: boolean
  semantic_type?: string | null
  param_name?: string
  group_name?: string
  /** Column-level sort_by_column map: { colName -> sortByColName } */
  sort_by_columns?: Record<string, string>
  /** Column-level type map: { colName -> DuckDB type string } */
  column_types?: Record<string, string>
}

export interface Relationship {
  from_table: string
  from_column: string
  to_table: string
  to_column: string
  active: boolean
  rel_id?: string
  cross_filter_direction?: 'single' | 'both'
  cardinality?: string | null
}

export interface SecurityRole {
  name: string
  rls?: Record<string, string>  // table -> filter expression
  ols?: {
    tables?: string[]     // hidden tables
    measures?: string[]   // hidden measures
    columns?: Record<string, string[]>  // table -> hidden columns
  }
}

export interface ExplanationEDU {
  id: string
  metric: string
  comparator?: string
  description?: string
  grain?: Record<string, string>
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

export type AppViewMode = 'report' | 'model' | 'data' | 'transform'

export interface AppState {
  // Project state
  projectPath: string | null
  projectSource: 'query' | 'env' | 'manual' | null
  projectLoading: boolean
  projectError: string | null
  
  // Server mode: 'author' = desktop app (free, no auth), 'server' = Report Server (paid, role-based auth)
  serverMode: 'author' | 'server'
  // User's role on the server: admin/editor/viewer (only relevant in server mode)
  userRole: 'admin' | 'editor' | 'viewer'
  
  // Model data
  tables: TableInfo[]
  measures: string[]
  relationships: Relationship[]
  visualTypes: Record<string, VisualTypeInfo>
  explanations: PlaybookMeta[]
  hierarchies: HierarchiesMap
  hierarchiesSaved: HierarchiesMap
  
  // Dirty state tracking
  isDirty: boolean
  isFiltersDirty: boolean
  isSlicersDirty: boolean
  isBookmarksDirty: boolean
  isVisualsDirty: boolean
  isSecurityDirty: boolean
  isHierarchiesDirty: boolean
  saveInProgress: boolean
  saveError: string | null
  
  // Role state
  roles: SecurityRole[]
  defaultRole: string | null
  currentRole: string | null
  
  // UI state
  leftSidebarOpen: boolean
  rightSidebarOpen: boolean
  leftSidebarWidth: number
  rightSidebarWidth: number
  canvasWidth: number
  canvasHeight: number
  canvasZoom: number
  snapToGrid: boolean
  gridSize: number
  smartGuidesEnabled: boolean
  smartGuideThreshold: number
  leftSidebarTab: 'fields' | 'model'
  rightSidebarTab: 'filters' | 'properties' | 'visualizations' | 'slicers' | 'bookmarks'
  
  // View mode
  viewMode: AppViewMode
  
  // Focus mode
  focusedVisualId: string | null
  isFullView: boolean
  
  // Selection pane (separate collapsible sidebar)
  selectionPaneOpen: boolean

  // Interaction editor visibility within right sidebar
  interactionSidebarOpen: boolean

  // Auto-refresh: when true, visuals auto-refresh on encoding changes
  autoRefresh: boolean

  // Theme
  theme: 'light' | 'dark' | 'system'
  
  // Actions
  setProjectPath: (path: string | null) => void
  setProjectSource: (source: 'query' | 'env' | 'manual' | null) => void
  setProjectLoading: (loading: boolean) => void
  setProjectError: (error: string | null) => void
  setModelData: (tables: TableInfo[], measures: string[], relationships?: Relationship[]) => void
  setRelationships: (relationships: Relationship[]) => void
  setExplanations: (explanations: PlaybookMeta[]) => void
  setVisualTypes: (types: Record<string, VisualTypeInfo>) => void
  setHierarchies: (hierarchies: HierarchiesMap) => void
  updateHierarchiesDraft: (hierarchies: HierarchiesMap) => void
  resetHierarchiesDraft: () => void
  markHierarchiesClean: () => void
  setRoles: (roles: SecurityRole[], defaultRole: string | null) => void
  setCurrentRole: (role: string | null) => void
  toggleLeftSidebar: () => void
  toggleRightSidebar: () => void
  setLeftSidebarTab: (tab: 'fields' | 'model') => void
  setRightSidebarTab: (tab: 'filters' | 'properties' | 'visualizations' | 'slicers' | 'bookmarks') => void
  toggleSelectionPane: () => void
  setSelectionPaneOpen: (open: boolean) => void
  toggleInteractionSidebar: () => void
  setInteractionSidebarOpen: (open: boolean) => void
  setAutoRefresh: (autoRefresh: boolean) => void
  toggleAutoRefresh: () => void
  setLeftSidebarWidth: (width: number) => void
  setRightSidebarWidth: (width: number) => void
  setCanvasSize: (width: number, height: number) => void
  setCanvasZoom: (zoom: number) => void
  setSnapToGrid: (snap: boolean) => void
  setGridSize: (size: number) => void
  setSmartGuidesEnabled: (enabled: boolean) => void
  setSmartGuideThreshold: (threshold: number) => void
  setViewMode: (mode: AppViewMode) => void
  setFocusedVisualId: (id: string | null) => void
  setFullView: (fullView: boolean) => void
  setTheme: (theme: 'light' | 'dark' | 'system') => void
  setServerMode: (mode: 'author' | 'server') => void
  setUserRole: (role: 'admin' | 'editor' | 'viewer') => void
  setTableType: (tableName: string, tableType: 'fact' | 'dim' | 'bridge' | null) => void
  reset: () => void
  
  // Dirty state actions
  setDirty: (dirty: boolean) => void
  setFiltersDirty: (dirty: boolean) => void
  setSlicersDirty: (dirty: boolean) => void
  setBookmarksDirty: (dirty: boolean) => void
  setVisualsDirty: (dirty: boolean) => void
  setSecurityDirty: (dirty: boolean) => void
  setHierarchiesDirty: (dirty: boolean) => void
  setSaveInProgress: (inProgress: boolean) => void
  setSaveError: (error: string | null) => void
  markClean: () => void
}

const initialState = {
  projectPath: null,
  projectSource: null,
  projectLoading: false,
  projectError: null,
  serverMode: 'author' as 'author' | 'server',
  userRole: 'admin' as 'admin' | 'editor' | 'viewer',
  tables: [],
  measures: [],
  relationships: [],
  visualTypes: {} as Record<string, VisualTypeInfo>,
  explanations: [],
  hierarchies: {} as HierarchiesMap,
  hierarchiesSaved: {} as HierarchiesMap,
  roles: [],
  defaultRole: null,
  currentRole: null,
  leftSidebarOpen: true,
  rightSidebarOpen: true,
  leftSidebarWidth: 256,
  rightSidebarWidth: 288,
  canvasWidth: 1280,
  canvasHeight: 720,
  canvasZoom: 100,
  snapToGrid: true,
  gridSize: 10,
  smartGuidesEnabled: true,
  smartGuideThreshold: 5,
  leftSidebarTab: 'fields' as const,
  rightSidebarTab: 'filters' as const,
  viewMode: 'report' as AppViewMode,
  focusedVisualId: null as string | null,
  isFullView: false,
  selectionPaneOpen: false,
  interactionSidebarOpen: true,
  autoRefresh: true,
  theme: 'system' as 'light' | 'dark' | 'system',
  // Dirty state
  isDirty: false,
  isFiltersDirty: false,
  isSlicersDirty: false,
  isBookmarksDirty: false,
  isVisualsDirty: false,
  isSecurityDirty: false,
  isHierarchiesDirty: false,
  saveInProgress: false,
  saveError: null,
}

export const useAppStore = create<AppState>()(
  persist(
    (set) => ({
      ...initialState,
      
      // Actions
      setProjectPath: (projectPath) => set({ projectPath, projectError: null }),
      setProjectSource: (projectSource) => set({ projectSource }),
      setProjectLoading: (projectLoading) => set({ projectLoading }),
      setProjectError: (projectError) => set({ projectError, projectLoading: false }),
      setModelData: (tables, measures, relationships = []) => set({ tables, measures, relationships }),
      setRelationships: (relationships) => set({ relationships }),
      setExplanations: (explanations) => set({ explanations }),
      setVisualTypes: (visualTypes) => set({ visualTypes }),
      setHierarchies: (hierarchies) => set({ hierarchies, hierarchiesSaved: hierarchies, isHierarchiesDirty: false }),
      updateHierarchiesDraft: (hierarchies) => set({
        hierarchies,
        isHierarchiesDirty: true,
        isDirty: true,
      }),
      resetHierarchiesDraft: () => set((state) => ({
        hierarchies: state.hierarchiesSaved,
        isHierarchiesDirty: false,
        isDirty: state.isFiltersDirty || state.isSlicersDirty || state.isVisualsDirty || state.isSecurityDirty,
      })),
      markHierarchiesClean: () => set((state) => ({
        hierarchiesSaved: state.hierarchies,
        isHierarchiesDirty: false,
      })),
      setRoles: (roles, defaultRole) => set({ roles, defaultRole }),
      setCurrentRole: (currentRole) => set({ currentRole }),
      toggleLeftSidebar: () => set((state) => ({ leftSidebarOpen: !state.leftSidebarOpen })),
      toggleRightSidebar: () => set((state) => ({ rightSidebarOpen: !state.rightSidebarOpen })),
      setLeftSidebarTab: (leftSidebarTab) => set({ leftSidebarTab }),
      setRightSidebarTab: (rightSidebarTab) => set({ rightSidebarTab }),
      setLeftSidebarWidth: (leftSidebarWidth) => set({ leftSidebarWidth: Math.max(180, Math.min(480, leftSidebarWidth)) }),
      setRightSidebarWidth: (rightSidebarWidth) => set({ rightSidebarWidth: Math.max(220, Math.min(520, rightSidebarWidth)) }),
      setCanvasSize: (canvasWidth, canvasHeight) => set({ 
        canvasWidth: Math.max(320, Math.min(3840, canvasWidth)), 
        canvasHeight: Math.max(240, Math.min(2160, canvasHeight)) 
      }),
      setCanvasZoom: (canvasZoom) => set({ canvasZoom: Math.max(50, Math.min(200, canvasZoom)) }),
      setSnapToGrid: (snapToGrid) => set({ snapToGrid }),
      setGridSize: (gridSize) => set({ gridSize: Math.max(5, Math.min(50, gridSize)) }),
      setSmartGuidesEnabled: (smartGuidesEnabled) => set({ smartGuidesEnabled }),
      setSmartGuideThreshold: (smartGuideThreshold) => set({ smartGuideThreshold: Math.max(1, Math.min(20, smartGuideThreshold)) }),
      setViewMode: (viewMode) => set({ viewMode }),
      setFocusedVisualId: (focusedVisualId) => set({ focusedVisualId }),
      setFullView: (isFullView) => set({ isFullView }),
      toggleSelectionPane: () => set((state) => ({ selectionPaneOpen: !state.selectionPaneOpen })),
      setSelectionPaneOpen: (selectionPaneOpen) => set({ selectionPaneOpen }),
      toggleInteractionSidebar: () => set((state) => ({ interactionSidebarOpen: !state.interactionSidebarOpen })),
      setInteractionSidebarOpen: (interactionSidebarOpen) => set({ interactionSidebarOpen }),
      setAutoRefresh: (autoRefresh) => set({ autoRefresh }),
      toggleAutoRefresh: () => set((state) => ({ autoRefresh: !state.autoRefresh })),
      setTheme: (theme) => set({ theme }),
      setServerMode: (serverMode) => set({ serverMode }),
      setUserRole: (userRole) => set({ userRole }),
      setTableType: (tableName, tableType) => set((state) => ({
        tables: state.tables.map(t =>
          t.name === tableName ? { ...t, table_type: tableType } : t
        ),
      })),
      reset: () => set(initialState),
      
      // Dirty state actions
      setDirty: (isDirty) => set({ isDirty }),
      setFiltersDirty: (isFiltersDirty) => set((state) => ({ 
        isFiltersDirty, 
        isDirty: isFiltersDirty || state.isSlicersDirty || state.isBookmarksDirty || state.isVisualsDirty || state.isSecurityDirty 
      })),
      setSlicersDirty: (isSlicersDirty) => set((state) => ({ 
        isSlicersDirty, 
        isDirty: state.isFiltersDirty || isSlicersDirty || state.isVisualsDirty || state.isSecurityDirty || state.isHierarchiesDirty 
      })),
      setBookmarksDirty: (isBookmarksDirty) => set((state) => ({
        isBookmarksDirty,
        isDirty: state.isFiltersDirty || state.isSlicersDirty || isBookmarksDirty || state.isVisualsDirty || state.isSecurityDirty || state.isHierarchiesDirty 
      })),
      setVisualsDirty: (isVisualsDirty) => set((state) => ({ 
        isVisualsDirty, 
        isDirty: state.isFiltersDirty || state.isSlicersDirty || isVisualsDirty || state.isSecurityDirty || state.isHierarchiesDirty 
      })),
      setSecurityDirty: (isSecurityDirty) => set((state) => ({ 
        isSecurityDirty, 
        isDirty: state.isFiltersDirty || state.isSlicersDirty || state.isVisualsDirty || isSecurityDirty || state.isHierarchiesDirty 
      })),
      setHierarchiesDirty: (isHierarchiesDirty) => set((state) => ({
        isHierarchiesDirty,
        isDirty: state.isFiltersDirty || state.isSlicersDirty || state.isVisualsDirty || state.isSecurityDirty || isHierarchiesDirty,
      })),
      setSaveInProgress: (saveInProgress) => set({ saveInProgress }),
      setSaveError: (saveError) => set({ saveError }),
      markClean: () => set({ 
        isDirty: false, 
        isFiltersDirty: false, 
        isSlicersDirty: false, 
        isBookmarksDirty: false, 
        isSecurityDirty: false,
        isHierarchiesDirty: false,
        saveError: null 
      }),
    }),
    {
      name: 'dax-app-store',
      // Only persist UI preferences, not transient data
      partialize: (state) => ({
        leftSidebarOpen: state.leftSidebarOpen,
        rightSidebarOpen: state.rightSidebarOpen,
        leftSidebarWidth: state.leftSidebarWidth,
        rightSidebarWidth: state.rightSidebarWidth,
        canvasWidth: state.canvasWidth,
        canvasHeight: state.canvasHeight,
        canvasZoom: state.canvasZoom,
        snapToGrid: state.snapToGrid,
        gridSize: state.gridSize,
        smartGuidesEnabled: state.smartGuidesEnabled,
        smartGuideThreshold: state.smartGuideThreshold,
        leftSidebarTab: state.leftSidebarTab,
        rightSidebarTab: state.rightSidebarTab,
        viewMode: state.viewMode,
        selectionPaneOpen: state.selectionPaneOpen,
        interactionSidebarOpen: state.interactionSidebarOpen,
        autoRefresh: state.autoRefresh,
        theme: state.theme,
        currentRole: state.currentRole,
        visualTypes: state.visualTypes,
      }),
    }
  )
)

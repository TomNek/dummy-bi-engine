import { useEffect, useMemo, useRef, useState, useCallback } from 'react'
import { TooltipProvider } from '@/components/ui/tooltip'
import { Toaster } from '@/components/ui/toast'
import { 
  Topbar, 
  LeftSidebar, 
  RightSidebar, 
  SelectionSidebar,
  VisualsPane,
  Canvas,
  PageTabs,
  ProjectPicker,
  FormulaBar,
  StatusBar,
} from '@/components/layout'
import { ViewSwitcher } from '@/components/layout/ViewSwitcher'
import { FocusMode } from '@/components/layout/FocusMode'
import { PerformanceAnalyzer } from '@/components/layout/PerformanceAnalyzer'
import { DaxAnalyzer } from '@/components/layout/DaxAnalyzer'
import { SlicerDockPanel, SyncSlicersPanel } from '@/components/slicers'
import { RelationshipGraph } from '@/components/model/RelationshipGraph'
import { ModelViewTabs } from '@/components/model/ModelViewTabs'
import { DataView } from '@/components/data/DataView'
import { TransformStudio } from '@/components/power-query/TransformStudio'
import { EDUDiagram, MLAnalyticsPanel } from '@/components/explanations'
import { AutogenWizard } from '@/components/autogen'
import { StoryViewer } from '@/components/stories'
import { StoryEditor } from '@/components/stories'
// Phase 18 (Hypothesis Simulation) — deferred to v2
// import { ScenarioPanel } from '@/components/decision'
import { useRuntimeState } from '@/hooks'
import { useTheme } from '@/hooks'
import { useIsViewer } from '@/hooks'
import { useAppStore, useReportStore, useStoryStore } from '@/stores'
import {
  HAS_EDU_RELATIONSHIPS,
  HAS_ML_ANALYTICS,
  HAS_REPORT_AUTOGENERATION,
  HAS_STORIES,
  HAS_TRANSFORM_STUDIO,
  IS_OPEN_CORE,
} from '@/lib/edition'
import { UpdateManager } from '@/components/updates/UpdateManager'
import { PRODUCT_NAME } from '@/lib/product'
import { addRecentProject } from '@/lib/api'

function App() {
  const { bootstrap, loadState } = useRuntimeState()
  // Apply theme (dark class on <html>) at root level
  useTheme()
  const projectLoading = useAppStore(s => s.projectLoading)
  const projectError = useAppStore(s => s.projectError)
  const viewMode = useAppStore(s => s.viewMode)
  const setViewMode = useAppStore(s => s.setViewMode)
  const isFullView = useAppStore(s => s.isFullView)
  const presentingStoryId = useStoryStore(s => s.presentingStoryId)
  const isPresenting = HAS_STORIES && !!presentingStoryId
  const reportLoading = useReportStore(s => s.loading)
  const isViewer = useIsViewer()
  const [syncSlicersOpen, setSyncSlicersOpen] = useState(false)
  const [projectPickerOpen, setProjectPickerOpen] = useState(false)
  const [projectPickerValue, setProjectPickerValue] = useState('')
  const [projectPickerError, setProjectPickerError] = useState<string | null>(null)
  const [modelSubView, setModelSubView] = useState<'tables' | 'edu' | 'ml'>('tables')

  // ── Resizable story sidebar ──
  const [storySidebarWidth, setStorySidebarWidth] = useState(288) // default w-72 = 288px
  const storyResizing = useRef(false)
  const storyResizeStart = useRef({ x: 0, w: 0 })

  const handleStoryResizePointerDown = useCallback((e: React.PointerEvent) => {
    e.preventDefault()
    storyResizing.current = true
    storyResizeStart.current = { x: e.clientX, w: storySidebarWidth }
    const el = e.currentTarget as HTMLElement
    el.setPointerCapture(e.pointerId)
  }, [storySidebarWidth])

  const handleStoryResizePointerMove = useCallback((e: React.PointerEvent) => {
    if (!storyResizing.current) return
    // Dragging left edge: moving left = wider, moving right = narrower
    const delta = storyResizeStart.current.x - e.clientX
    const newWidth = Math.max(200, Math.min(600, storyResizeStart.current.w + delta))
    setStorySidebarWidth(newWidth)
  }, [])

  const handleStoryResizePointerUp = useCallback((e: React.PointerEvent) => {
    storyResizing.current = false
    const el = e.currentTarget as HTMLElement
    el.releasePointerCapture(e.pointerId)
  }, [])
  // Phase 18 (Hypothesis Simulation) — deferred to v2
  // const [scenarioPanelOpen, setScenarioPanelOpen] = useState(false)

  // Load initial state on mount (once only — bootstrap identity changes when
  // loadState deps shift after the first call; re-firing would set loading=true
  // again before the overlay has been removed from the DOM, causing an
  // "always visible" overlay race condition).
  const bootstrapRan = useRef(false)
  useEffect(() => {
    if (bootstrapRan.current) return
    bootstrapRan.current = true
    bootstrap().then((result) => {
      if (result && result.ok === false && result.needsProject) {
        const prefill = result.prefillProject?.trim() || ''
        if (prefill && !/%[^%]+%/.test(prefill)) {
          setProjectPickerValue(prefill)
        } else {
          setProjectPickerValue('')
        }
        useAppStore.getState().setProjectError(null)
        useReportStore.getState().setError(null)
        setProjectPickerError(null)
        setProjectPickerOpen(true)
      }
    })
  }, [bootstrap])

  useEffect(() => {
    if (!HAS_TRANSFORM_STUDIO && viewMode === 'transform') {
      setViewMode('report')
    }
  }, [setViewMode, viewMode])

  const isLoading = projectLoading || reportLoading
  const showReportSidebars = viewMode === 'report' || viewMode === 'model'

  // Story page detection: show StoryEditor when current page is a story page
  const currentPageId = useReportStore(s => s.currentPageId)
  const pages = useReportStore(s => s.pages)
  const isStoryPage = useMemo(() => {
    const page = pages.find(p => p.id === currentPageId)
    return HAS_STORIES && page?.page_type === 'story'
  }, [pages, currentPageId])

  // Dynamic document title
  const projectPath = useAppStore(s => s.projectPath)
  useEffect(() => {
    const name = projectPath?.split(/[\\/]/).filter(Boolean).pop()
    document.title = name ? `${name} — ${PRODUCT_NAME}` : PRODUCT_NAME
  }, [projectPath])

  // ── Global Ctrl+wheel zoom interception ──
  // Prevents browser-level zoom entirely; always routes to canvas zoom.
  useEffect(() => {
    const handler = (e: WheelEvent) => {
      if (e.ctrlKey || e.metaKey) {
        e.preventDefault()
        const delta = e.deltaY > 0 ? -10 : 10
        const store = useAppStore.getState()
        store.setCanvasZoom(store.canvasZoom + delta)
      }
    }
    // Must be non-passive to allow preventDefault on wheel events
    document.addEventListener('wheel', handler, { passive: false })
    return () => document.removeEventListener('wheel', handler)
  }, [])

  const handleProjectPickerChange = useCallback((next: string) => {
    setProjectPickerValue(next)
    setProjectPickerError(null)
  }, [])

  const handleProjectSubmit = useCallback(async (path?: string): Promise<boolean> => {
    const trimmed = (path ?? projectPickerValue).trim()
    if (!trimmed) {
      setProjectPickerError('Choose a project folder first.')
      return false
    }

    const result = await loadState({ project: trimmed, projectSource: 'manual' })
    if (result.ok) {
      await addRecentProject(trimmed)
      setProjectPickerOpen(false)
      setProjectPickerError(null)
      return true
    } else {
      setProjectPickerError(result.error || 'Project load failed.')
      return false
    }
  }, [loadState, projectPickerValue])

  const handleContinueWithoutProject = useCallback(() => {
    setProjectPickerOpen(false)
    setProjectPickerError(null)
    useAppStore.getState().setProjectError(null)
    useReportStore.getState().setError(null)

    const url = new URL(window.location.href)
    url.searchParams.delete('project')
    window.history.replaceState(null, '', url.toString())
  }, [])

  return (
    <TooltipProvider delayDuration={300}>
      <div className="flex flex-col h-screen" data-testid="app-root">
        {/* Top bar — hidden during story presentation */}
        {!isPresenting && <Topbar />}
        
        {/* Formula bar — hidden in full-view mode, viewer mode, and presentation */}
        {!isFullView && !isViewer && !isPresenting && <FormulaBar />}
        
        {/* Main content area */}
        <div className="flex flex-1 overflow-hidden">
          {/* View switcher icons (Report / Data / Model) */}
          {!isFullView && !isPresenting && <ViewSwitcher />}
          
          {/* Left sidebar (hidden in data view, full-view mode, and presentation) */}
          {showReportSidebars && !isFullView && !isPresenting && <LeftSidebar />}
          
          {/* Center content */}
          <div className="flex flex-col flex-1 overflow-hidden">
            {/* Loading overlay */}
            {isLoading && (
              <div className="absolute inset-0 bg-background/50 flex items-center justify-center z-50" data-testid="loading-overlay">
                <div className="flex flex-col items-center gap-2">
                  <div className="h-8 w-8 border-4 border-primary border-t-transparent rounded-full animate-spin" />
                  <span className="text-sm text-muted-foreground">Loading...</span>
                </div>
              </div>
            )}
            
            {/* Error display */}
            {projectError && !isLoading && !projectPickerOpen && (
              <div className="p-4 m-4 bg-destructive/10 border border-destructive rounded-md" data-testid="error-display">
                <p className="text-sm text-destructive">{projectError}</p>
              </div>
            )}
            
            {/* Center content: switch based on viewMode (viewer mode forces report view) */}
            {!isViewer && viewMode === 'model' ? (
              <>
                {/* Model sub-view toggle: Table Relationships vs EDU Relationships */}
                {(HAS_EDU_RELATIONSHIPS || HAS_ML_ANALYTICS) && <div className="flex items-center gap-1 px-3 py-1 border-b bg-muted/30" data-testid="model-subview-toggle">
                  <button
                    className={`px-3 py-1 text-xs rounded-md transition-colors ${modelSubView === 'tables' ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:bg-accent'}`}
                    onClick={() => setModelSubView('tables')}
                    data-testid="model-subview-tables"
                  >
                    Table Relationships
                  </button>
                  {HAS_EDU_RELATIONSHIPS && <button
                    className={`px-3 py-1 text-xs rounded-md transition-colors ${modelSubView === 'edu' ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:bg-accent'}`}
                    onClick={() => setModelSubView('edu')}
                    data-testid="model-subview-edu"
                  >
                    EDU Relationships
                  </button>}
                  {HAS_ML_ANALYTICS && <button
                    className={`px-3 py-1 text-xs rounded-md transition-colors ${modelSubView === 'ml' ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:bg-accent'}`}
                    onClick={() => setModelSubView('ml')}
                    data-testid="model-subview-ml"
                  >
                    ML Analytics
                  </button>}
                </div>}
                {(!HAS_EDU_RELATIONSHIPS && !HAS_ML_ANALYTICS) || modelSubView === 'tables' ? (
                  <>
                    <RelationshipGraph />
                    <ModelViewTabs />
                  </>
                ) : HAS_EDU_RELATIONSHIPS && modelSubView === 'edu' ? (
                  <div className="flex flex-col flex-1 overflow-auto">
                    {/* Phase 18 Simulate button — deferred to v2
                    <div className="flex items-center gap-2 px-3 py-1 border-b bg-muted/20">
                      <button
                        className={`px-2 py-1 text-xs rounded ${scenarioPanelOpen ? 'bg-primary text-primary-foreground' : 'border hover:bg-accent'}`}
                        onClick={() => setScenarioPanelOpen((v) => !v)}
                        data-testid="scenario-toggle-btn"
                      >
                        {scenarioPanelOpen ? 'Hide Simulator' : 'Simulate'}
                      </button>
                    </div>
                    */}
                    <div className="flex flex-1 overflow-hidden min-h-0">
                      <div className="flex-1 overflow-auto">
                        <EDUDiagram />
                      </div>
                      {/* Phase 18 ScenarioPanel sidebar — deferred to v2
                      {scenarioPanelOpen && (
                        <div className="w-80 border-l overflow-auto p-2" data-testid="scenario-sidebar">
                          <ScenarioPanel
                            kpiId="total_sales"
                            availableDrivers={[
                              { id: 'sales_additive', label: 'Sales Additive' },
                              { id: 'sales_by_category', label: 'Sales by Category' },
                            ]}
                            visible={true}
                          />
                        </div>
                      )}
                      */}
                    </div>
                  </div>
                ) : HAS_ML_ANALYTICS ? (
                  <MLAnalyticsPanel />
                ) : (
                  <>
                    <RelationshipGraph />
                    <ModelViewTabs />
                  </>
                )}
              </>
            ) : !isViewer && viewMode === 'data' ? (
              <DataView />
            ) : HAS_TRANSFORM_STUDIO && !isViewer && viewMode === 'transform' ? (
              <TransformStudio />
            ) : (
              <>
                {/* Top slicer dock */}
                <SlicerDockPanel position="top" />
                {/* Canvas row with left/right slicer docks */}
                <div className="flex flex-1 overflow-hidden min-h-0">
                  <SlicerDockPanel position="left" />
                  <Canvas />
                  <SlicerDockPanel position="right" />
                </div>
                {/* Bottom slicer dock */}
                <SlicerDockPanel position="bottom" />
                {!isFullView && !isPresenting && <PageTabs />}
                <PerformanceAnalyzer />
                <DaxAnalyzer />
              </>
            )}
          </div>
          
          {/* Story editor sidebar (shown only on story pages, hidden during presentation) */}
          {HAS_STORIES && viewMode === 'report' && !isFullView && !isViewer && !isPresenting && isStoryPage && (
            <div className="relative border-l bg-sidebar-background overflow-auto shrink-0" style={{ width: storySidebarWidth }} data-testid="story-editor-sidebar">
              {/* Resize handle on the left edge */}
              <div
                className="absolute left-0 top-0 bottom-0 w-1 cursor-col-resize hover:bg-primary/30 active:bg-primary/50 z-10 transition-colors"
                onPointerDown={handleStoryResizePointerDown}
                onPointerMove={handleStoryResizePointerMove}
                onPointerUp={handleStoryResizePointerUp}
                data-testid="story-sidebar-resize-handle"
              />
              <StoryEditor />
            </div>
          )}

          {/* Right sidebar (hidden in data view, full-view mode, viewer mode, and presentation) */}
          {showReportSidebars && !isFullView && !isViewer && !isPresenting && <VisualsPane />}
          {showReportSidebars && !isFullView && !isViewer && !isPresenting && <RightSidebar onOpenSyncSlicers={() => setSyncSlicersOpen(true)} />}
          {showReportSidebars && !isFullView && !isViewer && !isPresenting && <SyncSlicersPanel open={syncSlicersOpen} onClose={() => setSyncSlicersOpen(false)} />}

          {/* Selection sidebar (separate collapsible panel) */}
          {showReportSidebars && !isFullView && !isPresenting && <SelectionSidebar />}
        </div>

        {/* Status bar — hidden during presentation */}
        {!isPresenting && <StatusBar />}
      </div>

      <ProjectPicker
        open={projectPickerOpen}
        value={projectPickerValue}
        error={projectPickerError}
        onChange={handleProjectPickerChange}
        onSubmit={handleProjectSubmit}
        onContinue={handleContinueWithoutProject}
      />

      <FocusMode />
      {HAS_REPORT_AUTOGENERATION && <AutogenWizard />}
      {HAS_STORIES && <StoryViewer />}
      {IS_OPEN_CORE && <UpdateManager />}
      <Toaster />
    </TooltipProvider>
  )
}

export default App

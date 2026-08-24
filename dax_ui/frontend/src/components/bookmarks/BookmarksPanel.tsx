import { useState, useEffect, useCallback } from 'react'
import {
  Plus,
  Pencil,
  Trash2,
  Play,
  Check,
  X,
  RefreshCw,
  Bookmark as BookmarkIcon,
  FileText,
  Database,
  Eye as EyeIcon,
  LayoutGrid,
  Paintbrush,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { ScrollArea } from '@/components/ui/scroll-area'
import { useAppStore, useReportStore, useFilterStore } from '@/stores'
import { useBookmarks, useSlicers } from '@/hooks'
import type { Bookmark } from '@/lib/api'

interface BookmarksPanelProps {
  className?: string
}

export function BookmarksPanel({ className }: BookmarksPanelProps) {
  const projectPath = useAppStore(s => s.projectPath)
  const setBookmarksDirty = useAppStore(s => s.setBookmarksDirty)
  const currentPageId = useReportStore(s => s.currentPageId)
  const reportFilters = useFilterStore(s => s.reportFilters)
  const pageFilters = useFilterStore(s => s.pageFilters)
  const interactionFilters = useFilterStore(s => s.interactionFilters)
  const setReportFilters = useFilterStore(s => s.setReportFilters)
  const setPageFilters = useFilterStore(s => s.setPageFilters)
  const setInteractionFilters = useFilterStore(s => s.setInteractionFilters)
  const {
    bookmarks,
    loading,
    error,
    loadBookmarks,
    create,
    update,
    remove,
    apply,
  } = useBookmarks()
  const { slicerInstances, loadAll: loadSlicers } = useSlicers()

  // Local UI state
  const [creating, setCreating] = useState(false)
  const [newName, setNewName] = useState('')
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editName, setEditName] = useState('')
  const [applyingId, setApplyingId] = useState<string | null>(null)

  // Capture options (Power BI-style)
  const [capturePage, setCapturePage] = useState(true)
  const [captureData, setCaptureData] = useState(true)
  const [captureDisplay, setCaptureDisplay] = useState(true)
  const [captureVisualLayout, setCaptureVisualLayout] = useState(false)
  const [captureVisualDesign, setCaptureVisualDesign] = useState(false)

  // Load bookmarks on mount / project change
  useEffect(() => {
    if (projectPath) {
      loadBookmarks()
    }
  }, [projectPath, loadBookmarks])

  // Capture current UI state as bookmark payload
  const captureCurrentState = useCallback((): Omit<Bookmark, 'id' | 'name'> => {
    // Collect all filters (report + page + visual are persisted separately, but bookmark captures the full set)
    const allFilters = [
      ...reportFilters.map(f => ({ ...f })),
      ...Object.entries(pageFilters).flatMap(([pageId, filters]) =>
        filters.map(f => ({ ...f, page_id: pageId }))
      ),
    ]

    // Capture slicer selections from current instances
    const slicerSelections: Record<string, unknown[]> = {}
    for (const inst of slicerInstances) {
      if (inst.selected_values && Array.isArray(inst.selected_values) && inst.selected_values.length > 0) {
        slicerSelections[inst.id] = inst.selected_values
      }
    }

    // Capture interaction filters
    const interactionSelectionsCapture = interactionFilters.map(f => ({ ...f }))

    // Capture visual visibility from report store
    const { visualVisibility, visuals } = useReportStore.getState()
    const visibilityMap: Record<string, boolean> = {}
    for (const v of visuals) {
      visibilityMap[v.id] = visualVisibility[v.id] ?? true
    }

    // Capture visual layout (positions & sizes) from report store
    const layoutMap: Record<string, { x: number; y: number; width: number; height: number }> = {}
    if (captureVisualLayout) {
      for (const v of visuals) {
        layoutMap[v.id] = {
          x: v.x ?? 0,
          y: v.y ?? 0,
          width: v.width ?? 300,
          height: v.height ?? 200,
        }
      }
    }

    // Capture visual design (format + advanced_plotly_patch) from report store
    const designMap: Record<string, { format?: Record<string, unknown>; advanced_plotly_patch?: Record<string, unknown> }> = {}
    if (captureVisualDesign) {
      for (const v of visuals) {
        const entry: { format?: Record<string, unknown>; advanced_plotly_patch?: Record<string, unknown> } = {}
        if (v.format) entry.format = { ...v.format } as Record<string, unknown>
        if (v.advanced_plotly_patch) entry.advanced_plotly_patch = { ...v.advanced_plotly_patch }
        designMap[v.id] = entry
      }
    }

    return {
      current_page_id: currentPageId || '',
      filters: allFilters,
      slicer_selections: slicerSelections,
      interaction_selections: interactionSelectionsCapture,
      capture_page: capturePage,
      capture_data: captureData,
      capture_display: captureDisplay,
      capture_visual_layout: captureVisualLayout,
      capture_visual_design: captureVisualDesign,
      visual_visibility: visibilityMap,
      visual_layout: layoutMap,
      visual_design: designMap,
    }
  }, [reportFilters, pageFilters, interactionFilters, slicerInstances, currentPageId, capturePage, captureData, captureDisplay, captureVisualLayout, captureVisualDesign])

  const handleCreate = useCallback(async () => {
    const trimmed = newName.trim()
    if (!trimmed) return

    const state = captureCurrentState()
    const result = await create({
      ...state,
      name: trimmed,
    } as Omit<Bookmark, 'id'>)

    if (result.success) {
      setNewName('')
      setCreating(false)
      setBookmarksDirty(true)
    }
  }, [newName, captureCurrentState, create, setBookmarksDirty])

  const handleUpdate = useCallback(async (bookmarkId: string) => {
    const trimmed = editName.trim()
    if (!trimmed) return

    const result = await update(bookmarkId, { name: trimmed })
    if (result.success) {
      setEditingId(null)
      setEditName('')
      setBookmarksDirty(true)
    }
  }, [editName, update, setBookmarksDirty])

  const handleDelete = useCallback(async (bookmarkId: string, bookmarkName: string) => {
    if (!confirm(`Delete bookmark "${bookmarkName}"?`)) return

    const result = await remove(bookmarkId)
    if (result.success) {
      setBookmarksDirty(true)
    }
  }, [remove, setBookmarksDirty])

  const handleApply = useCallback(async (bookmarkId: string) => {
    setApplyingId(bookmarkId)
    const result = await apply(bookmarkId)
    if (result.success && result.data) {
      const data = result.data
      const shouldRestorePage = data.capture_page !== false
      const shouldRestoreData = data.capture_data !== false
      const shouldRestoreDisplay = data.capture_display !== false

      // Restore page (only if capture_page)
      if (shouldRestorePage && data.current_page_id) {
        const { setCurrentPage } = useReportStore.getState()
        setCurrentPage(data.current_page_id)
      }

      // Restore filters (only if capture_data)
      if (shouldRestoreData && data.filters) {
        const report: typeof reportFilters = []
        const page: Record<string, typeof reportFilters> = {}
        for (const f of data.filters) {
          const fAny = f as Record<string, unknown>
          if (fAny.page_id) {
            const pid = String(fAny.page_id)
            if (!page[pid]) page[pid] = []
            page[pid].push(f as unknown as typeof reportFilters[0])
          } else {
            report.push(f as unknown as typeof reportFilters[0])
          }
        }
        setReportFilters(report)
        for (const [pid, filters] of Object.entries(page)) {
          setPageFilters(pid, filters)
        }
      }

      // Restore interaction filters (only if capture_data)
      if (shouldRestoreData && data.interaction_selections) {
        setInteractionFilters(data.interaction_selections as typeof interactionFilters)
      }

      // Restore slicer selections (only if capture_data)
      if (shouldRestoreData && data.slicer_selections && Object.keys(data.slicer_selections).length > 0) {
        await loadSlicers()
      }

      // Restore visual visibility (only if capture_display)
      if (shouldRestoreDisplay && data.visual_visibility) {
        const { setAllVisualVisibility } = useReportStore.getState()
        setAllVisualVisibility(data.visual_visibility)
      }

      // Restore visual layout (only if capture_visual_layout)
      const shouldRestoreLayout = data.capture_visual_layout === true
      if (shouldRestoreLayout && data.visual_layout) {
        const { visuals, setVisuals } = useReportStore.getState()
        const layoutMap = data.visual_layout as Record<string, { x: number; y: number; width: number; height: number }>
        const updated = visuals.map(v => {
          const layout = layoutMap[v.id]
          if (layout) {
            return { ...v, x: layout.x, y: layout.y, width: layout.width, height: layout.height }
          }
          return v
        })
        setVisuals(updated)
      }

      // Restore visual design (only if capture_visual_design)
      const shouldRestoreDesign = data.capture_visual_design === true
      if (shouldRestoreDesign && data.visual_design) {
        const { visuals, setVisuals } = useReportStore.getState()
        const designMap = data.visual_design as Record<string, { format?: Record<string, unknown>; advanced_plotly_patch?: Record<string, unknown> }>
        const updated = visuals.map(v => {
          const design = designMap[v.id]
          if (design) {
            return {
              ...v,
              ...(design.format !== undefined ? { format: design.format } : {}),
              ...(design.advanced_plotly_patch !== undefined ? { advanced_plotly_patch: design.advanced_plotly_patch } : {}),
            }
          }
          return v
        })
        setVisuals(updated)
      }
    }
    setApplyingId(null)
  }, [apply, setReportFilters, setPageFilters, setInteractionFilters, loadSlicers])

  const startEditing = (bookmark: Bookmark) => {
    setEditingId(bookmark.id)
    setEditName(bookmark.name)
  }

  const cancelEditing = () => {
    setEditingId(null)
    setEditName('')
  }

  // Update bookmark with current state (recapture)
  const handleRecapture = useCallback(async (bookmarkId: string) => {
    const state = captureCurrentState()
    const result = await update(bookmarkId, state as Partial<Bookmark>)
    if (result.success) {
      setBookmarksDirty(true)
    }
  }, [captureCurrentState, update, setBookmarksDirty])

  return (
    <div className={cn('flex flex-col h-full', className)} data-testid="bookmarks-panel">
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2 border-b">
        <span className="text-sm font-medium">Bookmarks</span>
        <Button
          variant="ghost"
          size="sm"
          className="h-7 w-7 p-0"
          onClick={() => { setCreating(true); setNewName('') }}
          data-testid="bookmark-create-btn"
          title="Create bookmark"
        >
          <Plus className="h-4 w-4" />
        </Button>
      </div>

      {/* Create form */}
      {creating && (
        <div className="px-3 py-2 border-b space-y-2" data-testid="bookmark-create-form">
          <Input
            autoFocus
            placeholder="Bookmark name"
            value={newName}
            onChange={e => setNewName(e.target.value)}
            onKeyDown={e => {
              if (e.key === 'Enter') handleCreate()
              if (e.key === 'Escape') setCreating(false)
            }}
            data-testid="bookmark-name-input"
            className="h-8 text-sm"
          />

          {/* Capture options */}
          <div className="space-y-1" data-testid="bookmark-capture-options">
            <span className="text-[10px] font-medium text-muted-foreground uppercase tracking-wide">Capture</span>
            <label className="flex items-center gap-2 cursor-pointer" data-testid="bookmark-capture-page">
              <input
                type="checkbox"
                checked={capturePage}
                onChange={e => setCapturePage(e.target.checked)}
                className="h-3.5 w-3.5 rounded border-muted-foreground"
              />
              <FileText className="h-3 w-3 text-muted-foreground" />
              <span className="text-xs">Current Page</span>
            </label>
            <label className="flex items-center gap-2 cursor-pointer" data-testid="bookmark-capture-data">
              <input
                type="checkbox"
                checked={captureData}
                onChange={e => setCaptureData(e.target.checked)}
                className="h-3.5 w-3.5 rounded border-muted-foreground"
              />
              <Database className="h-3 w-3 text-muted-foreground" />
              <span className="text-xs">Data (filters, slicers, cross-highlight)</span>
            </label>
            <label className="flex items-center gap-2 cursor-pointer" data-testid="bookmark-capture-display">
              <input
                type="checkbox"
                checked={captureDisplay}
                onChange={e => setCaptureDisplay(e.target.checked)}
                className="h-3.5 w-3.5 rounded border-muted-foreground"
              />
              <EyeIcon className="h-3 w-3 text-muted-foreground" />
              <span className="text-xs">Display (visual visibility)</span>
            </label>
            <label className="flex items-center gap-2 cursor-pointer" data-testid="bookmark-capture-visual-layout">
              <input
                type="checkbox"
                checked={captureVisualLayout}
                onChange={e => setCaptureVisualLayout(e.target.checked)}
                className="h-3.5 w-3.5 rounded border-muted-foreground"
              />
              <LayoutGrid className="h-3 w-3 text-muted-foreground" />
              <span className="text-xs">Visual Layout (positions & sizes)</span>
            </label>
            <label className="flex items-center gap-2 cursor-pointer" data-testid="bookmark-capture-visual-design">
              <input
                type="checkbox"
                checked={captureVisualDesign}
                onChange={e => setCaptureVisualDesign(e.target.checked)}
                className="h-3.5 w-3.5 rounded border-muted-foreground"
              />
              <Paintbrush className="h-3 w-3 text-muted-foreground" />
              <span className="text-xs">Visual Design (titles, formatting, colors)</span>
            </label>
          </div>

          <div className="flex gap-1 justify-end">
            <Button
              variant="ghost"
              size="sm"
              className="h-7"
              onClick={() => setCreating(false)}
            >
              Cancel
            </Button>
            <Button
              size="sm"
              className="h-7"
              onClick={handleCreate}
              disabled={!newName.trim()}
              data-testid="bookmark-save-btn"
            >
              <Check className="h-3 w-3 mr-1" />
              Save
            </Button>
          </div>
        </div>
      )}

      {/* Error */}
      {error && (
        <div className="px-3 py-2 text-xs text-destructive" data-testid="bookmark-error">
          {error}
        </div>
      )}

      {/* List */}
      <ScrollArea className="flex-1 min-h-0">
        <div className="p-2 space-y-1">
          {loading && bookmarks.length === 0 && (
            <div className="text-xs text-muted-foreground px-2 py-4 text-center">
              Loading...
            </div>
          )}

          {!loading && bookmarks.length === 0 && (
            <div className="text-xs text-muted-foreground px-2 py-4 text-center" data-testid="bookmark-empty">
              No bookmarks yet. Click + to create one.
            </div>
          )}

          {bookmarks.map(bookmark => (
            <div
              key={bookmark.id}
              className="group flex flex-col gap-0.5 px-2 py-1.5 rounded-md hover:bg-accent/50"
              data-testid={`bookmark-item-${bookmark.id}`}
            >
              <div className="flex items-center gap-2">
                <BookmarkIcon className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />

                {editingId === bookmark.id ? (
                  /* Inline edit mode */
                  <div className="flex-1 flex items-center gap-1">
                    <Input
                      autoFocus
                      value={editName}
                      onChange={e => setEditName(e.target.value)}
                      onKeyDown={e => {
                        if (e.key === 'Enter') handleUpdate(bookmark.id)
                        if (e.key === 'Escape') cancelEditing()
                      }}
                      className="h-6 text-xs flex-1"
                      data-testid="bookmark-edit-input"
                    />
                    <Button variant="ghost" size="sm" className="h-6 w-6 p-0" onClick={() => handleUpdate(bookmark.id)} data-testid="bookmark-edit-confirm">
                      <Check className="h-3 w-3" />
                    </Button>
                    <Button variant="ghost" size="sm" className="h-6 w-6 p-0" onClick={cancelEditing}>
                      <X className="h-3 w-3" />
                    </Button>
                  </div>
                ) : (
                  /* Display mode */
                  <>
                    <span className="flex-1 text-xs truncate">{bookmark.name}</span>
                    <div className="hidden group-hover:flex items-center gap-0.5">
                      <Button
                        variant="ghost"
                        size="sm"
                        className="h-6 w-6 p-0"
                        onClick={() => handleApply(bookmark.id)}
                        disabled={applyingId === bookmark.id}
                        data-testid={`bookmark-apply-${bookmark.id}`}
                        title="Apply bookmark"
                      >
                        <Play className="h-3 w-3" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        className="h-6 w-6 p-0"
                        onClick={() => handleRecapture(bookmark.id)}
                        data-testid={`bookmark-recapture-${bookmark.id}`}
                        title="Update bookmark with current state"
                      >
                        <RefreshCw className="h-3 w-3" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        className="h-6 w-6 p-0"
                        onClick={() => startEditing(bookmark)}
                        data-testid={`bookmark-edit-${bookmark.id}`}
                        title="Rename bookmark"
                      >
                        <Pencil className="h-3 w-3" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        className="h-6 w-6 p-0 text-destructive hover:text-destructive"
                        onClick={() => handleDelete(bookmark.id, bookmark.name)}
                        data-testid={`bookmark-delete-${bookmark.id}`}
                        title="Delete bookmark"
                      >
                        <Trash2 className="h-3 w-3" />
                      </Button>
                    </div>
                  </>
                )}
              </div>

              {/* Capture option badges */}
              {editingId !== bookmark.id && (
                <div className="flex items-center gap-1 ml-6">
                  {bookmark.capture_page !== false && (
                    <span className="text-[9px] px-1 py-0.5 rounded bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300" data-testid={`bookmark-badge-page-${bookmark.id}`}>
                      Page
                    </span>
                  )}
                  {bookmark.capture_data !== false && (
                    <span className="text-[9px] px-1 py-0.5 rounded bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-300" data-testid={`bookmark-badge-data-${bookmark.id}`}>
                      Data
                    </span>
                  )}
                  {bookmark.capture_display !== false && (
                    <span className="text-[9px] px-1 py-0.5 rounded bg-purple-100 dark:bg-purple-900/30 text-purple-700 dark:text-purple-300" data-testid={`bookmark-badge-display-${bookmark.id}`}>
                      Display
                    </span>
                  )}
                  {bookmark.capture_visual_layout === true && (
                    <span className="text-[9px] px-1 py-0.5 rounded bg-orange-100 dark:bg-orange-900/30 text-orange-700 dark:text-orange-300" data-testid={`bookmark-badge-layout-${bookmark.id}`}>
                      Layout
                    </span>
                  )}
                  {bookmark.capture_visual_design === true && (
                    <span className="text-[9px] px-1 py-0.5 rounded bg-teal-100 dark:bg-teal-900/30 text-teal-700 dark:text-teal-300" data-testid={`bookmark-badge-design-${bookmark.id}`}>
                      Design
                    </span>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      </ScrollArea>
    </div>
  )
}

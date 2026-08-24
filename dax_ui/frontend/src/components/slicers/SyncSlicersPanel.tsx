import { useState, useEffect, useCallback, useMemo, useRef } from 'react'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import {
  X,
  RefreshCw,
  Loader2,
  Eye,
  Link2,
  Filter as FilterIcon,
  SlidersHorizontal,
  ChevronDown,
  ChevronRight,
} from 'lucide-react'
import { useAppStore, useReportStore } from '@/stores'
import {
  getSlicerSync,
  updateSlicerSync,
  getSlicerDefs,
  type SlicerSyncPayload,
  type SlicerSyncEntry,
  type SlicerSyncPageConfig,
  type SlicerDef,
} from '@/lib/api'

interface SyncSlicersPanelProps {
  open: boolean
  onClose: () => void
  className?: string
  /** Pre-select a specific slicer def id */
  selectedDefId?: string | null
}

/**
 * Power BI–style "Sync slicers" panel.
 *
 * Shows a grid: columns = pages, rows = slicer defs.
 * Each cell has two toggles:
 *   - Sync (filter icon): whether the slicer's selection applies to that page
 *   - Visible (eye icon): whether the slicer is visible on that page
 *
 * Also supports an optional sync_group name for grouping shared state.
 */
export function SyncSlicersPanel({ open, onClose, className, selectedDefId }: SyncSlicersPanelProps) {
  const projectPath = useAppStore(s => s.projectPath)
  const pages = useReportStore(s => s.pages)

  const [syncData, setSyncData] = useState<SlicerSyncPayload | null>(null)
  const [slicerDefs, setSlicerDefs] = useState<SlicerDef[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [savingDef, setSavingDef] = useState<string | null>(null)
  const [activeDefId, setActiveDefId] = useState<string | null>(null)
  const [syncGroupInputs, setSyncGroupInputs] = useState<Record<string, string>>({})
  const [expandedDefs, setExpandedDefs] = useState<Set<string>>(new Set())

  // Load sync data
  const loadSync = useCallback(async () => {
    if (!projectPath) return
    setLoading(true)
    setError(null)

    const [syncResult, defsResult] = await Promise.all([
      getSlicerSync(projectPath),
      getSlicerDefs(projectPath),
    ])

    if (syncResult.error) {
      setError(syncResult.error)
    } else if (syncResult.data) {
      setSyncData(syncResult.data)
      // Initialize sync group inputs from loaded data
      const inputs: Record<string, string> = {}
      for (const [defId, entry] of Object.entries(syncResult.data.sync)) {
        inputs[defId] = entry.sync_group || ''
      }
      setSyncGroupInputs(inputs)
    }

    if (defsResult.data) {
      setSlicerDefs(defsResult.data.defs || [])
    }

    setLoading(false)
  }, [projectPath])

  useEffect(() => {
    if (open) {
      loadSync()
    }
  }, [open, loadSync])

  // Auto-select the given def
  useEffect(() => {
    if (selectedDefId) {
      setActiveDefId(selectedDefId)
      setExpandedDefs(prev => {
        const next = new Set(prev)
        next.add(selectedDefId)
        return next
      })
    }
  }, [selectedDefId])

  // Toggle a single sync/visible flag for a def × page
  const handleToggle = useCallback(async (
    defId: string,
    pageId: string,
    field: 'sync' | 'visible',
    checked: boolean
  ) => {
    if (!syncData || !projectPath) return

    const entry = syncData.sync[defId]
    if (!entry) return

    const currentPageConfig = entry.sync_pages[pageId] || { sync: true, visible: true }
    const updatedPageConfig: SlicerSyncPageConfig = {
      ...currentPageConfig,
      [field]: checked,
    }

    // Optimistic update
    const newSync = { ...syncData }
    const newEntry: SlicerSyncEntry = {
      ...entry,
      sync_pages: { ...entry.sync_pages, [pageId]: updatedPageConfig },
    }
    newSync.sync = { ...newSync.sync, [defId]: newEntry }
    setSyncData(newSync)

    setSavingDef(defId)

    const result = await updateSlicerSync(defId, {
      sync_pages: newEntry.sync_pages,
      sync_group: entry.sync_group || undefined,
    }, projectPath)

    if (result.error) {
      setError(result.error)
      // Revert
      setSyncData(syncData)
    }

    setSavingDef(null)
  }, [syncData, projectPath])

  // Toggle all pages for a def (sync or visible)
  const handleToggleAll = useCallback(async (
    defId: string,
    field: 'sync' | 'visible',
    checked: boolean
  ) => {
    if (!syncData || !projectPath) return

    const entry = syncData.sync[defId]
    if (!entry) return

    const updatedPages: Record<string, SlicerSyncPageConfig> = {}
    for (const [pageId, config] of Object.entries(entry.sync_pages)) {
      updatedPages[pageId] = { ...config, [field]: checked }
    }

    // Optimistic update
    const newSync = { ...syncData }
    const newEntry: SlicerSyncEntry = {
      ...entry,
      sync_pages: updatedPages,
    }
    newSync.sync = { ...newSync.sync, [defId]: newEntry }
    setSyncData(newSync)

    setSavingDef(defId)

    const result = await updateSlicerSync(defId, {
      sync_pages: updatedPages,
      sync_group: entry.sync_group || undefined,
    }, projectPath)

    if (result.error) {
      setError(result.error)
      setSyncData(syncData)
    }

    setSavingDef(null)
  }, [syncData, projectPath])

  // Save sync group
  const handleSyncGroupSave = useCallback(async (defId: string) => {
    if (!syncData || !projectPath) return

    const entry = syncData.sync[defId]
    if (!entry) return

    const newGroup = (syncGroupInputs[defId] || '').trim() || undefined

    setSavingDef(defId)

    const result = await updateSlicerSync(defId, {
      sync_pages: entry.sync_pages,
      sync_group: newGroup,
    }, projectPath)

    if (result.error) {
      setError(result.error)
    } else {
      // Update local state
      const newSync = { ...syncData }
      newSync.sync = {
        ...newSync.sync,
        [defId]: { ...entry, sync_group: newGroup || undefined },
      }
      setSyncData(newSync)
    }

    setSavingDef(null)
  }, [syncData, projectPath, syncGroupInputs])

  // Toggle expanded state for a def
  const toggleExpanded = useCallback((defId: string) => {
    setExpandedDefs(prev => {
      const next = new Set(prev)
      if (next.has(defId)) {
        next.delete(defId)
      } else {
        next.add(defId)
      }
      return next
    })
    setActiveDefId(defId)
  }, [])

  // Get pages from sync data or report store
  const displayPages = useMemo((): Array<{ id: string; title: string }> => {
    if (syncData?.pages?.length) return syncData.pages
    return pages.map((p: { id: string; title: string }) => ({ id: p.id, title: p.title }))
  }, [syncData, pages])

  // Compute column label for slicer def
  const getDefLabel = useCallback((def: SlicerDef): string => {
    const col = def.column
    if (col) {
      return `${col.table}[${col.column}]`
    }
    return def.name
  }, [])

  // Resizable width state
  const [panelWidth, setPanelWidth] = useState(380)
  const isResizing = useRef(false)
  const resizeStartX = useRef(0)
  const resizeStartWidth = useRef(380)

  const handleResizeStart = useCallback((e: React.PointerEvent) => {
    e.preventDefault()
    isResizing.current = true
    resizeStartX.current = e.clientX
    resizeStartWidth.current = panelWidth
    const onMove = (ev: PointerEvent) => {
      if (!isResizing.current) return
      // Panel is on the right side, dragging left increases width
      const delta = resizeStartX.current - ev.clientX
      const newWidth = Math.max(280, Math.min(800, resizeStartWidth.current + delta))
      setPanelWidth(newWidth)
    }
    const onUp = () => {
      isResizing.current = false
      document.removeEventListener('pointermove', onMove)
      document.removeEventListener('pointerup', onUp)
    }
    document.addEventListener('pointermove', onMove)
    document.addEventListener('pointerup', onUp)
  }, [panelWidth])

  if (!open) return null

  return (
    <div
      className={cn(
        'flex flex-col border-l bg-background relative',
        className
      )}
      style={{ width: panelWidth, minWidth: 280 }}
      data-testid="sync-slicers-panel"
    >
      {/* Resize handle on left edge — wider hit area for easy grabbing */}
      <div
        className="absolute -left-1 top-0 bottom-0 w-3 cursor-col-resize z-20 group/resize"
        style={{ touchAction: 'none' }}
        onPointerDown={handleResizeStart}
      >
        {/* Visible indicator line — centered in the hit area */}
        <div className="absolute left-1 top-0 bottom-0 w-1 bg-transparent group-hover/resize:bg-primary/40 group-active/resize:bg-primary/60 transition-colors" />
      </div>
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b">
        <div className="flex items-center gap-2">
          <SlidersHorizontal className="h-4 w-4 text-muted-foreground" />
          <h3 className="text-sm font-semibold">Sync slicers</h3>
        </div>
        <div className="flex items-center gap-1">
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant="ghost"
                size="icon"
                className="h-7 w-7"
                onClick={loadSync}
                disabled={loading}
                data-testid="sync-slicers-refresh"
              >
                <RefreshCw className={cn('h-3.5 w-3.5', loading && 'animate-spin')} />
              </Button>
            </TooltipTrigger>
            <TooltipContent>Refresh</TooltipContent>
          </Tooltip>
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7"
            onClick={onClose}
            data-testid="sync-slicers-close"
          >
            <X className="h-3.5 w-3.5" />
          </Button>
        </div>
      </div>

      {/* Error */}
      {error && (
        <div className="px-4 py-2 bg-destructive/10 text-destructive text-xs border-b">
          {error}
          <Button
            variant="link"
            className="text-xs h-auto p-0 ml-2"
            onClick={() => setError(null)}
          >
            Dismiss
          </Button>
        </div>
      )}

      {/* Loading */}
      {loading && (
        <div className="flex items-center justify-center py-8">
          <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
        </div>
      )}

      {/* Content */}
      {!loading && syncData && (
        <ScrollArea className="flex-1">
          <div className="p-3 space-y-2">
            {/* Legend */}
            <div className="flex items-center gap-4 text-[10px] text-muted-foreground pb-1 border-b mb-2">
              <span className="flex items-center gap-1">
                <FilterIcon className="h-3 w-3" /> = Sync (filter applies)
              </span>
              <span className="flex items-center gap-1">
                <Eye className="h-3 w-3" /> = Visible on page
              </span>
            </div>

            {slicerDefs.length === 0 && (
              <p className="text-xs text-muted-foreground text-center py-4">
                No slicers defined. Create slicers first.
              </p>
            )}

            {slicerDefs.map(def => {
              const entry = syncData.sync[def.id]
              if (!entry) return null

              const isExpanded = expandedDefs.has(def.id)
              const isActive = activeDefId === def.id
              const isSaving = savingDef === def.id

              // Compute "all synced" / "all visible" state
              const allSynced = displayPages.every(p => entry.sync_pages[p.id]?.sync !== false)
              const allVisible = displayPages.every(p => entry.sync_pages[p.id]?.visible !== false)
              const someSynced = displayPages.some(p => entry.sync_pages[p.id]?.sync !== false)
              const someVisible = displayPages.some(p => entry.sync_pages[p.id]?.visible !== false)

              return (
                <div
                  key={def.id}
                  className={cn(
                    'rounded-md border transition-colors',
                    isActive ? 'border-primary bg-accent/30' : 'border-border bg-card',
                  )}
                  data-testid={`sync-slicer-item-${def.id}`}
                >
                  {/* Slicer header row */}
                  <div
                    className="flex items-center gap-2 px-3 py-2 cursor-pointer hover:bg-accent/50"
                    onClick={() => toggleExpanded(def.id)}
                  >
                    {isExpanded ? (
                      <ChevronDown className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                    ) : (
                      <ChevronRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                    )}
                    <div className="flex-1 min-w-0">
                      <p className="text-xs font-medium truncate">{def.name}</p>
                      <p className="text-[10px] text-muted-foreground truncate">
                        {getDefLabel(def)}
                      </p>
                    </div>
                    {isSaving && <Loader2 className="h-3 w-3 animate-spin text-muted-foreground shrink-0" />}
                    {/* Quick all-toggle icons */}
                    <div className="flex items-center gap-2 shrink-0">
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <div className="flex items-center gap-1">
                            <Checkbox
                              checked={allSynced ? true : someSynced ? 'indeterminate' : false}
                              onCheckedChange={(c) => {
                                // Prevent click from toggling expansion
                                handleToggleAll(def.id, 'sync', c === true)
                              }}
                              onClick={(e) => e.stopPropagation()}
                              className="h-3.5 w-3.5"
                              data-testid={`sync-all-${def.id}`}
                            />
                            <FilterIcon className="h-3 w-3 text-muted-foreground" />
                          </div>
                        </TooltipTrigger>
                        <TooltipContent>Toggle sync on all pages</TooltipContent>
                      </Tooltip>
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <div className="flex items-center gap-1">
                            <Checkbox
                              checked={allVisible ? true : someVisible ? 'indeterminate' : false}
                              onCheckedChange={(c) => {
                                handleToggleAll(def.id, 'visible', c === true)
                              }}
                              onClick={(e) => e.stopPropagation()}
                              className="h-3.5 w-3.5"
                              data-testid={`visible-all-${def.id}`}
                            />
                            <Eye className="h-3 w-3 text-muted-foreground" />
                          </div>
                        </TooltipTrigger>
                        <TooltipContent>Toggle visibility on all pages</TooltipContent>
                      </Tooltip>
                    </div>
                  </div>

                  {/* Expanded: per-page grid + sync group */}
                  {isExpanded && (
                    <div className="border-t">
                      {/* Sync group input */}
                      <div className="px-3 py-2 border-b bg-muted/30">
                        <div className="flex items-center gap-2">
                          <Link2 className="h-3 w-3 text-muted-foreground shrink-0" />
                          <span className="text-[10px] text-muted-foreground whitespace-nowrap">Sync group:</span>
                          <Input
                            value={syncGroupInputs[def.id] || ''}
                            onChange={(e) => setSyncGroupInputs(prev => ({
                              ...prev,
                              [def.id]: e.target.value,
                            }))}
                            onBlur={() => handleSyncGroupSave(def.id)}
                            onKeyDown={(e) => {
                              if (e.key === 'Enter') handleSyncGroupSave(def.id)
                            }}
                            placeholder="(none)"
                            className="h-6 text-xs flex-1"
                            data-testid={`sync-group-input-${def.id}`}
                          />
                        </div>
                        <p className="text-[9px] text-muted-foreground mt-1">
                          Slicers with the same sync group share their selection.
                        </p>
                      </div>

                      {/* Per-page grid */}
                      <div className="divide-y">
                        {/* Header row */}
                        <div className="grid grid-cols-[1fr_auto_auto] gap-2 px-3 py-1.5 bg-muted/20">
                          <span className="text-[10px] font-medium text-muted-foreground">Page</span>
                          <Tooltip>
                            <TooltipTrigger>
                              <FilterIcon className="h-3 w-3 text-muted-foreground" />
                            </TooltipTrigger>
                            <TooltipContent>Sync: slicer selection applies to this page</TooltipContent>
                          </Tooltip>
                          <Tooltip>
                            <TooltipTrigger>
                              <Eye className="h-3 w-3 text-muted-foreground" />
                            </TooltipTrigger>
                            <TooltipContent>Visible: slicer is shown on this page</TooltipContent>
                          </Tooltip>
                        </div>

                        {displayPages.map(page => {
                          const pageConfig = entry.sync_pages[page.id] || { sync: true, visible: true }
                          return (
                            <div
                              key={page.id}
                              className="grid grid-cols-[1fr_auto_auto] gap-2 px-3 py-1.5 items-center hover:bg-accent/30"
                              data-testid={`sync-page-row-${def.id}-${page.id}`}
                            >
                              <span className="text-xs truncate" title={page.title}>
                                {page.title}
                              </span>
                              <Checkbox
                                checked={pageConfig.sync}
                                onCheckedChange={(c) => handleToggle(def.id, page.id, 'sync', c === true)}
                                className="h-3.5 w-3.5"
                                data-testid={`sync-check-${def.id}-${page.id}`}
                              />
                              <Checkbox
                                checked={pageConfig.visible}
                                onCheckedChange={(c) => handleToggle(def.id, page.id, 'visible', c === true)}
                                className="h-3.5 w-3.5"
                                data-testid={`visible-check-${def.id}-${page.id}`}
                              />
                            </div>
                          )
                        })}
                      </div>
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        </ScrollArea>
      )}
    </div>
  )
}

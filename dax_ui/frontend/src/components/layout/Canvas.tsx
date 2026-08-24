import { useState, useEffect, useCallback, useRef, useMemo } from 'react'
import { cn } from '@/lib/utils'
import { useReportStore, useFilterStore, useAppStore, useThemeStore, useSlicerDockStore } from '@/stores'
import type { DockPosition } from '@/stores'
import { useVisualRender, useSlicers, useCreateVisual } from '@/hooks'
import type { VisualType } from '@/hooks/useCreateVisual'
import { VisualCard } from '@/components/visuals/VisualCard'
import { SlicerVisual } from '@/components/slicers'
import { SmartGuideOverlay } from '@/components/layout/SmartGuideOverlay'
import { Plus, Settings, Group, Ungroup, Grid3x3, Magnet, LayoutGrid, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  ContextMenu,
  ContextMenuTrigger,
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuSeparator,
  ContextMenuSub,
  ContextMenuSubTrigger,
  ContextMenuSubContent,
} from '@/components/ui/context-menu'
import { isVisualTypeAvailable } from '@/lib/edition'

interface CanvasProps {
  className?: string
}

// Default visual dimensions if not specified
const DEFAULT_WIDTH = 400
const DEFAULT_HEIGHT = 300

const CANVAS_ADD_VISUAL_ITEMS: Array<{ type: VisualType; label: string }> = [
  { type: 'bar', label: 'Bar Chart' },
  { type: 'column', label: 'Column Chart' },
  { type: 'line', label: 'Line Chart' },
  { type: 'area', label: 'Area Chart' },
  { type: 'pie', label: 'Pie Chart' },
  { type: 'table', label: 'Table' },
  { type: 'matrix', label: 'Matrix' },
  { type: 'card', label: 'Card' },
  { type: 'slicer', label: 'Slicer' },
  { type: 'textbox', label: 'Text Box' },
  { type: 'button', label: 'Button' },
  { type: 'shape', label: 'Shape' },
  { type: 'image', label: 'Image' },
]

function toPlaceholderTestIdToken(value: string): string {
  const token = value
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/(^-|-$)/g, '')
  return token || 'unnamed'
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

export function Canvas({ className }: CanvasProps) {
  const canvasWidth = useAppStore(s => s.canvasWidth)
  const canvasHeight = useAppStore(s => s.canvasHeight)
  const canvasZoom = useAppStore(s => s.canvasZoom)
  const setCanvasZoom = useAppStore(s => s.setCanvasZoom)
  const setCanvasSize = useAppStore(s => s.setCanvasSize)
  const snapToGrid = useAppStore(s => s.snapToGrid)
  const setSnapToGrid = useAppStore(s => s.setSnapToGrid)
  const gridSize = useAppStore(s => s.gridSize)
  const setGridSize = useAppStore(s => s.setGridSize)
  const smartGuidesEnabled = useAppStore(s => s.smartGuidesEnabled)
  const setSmartGuidesEnabled = useAppStore(s => s.setSmartGuidesEnabled)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [editWidth, setEditWidth] = useState(String(canvasWidth))
  const [editHeight, setEditHeight] = useState(String(canvasHeight))
  const visuals = useReportStore(s => s.visuals)
  const renderStates = useReportStore(s => s.renderStates)
  const selectedVisualId = useReportStore(s => s.selectedVisualId)
  const pages = useReportStore(s => s.pages)
  const selectVisual = useReportStore(s => s.selectVisual)
  const toggleSelectVisual = useReportStore(s => s.toggleSelectVisual)
  const currentPageId = useReportStore(s => s.currentPageId)
  const removeVisual = useReportStore(s => s.removeVisual)
  const selectedVisualIds = useReportStore(s => s.selectedVisualIds)
  const visualVisibility = useReportStore(s => s.visualVisibility)
  const visualGroups = useReportStore(s => s.visualGroups)
  const getGroupMembers = useReportStore(s => s.getGroupMembers)
  const createGroup = useReportStore(s => s.createGroup)
  const ungroupVisuals = useReportStore(s => s.ungroupVisuals)
  const getGroupForVisual = useReportStore(s => s.getGroupForVisual)
  const copyVisualToClipboard = useReportStore(s => s.copyVisualToClipboard)
  const cutVisualToClipboard = useReportStore(s => s.cutVisualToClipboard)
  const pasteVisualFromClipboard = useReportStore(s => s.pasteVisualFromClipboard)
  const visualClipboard = useReportStore(s => s.visualClipboard)
  const editInteractionsSourceId = useReportStore(s => s.editInteractionsSourceId)
  const setEditInteractionsSourceId = useReportStore(s => s.setEditInteractionsSourceId)
  const { renderAllCoalesced, cancelAll } = useVisualRender()
  const { slicerDefs, slicerInstances, loadAll, removeInstance: removeSlicerInstance, saveInstance } = useSlicers()
  const interactionFilters = useFilterStore(s => s.interactionFilters)
  const filtersVersion = useFilterStore(s => s.filtersVersion)
  const { quickCreateVisual } = useCreateVisual()
  const dockAssignments = useSlicerDockStore(s => s.dockAssignments)
  const assignToDock = useSlicerDockStore(s => s.assignToDock)

  // Track whether initial render has fired (skip interaction re-render before first paint)
  const initialRenderDone = useRef(false)

  // Filter visuals to only those belonging to the current page.
  // The store may hold unsaved visuals from other pages (to preserve them
  // across page switches), but only current-page visuals should be shown.
  const pageVisuals = useMemo(() => {
    if (!currentPageId) return visuals
    return visuals.filter(v => (v.page_id || '').toLowerCase() === currentPageId.toLowerCase())
  }, [visuals, currentPageId])

  // Stable key derived from visual IDs only — prevents re-render-all on property-only changes
  const visualIdsKey = useMemo(() => pageVisuals.map(v => v.id).sort().join(','), [pageVisuals])

  // Slicer drag state
  const [draggingSlicer, setDraggingSlicer] = useState<string | null>(null)
  const [slicerDragOffset, setSlicerDragOffset] = useState({ x: 0, y: 0 })
  const [slicerDragPos, setSlicerDragPos] = useState<{ x: number; y: number } | null>(null)
  const canvasRef = useRef<HTMLDivElement>(null)
  const scrollContainerRef = useRef<HTMLDivElement>(null)
  const lastCanvasPointerRef = useRef<{ x: number; y: number } | null>(null)

  // NOTE: Ctrl+wheel zoom interception is handled globally in App.tsx
  // to prevent browser zoom everywhere (not just on canvas).

  const hasVisualClipboard = !!visualClipboard

  const getCanvasPointFromClient = useCallback((clientX: number, clientY: number) => {
    const rect = canvasRef.current?.getBoundingClientRect()
    if (!rect) return null
    const scale = Math.max(0.01, canvasZoom / 100)
    return {
      x: Math.max(0, (clientX - rect.left) / scale),
      y: Math.max(0, (clientY - rect.top) / scale),
    }
  }, [canvasZoom])

  const handlePasteVisual = useCallback((pos?: { x: number; y: number }) => {
    if (!currentPageId) return
    const pasted = pasteVisualFromClipboard(currentPageId, pos)
    if (pasted) {
      useAppStore.getState().setDirty(true)
    }
  }, [currentPageId, pasteVisualFromClipboard])

  // Load slicers on mount
  useEffect(() => {
    loadAll()
  }, [loadAll])

  // Update canvas size when the current page has custom dimensions
  useEffect(() => {
    if (!currentPageId) return
    const page = pages.find(p => p.id === currentPageId)
    if (!page) return
    const pw = page.width ?? 1280
    const ph = page.height ?? 720
    if (pw !== canvasWidth || ph !== canvasHeight) {
      setCanvasSize(pw, ph)
      setEditWidth(String(pw))
      setEditHeight(String(ph))
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentPageId])

  // Render all visuals when the component mounts or the set of visuals changes (added/removed)
  // We depend on visualIdsKey (not visuals) to avoid re-rendering all visuals on property-only
  // changes like format, encodings, or interactions updates.
  useEffect(() => {
    if (visuals.length > 0) {
      // Cancel any in-flight / debounced renders from the previous page
      // so they don't compete with the new page's renders.
      cancelAll()
      renderAllCoalesced()
      // Mark initial render done on next microtask (after the coalesced
      // call is guaranteed to be scheduled).
      queueMicrotask(() => { initialRenderDone.current = true })
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visualIdsKey, renderAllCoalesced, cancelAll])

  // Re-render all visuals when interaction filters change (crossfiltering / highlight).
  // Performance: we do NOT pass force:true here so the fingerprint cache can
  // skip visuals whose effective filters haven't actually changed (e.g., when
  // clicking the same data point twice to toggle).  The fingerprint includes
  // all interaction filters, so genuine changes are always detected.
  // The renderAllCoalesced hook applies an additional INTERACTION_DEBOUNCE_MS
  // debounce (150 ms) for interaction-only calls, coalescing rapid clicks
  // into a single render batch.
  useEffect(() => {
    if (!initialRenderDone.current) {
      if (interactionFilters.length > 0) {
        initialRenderDone.current = true
        renderAllCoalesced({ force: true })
      }
      return
    }
    renderAllCoalesced({ interactionOnly: true })
  }, [interactionFilters, renderAllCoalesced])

  // Re-render all visuals when report/page/visual filters finish loading.
  // filtersVersion is bumped once after the deferred filter load in useRuntimeState.
  useEffect(() => {
    if (!initialRenderDone.current) return
    if (filtersVersion === 0) return  // initial state; nothing loaded yet
    renderAllCoalesced({ force: true })
  }, [filtersVersion, renderAllCoalesced])
  
  // Get slicer instances for current page, filtered by visibility and NOT docked
  const pageSlicerInstances = slicerInstances.filter(
    inst => inst.page_id?.toLowerCase() === (currentPageId || '').toLowerCase()
      && (visualVisibility[inst.id] ?? true)
      && !dockAssignments[inst.id]
  )

  // Compute the max visual bottom for auto-positioning slicers below visuals
  const maxVisualBottom = useMemo(() => {
    let maxBottom = 0
    for (const v of pageVisuals) {
      const y = v.layout?.y ?? v.y ?? 20
      const h = v.layout?.h ?? v.height ?? DEFAULT_HEIGHT
      maxBottom = Math.max(maxBottom, y + h)
    }
    return maxBottom
  }, [pageVisuals])

  // All visuals filtered by visibility (no viewport clipping — let the canvas scroll)
  // Also filter out hidden visuals (PBI transfer: hidden flag), group-type visuals (transparent containers),
  // except unsupported Power BI visuals that use group as a visible preserve-only carrier,
  // and slicer visuals (converted to native slicers during transfer)
  const visibleVisuals = useMemo(() => {
    return pageVisuals.filter(v =>
      (visualVisibility[v.id] ?? true) &&
      !v.hidden &&
      (v.visual_type !== 'group' || !!v.unsupported_visual) &&
      v.visual_type !== 'slicer'
    )
  }, [pageVisuals, visualVisibility])

  // Compute canvas inner size: at least canvasWidth/canvasHeight, but expand to fit all visuals/slicers
  const canvasInnerSize = useMemo(() => {
    let maxRight = canvasWidth
    let maxBottom = canvasHeight
    for (const v of pageVisuals) {
      const x = v.layout?.x ?? v.x ?? 20
      const y = v.layout?.y ?? v.y ?? 20
      const w = v.layout?.w ?? v.width ?? DEFAULT_WIDTH
      const h = v.layout?.h ?? v.height ?? DEFAULT_HEIGHT
      maxRight = Math.max(maxRight, x + w + 20)
      maxBottom = Math.max(maxBottom, y + h + 20)
    }
    for (const inst of pageSlicerInstances) {
      maxRight = Math.max(maxRight, (inst.x ?? 0) + 200 + 20)
      maxBottom = Math.max(maxBottom, (inst.y ?? 0) + 100 + 20)
    }
    return { width: maxRight, height: maxBottom }
  }, [pageVisuals, pageSlicerInstances, canvasWidth, canvasHeight])

  // Combined list of all selectable items (visuals + slicer instances) for arrow-key navigation
  const allSelectableIds = useMemo(() => {
    const ids: string[] = visibleVisuals.map(v => v.id)
    pageSlicerInstances.forEach(si => ids.push(si.id))
    return ids
  }, [visibleVisuals, pageSlicerInstances])

  // Keyboard shortcut handler for Delete key + arrow key navigation
  const handleKeyDown = useCallback((e: KeyboardEvent) => {
    const target = e.target as HTMLElement
    const isEditing = target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable
    const isCtrlLike = e.ctrlKey || e.metaKey

    if (isCtrlLike && !isEditing) {
      const key = e.key.toLowerCase()
      const selectedVisual = selectedVisualId ? visuals.find(v => v.id === selectedVisualId) : null

      if (key === 'c' && selectedVisual) {
        e.preventDefault()
        copyVisualToClipboard(selectedVisual.id)
        return
      }

      if (key === 'x' && selectedVisual) {
        e.preventDefault()
        cutVisualToClipboard(selectedVisual.id)
        useAppStore.getState().setDirty(true)
        return
      }

      if (key === 'v' && !selectedVisualId && currentPageId) {
        e.preventDefault()
        handlePasteVisual(lastCanvasPointerRef.current ?? undefined)
        return
      }
    }

    // Arrow key navigation between visual cards
    if ((e.key === 'ArrowRight' || e.key === 'ArrowLeft' || e.key === 'ArrowDown' || e.key === 'ArrowUp') && !isEditing) {
      if (allSelectableIds.length === 0) return
      e.preventDefault()
      const currentIdx = selectedVisualId ? allSelectableIds.indexOf(selectedVisualId) : -1
      let nextIdx: number
      if (e.key === 'ArrowRight' || e.key === 'ArrowDown') {
        nextIdx = currentIdx < allSelectableIds.length - 1 ? currentIdx + 1 : 0
      } else {
        nextIdx = currentIdx > 0 ? currentIdx - 1 : allSelectableIds.length - 1
      }
      selectVisual(allSelectableIds[nextIdx])
      // Focus the visual card element
      const el = document.querySelector(`[data-testid="visual-${allSelectableIds[nextIdx]}"]`) as HTMLElement
      el?.focus()
      return
    }

    // Delete/Backspace key
    if (e.key === 'Delete' || e.key === 'Backspace') {
      if (isEditing) return
      
      if (selectedVisualId) {
        e.preventDefault()
        const slicerInstance = slicerInstances.find(s => s.id === selectedVisualId)
        if (slicerInstance) {
          if (confirm('Delete this slicer?')) {
            removeSlicerInstance(slicerInstance.id)
          }
        } else {
          const visual = visuals.find(v => v.id === selectedVisualId)
          if (visual && confirm(`Delete visual "${visual.title || visual.id}"?`)) {
            removeVisual(selectedVisualId)
          }
        }
        selectVisual(null)
      }
    }
  }, [
    selectedVisualId,
    visuals,
    slicerInstances,
    removeVisual,
    removeSlicerInstance,
    selectVisual,
    allSelectableIds,
    copyVisualToClipboard,
    cutVisualToClipboard,
    currentPageId,
    handlePasteVisual,
  ])
  
  useEffect(() => {
    document.addEventListener('keydown', handleKeyDown)
    return () => document.removeEventListener('keydown', handleKeyDown)
  }, [handleKeyDown])

  // Slicer drag handlers — uses a movement threshold so clicks on interactive
  // elements (checkboxes, buttons, inputs, dropdowns) pass through unblocked.
  const slicerDragStartRef = useRef<{ id: string; startX: number; startY: number; offsetX: number; offsetY: number } | null>(null)
  const DRAG_THRESHOLD = 5

  const handleSlicerMouseDown = useCallback((e: React.MouseEvent, instanceId: string) => {
    // Allow clicks on interactive elements (checkbox, input, button, select, label) to pass through
    const target = e.target as HTMLElement
    const interactive = target.closest('input, button, select, label, [role="checkbox"], [role="option"], [role="listbox"], [data-slicer-interactive]')
    if (interactive) {
      // Still select the slicer visually but don't block the event
      selectVisual(instanceId)
      e.stopPropagation() // prevent canvas click from deselecting
      return
    }
    e.stopPropagation()
    const instance = pageSlicerInstances.find(i => i.id === instanceId)
    if (!instance) return
    selectVisual(instanceId)
    // Record pending drag start — actual drag begins only after threshold
    slicerDragStartRef.current = {
      id: instanceId,
      startX: e.clientX,
      startY: e.clientY,
      offsetX: e.clientX - (instance.x ?? 0),
      offsetY: e.clientY - (instance.y ?? 0),
    }
  }, [pageSlicerInstances, selectVisual])

  useEffect(() => {
    // Combined listener for pending-drag-threshold and active-drag
    const handleMouseMove = (e: MouseEvent) => {
      // Phase 1: check if pending drag should become active
      if (slicerDragStartRef.current && !draggingSlicer) {
        const dx = e.clientX - slicerDragStartRef.current.startX
        const dy = e.clientY - slicerDragStartRef.current.startY
        if (Math.abs(dx) > DRAG_THRESHOLD || Math.abs(dy) > DRAG_THRESHOLD) {
          const pending = slicerDragStartRef.current
          setDraggingSlicer(pending.id)
          setSlicerDragOffset({ x: pending.offsetX, y: pending.offsetY })
          const inst = pageSlicerInstances.find(i => i.id === pending.id)
          setSlicerDragPos({ x: inst?.x ?? 0, y: inst?.y ?? 0 })
          slicerDragStartRef.current = null
        }
        return
      }
      // Phase 2: active drag
      if (!draggingSlicer) return
      let sx = Math.max(0, e.clientX - slicerDragOffset.x)
      let sy = Math.max(0, e.clientY - slicerDragOffset.y)
      if (snapToGrid && !e.altKey && gridSize > 0) {
        sx = Math.round(sx / gridSize) * gridSize
        sy = Math.round(sy / gridSize) * gridSize
      }
      setSlicerDragPos({ x: sx, y: sy })
    }
    const handleMouseUp = () => {
      // Cancel pending drag that never exceeded threshold (was a click)
      slicerDragStartRef.current = null
      if (slicerDragPos && draggingSlicer) {
        const instance = pageSlicerInstances.find(i => i.id === draggingSlicer)
        if (instance) {
          // Save updated position (in-memory; user must Save to persist)
          saveInstance({ ...instance, x: slicerDragPos.x, y: slicerDragPos.y })
        }
      }
      setDraggingSlicer(null)
      setSlicerDragPos(null)
    }
    document.addEventListener('mousemove', handleMouseMove)
    document.addEventListener('mouseup', handleMouseUp)
    return () => {
      document.removeEventListener('mousemove', handleMouseMove)
      document.removeEventListener('mouseup', handleMouseUp)
    }
  }, [draggingSlicer, slicerDragOffset, slicerDragPos, pageSlicerInstances, saveInstance, snapToGrid, gridSize])

  // ── Slicer resize state ─────────────────────────────────────────────
  const [resizingSlicer, setResizingSlicer] = useState<string | null>(null)
  const slicerResizeRef = useRef<{ id: string; startX: number; startY: number; startW: number; startH: number; edge: 'right' | 'bottom' | 'corner'; lastX: number; lastY: number } | null>(null)

  const handleSlicerResizeDown = useCallback((e: React.MouseEvent, instanceId: string, edge: 'right' | 'bottom' | 'corner') => {
    e.stopPropagation()
    e.preventDefault()
    const instance = pageSlicerInstances.find(i => i.id === instanceId)
    if (!instance) return
    slicerResizeRef.current = {
      id: instanceId,
      startX: e.clientX,
      startY: e.clientY,
      startW: instance.width ?? 240,
      startH: instance.height ?? 260,
      edge,
      lastX: e.clientX,
      lastY: e.clientY,
    }
    setResizingSlicer(instanceId)
  }, [pageSlicerInstances])

  useEffect(() => {
    if (!resizingSlicer) return
    const handleResizeMove = (e: MouseEvent) => {
      const ref = slicerResizeRef.current
      if (!ref) return
      ref.lastX = e.clientX
      ref.lastY = e.clientY
      const dx = e.clientX - ref.startX
      const dy = e.clientY - ref.startY
      // Live update via imperative DOM (avoids re-render cascade during drag)
      const el = document.querySelector(`[data-testid="slicer-instance-${ref.id}"]`) as HTMLElement
      if (el) {
        const inner = el.firstElementChild as HTMLElement
        if (inner) {
          if (ref.edge === 'right' || ref.edge === 'corner') inner.style.width = `${Math.max(120, ref.startW + dx)}px`
          if (ref.edge === 'bottom' || ref.edge === 'corner') inner.style.height = `${Math.max(80, ref.startH + dy)}px`
        }
      }
    }
    const handleResizeUp = () => {
      const ref = slicerResizeRef.current
      if (ref) {
        const dx = ref.lastX - ref.startX
        const dy = ref.lastY - ref.startY
        const instance = pageSlicerInstances.find(i => i.id === ref.id)
        if (instance) {
          let newW = ref.startW
          let newH = ref.startH
          if (ref.edge === 'right' || ref.edge === 'corner') newW = Math.max(120, ref.startW + dx)
          if (ref.edge === 'bottom' || ref.edge === 'corner') newH = Math.max(80, ref.startH + dy)
          saveInstance({ ...instance, width: Math.round(newW), height: Math.round(newH) })
        }
      }
      slicerResizeRef.current = null
      setResizingSlicer(null)
    }
    document.addEventListener('mousemove', handleResizeMove)
    document.addEventListener('mouseup', handleResizeUp)
    return () => {
      document.removeEventListener('mousemove', handleResizeMove)
      document.removeEventListener('mouseup', handleResizeUp)
    }
  }, [resizingSlicer, pageSlicerInstances, saveInstance])

  const canvasBackground = useThemeStore((s) => s.reportingTheme.canvas.background)
  const canvasBackgroundImage = useThemeStore((s) => s.reportingTheme.canvas.backgroundImage)
  const showHeaderIcons = useThemeStore((s) => s.reportingTheme.canvas?.showHeaderIcons)
  const showVisualHeaders = useThemeStore((s) => s.reportingTheme.canvas?.showVisualHeaders)
  const currentPage = useMemo(() => {
    if (!currentPageId) return null
    return pages.find((page) => page.id === currentPageId) || null
  }, [pages, currentPageId])
  const currentPagePlaceholderContainers = useMemo(() => {
    const raw = currentPage?.placeholder_containers
      ?? (currentPage as Record<string, unknown> | null)?.placeholderContainers
    if (!Array.isArray(raw) || raw.length === 0) return []
    const seen = new Set<string>()
    const normalized: string[] = []
    for (const item of raw) {
      if (typeof item !== 'string') continue
      const trimmed = item.trim()
      if (!trimmed || seen.has(trimmed)) continue
      seen.add(trimmed)
      normalized.push(trimmed)
    }
    return normalized
  }, [currentPage])
  const currentPageVisibleVisuals = useMemo(() => {
    return visibleVisuals.filter((visual) => (visual.page_id || '').toLowerCase() === (currentPageId || '').toLowerCase())
  }, [visibleVisuals, currentPageId])
  const detailArtifactFlags = useMemo(() => {
    let hasDecisionArtifacts = false
    let hasSignalArtifacts = false
    let hasEvidenceArtifacts = false

    for (const visual of currentPageVisibleVisuals) {
      const payload = renderStates[visual.id]?.data
      if (!isPlainObject(payload)) continue

      const decisionOverlays = Array.isArray(payload.decision_overlays) ? payload.decision_overlays : []
      const packSummary = isPlainObject(payload.pack_summary) ? payload.pack_summary : null
      const overlayMeta = isPlainObject(payload.overlay_meta) ? payload.overlay_meta : null

      if (decisionOverlays.length > 0) {
        hasDecisionArtifacts = true
      }
      if (packSummary && Object.keys(packSummary).length > 0) {
        hasDecisionArtifacts = true
      }
      if (overlayMeta && Object.keys(overlayMeta).length > 0) {
        hasDecisionArtifacts = true
      }

      for (const overlay of decisionOverlays) {
        if (!isPlainObject(overlay)) continue
        const signals = Array.isArray(overlay.signals) ? overlay.signals : []
        if (signals.length > 0) {
          hasSignalArtifacts = true
        }

        const episode = isPlainObject(overlay.episode) ? overlay.episode : null
        const simulation = isPlainObject(overlay.simulation) ? overlay.simulation : null
        const reasons = Array.isArray(overlay.computability_reasons)
          ? overlay.computability_reasons
          : (simulation && Array.isArray(simulation.computability_reasons) ? simulation.computability_reasons : [])
        const hasComputabilityState =
          typeof overlay.computability_state === 'string'
          || typeof overlay.computabilityState === 'string'
          || (simulation && typeof simulation.computability_state === 'string')
          || (simulation && typeof simulation.computabilityState === 'string')
        const hasScenarioStatusDetail =
          typeof overlay.scenario_status_detail === 'string'
          || typeof overlay.scenarioStatusDetail === 'string'
          || (simulation && typeof simulation.scenario_status_detail === 'string')
          || (simulation && typeof simulation.scenarioStatusDetail === 'string')
        const hasEpisodeState =
          typeof overlay.episode_state === 'string'
          || typeof overlay.episodeState === 'string'
          || (episode && typeof episode.episode_state === 'string')
          || (episode && typeof episode.episodeState === 'string')
          || (episode && typeof episode.state === 'string')

        if (isPlainObject(episode) || isPlainObject(simulation) || reasons.length > 0 || hasComputabilityState || hasScenarioStatusDetail || hasEpisodeState) {
          hasEvidenceArtifacts = true
        }
      }

      if (packSummary) {
        const hasPackEvidence = [
          'active_episode_count',
          'non_computable_kpi_count',
          'high_severity_signal_count',
          'pack_confidence_tier',
        ].some((key) => key in packSummary)
        if (hasPackEvidence) {
          hasEvidenceArtifacts = true
        }
      }

      if (hasDecisionArtifacts && hasSignalArtifacts && hasEvidenceArtifacts) {
        break
      }
    }

    return {
      hasDecisionArtifacts,
      hasSignalArtifacts,
      hasEvidenceArtifacts,
    }
  }, [currentPageVisibleVisuals, renderStates])
  const visiblePagePlaceholderContainers = useMemo(() => {
    if (currentPagePlaceholderContainers.length === 0) return []
    const pageType = String(
      currentPage?.page_type
      ?? (currentPage as Record<string, unknown> | null)?.pageType
      ?? '',
    ).toLowerCase()
    if (pageType !== 'detail') {
      return currentPagePlaceholderContainers
    }

    return currentPagePlaceholderContainers.filter((name) => {
      const token = toPlaceholderTestIdToken(name)
      if (token === 'signals-panel') {
        return detailArtifactFlags.hasSignalArtifacts
      }
      if (token === 'evidence-episode-panel') {
        return detailArtifactFlags.hasEvidenceArtifacts
      }
      if (token === 'decision-context-block') {
        return detailArtifactFlags.hasDecisionArtifacts
      }
      return true
    })
  }, [currentPagePlaceholderContainers, currentPage, detailArtifactFlags])
  return (
    <div
      ref={scrollContainerRef}
      className={cn(
        'flex-1 bg-canvas overflow-auto relative canvas-dot-grid',
        className
      )}
      data-testid="canvas"
      onClick={() => {
        selectVisual(null)
        // Clear all crossfilter/highlight interactions when clicking canvas background
        useFilterStore.getState().clearInteractionFilters()
        // Exit Edit Interactions mode
        useReportStore.getState().setEditInteractionsSourceId(null)
      }}
    >
      {/* Edit Interactions mode banner */}
      {editInteractionsSourceId && (() => {
        const sourceVisual = visuals.find(v => v.id === editInteractionsSourceId)
        const sourceName = sourceVisual?.title || sourceVisual?.id || 'Unknown'
        return (
          <div
            className="sticky top-0 left-0 right-0 z-30 flex items-center justify-between gap-2 px-4 py-2 bg-blue-600 text-white text-sm font-medium shadow-md"
            data-testid="edit-interactions-banner"
            onClick={(e) => e.stopPropagation()}
          >
            <span>Edit Interactions — Click badges on other visuals to set filter / highlight / none for <strong>{sourceName}</strong></span>
            <Button
              variant="ghost"
              size="sm"
              className="h-6 px-2 text-white hover:bg-blue-700 hover:text-white"
              data-testid="exit-edit-interactions-btn"
              onClick={(e) => {
                e.stopPropagation()
                setEditInteractionsSourceId(null)
              }}
            >
              <X className="h-4 w-4 mr-1" /> Done
            </Button>
          </div>
        )
      })()}

      {/* Canvas settings button — sticky in viewport corner */}
      <div className="sticky top-2 right-2 z-20 flex justify-end pr-2 pt-2 pointer-events-none">
        <div className="pointer-events-auto">
          <Button
            variant="outline"
            size="sm"
            className="h-8 gap-1.5 text-xs text-muted-foreground hover:text-foreground bg-background/90 backdrop-blur-sm shadow-md border-primary/20"
            data-testid="canvas-settings-btn"
            onClick={(e) => {
              e.stopPropagation()
              setSettingsOpen(!settingsOpen)
              setEditWidth(String(canvasWidth))
              setEditHeight(String(canvasHeight))
            }}
          >
            <Settings className="h-3.5 w-3.5" />
            Canvas Settings
          </Button>
          {settingsOpen && (
            <div 
              className="absolute right-0 top-8 w-56 bg-popover border rounded-lg shadow-lg p-3 space-y-3 z-50"
              data-testid="canvas-settings-panel"
              onClick={(e) => e.stopPropagation()}
            >
                <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider">Canvas Size</p>
                <div className="grid grid-cols-2 gap-2">
                  <div>
                    <Label className="text-xs">Width</Label>
                    <Input
                      type="number"
                      min={320}
                      max={3840}
                      value={editWidth}
                      onChange={(e) => setEditWidth(e.target.value)}
                      className="h-7 text-xs"
                      data-testid="canvas-width-input"
                    />
                  </div>
                  <div>
                    <Label className="text-xs">Height</Label>
                    <Input
                      type="number"
                      min={240}
                      max={2160}
                      value={editHeight}
                      onChange={(e) => setEditHeight(e.target.value)}
                      className="h-7 text-xs"
                      data-testid="canvas-height-input"
                    />
                  </div>
                </div>
                <div className="flex gap-1">
                  <Button 
                    size="sm" 
                    className="h-7 text-xs flex-1"
                    data-testid="canvas-size-apply"
                    onClick={() => {
                      const w = parseInt(editWidth, 10)
                      const h = parseInt(editHeight, 10)
                      if (!isNaN(w) && !isNaN(h)) {
                        setCanvasSize(w, h)
                      }
                      setSettingsOpen(false)
                    }}
                  >
                    Apply
                  </Button>
                  <Button 
                    variant="ghost" 
                    size="sm" 
                    className="h-7 text-xs"
                    onClick={() => setSettingsOpen(false)}
                  >
                    Cancel
                  </Button>
                </div>
                <div className="flex gap-1 flex-wrap">
                  {[
                    { label: '720p', w: 1280, h: 720 },
                    { label: '1080p', w: 1920, h: 1080 },
                    { label: '4:3', w: 1024, h: 768 },
                    { label: '16:10', w: 1280, h: 800 },
                  ].map((preset) => (
                    <Button
                      key={preset.label}
                      variant="outline"
                      size="sm"
                      className="h-6 text-[10px] px-2"
                      onClick={() => {
                        setEditWidth(String(preset.w))
                        setEditHeight(String(preset.h))
                      }}
                    >
                      {preset.label}
                    </Button>
                  ))}
                </div>
                {/* ─── Snap-to-Grid ─── */}
                <div className="border-t pt-2 space-y-2">
                  <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider">Grid &amp; Snap</p>
                  <div className="flex items-center justify-between">
                    <Label className="text-xs flex items-center gap-1.5">
                      <Grid3x3 className="h-3.5 w-3.5" />
                      Snap to Grid
                    </Label>
                    <button
                      type="button"
                      role="switch"
                      aria-checked={snapToGrid}
                      data-testid="canvas-snap-toggle"
                      className={cn(
                        'relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors',
                        snapToGrid ? 'bg-primary' : 'bg-input'
                      )}
                      onClick={(e) => {
                        e.stopPropagation()
                        setSnapToGrid(!snapToGrid)
                      }}
                    >
                      <span
                        className={cn(
                          'pointer-events-none block h-4 w-4 rounded-full bg-background shadow-lg ring-0 transition-transform',
                          snapToGrid ? 'translate-x-4' : 'translate-x-0'
                        )}
                      />
                    </button>
                  </div>
                  {snapToGrid && (
                    <div className="flex items-center gap-2">
                      <Label className="text-xs whitespace-nowrap">Grid Size</Label>
                      <Input
                        type="number"
                        min={5}
                        max={50}
                        step={5}
                        value={gridSize}
                        onChange={(e) => {
                          const v = parseInt(e.target.value, 10)
                          if (!isNaN(v)) setGridSize(v)
                        }}
                        className="h-7 text-xs w-16"
                        data-testid="canvas-grid-size-input"
                      />
                      <span className="text-[10px] text-muted-foreground">px</span>
                    </div>
                  )}
                  {snapToGrid && (
                    <p className="text-[10px] text-muted-foreground">Hold <kbd className="px-1 py-0.5 rounded border text-[9px]">Alt</kbd> while dragging for free movement</p>
                  )}
                  {/* Smart Guides toggle */}
                  <div className="flex items-center justify-between pt-1">
                    <Label className="text-xs flex items-center gap-1.5">
                      <Magnet className="h-3.5 w-3.5" />
                      Smart Guides
                    </Label>
                    <button
                      type="button"
                      role="switch"
                      aria-checked={smartGuidesEnabled}
                      data-testid="canvas-smart-guides-toggle"
                      className={cn(
                        'relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors',
                        smartGuidesEnabled ? 'bg-primary' : 'bg-input'
                      )}
                      onClick={(e) => {
                        e.stopPropagation()
                        setSmartGuidesEnabled(!smartGuidesEnabled)
                      }}
                    >
                      <span
                        className={cn(
                          'pointer-events-none block h-4 w-4 rounded-full bg-background shadow-lg ring-0 transition-transform',
                          smartGuidesEnabled ? 'translate-x-4' : 'translate-x-0'
                        )}
                      />
                    </button>
                  </div>
                </div>
                {/* ─── Canvas Background ─── */}
                <div className="border-t pt-2 space-y-2">
                  <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider">Background</p>
                  <div className="space-y-1">
                    <Label className="text-xs">Color</Label>
                    <div className="flex items-center gap-2">
                      <input
                        type="color"
                        value={canvasBackground || '#f5f5f5'}
                        onChange={(e) => useThemeStore.getState().updateReportingTheme({ canvas: { background: e.target.value } })}
                        className="h-7 w-10 cursor-pointer rounded border border-input bg-transparent"
                        data-testid="canvas-bg-color"
                      />
                      <Input
                        value={canvasBackground}
                        onChange={(e) => useThemeStore.getState().updateReportingTheme({ canvas: { background: e.target.value } })}
                        placeholder="#000000"
                        className="h-7 text-xs flex-1"
                        data-testid="canvas-bg-color-text"
                      />
                      {canvasBackground && (
                        <Button
                          variant="ghost"
                          size="sm"
                          className="h-7 px-2 text-xs"
                          onClick={() => useThemeStore.getState().updateReportingTheme({ canvas: { background: '' } })}
                        >
                          Clear
                        </Button>
                      )}
                    </div>
                  </div>
                  <div className="space-y-1">
                    <Label className="text-xs">Image</Label>
                    <div className="flex items-center gap-1">
                      {canvasBackgroundImage && (
                        <div
                          className="h-7 w-10 rounded border border-input bg-cover bg-center flex-shrink-0"
                          style={{ backgroundImage: `url(${canvasBackgroundImage})` }}
                        />
                      )}
                      <label className="cursor-pointer">
                        <input
                          type="file"
                          accept="image/*"
                          className="hidden"
                          data-testid="canvas-bg-image-upload"
                          onChange={(e) => {
                            const file = e.target.files?.[0]
                            if (!file || !file.type.startsWith('image/')) return
                            const reader = new FileReader()
                            reader.onload = () => {
                              if (typeof reader.result === 'string') {
                                useThemeStore.getState().updateReportingTheme({ canvas: { backgroundImage: reader.result } })
                              }
                            }
                            reader.readAsDataURL(file)
                          }}
                        />
                        <span className="inline-flex items-center justify-center h-7 px-3 text-xs rounded border border-input bg-background hover:bg-accent cursor-pointer">
                          {canvasBackgroundImage ? 'Change' : 'Upload'}
                        </span>
                      </label>
                      {canvasBackgroundImage && (
                        <Button
                          variant="ghost"
                          size="sm"
                          className="h-7 px-2 text-xs"
                          onClick={() => useThemeStore.getState().updateReportingTheme({ canvas: { backgroundImage: '' } })}
                        >
                          Clear
                        </Button>
                      )}
                    </div>
                  </div>
                </div>
                {/* ─── Visual Header Settings ─── */}
                <div className="border-t pt-2 space-y-2">
                  <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider">Visuals</p>
                  <div className="flex items-center justify-between">
                    <Label className="text-xs">Show visual headers</Label>
                    <button
                      type="button"
                      role="switch"
                      aria-checked={showVisualHeaders !== false}
                      data-testid="canvas-show-visual-headers"
                      className={cn(
                        'relative inline-flex h-5 w-9 items-center rounded-full transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                        showVisualHeaders !== false ? 'bg-primary' : 'bg-input'
                      )}
                      onClick={(e) => {
                        e.stopPropagation()
                        useThemeStore.getState().updateReportingTheme({ canvas: { showVisualHeaders: showVisualHeaders === false ? true : false } })
                      }}
                    >
                      <span
                        className={cn(
                          'pointer-events-none block h-4 w-4 rounded-full bg-background shadow-lg ring-0 transition-transform',
                          showVisualHeaders !== false ? 'translate-x-4' : 'translate-x-0'
                        )}
                      />
                    </button>
                  </div>
                  <div className="flex items-center justify-between">
                    <Label className="text-xs">Show header icons</Label>
                    <button
                      type="button"
                      role="switch"
                      aria-checked={showHeaderIcons !== false}
                      data-testid="canvas-show-header-icons"
                      className={cn(
                        'relative inline-flex h-5 w-9 items-center rounded-full transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                        showHeaderIcons !== false ? 'bg-primary' : 'bg-input'
                      )}
                      onClick={(e) => {
                        e.stopPropagation()
                        useThemeStore.getState().updateReportingTheme({ canvas: { showHeaderIcons: showHeaderIcons === false ? true : false } })
                      }}
                    >
                      <span
                        className={cn(
                          'pointer-events-none block h-4 w-4 rounded-full bg-background shadow-lg ring-0 transition-transform',
                          showHeaderIcons !== false ? 'translate-x-4' : 'translate-x-0'
                        )}
                      />
                    </button>
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>
      {/* Canvas container — scrollable */}
      <div className="min-h-full p-4">
        {/* Zoom wrapper — explicit size so scroll container accounts for scaled canvas */}
        <div style={{
          width: canvasInnerSize.width * (canvasZoom / 100),
          height: canvasInnerSize.height * (canvasZoom / 100),
        }}>
        <ContextMenu>
          <ContextMenuTrigger asChild>
            <div 
              ref={canvasRef}
              className="relative bg-background border shadow-sm"
              style={{ 
                width: canvasInnerSize.width, 
                height: canvasInnerSize.height,
                minWidth: canvasWidth,
                minHeight: canvasHeight,
                transform: `scale(${canvasZoom / 100})`,
                transformOrigin: 'top left',
                ...(canvasBackground ? { backgroundColor: canvasBackground } : {}),
                ...(canvasBackgroundImage ? { backgroundImage: `url(${canvasBackgroundImage})`, backgroundSize: 'cover', backgroundPosition: 'center' } : {}),
              }}
              onContextMenu={(e) => {
                const target = e.target as HTMLElement
                if (target.closest('[data-testid^="visual-"]') || target.closest('[data-testid^="slicer-instance-"]')) {
                  return
                }
                const pos = getCanvasPointFromClient(e.clientX, e.clientY)
                if (pos) lastCanvasPointerRef.current = pos
              }}
              onClick={(e) => {
                const pos = getCanvasPointFromClient(e.clientX, e.clientY)
                if (pos) lastCanvasPointerRef.current = pos
                selectVisual(null)
                // Clear all crossfilter/highlight interactions when clicking canvas background
                useFilterStore.getState().clearInteractionFilters()
              }}
              onDragOver={(e) => {
                if (e.dataTransfer.types.includes('application/x-visual-type')) {
                  e.preventDefault()
                  e.dataTransfer.dropEffect = 'copy'
                }
              }}
              onDrop={(e) => {
                const visualType = e.dataTransfer.getData('application/x-visual-type')
                if (!visualType) return
                e.preventDefault()
                const pos = getCanvasPointFromClient(e.clientX, e.clientY)
                if (pos) {
                  quickCreateVisual(visualType as any, { x: pos.x, y: pos.y })
                }
              }}
            >
          {/* Grid overlay — visible when snap-to-grid is enabled */}
          {snapToGrid && gridSize > 0 && (
            <svg
              className="absolute inset-0 pointer-events-none"
              width="100%"
              height="100%"
              data-testid="canvas-grid-overlay"
              aria-hidden="true"
            >
              <defs>
                <pattern
                  id="canvas-snap-grid"
                  width={gridSize}
                  height={gridSize}
                  patternUnits="userSpaceOnUse"
                >
                  <circle cx={gridSize} cy={gridSize} r="0.5" className="fill-muted-foreground/20" />
                </pattern>
              </defs>
              <rect width="100%" height="100%" fill="url(#canvas-snap-grid)" />
            </svg>
          )}

          {/* Smart guide alignment lines — visible during drag/resize */}
          <SmartGuideOverlay />

          {visiblePagePlaceholderContainers.length > 0 && (
            <div
              className="absolute left-2 top-2 z-10 pointer-events-none flex flex-wrap items-center gap-1 max-w-[70%]"
              data-testid="page-placeholder-containers"
              data-page-id={currentPage?.id || ''}
              data-page-type={String(
                currentPage?.page_type
                ?? (currentPage as Record<string, unknown> | null)?.pageType
                ?? '',
              )}
            >
              {visiblePagePlaceholderContainers.map((name) => (
                <span
                  key={name}
                  className="inline-flex h-5 items-center rounded border border-dashed bg-background/70 px-2 text-[10px] text-muted-foreground"
                  data-testid={`page-placeholder-container-${toPlaceholderTestIdToken(name)}`}
                  data-placeholder-name={name}
                >
                  {name}
                </span>
              ))}
            </div>
          )}
          {visibleVisuals.length === 0 && pageSlicerInstances.length === 0 ? (
            <div className="absolute inset-0 flex flex-col items-center justify-center text-muted-foreground gap-4" data-testid="canvas-empty-state">
              <div className="rounded-full bg-primary/10 p-4">
                <LayoutGrid className="h-10 w-10 text-primary/60" />
              </div>
              <div className="text-center space-y-1">
                <p className="text-base font-medium text-foreground/70">No visuals on this page</p>
                <p className="text-xs text-muted-foreground">Add a visual from the Insert menu or click below</p>
              </div>
              <Button
                variant="outline"
                size="sm"
                aria-label="Add a visual to this page"
                data-testid="canvas-add-visual-cta"
                onClick={() => quickCreateVisual(isVisualTypeAvailable('matrix') ? 'matrix' : 'table')}
                className="mt-1"
              >
                <Plus className="h-4 w-4 mr-1" />
                Add Visual
              </Button>
            </div>
          ) : (
            <>
              {/* Regular visuals */}
              {visibleVisuals.map((visual) => {
                // Check if this visual belongs to a group
                const groupMembers = getGroupMembers(visual.id)
                const isInGroup = groupMembers.length > 1

                return (
                  <VisualCard
                    key={visual.id}
                    visual={visual}
                    isSelected={selectedVisualId === visual.id || selectedVisualIds.includes(visual.id)}
                    isInGroup={isInGroup}
                    groupMembers={isInGroup ? groupMembers : undefined}
                    onSelect={(e?: React.MouseEvent) => {
                      if (e && (e.ctrlKey || e.metaKey)) {
                        toggleSelectVisual(visual.id)
                      } else {
                        selectVisual(visual.id)
                      }
                    }}
                    style={{
                      left: visual.layout?.x ?? visual.x ?? 20,
                      top: visual.layout?.y ?? visual.y ?? 20,
                      width: visual.layout?.w ?? visual.width ?? DEFAULT_WIDTH,
                      height: visual.layout?.h ?? visual.height ?? DEFAULT_HEIGHT,
                    }}
                  />
                )
              })}
              
              {/* Slicer instances — draggable */}
              {pageSlicerInstances.map((instance) => {
                const def = slicerDefs.find(d => d.id.toLowerCase() === instance.def_id.toLowerCase())
                if (!def) return null
                const isDragging = draggingSlicer === instance.id
                // Auto-position slicers without saved x/y below the visual grid
                const autoX = instance.x ?? (pageSlicerInstances.indexOf(instance) * 220 + 20)
                const autoY = instance.y ?? (maxVisualBottom + 20)
                const pos = isDragging && slicerDragPos 
                  ? slicerDragPos 
                  : { x: autoX, y: autoY }
                const isSelected = selectedVisualId === instance.id || selectedVisualIds.includes(instance.id)
                
                return (
                  <ContextMenu key={instance.id}>
                    <ContextMenuTrigger asChild>
                      <div
                        className={cn(
                          "absolute cursor-grab",
                          isDragging && "cursor-grabbing",
                          isSelected && "ring-2 ring-primary rounded-lg"
                        )}
                        style={{
                          left: pos.x,
                          top: pos.y,
                          zIndex: isDragging || isSelected ? 30 : undefined,
                          transition: isDragging ? 'none' : undefined,
                        }}
                        data-testid={`slicer-instance-${instance.id}`}
                        onMouseDown={(e) => handleSlicerMouseDown(e, instance.id)}
                        onClick={(e) => {
                          e.stopPropagation()
                          selectVisual(instance.id)
                        }}
                      >
                        <SlicerVisual
                          instance={instance}
                          def={def}
                        />
                        {/* Resize handles */}
                        {isSelected && (
                          <>
                            {/* Right edge */}
                            <div
                              className="absolute top-0 right-0 w-1.5 h-full cursor-col-resize hover:bg-primary/30 active:bg-primary/50 z-10"
                              onMouseDown={(e) => handleSlicerResizeDown(e, instance.id, 'right')}
                            />
                            {/* Bottom edge */}
                            <div
                              className="absolute bottom-0 left-0 w-full h-1.5 cursor-row-resize hover:bg-primary/30 active:bg-primary/50 z-10"
                              onMouseDown={(e) => handleSlicerResizeDown(e, instance.id, 'bottom')}
                            />
                            {/* Corner handle */}
                            <div
                              className="absolute bottom-0 right-0 w-3 h-3 cursor-nwse-resize hover:bg-primary/40 active:bg-primary/60 z-20 rounded-tl"
                              onMouseDown={(e) => handleSlicerResizeDown(e, instance.id, 'corner')}
                            />
                          </>
                        )}
                      </div>
                    </ContextMenuTrigger>
                    <ContextMenuContent className="w-48" data-testid={`slicer-context-${instance.id}`}>
                      <ContextMenuSub>
                        <ContextMenuSubTrigger>Dock to Panel</ContextMenuSubTrigger>
                        <ContextMenuSubContent>
                          {(['left', 'right', 'top', 'bottom'] as DockPosition[]).map(pos => (
                            <ContextMenuItem key={pos} onClick={() => assignToDock(instance.id, pos)}>
                              {pos.charAt(0).toUpperCase() + pos.slice(1)}
                            </ContextMenuItem>
                          ))}
                        </ContextMenuSubContent>
                      </ContextMenuSub>
                      <ContextMenuSeparator />
                      <ContextMenuItem
                        className="text-destructive"
                        onClick={() => {
                          if (confirm('Delete this slicer?')) {
                            removeSlicerInstance(instance.id)
                          }
                        }}
                      >
                        Delete Slicer
                      </ContextMenuItem>
                    </ContextMenuContent>
                  </ContextMenu>
                )
              })}
            </>
          )}
            </div>
          </ContextMenuTrigger>
          <ContextMenuContent className="w-52" data-testid="canvasContextMenu">
            <ContextMenuSub>
              <ContextMenuSubTrigger data-testid="canvasContextAddVisual">Add Visual</ContextMenuSubTrigger>
              <ContextMenuSubContent>
                {CANVAS_ADD_VISUAL_ITEMS.filter(({ type }) => isVisualTypeAvailable(type)).map(({ type, label }) => (
                  <ContextMenuItem
                    key={type}
                    onClick={() => {
                      const pos = lastCanvasPointerRef.current
                      quickCreateVisual(type, pos ? { x: pos.x, y: pos.y } : undefined)
                    }}
                    data-testid={`canvasContextAddVisual-${type}`}
                  >
                    {label}
                  </ContextMenuItem>
                ))}
              </ContextMenuSubContent>
            </ContextMenuSub>
            <ContextMenuSeparator />
            <ContextMenuItem
              disabled={!hasVisualClipboard}
              onClick={() => handlePasteVisual(lastCanvasPointerRef.current ?? undefined)}
              data-testid="canvasContextPasteVisual"
            >
              Paste Visual
            </ContextMenuItem>
          </ContextMenuContent>
        </ContextMenu>
        </div>{/* /zoom wrapper */}

        {/* Floating multi-select toolbar */}
        {selectedVisualIds.length >= 2 && (
          <div
            className="absolute bottom-4 left-1/2 -translate-x-1/2 flex items-center gap-2 bg-card border rounded-lg shadow-lg px-3 py-2 z-50"
            data-testid="canvas-multiselect-toolbar"
          >
            <span className="text-xs text-muted-foreground mr-1">
              {selectedVisualIds.length} visuals selected
            </span>
            {/* Show Group button if none of the selected are already in the same group */}
            {(() => {
              const firstGroup = getGroupForVisual(selectedVisualIds[0])
              const allInSameGroup = firstGroup && selectedVisualIds.every(id => {
                const g = getGroupForVisual(id)
                return g?.id === firstGroup.id
              })
              return (
                <>
                  {!allInSameGroup && (
                    <Button
                      variant="outline"
                      size="sm"
                      className="h-7 px-2 text-xs gap-1"
                      onClick={() => createGroup(selectedVisualIds)}
                      data-testid="canvas-group-btn"
                    >
                      <Group className="h-3.5 w-3.5" />
                      Group
                    </Button>
                  )}
                  {allInSameGroup && firstGroup && (
                    <Button
                      variant="outline"
                      size="sm"
                      className="h-7 px-2 text-xs gap-1"
                      onClick={() => ungroupVisuals(firstGroup.id)}
                      data-testid="canvas-ungroup-btn"
                    >
                      <Ungroup className="h-3.5 w-3.5" />
                      Ungroup
                    </Button>
                  )}
                </>
              )
            })()}
            <span className="text-[10px] text-muted-foreground/60">
              Ctrl+Click to select more
            </span>
          </div>
        )}
      </div>
    </div>
  )
}

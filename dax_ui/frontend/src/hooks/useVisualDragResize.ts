/**
 * Hook for managing visual drag-to-move and resize functionality
 */

import { useState, useCallback, useRef, useEffect } from 'react'
import { updateVisual as apiUpdateVisual } from '@/lib/api'
import { useReportStore, useAppStore } from '@/stores'
import { computeSmartGuides, visualToRect, useSmartGuideStore } from '@/hooks/useSmartGuides'

interface Position {
  x: number
  y: number
}

interface Size {
  width: number
  height: number
}

interface DragState {
  isDragging: boolean
  startPos: Position
  startMouse: Position
}

interface ResizeState {
  isResizing: boolean
  handle: 'n' | 's' | 'e' | 'w' | 'ne' | 'nw' | 'se' | 'sw' | null
  startSize: Size
  startPos: Position
  startMouse: Position
}

interface UseVisualDragResizeOptions {
  visualId: string
  initialX: number
  initialY: number
  initialWidth: number
  initialHeight: number
  minWidth?: number
  minHeight?: number
  maxWidth?: number
  maxHeight?: number
  canvasWidth?: number
  canvasHeight?: number
  /** IDs of other visuals in the same group (for group drag). */
  groupMembers?: string[]
  onDragEnd?: (x: number, y: number) => void
  onResizeEnd?: (width: number, height: number, x: number, y: number) => void
}

const MIN_SIZE = 100
const DEFAULT_CANVAS_WIDTH = 1280
const DEFAULT_CANVAS_HEIGHT = 720

/** Round a value to the nearest grid unit. */
function snapValue(val: number, gridSize: number): number {
  return Math.round(val / gridSize) * gridSize
}

export function useVisualDragResize(options: UseVisualDragResizeOptions) {
  const {
    visualId,
    initialX,
    initialY,
    initialWidth,
    initialHeight,
    minWidth = MIN_SIZE,
    minHeight = MIN_SIZE,
    maxWidth,
    maxHeight,
    canvasWidth = DEFAULT_CANVAS_WIDTH,
    canvasHeight = DEFAULT_CANVAS_HEIGHT,
    groupMembers,
  } = options

  const updateVisual = useReportStore(s => s.updateVisual)
  const projectPath = useAppStore(s => s.projectPath)
  const setDirty = useAppStore(s => s.setDirty)
  const snapEnabled = useAppStore(s => s.snapToGrid)
  const gridSize = useAppStore(s => s.gridSize)
  const smartGuidesEnabled = useAppStore(s => s.smartGuidesEnabled)
  const smartGuideThreshold = useAppStore(s => s.smartGuideThreshold)

  // Local state for immediate visual feedback
  const [position, setPosition] = useState<Position>({ x: initialX, y: initialY })
  const [size, setSize] = useState<Size>({ width: initialWidth, height: initialHeight })

  // Drag state
  const dragRef = useRef<DragState>({
    isDragging: false,
    startPos: { x: 0, y: 0 },
    startMouse: { x: 0, y: 0 },
  })

  // Resize state
  const resizeRef = useRef<ResizeState>({
    isResizing: false,
    handle: null,
    startSize: { width: 0, height: 0 },
    startPos: { x: 0, y: 0 },
    startMouse: { x: 0, y: 0 },
  })

  const [isDragging, setIsDragging] = useState(false)
  const [isResizing, setIsResizing] = useState(false)

  // Ref to the element that holds pointer capture during drag/resize.
  // Using a stable HTML element (not a transient SVG child) prevents
  // Plotly's internal drag handling from stealing capture.
  const pointerCaptureRef = useRef<HTMLElement | null>(null)

  // Track Alt key to temporarily disable snap during drag/resize
  const altKeyRef = useRef(false)
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { altKeyRef.current = e.altKey }
    window.addEventListener('keydown', onKey)
    window.addEventListener('keyup', onKey)
    return () => {
      window.removeEventListener('keydown', onKey)
      window.removeEventListener('keyup', onKey)
    }
  }, [])

  // Sync with external changes
  useEffect(() => {
    setPosition({ x: initialX, y: initialY })
  }, [initialX, initialY])

  useEffect(() => {
    setSize({ width: initialWidth, height: initialHeight })
  }, [initialWidth, initialHeight])

  // Clamp position: only prevent negative values, allow placing anywhere on canvas
  // When snap is enabled (and Alt is not held), round to grid.
  const clampPosition = useCallback((x: number, y: number, _w: number, _h: number): Position => {
    let cx = Math.max(0, x)
    let cy = Math.max(0, y)
    if (snapEnabled && !altKeyRef.current && gridSize > 0) {
      cx = snapValue(cx, gridSize)
      cy = snapValue(cy, gridSize)
    }
    return { x: cx, y: cy }
  }, [snapEnabled, gridSize])

  // Clamp size within limits; snap when enabled.
  const clampSize = useCallback((w: number, h: number): Size => {
    let cw = Math.max(minWidth, Math.min(w, maxWidth ?? canvasWidth))
    let ch = Math.max(minHeight, Math.min(h, maxHeight ?? canvasHeight))
    if (snapEnabled && !altKeyRef.current && gridSize > 0) {
      cw = Math.max(minWidth, snapValue(cw, gridSize))
      ch = Math.max(minHeight, snapValue(ch, gridSize))
    }
    return { width: cw, height: ch }
  }, [minWidth, minHeight, maxWidth, maxHeight, canvasWidth, canvasHeight, snapEnabled, gridSize])

  // Persist changes to backend
  const persistLayout = useCallback(async (x: number, y: number, w: number, h: number) => {
    // Update local store
    updateVisual(visualId, { x, y, width: w, height: h })
    setDirty(true)

    // Persist to backend
    try {
      await apiUpdateVisual(visualId, {
        layout: { x, y, w, h },
      }, projectPath ?? undefined)
    } catch (err) {
      console.error('Failed to persist visual layout:', err)
    }
  }, [visualId, updateVisual, setDirty, projectPath])

  // Persist group members' layout changes to backend (called at drag/resize end)
  const persistGroupMembers = useCallback(async () => {
    if (!groupMembers || groupMembers.length <= 1) return
    const visuals = useReportStore.getState().visuals
    for (const memberId of groupMembers) {
      if (memberId === visualId) continue // already handled by persistLayout
      const member = visuals.find(v => v.id === memberId)
      if (!member) continue
      const mx = member.layout?.x ?? member.x ?? 20
      const my = member.layout?.y ?? member.y ?? 20
      const mw = member.layout?.w ?? member.width ?? 400
      const mh = member.layout?.h ?? member.height ?? 300
      try {
        await apiUpdateVisual(memberId, {
          layout: { x: mx, y: my, w: mw, h: mh },
        }, projectPath ?? undefined)
      } catch (err) {
        console.error('Failed to persist group member layout:', err)
      }
    }
  }, [groupMembers, visualId, projectPath])

  /** Update a group member's position & size in the store (includes layout field). */
  const updateMemberLayout = useCallback((memberId: string, x: number, y: number, w: number, h: number) => {
    updateVisual(memberId, {
      x, y, width: w, height: h,
      layout: { x, y, w, h },
    })
  }, [updateVisual])

  // --- Drag handlers ---

  const handleDragStart = useCallback((e: React.PointerEvent) => {
    // Only allow dragging from header area (check data-drag-handle)
    const target = e.target as HTMLElement
    if (!target.closest('[data-drag-handle]')) return

    e.preventDefault()
    e.stopPropagation()

    dragRef.current = {
      isDragging: true,
      startPos: { ...position },
      startMouse: { x: e.clientX, y: e.clientY },
    }
    setIsDragging(true)

    // Snapshot group members' positions at drag start for coordinated movement
    if (groupMembers && groupMembers.length > 1) {
      const visuals = useReportStore.getState().visuals
      const snaps: Record<string, { x: number; y: number; w: number; h: number }> = {}
      for (const memberId of groupMembers) {
        if (memberId === visualId) continue
        const member = visuals.find(v => v.id === memberId)
        if (member) {
          snaps[memberId] = {
            x: member.layout?.x ?? member.x ?? 20,
            y: member.layout?.y ?? member.y ?? 20,
            w: member.layout?.w ?? member.width ?? 400,
            h: member.layout?.h ?? member.height ?? 300,
          }
        }
      }
      groupStartSnapshots.current = snaps
    }

    // Capture pointer on the drag-handle element (not e.target which may be
    // a deeply nested SVG element inside Plotly charts that can lose capture).
    const dragHandle = target.closest('[data-drag-handle]') as HTMLElement | null
    const captureEl = dragHandle ?? (e.currentTarget as HTMLElement)
    captureEl.setPointerCapture(e.pointerId)
    pointerCaptureRef.current = captureEl
  }, [position, groupMembers, visualId])

  // Track group members' original positions/sizes at drag/resize start
  const groupStartSnapshots = useRef<Record<string, { x: number; y: number; w: number; h: number }>>({})

  const handleDragMove = useCallback((e: React.PointerEvent) => {
    if (!dragRef.current.isDragging) return

    const dx = e.clientX - dragRef.current.startMouse.x
    const dy = e.clientY - dragRef.current.startMouse.y

    let newPos = clampPosition(
      dragRef.current.startPos.x + dx,
      dragRef.current.startPos.y + dy,
      size.width,
      size.height
    )

    // Apply smart guides (after grid snap, before final set)
    if (smartGuidesEnabled && !altKeyRef.current) {
      const visuals = useReportStore.getState().visuals
      const otherRects = visuals
        .filter((v) => v.id !== visualId && !(groupMembers ?? []).includes(v.id))
        .map(visualToRect)

      const movingRect = { x: newPos.x, y: newPos.y, w: size.width, h: size.height }
      const { snappedX, snappedY, guides } = computeSmartGuides(
        movingRect,
        otherRects,
        smartGuideThreshold,
      )
      newPos = { x: Math.max(0, snappedX), y: Math.max(0, snappedY) }
      useSmartGuideStore.getState().setActiveGuides(guides)
    }

    setPosition(newPos)

    // Move group members visually in real-time
    if (groupMembers && groupMembers.length > 1) {
      for (const memberId of groupMembers) {
        if (memberId === visualId) continue
        const snap = groupStartSnapshots.current[memberId]
        if (snap) {
          updateMemberLayout(
            memberId,
            Math.max(0, snap.x + dx),
            Math.max(0, snap.y + dy),
            snap.w,
            snap.h
          )
        }
      }
    }
  }, [clampPosition, size, groupMembers, visualId, updateMemberLayout, smartGuidesEnabled, smartGuideThreshold])

  const handleDragEnd = useCallback((e: React.PointerEvent) => {
    if (!dragRef.current.isDragging) return

    if (pointerCaptureRef.current) {
      try { pointerCaptureRef.current.releasePointerCapture(e.pointerId) } catch { /* already released */ }
      pointerCaptureRef.current = null
    }

    dragRef.current.isDragging = false
    setIsDragging(false)

    // Clear smart guide overlay
    useSmartGuideStore.getState().clearGuides()

    // Persist the new position
    persistLayout(position.x, position.y, size.width, size.height)

    // Also persist group members (their store state is already updated from handleDragMove)
    if (groupMembers && groupMembers.length > 1) {
      persistGroupMembers()
    }
  }, [position, size, persistLayout, persistGroupMembers, groupMembers])

  // --- Resize handlers ---

  // Store the group bounding box at resize start for proportional scaling
  const groupBBoxRef = useRef<{ minX: number; minY: number; maxX: number; maxY: number; width: number; height: number } | null>(null)

  const handleResizeStart = useCallback((
    e: React.PointerEvent,
    handle: ResizeState['handle']
  ) => {
    e.preventDefault()
    e.stopPropagation()

    resizeRef.current = {
      isResizing: true,
      handle,
      startSize: { ...size },
      startPos: { ...position },
      startMouse: { x: e.clientX, y: e.clientY },
    }
    setIsResizing(true)

    // Snapshot group members for proportional resize
    if (groupMembers && groupMembers.length > 1) {
      const visuals = useReportStore.getState().visuals
      const snaps: Record<string, { x: number; y: number; w: number; h: number }> = {}
      // Include the current visual itself in the bounding box
      let minX = position.x, minY = position.y
      let maxX = position.x + size.width, maxY = position.y + size.height
      for (const memberId of groupMembers) {
        if (memberId === visualId) continue
        const member = visuals.find(v => v.id === memberId)
        if (member) {
          const mx = member.layout?.x ?? member.x ?? 20
          const my = member.layout?.y ?? member.y ?? 20
          const mw = member.layout?.w ?? member.width ?? 400
          const mh = member.layout?.h ?? member.height ?? 300
          snaps[memberId] = { x: mx, y: my, w: mw, h: mh }
          minX = Math.min(minX, mx)
          minY = Math.min(minY, my)
          maxX = Math.max(maxX, mx + mw)
          maxY = Math.max(maxY, my + mh)
        }
      }
      groupStartSnapshots.current = snaps
      groupBBoxRef.current = { minX, minY, maxX, maxY, width: maxX - minX, height: maxY - minY }
    }

    const captureEl = (e.currentTarget ?? e.target) as HTMLElement
    captureEl.setPointerCapture(e.pointerId)
    pointerCaptureRef.current = captureEl
  }, [size, position, groupMembers, visualId])

  const handleResizeMove = useCallback((e: React.PointerEvent) => {
    if (!resizeRef.current.isResizing || !resizeRef.current.handle) return

    const dx = e.clientX - resizeRef.current.startMouse.x
    const dy = e.clientY - resizeRef.current.startMouse.y
    const handle = resizeRef.current.handle

    let newWidth = resizeRef.current.startSize.width
    let newHeight = resizeRef.current.startSize.height
    let newX = resizeRef.current.startPos.x
    let newY = resizeRef.current.startPos.y

    // Handle horizontal resize
    if (handle.includes('e')) {
      newWidth = resizeRef.current.startSize.width + dx
    } else if (handle.includes('w')) {
      const potentialWidth = resizeRef.current.startSize.width - dx
      if (potentialWidth >= minWidth) {
        newWidth = potentialWidth
        newX = resizeRef.current.startPos.x + dx
      }
    }

    // Handle vertical resize
    if (handle.includes('s')) {
      newHeight = resizeRef.current.startSize.height + dy
    } else if (handle.includes('n')) {
      const potentialHeight = resizeRef.current.startSize.height - dy
      if (potentialHeight >= minHeight) {
        newHeight = potentialHeight
        newY = resizeRef.current.startPos.y + dy
      }
    }

    const clampedSize = clampSize(newWidth, newHeight)
    let clampedPos = clampPosition(newX, newY, clampedSize.width, clampedSize.height)

    // Apply smart guides during resize
    if (smartGuidesEnabled && !altKeyRef.current) {
      const visuals = useReportStore.getState().visuals
      const otherRects = visuals
        .filter((v) => v.id !== visualId && !(groupMembers ?? []).includes(v.id))
        .map(visualToRect)

      const movingRect = { x: clampedPos.x, y: clampedPos.y, w: clampedSize.width, h: clampedSize.height }
      const { snappedX, snappedY, guides } = computeSmartGuides(
        movingRect,
        otherRects,
        smartGuideThreshold,
      )

      // Adjust size and position based on which handles are being dragged
      const deltaX = snappedX - clampedPos.x
      const deltaY = snappedY - clampedPos.y

      if (handle.includes('w')) {
        // Left edge snapped: adjust x and width
        clampedPos = { ...clampedPos, x: Math.max(0, snappedX) }
        clampedSize.width = Math.max(minWidth, clampedSize.width - deltaX)
      } else if (handle.includes('e')) {
        // Right edge snapped: x stays, width adjusts via guide
        // (snappedX already reflects the guide-snapped left; width comes from the rect)
      }
      if (handle.includes('n')) {
        clampedPos = { ...clampedPos, y: Math.max(0, snappedY) }
        clampedSize.height = Math.max(minHeight, clampedSize.height - deltaY)
      }

      useSmartGuideStore.getState().setActiveGuides(guides)
    }

    setSize(clampedSize)
    setPosition(clampedPos)

    // Proportionally resize group members
    if (groupMembers && groupMembers.length > 1 && groupBBoxRef.current) {
      const bbox = groupBBoxRef.current
      const scaleX = bbox.width > 0
        ? (clampedSize.width + (clampedPos.x - resizeRef.current.startPos.x) + (resizeRef.current.startSize.width - clampedSize.width === 0 ? 0 : 0)) / resizeRef.current.startSize.width
        : 1
      const scaleY = bbox.height > 0
        ? clampedSize.height / resizeRef.current.startSize.height
        : 1
      // Use the dragged visual's start position as the anchor point
      const anchorX = resizeRef.current.startPos.x
      const anchorY = resizeRef.current.startPos.y

      for (const memberId of groupMembers) {
        if (memberId === visualId) continue
        const snap = groupStartSnapshots.current[memberId]
        if (snap) {
          const relX = snap.x - anchorX
          const relY = snap.y - anchorY
          const newMemberX = Math.max(0, anchorX + clampedPos.x - resizeRef.current.startPos.x + relX * scaleX)
          const newMemberY = Math.max(0, anchorY + clampedPos.y - resizeRef.current.startPos.y + relY * scaleY)
          const newMemberW = Math.max(minWidth, snap.w * scaleX)
          const newMemberH = Math.max(minHeight, snap.h * scaleY)
          updateMemberLayout(memberId, newMemberX, newMemberY, newMemberW, newMemberH)
        }
      }
    }
  }, [clampSize, clampPosition, minWidth, minHeight, groupMembers, visualId, updateMemberLayout, smartGuidesEnabled, smartGuideThreshold])

  const handleResizeEnd = useCallback((e: React.PointerEvent) => {
    if (!resizeRef.current.isResizing) return

    if (pointerCaptureRef.current) {
      try { pointerCaptureRef.current.releasePointerCapture(e.pointerId) } catch { /* already released */ }
      pointerCaptureRef.current = null
    }

    resizeRef.current.isResizing = false
    resizeRef.current.handle = null
    setIsResizing(false)

    // Clear smart guide overlay
    useSmartGuideStore.getState().clearGuides()

    // Persist the new size and position
    persistLayout(position.x, position.y, size.width, size.height)

    // Persist group members (their store state is already updated from handleResizeMove)
    if (groupMembers && groupMembers.length > 1) {
      persistGroupMembers()
    }
  }, [position, size, persistLayout, groupMembers, persistGroupMembers])

  return {
    position,
    size,
    isDragging,
    isResizing,
    handlers: {
      onPointerDown: handleDragStart,
      onPointerMove: (e: React.PointerEvent) => {
        if (dragRef.current.isDragging) handleDragMove(e)
        if (resizeRef.current.isResizing) handleResizeMove(e)
      },
      onPointerUp: (e: React.PointerEvent) => {
        if (dragRef.current.isDragging) handleDragEnd(e)
        if (resizeRef.current.isResizing) handleResizeEnd(e)
      },
    },
    resizeHandlers: {
      onResizeStart: handleResizeStart,
      onResizeMove: handleResizeMove,
      onResizeEnd: handleResizeEnd,
    },
  }
}

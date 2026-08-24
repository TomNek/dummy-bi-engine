import { useCallback, useEffect, useRef } from 'react'
import { useAppStore, useFilterStore, useReportStore } from '@/stores'
import { useUndoRedoStore, type UndoSnapshot } from '@/stores/undo-redo-store'

const SNAPSHOT_DEBOUNCE_MS = 75

function deepClone<T>(value: T): T {
  if (typeof structuredClone === 'function') {
    return structuredClone(value)
  }
  return JSON.parse(JSON.stringify(value)) as T
}

function hashSnapshot(snapshot: UndoSnapshot): string {
  return JSON.stringify(snapshot)
}

export function useUndoRedo() {
  const projectPath = useAppStore((state) => state.projectPath)
  const projectLoading = useAppStore((state) => state.projectLoading)
  const setDirty = useAppStore((state) => state.setDirty)
  const reportLoading = useReportStore((state) => state.loading)

  const pushSnapshot = useUndoRedoStore((state) => state.pushSnapshot)
  const undo = useUndoRedoStore((state) => state.undo)
  const redo = useUndoRedoStore((state) => state.redo)
  const reset = useUndoRedoStore((state) => state.reset)
  const canUndo = useUndoRedoStore((state) => state.past.length > 0)
  const canRedo = useUndoRedoStore((state) => state.future.length > 0)

  const readyRef = useRef(false)
  const restoringRef = useRef(false)
  const debounceRef = useRef<number | null>(null)
  const lastProjectRef = useRef<string | null>(null)

  const clearPendingSnapshot = useCallback(() => {
    if (debounceRef.current !== null) {
      window.clearTimeout(debounceRef.current)
      debounceRef.current = null
    }
  }, [])

  const buildSnapshot = useCallback((): UndoSnapshot => {
    const reportState = useReportStore.getState()
    const filterState = useFilterStore.getState()

    return {
      report: {
        pages: deepClone(reportState.pages),
        currentPageId: reportState.currentPageId,
        visuals: deepClone(reportState.visuals),
        selectedVisualId: reportState.selectedVisualId,
      },
      filters: {
        reportFilters: deepClone(filterState.reportFilters),
        pageFilters: deepClone(filterState.pageFilters),
        visualFilters: deepClone(filterState.visualFilters),
      },
    }
  }, [])

  const captureSnapshot = useCallback(() => {
    if (!readyRef.current || restoringRef.current) return
    const snapshot = buildSnapshot()
    pushSnapshot(snapshot, hashSnapshot(snapshot))
  }, [buildSnapshot, pushSnapshot])

  const scheduleSnapshot = useCallback(() => {
    if (!readyRef.current || restoringRef.current) return
    if (debounceRef.current !== null) return

    debounceRef.current = window.setTimeout(() => {
      debounceRef.current = null
      captureSnapshot()
    }, SNAPSHOT_DEBOUNCE_MS)
  }, [captureSnapshot])

  const applySnapshot = useCallback((snapshot: UndoSnapshot) => {
    restoringRef.current = true
    useReportStore.getState().replaceState(snapshot.report)
    useFilterStore.getState().replaceState(snapshot.filters)
    restoringRef.current = false
    setDirty(true)
  }, [setDirty])

  const handleUndo = useCallback(() => {
    clearPendingSnapshot()
    const snapshot = undo()
    if (!snapshot) return
    applySnapshot(snapshot)
  }, [undo, applySnapshot, clearPendingSnapshot])

  const handleRedo = useCallback(() => {
    clearPendingSnapshot()
    const snapshot = redo()
    if (!snapshot) return
    applySnapshot(snapshot)
  }, [redo, applySnapshot, clearPendingSnapshot])

  useEffect(() => {
    if (projectPath !== lastProjectRef.current) {
      lastProjectRef.current = projectPath
      readyRef.current = false
      reset()
    }
  }, [projectPath, reset])

  useEffect(() => {
    if (!projectPath || projectLoading || reportLoading) return
    if (readyRef.current) return

    readyRef.current = true
    captureSnapshot()
  }, [projectPath, projectLoading, reportLoading, captureSnapshot])

  useEffect(() => {
    const unsubscribeReport = useReportStore.subscribe(() => {
      scheduleSnapshot()
    })
    const unsubscribeFilters = useFilterStore.subscribe(() => {
      scheduleSnapshot()
    })

    return () => {
      unsubscribeReport()
      unsubscribeFilters()
      if (debounceRef.current !== null) {
        window.clearTimeout(debounceRef.current)
        debounceRef.current = null
      }
    }
  }, [scheduleSnapshot])

  return {
    canUndo,
    canRedo,
    undo: handleUndo,
    redo: handleRedo,
  }
}

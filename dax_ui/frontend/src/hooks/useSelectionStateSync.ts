/**
 * useSelectionStateSync — Phase 23D
 *
 * A hook that watches the filter store for slicer/interaction filter changes
 * and debounce-fetches the selection state engine for all active slicer fields.
 *
 * Usage: Mount once in a parent component that has access to all slicer defs
 * (e.g., SlicerDockPanel or Canvas).
 */
import { useEffect, useRef } from 'react'
import { useFilterStore } from '@/stores/filter-store'
import { useSelectionStateStore } from '@/stores/selection-state-store'
import type { SlicerDef } from '@/lib/api'

/**
 * Sync selection state whenever filters change.
 *
 * @param slicerDefs - All active slicer definitions (used to know which fields to compute)
 * @param pageId - Current page ID (for page-scoped slicers)
 * @param includeCounts - When true, request per-value row counts from the backend (Phase 23F)
 */
export function useSelectionStateSync(
  slicerDefs: SlicerDef[],
  pageId: string | undefined,
  includeCounts: boolean = false
) {
  const interactionFilters = useFilterStore(s => s.interactionFilters)
  const reportFilters = useFilterStore(s => s.reportFilters)
  const pageFilters = useFilterStore(s => s.pageFilters)
  const filtersVersion = useFilterStore(s => s.filtersVersion)
  const fetchSelectionState = useSelectionStateStore(s => s.fetchSelectionState)
  const clear = useSelectionStateStore(s => s.clear)

  // Track if we have any slicer defs — skip fetch if none
  const hasDefs = slicerDefs.length > 0

  // Track previous filter state to know which fields changed (incremental)
  const prevFiltersRef = useRef<string>('')

  useEffect(() => {
    if (!hasDefs) {
      clear()
      return
    }

    // Build a fingerprint of filter state
    const filterFingerprint = JSON.stringify({
      interaction: interactionFilters.map(f => ({
        t: f.table,
        c: f.column,
        o: f.operator || 'in',
        v: f.values,
        s: f.source_visual_id,
      })),
      v: filtersVersion,
    })

    // Skip if nothing changed
    if (filterFingerprint === prevFiltersRef.current) return
    prevFiltersRef.current = filterFingerprint

    // Build runtime filters payload from slicer interaction filters
    const slicerFilters = interactionFilters
      .filter(f => (f as { slicer_id?: string }).slicer_id)
      .map(f => ({
        scope: 'interaction' as const,
        column: { type: 'ColumnRef' as const, table: f.table, column: f.column },
        operator: f.operator || 'in',
        values: f.values,
        source: 'slicer' as const,
        source_visual_id: f.source_visual_id,
      }))

    // Build slicer_defs for the backend
    const defsPayload = slicerDefs.map(d => ({
      id: d.id,
      name: d.name,
      column: d.column,
      type: d.type,
      selection_type: d.selection_type,
      selection: d.selection,
    }))

    fetchSelectionState({
      filters: slicerFilters,
      slicer_defs: { defs: defsPayload },
      page_id: pageId,
      include_counts: includeCounts || undefined,
    })
  }, [
    interactionFilters,
    reportFilters,
    pageFilters,
    filtersVersion,
    hasDefs,
    slicerDefs,
    pageId,
    includeCounts,
    fetchSelectionState,
    clear,
  ])
}

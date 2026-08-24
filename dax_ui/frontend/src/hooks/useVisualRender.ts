import { useCallback, useRef } from 'react'
import { useAppStore, useReportStore, useFilterStore } from '@/stores'
import { renderVisual, renderMatrix, renderBatch, type VisualInfo } from '@/lib/api'
import { useMatrixStore } from '@/hooks/useMatrixState'
import { usePerfStore } from '@/stores/perf-store'
import { STATIC_VISUAL_TYPES } from '@/hooks/useCreateVisual'

/** Default debounce delay for render requests (ms) */
const RENDER_DEBOUNCE_MS = 50

/**
 * Debounce delay for interaction-filter (crossfilter) re-renders (ms).
 * Rapid clicks on chart data points are coalesced within this window
 * so only ONE renderAll fires instead of N, dramatically reducing
 * backend pressure and UI jank during fast crossfilter exploration.
 */
const INTERACTION_DEBOUNCE_MS = 150

/**
 * Max concurrent render requests.  Limits backend pressure so the first
 * batch of visuals appears quickly instead of all 14+ saturating the
 * server and making everything slow.
 * 6 matches browser HTTP/1.1 connection limit per origin.
 */
const MAX_CONCURRENT_RENDERS = 6

/** Run promises with bounded concurrency.  Returns results in input order. */
async function pAll<T>(tasks: (() => Promise<T>)[], concurrency: number): Promise<T[]> {
  const results: T[] = new Array(tasks.length)
  let idx = 0
  async function next(): Promise<void> {
    while (idx < tasks.length) {
      const i = idx++
      results[i] = await tasks[i]()
    }
  }
  await Promise.all(Array.from({ length: Math.min(concurrency, tasks.length) }, () => next()))
  return results
}

/**
 * Normalize interaction config for a visual; mirrors useInteractions.normalizeInteractions.
 */
function normalizeInteractions(v: VisualInfo) {
  const defaults = { affects_others: true, is_affected: true, mode: 'filter' as const, interaction_targets: undefined as Record<string, 'filter' | 'highlight' | 'none'> | undefined }
  const raw = v.interactions
  if (!raw || typeof raw !== 'object') return defaults
  const affects_others = typeof raw.affects_others === 'boolean' ? raw.affects_others : defaults.affects_others
  const is_affected = typeof raw.is_affected === 'boolean' ? raw.is_affected : defaults.is_affected
  const mode = raw.mode === 'highlight' ? 'highlight' : 'filter'
  const interaction_targets = (raw.interaction_targets && typeof raw.interaction_targets === 'object')
    ? raw.interaction_targets as Record<string, 'filter' | 'highlight' | 'none'>
    : undefined
  return { affects_others, is_affected, mode, interaction_targets }
}

/**
 * Build per-visual render request filters following the old UI's
 * _buildRenderRequestForVisual() logic, extended with per-pair
 * interaction_targets overrides.
 *
 * Per-pair logic:
 * - For each source visual, check source.interaction_targets[targetId].
 * - If 'none' → drop those interaction filters.
 * - If 'filter' → merge into regular filters.
 * - If 'highlight' → send as interaction_filters with render_mode 'highlight'.
 * - If no override → fall back to the target visual's own mode.
 */
function buildFiltersForVisual(
  visualId: string,
  visual: VisualInfo,
  manualFilters: Array<{ column: unknown; operator: string; values: unknown[]; scope?: string }>,
  interactionFilters: Array<{ source_visual_id: string; table: string; column: string; operator?: string; values: unknown[] }>,
  allVisuals: VisualInfo[],
) {
  const interactions = normalizeInteractions(visual)

  // Exclude interaction filters originating from this visual (self-filter prevention)
  const otherInteraction = interactionFilters.filter(
    f => String(f.source_visual_id || '').trim() !== String(visualId).trim()
  )

  // If visual is not affected by interactions, send only manual filters
  if (!interactions.is_affected) {
    return { render_mode: 'normal' as const, filters: manualFilters, interaction_filters: undefined }
  }

  if (otherInteraction.length === 0) {
    return { render_mode: 'normal' as const, filters: manualFilters, interaction_filters: undefined }
  }

  // --- Per-pair override logic ---
  // Bucket interaction filters by effective mode for this target.
  const filterBucket: typeof otherInteraction = []
  const highlightBucket: typeof otherInteraction = []

  // Build a quick lookup of source visuals by id
  const visualById = new Map<string, VisualInfo>()
  for (const v of allVisuals) visualById.set(v.id, v)

  for (const f of otherInteraction) {
    // Slicer-originated filters always use filter mode (not highlight).
    // Slicer source IDs start with 'slicer_'.
    const isSlicerFilter = String(f.source_visual_id || '').startsWith('slicer_')
    if (isSlicerFilter) {
      filterBucket.push(f)
      continue
    }

    const sourceVisual = visualById.get(f.source_visual_id)
    let effectiveMode: 'filter' | 'highlight' | 'none' = interactions.mode as 'filter' | 'highlight'

    if (sourceVisual) {
      const sourceInteractions = normalizeInteractions(sourceVisual)
      const perPair = sourceInteractions.interaction_targets?.[visualId]
      if (perPair === 'none' || perPair === 'filter' || perPair === 'highlight') {
        effectiveMode = perPair
      }
    }

    if (effectiveMode === 'none') continue // Drop this interaction filter
    if (effectiveMode === 'highlight') {
      highlightBucket.push(f)
    } else {
      filterBucket.push(f)
    }
  }

  // Build result:
  // - Filter-mode interactions merge into regular filters
  // - Highlight-mode interactions go to interaction_filters with render_mode 'highlight'
  const mergedFilters = [...manualFilters]
  if (filterBucket.length > 0) {
    for (const f of filterBucket) {
      mergedFilters.push({
        column: { type: 'ColumnRef' as const, table: f.table, column: f.column },
        operator: f.operator || 'in',
        values: f.values,
        scope: 'interaction',
      })
    }
  }

  if (highlightBucket.length > 0) {
    return {
      render_mode: 'highlight' as const,
      filters: mergedFilters,
      interaction_filters: highlightBucket,
    }
  }

  return { render_mode: 'normal' as const, filters: mergedFilters, interaction_filters: undefined }
}

/**
 * Hook to manage visual rendering
 * Handles render requests with debouncing and caching
 */
/** Stable fallback for visuals without render state — avoids creating a new
 *  object on every call, which would defeat React Compiler memoization and
 *  cause cascading re-renders across all VisualCard instances. */
export const EMPTY_RENDER_STATE: {
  loading: boolean
  error: string | null
  blocked: boolean
  hiddenRefs?: Array<{ kind: string; table?: string; column?: string; name?: string }>
  data?: unknown
  query?: { sql: string; row_count?: number; execution_ms?: number; filters?: unknown[]; ir?: Record<string, unknown> | string | null }
} = Object.freeze({
  loading: false,
  error: null,
  blocked: false,
})

export function useVisualRender() {
  // Use individual selectors instead of destructuring from the full store.
  // Full-store subscriptions (`useReportStore()` / `useAppStore()`) caused
  // every VisualCard to re-render on ANY store change, creating an N²
  // cascade during renderAll() that exceeded React 19's update depth limit.
  const projectPath = useAppStore(s => s.projectPath)
  const currentRole = useAppStore(s => s.currentRole)
  const setRenderState = useReportStore(s => s.setRenderState)
  // NOTE: Do NOT subscribe to renderStates here.  The old subscription
  // (`useReportStore(s => s.renderStates)`) created a new object reference
  // on every setRenderState call, causing ALL consumers of this hook to
  // re-render for every visual — an N² cascade that triggers React #185.
  // Instead, getRenderState uses getState() for imperative access, and
  // each VisualCard subscribes to its own slice via a per-visual selector.
  
  // Track pending renders to avoid duplicates
  const pendingRenders = useRef<Set<string>>(new Set())
  // Debounce timers per visual
  const debounceTimers = useRef<Map<string, ReturnType<typeof setTimeout>>>(new Map())
  // Race-proof render tokens: each visual gets a monotonically increasing counter.
  // When a response arrives, it's discarded if its token doesn't match the latest.
  const renderTokens = useRef<Map<string, number>>(new Map())
  // AbortControllers per visual — cancel in-flight requests when new renders are issued
  const abortControllers = useRef<Map<string, AbortController>>(new Map())
  // Filter fingerprint cache: skip re-renders when effective filters haven't changed
  const filterFingerprints = useRef<Map<string, string>>(new Map())
  // Fingerprints for in-flight renders. If filters change while a visual is still
  // loading, the newer request must abort/replace the stale one instead of being skipped.
  const pendingFingerprints = useRef<Map<string, string>>(new Map())

  /** Emit a performance event to the perf store (only records when isRecording). */
  function _emitPerfEvent(
    visualId: string,
    visual: VisualInfo | undefined,
    totalMs: number,
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    data?: any,
    errorMsg?: string,
  ) {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const q = data?.query as Record<string, any> | undefined
    usePerfStore.getState().addEvent({
      visualId,
      visualTitle: visual?.title || visualId,
      visualType: visual?.visual_type || 'unknown',
      totalMs,
      planMs: (q?.plan_ms as number) ?? 0,
      executeMs: (q?.execution_ms as number) ?? 0,
      sql: (q?.sql as string) ?? '',
      rowCount: (q?.row_count as number) ?? 0,
      success: !errorMsg,
      error: errorMsg || undefined,
    })
  }

  // Render a single visual
  const render = useCallback(async (
    visualId: string,
    options: {
      force?: boolean
      fingerprint?: string
      filters?: Array<{
        column: unknown
        operator?: string
        values: unknown[]
        scope?: string
      }>
      interactionFilters?: Array<{
        source_visual_id: string
        table: string
        column: string
        operator?: string
        values: unknown[]
      }>
      /** When set, override render_mode (used by renderAll to pass computed mode) */
      renderMode?: 'normal' | 'highlight'
    } = {}
  ) => {
    // Skip static visuals — they don't query data
    const visualForSkip = useReportStore.getState().visuals.find(v => v.id === visualId)
    if (visualForSkip && STATIC_VISUAL_TYPES.includes(visualForSkip.visual_type as any)) {
      return
    }

    // Skip duplicate in-flight renders, but allow a changed filter fingerprint
    // to abort/replace the stale request. This keeps slicer/crossfilter changes
    // made during initial load from being silently dropped.
    if (pendingRenders.current.has(visualId) && !options.force) {
      const nextFingerprint = typeof options.fingerprint === 'string' ? options.fingerprint : ''
      const pendingFingerprint = pendingFingerprints.current.get(visualId) || ''
      if (!nextFingerprint || nextFingerprint === pendingFingerprint) {
        return
      }
    }

    // Abort any in-flight request for this visual (crossfilter performance)
    const prevAbort = abortControllers.current.get(visualId)
    if (prevAbort) prevAbort.abort()
    const abortCtrl = new AbortController()
    abortControllers.current.set(visualId, abortCtrl)

    pendingRenders.current.add(visualId)
    if (typeof options.fingerprint === 'string' && options.fingerprint.length > 0) {
      pendingFingerprints.current.set(visualId, options.fingerprint)
    } else {
      pendingFingerprints.current.delete(visualId)
    }
    // Issue a new render token for this visual
    const prevToken = renderTokens.current.get(visualId) ?? 0
    const token = prevToken + 1
    renderTokens.current.set(visualId, token)
    setRenderState(visualId, { loading: true, error: null })

    let _perfT0 = performance.now()

    try {
      const visual = useReportStore.getState().visuals.find(v => v.id === visualId)
      const isMatrix = visual?.visual_type?.toLowerCase() === 'matrix'

      const renderFn = isMatrix ? renderMatrix : renderVisual

      // Build the render request
      const renderRequest: Parameters<typeof renderFn>[1] = {
        render_mode: options.renderMode ?? 'normal',
        filters: options.filters,
        interaction_filters: options.interactionFilters,
      }

      // Include inline visual definition for unsaved visuals so the server
      // can render them without needing a persisted JSON file on disk.
      if (visual) {
        const vAny = visual as unknown as Record<string, unknown>
        renderRequest.visual_definition = {
          id: visual.id,
          visual_type: visual.visual_type,
          title: visual.title,
          page_id: visual.page_id,
          encodings: visual.encodings || {},
          format: visual.format || {},
          interactions: visual.interactions || {},
          layout: visual.layout,
          ...(visual.static_content ? { static_content: visual.static_content } : {}),
          ...(visual.advanced_plotly_patch ? { advanced_plotly_patch: visual.advanced_plotly_patch } : {}),
          ...(vAny.param_values ? { param_values: vAny.param_values } : {}),
          ...(vAny.calc_groups ? { calc_groups: vAny.calc_groups } : {}),
          ...(Array.isArray(vAny.decision_overlays) ? { decision_overlays: vAny.decision_overlays } : {}),
          ...(vAny.pack_summary && typeof vAny.pack_summary === 'object' ? { pack_summary: vAny.pack_summary } : {}),
          ...(vAny.overlay_meta && typeof vAny.overlay_meta === 'object' ? { overlay_meta: vAny.overlay_meta } : {}),
          ...(visual.options ? { options: visual.options } : {}),
        }
      }

      // For matrix visuals, forward tablix properties and expansion state
      if (isMatrix && visual) {
        const encodings = visual.encodings as Record<string, unknown> | undefined
        const tablix = encodings?.tablix
        if (tablix && typeof tablix === 'object') {
          renderRequest.tablixProperties = tablix as Record<string, unknown>
        }
        // Forward expanded rows/cols from matrix state store
        const matrixState = useMatrixStore.getState()
        const expandedRowPaths = matrixState.getExpandedRowPaths(visualId)
        const expandedColPaths = matrixState.getExpandedColPaths(visualId)
        if (expandedRowPaths.length > 0) {
          renderRequest.expanded_rows = expandedRowPaths.map(ep => ep.path)
        }
        if (expandedColPaths.length > 0) {
          renderRequest.expanded_cols = expandedColPaths.map(ep => ep.path)
        }
        
        // Forward drill state from matrix store
        const drillState = matrixState.getDrillState(visualId)
        if (drillState.drillRowLevel !== undefined) {
          renderRequest.drill_row_level = drillState.drillRowLevel
        }
        if (drillState.drillColLevel !== undefined) {
          renderRequest.drill_col_level = drillState.drillColLevel
        }
        if (drillState.drillRowMode !== 'expand') {
          renderRequest.drill_row_mode = drillState.drillRowMode
        }
        if (drillState.drillColMode !== 'expand') {
          renderRequest.drill_col_mode = drillState.drillColMode
        }
        if (drillState.drillRowFilters.length > 0) {
          renderRequest.drill_row_filters = drillState.drillRowFilters
        }
        if (drillState.drillColFilters.length > 0) {
          renderRequest.drill_col_filters = drillState.drillColFilters
        }
        if (drillState.expandAllRows) {
          renderRequest.expand_all_rows = true
        }
        if (drillState.expandAllCols) {
          renderRequest.expand_all_cols = true
        }
        
        // Forward include_bars from visual options
        const visualOptions = visual.options as Record<string, unknown> | undefined
        if (visualOptions?.showBars) {
          renderRequest.include_bars = true
        }
        
        // Forward matrix performance safety caps from tablix settings
        const tablixCapsMaxRows = (tablix as Record<string, unknown> | undefined)?.matrix_caps_max_rows
          ?? (tablix as Record<string, unknown> | undefined)?.matrixCapsMaxRows
        const tablixCapsMaxCols = (tablix as Record<string, unknown> | undefined)?.matrix_caps_max_cols
          ?? (tablix as Record<string, unknown> | undefined)?.matrixCapsMaxCols
        if (typeof tablixCapsMaxRows === 'number' || typeof tablixCapsMaxCols === 'number') {
          renderRequest.matrix_caps = {
            ...(typeof tablixCapsMaxRows === 'number' ? { max_rows: tablixCapsMaxRows } : {}),
            ...(typeof tablixCapsMaxCols === 'number' ? { max_cols: tablixCapsMaxCols } : {}),
          }
        }
        
        // Forward CMB/RMB expand depth from tablix properties
        const tablixObj = tablix as Record<string, unknown> | undefined
        if (tablixObj) {
          const cmbDepth = tablixObj.cmb_expand_depth ?? tablixObj.cmbExpandDepth
          if (typeof cmbDepth === 'number' && cmbDepth >= 0) {
            renderRequest.cmb_expand_depth = cmbDepth
          }
          const rmbDepth = tablixObj.rmb_expand_depth ?? tablixObj.rmbExpandDepth
          if (typeof rmbDepth === 'number' && rmbDepth >= 0) {
            renderRequest.rmb_expand_depth = rmbDepth
          }
        }
      }

      // Forward chart hierarchy drill state (non-matrix visuals)
      if (!isMatrix) {
        const { useChartDrillStore } = await import('@/stores/chart-drill-store')
        const chartDrill = useChartDrillStore.getState()
        const chartDrillLevel = chartDrill.getDrillLevel(visualId)
        const chartDrillFilters = chartDrill.getDrillFilters(visualId)
        const expandCount = chartDrill.getExpandCount(visualId)
        if (chartDrillLevel > 0) {
          renderRequest.drill_level = chartDrillLevel
        }
        if (chartDrillFilters.length > 0) {
          renderRequest.drill_filters = chartDrillFilters
        }
        if (expandCount > 1) {
          renderRequest.expand_levels = expandCount
        }
      }

      // Forward drillthrough filters (when navigated to a drillthrough page)
      {
        const { useDrillthroughStore } = await import('@/stores/drillthrough-store')
        const dtState = useDrillthroughStore.getState()
        if (dtState.active && dtState.filters.length > 0) {
          const existingFilters = Array.isArray(renderRequest.filters) ? renderRequest.filters : []
          const dtFilters = dtState.filters.map(f => ({
            column: { type: 'ColumnRef' as const, table: f.table, column: f.column },
            operator: 'eq' as const,
            values: [f.value],
            scope: 'drillthrough',
          }))
          renderRequest.filters = [...existingFilters, ...dtFilters]
        }
      }

      // Performance timing: measure total round-trip
      _perfT0 = performance.now()

      const { data, error } = await renderFn(
        visualId,
        renderRequest,
        {
          project: projectPath ?? undefined,
          role: currentRole ?? undefined,
          signal: abortCtrl.signal,
        }
      )

      if (error) {
        const _perfTotalMs = performance.now() - _perfT0
        _emitPerfEvent(visualId, visual, _perfTotalMs, data, error)
        // Discard stale response
        if (renderTokens.current.get(visualId) !== token) return
        // Note: we intentionally do NOT auto-clear interaction filters on error.
        // Auto-clearing caused a cascade where one visual's error wiped filters
        // for all visuals, making crossfiltering appear broken.  Users can clear
        // interaction filters via the filter panel or by clicking the chart again.
        // Keep last good render data visible behind the error
        const prev = useReportStore.getState().renderStates[visualId]
        setRenderState(visualId, {
          loading: false,
          error,
          blocked: false,
          // Preserve last good data so UI can show it behind the error overlay
          data: prev?.data ?? null,
          query: prev?.query,
        })
        return
      }

      if (data?.blocked) {
        const _perfTotalMs = performance.now() - _perfT0
        _emitPerfEvent(visualId, visual, _perfTotalMs, undefined, 'Visual blocked by OLS')
        // Discard stale response
        if (renderTokens.current.get(visualId) !== token) return
        setRenderState(visualId, {
          loading: false,
          error: null,
          blocked: true,
          hiddenRefs: data.hidden_refs,
          data: null,
        })
        return
      }

      // Discard stale response — a newer render was issued while this one was in flight
      if (renderTokens.current.get(visualId) !== token) return

      // Emit perf event for successful render
      const _perfTotalMs = performance.now() - _perfT0
      _emitPerfEvent(visualId, visual, _perfTotalMs, data)

      setRenderState(visualId, {
        loading: false,
        error: data?.error ?? null,
        blocked: false,
        data,
        query: data?.query,
      })

      if (typeof options.fingerprint === 'string' && options.fingerprint.length > 0) {
        filterFingerprints.current.set(visualId, options.fingerprint)
      }

      // Store chart drill metadata from render response
      if (data?.drill) {
        const { useChartDrillStore } = await import('@/stores/chart-drill-store')
        useChartDrillStore.getState().setDrillMeta(visualId, data.drill)
      }
    } catch (err) {
      // Silently ignore aborted requests — they are expected during rapid crossfiltering
      if (err instanceof DOMException && err.name === 'AbortError') return
      const _perfTotalMs = performance.now() - _perfT0
      _emitPerfEvent(visualId, undefined, _perfTotalMs, undefined,
        err instanceof Error ? err.message : 'Render failed')
      // Discard stale error
      if (renderTokens.current.get(visualId) !== token) return
      const prev = useReportStore.getState().renderStates[visualId]
      setRenderState(visualId, {
        loading: false,
        error: err instanceof Error ? err.message : 'Render failed',
        blocked: false,
        // Preserve last good data
        data: prev?.data ?? null,
        query: prev?.query,
      })
    } finally {
      if (renderTokens.current.get(visualId) === token) {
        pendingRenders.current.delete(visualId)
        pendingFingerprints.current.delete(visualId)
      }
      // Clean up AbortController ref
      if (abortControllers.current.get(visualId)?.signal === abortCtrl.signal) {
        abortControllers.current.delete(visualId)
      }
    }
  }, [projectPath, currentRole, setRenderState])

  // Debounced render — delays the render call by RENDER_DEBOUNCE_MS
  const renderDebounced = useCallback((
    visualId: string,
    options: Parameters<typeof render>[1] = {}
  ) => {
    // Clear any existing debounce timer for this visual
    const existing = debounceTimers.current.get(visualId)
    if (existing) clearTimeout(existing)

    const timer = setTimeout(() => {
      debounceTimers.current.delete(visualId)
      render(visualId, options)
    }, RENDER_DEBOUNCE_MS)

    debounceTimers.current.set(visualId, timer)
  }, [render])

  // Cancel all pending/in-flight renders (used on page switch)
  const cancelAll = useCallback(() => {
    // Clear all debounce timers
    for (const timer of debounceTimers.current.values()) clearTimeout(timer)
    debounceTimers.current.clear()
    // Cancel any pending interaction debounce timer
    if (_interactionDebounceTimer.current) {
      clearTimeout(_interactionDebounceTimer.current)
      _interactionDebounceTimer.current = null
    }
    // Abort all in-flight HTTP requests
    for (const ctrl of abortControllers.current.values()) ctrl.abort()
    abortControllers.current.clear()
    // Bump all render tokens so any in-flight responses are discarded
    for (const [id, token] of renderTokens.current.entries()) {
      renderTokens.current.set(id, token + 1)
    }
    pendingRenders.current.clear()
    pendingFingerprints.current.clear()
    filterFingerprints.current.clear()
  }, [])

  // Render all visuals on the current page with proper per-visual filter sets
  const renderAll = useCallback(async (options?: { force?: boolean; interactionOnly?: boolean }) => {
    const allVisuals = useReportStore.getState().visuals
    const currentPageId = useReportStore.getState().currentPageId
    // Only render visuals belonging to the current page (store may hold
    // unsaved visuals from other pages to preserve them across navigation).
    // Pre-filter static visuals up-front to avoid per-visual lookup overhead.
    const visuals = (currentPageId
      ? allVisuals.filter(v => (v.page_id || '').toLowerCase() === currentPageId.toLowerCase())
      : allVisuals
    ).filter(v => !STATIC_VISUAL_TYPES.includes(v.visual_type as any))
    const interactionFilters = useFilterStore.getState().interactionFilters

    // Import filter state to build manual filters per-visual
    const filterState = useFilterStore.getState()
    const { reportFilters, pageFilters, visualFilters } = filterState

    // When interactionOnly is set, skip visuals that won't be affected by
    // interaction filter changes.  This avoids re-rendering unrelated visuals
    // during crossfilter events, saving ~30-60% of render requests.
    let visualsToRender = visuals
    if (options?.interactionOnly && interactionFilters.length > 0) {
      const sourceIds = new Set(interactionFilters.map(f => String(f.source_visual_id || '').trim()))
      visualsToRender = visuals.filter(v => {
        const interactions = normalizeInteractions(v)
        // Skip visuals that declared they are not affected by interactions
        if (!interactions.is_affected) return false
        // Skip the source visual — its effective filters don't change
        // because buildFiltersForVisual strips self-filters.
        if (sourceIds.has(v.id.trim())) return false
        return true
      })
    } else if (options?.interactionOnly && interactionFilters.length === 0) {
      // Interaction filters were cleared — all previously-affected visuals
      // must re-render to revert to unfiltered state.  We still skip
      // is_affected=false visuals since they were never filtered.
      visualsToRender = visuals.filter(v => {
        const interactions = normalizeInteractions(v)
        return interactions.is_affected
      })
    }

    const buildManualFilters = (visualId: string) => {
      // Build filter objects in the format the render endpoint expects.
      // Filters may have nested ColumnRef ({column: {type, table, column}})
      // or flat ({table, column}) depending on source.
      // IMPORTANT: `target` must be included so the server's
      // applicable_scoped_filters() can match page/visual scope filters to
      // the correct page_id / visual_id.  `keep` preserves the YAML-defined
      // keep-filter semantics.
      const toRenderFormat = (
        f: { table?: string; column: unknown; values: unknown[]; operator?: string; target?: string; keep?: boolean },
        scope: string,
        target?: string,
      ) => {
        const col = f.column
        const columnRef = (col && typeof col === 'object')
          ? col
          : { type: 'ColumnRef', table: f.table || '', column: String(col || '') }
        return {
          column: columnRef,
          operator: (f as { operator?: string }).operator || 'in',
          values: f.values,
          scope,
          // Use explicit target arg (page_id / visual_id) when provided,
          // otherwise fall back to the filter's own target property.
          target: target ?? f.target ?? undefined,
          keep: f.keep ?? false,
        }
      }

      const all: Array<{ column: unknown; operator: string; values: unknown[]; scope?: string; target?: string; keep?: boolean }> = []
      for (const f of reportFilters) {
        all.push(toRenderFormat(f, 'report'))
      }
      if (currentPageId && pageFilters[currentPageId]) {
        for (const f of pageFilters[currentPageId]) {
          all.push(toRenderFormat(f, 'page', currentPageId))
        }
      }
      if (visualFilters[visualId]) {
        for (const f of visualFilters[visualId]) {
          all.push(toRenderFormat(f, 'visual', visualId))
        }
      }
      return all
    }
    
    // ── Decide: batch endpoint vs individual renders ─────────────────
    // Batch is used when no interaction filters are active, no
    // drillthrough is active, and there are >1 visuals to render.
    // This eliminates N-1 HTTP round-trips for initial page loads,
    // role changes, and manual filter changes.
    let isDrillthroughActive = false
    try {
      const { useDrillthroughStore } = await import('@/stores/drillthrough-store')
      isDrillthroughActive = useDrillthroughStore.getState().active
    } catch { /* ignore */ }

    // Use batch for 4+ visuals — below that, individual parallel is
    // faster because the per-request slicer/pool overhead dominates.
    const useBatch = interactionFilters.length === 0
      && !isDrillthroughActive
      && visualsToRender.length >= 4
      && !options?.interactionOnly

    if (useBatch) {
      // ── Batch render path ────────────────────────────────────────
      // Check per-visual drill state — drilled visuals fall back to
      // individual renders (batch doesn't support drill params).
      const { useChartDrillStore } = await import('@/stores/chart-drill-store')
      const chartDrill = useChartDrillStore.getState()

      const batchCandidates: typeof visualsToRender = []
      const individualFallback: typeof visualsToRender = []
      for (const v of visualsToRender) {
        const isMatrix = v.visual_type?.toLowerCase() === 'matrix'
        const hasDrill = chartDrill.getDrillLevel(v.id) > 0
          || chartDrill.getDrillFilters(v.id).length > 0
          || chartDrill.getExpandCount(v.id) > 1
        if (isMatrix || hasDrill) {
          individualFallback.push(v)
        } else {
          batchCandidates.push(v)
        }
      }

      // Fingerprint check — only include visuals whose effective
      // filters have actually changed since the last render.
      const batchIds: string[] = []
      const perVisualFPs = new Map<string, string>()
      for (const v of batchCandidates) {
        const manual = buildManualFilters(v.id)
        const fp = JSON.stringify({
          mode: 'normal',
          filters: manual,
          interaction_filters: undefined,
          role: currentRole ?? null,
          page_id: currentPageId ?? null,
        })
        if (!options?.force && filterFingerprints.current.get(v.id) === fp) continue
        batchIds.push(v.id)
        perVisualFPs.set(v.id, fp)
      }

      // Build shared filter payload (report + page + all visual-scoped).
      // The server's scoped-filter routing applies visual-scoped filters
      // only to their target visual, so including all is correct.
      const _toFilterObj = (
        f: { table?: string; column: unknown; values: unknown[]; operator?: string; target?: string; keep?: boolean },
        scope: string,
        target?: string,
      ) => {
        const col = f.column
        const columnRef = (col && typeof col === 'object')
          ? col
          : { type: 'ColumnRef', table: f.table || '', column: String(col || '') }
        return {
          column: columnRef,
          operator: (f as { operator?: string }).operator || 'in',
          values: f.values,
          scope,
          target: target ?? f.target ?? undefined,
          keep: f.keep ?? false,
        }
      }

      if (batchIds.length > 1) {
        const allFilters: Array<{ column: unknown; operator: string; values: unknown[]; scope?: string; target?: string; keep?: boolean }> = []
        for (const f of reportFilters) allFilters.push(_toFilterObj(f, 'report'))
        if (currentPageId && pageFilters[currentPageId]) {
          for (const f of pageFilters[currentPageId]) allFilters.push(_toFilterObj(f, 'page', currentPageId))
        }
        for (const vid of batchIds) {
          if (visualFilters[vid]) {
            for (const f of visualFilters[vid]) allFilters.push(_toFilterObj(f, 'visual', vid))
          }
        }

        // Set loading state + render tokens for all batch visuals
        for (const vid of batchIds) {
          const prevAbort = abortControllers.current.get(vid)
          if (prevAbort) prevAbort.abort()
          const prevToken = renderTokens.current.get(vid) ?? 0
          renderTokens.current.set(vid, prevToken + 1)
          setRenderState(vid, { loading: true, error: null })
        }
        const batchAbort = new AbortController()
        for (const vid of batchIds) abortControllers.current.set(vid, batchAbort)
        const batchTokenSnap = new Map<string, number>()
        for (const vid of batchIds) batchTokenSnap.set(vid, renderTokens.current.get(vid)!)
        const _batchT0 = performance.now()

        try {
          const { data: batchData, error: batchError } = await renderBatch(
            { visual_ids: batchIds, filters: allFilters },
            { project: projectPath ?? undefined, role: currentRole ?? undefined, signal: batchAbort.signal },
          )

          if (batchError) {
            // Batch HTTP error — set error on all visuals
            for (const vid of batchIds) {
              if (renderTokens.current.get(vid) !== batchTokenSnap.get(vid)) continue
              const prev = useReportStore.getState().renderStates[vid]
              setRenderState(vid, { loading: false, error: batchError, blocked: false, data: prev?.data ?? null, query: prev?.query })
            }
          } else if (batchData?.results) {
            for (const vid of batchIds) {
              if (renderTokens.current.get(vid) !== batchTokenSnap.get(vid)) continue
              const result = batchData.results[vid]
              if (!result) {
                setRenderState(vid, { loading: false, error: 'Missing from batch', blocked: false })
                continue
              }
              // Server returned skip (matrix that slipped through) — queue individual
              if (result.skip) {
                const v = batchCandidates.find(x => x.id === vid)
                if (v) individualFallback.push(v)
                continue
              }
              if (result.blocked) {
                setRenderState(vid, { loading: false, error: null, blocked: true, hiddenRefs: result.hidden_refs, data: null })
                const visual = batchCandidates.find(x => x.id === vid)
                _emitPerfEvent(vid, visual, performance.now() - _batchT0, undefined, 'Visual blocked by OLS')
                continue
              }
              if (result.error && !(result as { ok?: boolean }).ok) {
                const prev = useReportStore.getState().renderStates[vid]
                setRenderState(vid, { loading: false, error: result.error, blocked: false, data: prev?.data ?? null, query: prev?.query })
                const visual = batchCandidates.find(x => x.id === vid)
                _emitPerfEvent(vid, visual, performance.now() - _batchT0, result, result.error)
                continue
              }
              // Success — distribute result
              setRenderState(vid, { loading: false, error: result.error ?? null, blocked: false, data: result, query: result.query })
              const fp = perVisualFPs.get(vid)
              if (fp) filterFingerprints.current.set(vid, fp)
              const visual = batchCandidates.find(x => x.id === vid)
              _emitPerfEvent(vid, visual, performance.now() - _batchT0, result)
              if (result.drill) {
                chartDrill.setDrillMeta(vid, result.drill)
              }
            }
          }
        } catch (err) {
          if (err instanceof DOMException && err.name === 'AbortError') return
          for (const vid of batchIds) {
            if (renderTokens.current.get(vid) !== batchTokenSnap.get(vid)) continue
            setRenderState(vid, { loading: false, error: err instanceof Error ? err.message : 'Batch render failed', blocked: false })
          }
        }
      } else {
        // 0–1 batchable visuals — fold into individual fallback
        for (const vid of batchIds) {
          const v = batchCandidates.find(x => x.id === vid)
          if (v) individualFallback.push(v)
        }
      }

      // Individual renders for matrix / drilled / skipped visuals
      if (individualFallback.length > 0) {
        await pAll(
          individualFallback.map(v => () => {
            const manual = buildManualFilters(v.id)
            const fp = JSON.stringify({
              mode: 'normal',
              filters: manual,
              interaction_filters: undefined,
              role: currentRole ?? null,
              page_id: currentPageId ?? null,
            })
            if (!options?.force && filterFingerprints.current.get(v.id) === fp) return Promise.resolve()
            return render(v.id, { force: options?.force, fingerprint: fp, filters: manual })
          }),
          MAX_CONCURRENT_RENDERS,
        )
      }
    } else {
      // ── Individual render path (interaction filters or drillthrough) ──
      // Per-visual filter routing is required for correct crossfilter behavior.
      await pAll(
        visualsToRender.map(v => () => {
          const manual = buildManualFilters(v.id)
          const perVisual = buildFiltersForVisual(v.id, v, manual, interactionFilters, visuals)
          const fp = JSON.stringify({
            mode: perVisual.render_mode,
            filters: perVisual.filters,
            interaction_filters: perVisual.interaction_filters,
            role: currentRole ?? null,
            page_id: currentPageId ?? null,
          })
          if (!options?.force && filterFingerprints.current.get(v.id) === fp) {
            return Promise.resolve()
          }
          return render(v.id, {
            force: options?.force,
            fingerprint: fp,
            filters: perVisual.filters,
            interactionFilters: perVisual.interaction_filters,
            renderMode: perVisual.render_mode,
          })
        }),
        MAX_CONCURRENT_RENDERS,
      )
    }
  }, [render, currentRole])

  // ── Coalescing wrapper ────────────────────────────────────────────────
  // Multiple useEffect hooks in Canvas can call renderAll in the same
  // React commit (e.g. visualIdsKey + filtersVersion both change on page
  // navigation).  Without coalescing each visual gets 2× HTTP requests.
  // This wrapper defers execution to the next microtask and merges
  // options: if ANY caller requested force, the merged call uses force.
  const _coalescePending = useRef(false)
  const _coalesceForce = useRef(false)
  const _coalesceInteractionOnly = useRef(false)
  // Separate debounce timer for interaction-only re-renders.
  // Rapid crossfilter clicks are coalesced within INTERACTION_DEBOUNCE_MS
  // so that only one renderAll fires per burst of clicks.
  const _interactionDebounceTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  const renderAllCoalesced = useCallback((options?: { force?: boolean; interactionOnly?: boolean }) => {
    if (options?.force) _coalesceForce.current = true
    if (options?.interactionOnly) _coalesceInteractionOnly.current = true

    // ── Interaction-only path: debounced with setTimeout ─────────────
    // Rapid crossfilter clicks fire many setInteractionFilters → useEffect
    // calls within milliseconds.  queueMicrotask only coalesces within a
    // single synchronous tick, so successive clicks still trigger separate
    // renderAll cycles.  Using setTimeout(INTERACTION_DEBOUNCE_MS) ensures
    // that clicks arriving within the window are merged into ONE renderAll,
    // reducing backend requests by up to 80% during fast exploration.
    if (options?.interactionOnly && !_coalescePending.current) {
      if (_interactionDebounceTimer.current) {
        clearTimeout(_interactionDebounceTimer.current)
      }
      _interactionDebounceTimer.current = setTimeout(() => {
        _interactionDebounceTimer.current = null
        const force = _coalesceForce.current
        const interactionOnly = _coalesceInteractionOnly.current
        _coalesceForce.current = false
        _coalesceInteractionOnly.current = false
        renderAll({ force, interactionOnly })
      }, INTERACTION_DEBOUNCE_MS)
      return
    }

    // ── Normal path: queueMicrotask (immediate, coalesces within one tick)
    if (_coalescePending.current) return          // already scheduled
    _coalescePending.current = true
    // Cancel any pending interaction debounce — the non-interaction render
    // will cover everything (it renders ALL visuals, not just affected ones).
    if (_interactionDebounceTimer.current) {
      clearTimeout(_interactionDebounceTimer.current)
      _interactionDebounceTimer.current = null
    }
    // queueMicrotask fires after all synchronous useEffect callbacks in the
    // same React commit, but before the browser paints.
    queueMicrotask(() => {
      const force = _coalesceForce.current
      const interactionOnly = _coalesceInteractionOnly.current
      _coalescePending.current = false
      _coalesceForce.current = false
      _coalesceInteractionOnly.current = false
      renderAll({ force, interactionOnly })
    })
  }, [renderAll])

  // Get render state for a visual — imperative (non-reactive) access via
  // getState().  This function is stable (empty dep array) and does NOT
  // trigger re-renders.  Components that need reactive render-state updates
  // should subscribe directly: useReportStore(s => s.renderStates[id]).
  const getRenderState = useCallback((visualId: string) => {
    return useReportStore.getState().renderStates[visualId] ?? EMPTY_RENDER_STATE
  }, [])

  return {
    render,
    renderDebounced,
    renderAll,
    renderAllCoalesced,
    cancelAll,
    getRenderState,
  }
}

import { useCallback, useMemo } from 'react'
import { useAppStore, useFilterStore, useReportStore } from '@/stores'
import type { VisualInfo, ColumnRef, HierarchiesMap } from '@/lib/api'

export interface InteractionFilter {
  id: string
  source_visual_id: string
  table: string
  column: string
  values: unknown[]
  /** Point indices for scatter-level highlighting (parallel to values) */
  pointIndices?: number[]
}

export interface InteractionClick {
  visualId: string
  column: ColumnRef
  value: unknown
  isMultiSelect: boolean
  /** The Plotly pointIndex of the clicked data point (for scatter highlighting) */
  pointIndex?: number
}

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
 * Resolve a HierarchyRef encoding to a ColumnRef using the first hierarchy level.
 * Returns null if the hierarchy is not found or has no levels.
 */
function resolveHierarchyRef(
  enc: Record<string, unknown>,
  hierarchies: HierarchiesMap | undefined,
): ColumnRef | null {
  if (!hierarchies) return null
  const ref = enc as { type?: string; name?: string }
  if (ref.type !== 'HierarchyRef' || !ref.name) return null
  const def = hierarchies[ref.name]
  if (!def || !def.levels || def.levels.length === 0) return null
  return { type: 'ColumnRef', table: def.table, column: def.levels[0].column }
}

/**
 * Try to extract a ColumnRef from a single encoding field.
 * Handles both ColumnRef and HierarchyRef (resolved via hierarchies map).
 */
function resolveEncodingField(
  field: unknown,
  hierarchies: HierarchiesMap | undefined,
): ColumnRef | null {
  if (!field || typeof field !== 'object') return null
  const obj = field as Record<string, unknown>
  if ((obj as unknown as ColumnRef).type === 'ColumnRef') return obj as unknown as ColumnRef
  if (obj.type === 'HierarchyRef') return resolveHierarchyRef(obj, hierarchies)
  return null
}

function getVisualCategoricalAxisColumn(
  v: VisualInfo,
  hierarchies?: HierarchiesMap,
): ColumnRef | null {
  const enc = v.encodings
  if (!enc || typeof enc !== 'object') return null
  
  // Check x axis first
  const xResult = resolveEncodingField(enc.x, hierarchies)
  if (xResult) return xResult
  
  // Then color axis
  const colorResult = resolveEncodingField(enc.color, hierarchies)
  if (colorResult) return colorResult
  
  // Then y axis
  const yResult = resolveEncodingField(enc.y, hierarchies)
  if (yResult) return yResult

  // Pie charts: check encodings.names (single ColumnRef or HierarchyRef)
  const namesResult = resolveEncodingField((enc as Record<string, unknown>).names, hierarchies)
  if (namesResult) return namesResult

  // Polar charts: check encodings.theta (angular dimension)
  const thetaResult = resolveEncodingField((enc as Record<string, unknown>).theta, hierarchies)
  if (thetaResult) return thetaResult

  // Treemap / sunburst / icicle: check encodings.path[] (first resolvable ref)
  const path = (enc as Record<string, unknown>).path
  if (Array.isArray(path)) {
    for (const p of path) {
      const pathResult = resolveEncodingField(p, hierarchies)
      if (pathResult) return pathResult
    }
  }
  
  // For table/tablix visuals: check encodings.columns[] for the first resolvable ref
  const columns = enc.columns
  if (Array.isArray(columns)) {
    for (const col of columns) {
      const colResult = resolveEncodingField(col, hierarchies)
      if (colResult) return colResult
    }
  }

  // For matrix visuals: check encodings.rows[] for the first resolvable ref
  const rows = enc.rows
  if (Array.isArray(rows)) {
    for (const r of rows) {
      const rowResult = resolveEncodingField(r, hierarchies)
      if (rowResult) return rowResult
    }
  }
  
  return null
}

function interactionColumnKey(col: ColumnRef | null): string {
  if (!col) return ''
  const t = String(col.table || '').trim()
  const c = String(col.column || '').trim()
  if (!t || !c) return ''
  return `${t}.${c}`
}

function interactionValueKey(value: unknown): string {
  return JSON.stringify(value === undefined ? null : value)
}

export function useInteractions() {
  const interactionFilters = useFilterStore(s => s.interactionFilters)
  const setInteractionFilters = useFilterStore(s => s.setInteractionFilters)
  const clearInteractionFilters = useFilterStore(s => s.clearInteractionFilters)
  const visuals = useReportStore(s => s.visuals)
  const hierarchies = useAppStore(s => s.hierarchies)
  
  // Apply interaction selection (click on chart point)
  const applyInteractionSelection = useCallback((click: InteractionClick) => {
    const { visualId, column, value, isMultiSelect, pointIndex } = click
    const sourceVisual = visuals.find(v => v.id === visualId)
    
    if (!sourceVisual) return
    
    // Check if this visual can affect others
    const interactions = normalizeInteractions(sourceVisual)
    if (!interactions.affects_others) return
    
    const colKey = interactionColumnKey(column)
    if (!colKey) return
    
    const vKey = interactionValueKey(value)
    
    // Find existing filter for this source visual and column
    const existingFilterIdx = interactionFilters.findIndex(
      f => f.source_visual_id === visualId && 
           f.table === column.table && 
           f.column === column.column
    )
    
    let nextFilters = [...interactionFilters]
    
    if (existingFilterIdx >= 0) {
      const existing = nextFilters[existingFilterIdx]
      const curValues = existing.values
      const curPtIdx = existing.pointIndices ?? []
      
      if (isMultiSelect) {
        // Toggle value in array
        const valueExists = curValues.some(v => interactionValueKey(v) === vKey)
        if (valueExists) {
          const keep: number[] = []
          const newValues = curValues.filter((v, i) => {
            const keepIt = interactionValueKey(v) !== vKey
            if (keepIt) keep.push(curPtIdx[i] ?? -1)
            return keepIt
          })
          if (newValues.length === 0) {
            // Remove filter entirely
            nextFilters.splice(existingFilterIdx, 1)
          } else {
            nextFilters[existingFilterIdx] = { ...existing, values: newValues, pointIndices: keep }
          }
        } else {
          nextFilters[existingFilterIdx] = {
            ...existing,
            values: [...curValues, value],
            pointIndices: [...curPtIdx, pointIndex ?? -1],
          }
        }
      } else {
        // Single-select: if clicking same value AND same point, clear; otherwise replace
        const samePointIndex = curPtIdx.length === 1 && pointIndex !== undefined && curPtIdx[0] === pointIndex
        const sameValue = curValues.length === 1 && interactionValueKey(curValues[0]) === vKey
        if (sameValue && (samePointIndex || pointIndex === undefined)) {
          nextFilters.splice(existingFilterIdx, 1)
        } else {
          nextFilters[existingFilterIdx] = {
            ...existing,
            values: [value],
            pointIndices: pointIndex !== undefined ? [pointIndex] : [],
          }
        }
      }
    } else {
      // Create new interaction filter
      const newFilter: InteractionFilter = {
        id: `if_${Date.now()}_${Math.floor(Math.random() * 1e9)}`,
        source_visual_id: visualId,
        table: column.table,
        column: column.column,
        values: [value],
        pointIndices: pointIndex !== undefined ? [pointIndex] : [],
      }
      nextFilters.push(newFilter)
    }
    
    setInteractionFilters(nextFilters)
  }, [interactionFilters, setInteractionFilters, visuals])

  /**
   * Apply multi-column interaction selection (table row click).
   * When clicking a table row, ALL dimension (ColumnRef) columns from that
   * row should be sent as interaction filters so the crossfilter targets
   * every axis, not just one column.
   *
   * Toggle logic: if the exact same set of columns+values is already active
   * for this visual, clear the interaction. Otherwise replace.
   */
  const applyRowInteractionSelection = useCallback((
    visualId: string,
    columnValues: Array<{ column: ColumnRef; value: unknown }>,
  ) => {
    const sourceVisual = visuals.find(v => v.id === visualId)
    if (!sourceVisual) return

    const interactions = normalizeInteractions(sourceVisual)
    if (!interactions.affects_others) return

    if (columnValues.length === 0) return

    // Check if the exact same row selection is already active → toggle off
    const existing = interactionFilters.filter(f => f.source_visual_id === visualId)
    const sameSelection = existing.length === columnValues.length && columnValues.every(cv => {
      const colKey = interactionColumnKey(cv.column)
      const match = existing.find(f => `${f.table}.${f.column}` === colKey)
      if (!match) return false
      return match.values.length === 1 && interactionValueKey(match.values[0]) === interactionValueKey(cv.value)
    })

    if (sameSelection) {
      // Toggle off: remove all interaction filters from this visual
      setInteractionFilters(interactionFilters.filter(f => f.source_visual_id !== visualId))
      return
    }

    // Replace all interaction filters from this visual with the new row selection
    const nextFilters = interactionFilters.filter(f => f.source_visual_id !== visualId)
    for (const cv of columnValues) {
      const colKey = interactionColumnKey(cv.column)
      if (!colKey) continue
      nextFilters.push({
        id: `if_${Date.now()}_${Math.floor(Math.random() * 1e9)}`,
        source_visual_id: visualId,
        table: cv.column.table,
        column: cv.column.column,
        values: [cv.value],
        pointIndices: [],
      })
    }
    setInteractionFilters(nextFilters)
  }, [interactionFilters, setInteractionFilters, visuals])
  
  // Determine which visuals are affected by current filters
  // Respects per-pair interaction_targets overrides from source visuals.
  const getAffectedVisualIds = useMemo(() => {
    if (interactionFilters.length === 0) return new Set<string>()
    
    // Collect unique source visual ids from active interaction filters
    const sourceIds = new Set(interactionFilters.map(f => f.source_visual_id))
    const sourceVisuals = visuals.filter(v => sourceIds.has(v.id))

    const affected = new Set<string>()
    for (const target of visuals) {
      const tInteractions = normalizeInteractions(target)
      if (!tInteractions.is_affected) continue
      // Exclude source visuals from being affected by their own filters
      if (sourceIds.has(target.id)) continue

      // Check per-pair overrides from each source
      let hasFilterSource = false
      for (const src of sourceVisuals) {
        const srcInteractions = normalizeInteractions(src)
        const perPair = srcInteractions.interaction_targets?.[target.id]
        // Effective mode: per-pair override > target's own mode
        const effectiveMode = perPair ?? tInteractions.mode
        if (effectiveMode === 'filter') {
          hasFilterSource = true
          break
        }
      }
      if (hasFilterSource) affected.add(target.id)
    }
    return affected
  }, [interactionFilters, visuals])
  
  // Get highlight mode visuals (for highlight rendering)
  // Respects per-pair interaction_targets overrides from source visuals.
  const getHighlightVisualIds = useMemo(() => {
    if (interactionFilters.length === 0) return new Set<string>()
    
    const sourceIds = new Set(interactionFilters.map(f => f.source_visual_id))
    const sourceVisuals = visuals.filter(v => sourceIds.has(v.id))

    const highlight = new Set<string>()
    for (const target of visuals) {
      const tInteractions = normalizeInteractions(target)
      if (!tInteractions.is_affected) continue
      if (sourceIds.has(target.id)) continue

      for (const src of sourceVisuals) {
        const srcInteractions = normalizeInteractions(src)
        const perPair = srcInteractions.interaction_targets?.[target.id]
        const effectiveMode = perPair ?? tInteractions.mode
        if (effectiveMode === 'highlight') {
          highlight.add(target.id)
          break
        }
      }
    }
    return highlight
  }, [interactionFilters, visuals])
  
  // Check if a visual has active interaction selection
  const hasActiveInteraction = useCallback((visualId: string) => {
    return interactionFilters.some(f => f.source_visual_id === visualId)
  }, [interactionFilters])
  
  // Get the categorical column for a visual (for click handling)
  const getCategoricalColumn = useCallback((visual: VisualInfo): ColumnRef | null => {
    return getVisualCategoricalAxisColumn(visual, hierarchies)
  }, [hierarchies])
  
  // Clear all interaction filters from a specific source visual
  const clearInteractionsForVisual = useCallback((visualId: string) => {
    clearInteractionFilters(visualId)
  }, [clearInteractionFilters])
  
  // Clear all interaction filters
  const clearAllInteractions = useCallback(() => {
    clearInteractionFilters()
  }, [clearInteractionFilters])
  
  return {
    interactionFilters,
    applyInteractionSelection,
    applyRowInteractionSelection,
    getAffectedVisualIds,
    getHighlightVisualIds,
    hasActiveInteraction,
    getCategoricalColumn,
    clearInteractionsForVisual,
    clearAllInteractions,
    normalizeInteractions,
  }
}

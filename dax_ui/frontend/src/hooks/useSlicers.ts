import { useState, useCallback, useMemo } from 'react'
import { useAppStore } from '@/stores'
import {
  getUnifiedSlicers,
  createUnifiedSlicer,
  updateUnifiedSlicer,
  deleteUnifiedSlicer,
  getSlicerValues,
  type UnifiedSlicer,
  type SlicerDef,
  type SlicerInstance,
  type SlicerValuesRequest,
} from '@/lib/api'

type SlicerVisualType = NonNullable<SlicerDef['type']>

function normalizeSlicerVisualType(type: UnifiedSlicer['type'], style?: string): SlicerVisualType {
  const raw = String(style || type || 'list').trim().toLowerCase()
  if (raw.includes('button')) return 'button'
  if (raw.includes('tile')) return 'tile'
  if (raw.includes('input')) return 'input'
  if (raw.includes('relative') && raw.includes('time')) return 'relative_time'
  if (raw.includes('relative')) return 'relative_date'
  if (raw.includes('between') || raw.includes('range')) return 'date_range'
  if (raw.includes('dropdown')) return 'dropdown'
  return (type || 'list') as SlicerVisualType
}

interface UseSlicersReturn {
  // Unified state (authoritative)
  slicers: UnifiedSlicer[]

  // Backward-compat projections (derived from unified)
  slicerDefs: SlicerDef[]
  slicerInstances: SlicerInstance[]
  loading: boolean
  error: string | null
  
  // Load operations
  loadSlicerDefs: () => Promise<void>
  loadSlicerInstances: () => Promise<void>
  loadAll: () => Promise<void>
  
  // Definition CRUD (operates on unified slicers)
  saveDef: (def: SlicerDef | Omit<SlicerDef, 'id'>, isNew?: boolean) => Promise<{ success: boolean; error?: string }>
  removeDef: (defId: string) => Promise<{ success: boolean; error?: string }>
  saveAllDefs: (defs: SlicerDef[]) => Promise<{ success: boolean; error?: string }>
  
  // Instance CRUD (operates on unified slicer page entries)
  saveInstance: (instance: SlicerInstance | Omit<SlicerInstance, 'id'>, isNew?: boolean) => Promise<{ success: boolean; error?: string }>
  removeInstance: (instanceId: string) => Promise<{ success: boolean; error?: string }>
  saveAllInstances: (instances: SlicerInstance[]) => Promise<{ success: boolean; error?: string }>
  
  // Duplicate operations
  duplicatePlacement: (instance: SlicerInstance) => Promise<{ success: boolean; error?: string }>
  duplicateIndependent: (instance: SlicerInstance) => Promise<{ success: boolean; error?: string }>
  
  // Values
  fetchValues: (request: SlicerValuesRequest) => Promise<{ values: unknown[]; total?: number; has_more?: boolean; error?: string }>
  
  // Helpers
  getDefById: (defId: string) => SlicerDef | undefined
  getInstanceById: (instanceId: string) => SlicerInstance | undefined
  getInstancesForPage: (pageId: string) => SlicerInstance[]
  getInstancesForDef: (defId: string) => SlicerInstance[]
}

/** Convert a unified slicer to the legacy SlicerDef shape */
function toSlicerDef(s: UnifiedSlicer): SlicerDef {
  const style = typeof s.ui?.style === 'string' ? s.ui.style : undefined
  return {
    id: s.id,
    name: s.name,
    column: s.column,
    type: normalizeSlicerVisualType(s.type, style),
    sync_group: s.sync_group,
    selection_type: s.ui?.multi === false ? 'single' : 'multi',
    show_select_all: s.ui?.show_select_all !== false,
    search_enabled: s.ui?.search !== false,
    auto_apply: s.behavior?.auto_apply !== false,
    force_selection: s.behavior?.force_selection === true,
    apply_to: s.behavior?.apply_to,
    style,
    paste_values: s.ui?.paste_values === true,
    leaf_only: s.ui?.leaf_only === true,
    image_fit: typeof s.ui?.image_fit === 'string' ? s.ui.image_fit : undefined,
    image_position: typeof s.ui?.image_position === 'string' ? s.ui.image_position : undefined,
    image_saturation: typeof s.ui?.image_saturation === 'number' || typeof s.ui?.image_saturation === 'string' ? s.ui.image_saturation : undefined,
    image_background: typeof s.ui?.image_background === 'string' ? s.ui.image_background : undefined,
    image_padding: typeof s.ui?.image_padding === 'number' || typeof s.ui?.image_padding === 'string' ? s.ui.image_padding : undefined,
    filter_operator: typeof s.ui?.filter_operator === 'string' ? s.ui.filter_operator : undefined,
    input_mode: typeof s.ui?.input_mode === 'string' ? s.ui.input_mode : undefined,
    selection: s.selection,
    defaults: s.defaults,
    pages: s.pages,
  }
}

/** Derive synthetic SlicerInstance entries from a unified slicer's pages */
function toSlicerInstances(s: UnifiedSlicer): SlicerInstance[] {
  const instances: SlicerInstance[] = []
  for (const [pageId, entry] of Object.entries(s.pages || {})) {
    if (!entry.visible) continue
    instances.push({
      id: `si_${s.id}_${pageId}`,
      def_id: s.id,
      page_id: pageId,
      x: entry.layout?.x ?? 0,
      y: entry.layout?.y ?? 0,
      width: entry.layout?.w ?? 240,
      height: entry.layout?.h ?? 260,
      selected_values: s.selection?.mode === 'range'
        ? [s.selection.start, s.selection.end].filter((value): value is string => typeof value === 'string' && value.trim().length > 0)
        : s.selection?.values,
    })
  }
  return instances
}

/** Convert a SlicerDef back to a partial unified slicer for save operations */
function fromSlicerDef(def: SlicerDef | (Omit<SlicerDef, 'id'> & { id?: string })): Partial<UnifiedSlicer> & { name: string; column: { table: string; column: string } } {
  return {
    ...(('id' in def && def.id) ? { id: def.id } : {}),
    name: def.name,
    column: def.column,
    type: def.type,
    sync_group: def.sync_group,
    ui: {
      multi: def.selection_type !== 'single',
      search: def.search_enabled !== false,
      show_select_all: def.show_select_all !== false,
      paste_values: def.paste_values === true,
      leaf_only: def.leaf_only === true,
      ...(def.image_fit ? { image_fit: def.image_fit } : {}),
      ...(def.image_position ? { image_position: def.image_position } : {}),
      ...(def.image_saturation !== undefined ? { image_saturation: def.image_saturation } : {}),
      ...(def.image_background ? { image_background: def.image_background } : {}),
      ...(def.image_padding !== undefined ? { image_padding: def.image_padding } : {}),
      ...(def.filter_operator ? { filter_operator: def.filter_operator } : {}),
      ...(def.input_mode ? { input_mode: def.input_mode } : {}),
      ...(def.style ? { style: def.style } : {}),
    },
    behavior: {
      apply_to: def.apply_to ?? 'all_visuals',
      auto_apply: def.auto_apply !== false,
      force_selection: def.force_selection === true,
    },
    ...(def.selection ? { selection: def.selection } : {}),
    defaults: def.defaults,
  }
}

export function useSlicers(): UseSlicersReturn {
  const projectPath = useAppStore(s => s.projectPath)
  const currentRole = useAppStore(s => s.currentRole)
  
  const [slicers, setSlicers] = useState<UnifiedSlicer[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Backward-compat projections (derived)
  const slicerDefs = useMemo(() => slicers.map(toSlicerDef), [slicers])
  const slicerInstances = useMemo(() => slicers.flatMap(toSlicerInstances), [slicers])

  // Load unified slicers
  const loadAll = useCallback(async () => {
    if (!projectPath) return
    setLoading(true)
    setError(null)
    const result = await getUnifiedSlicers(projectPath)
    if (result.error) {
      setError(result.error)
      setSlicers([])
    } else {
      setSlicers(result.data?.slicers || [])
    }
    setLoading(false)
  }, [projectPath])

  // Aliases for compat
  const loadSlicerDefs = loadAll
  const loadSlicerInstances = loadAll

  // Save or create a definition (operates on unified slicer)
  const saveDef = useCallback(async (
    def: SlicerDef | Omit<SlicerDef, 'id'>,
    isNew = false
  ): Promise<{ success: boolean; error?: string }> => {
    if (!projectPath) return { success: false, error: 'No project loaded' }
    
    const slicerData = fromSlicerDef(def)
    let result
    
    if (isNew || !('id' in def) || !def.id) {
      // Create: include pages for all current pages (report-scoped by default)
      result = await createUnifiedSlicer(
        { ...slicerData, pages: {} } as Omit<UnifiedSlicer, 'id'>,
        projectPath
      )
    } else {
      result = await updateUnifiedSlicer(def.id, slicerData, projectPath)
    }
    
    if (result.error) {
      return { success: false, error: result.error }
    }
    setSlicers(result.data?.slicers || [])
    return { success: true }
  }, [projectPath])

  // Remove a definition (deletes the whole unified slicer)
  const removeDef = useCallback(async (defId: string): Promise<{ success: boolean; error?: string }> => {
    if (!projectPath) return { success: false, error: 'No project loaded' }
    const result = await deleteUnifiedSlicer(defId, projectPath)
    if (result.error) {
      return { success: false, error: result.error }
    }
    setSlicers(result.data?.slicers || [])
    return { success: true }
  }, [projectPath])

  // Save all definitions (bulk replace)
  const saveAllDefs = useCallback(async (_defs: SlicerDef[]): Promise<{ success: boolean; error?: string }> => {
    // Not commonly used with unified model; reload instead
    await loadAll()
    return { success: true }
  }, [loadAll])

  // Save or create an instance (adds/updates a page entry on a unified slicer)
  const saveInstance = useCallback(async (
    instance: SlicerInstance | Omit<SlicerInstance, 'id'>,
    _isNew = false
  ): Promise<{ success: boolean; error?: string }> => {
    if (!projectPath) return { success: false, error: 'No project loaded' }
    
    const defId = 'def_id' in instance ? instance.def_id : ''
    const pageId = instance.page_id
    if (!defId || !pageId) return { success: false, error: 'def_id and page_id are required' }
    
    // Find existing slicer and update its pages dict
    const existing = slicers.find(s => s.id?.toLowerCase() === defId.toLowerCase())
    if (!existing) return { success: false, error: `Slicer not found: ${defId}` }
    
    const updatedPages = { ...existing.pages }
    updatedPages[pageId] = {
      visible: true,
      sync: updatedPages[pageId]?.sync ?? true,
      layout: {
        x: instance.x ?? 0,
        y: instance.y ?? 0,
        w: instance.width ?? 240,
        h: instance.height ?? 260,
      },
    }
    
    const result = await updateUnifiedSlicer(defId, { pages: updatedPages }, projectPath)
    if (result.error) {
      return { success: false, error: result.error }
    }
    setSlicers(result.data?.slicers || [])
    return { success: true }
  }, [projectPath, slicers])

  // Remove an instance (sets page entry visible=false or removes it)
  const removeInstance = useCallback(async (instanceId: string): Promise<{ success: boolean; error?: string }> => {
    if (!projectPath) return { success: false, error: 'No project loaded' }
    
    // Parse synthetic instance ID: si_{slicer_id}_{page_id}
    const match = instanceId.match(/^si_(.+)_([^_]+)$/)
    if (!match) return { success: false, error: `Invalid instance ID: ${instanceId}` }
    
    const slicerId = match[1]
    const pageId = match[2]
    
    const existing = slicers.find(s => s.id?.toLowerCase() === slicerId.toLowerCase())
    if (!existing) return { success: false, error: `Slicer not found: ${slicerId}` }
    
    const updatedPages = { ...existing.pages }
    delete updatedPages[pageId]
    
    const result = await updateUnifiedSlicer(slicerId, { pages: updatedPages }, projectPath)
    if (result.error) {
      return { success: false, error: result.error }
    }
    setSlicers(result.data?.slicers || [])
    return { success: true }
  }, [projectPath, slicers])

  // Save all instances (not commonly used with unified model)
  const saveAllInstances = useCallback(async (_instances: SlicerInstance[]): Promise<{ success: boolean; error?: string }> => {
    await loadAll()
    return { success: true }
  }, [loadAll])

  // Fetch values for a slicer
  const fetchValues = useCallback(async (request: SlicerValuesRequest): Promise<{ values: unknown[]; total?: number; has_more?: boolean; error?: string }> => {
    const result = await getSlicerValues(request, projectPath || undefined, currentRole || undefined)
    if (result.error) {
      return { values: [], error: result.error }
    }
    return {
      values: result.data?.values || [],
      total: result.data?.total,
      has_more: result.data?.has_more,
    }
  }, [projectPath, currentRole])

  // Helper: get def by ID
  const getDefById = useCallback((defId: string): SlicerDef | undefined => {
    return slicerDefs.find(d => d.id?.toLowerCase() === defId?.toLowerCase())
  }, [slicerDefs])

  // Helper: get instance by ID
  const getInstanceById = useCallback((instanceId: string): SlicerInstance | undefined => {
    return slicerInstances.find(i => i.id?.toLowerCase() === instanceId?.toLowerCase())
  }, [slicerInstances])

  // Helper: get instances for a page
  const getInstancesForPage = useCallback((pageId: string): SlicerInstance[] => {
    return slicerInstances.filter(i => i.page_id?.toLowerCase() === pageId?.toLowerCase())
  }, [slicerInstances])

  // Helper: get instances for a def
  const getInstancesForDef = useCallback((defId: string): SlicerInstance[] => {
    return slicerInstances.filter(i => i.def_id?.toLowerCase() === defId?.toLowerCase())
  }, [slicerInstances])

  // Duplicate placement: add same slicer to same page at offset position
  const duplicatePlacement = useCallback(async (
    instance: SlicerInstance
  ): Promise<{ success: boolean; error?: string }> => {
    if (!projectPath) return { success: false, error: 'No project loaded' }
    // For unified: this doesn't quite make sense (one slicer per page).
    // Instead, offset the layout position.
    return saveInstance({
      def_id: instance.def_id,
      page_id: instance.page_id,
      x: (instance.x ?? 0) + 20,
      y: (instance.y ?? 0) + 20,
      width: instance.width ?? 200,
      height: instance.height ?? 300,
    }, true)
  }, [projectPath, saveInstance])

  // Duplicate independent: clone the slicer + create on same page
  const duplicateIndependent = useCallback(async (
    instance: SlicerInstance
  ): Promise<{ success: boolean; error?: string }> => {
    if (!projectPath) return { success: false, error: 'No project loaded' }
    const original = slicers.find(
      s => s.id?.toLowerCase() === instance.def_id?.toLowerCase()
    )
    if (!original) {
      return { success: false, error: 'Original slicer not found' }
    }
    // Clone with a new page entry
    const { id: _id, ...withoutId } = original
    const cloned: Omit<UnifiedSlicer, 'id'> = {
      ...withoutId,
      name: `${original.name} (copy)`,
      pages: {
        [instance.page_id]: {
          visible: true,
          sync: true,
          layout: {
            x: (instance.x ?? 0) + 20,
            y: (instance.y ?? 0) + 20,
            w: instance.width ?? 240,
            h: instance.height ?? 260,
          },
        },
      },
    }
    const result = await createUnifiedSlicer(cloned, projectPath)
    if (result.error) {
      return { success: false, error: result.error }
    }
    setSlicers(result.data?.slicers || [])
    return { success: true }
  }, [projectPath, slicers])

  return {
    // Unified state
    slicers,

    // Backward-compat projections
    slicerDefs,
    slicerInstances,
    loading,
    error,
    
    // Load operations
    loadSlicerDefs,
    loadSlicerInstances,
    loadAll,
    
    // Definition CRUD
    saveDef,
    removeDef,
    saveAllDefs,
    
    // Instance CRUD
    saveInstance,
    removeInstance,
    saveAllInstances,
    
    // Duplicate operations
    duplicatePlacement,
    duplicateIndependent,
    
    // Values
    fetchValues,
    
    // Helpers
    getDefById,
    getInstanceById,
    getInstancesForPage,
    getInstancesForDef,
  }
}

import { useCallback } from 'react'
import { useAppStore, useReportStore, useFilterStore, useModelViewStore, useThemeStore, type Filter } from '@/stores'
import { saveAll as apiSaveAll, updateHierarchies, clearApiDedupCache } from '@/lib/api'

/**
 * Hook to manage Save All functionality
 * Saves all project state: filters, slicers, visuals, security
 */
export function useSaveAll() {
  // Only subscribe to values needed for RENDERING (button state).
  // All other values are read via getState() inside the saveAll callback.
  const projectPath = useAppStore(s => s.projectPath)
  const isDirty = useAppStore(s => s.isDirty)
  const saveInProgress = useAppStore(s => s.saveInProgress)
  const isHierarchiesDirty = useAppStore(s => s.isHierarchiesDirty)
  const isModelViewDirty = useModelViewStore(s => s.isModelViewDirty)
  const isThemeDirty = useThemeStore(s => s.isThemeDirty)

  // Check if we can save (project exists and not already saving)
  const canSave = !!projectPath && !saveInProgress

  // Build the save payload from current state (reads stores imperatively)
  const buildPayload = useCallback(() => {
    const { reportFilters, pageFilters, visualFilters } = useFilterStore.getState()
    const reportVisuals = useReportStore.getState().visuals
    const pages = useReportStore.getState().pages
    const { roles, defaultRole } = useAppStore.getState()
    const { layouts: modelLayouts } = useModelViewStore.getState()
    const { reportingTheme } = useThemeStore.getState()
    // Collect all filters and convert to save format
    const allFilters: Filter[] = [
      ...reportFilters,
      ...Object.values(pageFilters).flat(),
      ...Object.values(visualFilters).flat(),
    ]

    // Filter out interaction filters (not persisted)
    const persistableFilters = allFilters
      .filter(f => f && f.type !== 'interaction')
      .map(f => {
        const columnObj = (typeof f.column === 'object' && f.column !== null)
          ? f.column as { table?: string; column?: string }
          : null
        const table = columnObj?.table || f.table || ''
        const column = columnObj?.column || (typeof f.column === 'string' ? f.column : '')
        return {
          scope: f.type === 'report' ? 'report' : f.type === 'page' ? 'page' : 'visual',
          target: f.type === 'report' ? null : (f.visual_id || null),
          keep: true,
          column: { table, column },
          operator: f.operator || 'in',
          values: Array.isArray(f.values) ? f.values : [],
        }
      })

    // Map visuals to save format
    // Layout: prefer nested v.layout (server format), fall back to top-level fields
    const visualsPayload = (reportVisuals || []).map(v => ({
      id: v.id,
      title: v.title,
      visual_type: v.visual_type,
      page_id: v.page_id,
      layout: v.layout ?? {
        x: v.x ?? 0,
        y: v.y ?? 0,
        w: v.width ?? 400,
        h: v.height ?? 300,
      },
      encodings: v.encodings || {},
      format: v.format || {},
      advanced_plotly_patch: v.advanced_plotly_patch || {},
      interactions: v.interactions || {},
      ...(v.tooltip_page_id ? { tooltip_page_id: v.tooltip_page_id } : {}),
    }))

    return {
      roles: roles || [],
      default_role: defaultRole || null,
      filters: persistableFilters,
      // Slicers are persisted via their own unified endpoints, not Save All.
      // Do NOT send empty slicer data here — it would wipe persisted slicers.
      visuals: visualsPayload,
      pages: (pages || []).map((p, i) => ({
        id: p.id,
        title: p.title,
        order: p.order ?? i + 1,
      })),
      // Model view layouts (only include custom layouts, "all" is built-in)
      model_layouts: modelLayouts.filter(l => l.id !== 'all'),
      // Reporting theme
      reporting_theme: reportingTheme,
    }
  }, [])  // stable — reads stores imperatively at call time

  // Perform the save
  const saveAll = useCallback(async () => {
    if (!canSave) return

    const app = useAppStore.getState()
    app.setSaveInProgress(true)
    app.setSaveError(null)

    try {
      if (app.isHierarchiesDirty) {
        const { error: hierarchiesError } = await updateHierarchies(
          app.hierarchies,
          projectPath ?? undefined
        )
        if (hierarchiesError) {
          app.setSaveError(hierarchiesError)
          return
        }
        app.markHierarchiesClean()
      }

      const payload = buildPayload()
      const { error } = await apiSaveAll(
        payload,
        projectPath ?? undefined,
        app.currentRole ?? undefined
      )

      if (error) {
        app.setSaveError(error)
        console.error('Save failed:', error)
        return
      }

      // Success - mark all state as clean
      app.markClean()
      useModelViewStore.getState().markModelViewClean()
      useThemeStore.getState().markThemeClean()
      // Clear unsaved flags — server now knows about these visuals
      useReportStore.getState().clearUnsavedFlags()
      // Update savedPageIds so changePage knows which pages the server has
      const currentPages = useReportStore.getState().pages
      useReportStore.getState().setSavedPageIds(new Set(currentPages.map(p => p.id)))
      // Invalidate API dedup cache — saved state may differ from cached responses
      clearApiDedupCache()
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Unknown error'
      useAppStore.getState().setSaveError(msg)
      console.error('Save failed:', err)
    } finally {
      useAppStore.getState().setSaveInProgress(false)
    }
  }, [canSave, buildPayload, projectPath])

  return {
    saveAll,
    canSave,
    isDirty: isDirty || isModelViewDirty || isThemeDirty || isHierarchiesDirty,
    saveInProgress,
  }
}

import { useCallback, useState } from 'react'
import { useAppStore, useReportStore, useFilterStore, useModelViewStore, useThemeStore, type Filter, type PlaybookMeta } from '@/stores'
import { getRuntimeState, getSecurityRoles, getRuntimeMeta, getFilters, getReportingTheme, clearApiDedupCache } from '@/lib/api'

/**
 * Hook to load and manage runtime state
 * Fetches project data, pages, visuals, fields, and security roles
 */
export function useRuntimeState() {
  type LoadStateResult = { ok: true } | { ok: false; error: string }
  type BootstrapResult = LoadStateResult & { needsProject?: boolean; prefillProject?: string }

  // ── Store access strategy ──
  // IMPORTANT: We do NOT destructure from useAppStore() / useReportStore()
  // at the top level.  Full-store destructuring subscribes the calling
  // component to EVERY state change in EVERY store field, which caused an
  // N² re-render cascade (React error #185) because App.tsx calls this hook
  // at the root of the component tree.
  //
  // Instead:
  // • Values needed only inside callbacks → accessed via getState() at call time
  // • Reactive values needed as useCallback deps → individual selectors below
  //
  // Setter functions in Zustand are referentially stable, so subscribing to
  // them individually is safe and cheap — but subscribing to the whole store
  // to pull them out is NOT, because it also fires on every data change.

  // Only subscribe to values that are used as reactive deps in callbacks/effects
  const projectPath = useAppStore(s => s.projectPath)
  const currentRole = useAppStore(s => s.currentRole)

  // Get project path from URL query params
  const getProjectFromUrl = useCallback(() => {
    const params = new URLSearchParams(window.location.search)
    return params.get('project') || undefined
  }, [])

  const getPageFromUrl = useCallback(() => {
    const params = new URLSearchParams(window.location.search)
    return params.get('page') || undefined
  }, [])

  const syncProjectToUrl = useCallback((project: string | null) => {
    const url = new URL(window.location.href)
    if (project && project.trim()) {
      url.searchParams.set('project', project.trim())
    } else {
      url.searchParams.delete('project')
    }
    window.history.replaceState(null, '', url.toString())
  }, [])

  // Load runtime state
  const loadState = useCallback(async (options: {
    project?: string
    page?: string
    role?: string
    projectSource?: 'query' | 'env' | 'manual'
    preservePages?: boolean
  } = {}): Promise<LoadStateResult> => {
    // Access store values imperatively — we only need them at call time,
    // not as reactive subscriptions.
    const appState = useAppStore.getState()
    const reportState = useReportStore.getState()
    const currentPageIdNow = reportState.currentPageId

    const resolvedProject = options.project || projectPath || getProjectFromUrl()
    const page = options.page || getPageFromUrl() || currentPageIdNow || undefined
    const role = options.role ?? currentRole ?? undefined

    if (!resolvedProject) {
      const msg = 'Project path is required.'
      appState.setProjectError(msg)
      reportState.setError(msg)
      appState.setProjectLoading(false)
      reportState.setLoading(false)
      return { ok: false, error: msg }
    }

    appState.setProjectLoading(true)
    reportState.setLoading(true)
    reportState.clearRenderStates()

    try {
      const { data, error } = await getRuntimeState({
        project: resolvedProject,
        page,
        role,
      })

      if (error) {
        appState.setProjectError(error)
        reportState.setError(error)
        appState.setProjectLoading(false)
        reportState.setLoading(false)
        return { ok: false, error }
      }

      if (!data) {
        const msg = 'No data received'
        appState.setProjectError(msg)
        reportState.setError(msg)
        appState.setProjectLoading(false)
        reportState.setLoading(false)
        return { ok: false, error: msg }
      }

      // Update project path (fallback to requested project if response omits it)
      const nextProject = (data.project && data.project.trim()) ? data.project : (resolvedProject || '')
      appState.setProjectPath(nextProject || null)
      if (options.projectSource) {
        appState.setProjectSource(options.projectSource)
      }
      if (nextProject) {
        syncProjectToUrl(nextProject)
      }

      // Update pages (skip when preserving in-memory page changes during navigation)
      if (!options.preservePages) {
        reportState.setPages(data.pages)
        // Track which page IDs the server knows about
        reportState.setSavedPageIds(new Set(data.pages.map((p: { id: string }) => p.id)))
      }
      if (data.current_page && data.current_page !== currentPageIdNow) {
        reportState.setCurrentPage(data.current_page)
      }

      // Load filters BEFORE setting visuals so that report/page/visual
      // filters are already in the store when Canvas triggers renderAll().
      // setVisuals() triggers a Canvas re-render via visualIdsKey, and
      // renderAll() reads filters from the store. If filters aren't loaded
      // yet, the first render will be unfiltered (causing a flash).
      try {
        const { data: filterData } = await getFilters(nextProject || resolvedProject || '')
        if (filterData) {
          const store = useFilterStore.getState()

          const reportFiltersLoaded: Filter[] = (filterData.report_filters || []).map((f, i) => ({
            ...f,
            id: f.id || `report_${i}`,
            type: 'report' as const,
          } as Filter))
          store.setReportFilters(reportFiltersLoaded)

          if (filterData.page_filters) {
            Object.entries(filterData.page_filters).forEach(([pageId, filters]) => {
              const pageFiltersWithId: Filter[] = (filters || []).map((f, i) => ({
                ...f,
                id: f.id || `page_${pageId}_${i}`,
                type: 'page' as const,
                visual_id: pageId,
              } as Filter))
              store.setPageFilters(pageId, pageFiltersWithId)
            })
          }

          if (filterData.visual_filters) {
            Object.entries(filterData.visual_filters).forEach(([visualId, filters]) => {
              const visualFiltersWithId: Filter[] = (filters || []).map((f, i) => ({
                ...f,
                id: f.id || `visual_${visualId}_${i}`,
                type: 'visual' as const,
                visual_id: visualId,
              } as Filter))
              store.setVisualFilters(visualId, visualFiltersWithId)
            })
          }

          store.bumpFiltersVersion()
        }
      } catch {
        // Filter load failure is non-fatal; visuals render without filters
      }

      // Update visuals (triggers Canvas renderAll — filters must be loaded above)
      // When navigating between pages (preservePages=true), use setPageVisuals
      // to preserve unsaved (client-created) visuals across all pages.
      // On initial/full load, replace everything.
      if (options.preservePages && data.current_page) {
        reportState.setPageVisuals(data.current_page, data.visuals)
      } else {
        reportState.setVisuals(data.visuals)
      }

      // Convert PBI group visuals to VisualGroup entries.
      // PBI groups are visuals with visual_type='group' and group_properties.
      // Child visuals have parent_group set to the full PBIR visual ID (20 chars).
      // Group visual IDs are pbi_ + first 12 chars of PBIR ID.
      const groupVisuals = (data.visuals || []).filter(
        (v: { visual_type?: string; group_properties?: unknown }) =>
          v.visual_type === 'group' && v.group_properties
      )
      if (groupVisuals.length > 0) {
        const allVisuals = data.visuals || []
        const groups = groupVisuals.map((gv: { id: string; group_properties?: { display_name?: string } }) => {
          // Group visual ID is "pbi_XXXXXXXXXXXX" (12-char suffix)
          // Child parent_group is "XXXXXXXXXXXXXXXXXXXX" (20-char full PBIR ID, starts with the 12-char suffix)
          const groupIdSuffix = gv.id.replace(/^pbi_/, '')
          const childIds = allVisuals
            .filter((v: { parent_group?: string; id: string }) =>
              v.parent_group && v.parent_group.startsWith(groupIdSuffix) && v.id !== gv.id
            )
            .map((v: { id: string }) => v.id)
          return {
            id: gv.id,
            name: gv.group_properties?.display_name || gv.id,
            visualIds: childIds,
          }
        })
        reportState.setVisualGroups(groups)
      }

      // Update model data (fields)
      if (data.fields) {
        appState.setModelData(data.fields.tables, data.fields.measures, data.relationships ?? [])
      }

      if (data.hierarchies) {
        appState.setHierarchies(data.hierarchies)
      } else {
        appState.setHierarchies({})
      }

      // Update explanation playbooks
      if (data.explanations && Array.isArray(data.explanations)) {
        appState.setExplanations(data.explanations as PlaybookMeta[])
      }

      // Update visual types registry
      if (data.visual_types) {
        appState.setVisualTypes(data.visual_types)
      }

      // Update security roles (state endpoint returns role names only)
      // We'll fetch full definitions separately for the security view
      if (data.security) {
        // Convert role names to basic SecurityRole objects
        const basicRoles = data.security.roles.map(name => ({ name }))
        appState.setRoles(basicRoles, data.security.default_role)
      }

      // Load model view layouts
      if (data.model_layouts) {
        const { setLayouts } = useModelViewStore.getState()
        setLayouts(data.model_layouts)
      }

      // Load reporting theme from server (non-blocking)
      getReportingTheme(nextProject || undefined).then((res) => {
        if (res.data) {
          const { setReportingTheme, markThemeClean } = useThemeStore.getState()
          setReportingTheme(res.data)
          markThemeClean()
        }
      }).catch(() => { /* theme load failure is non-fatal */ })

      appState.setProjectLoading(false)
      reportState.setLoading(false)
      return { ok: true }
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Unknown error'
      useAppStore.getState().setProjectError(message)
      useReportStore.getState().setError(message)
      useAppStore.getState().setProjectLoading(false)
      useReportStore.getState().setLoading(false)
      return { ok: false, error: message }
    }
  }, [
    getProjectFromUrl,
    getPageFromUrl,
    currentRole,
    projectPath,
    syncProjectToUrl,
  ])

  const bootstrap = useCallback(async (): Promise<BootstrapResult> => {
    const urlProject = getProjectFromUrl()
    const app = useAppStore.getState()
    const report = useReportStore.getState()

    if (urlProject) {
      app.setProjectSource('query')
      app.setProjectPath(urlProject)
      syncProjectToUrl(urlProject)
      const result = await loadState({ project: urlProject, projectSource: 'query' })
      if (!result.ok) {
        return { ...result, needsProject: true, prefillProject: urlProject }
      }
      return result
    }

    app.setProjectLoading(true)
    report.setLoading(true)

    const { data, error } = await getRuntimeMeta()
    if (error) {
      app.setProjectError(error)
      report.setError(error)
      app.setProjectLoading(false)
      report.setLoading(false)
      return { ok: false, error, needsProject: true }
    }

    // Set server mode from meta response (author or server)
    if (data?.mode) {
      app.setServerMode(data.mode as 'author' | 'server')
    }
    // Set user role (only relevant in server mode)
    if (data?.user_role) {
      useAppStore.getState().setUserRole(data.user_role as 'admin' | 'editor' | 'viewer')
    }

    const active = (data?.active_project || '').trim()
    if (active) {
      const source = data?.active_project_source === 'env' ? 'env' : 'manual'
      app.setProjectSource(source)
      app.setProjectPath(active)
      syncProjectToUrl(active)
      const result = await loadState({ project: active, projectSource: source })
      if (!result.ok) {
        return { ...result, needsProject: true, prefillProject: active }
      }
      return result
    }

    const errs = (data?.errors || []).filter(Boolean)
    const msg = errs.length ? errs.join('\n') : 'Project path is required.'
    app.setProjectError(msg)
    report.setError(msg)
    app.setProjectLoading(false)
    report.setLoading(false)
    return { ok: false, error: msg, needsProject: true }
  }, [
    getProjectFromUrl,
    loadState,
    syncProjectToUrl,
  ])

  // Load security roles separately (for role selector)
  const loadRoles = useCallback(async () => {
    const project = projectPath || getProjectFromUrl()
    
    try {
      const { data, error } = await getSecurityRoles(project)
      if (error || !data) return

      // Normalize roles from backend format to UI format
      const securityRoles = data.roles.map(r => {
        // Normalize RLS from array [{table, filter}] to Record<table, filter>
        let rls: Record<string, string> | undefined = undefined
        if (r.rls && r.rls.length > 0) {
          rls = Object.fromEntries(r.rls.map(item => [item.table, item.filter]))
        }
        
        // Normalize OLS - backend returns {tables, measures, columns}
        // We flatten to Record<table, columns[]> 
        let ols: Record<string, string[]> | undefined = undefined
        if (r.ols && r.ols.columns && Object.keys(r.ols.columns).length > 0) {
          ols = r.ols.columns
        }
        
        return { name: r.name, rls, ols }
      })
      useAppStore.getState().setRoles(securityRoles, data.default_role)
    } catch {
      // Silently fail - roles are optional
    }
  }, [projectPath, getProjectFromUrl])

  // Reload when role changes
  const changeRole = useCallback((role: string | null) => {
    clearApiDedupCache()
    useAppStore.getState().setCurrentRole(role)
    // Clear stale interaction filters before reloading with new role
    useFilterStore.getState().clearInteractionFilters()
    // Reload state with new role
    loadState({ role: role ?? undefined })
  }, [loadState])

  // Change page — lightweight path that skips full loadState.
  // Only fetches visuals + filters in parallel; skips model data, hierarchies,
  // visual types, security roles, theme, layouts, explanations (all project-level
  // data that doesn't change between pages).
  const changePage = useCallback(async (pageId: string) => {
    clearApiDedupCache()
    const reportState = useReportStore.getState()
    // Clear stale interaction filters when switching pages
    useFilterStore.getState().clearInteractionFilters()

    if (!reportState.savedPageIds.has(pageId)) {
      // New unsaved page — just switch locally (no server state to load)
      reportState.setCurrentPage(pageId)
      return
    }

    // Switch page immediately so user sees feedback right away
    reportState.setCurrentPage(pageId)

    const resolvedProject = useAppStore.getState().projectPath || getProjectFromUrl() || ''
    const role = useAppStore.getState().currentRole ?? undefined

    // Fetch state + filters in PARALLEL (loadState does them sequentially)
    const [stateRes, filterRes] = await Promise.all([
      getRuntimeState({ project: resolvedProject, page: pageId, role }),
      getFilters(resolvedProject),
    ])

    if (stateRes.data) {
      // Only update page visuals — skip model data, hierarchies,
      // visual types, security roles, theme, layouts, explanations
      reportState.setPageVisuals(pageId, stateRes.data.visuals)
    }

    // Update filters
    if (filterRes.data) {
      const filterStore = useFilterStore.getState()

      const reportFiltersLoaded: Filter[] = (filterRes.data.report_filters || []).map((f: any, i: number) => ({
        ...f,
        id: f.id || `report_${i}`,
        type: 'report' as const,
      } as Filter))
      filterStore.setReportFilters(reportFiltersLoaded)

      if (filterRes.data.page_filters) {
        Object.entries(filterRes.data.page_filters).forEach(([pid, filters]) => {
          const pageFiltersWithId: Filter[] = ((filters as any[]) || []).map((f: any, i: number) => ({
            ...f,
            id: f.id || `page_${pid}_${i}`,
            type: 'page' as const,
            visual_id: pid,
          } as Filter))
          filterStore.setPageFilters(pid, pageFiltersWithId)
        })
      }

      if (filterRes.data.visual_filters) {
        Object.entries(filterRes.data.visual_filters).forEach(([visualId, filters]) => {
          const visualFiltersWithId: Filter[] = ((filters as any[]) || []).map((f: any, i: number) => ({
            ...f,
            id: f.id || `visual_${visualId}_${i}`,
            type: 'visual' as const,
            visual_id: visualId,
          } as Filter))
          filterStore.setVisualFilters(visualId, visualFiltersWithId)
        })
      }

      filterStore.bumpFiltersVersion()
    }
  }, [getProjectFromUrl])

  // Reload current state (for Reload button)
  const [reloading, setReloading] = useState(false)
  const reload = useCallback(async () => {
    clearApiDedupCache()
    setReloading(true)
    try {
      await loadState({})
    } finally {
      setReloading(false)
    }
  }, [loadState])

  return {
    bootstrap,
    loadState,
    loadRoles,
    changeRole,
    changePage,
    reload,
    reloading,
  }
}

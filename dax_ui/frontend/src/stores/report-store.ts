import { create } from 'zustand'
import type { VisualInfo, PageInfo } from '@/lib/api'

/** A named group of visuals that move/resize together. */
export interface VisualGroup {
  id: string
  name: string
  visualIds: string[]
}

export interface ReportState {
  // Pages
  pages: PageInfo[]
  currentPageId: string | null
  
  // Visuals on current page
  visuals: VisualInfo[]
  
  // Selection (single and multi)
  selectedVisualId: string | null
  selectedVisualIds: string[]
  
  // Tracks which page IDs the server knows about (last loadState or saveAll)
  savedPageIds: Set<string>
  // Runtime-only page navigation stack used by Power BI-style Back buttons.
  pageHistory: string[]

  // Visual visibility (in-memory, save-only persistence)
  // Maps visual_id → visible. Absent means visible (default true).
  visualVisibility: Record<string, boolean>

  // Visual groups (in-memory, save-only persistence)
  visualGroups: VisualGroup[]

  // Visual clipboard (in-memory, save-only persistence)
  visualClipboard: {
    visual: VisualInfo
    mode: 'copy' | 'cut'
  } | null

  // Render state for each visual
  renderStates: Record<string, {
    loading: boolean
    error: string | null
    blocked: boolean
    hiddenRefs?: Array<{ kind: string; table?: string; column?: string; name?: string }>
    data?: unknown
    query?: {
      sql: string
      row_count?: number
      execution_ms?: number
      filters?: unknown[]
      ir?: Record<string, unknown> | string | null
    }
  }>
  
  // Loading
  loading: boolean
  error: string | null
  
  // Actions
  setPages: (pages: PageInfo[]) => void
  setCurrentPage: (pageId: string, options?: { replace?: boolean }) => void
  goBackPage: () => string | null
  addPage: (page: PageInfo) => void
  removePage: (pageId: string) => void
  renamePage: (pageId: string, title: string) => void
  togglePageHidden: (pageId: string) => void
  setPageType: (pageId: string, pageType: string | undefined) => void
  reorderPages: (pages: PageInfo[]) => void
  setVisuals: (visuals: VisualInfo[]) => void
  setPageVisuals: (pageId: string, serverVisuals: VisualInfo[]) => void
  addVisual: (visual: VisualInfo) => void
  removeVisual: (visualId: string) => void
  selectVisual: (visualId: string | null) => void
  toggleSelectVisual: (visualId: string) => void
  addToSelection: (visualId: string) => void
  clearSelection: () => void
  updateVisual: (visualId: string, updates: Partial<VisualInfo>) => void
  setRenderState: (visualId: string, state: Partial<ReportState['renderStates'][string]>) => void
  clearRenderStates: () => void
  setVisualVisibility: (visualId: string, visible: boolean) => void
  toggleVisualVisibility: (visualId: string) => void
  setAllVisualVisibility: (map: Record<string, boolean>) => void
  setSavedPageIds: (ids: Set<string>) => void
  clearUnsavedFlags: () => void
  setLoading: (loading: boolean) => void
  setError: (error: string | null) => void
  reset: () => void
  replaceState: (snapshot: ReportSnapshot) => void

  // Visual group actions
  createGroup: (visualIds: string[], name?: string) => string
  ungroupVisuals: (groupId: string) => void
  renameGroup: (groupId: string, name: string) => void
  getGroupForVisual: (visualId: string) => VisualGroup | null
  getGroupMembers: (visualId: string) => string[]
  setVisualGroups: (groups: VisualGroup[]) => void
  copyVisualToClipboard: (visualId: string) => void
  cutVisualToClipboard: (visualId: string) => void
  pasteVisualFromClipboard: (pageId: string, pos?: { x: number; y: number }) => string | null
  clearVisualClipboard: () => void

  // Edit Interactions mode: when non-null, the canvas shows per-pair target badges
  editInteractionsSourceId: string | null
  setEditInteractionsSourceId: (visualId: string | null) => void
}

export interface ReportSnapshot {
  pages: PageInfo[]
  currentPageId: string | null
  visuals: VisualInfo[]
  selectedVisualId: string | null
}

const initialState = {
  pages: [],
  currentPageId: null,
  pageHistory: [] as string[],
  visuals: [],
  selectedVisualId: null,
  selectedVisualIds: [] as string[],
  savedPageIds: new Set<string>(),
  visualVisibility: {} as Record<string, boolean>,
  visualGroups: [] as VisualGroup[],
  visualClipboard: null as { visual: VisualInfo; mode: 'copy' | 'cut' } | null,
  renderStates: {},
  editInteractionsSourceId: null as string | null,
  loading: false,
  error: null,
}

let groupCounter = 0
function nextGroupId(): string {
  groupCounter += 1
  return `group-${Date.now()}-${groupCounter}`
}

export const useReportStore = create<ReportState>((set, get) => ({
  ...initialState,
  
  // Actions
  setPages: (pages) => set({ 
    pages,
    currentPageId: pages.length > 0 ? pages[0].id : null,
    pageHistory: [],
  }),
  
  setCurrentPage: (currentPageId, options) => set((state) => {
    if (state.currentPageId === currentPageId) return state
    const pageHistory = state.currentPageId && !options?.replace
      ? [...state.pageHistory, state.currentPageId].slice(-25)
      : state.pageHistory
    return {
      currentPageId,
      pageHistory,
      selectedVisualId: null,
      selectedVisualIds: [],
      visualVisibility: {},
      renderStates: {},
    }
  }),

  goBackPage: () => {
    const state = get()
    const previousPageId = state.pageHistory[state.pageHistory.length - 1] ?? null
    if (!previousPageId || previousPageId === state.currentPageId) return null
    set({
      currentPageId: previousPageId,
      pageHistory: state.pageHistory.slice(0, -1),
      selectedVisualId: null,
      selectedVisualIds: [],
      visualVisibility: {},
      renderStates: {},
    })
    return previousPageId
  },

  addPage: (page) => set((state) => ({
    pages: [...state.pages, page],
    currentPageId: page.id,
    pageHistory: state.currentPageId ? [...state.pageHistory, state.currentPageId].slice(-25) : state.pageHistory,
    visuals: [],
    selectedVisualId: null,
    renderStates: {},
  })),

  removePage: (pageId) => set((state) => {
    const remaining = state.pages.filter((p) => p.id !== pageId)
    const needSwitch = state.currentPageId === pageId
    return {
      pages: remaining,
      currentPageId: needSwitch ? (remaining[0]?.id ?? null) : state.currentPageId,
      pageHistory: state.pageHistory.filter((id) => id !== pageId),
      selectedVisualId: needSwitch ? null : state.selectedVisualId,
      renderStates: needSwitch ? {} : state.renderStates,
    }
  }),

  renamePage: (pageId, title) => set((state) => ({
    pages: state.pages.map((p) => p.id === pageId ? { ...p, title } : p),
  })),

  togglePageHidden: (pageId) => set((state) => ({
    pages: state.pages.map((p) => p.id === pageId ? { ...p, hidden: !p.hidden } : p),
  })),

  setPageType: (pageId, pageType) => set((state) => ({
    pages: state.pages.map((p) => p.id === pageId ? { ...p, page_type: pageType } : p),
  })),

  reorderPages: (pages) => set({ pages }),
  
  setVisuals: (visuals) => set({ visuals }),

  setPageVisuals: (pageId, serverVisuals) => set((state) => {
    // Keep unsaved visuals (client-created, not yet saved) from ALL pages,
    // plus server visuals from OTHER pages. Replace only the target page's
    // server-known visuals with the fresh server response.
    const unsaved = state.visuals.filter((v) => (v as any)._unsaved)
    const otherPageVisuals = state.visuals.filter(
      (v) => !(v as any)._unsaved && (v.page_id || '').toLowerCase() !== pageId.toLowerCase()
    )
    return { visuals: [...otherPageVisuals, ...serverVisuals, ...unsaved] }
  }),

  addVisual: (visual) => set((state) => ({
    visuals: [...state.visuals, { ...visual, _unsaved: true } as VisualInfo]
  })),
  
  removeVisual: (visualId) => set((state) => ({
    visuals: state.visuals.filter((v) => v.id !== visualId),
    selectedVisualId: state.selectedVisualId === visualId ? null : state.selectedVisualId,
    selectedVisualIds: state.selectedVisualIds.filter((id) => id !== visualId),
    visualGroups: state.visualGroups
      .map((group) => ({ ...group, visualIds: group.visualIds.filter((id) => id !== visualId) }))
      .filter((group) => group.visualIds.length > 0),
    renderStates: Object.fromEntries(
      Object.entries(state.renderStates).filter(([id]) => id !== visualId)
    )
  })),
  
  selectVisual: (selectedVisualId) => set({ selectedVisualId, selectedVisualIds: selectedVisualId ? [selectedVisualId] : [] }),
  
  toggleSelectVisual: (visualId) => set((state) => {
    const ids = state.selectedVisualIds.includes(visualId)
      ? state.selectedVisualIds.filter(id => id !== visualId)
      : [...state.selectedVisualIds, visualId]
    return {
      selectedVisualIds: ids,
      selectedVisualId: ids.length > 0 ? ids[ids.length - 1] : null,
    }
  }),
  
  addToSelection: (visualId) => set((state) => {
    if (state.selectedVisualIds.includes(visualId)) return state
    const ids = [...state.selectedVisualIds, visualId]
    return { selectedVisualIds: ids, selectedVisualId: visualId }
  }),
  
  clearSelection: () => set({ selectedVisualId: null, selectedVisualIds: [] }),
  
  updateVisual: (visualId, updates) => set((state) => ({
    visuals: state.visuals.map((visual) =>
      visual.id === visualId ? { ...visual, ...updates } : visual
    )
  })),
  
  setRenderState: (visualId, newState) => set((state) => ({
    renderStates: {
      ...state.renderStates,
      [visualId]: {
        ...state.renderStates[visualId],
        ...newState,
      }
    }
  })),
  
  clearRenderStates: () => set({ renderStates: {} }),
  
  setVisualVisibility: (visualId, visible) => set((state) => ({
    visualVisibility: { ...state.visualVisibility, [visualId]: visible }
  })),
  
  toggleVisualVisibility: (visualId) => set((state) => ({
    visualVisibility: {
      ...state.visualVisibility,
      [visualId]: !(state.visualVisibility[visualId] ?? true),
    }
  })),
  
  setAllVisualVisibility: (map) => set({ visualVisibility: map }),
  
  setSavedPageIds: (ids) => set({ savedPageIds: ids }),

  clearUnsavedFlags: () => set((state) => ({
    visuals: state.visuals.map((v) => {
      if ((v as any)._unsaved) {
        const { _unsaved, ...rest } = v as any
        return rest as VisualInfo
      }
      return v
    })
  })),

  setLoading: (loading) => set({ loading }),
  setError: (error) => set({ error, loading: false }),
  reset: () => set(initialState),
  replaceState: (snapshot) => set(() => {
    const nextPageId = snapshot.currentPageId
      && snapshot.pages.some((page) => page.id === snapshot.currentPageId)
      ? snapshot.currentPageId
      : (snapshot.pages[0]?.id ?? null)

    const nextSelected = snapshot.selectedVisualId
      && snapshot.visuals.some((visual) => visual.id === snapshot.selectedVisualId)
      ? snapshot.selectedVisualId
      : null

    return {
      pages: snapshot.pages,
      currentPageId: nextPageId,
      pageHistory: [],
      visuals: snapshot.visuals,
      selectedVisualId: nextSelected,
      visualVisibility: {},
      visualGroups: [],
      renderStates: {},
    }
  }),

  // ── Visual Group Actions ──────────────────────────────────────────

  createGroup: (visualIds, name) => {
    const id = nextGroupId()
    const groupName = name || `Group ${id.slice(-4)}`
    set((state) => {
      // Remove these visuals from any existing groups
      const cleaned = state.visualGroups.map((g) => ({
        ...g,
        visualIds: g.visualIds.filter((vid) => !visualIds.includes(vid)),
      })).filter((g) => g.visualIds.length > 0)

      return {
        visualGroups: [...cleaned, { id, name: groupName, visualIds: [...visualIds] }],
      }
    })
    return id
  },

  ungroupVisuals: (groupId) => set((state) => ({
    visualGroups: state.visualGroups.filter((g) => g.id !== groupId),
  })),

  renameGroup: (groupId, name) => set((state) => ({
    visualGroups: state.visualGroups.map((g) =>
      g.id === groupId ? { ...g, name } : g
    ),
  })),

  getGroupForVisual: (visualId) => {
    return get().visualGroups.find((g) => g.visualIds.includes(visualId)) ?? null
  },

  getGroupMembers: (visualId) => {
    const group = get().visualGroups.find((g) => g.visualIds.includes(visualId))
    return group ? group.visualIds : [visualId]
  },

  setVisualGroups: (groups) => set({ visualGroups: groups }),

  copyVisualToClipboard: (visualId) => {
    const visual = get().visuals.find((v) => v.id === visualId)
    if (!visual) return
    const cloned = JSON.parse(JSON.stringify(visual)) as VisualInfo
    set({ visualClipboard: { visual: cloned, mode: 'copy' } })
  },

  cutVisualToClipboard: (visualId) => {
    const visual = get().visuals.find((v) => v.id === visualId)
    if (!visual) return
    const cloned = JSON.parse(JSON.stringify(visual)) as VisualInfo
    set({ visualClipboard: { visual: cloned, mode: 'cut' } })
    get().removeVisual(visualId)
  },

  pasteVisualFromClipboard: (pageId, pos) => {
    const clipboard = get().visualClipboard
    if (!clipboard) return null

    const source = JSON.parse(JSON.stringify(clipboard.visual)) as VisualInfo
    const srcLayout = source.layout ?? {
      x: source.x ?? 20,
      y: source.y ?? 20,
      w: source.width ?? 400,
      h: source.height ?? 300,
    }

    const newId = `v_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`
    const x = pos?.x ?? (srcLayout.x + 30)
    const y = pos?.y ?? (srcLayout.y + 30)
    const titleBase = source.title || source.id
    const title = clipboard.mode === 'copy' ? `${titleBase} (Copy)` : titleBase

    const pasted: VisualInfo = {
      ...source,
      id: newId,
      title,
      page_id: pageId,
      x,
      y,
      width: srcLayout.w,
      height: srcLayout.h,
      layout: { x, y, w: srcLayout.w, h: srcLayout.h },
    }

    set((state) => ({
      visuals: [...state.visuals, pasted],
      selectedVisualId: pasted.id,
      selectedVisualIds: [pasted.id],
      visualClipboard: clipboard.mode === 'cut' ? null : state.visualClipboard,
    }))

    return pasted.id
  },

  clearVisualClipboard: () => set({ visualClipboard: null }),

  setEditInteractionsSourceId: (visualId) => set({ editInteractionsSourceId: visualId }),
}))

// Re-export types for convenience
export type { VisualInfo, PageInfo }

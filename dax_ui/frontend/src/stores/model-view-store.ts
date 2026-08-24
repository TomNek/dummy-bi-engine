/**
 * Model View Store — manages model diagram layouts (pages).
 *
 * Each layout represents a page in the Model View. The first layout ("All tables")
 * always shows every table with auto-layout. Custom layouts track which tables
 * are visible and their saved positions.
 *
 * Save-only persistence: changes stay in-memory until the user explicitly saves.
 */
import { create } from 'zustand'

// ─── Types ──────────────────────────────────────────────────────────────────

export interface NodePosition {
  x: number
  y: number
}

export interface ModelViewLayout {
  /** Unique identifier. "all" is reserved for the built-in "All tables" page. */
  id: string
  /** User-visible name. */
  name: string
  /**
   * Which tables are visible on this layout.
   * - `null` means ALL tables (used for the "All tables" built-in page).
   * - Otherwise an array of table names.
   */
  visibleTables: string[] | null
  /**
   * Saved node positions keyed by table name.
   * Empty object means positions should be auto-computed.
   */
  nodePositions: Record<string, NodePosition>
}

export interface ModelViewState {
  /** All model view layouts/pages. */
  layouts: ModelViewLayout[]
  /** ID of the currently active layout. */
  activeLayoutId: string
  /** Whether the user has made unsaved changes to layouts. */
  isModelViewDirty: boolean

  // ── Actions ────────────────────────────────
  /** Initialize layouts from backend data (on bootstrap). */
  setLayouts: (layouts: ModelViewLayout[]) => void
  /** Switch to a different layout by ID. */
  setActiveLayout: (id: string) => void
  /** Create a new custom layout (empty — user adds tables via drag). */
  addLayout: (name: string) => void
  /** Rename a layout. */
  renameLayout: (id: string, name: string) => void
  /** Delete a custom layout (cannot delete "All tables"). */
  deleteLayout: (id: string) => void
  /** Add a table to a custom layout. */
  addTableToLayout: (layoutId: string, tableName: string, position: NodePosition) => void
  /** Remove a table from a custom layout. */
  removeTableFromLayout: (layoutId: string, tableName: string) => void
  /** Update a node's position within a layout (triggered by React Flow node drag). */
  updateNodePosition: (layoutId: string, tableName: string, position: NodePosition) => void
  /** Batch-update multiple node positions (e.g., after auto-layout). */
  updateNodePositions: (layoutId: string, positions: Record<string, NodePosition>) => void
  /** Mark layouts as clean (after save). */
  markModelViewClean: () => void
  /** Reset to defaults. */
  resetModelView: () => void
}

// ─── Helpers ────────────────────────────────────────────────────────────────

let _layoutCounter = 0

function generateLayoutId(): string {
  _layoutCounter += 1
  return `layout-${Date.now()}-${_layoutCounter}`
}

const DEFAULT_ALL_LAYOUT: ModelViewLayout = {
  id: 'all',
  name: 'All tables',
  visibleTables: null,
  nodePositions: {},
}

// ─── Store ──────────────────────────────────────────────────────────────────

export const useModelViewStore = create<ModelViewState>()((set) => ({
  layouts: [{ ...DEFAULT_ALL_LAYOUT }],
  activeLayoutId: 'all',
  isModelViewDirty: false,

  setLayouts: (layouts) => {
    // Ensure "All tables" is always present
    const hasAll = layouts.some((l) => l.id === 'all')
    const final = hasAll ? layouts : [{ ...DEFAULT_ALL_LAYOUT }, ...layouts]
    set({ layouts: final, isModelViewDirty: false })
  },

  setActiveLayout: (id) => set({ activeLayoutId: id }),

  addLayout: (name) => {
    const newLayout: ModelViewLayout = {
      id: generateLayoutId(),
      name,
      visibleTables: [],
      nodePositions: {},
    }
    set((state) => ({
      layouts: [...state.layouts, newLayout],
      activeLayoutId: newLayout.id,
      isModelViewDirty: true,
    }))
  },

  renameLayout: (id, name) =>
    set((state) => ({
      layouts: state.layouts.map((l) => (l.id === id ? { ...l, name } : l)),
      isModelViewDirty: true,
    })),

  deleteLayout: (id) => {
    if (id === 'all') return // Cannot delete the built-in layout
    set((state) => {
      const filtered = state.layouts.filter((l) => l.id !== id)
      return {
        layouts: filtered,
        activeLayoutId: state.activeLayoutId === id ? 'all' : state.activeLayoutId,
        isModelViewDirty: true,
      }
    })
  },

  addTableToLayout: (layoutId, tableName, position) =>
    set((state) => ({
      layouts: state.layouts.map((l) => {
        if (l.id !== layoutId || l.visibleTables === null) return l
        if (l.visibleTables.includes(tableName)) return l
        return {
          ...l,
          visibleTables: [...l.visibleTables, tableName],
          nodePositions: { ...l.nodePositions, [tableName]: position },
        }
      }),
      isModelViewDirty: true,
    })),

  removeTableFromLayout: (layoutId, tableName) =>
    set((state) => ({
      layouts: state.layouts.map((l) => {
        if (l.id !== layoutId || l.visibleTables === null) return l
        const { [tableName]: _, ...restPositions } = l.nodePositions
        return {
          ...l,
          visibleTables: l.visibleTables.filter((t) => t !== tableName),
          nodePositions: restPositions,
        }
      }),
      isModelViewDirty: true,
    })),

  updateNodePosition: (layoutId, tableName, position) =>
    set((state) => ({
      layouts: state.layouts.map((l) =>
        l.id === layoutId
          ? { ...l, nodePositions: { ...l.nodePositions, [tableName]: position } }
          : l
      ),
      isModelViewDirty: true,
    })),

  updateNodePositions: (layoutId, positions) =>
    set((state) => ({
      layouts: state.layouts.map((l) =>
        l.id === layoutId
          ? { ...l, nodePositions: { ...l.nodePositions, ...positions } }
          : l
      ),
      isModelViewDirty: true,
    })),

  markModelViewClean: () => set({ isModelViewDirty: false }),

  resetModelView: () =>
    set({
      layouts: [{ ...DEFAULT_ALL_LAYOUT }],
      activeLayoutId: 'all',
      isModelViewDirty: false,
    }),
}))

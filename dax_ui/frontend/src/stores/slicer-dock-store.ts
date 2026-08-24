import { create } from 'zustand'
import { persist } from 'zustand/middleware'

/** Generate a short random ID. */
function shortId(): string {
  return Math.random().toString(36).slice(2, 10)
}

export type DockPosition = 'left' | 'right' | 'top' | 'bottom'

export interface SlicerGroup {
  id: string
  name: string
  collapsed: boolean
}

export interface SlicerDockState {
  /** Whether each dock panel is expanded (true) or collapsed (false). */
  dockOpen: Record<DockPosition, boolean>

  /** Slicer instance ID → dock position. If absent, slicer stays on canvas. */
  dockAssignments: Record<string, DockPosition>

  /** Set of slicer instance IDs that are individually collapsed in the dock. */
  collapsedSlicers: Record<string, boolean>

  /** User-defined slicer groups (within docks). */
  groups: SlicerGroup[]

  /** Slicer instance ID → group ID. If absent, slicer is ungrouped. */
  groupAssignments: Record<string, string>

  // --- Actions ---

  /** Toggle a dock open/collapsed. */
  toggleDock: (position: DockPosition) => void
  setDockOpen: (position: DockPosition, open: boolean) => void

  /** Assign a slicer to a dock (removes from canvas). */
  assignToDock: (slicerId: string, position: DockPosition) => void
  /** Move slicer back to canvas (remove from dock). */
  unassignFromDock: (slicerId: string) => void
  /** Move slicer to a different dock. */
  moveToDock: (slicerId: string, position: DockPosition) => void

  /** Toggle individual slicer collapsed/expanded in the dock. */
  toggleSlicerCollapsed: (slicerId: string) => void

  /** Create a new group. Returns its ID. */
  createGroup: (name: string) => string
  /** Rename a group. */
  renameGroup: (groupId: string, name: string) => void
  /** Delete a group (ungroups its slicers). */
  deleteGroup: (groupId: string) => void
  /** Toggle group collapsed/expanded. */
  toggleGroupCollapsed: (groupId: string) => void
  /** Assign a slicer to a group. */
  assignToGroup: (slicerId: string, groupId: string) => void
  /** Remove slicer from its group. */
  unassignFromGroup: (slicerId: string) => void

  /** Collapse all slicers in a specific dock. */
  collapseAllSlicers: (position: DockPosition, slicerIds: string[]) => void
  /** Expand all slicers in a specific dock. */
  expandAllSlicers: (slicerIds: string[]) => void

  /** Get the dock position for a slicer (or undefined if on canvas). */
  getDock: (slicerId: string) => DockPosition | undefined
}

export const useSlicerDockStore = create<SlicerDockState>()(
  persist(
    (set, get) => ({
      dockOpen: { left: false, right: false, top: false, bottom: false },
      dockAssignments: {},
      collapsedSlicers: {},
      groups: [],
      groupAssignments: {},

      toggleDock: (position) =>
        set(s => ({
          dockOpen: { ...s.dockOpen, [position]: !s.dockOpen[position] },
        })),

      setDockOpen: (position, open) =>
        set(s => ({
          dockOpen: { ...s.dockOpen, [position]: open },
        })),

      assignToDock: (slicerId, position) =>
        set(s => ({
          dockAssignments: { ...s.dockAssignments, [slicerId]: position },
          dockOpen: { ...s.dockOpen, [position]: true }, // auto-open the dock
        })),

      unassignFromDock: (slicerId) =>
        set(s => {
          const { [slicerId]: _, ...rest } = s.dockAssignments
          const { [slicerId]: __, ...restCollapsed } = s.collapsedSlicers
          const { [slicerId]: ___, ...restGroups } = s.groupAssignments
          return { dockAssignments: rest, collapsedSlicers: restCollapsed, groupAssignments: restGroups }
        }),

      moveToDock: (slicerId, position) =>
        set(s => ({
          dockAssignments: { ...s.dockAssignments, [slicerId]: position },
          dockOpen: { ...s.dockOpen, [position]: true },
        })),

      toggleSlicerCollapsed: (slicerId) =>
        set(s => ({
          collapsedSlicers: {
            ...s.collapsedSlicers,
            [slicerId]: !(s.collapsedSlicers[slicerId] ?? false),
          },
        })),

      createGroup: (name) => {
        const id = shortId()
        set(s => ({
          groups: [...s.groups, { id, name, collapsed: false }],
        }))
        return id
      },

      renameGroup: (groupId, name) =>
        set(s => ({
          groups: s.groups.map(g => (g.id === groupId ? { ...g, name } : g)),
        })),

      deleteGroup: (groupId) =>
        set(s => {
          // Ungroup all slicers in this group
          const newAssign = { ...s.groupAssignments }
          for (const [sid, gid] of Object.entries(newAssign)) {
            if (gid === groupId) delete newAssign[sid]
          }
          return {
            groups: s.groups.filter(g => g.id !== groupId),
            groupAssignments: newAssign,
          }
        }),

      toggleGroupCollapsed: (groupId) =>
        set(s => ({
          groups: s.groups.map(g =>
            g.id === groupId ? { ...g, collapsed: !g.collapsed } : g
          ),
        })),

      assignToGroup: (slicerId, groupId) =>
        set(s => ({
          groupAssignments: { ...s.groupAssignments, [slicerId]: groupId },
        })),

      unassignFromGroup: (slicerId) =>
        set(s => {
          const { [slicerId]: _, ...rest } = s.groupAssignments
          return { groupAssignments: rest }
        }),

      collapseAllSlicers: (_position, slicerIds) =>
        set(s => {
          const updated = { ...s.collapsedSlicers }
          for (const id of slicerIds) updated[id] = true
          return { collapsedSlicers: updated }
        }),

      expandAllSlicers: (slicerIds) =>
        set(s => {
          const updated = { ...s.collapsedSlicers }
          for (const id of slicerIds) updated[id] = false
          return { collapsedSlicers: updated }
        }),

      getDock: (slicerId) => get().dockAssignments[slicerId],
    }),
    {
      name: 'dax-slicer-dock-store',
      version: 1,
      migrate: (persisted: unknown, version: number) => {
        // v0 → v1: unified slicer model changed instance IDs from UUIDs
        // to synthetic si_{slicer_id}_{page_id}. Clear stale assignments.
        if (version === 0) {
          const state = persisted as Record<string, unknown>
          return {
            ...state,
            dockAssignments: {},
            collapsedSlicers: {},
            groupAssignments: {},
            // keep groups and dockOpen — they don't reference instance IDs
          }
        }
        return persisted as SlicerDockState
      },
    }
  )
)

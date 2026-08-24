import { useEffect, useMemo, useState, useCallback } from 'react'
import {
  ChevronDown,
  ChevronRight,
  ChevronLeft,
  ChevronUp,
  ChevronsDownUp,
  ChevronsUpDown,
  FolderPlus,
  Grip,
  X,
  XCircle,
  Eraser,
  Pencil,
  Check,
  Trash2,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { ScrollArea } from '@/components/ui/scroll-area'
import {
  ContextMenu,
  ContextMenuTrigger,
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuSeparator,
  ContextMenuSub,
  ContextMenuSubTrigger,
  ContextMenuSubContent,
} from '@/components/ui/context-menu'
import { useSlicerDockStore, type DockPosition } from '@/stores'
import { useSlicers } from '@/hooks'
import { useFilters } from '@/hooks'
import { useSelectionStateSync } from '@/hooks/useSelectionStateSync'
import { useReportStore } from '@/stores'
import { SlicerVisual } from '@/components/slicers'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const DOCK_LABELS: Record<DockPosition, string> = {
  left: 'Left',
  right: 'Right',
  top: 'Top',
  bottom: 'Bottom',
}

const COLLAPSE_ICONS: Record<DockPosition, { open: typeof ChevronLeft; closed: typeof ChevronRight }> = {
  left: { open: ChevronLeft, closed: ChevronRight },
  right: { open: ChevronRight, closed: ChevronLeft },
  top: { open: ChevronUp, closed: ChevronDown },
  bottom: { open: ChevronDown, closed: ChevronUp },
}

/** Is this a horizontal (left/right) or vertical (top/bottom) dock? */
function isHorizontal(pos: DockPosition) {
  return pos === 'left' || pos === 'right'
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

interface SlicerDockPanelProps {
  position: DockPosition
}

export function SlicerDockPanel({ position }: SlicerDockPanelProps) {
  const open = useSlicerDockStore(s => s.dockOpen[position])
  const toggleDock = useSlicerDockStore(s => s.toggleDock)
  const dockAssignments = useSlicerDockStore(s => s.dockAssignments)
  const collapsedSlicers = useSlicerDockStore(s => s.collapsedSlicers)
  const toggleSlicerCollapsed = useSlicerDockStore(s => s.toggleSlicerCollapsed)
  const unassignFromDock = useSlicerDockStore(s => s.unassignFromDock)
  const moveToDock = useSlicerDockStore(s => s.moveToDock)
  const groups = useSlicerDockStore(s => s.groups)
  const groupAssignments = useSlicerDockStore(s => s.groupAssignments)
  const createGroup = useSlicerDockStore(s => s.createGroup)
  const renameGroup = useSlicerDockStore(s => s.renameGroup)
  const deleteGroup = useSlicerDockStore(s => s.deleteGroup)
  const toggleGroupCollapsed = useSlicerDockStore(s => s.toggleGroupCollapsed)
  const assignToGroup = useSlicerDockStore(s => s.assignToGroup)
  const unassignFromGroup = useSlicerDockStore(s => s.unassignFromGroup)
  const collapseAllSlicers = useSlicerDockStore(s => s.collapseAllSlicers)
  const expandAllSlicers = useSlicerDockStore(s => s.expandAllSlicers)

  const { slicerDefs, slicerInstances, loadAll } = useSlicers()
  const { clearSlicerFilters } = useFilters()
  const currentPageId = useReportStore(s => s.currentPageId)

  // Bumped to force SlicerVisual re-mount and reset selections
  const [clearVersion, setClearVersion] = useState(0)

  // Phase 23D: Sync selection state when filters change
  useSelectionStateSync(slicerDefs, currentPageId ?? undefined)

  // Load slicer data when the panel mounts
  useEffect(() => {
    loadAll()
  }, [loadAll])

  // Refresh slicer data when a new slicer is created elsewhere
  useEffect(() => {
    const handler = () => { loadAll() }
    window.addEventListener('slicers-changed', handler)
    return () => window.removeEventListener('slicers-changed', handler)
  }, [loadAll])

  // Editing state for group rename
  const [editingGroupId, setEditingGroupId] = useState<string | null>(null)
  const [editingGroupName, setEditingGroupName] = useState('')

  // Slicers assigned to this dock on the current page
  const dockedSlicers = useMemo(() => {
    return slicerInstances.filter(inst => {
      const assigned = dockAssignments[inst.id]
      if (assigned !== position) return false
      return inst.page_id?.toLowerCase() === (currentPageId || '').toLowerCase()
    })
  }, [slicerInstances, dockAssignments, position, currentPageId])

  const dockedSlicerIds = useMemo(() => dockedSlicers.map(inst => inst.id), [dockedSlicers])

  // Organize slicers by group (must be called unconditionally — Rules of Hooks)
  const groupedSlicers = useMemo(() => {
    const byGroup: Record<string, typeof dockedSlicers> = {}
    const ungrouped: typeof dockedSlicers = []

    for (const inst of dockedSlicers) {
      const gid = groupAssignments[inst.id]
      if (gid && groups.find(g => g.id === gid)) {
        if (!byGroup[gid]) byGroup[gid] = []
        byGroup[gid].push(inst)
      } else {
        ungrouped.push(inst)
      }
    }

    return { byGroup, ungrouped }
  }, [dockedSlicers, groupAssignments, groups])

  const handleClearAllSelections = useCallback(() => {
    clearSlicerFilters()
    setClearVersion(v => v + 1)
  }, [clearSlicerFilters])

  const handleCreateGroup = useCallback(() => {
    const id = createGroup('New Group')
    setEditingGroupId(id)
    setEditingGroupName('New Group')
  }, [createGroup])

  const handleSaveGroupName = useCallback((groupId: string) => {
    if (editingGroupName.trim()) {
      renameGroup(groupId, editingGroupName.trim())
    }
    setEditingGroupId(null)
  }, [editingGroupName, renameGroup])

  // No slicers docked here — don't render (after all hooks)
  if (dockedSlicers.length === 0) return null

  const horizontal = isHorizontal(position)
  const CollapseOpenIcon = COLLAPSE_ICONS[position].open
  const CollapseClosedIcon = COLLAPSE_ICONS[position].closed

  const otherDocks = (['left', 'right', 'top', 'bottom'] as DockPosition[]).filter(p => p !== position)

  // ---- Render a single slicer item ----
  const renderSlicer = (inst: typeof dockedSlicers[number]) => {
    const def = slicerDefs.find(d => d.id?.toLowerCase() === inst.def_id?.toLowerCase())
    if (!def) return null
    const isCollapsed = collapsedSlicers[inst.id] ?? false
    const defName = def.name || def.column?.column || inst.def_id

    return (
      <ContextMenu key={inst.id}>
        <ContextMenuTrigger asChild>
          <div
            className={cn(
              'border rounded-lg bg-background',
              horizontal ? 'w-full' : 'min-w-[200px] max-w-[300px] shrink-0',
            )}
            data-testid={`dock-slicer-${inst.id}`}
          >
            {/* Slicer header (click to collapse) */}
            <button
              className="flex items-center gap-1.5 w-full px-2 py-1 text-xs font-medium hover:bg-accent/50 rounded-t-lg"
              onClick={() => toggleSlicerCollapsed(inst.id)}
            >
              <Grip className="h-3 w-3 text-muted-foreground/50 shrink-0" />
              {isCollapsed ? (
                <ChevronRight className="h-3 w-3 text-muted-foreground shrink-0" />
              ) : (
                <ChevronDown className="h-3 w-3 text-muted-foreground shrink-0" />
              )}
              <span className="truncate">{defName}</span>
            </button>
            {/* Slicer content */}
            {!isCollapsed && (
              <div className="p-1">
                <SlicerVisual key={`${inst.id}_cv${clearVersion}`} instance={inst} def={def} />
              </div>
            )}
          </div>
        </ContextMenuTrigger>
        <ContextMenuContent className="w-48">
          <ContextMenuItem onClick={() => unassignFromDock(inst.id)}>
            <X className="h-3.5 w-3.5 mr-2" />
            Move to Canvas
          </ContextMenuItem>
          <ContextMenuSub>
            <ContextMenuSubTrigger>Move to Dock</ContextMenuSubTrigger>
            <ContextMenuSubContent>
              {otherDocks.map(d => (
                <ContextMenuItem key={d} onClick={() => moveToDock(inst.id, d)}>
                  {DOCK_LABELS[d]}
                </ContextMenuItem>
              ))}
            </ContextMenuSubContent>
          </ContextMenuSub>
          <ContextMenuSeparator />
          {groups.length > 0 && (
            <ContextMenuSub>
              <ContextMenuSubTrigger>Assign to Group</ContextMenuSubTrigger>
              <ContextMenuSubContent>
                {groups.map(g => (
                  <ContextMenuItem key={g.id} onClick={() => assignToGroup(inst.id, g.id)}>
                    {g.name}
                  </ContextMenuItem>
                ))}
                <ContextMenuSeparator />
                <ContextMenuItem onClick={() => unassignFromGroup(inst.id)}>
                  Ungrouped
                </ContextMenuItem>
              </ContextMenuSubContent>
            </ContextMenuSub>
          )}
          <ContextMenuItem onClick={() => toggleSlicerCollapsed(inst.id)}>
            {isCollapsed ? 'Expand' : 'Collapse'}
          </ContextMenuItem>
        </ContextMenuContent>
      </ContextMenu>
    )
  }

  // ---- Render a group section ----
  const renderGroup = (group: typeof groups[number]) => {
    const members = groupedSlicers.byGroup[group.id] || []
    const isEditing = editingGroupId === group.id

    return (
      <div key={group.id} className="border rounded-lg group" data-testid={`dock-group-${group.id}`}>
        <div className="flex items-center gap-1 px-2 py-1 bg-muted/30 rounded-t-lg">
          <button
            className="flex items-center gap-1 flex-1 text-xs font-semibold hover:text-foreground"
            onClick={() => toggleGroupCollapsed(group.id)}
          >
            {group.collapsed ? (
              <ChevronRight className="h-3 w-3 shrink-0" />
            ) : (
              <ChevronDown className="h-3 w-3 shrink-0" />
            )}
            {isEditing ? (
              <Input
                autoFocus
                className="h-5 text-xs px-1 py-0 w-28"
                value={editingGroupName}
                onChange={e => setEditingGroupName(e.target.value)}
                onClick={e => e.stopPropagation()}
                onKeyDown={e => {
                  if (e.key === 'Enter') handleSaveGroupName(group.id)
                  if (e.key === 'Escape') setEditingGroupId(null)
                }}
              />
            ) : (
              <span className="truncate">{group.name}</span>
            )}
          </button>
          {isEditing ? (
            <Button variant="ghost" size="sm" className="h-5 w-5 p-0" onClick={() => handleSaveGroupName(group.id)}>
              <Check className="h-3 w-3" />
            </Button>
          ) : (
            <>
              <Button
                variant="ghost"
                size="sm"
                className="h-5 w-5 p-0 opacity-0 group-hover:opacity-100"
                onClick={() => { setEditingGroupId(group.id); setEditingGroupName(group.name) }}
                title="Rename group"
              >
                <Pencil className="h-3 w-3" />
              </Button>
              <Button
                variant="ghost"
                size="sm"
                className="h-5 w-5 p-0 opacity-0 group-hover:opacity-100 text-destructive"
                onClick={() => deleteGroup(group.id)}
                title="Delete group"
              >
                <Trash2 className="h-3 w-3" />
              </Button>
            </>
          )}
        </div>
        {!group.collapsed && (
          <div className={cn(
            'p-1 gap-1',
            horizontal ? 'flex flex-col' : 'flex flex-row flex-wrap',
          )}>
            {members.length === 0 ? (
              <div className="text-[10px] text-muted-foreground text-center py-2 px-1">
                Right-click a slicer → Assign to Group
              </div>
            ) : (
              members.map(renderSlicer)
            )}
          </div>
        )}
      </div>
    )
  }

  // ---- Main render ----
  return (
    <div
      className={cn(
        'flex border-muted shrink-0 bg-background transition-all',
        horizontal
          ? 'flex-col border-x w-[240px]'
          : 'flex-row border-y h-fit max-h-[240px]',
        !open && (horizontal ? 'w-8' : 'h-8'),
      )}
      data-testid={`slicer-dock-${position}`}
    >
      {/* Collapse toggle strip */}
      {!open && (
        <button
          className={cn(
            'flex items-center justify-center gap-1 hover:bg-accent/50 transition-colors',
            horizontal ? 'h-full w-8 flex-col' : 'w-full h-8 flex-row',
          )}
          onClick={() => toggleDock(position)}
          title={`Expand ${DOCK_LABELS[position]} slicer dock`}
          data-testid={`dock-expand-${position}`}
        >
          <CollapseClosedIcon className="h-3.5 w-3.5 text-muted-foreground" />
          <span className={cn(
            'text-[9px] text-muted-foreground tracking-widest',
            horizontal && '[writing-mode:vertical-lr]',
          )}>
            SLICERS ({dockedSlicers.length})
          </span>
        </button>
      )}

      {/* Expanded dock content */}
      {open && (
        <div className={cn(
          'flex flex-col h-full',
          horizontal ? 'w-[240px]' : 'w-full',
        )}>
          {/* Dock header */}
          <div className="flex items-center justify-between px-2 py-1 border-b shrink-0">
            <span className="text-[10px] font-semibold tracking-wide">
              {DOCK_LABELS[position]} Slicers
            </span>
            <div className="flex items-center gap-0.5">
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-5 w-5 p-0"
                  onClick={() => expandAllSlicers(dockedSlicerIds)}
                  title="Expand all slicers"
                  data-testid={`dock-expand-all-${position}`}
                >
                  <ChevronsUpDown className="h-3 w-3" />
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-5 w-5 p-0"
                  onClick={() => collapseAllSlicers(position, dockedSlicerIds)}
                  title="Collapse all slicers"
                  data-testid={`dock-collapse-all-${position}`}
                >
                  <ChevronsDownUp className="h-3 w-3" />
                </Button>
              <Button
                variant="ghost"
                size="sm"
                className="h-5 w-5 p-0"
                onClick={handleCreateGroup}
                title="Create slicer group"
                data-testid={`dock-create-group-${position}`}
              >
                <FolderPlus className="h-3 w-3" />
              </Button>
              <Button
                variant="ghost"
                size="sm"
                className="h-5 w-5 p-0 text-destructive hover:text-destructive"
                onClick={() => dockedSlicerIds.forEach(id => unassignFromDock(id))}
                title="Clear all slicers from this dock"
                data-testid={`dock-clear-all-${position}`}
              >
                <XCircle className="h-3 w-3" />
              </Button>
              <Button
                variant="ghost"
                size="sm"
                className="h-5 w-5 p-0"
                onClick={handleClearAllSelections}
                title="Clear all slicer selections"
                data-testid={`dock-clear-selections-${position}`}
              >
                <Eraser className="h-3 w-3" />
              </Button>
              <Button
                variant="ghost"
                size="sm"
                className="h-5 w-5 p-0"
                onClick={() => toggleDock(position)}
                title="Collapse dock"
                data-testid={`dock-collapse-${position}`}
              >
                <CollapseOpenIcon className="h-3.5 w-3.5" />
              </Button>
            </div>
          </div>

          {/* Scrollable slicer area */}
          <ScrollArea className={cn(
            'flex-1 min-h-0',
            !horizontal && 'overflow-x-auto',
          )}>
            <div className={cn(
              'p-1.5 gap-1.5',
              horizontal ? 'flex flex-col' : 'flex flex-row flex-wrap',
            )}>
              {/* Grouped slicers */}
              {groups.map(renderGroup)}

              {/* Ungrouped slicers */}
              {groupedSlicers.ungrouped.map(renderSlicer)}
            </div>
          </ScrollArea>
        </div>
      )}
    </div>
  )
}

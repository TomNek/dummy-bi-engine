import { useCallback, useEffect, useMemo, useState } from 'react'
import { Eye, EyeOff, BarChart3, SlidersHorizontal, PanelLeft, PanelRight, PanelTop, PanelBottom, Undo2, Group, Ungroup, ChevronDown, ChevronRight, Trash2 } from 'lucide-react'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
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
import { useReportStore, useSlicerDockStore, useAppStore, type DockPosition, type VisualGroup } from '@/stores'
import { useSlicers } from '@/hooks'

const VISUAL_TYPE_LABELS: Record<string, string> = {
  matrix: 'Matrix',
  table: 'Table',
  card: 'Card',
  chart: 'Chart',
  bar: 'Bar Chart',
  line: 'Line Chart',
  scatter: 'Scatter',
  slicer: 'Slicer',
}

/** Unified item shown in the selection pane (visual or slicer instance). */
interface SelectionItem {
  id: string
  kind: 'visual' | 'slicer'
  label: string
  typeLabel: string
}

interface SelectionPaneProps {
  className?: string
}

export function SelectionPane({ className }: SelectionPaneProps) {
  const allVisuals = useReportStore(s => s.visuals)
  const currentPageId = useReportStore(s => s.currentPageId)

  // Filter visuals to only those belonging to the current page
  const visuals = useMemo(() => {
    if (!currentPageId) return allVisuals
    return allVisuals.filter(v => (v.page_id || '').toLowerCase() === currentPageId.toLowerCase())
  }, [allVisuals, currentPageId])
  const visualVisibility = useReportStore(s => s.visualVisibility)
  const toggleVisualVisibility = useReportStore(s => s.toggleVisualVisibility)
  const setAllVisualVisibility = useReportStore(s => s.setAllVisualVisibility)
  const selectedVisualIds = useReportStore(s => s.selectedVisualIds)
  const selectVisual = useReportStore(s => s.selectVisual)
  const toggleSelectVisual = useReportStore(s => s.toggleSelectVisual)
  const removeVisual = useReportStore(s => s.removeVisual)
  const addToSelection = useReportStore(s => s.addToSelection)
  const visualGroups = useReportStore(s => s.visualGroups)
  const createGroup = useReportStore(s => s.createGroup)
  const ungroupVisuals = useReportStore(s => s.ungroupVisuals)
  const renameGroup = useReportStore(s => s.renameGroup)
  const setDirty = useAppStore(s => s.setDirty)

  const { slicerDefs, slicerInstances, loadAll } = useSlicers()

  const dockAssignments = useSlicerDockStore(s => s.dockAssignments)
  const assignToDock = useSlicerDockStore(s => s.assignToDock)
  const unassignFromDock = useSlicerDockStore(s => s.unassignFromDock)

  // Load slicer data when the pane mounts
  useEffect(() => {
    loadAll()
  }, [loadAll])

  // Slicer instances on the current page
  const pageSlicerInstances = useMemo(() => {
    return slicerInstances.filter(
      inst => inst.page_id?.toLowerCase() === (currentPageId || '').toLowerCase()
    )
  }, [slicerInstances, currentPageId])

  // Build unified list: visuals first, then slicers
  const items: SelectionItem[] = useMemo(() => {
    const out: SelectionItem[] = []
    for (const v of visuals) {
      const typeLabel = VISUAL_TYPE_LABELS[v.visual_type?.toLowerCase() || ''] || v.visual_type || 'Visual'
      out.push({
        id: v.id,
        kind: 'visual',
        label: v.title || `${typeLabel} (${v.id.slice(0, 8)})`,
        typeLabel,
      })
    }
    for (const si of pageSlicerInstances) {
      const def = slicerDefs.find(d => d.id?.toLowerCase() === si.def_id?.toLowerCase())
      const defName = def?.name || def?.table || si.def_id
      out.push({
        id: si.id,
        kind: 'slicer',
        label: defName,
        typeLabel: 'Slicer',
      })
    }
    return out
  }, [visuals, pageSlicerInstances, slicerDefs])

  const isVisible = useCallback((itemId: string) => {
    return visualVisibility[itemId] ?? true
  }, [visualVisibility])

  const showAll = useCallback(() => {
    const map: Record<string, boolean> = {}
    for (const item of items) {
      map[item.id] = true
    }
    setAllVisualVisibility(map)
  }, [items, setAllVisualVisibility])

  const hideAll = useCallback(() => {
    const map: Record<string, boolean> = {}
    for (const item of items) {
      map[item.id] = false
    }
    setAllVisualVisibility(map)
  }, [items, setAllVisualVisibility])

  const hiddenCount = items.filter(item => !isVisible(item.id)).length

  // Track collapsed groups
  const [collapsedGroups, setCollapsedGroups] = useState<Set<string>>(new Set())

  const toggleGroupCollapse = useCallback((groupId: string) => {
    setCollapsedGroups((prev) => {
      const next = new Set(prev)
      if (next.has(groupId)) next.delete(groupId)
      else next.add(groupId)
      return next
    })
  }, [])

  // Build a map from item ID to the group it belongs to
  const itemGroupMap = useMemo(() => {
    const map = new Map<string, VisualGroup>()
    for (const g of visualGroups) {
      for (const vid of g.visualIds) {
        map.set(vid, g)
      }
    }
    return map
  }, [visualGroups])

  // Items NOT in any group
  const ungroupedItems = useMemo(() => {
    return items.filter((item) => !itemGroupMap.has(item.id))
  }, [items, itemGroupMap])

  const handleGroupSelected = useCallback(() => {
    if (selectedVisualIds.length < 2) return
    createGroup(selectedVisualIds)
  }, [selectedVisualIds, createGroup])

  const canGroupSelected = selectedVisualIds.length >= 2

  // Track last clicked item for Shift+Click range selection
  const [lastClickedId, setLastClickedId] = useState<string | null>(null)

  const handleItemClick = useCallback((e: React.MouseEvent, itemId: string) => {
    if (e.shiftKey && lastClickedId) {
      // Shift+Click: range selection from last clicked to current
      const lastIdx = items.findIndex(i => i.id === lastClickedId)
      const curIdx = items.findIndex(i => i.id === itemId)
      if (lastIdx >= 0 && curIdx >= 0) {
        const start = Math.min(lastIdx, curIdx)
        const end = Math.max(lastIdx, curIdx)
        for (let i = start; i <= end; i++) {
          if (!selectedVisualIds.includes(items[i].id)) {
            addToSelection(items[i].id)
          }
        }
      }
    } else if (e.ctrlKey || e.metaKey) {
      // Ctrl+Click: toggle individual item in multi-select
      toggleSelectVisual(itemId)
    } else {
      // Normal click: single-select (clears others)
      selectVisual(itemId)
    }
    setLastClickedId(itemId)
  }, [selectVisual, toggleSelectVisual, addToSelection, lastClickedId, items, selectedVisualIds])

  const isSelected = useCallback((itemId: string) => {
    return selectedVisualIds.includes(itemId)
  }, [selectedVisualIds])

  // Shared item renderer for both grouped and ungrouped items
  const renderItem = useCallback((item: SelectionItem) => {
    const visible = isVisible(item.id)
    const selected = isSelected(item.id)
    const isSlicer = item.kind === 'slicer'
    const itemGroup = itemGroupMap.get(item.id)

    return (
      <ContextMenu key={item.id}>
        <ContextMenuTrigger asChild>
          <div
            className={cn(
              'group flex items-center gap-2 px-2 py-1.5 rounded-md cursor-pointer',
              'hover:bg-accent/50',
              selected && 'bg-accent ring-1 ring-primary/30',
              !visible && 'opacity-50',
            )}
            onClick={(e) => handleItemClick(e, item.id)}
            data-testid={`selection-item-${item.id}`}
          >
            {/* Clickable visibility toggle */}
            <button
              className="shrink-0 p-0.5 rounded hover:bg-accent transition-colors"
              onClick={(e) => {
                e.stopPropagation()
                toggleVisualVisibility(item.id)
              }}
              title={visible ? 'Hide' : 'Show'}
              data-testid={`selection-toggle-${item.id}`}
            >
              {visible ? (
                <Eye className="h-3 w-3 text-muted-foreground/60" />
              ) : (
                <EyeOff className="h-3 w-3 text-muted-foreground/40" />
              )}
            </button>

            {/* Type icon */}
            {isSlicer ? (
              <SlidersHorizontal className="h-3 w-3 text-muted-foreground shrink-0" />
            ) : (
              <BarChart3 className="h-3 w-3 text-muted-foreground shrink-0" />
            )}

            {/* Type label */}
            <span className="text-[10px] text-muted-foreground w-12 truncate shrink-0">
              {item.typeLabel}
            </span>

            {/* Name */}
            <span className="flex-1 text-xs truncate">
              {item.label}
            </span>
          </div>
        </ContextMenuTrigger>
        <ContextMenuContent className="w-48">
          <ContextMenuItem
            onClick={() => toggleVisualVisibility(item.id)}
            data-testid={`selection-ctx-toggle-${item.id}`}
          >
            {visible ? (
              <>
                <EyeOff className="h-3.5 w-3.5 mr-2" />
                Hide
              </>
            ) : (
              <>
                <Eye className="h-3.5 w-3.5 mr-2" />
                Show
              </>
            )}
          </ContextMenuItem>
          {/* Group/Ungroup for this item */}
          {itemGroup && (
            <>
              <ContextMenuSeparator />
              <ContextMenuItem
                onClick={() => ungroupVisuals(itemGroup.id)}
                data-testid={`selection-ctx-ungroup-${item.id}`}
              >
                <Ungroup className="h-3.5 w-3.5 mr-2" />
                Ungroup from &ldquo;{itemGroup.name}&rdquo;
              </ContextMenuItem>
            </>
          )}
          <ContextMenuSeparator />
          <ContextMenuItem
            onClick={() => {
              if (!confirm(`Delete "${item.label}"?`)) return
              removeVisual(item.id)
              setDirty(true)
            }}
            className="text-destructive focus:text-destructive"
            data-testid={`selection-ctx-delete-${item.id}`}
          >
            <Trash2 className="h-3.5 w-3.5 mr-2" />
            Delete
          </ContextMenuItem>
          <ContextMenuSeparator />
          <ContextMenuItem onClick={showAll}>
            <Eye className="h-3.5 w-3.5 mr-2" />
            Show All
          </ContextMenuItem>
          <ContextMenuItem onClick={hideAll}>
            <EyeOff className="h-3.5 w-3.5 mr-2" />
            Hide All
          </ContextMenuItem>

          {/* Dock options — slicers only */}
          {isSlicer && (
            <>
              <ContextMenuSeparator />
              {dockAssignments[item.id] ? (
                <>
                  <ContextMenuItem
                    onClick={() => unassignFromDock(item.id)}
                    data-testid={`selection-ctx-undock-${item.id}`}
                  >
                    <Undo2 className="h-3.5 w-3.5 mr-2" />
                    Move to Canvas
                  </ContextMenuItem>
                  <ContextMenuSub>
                    <ContextMenuSubTrigger>
                      <SlidersHorizontal className="h-3.5 w-3.5 mr-2" />
                      Move to Dock…
                    </ContextMenuSubTrigger>
                    <ContextMenuSubContent>
                      {(['left', 'right', 'top', 'bottom'] as DockPosition[])
                        .filter(p => p !== dockAssignments[item.id])
                        .map(p => (
                          <ContextMenuItem
                            key={p}
                            onClick={() => assignToDock(item.id, p)}
                            data-testid={`selection-ctx-dock-${p}-${item.id}`}
                          >
                            {p === 'left' && <PanelLeft className="h-3.5 w-3.5 mr-2" />}
                            {p === 'right' && <PanelRight className="h-3.5 w-3.5 mr-2" />}
                            {p === 'top' && <PanelTop className="h-3.5 w-3.5 mr-2" />}
                            {p === 'bottom' && <PanelBottom className="h-3.5 w-3.5 mr-2" />}
                            {p.charAt(0).toUpperCase() + p.slice(1)}
                          </ContextMenuItem>
                        ))}
                    </ContextMenuSubContent>
                  </ContextMenuSub>
                </>
              ) : (
                <ContextMenuSub>
                  <ContextMenuSubTrigger>
                    <SlidersHorizontal className="h-3.5 w-3.5 mr-2" />
                    Dock to…
                  </ContextMenuSubTrigger>
                  <ContextMenuSubContent>
                    {(['left', 'right', 'top', 'bottom'] as DockPosition[]).map(p => (
                      <ContextMenuItem
                        key={p}
                        onClick={() => assignToDock(item.id, p)}
                        data-testid={`selection-ctx-dock-${p}-${item.id}`}
                      >
                        {p === 'left' && <PanelLeft className="h-3.5 w-3.5 mr-2" />}
                        {p === 'right' && <PanelRight className="h-3.5 w-3.5 mr-2" />}
                        {p === 'top' && <PanelTop className="h-3.5 w-3.5 mr-2" />}
                        {p === 'bottom' && <PanelBottom className="h-3.5 w-3.5 mr-2" />}
                        {p.charAt(0).toUpperCase() + p.slice(1)}
                      </ContextMenuItem>
                    ))}
                  </ContextMenuSubContent>
                </ContextMenuSub>
              )}
            </>
          )}
        </ContextMenuContent>
      </ContextMenu>
    )
  }, [isVisible, isSelected, handleItemClick, toggleVisualVisibility, showAll, hideAll, dockAssignments, assignToDock, unassignFromDock, itemGroupMap, ungroupVisuals, removeVisual, setDirty])

  return (
    <div className={cn('flex flex-col h-full', className)} data-testid="selection-pane">
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2 border-b">
        <div className="flex items-center gap-1.5">
          <span className="text-sm font-medium">Selection</span>
          {hiddenCount > 0 && (
            <span className="text-[10px] text-muted-foreground">
              ({hiddenCount} hidden)
            </span>
          )}
        </div>
        <div className="flex items-center gap-0.5">
          <Button
            variant="ghost"
            size="sm"
            className="h-6 text-[10px] px-1.5"
            onClick={showAll}
            title="Show all"
            data-testid="selection-show-all"
          >
            Show All
          </Button>
          <Button
            variant="ghost"
            size="sm"
            className="h-6 text-[10px] px-1.5"
            onClick={hideAll}
            title="Hide all"
            data-testid="selection-hide-all"
          >
            Hide All
          </Button>
        </div>
      </div>

      {/* Multi-select hint + Group / Delete buttons */}
      {selectedVisualIds.length > 1 && (
        <div className="px-3 py-1 border-b bg-accent/30 flex items-center justify-between" data-testid="selection-multi-hint">
          <span className="text-[10px] text-muted-foreground">
            {selectedVisualIds.length} items selected
          </span>
          <div className="flex items-center gap-1">
            <Button
              variant="outline"
              size="sm"
              className="h-5 px-2 text-[10px] gap-1"
              onClick={handleGroupSelected}
              disabled={!canGroupSelected}
              data-testid="selection-group-btn"
            >
              <Group className="h-3 w-3" />
              Group
            </Button>
            <Button
              variant="outline"
              size="sm"
              className="h-5 px-2 text-[10px] gap-1 text-destructive border-destructive/40 hover:bg-destructive/10"
              onClick={() => {
                if (!confirm(`Delete ${selectedVisualIds.length} selected visuals?`)) return
                for (const id of [...selectedVisualIds]) {
                  removeVisual(id)
                }
                setDirty(true)
              }}
              data-testid="selection-delete-btn"
            >
              <Trash2 className="h-3 w-3" />
              Delete
            </Button>
          </div>
        </div>
      )}

      {/* Item list */}
      <ScrollArea className="flex-1 min-h-0">
        <div className="p-2 space-y-0.5">
          {items.length === 0 && (
            <div className="text-xs text-muted-foreground px-2 py-4 text-center" data-testid="selection-empty">
              No visuals or slicers on this page.
            </div>
          )}

          {/* Grouped items — show each group as a collapsible section */}
          {visualGroups.map((group) => {
            const groupItems = items.filter((item) => group.visualIds.includes(item.id))
            if (groupItems.length === 0) return null
            const isCollapsed = collapsedGroups.has(group.id)
            const allGroupVisible = groupItems.every((item) => isVisible(item.id))

            return (
              <div key={group.id} className="border rounded-md mb-1" data-testid={`group-${group.id}`}>
                {/* Group header */}
                <ContextMenu>
                  <ContextMenuTrigger asChild>
                    <div
                      className="flex items-center gap-1.5 px-2 py-1 bg-blue-50 dark:bg-blue-950/30 rounded-t-md cursor-pointer hover:bg-blue-100 dark:hover:bg-blue-900/30"
                      onClick={() => toggleGroupCollapse(group.id)}
                      data-testid={`group-header-${group.id}`}
                    >
                      {isCollapsed ? (
                        <ChevronRight className="h-3 w-3 text-blue-600 dark:text-blue-400 shrink-0" />
                      ) : (
                        <ChevronDown className="h-3 w-3 text-blue-600 dark:text-blue-400 shrink-0" />
                      )}
                      <Group className="h-3 w-3 text-blue-600 dark:text-blue-400 shrink-0" />
                      <span className="text-xs font-medium text-blue-700 dark:text-blue-300 flex-1 truncate">
                        {group.name}
                      </span>
                      <span className="text-[10px] text-blue-500 dark:text-blue-400">
                        {groupItems.length}
                      </span>
                      <button
                        className="shrink-0 p-0.5 rounded hover:bg-accent transition-colors"
                        onClick={(e) => {
                          e.stopPropagation()
                          // Toggle visibility for all items in group
                          const newVisible = !allGroupVisible
                          for (const item of groupItems) {
                            if (isVisible(item.id) !== newVisible) {
                              toggleVisualVisibility(item.id)
                            }
                          }
                        }}
                        title={allGroupVisible ? 'Hide group' : 'Show group'}
                        data-testid={`group-toggle-vis-${group.id}`}
                      >
                        {allGroupVisible ? (
                          <Eye className="h-3 w-3 text-muted-foreground/60" />
                        ) : (
                          <EyeOff className="h-3 w-3 text-muted-foreground/40" />
                        )}
                      </button>
                    </div>
                  </ContextMenuTrigger>
                  <ContextMenuContent className="w-48">
                    <ContextMenuItem
                      onClick={() => ungroupVisuals(group.id)}
                      data-testid={`group-ungroup-${group.id}`}
                    >
                      <Ungroup className="h-3.5 w-3.5 mr-2" />
                      Ungroup
                    </ContextMenuItem>
                    <ContextMenuSeparator />
                    <ContextMenuItem
                      onClick={() => {
                        const newName = prompt('Rename group:', group.name)
                        if (newName && newName.trim()) renameGroup(group.id, newName.trim())
                      }}
                    >
                      Rename Group
                    </ContextMenuItem>
                    <ContextMenuSeparator />
                    <ContextMenuItem onClick={() => {
                      for (const item of groupItems) {
                        if (!isVisible(item.id)) toggleVisualVisibility(item.id)
                      }
                    }}>
                      <Eye className="h-3.5 w-3.5 mr-2" />
                      Show All in Group
                    </ContextMenuItem>
                    <ContextMenuItem onClick={() => {
                      for (const item of groupItems) {
                        if (isVisible(item.id)) toggleVisualVisibility(item.id)
                      }
                    }}>
                      <EyeOff className="h-3.5 w-3.5 mr-2" />
                      Hide All in Group
                    </ContextMenuItem>
                  </ContextMenuContent>
                </ContextMenu>

                {/* Group children */}
                {!isCollapsed && (
                  <div className="px-1 py-0.5 space-y-0.5">
                    {groupItems.map(item => renderItem(item))}
                  </div>
                )}
              </div>
            )
          })}

          {/* Ungrouped items */}
          {ungroupedItems.map(item => renderItem(item))}
        </div>
      </ScrollArea>

      {/* Footer hint */}
      <div className="px-3 py-1.5 border-t text-[9px] text-muted-foreground text-center">
        Ctrl+Click to toggle · Shift+Click for range · Right-click for options
      </div>
    </div>
  )
}

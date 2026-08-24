/**
 * RelationshipGraph — interactive graph of model tables and relationships.
 *
 * Supports multi-page layouts (model view pages/diagrams).
 * - "All tables" layout: always shows every table with auto-layout
 * - Custom layouts: show only selected tables, remembering positions
 *
 * Tables can be dragged from the sidebar (LeftSidebar) into custom layouts.
 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  Panel,
  Handle,
  Position,
  useNodesState,
  useEdgesState,
  type Node,
  type Edge,
  type NodeTypes,
  MarkerType,
  useReactFlow,
  ReactFlowProvider,
  type NodeChange,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { cn } from '@/lib/utils'
import { useAppStore } from '@/stores/app-store'
import { useModelViewStore, type NodePosition } from '@/stores/model-view-store'
import { Button } from '@/components/ui/button'
import { createRelationship, updateRelationship, setTableType as apiSetTableType, type RelationshipDef } from '@/lib/api'
import type { TableInfo, Relationship } from '@/stores/app-store'
import { RelationshipEditorDialog } from './RelationshipEditorDialog'

// ---------- Custom node ----------

interface TableNodeData {
  label: string
  columns: string[]
  table_type: string | null
  relatedColumns: Set<string>
  onColumnDragStart?: (table: string, column: string) => void
  onColumnDrop?: (fromTable: string, fromColumn: string, toTable: string, toColumn: string) => void
  [key: string]: unknown
}

function TableNode({ data }: { data: TableNodeData }) {
  const headerColor = {
    fact: 'bg-blue-600',
    dim: 'bg-emerald-600',
    bridge: 'bg-amber-600',
    null: 'bg-zinc-500',
  }[data.table_type ?? 'null']

  return (
    <div className="bg-card border rounded-lg shadow-md min-w-[180px] max-w-[220px] overflow-hidden" data-testid={`model-node-${data.label}`}>
      {/* Header */}
      <div className={cn('px-3 py-1.5 text-xs font-semibold text-white truncate', headerColor)}>
        {data.label}
      </div>

      {/* Columns */}
      <div className="px-2 py-1 max-h-[200px] overflow-y-auto">
        {data.columns.map((col) => (
          <div
            key={col}
            className={cn(
              'text-[11px] py-0.5 px-1 truncate rounded cursor-grab active:cursor-grabbing',
              data.relatedColumns.has(col)
                ? 'text-primary font-medium bg-primary/5'
                : 'text-muted-foreground'
            )}
            draggable
            onDragStart={(event) => {
              const payload = JSON.stringify({ table: data.label, column: col })
              event.dataTransfer.setData('application/model-column', payload)
              event.dataTransfer.effectAllowed = 'move'
              data.onColumnDragStart?.(data.label, col)
            }}
            onDragOver={(event) => {
              event.preventDefault()
              event.dataTransfer.dropEffect = 'move'
            }}
            onDrop={(event) => {
              event.preventDefault()
              const raw = event.dataTransfer.getData('application/model-column')
              if (!raw) return
              try {
                const parsed = JSON.parse(raw) as { table?: string; column?: string }
                if (!parsed.table || !parsed.column) return
                data.onColumnDrop?.(parsed.table, parsed.column, data.label, col)
              } catch {
                // Ignore malformed drag payload.
              }
            }}
            data-testid={`model-node-column-${data.label}-${col}`}
          >
            {col}
          </div>
        ))}
      </div>

      {/* Handles (invisible, used for edge connections) */}
      <Handle type="target" position={Position.Left} className="!w-2 !h-2 !bg-primary/50" />
      <Handle type="source" position={Position.Right} className="!w-2 !h-2 !bg-primary/50" />
    </div>
  )
}

const nodeTypes: NodeTypes = {
  tableNode: TableNode,
}

// ---------- Layout algorithm ----------

interface LayoutInput {
  tables: TableInfo[]
  relationships: Relationship[]
  savedPositions?: Record<string, NodePosition>
  onColumnDragStart?: (table: string, column: string) => void
  onColumnDrop?: (fromTable: string, fromColumn: string, toTable: string, toColumn: string) => void
}

function computeLayout({ tables, relationships, savedPositions, onColumnDragStart, onColumnDrop }: LayoutInput): {
  nodes: Node<TableNodeData>[]
  edges: Edge[]
} {
  // Build relationship column lookup for highlighting
  const relColumnsByTable = new Map<string, Set<string>>()
  for (const rel of relationships) {
    if (!relColumnsByTable.has(rel.from_table)) relColumnsByTable.set(rel.from_table, new Set())
    if (!relColumnsByTable.has(rel.to_table)) relColumnsByTable.set(rel.to_table, new Set())
    relColumnsByTable.get(rel.from_table)!.add(rel.from_column)
    relColumnsByTable.get(rel.to_table)!.add(rel.to_column)
  }

  // Classify tables
  const tableTypeMap = new Map<string, string | null>()
  const fromTables = new Set(relationships.map((r) => r.from_table))
  const toTables = new Set(relationships.map((r) => r.to_table))

  for (const t of tables) {
    if (t.table_type) {
      tableTypeMap.set(t.name, t.table_type)
    } else {
      const isFrom = fromTables.has(t.name)
      const isTo = toTables.has(t.name)
      if (isFrom && !isTo) tableTypeMap.set(t.name, 'fact')
      else if (isTo && !isFrom) tableTypeMap.set(t.name, 'dim')
      else if (isFrom && isTo) tableTypeMap.set(t.name, 'bridge')
      else tableTypeMap.set(t.name, null)
    }
  }

  // Layout constants
  const NODE_WIDTH = 200
  const NODE_GAP_X = 80
  const NODE_GAP_Y = 40
  const COL_HEIGHT_ESTIMATE = 16

  function estimateNodeHeight(t: TableInfo) {
    return 40 + Math.min(t.columns.length, 12) * COL_HEIGHT_ESTIMATE + 16
  }

  // Helper: create node data for a table
  function makeNodeData(t: TableInfo): TableNodeData {
    return {
      label: t.name,
      columns: t.columns,
      table_type: tableTypeMap.get(t.name) ?? null,
      relatedColumns: relColumnsByTable.get(t.name) ?? new Set(),
      onColumnDragStart,
      onColumnDrop,
    }
  }

  const nodes: Node<TableNodeData>[] = []

  // If savedPositions are provided and non-empty, use them
  const hasSavedPositions = savedPositions && Object.keys(savedPositions).length > 0

  if (hasSavedPositions) {
    for (const t of tables) {
      const pos = savedPositions[t.name]
      nodes.push({
        id: t.name,
        type: 'tableNode',
        position: pos ? { x: pos.x, y: pos.y } : { x: 40, y: 40 + nodes.length * 120 },
        data: makeNodeData(t),
      })
    }
  } else {
    // Auto-layout: facts left, dims right, bridges between, others bottom
    const factTables = tables.filter((t) => tableTypeMap.get(t.name) === 'fact')
    const dimTables = tables.filter((t) => tableTypeMap.get(t.name) === 'dim')
    const bridgeTables = tables.filter((t) => tableTypeMap.get(t.name) === 'bridge')
    const otherTables = tables.filter((t) => tableTypeMap.get(t.name) === null)

    let factY = 40
    for (const t of factTables) {
      const h = estimateNodeHeight(t)
      nodes.push({
        id: t.name,
        type: 'tableNode',
        position: { x: 40, y: factY },
        data: makeNodeData(t),
      })
      factY += h + NODE_GAP_Y
    }

    const dimStartX = 40 + NODE_WIDTH + NODE_GAP_X * 2
    const dimsPerRow = Math.max(1, Math.ceil(Math.sqrt(dimTables.length)))
    for (let i = 0; i < dimTables.length; i++) {
      const t = dimTables[i]
      const col = i % dimsPerRow
      const row = Math.floor(i / dimsPerRow)
      const h = estimateNodeHeight(t)
      nodes.push({
        id: t.name,
        type: 'tableNode',
        position: {
          x: dimStartX + col * (NODE_WIDTH + NODE_GAP_X),
          y: 40 + row * (h + NODE_GAP_Y),
        },
        data: makeNodeData(t),
      })
    }

    const bridgeStartX = 40 + NODE_WIDTH + NODE_GAP_X
    let bridgeY = factY + 40
    for (const t of bridgeTables) {
      const h = estimateNodeHeight(t)
      nodes.push({
        id: t.name,
        type: 'tableNode',
        position: { x: bridgeStartX, y: bridgeY },
        data: makeNodeData(t),
      })
      bridgeY += h + NODE_GAP_Y
    }

    let otherX = 40
    const otherY = Math.max(factY, bridgeY) + 60
    for (const t of otherTables) {
      nodes.push({
        id: t.name,
        type: 'tableNode',
        position: { x: otherX, y: otherY },
        data: makeNodeData(t),
      })
      otherX += NODE_WIDTH + NODE_GAP_X
    }
  }

  // Edges — only for tables that are visible in the current layout
  const visibleTableNames = new Set(tables.map((t) => t.name))
  const edges: Edge[] = relationships
    .filter((rel) => visibleTableNames.has(rel.from_table) && visibleTableNames.has(rel.to_table))
    .map((rel, i) => {
      // Cardinality markers: from = many side (fact), to = one side (dim)
      // Filter direction: dim (to_table) filters fact (from_table)
      // So edge source = to_table (filter origin), target = from_table (filter target)
      const card = rel.cardinality ?? 'many-to-one'
      // fromMarker goes near from_table (now the target end), toMarker near to_table (now the source end)
      const fromMarker = card.startsWith('many') ? '*' : '1'
      const toMarker = card.endsWith('many') ? '*' : '1'
      const arrow = (rel.cross_filter_direction ?? 'single') === 'both' ? '↔' : '→'
      return {
      id: rel.rel_id || `rel-${i}`,
      source: rel.to_table,
      target: rel.from_table,
      label: `${toMarker}  ${rel.to_column} ${arrow} ${rel.from_column}  ${fromMarker}`,
      type: 'default',
      animated: false,
      style: {
        stroke: 'var(--color-primary)',
        strokeWidth: 2,
        strokeDasharray: rel.active ? undefined : '4 2',
      },
      // Arrow on target end (from_table = fact, the one being filtered)
      markerEnd: {
        type: MarkerType.ArrowClosed,
        width: 16,
        height: 16,
        color: 'var(--color-primary)',
      },
      // Bi-directional: also put arrow on source end
      markerStart: (rel.cross_filter_direction ?? 'single') === 'both'
        ? {
            type: MarkerType.ArrowClosed,
            width: 16,
            height: 16,
            color: 'var(--color-primary)',
          }
        : undefined,
      labelStyle: { fontSize: 10, fill: 'var(--color-muted-foreground)' },
      data: { from_column: rel.from_column, to_column: rel.to_column },
    }})

  return { nodes, edges }
}

// ---------- Inner component (needs ReactFlow context) ----------

function RelationshipGraphInner() {
  const tables = useAppStore(s => s.tables)
  const relationships = useAppStore(s => s.relationships)
  const projectPath = useAppStore(s => s.projectPath)
  const setTableTypeInStore = useAppStore((s) => s.setTableType)
  const setRelationships = useAppStore((s) => s.setRelationships)

  const layouts = useModelViewStore(s => s.layouts)
  const activeLayoutId = useModelViewStore(s => s.activeLayoutId)
  const updateNodePosition = useModelViewStore(s => s.updateNodePosition)
  const addTableToLayout = useModelViewStore(s => s.addTableToLayout)
  const removeTableFromLayout = useModelViewStore(s => s.removeTableFromLayout)

  const activeLayout = useMemo(
    () => layouts.find((l) => l.id === activeLayoutId) ?? layouts[0],
    [layouts, activeLayoutId]
  )

  const isCustomLayout = activeLayout.id !== 'all'

  // Filter tables by what's visible in the active layout
  const visibleTables = useMemo(() => {
    if (!activeLayout || activeLayout.visibleTables === null) return tables
    const set = new Set(activeLayout.visibleTables.map((t) => t.toUpperCase()))
    return tables.filter((t) => set.has(t.name.toUpperCase()))
  }, [tables, activeLayout])

  // Tables NOT in this layout (for display / drag-drop info)
  const missingTables = useMemo(() => {
    if (!isCustomLayout || !activeLayout.visibleTables) return []
    const set = new Set(activeLayout.visibleTables.map((t) => t.toUpperCase()))
    return tables.filter((t) => !set.has(t.name.toUpperCase()))
  }, [tables, isCustomLayout, activeLayout])

  // Context menu state
  const [contextMenu, setContextMenu] = useState<{
    x: number
    y: number
    tableName: string
  } | null>(null)
  const [relationshipDialogOpen, setRelationshipDialogOpen] = useState(false)
  const [relationshipDialogMode, setRelationshipDialogMode] = useState<'create' | 'edit'>('create')
  const [relationshipInitial, setRelationshipInitial] = useState<Partial<RelationshipDef> | undefined>(undefined)
  const [relationshipError, setRelationshipError] = useState<string | null>(null)
  const [dragSourceColumn, setDragSourceColumn] = useState<{ table: string; column: string } | null>(null)

  const handleColumnDragStart = useCallback((table: string, column: string) => {
    setDragSourceColumn({ table, column })
  }, [])

  const handleColumnDrop = useCallback((fromTable: string, fromColumn: string, toTable: string, toColumn: string) => {
    if (fromTable === toTable) {
      setRelationshipError('Relationship drag/drop requires two different tables.')
      return
    }
    setRelationshipInitial({
      from_table: fromTable,
      from_column: fromColumn,
      to_table: toTable,
      to_column: toColumn,
      cross_filter_direction: 'single',
      active: true,
    })
    setRelationshipDialogMode('create')
    setRelationshipError(null)
    setRelationshipDialogOpen(true)
    setDragSourceColumn(null)
  }, [])

  // Compute initial layout
  const { nodes: initialNodes, edges: initialEdges } = useMemo(
    () =>
      computeLayout({
        tables: visibleTables,
        relationships,
        savedPositions: activeLayout.nodePositions,
        onColumnDragStart: handleColumnDragStart,
        onColumnDrop: handleColumnDrop,
      }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [] // Initial only
  )

  const [nodes, setNodes, onNodesChange] = useNodesState(initialNodes)
  const [edges, setEdges, onEdgesChange] = useEdgesState(initialEdges)

  const { screenToFlowPosition } = useReactFlow()

  // Re-layout when visible tables/relationships/activeLayout changes
  useEffect(() => {
    const { nodes: n, edges: e } = computeLayout({
      tables: visibleTables,
      relationships,
      savedPositions: activeLayout.nodePositions,
      onColumnDragStart: handleColumnDragStart,
      onColumnDrop: handleColumnDrop,
    })
    setNodes(n)
    setEdges(e)
  }, [visibleTables, relationships, activeLayout.id, activeLayout.nodePositions, setNodes, setEdges, handleColumnDragStart, handleColumnDrop])
  // Note: we intentionally depend on activeLayout.id rather than the full object
  // to avoid re-layout on every position update

  // Persist node positions when a node is dragged
  const handleNodesChange = useCallback(
    (changes: NodeChange<Node<TableNodeData>>[]) => {
      onNodesChange(changes)
      for (const change of changes) {
        if (change.type === 'position' && change.position && !change.dragging) {
          // Node drag ended — save position
          updateNodePosition(activeLayout.id, change.id, {
            x: change.position.x,
            y: change.position.y,
          })
        }
      }
    },
    [onNodesChange, updateNodePosition, activeLayout.id]
  )

  // ── Drag-and-drop from sidebar ──

  const onDragOver = useCallback((event: React.DragEvent) => {
    event.preventDefault()
    event.dataTransfer.dropEffect = 'move'
  }, [])

  const onDrop = useCallback(
    (event: React.DragEvent) => {
      event.preventDefault()

      const tableName = event.dataTransfer.getData('application/model-table')
      if (!tableName) return

      // Only allow drop on custom layouts
      if (!isCustomLayout) return

      // Check if table already in layout
      if (
        activeLayout.visibleTables &&
        activeLayout.visibleTables.some((t) => t.toUpperCase() === tableName.toUpperCase())
      ) {
        return
      }

      // Convert screen position to flow position
      const position = screenToFlowPosition({
        x: event.clientX,
        y: event.clientY,
      })

      addTableToLayout(activeLayout.id, tableName, position)
    },
    [isCustomLayout, activeLayout, screenToFlowPosition, addTableToLayout]
  )

  // ── Context menu ──

  const onNodeContextMenu = useCallback((event: React.MouseEvent, node: Node) => {
    event.preventDefault()
    setContextMenu({
      x: event.clientX,
      y: event.clientY,
      tableName: node.id,
    })
  }, [])

  const onPaneClick = useCallback(() => {
    setContextMenu(null)
    setDragSourceColumn(null)
  }, [])

  const handleSetType = useCallback(
    async (tableName: string, type: 'fact' | 'dim' | 'bridge' | null) => {
      setContextMenu(null)
      setTableTypeInStore(tableName, type)
      try {
        await apiSetTableType(tableName, type, projectPath ?? undefined)
      } catch (err) {
        console.error('Failed to save table_type:', err)
      }
    },
    [projectPath, setTableTypeInStore]
  )

  const handleRemoveFromLayout = useCallback(
    (tableName: string) => {
      setContextMenu(null)
      if (isCustomLayout) {
        removeTableFromLayout(activeLayout.id, tableName)
      }
    },
    [isCustomLayout, activeLayout.id, removeTableFromLayout]
  )

  const contextTableType = useMemo(() => {
    if (!contextMenu) return null
    const t = tables.find((t) => t.name === contextMenu.tableName)
    return t?.table_type ?? null
  }, [contextMenu, tables])

  // Legend items
  const legendItems = [
    { type: 'fact', label: 'Fact', color: 'bg-blue-600' },
    { type: 'dim', label: 'Dimension', color: 'bg-emerald-600' },
    { type: 'bridge', label: 'Bridge', color: 'bg-amber-600' },
    { type: null, label: 'Unclassified', color: 'bg-zinc-500' },
  ] as const

  const handleCreateRelationship = useCallback(
    async (payload: Omit<RelationshipDef, 'rel_id'> & { rel_id?: string }) => {
      const result = await createRelationship(payload, projectPath ?? undefined)
      if (result.error || !result.data) {
        throw new Error(result.error || 'Failed to create relationship')
      }
      setRelationships(result.data.relationships)
      setRelationshipError(null)
    },
    [projectPath, setRelationships]
  )

  const handleUpdateRelationship = useCallback(
    async (payload: Omit<RelationshipDef, 'rel_id'> & { rel_id?: string }) => {
      if (!payload.rel_id) {
        throw new Error('Relationship id is required to update an existing relationship.')
      }
      const result = await updateRelationship(payload.rel_id, {
        from_table: payload.from_table,
        from_column: payload.from_column,
        to_table: payload.to_table,
        to_column: payload.to_column,
        active: payload.active,
        cross_filter_direction: payload.cross_filter_direction,
        cardinality: payload.cardinality,
      }, projectPath ?? undefined)
      if (result.error || !result.data) {
        throw new Error(result.error || 'Failed to update relationship')
      }
      setRelationships(result.data.relationships)
      setRelationshipError(null)
    },
    [projectPath, setRelationships]
  )

  const onConnect = useCallback(
    ({ source, target }: { source: string | null; target: string | null }) => {
      if (!source || !target || source === target) return
      setRelationshipInitial({
        from_table: source,
        to_table: target,
        cross_filter_direction: 'single',
        active: true,
      })
      setRelationshipDialogMode('create')
      setRelationshipDialogOpen(true)
    },
    []
  )

  const onEdgeClick = useCallback(
    (_event: React.MouseEvent, edge: Edge) => {
      const fromColumn = (edge.data as { from_column?: string } | undefined)?.from_column
      const toColumn = (edge.data as { to_column?: string } | undefined)?.to_column
      const relationship = relationships.find((rel) => {
        if (rel.rel_id && rel.rel_id === edge.id) return true
        return rel.from_table === edge.source
          && rel.to_table === edge.target
          && rel.from_column === fromColumn
          && rel.to_column === toColumn
      })
      if (!relationship) {
        setRelationshipError('Unable to resolve relationship for editing.')
        return
      }
      if (!relationship.rel_id) {
        setRelationshipError('This relationship has no id and cannot be edited yet.')
        return
      }
      setRelationshipInitial({
        rel_id: relationship.rel_id,
        from_table: relationship.from_table,
        from_column: relationship.from_column,
        to_table: relationship.to_table,
        to_column: relationship.to_column,
        cross_filter_direction: relationship.cross_filter_direction,
        active: relationship.active,
        cardinality: relationship.cardinality,
      })
      setRelationshipDialogMode('edit')
      setRelationshipError(null)
      setRelationshipDialogOpen(true)
    },
    [relationships]
  )

  return (
    <div className="w-full h-full relative" data-testid="relationship-graph">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={handleNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={onConnect}
        onEdgeClick={onEdgeClick}
        onNodeContextMenu={onNodeContextMenu}
        onPaneClick={onPaneClick}
        onDragOver={onDragOver}
        onDrop={onDrop}
        nodeTypes={nodeTypes}
        fitView
        fitViewOptions={{ padding: 0.2 }}
        minZoom={0.1}
        maxZoom={2}
        attributionPosition="bottom-left"
        proOptions={{ hideAttribution: true }}
      >
        <Background gap={16} size={1} />
        <Controls showInteractive={false} />
        <MiniMap
          nodeStrokeWidth={3}
          pannable
          zoomable
          style={{ height: 100, width: 140 }}
        />

        {/* Legend panel */}
        <Panel position="top-right">
          <div className="bg-background/90 backdrop-blur-sm border rounded-lg p-3 shadow-md" data-testid="model-view-legend">
            <div className="text-xs font-semibold mb-2 text-foreground">Table Types</div>
            <div className="flex flex-col gap-1">
              {legendItems.map((item) => (
                <div key={item.label} className="flex items-center gap-2">
                  <div className={cn('w-3 h-3 rounded-sm', item.color)} />
                  <span className="text-xs text-muted-foreground">{item.label}</span>
                </div>
              ))}
            </div>
            <div className="mt-2 pt-2 border-t text-[10px] text-muted-foreground">
              Right-click a table to change its type
            </div>
          </div>
        </Panel>

        {/* Info panel */}
        <Panel position="top-left">
          <div className="bg-background/90 backdrop-blur-sm border rounded-lg p-3 shadow-md">
            <div className="text-sm font-semibold text-foreground">
              {activeLayout.name}
            </div>
            <div className="text-xs text-muted-foreground mt-1">
              {visibleTables.length} tables · {relationships.length} relationships
              {isCustomLayout && missingTables.length > 0 && (
                <span className="block mt-0.5">
                  Drag tables from sidebar to add
                </span>
              )}
            </div>
            <div className="mt-2 flex items-center gap-2">
              <Button
                size="sm"
                variant="outline"
                className="h-7 text-xs"
                onClick={() => {
                  setRelationshipInitial(undefined)
                  setRelationshipDialogMode('create')
                  setRelationshipError(null)
                  setRelationshipDialogOpen(true)
                }}
                data-testid="model-relationship-add-btn"
              >
                New relationship
              </Button>
              <span className="text-[10px] text-muted-foreground">drag column → column to prefill</span>
            </div>
            {dragSourceColumn && (
              <div className="text-[10px] text-muted-foreground mt-1" data-testid="model-column-drag-source">
                Dragging: {dragSourceColumn.table}.{dragSourceColumn.column}
              </div>
            )}
            {relationshipError && (
              <div className="text-[10px] text-destructive mt-1" data-testid="model-relationship-error">
                {relationshipError}
              </div>
            )}
          </div>
        </Panel>

        {/* Empty state for custom layouts with no tables */}
        {isCustomLayout && visibleTables.length === 0 && (
          <Panel position="top-left" className="!top-1/2 !left-1/2 !-translate-x-1/2 !-translate-y-1/2">
            <div className="bg-background/90 backdrop-blur-sm border rounded-lg p-6 shadow-md text-center" data-testid="model-view-empty">
              <div className="text-muted-foreground text-sm mb-2">
                This layout is empty
              </div>
              <div className="text-muted-foreground/60 text-xs">
                Drag tables from the Fields pane on the left to add them here.
              </div>
            </div>
          </Panel>
        )}
      </ReactFlow>

      {/* Context menu */}
      {contextMenu && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setContextMenu(null)} />
          <div
            className="fixed z-50 bg-popover border rounded-lg shadow-xl py-1 min-w-[180px]"
            style={{ left: contextMenu.x, top: contextMenu.y }}
            data-testid="table-type-context-menu"
          >
            <div className="px-3 py-1.5 text-xs font-semibold text-muted-foreground border-b">
              {contextMenu.tableName}
            </div>
            <div className="py-1">
              {([
                { type: 'fact' as const, label: 'Set as Fact', color: 'bg-blue-600' },
                { type: 'dim' as const, label: 'Set as Dimension', color: 'bg-emerald-600' },
                { type: 'bridge' as const, label: 'Set as Bridge', color: 'bg-amber-600' },
              ]).map((item) => (
                <button
                  key={item.type}
                  className={cn(
                    'w-full text-left px-3 py-1.5 text-sm flex items-center gap-2 hover:bg-accent',
                    contextTableType === item.type && 'bg-accent/50 font-medium'
                  )}
                  onClick={() => handleSetType(contextMenu.tableName, item.type)}
                  data-testid={`set-table-type-${item.type}`}
                >
                  <div className={cn('w-2.5 h-2.5 rounded-sm', item.color)} />
                  <span>{item.label}</span>
                  {contextTableType === item.type && (
                    <span className="ml-auto text-xs text-muted-foreground">✓</span>
                  )}
                </button>
              ))}
              <div className="border-t my-1" />
              <button
                className={cn(
                  'w-full text-left px-3 py-1.5 text-sm flex items-center gap-2 hover:bg-accent',
                  contextTableType === null && 'bg-accent/50 font-medium'
                )}
                onClick={() => handleSetType(contextMenu.tableName, null)}
                data-testid="set-table-type-auto"
              >
                <div className="w-2.5 h-2.5 rounded-sm bg-zinc-500" />
                <span>Auto-detect</span>
                {contextTableType === null && (
                  <span className="ml-auto text-xs text-muted-foreground">✓</span>
                )}
              </button>
              {isCustomLayout && (
                <>
                  <div className="border-t my-1" />
                  <button
                    className="w-full text-left px-3 py-1.5 text-sm flex items-center gap-2 hover:bg-accent text-destructive"
                    onClick={() => handleRemoveFromLayout(contextMenu.tableName)}
                    data-testid="remove-from-layout"
                  >
                    <span>Remove from layout</span>
                  </button>
                </>
              )}
            </div>
          </div>
        </>
      )}

      <RelationshipEditorDialog
        open={relationshipDialogOpen}
        onOpenChange={setRelationshipDialogOpen}
        tables={tables}
        initial={relationshipInitial}
        title={relationshipDialogMode === 'edit' ? 'Edit Relationship' : 'Create Relationship'}
        description={relationshipDialogMode === 'edit'
          ? 'Update the selected relationship from the model view graph.'
          : 'Create a relationship between two tables in the model view.'}
        submitLabel={relationshipDialogMode === 'edit' ? 'Update' : 'Create'}
        onSubmit={relationshipDialogMode === 'edit' ? handleUpdateRelationship : handleCreateRelationship}
      />
    </div>
  )
}

// ---------- Exported wrapper (provides ReactFlow context) ----------

export function RelationshipGraph() {
  return (
    <ReactFlowProvider>
      <RelationshipGraphInner />
    </ReactFlowProvider>
  )
}

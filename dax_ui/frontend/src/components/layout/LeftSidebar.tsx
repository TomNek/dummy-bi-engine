import { useState, useMemo, useEffect, useCallback } from 'react'
import { 
  ChevronRight, 
  ChevronDown, 
  Table2, 
  Hash, 
  Type, 
  Calendar, 
  ToggleLeft,
  FunctionSquare,
  GripVertical,
  X,
  Link,
  Shield,
  Eye,
  EyeOff,
  User,
  Plus,
  Pencil,
  Trash2,
  Calculator,
  TableProperties,
  ListFilter,
  ListTree,
  Layers,
  Gauge,
  ChevronsUpDown,
  ChevronsDownUp,
  Lightbulb,
  SlidersHorizontal,
  BookOpen,
  AlignLeft,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { ScrollArea } from '@/components/ui/scroll-area'

import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { Separator } from '@/components/ui/separator'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Slider } from '@/components/ui/slider'
import { useAppStore, useFormulaBarStore, useModelViewStore, useReportStore, type PlaybookMeta } from '@/stores'
import { useModelAuthoring, useFieldParameters, useCalcGroups, useWhatIfParameters, useHierarchies, usePanelResize } from '@/hooks'
import { MeasureEditor, CalcTableEditor, CalcColumnEditor, FieldParameterEditor, CalcGroupEditor, WhatIfParameterEditor, HierarchyEditor, PlaybookEditor } from '@/components/model'
import { DataTypeEditor } from '@/components/model/DataTypeEditor'
import { RelationshipManager } from '@/components/model/RelationshipManager'
// Slicer editors moved to RightSidebar
import { RoleEditor } from '@/components/security'
import { EDUSubWizard, type EDUConfig } from '@/components/autogen/EDUSubWizard'
import type { 
  MeasureDetail, CalcTableDetail, CalcColumnDetail, 
  FieldParameterMeta, FieldParameterDef,
  CalcGroupMeta, CalcGroupDef,
  WhatIfParameterMeta, WhatIfParameterDef,
  SecurityRoleRaw,
  HierarchyDef,
  TableInfo
} from '@/lib/api'
import { getSecurityRoles, listPlaybooks, deletePlaybook } from '@/lib/api'
import { HAS_EDU_RELATIONSHIPS } from '@/lib/edition'

interface LeftSidebarProps {
  className?: string
}

function getTypeIcon(columnName: string, dataType?: string) {
  // Use actual data type when available
  if (dataType) {
    const dt = dataType.toUpperCase()
    if (dt.startsWith('DATE') || dt.startsWith('TIMESTAMP')) return Calendar
    if (dt.startsWith('INT') || dt.startsWith('BIGINT') || dt.startsWith('SMALLINT') || dt.startsWith('TINYINT')
        || dt.startsWith('DOUBLE') || dt.startsWith('FLOAT') || dt.startsWith('DECIMAL') || dt === 'REAL'
        || dt === 'NUMERIC' || dt === 'HUGEINT') return Hash
    if (dt === 'BOOLEAN') return ToggleLeft
    return Type  // VARCHAR and anything else → text icon
  }
  // Fallback: infer type from column name patterns
  const name = columnName.toLowerCase()
  if (name.includes('date') || name.includes('time') || name.includes('year') || name.includes('month') || name.includes('day')) {
    return Calendar
  }
  if (name.includes('amount') || name.includes('price') || name.includes('cost') || name.includes('qty') || name.includes('count') || name.includes('total') || name.includes('sum') || name.includes('key') || name.includes('id')) {
    return Hash
  }
  if (name.includes('flag') || name.includes('is_') || name.includes('has_') || name.includes('active') || name.includes('enabled')) {
    return ToggleLeft
  }
  return Type
}

function getMeasureName(measure: string) {
  if (measure.includes('[')) {
    return measure.replace(/^[^\[]+\[/, '').replace(/\]$/, '')
  }
  return measure
}

/**
 * Extract used field identifiers from a visual's encodings.
 * Returns a Set of keys like "col:Table.Column" or "measure:MeasureName"
 * plus a map from key → slot names where it's used.
 */
function extractUsedFields(encodings?: Record<string, unknown>): {
  usedFieldKeys: Set<string>
  fieldSlotMap: Map<string, string[]>
} {
  const usedFieldKeys = new Set<string>()
  const fieldSlotMap = new Map<string, string[]>()
  if (!encodings) return { usedFieldKeys, fieldSlotMap }

  const addField = (key: string, slotName: string) => {
    usedFieldKeys.add(key)
    const slots = fieldSlotMap.get(key) || []
    if (!slots.includes(slotName)) slots.push(slotName)
    fieldSlotMap.set(key, slots)
  }

  const processExpr = (expr: any, slotName: string) => {
    if (!expr || typeof expr !== 'object') return
    if (expr.type === 'ColumnRef' && expr.table && expr.column) {
      addField(`col:${expr.table}.${expr.column}`, slotName)
    } else if (expr.type === 'MeasureRef' && expr.name) {
      addField(`measure:${expr.name}`, slotName)
    } else if (expr.type === 'HierarchyRef' && expr.name) {
      addField(`hierarchy:${expr.name}`, slotName)
    }
  }

  for (const [slotName, value] of Object.entries(encodings)) {
    if (Array.isArray(value)) {
      value.forEach(v => processExpr(v, slotName))
    } else {
      processExpr(value, slotName)
    }
  }

  return { usedFieldKeys, fieldSlotMap }
}

interface TableItemProps {
  table: { name: string; columns: string[] }
  measures: string[]
  searchTerm: string
  expandGeneration?: number
  expandDefault?: boolean
  /** When true, the table header is draggable (for Model View drag-to-layout). */
  draggableAsTable?: boolean
  /** Optional: set to true if this table is already in the current model layout. */
  isInModelLayout?: boolean
  /** Set of used field keys from the selected visual's encodings */
  usedFieldKeys?: Set<string>
}

function TableItem({ table, measures, searchTerm, expandGeneration, expandDefault, draggableAsTable, isInModelLayout, usedFieldKeys }: TableItemProps) {
  const [isOpen, setIsOpen] = useState(true)
  // Data type editor state
  const [dtEditorCol, setDtEditorCol] = useState<{ column: string; x: number; y: number } | null>(null)
  const storeTables = useAppStore(s => s.tables)
  const setModelData = useAppStore(s => s.setModelData)
  
  // Respond to expand/collapse all
  useEffect(() => {
    if (expandGeneration !== undefined && expandGeneration > 0) {
      setIsOpen(!!expandDefault)
    }
  }, [expandGeneration, expandDefault])
  
  const tableMeasures = useMemo(() => 
    measures.filter(m => {
      // Measures often have format like "Table[Measure]" or just "Measure"
      const match = m.match(/^([^\[]+)\[/)
      return match ? match[1] === table.name : false
    }),
    [measures, table.name]
  )
  
  const filteredColumns = (table.columns || []).filter((col) =>
    col && col.toLowerCase().includes(searchTerm.toLowerCase())
  )
  const filteredMeasures = tableMeasures.filter((m) =>
    m && m.toLowerCase().includes(searchTerm.toLowerCase())
  )
  
  const hasMatches = 
    (table.name || '').toLowerCase().includes(searchTerm.toLowerCase()) ||
    filteredColumns.length > 0 ||
    filteredMeasures.length > 0
  
  if (searchTerm && !hasMatches) {
    return null
  }

  return (
    <Collapsible open={isOpen} onOpenChange={setIsOpen}>
      <CollapsibleTrigger asChild>
        <Button
          variant="ghost"
          className={cn(
            "w-full justify-start gap-2 px-2 h-8 font-normal hover:bg-accent",
            draggableAsTable && !isInModelLayout && "cursor-grab",
            draggableAsTable && isInModelLayout && "opacity-50"
          )}
          data-testid={`table-${table.name}`}
          draggable={draggableAsTable && !isInModelLayout}
          onDragStart={
            draggableAsTable && !isInModelLayout
              ? (e: React.DragEvent) => {
                  e.dataTransfer.setData('application/model-table', table.name)
                  e.dataTransfer.effectAllowed = 'move'
                }
              : undefined
          }
        >
          {isOpen ? (
            <ChevronDown className="h-4 w-4 shrink-0" />
          ) : (
            <ChevronRight className="h-4 w-4 shrink-0" />
          )}
          <Table2 className="h-4 w-4 shrink-0 text-muted-foreground" />
          <span className="truncate">{table.name}</span>
        </Button>
      </CollapsibleTrigger>
      <CollapsibleContent>
        <div className="ml-4 border-l pl-2">
          {/* Columns */}
          {filteredColumns.map((column) => {
            const colType = storeTables?.find(t => t.name === table.name)?.column_types?.[column]
            const TypeIcon = getTypeIcon(column, colType)
            const isUsed = usedFieldKeys?.has(`col:${table.name}.${column}`)
            return (
              <div
                key={column}
                className={cn(
                  "flex items-center gap-2 px-2 py-1 text-sm hover:bg-accent rounded cursor-grab group",
                  isUsed && "bg-primary/8 font-medium"
                )}
                draggable
                data-testid={`column-${table.name}-${column}`}
                data-drag-type="column"
                data-drag-table={table.name}
                data-drag-column={column}
                onDragStart={(e) => {
                  e.dataTransfer.setData(
                    'application/json',
                    JSON.stringify({ type: 'ColumnRef', table: table.name, column })
                  )
                  e.dataTransfer.effectAllowed = 'copy'
                }}
                onContextMenu={(e) => {
                  e.preventDefault()
                  setDtEditorCol({ column, x: e.clientX, y: e.clientY })
                }}
              >
                <GripVertical className="h-3 w-3 opacity-0 group-hover:opacity-50" />
                <TypeIcon className={cn("h-4 w-4 shrink-0", isUsed ? "text-primary" : "text-muted-foreground")} />
                <span className="truncate">{column}</span>
                {isUsed && <span className="ml-auto text-[9px] text-primary/70 shrink-0">in use</span>}
              </div>
            )
          })}
          
          {/* Measures from this table */}
          {filteredMeasures.map((measure) => {
            const displayName = getMeasureName(measure)
            const isUsed = usedFieldKeys?.has(`measure:${displayName}`)
            return (
              <div
                key={measure}
                className={cn(
                  "flex items-center gap-2 px-2 py-1 text-sm hover:bg-accent rounded cursor-grab group",
                  isUsed && "bg-primary/8 font-medium"
                )}
                draggable
                data-testid={`measure-${measure}`}
                data-drag-type="measure"
                data-drag-measure={measure}
                onDragStart={(e) => {
                  e.dataTransfer.setData(
                    'application/json',
                    JSON.stringify({ type: 'MeasureRef', name: displayName })
                  )
                  e.dataTransfer.effectAllowed = 'copy'
                }}
              >
                <GripVertical className="h-3 w-3 opacity-0 group-hover:opacity-50" />
                <FunctionSquare className={cn("h-4 w-4 shrink-0", isUsed ? "text-primary" : "text-yellow-600")} />
                <span className="truncate">{displayName}</span>
                {isUsed && <span className="ml-auto text-[9px] text-primary/70 shrink-0">in use</span>}
              </div>
            )
          })}
        </div>
      </CollapsibleContent>
      {/* Data type editor popover */}
      {dtEditorCol && (
        <DataTypeEditor
          table={table.name}
          column={dtEditorCol.column}
          currentType={storeTables?.find(t => t.name === table.name)?.column_types?.[dtEditorCol.column]}
          position={{ x: dtEditorCol.x, y: dtEditorCol.y }}
          onClose={() => setDtEditorCol(null)}
          onSaved={(newType) => {
            // Update column_types in the store locally
            if (storeTables) {
              const updated = storeTables.map(t => {
                if (t.name !== table.name) return t
                return { ...t, column_types: { ...(t.column_types ?? {}), [dtEditorCol.column]: newType } }
              })
              const measures = useAppStore.getState().measures
              const rels = useAppStore.getState().relationships
              setModelData(updated, measures ?? [], rels)
            }
          }}
        />
      )}
    </Collapsible>
  )
}

// Standalone measures section (measures not associated with a table)
function StandaloneMeasures({ measures, searchTerm, measureDetails, expandGeneration, expandDefault, usedFieldKeys }: { 
  measures: string[]
  searchTerm: string
  measureDetails?: MeasureDetail[]
  expandGeneration?: number
  expandDefault?: boolean
  usedFieldKeys?: Set<string>
}) {
  const [isOpen, setIsOpen] = useState(true)
  const [openFolders, setOpenFolders] = useState<Record<string, boolean>>({})
  
  useEffect(() => {
    if (expandGeneration !== undefined && expandGeneration > 0) {
      setIsOpen(!!expandDefault)
    }
  }, [expandGeneration, expandDefault])
  const setFormulaBarSelection = useFormulaBarStore(s => s.setSelection)
  
  // Filter to measures without table prefix
  const standaloneMeasures = measures.filter(m => !m.includes('['))
  const filteredMeasures = standaloneMeasures.filter(m =>
    m.toLowerCase().includes(searchTerm.toLowerCase())
  )

  if (filteredMeasures.length === 0) return null

  // Group by folder if details available
  const folderMap = new Map<string, string[]>()
  if (measureDetails && measureDetails.length > 0) {
    const detailByName = new Map(measureDetails.map(d => [d.name, d]))
    for (const m of filteredMeasures) {
      const detail = detailByName.get(m)
      const folder = detail?.folder || ''
      if (!folderMap.has(folder)) folderMap.set(folder, [])
      folderMap.get(folder)!.push(m)
    }
  } else {
    folderMap.set('', filteredMeasures)
  }
  
  // Sort folders: empty string last, then alphabetical
  const sortedFolders = [...folderMap.keys()].sort((a, b) => {
    if (!a) return 1
    if (!b) return -1
    return a.localeCompare(b)
  })
  
  const toggleFolder = (folder: string) => {
    setOpenFolders(prev => ({ ...prev, [folder]: !(prev[folder] ?? true) }))
  }

  return (
    <Collapsible open={isOpen} onOpenChange={setIsOpen}>
      <CollapsibleTrigger asChild>
        <Button
          variant="ghost"
          className="w-full justify-start gap-2 px-2 h-8 font-normal hover:bg-accent"
          data-testid="measures-standalone"
        >
          {isOpen ? (
            <ChevronDown className="h-4 w-4 shrink-0" />
          ) : (
            <ChevronRight className="h-4 w-4 shrink-0" />
          )}
          <FunctionSquare className="h-4 w-4 shrink-0 text-yellow-600" />
          <span className="truncate">Measures</span>
        </Button>
      </CollapsibleTrigger>
      <CollapsibleContent>
        <div className="ml-4 border-l pl-2">
          {sortedFolders.map(folder => {
            const folderMeasures = folderMap.get(folder)!
            if (!folder) {
              // No-folder measures render directly
              return folderMeasures.map((measure) => {
                const isUsed = usedFieldKeys?.has(`measure:${measure}`)
                return (
                <div
                  key={measure}
                  className={cn(
                    "flex items-center gap-2 px-2 py-1 text-sm hover:bg-accent rounded cursor-grab group",
                    isUsed && "bg-primary/8 font-medium"
                  )}
                  draggable
                  data-testid={`measure-${measure}`}
                  data-drag-type="measure"
                  data-drag-measure={measure}
                  onDragStart={(e) => {
                    e.dataTransfer.setData(
                      'application/json',
                      JSON.stringify({ type: 'MeasureRef', name: getMeasureName(measure) })
                    )
                    e.dataTransfer.effectAllowed = 'copy'
                  }}
                  onClick={() => setFormulaBarSelection({ kind: 'measure', name: measure })}
                >
                  <GripVertical className="h-3 w-3 opacity-0 group-hover:opacity-50" />
                  <FunctionSquare className={cn("h-4 w-4 shrink-0", isUsed ? "text-primary" : "text-yellow-600")} />
                  <span className="truncate">{measure}</span>
                  {isUsed && <span className="ml-auto text-[9px] text-primary/70 shrink-0">in use</span>}
                </div>
              )})
            }
            // Folder group
            const isFolderOpen = openFolders[folder] ?? true
            return (
              <Collapsible key={`folder-${folder}`} open={isFolderOpen} onOpenChange={() => toggleFolder(folder)}>
                <CollapsibleTrigger asChild>
                  <Button
                    variant="ghost"
                    className="w-full justify-start gap-2 px-2 h-7 font-normal hover:bg-accent text-xs"
                    data-testid={`measure-folder-${folder}`}
                  >
                    {isFolderOpen ? (
                      <ChevronDown className="h-3 w-3 shrink-0" />
                    ) : (
                      <ChevronRight className="h-3 w-3 shrink-0" />
                    )}
                    <span className="truncate text-muted-foreground">{folder}</span>
                    <span className="text-[10px] text-muted-foreground ml-auto">({folderMeasures.length})</span>
                  </Button>
                </CollapsibleTrigger>
                <CollapsibleContent>
                  <div className="ml-2">
                    {folderMeasures.map((measure) => {
                      const isUsed = usedFieldKeys?.has(`measure:${measure}`)
                      return (
                      <div
                        key={measure}
                        className={cn(
                          "flex items-center gap-2 px-2 py-1 text-sm hover:bg-accent rounded cursor-grab group",
                          isUsed && "bg-primary/8 font-medium"
                        )}
                        draggable
                        data-testid={`measure-${measure}`}
                        data-drag-type="measure"
                        data-drag-measure={measure}
                        onDragStart={(e) => {
                          e.dataTransfer.setData(
                            'application/json',
                            JSON.stringify({ type: 'MeasureRef', name: getMeasureName(measure) })
                          )
                          e.dataTransfer.effectAllowed = 'copy'
                        }}
                        onClick={() => setFormulaBarSelection({ kind: 'measure', name: measure })}
                      >
                        <GripVertical className="h-3 w-3 opacity-0 group-hover:opacity-50" />
                        <FunctionSquare className={cn("h-4 w-4 shrink-0", isUsed ? "text-primary" : "text-yellow-600")} />
                        <span className="truncate">{measure}</span>
                        {isUsed && <span className="ml-auto text-[9px] text-primary/70 shrink-0">in use</span>}
                      </div>
                    )})}
                  </div>
                </CollapsibleContent>
              </Collapsible>
            )
          })}
        </div>
      </CollapsibleContent>
    </Collapsible>
  )
}

// Calculation Groups section for Fields pane
function FieldsCalcGroups({ calcGroupDefs, tables, searchTerm, expandGeneration, expandDefault }: { 
  calcGroupDefs: Record<string, CalcGroupDef>
  tables: TableInfo[]
  searchTerm: string
  expandGeneration?: number
  expandDefault?: boolean
}) {
  // Build map of group_name -> virtual table for column display
  const virtualTableMap = new Map<string, TableInfo>()
  for (const t of tables) {
    if (t.semantic_type === 'calculation_group' && t.group_name) {
      virtualTableMap.set(t.group_name, t)
    }
  }
  
  const entries = Object.entries(calcGroupDefs)
  const [isOpen, setIsOpen] = useState(true)
  
  useEffect(() => {
    if (expandGeneration !== undefined && expandGeneration > 0) {
      setIsOpen(!!expandDefault)
    }
  }, [expandGeneration, expandDefault])

  // Filter entries based on search
  const filteredEntries = entries.filter(([groupName, def]) => {
    const items = def.items || []
    const itemMatches = items.some(item =>
      item.name.toLowerCase().includes(searchTerm.toLowerCase())
    )
    const groupMatch = groupName.toLowerCase().includes(searchTerm.toLowerCase())
    return !searchTerm || groupMatch || itemMatches
  })

  if (searchTerm && filteredEntries.length === 0) return null
  
  return (
    <Collapsible open={isOpen} onOpenChange={setIsOpen}>
      <CollapsibleTrigger asChild>
        <Button
          variant="ghost"
          className="w-full justify-start gap-2 px-2 h-8 font-normal hover:bg-accent"
          data-testid="fields-calc-groups"
        >
          {isOpen ? <ChevronDown className="h-4 w-4 shrink-0" /> : <ChevronRight className="h-4 w-4 shrink-0" />}
          <Layers className="h-4 w-4 shrink-0 text-purple-600" />
          <span className="truncate">Calculation Groups</span>
        </Button>
      </CollapsibleTrigger>
      <CollapsibleContent>
        <div className="ml-4 border-l pl-2">
          {(searchTerm ? filteredEntries : entries).map(([groupName, def]) => {
            const filteredItems = (def.items || []).filter(item =>
              item.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
              groupName.toLowerCase().includes(searchTerm.toLowerCase())
            )
            const virtualTable = virtualTableMap.get(groupName)
            return (
              <FieldsCalcGroupItem
                key={groupName}
                groupName={groupName}
                virtualTable={virtualTable}
                items={searchTerm ? filteredItems : (def.items || [])}
                expandGeneration={expandGeneration}
                expandDefault={expandDefault}
              />
            )
          })}
        </div>
      </CollapsibleContent>
    </Collapsible>
  )
}

function FieldsCalcGroupItem({ groupName, virtualTable, items, expandGeneration, expandDefault }: {
  groupName: string
  virtualTable?: TableInfo
  items: Array<{ name: string; expression: string }>
  expandGeneration?: number
  expandDefault?: boolean
}) {
  const [isOpen, setIsOpen] = useState(true)
  const [itemsOpen, setItemsOpen] = useState(true)
  const setFormulaBarSelection = useFormulaBarStore(s => s.setSelection)
  
  useEffect(() => {
    if (expandGeneration !== undefined && expandGeneration > 0) {
      setIsOpen(!!expandDefault)
      setItemsOpen(!!expandDefault)
    }
  }, [expandGeneration, expandDefault])

  const tableName = virtualTable?.name || `CalcGroup_${groupName}`
  const columns = virtualTable?.columns || [groupName]

  return (
    <Collapsible open={isOpen} onOpenChange={setIsOpen}>
      <CollapsibleTrigger asChild>
        <Button
          variant="ghost"
          className="w-full justify-start gap-2 px-2 h-8 font-normal hover:bg-accent"
          data-testid={`fields-calc-group-${groupName}`}
        >
          {isOpen ? <ChevronDown className="h-4 w-4 shrink-0" /> : <ChevronRight className="h-4 w-4 shrink-0" />}
          <Layers className="h-4 w-4 shrink-0 text-purple-600" />
          <span className="truncate">{tableName}</span>
        </Button>
      </CollapsibleTrigger>
      <CollapsibleContent>
        <div className="ml-4 border-l pl-2">
          {/* Table Columns */}
          {columns.map((col) => (
            <div
              key={col}
              className="flex items-center gap-2 px-2 py-1 text-sm hover:bg-accent rounded cursor-grab group"
              data-testid={`fields-calc-group-col-${groupName}-${col}`}
              title={`${tableName}[${col}]`}
              draggable
              onDragStart={(e) => {
                e.dataTransfer.setData(
                  'application/json',
                  JSON.stringify({ type: 'ColumnRef', table: tableName, column: col })
                )
                e.dataTransfer.effectAllowed = 'copy'
              }}
            >
              <GripVertical className="h-3 w-3 opacity-0 group-hover:opacity-50" />
              <Type className="h-4 w-4 shrink-0 text-muted-foreground" />
              <span className="truncate">{col}</span>
            </div>
          ))}
          
          {/* Calculation Items */}
          {items.length > 0 && (
            <Collapsible open={itemsOpen} onOpenChange={setItemsOpen}>
              <CollapsibleTrigger asChild>
                <Button
                  variant="ghost"
                  className="w-full justify-start gap-2 px-2 h-7 font-normal text-xs hover:bg-accent"
                >
                  {itemsOpen ? <ChevronDown className="h-3 w-3 shrink-0" /> : <ChevronRight className="h-3 w-3 shrink-0" />}
                  <span className="truncate text-muted-foreground">Items ({items.length})</span>
                </Button>
              </CollapsibleTrigger>
              <CollapsibleContent>
                <div className="ml-4 border-l pl-2">
                  {items.map((item) => (
                    <div
                      key={item.name}
                      className="flex items-center gap-2 px-2 py-1 text-sm hover:bg-accent rounded cursor-pointer"
                      data-testid={`fields-calc-item-${groupName}-${item.name}`}
                      onClick={() => setFormulaBarSelection({ kind: 'calc_item', group: groupName, item: item.name })}
                    >
                      <Calculator className="h-4 w-4 shrink-0 text-purple-500" />
                      <span className="truncate">{item.name}</span>
                    </div>
                  ))}
                </div>
              </CollapsibleContent>
            </Collapsible>
          )}
        </div>
      </CollapsibleContent>
    </Collapsible>
  )
}

// Hierarchies section for Fields pane
function FieldsHierarchies({ hierarchies, searchTerm, expandGeneration, expandDefault }: {
  hierarchies: Record<string, HierarchyDef>
  searchTerm: string
  expandGeneration?: number
  expandDefault?: boolean
}) {
  const [isOpen, setIsOpen] = useState(true)
  
  useEffect(() => {
    if (expandGeneration !== undefined && expandGeneration > 0) {
      setIsOpen(!!expandDefault)
    }
  }, [expandGeneration, expandDefault])

  const entries = Object.entries(hierarchies)
    .sort(([a], [b]) => a.localeCompare(b))

  // Filter entries based on search
  const filteredEntries = entries.filter(([name, def]) => {
    const term = searchTerm.toLowerCase()
    const levelMatches = (def.levels || []).some(level =>
      level.column.toLowerCase().includes(term) ||
      (level.name || level.column).toLowerCase().includes(term)
    )
    const tableMatch = def.table.toLowerCase().includes(term)
    const nameMatch = name.toLowerCase().includes(term)
    return !searchTerm || nameMatch || tableMatch || levelMatches
  })

  if (searchTerm && filteredEntries.length === 0) return null

  return (
    <Collapsible open={isOpen} onOpenChange={setIsOpen}>
      <CollapsibleTrigger asChild>
        <Button
          variant="ghost"
          className="w-full justify-start gap-2 px-2 h-8 font-normal hover:bg-accent"
          data-testid="fields-hierarchies"
        >
          {isOpen ? <ChevronDown className="h-4 w-4 shrink-0" /> : <ChevronRight className="h-4 w-4 shrink-0" />}
          <ListTree className="h-4 w-4 shrink-0 text-emerald-600" />
          <span className="truncate">Hierarchies</span>
        </Button>
      </CollapsibleTrigger>
      <CollapsibleContent>
        <div className="ml-4 border-l pl-2">
          {(searchTerm ? filteredEntries : entries).map(([name, def]) => (
            <FieldsHierarchyItem
              key={name}
              hierarchyName={name}
              def={def}
              expandGeneration={expandGeneration}
              expandDefault={expandDefault}
            />
          ))}
        </div>
      </CollapsibleContent>
    </Collapsible>
  )
}

function FieldsHierarchyItem({ hierarchyName, def, expandGeneration, expandDefault }: {
  hierarchyName: string
  def: HierarchyDef
  expandGeneration?: number
  expandDefault?: boolean
}) {
  const [isOpen, setIsOpen] = useState(true)

  useEffect(() => {
    if (expandGeneration !== undefined && expandGeneration > 0) {
      setIsOpen(!!expandDefault)
    }
  }, [expandGeneration, expandDefault])

  return (
    <Collapsible open={isOpen} onOpenChange={setIsOpen}>
      <CollapsibleTrigger asChild>
        <Button
          variant="ghost"
          className="w-full justify-start gap-2 px-2 h-8 font-normal hover:bg-accent cursor-grab"
          data-testid={`fields-hierarchy-${hierarchyName}`}
          draggable
          onDragStart={(e) => {
            e.dataTransfer.setData(
              'application/json',
              JSON.stringify({ type: 'HierarchyRef', name: hierarchyName })
            )
            e.dataTransfer.effectAllowed = 'copy'
          }}
        >
          {isOpen ? <ChevronDown className="h-4 w-4 shrink-0" /> : <ChevronRight className="h-4 w-4 shrink-0" />}
          <ListTree className="h-4 w-4 shrink-0 text-emerald-600" />
          <span className="truncate">{hierarchyName}</span>
        </Button>
      </CollapsibleTrigger>
      <CollapsibleContent>
        <div className="ml-4 border-l pl-2">
          <div className="text-[10px] text-muted-foreground px-2 py-1">
            {def.table}
          </div>
          {(def.levels || []).map((level) => (
            <div
              key={`${hierarchyName}-${level.name || level.column}`}
              className="flex items-center gap-2 px-2 py-1 text-sm hover:bg-accent rounded cursor-grab group"
              draggable
              data-testid={`fields-hierarchy-level-${hierarchyName}-${level.name || level.column}`}
              onDragStart={(e) => {
                e.dataTransfer.setData(
                  'application/json',
                  JSON.stringify({ type: 'HierarchyRef', name: hierarchyName })
                )
                e.dataTransfer.effectAllowed = 'copy'
              }}
            >
              <GripVertical className="h-3 w-3 opacity-0 group-hover:opacity-50" />
              <Type className="h-4 w-4 shrink-0 text-muted-foreground" />
              <span className="truncate">{level.name || level.column}</span>
              {level.name && level.column !== level.name && (
                <span className="ml-auto text-[10px] text-muted-foreground truncate max-w-[120px]" title={level.column}>
                  {level.column}
                </span>
              )}
            </div>
          ))}
        </div>
      </CollapsibleContent>
    </Collapsible>
  )
}

// Field Parameters section for Fields pane
function FieldsFieldParams({ fieldParamDefs, tables, searchTerm, expandGeneration, expandDefault }: {
  fieldParamDefs: Record<string, FieldParameterDef>
  tables: TableInfo[]
  searchTerm: string
  expandGeneration?: number
  expandDefault?: boolean
}) {
  // Build map of param_name -> virtual table for column display
  const virtualTableMap = new Map<string, TableInfo>()
  for (const t of tables) {
    if (t.semantic_type === 'field_parameter' && t.param_name) {
      virtualTableMap.set(t.param_name, t)
    }
  }
  const [isOpen, setIsOpen] = useState(true)
  const entries = Object.entries(fieldParamDefs)
  
  useEffect(() => {
    if (expandGeneration !== undefined && expandGeneration > 0) {
      setIsOpen(!!expandDefault)
    }
  }, [expandGeneration, expandDefault])

  // Filter entries based on search
  const filteredEntries = entries.filter(([paramName, def]) => {
    const items = def.items || []
    const itemMatches = items.some(item =>
      item.name.toLowerCase().includes(searchTerm.toLowerCase())
    )
    const paramMatch = paramName.toLowerCase().includes(searchTerm.toLowerCase())
    return !searchTerm || paramMatch || itemMatches
  })

  if (searchTerm && filteredEntries.length === 0) return null
  
  return (
    <Collapsible open={isOpen} onOpenChange={setIsOpen}>
      <CollapsibleTrigger asChild>
        <Button
          variant="ghost"
          className="w-full justify-start gap-2 px-2 h-8 font-normal hover:bg-accent"
          data-testid="fields-field-params"
        >
          {isOpen ? <ChevronDown className="h-4 w-4 shrink-0" /> : <ChevronRight className="h-4 w-4 shrink-0" />}
          <ListFilter className="h-4 w-4 shrink-0 text-blue-600" />
          <span className="truncate">Field Parameters</span>
        </Button>
      </CollapsibleTrigger>
      <CollapsibleContent>
        <div className="ml-4 border-l pl-2">
          {(searchTerm ? filteredEntries : entries).map(([paramName, def]) => {
            const filteredItems = (def.items || []).filter(item =>
              item.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
              paramName.toLowerCase().includes(searchTerm.toLowerCase())
            )
            const virtualTable = virtualTableMap.get(paramName)
            return (
              <FieldsFieldParamItem
                key={paramName}
                paramName={paramName}
                virtualTable={virtualTable}
                items={searchTerm ? filteredItems : (def.items || [])}
                expandGeneration={expandGeneration}
                expandDefault={expandDefault}
              />
            )
          })}
        </div>
      </CollapsibleContent>
    </Collapsible>
  )
}

function FieldsFieldParamItem({ paramName, virtualTable, items, expandGeneration, expandDefault }: {
  paramName: string
  virtualTable?: TableInfo
  items: Array<{ name: string; ref?: { type: string; table?: string; column?: string; name?: string }; sort?: number; [key: string]: unknown }>
  expandGeneration?: number
  expandDefault?: boolean
}) {
  const [isOpen, setIsOpen] = useState(true)
  const [itemsOpen, setItemsOpen] = useState(true)
  const setFormulaBarSelection = useFormulaBarStore(s => s.setSelection)
  
  useEffect(() => {
    if (expandGeneration !== undefined && expandGeneration > 0) {
      setIsOpen(!!expandDefault)
      setItemsOpen(!!expandDefault)
    }
  }, [expandGeneration, expandDefault])

  /** Format item ref as Power BI-style NAMEOF reference */
  const formatRef = (ref?: { type: string; table?: string; column?: string; name?: string }) => {
    if (!ref) return null
    if (ref.type === 'ColumnRef' && ref.table && ref.column) {
      return `NAMEOF('${ref.table}'[${ref.column}])`
    }
    if (ref.type === 'MeasureRef' && ref.name) {
      return `NAMEOF([${ref.name}])`
    }
    return null
  }

  const tableName = virtualTable?.name || `FieldParams_${paramName}`
  // Derive columns: standard columns + custom property columns from items
  const standardColumns = virtualTable?.columns || [paramName, `${paramName} Label`, `${paramName} Sort`]
  const customKeys: string[] = []
  const standardItemKeys = new Set(['name', 'ref', 'sort', 'sortColumn'])
  for (const item of items) {
    for (const k of Object.keys(item)) {
      if (!standardItemKeys.has(k) && !customKeys.includes(k)) {
        customKeys.push(k)
      }
    }
  }
  // Add custom columns like "AxisField Locale" to the field pane columns
  const extraColumns = customKeys.map(k => `${paramName} ${k.charAt(0).toUpperCase() + k.slice(1)}`)
  const columns = [...standardColumns, ...extraColumns.filter(ec => !standardColumns.includes(ec))]

  return (
    <Collapsible open={isOpen} onOpenChange={setIsOpen}>
      <CollapsibleTrigger asChild>
        <Button
          variant="ghost"
          className="w-full justify-start gap-2 px-2 h-8 font-normal hover:bg-accent"
          data-testid={`fields-field-param-${paramName}`}
          onClick={() => {
            setFormulaBarSelection({ kind: 'field_parameter', name: paramName })
          }}
        >
          {isOpen ? <ChevronDown className="h-4 w-4 shrink-0" /> : <ChevronRight className="h-4 w-4 shrink-0" />}
          <ListFilter className="h-4 w-4 shrink-0 text-blue-600" />
          <span className="truncate">{tableName}</span>
        </Button>
      </CollapsibleTrigger>
      <CollapsibleContent>
        <div className="ml-4 border-l pl-2">
          {/* Table Columns */}
          {columns.map((col) => (
            <div
              key={col}
              className="flex items-center gap-2 px-2 py-1 text-sm hover:bg-accent rounded cursor-grab group"
              data-testid={`fields-field-param-col-${paramName}-${col}`}
              title={`${tableName}[${col}]`}
              draggable
              onDragStart={(e) => {
                e.dataTransfer.setData(
                  'application/json',
                  JSON.stringify({ type: 'ColumnRef', table: tableName, column: col })
                )
                e.dataTransfer.effectAllowed = 'copy'
              }}
            >
              <GripVertical className="h-3 w-3 opacity-0 group-hover:opacity-50" />
              <Type className="h-4 w-4 shrink-0 text-muted-foreground" />
              <span className="truncate">{col}</span>
            </div>
          ))}
          
          {/* Items */}
          {items.length > 0 && (
            <Collapsible open={itemsOpen} onOpenChange={setItemsOpen}>
              <CollapsibleTrigger asChild>
                <Button
                  variant="ghost"
                  className="w-full justify-start gap-2 px-2 h-7 font-normal text-xs hover:bg-accent"
                >
                  {itemsOpen ? <ChevronDown className="h-3 w-3 shrink-0" /> : <ChevronRight className="h-3 w-3 shrink-0" />}
                  <span className="truncate text-muted-foreground">Items ({items.length})</span>
                </Button>
              </CollapsibleTrigger>
              <CollapsibleContent>
                <div className="ml-4 border-l pl-2">
                  {items.map((item) => {
                    const refStr = formatRef(item.ref)
                    return (
                      <div
                        key={item.name}
                        className="flex items-center gap-2 px-2 py-1 text-sm hover:bg-accent rounded cursor-pointer"
                        data-testid={`fields-field-param-item-${paramName}-${item.name}`}
                        title={refStr || item.name}
                      >
                        <Type className="h-4 w-4 shrink-0 text-muted-foreground" />
                        <span className="truncate">{item.name}</span>
                      </div>
                    )
                  })}
                </div>
              </CollapsibleContent>
            </Collapsible>
          )}
        </div>
      </CollapsibleContent>
    </Collapsible>
  )
}

// What-If Parameters section for Fields pane
function FieldsWhatIfParams({ whatIfDefs, tables, searchTerm, expandGeneration, expandDefault }: {
  whatIfDefs: Record<string, WhatIfParameterDef>
  tables: TableInfo[]
  searchTerm: string
  expandGeneration?: number
  expandDefault?: boolean
}) {
  // Build map of param_name -> virtual table for column display
  const virtualTableMap = new Map<string, TableInfo>()
  for (const t of tables) {
    if (t.semantic_type === 'what_if_parameter' && t.param_name) {
      virtualTableMap.set(t.param_name, t)
    }
  }
  
  const setFormulaBarSelection = useFormulaBarStore(s => s.setSelection)
  const entries = Object.entries(whatIfDefs).filter(([name]) =>
    name.toLowerCase().includes(searchTerm.toLowerCase())
  )
  if (entries.length === 0 && searchTerm) return null
  
  const [isOpen, setIsOpen] = useState(true)
  
  useEffect(() => {
    if (expandGeneration !== undefined && expandGeneration > 0) {
      setIsOpen(!!expandDefault)
    }
  }, [expandGeneration, expandDefault])

  return (
    <Collapsible open={isOpen} onOpenChange={setIsOpen}>
      <CollapsibleTrigger asChild>
        <Button
          variant="ghost"
          className="w-full justify-start gap-2 px-2 h-8 font-normal hover:bg-accent"
          data-testid="fields-what-if-params"
        >
          {isOpen ? <ChevronDown className="h-4 w-4 shrink-0" /> : <ChevronRight className="h-4 w-4 shrink-0" />}
          <Gauge className="h-4 w-4 shrink-0 text-orange-600" />
          <span className="truncate">What-If Parameters</span>
        </Button>
      </CollapsibleTrigger>
      <CollapsibleContent>
        <div className="ml-4 border-l pl-2">
          {entries.map(([name, def]) => {
            const virtualTable = virtualTableMap.get(name)
            const tableName = virtualTable?.name || `WhatIf_${name}`
            const columns = virtualTable?.columns || ['Value', 'Label', 'Sort']
            return (
              <FieldsWhatIfItem
                key={name}
                name={name}
                def={def}
                tableName={tableName}
                columns={columns}
                onSelect={() => setFormulaBarSelection({ kind: 'what_if_parameter', name })}
              />
            )
          })}
        </div>
      </CollapsibleContent>
    </Collapsible>
  )
}

function FieldsWhatIfItem({ name, def, tableName, columns, onSelect }: {
  name: string
  def: WhatIfParameterDef
  tableName: string
  columns: string[]
  onSelect: () => void
}) {
  const [isOpen, setIsOpen] = useState(true)
  
  return (
    <Collapsible open={isOpen} onOpenChange={setIsOpen}>
      <CollapsibleTrigger asChild>
        <Button
          variant="ghost"
          className="w-full justify-start gap-2 px-2 h-8 font-normal hover:bg-accent"
          data-testid={`fields-what-if-${name}`}
          onClick={onSelect}
        >
          {isOpen ? <ChevronDown className="h-4 w-4 shrink-0" /> : <ChevronRight className="h-4 w-4 shrink-0" />}
          <Gauge className="h-4 w-4 shrink-0 text-orange-600" />
          <span className="truncate">{tableName}</span>
        </Button>
      </CollapsibleTrigger>
      <CollapsibleContent>
        <div className="ml-4 border-l pl-2">
          {/* Table Columns */}
          {columns.map((col) => (
            <div
              key={col}
              className="flex items-center gap-2 px-2 py-1 text-sm hover:bg-accent rounded cursor-grab group"
              data-testid={`fields-what-if-col-${name}-${col}`}
              title={`${tableName}[${col}]`}
              draggable
              onDragStart={(e) => {
                e.dataTransfer.setData(
                  'application/json',
                  JSON.stringify({ type: 'ColumnRef', table: tableName, column: col })
                )
                e.dataTransfer.effectAllowed = 'copy'
              }}
            >
              <GripVertical className="h-3 w-3 opacity-0 group-hover:opacity-50" />
              <Type className="h-4 w-4 shrink-0 text-muted-foreground" />
              <span className="truncate">{col}</span>
            </div>
          ))}
          
          {/* Definition info */}
          <div className="px-2 py-1 text-[10px] text-muted-foreground">
            <div className="font-mono">GENERATESERIES({def.min}, {def.max}, {def.step})</div>
            <div className="flex gap-3 mt-0.5">
              {def.format && <span>Format: {def.format}</span>}
              <span>Default: {def.default}</span>
            </div>
          </div>
        </div>
      </CollapsibleContent>
    </Collapsible>
  )
}

// Explanations / EDU section for Fields pane
// Renders EDU metrics as draggable measure items (same drag format as regular measures)
function FieldsExplanations({ explanations, searchTerm, expandGeneration, expandDefault }: {
  explanations: PlaybookMeta[]
  searchTerm: string
  expandGeneration?: number
  expandDefault?: boolean
}) {
  const [isOpen, setIsOpen] = useState(true)
  
  useEffect(() => {
    if (expandGeneration !== undefined && expandGeneration > 0) {
      setIsOpen(!!expandDefault)
    }
  }, [expandGeneration, expandDefault])
  
  if (!explanations || explanations.length === 0) return null

  // Filter playbooks based on search
  const filteredPlaybooks = explanations.filter((playbook) => {
    const playbookMatch = playbook.name.toLowerCase().includes(searchTerm.toLowerCase())
    const eduMatch = (playbook.edus || []).some(edu =>
      edu.metric.toLowerCase().includes(searchTerm.toLowerCase()) ||
      edu.id.toLowerCase().includes(searchTerm.toLowerCase())
    )
    return !searchTerm || playbookMatch || eduMatch
  })

  if (searchTerm && filteredPlaybooks.length === 0) return null

  return (
    <Collapsible open={isOpen} onOpenChange={setIsOpen}>
      <CollapsibleTrigger asChild>
        <Button
          variant="ghost"
          className="w-full justify-start gap-2 px-2 h-8 font-normal hover:bg-accent"
          data-testid="fields-explanations"
        >
          {isOpen ? <ChevronDown className="h-4 w-4 shrink-0" /> : <ChevronRight className="h-4 w-4 shrink-0" />}
          <Lightbulb className="h-4 w-4 shrink-0 text-amber-500" />
          <span className="truncate">Explanations</span>
        </Button>
      </CollapsibleTrigger>
      <CollapsibleContent>
        <div className="ml-4 border-l pl-2">
          {(searchTerm ? filteredPlaybooks : explanations).map((playbook) => (
            <FieldsPlaybookItem
              key={playbook.name}
              playbook={playbook}
              searchTerm={searchTerm}
              expandGeneration={expandGeneration}
              expandDefault={expandDefault}
            />
          ))}
        </div>
      </CollapsibleContent>
    </Collapsible>
  )
}

function FieldsPlaybookItem({ playbook, searchTerm, expandGeneration, expandDefault }: {
  playbook: PlaybookMeta
  searchTerm: string
  expandGeneration?: number
  expandDefault?: boolean
}) {
  const [isOpen, setIsOpen] = useState(true)
  const setFormulaBarSelection = useFormulaBarStore(s => s.setSelection)

  useEffect(() => {
    if (expandGeneration !== undefined && expandGeneration > 0) {
      setIsOpen(!!expandDefault)
    }
  }, [expandGeneration, expandDefault])

  const filteredEdus = (playbook.edus || []).filter(edu =>
    edu.metric.toLowerCase().includes(searchTerm.toLowerCase()) ||
    edu.id.toLowerCase().includes(searchTerm.toLowerCase()) ||
    playbook.name.toLowerCase().includes(searchTerm.toLowerCase())
  )
  if (searchTerm && filteredEdus.length === 0 && !playbook.name.toLowerCase().includes(searchTerm.toLowerCase())) {
    return null
  }
  const edusToShow = searchTerm ? filteredEdus : (playbook.edus || [])

  return (
    <Collapsible open={isOpen} onOpenChange={setIsOpen}>
      <CollapsibleTrigger asChild>
        <Button
          variant="ghost"
          className="w-full justify-start gap-2 px-2 h-8 font-normal hover:bg-accent"
          data-testid={`fields-playbook-${playbook.name}`}
        >
          {isOpen ? <ChevronDown className="h-4 w-4 shrink-0" /> : <ChevronRight className="h-4 w-4 shrink-0" />}
          <Lightbulb className="h-4 w-4 shrink-0 text-amber-500" />
          <span className="truncate">{playbook.name}</span>
          {playbook.description && (
            <span className="text-[10px] text-muted-foreground ml-auto truncate max-w-[120px]">{playbook.description}</span>
          )}
        </Button>
      </CollapsibleTrigger>
      <CollapsibleContent>
        <div className="ml-4 border-l pl-2">
          {edusToShow.map((edu) => {
            const driverCount = (playbook.drivers || []).filter(d => d.parent_edu_id === edu.id).length
            return (
              <div key={edu.id}>
                <div
                  className="flex items-center gap-2 px-2 py-1 text-sm hover:bg-accent rounded cursor-grab group"
                  draggable
                  data-testid={`fields-edu-${edu.id}`}
                  data-drag-type="measure"
                  data-drag-measure={edu.metric}
                  onDragStart={(e) => {
                    e.dataTransfer.setData(
                      'application/json',
                      JSON.stringify({ type: 'MeasureRef', name: edu.metric })
                    )
                    e.dataTransfer.effectAllowed = 'copy'
                  }}
                  onClick={() => setFormulaBarSelection({ kind: 'measure', name: edu.metric })}
                >
                  <GripVertical className="h-3 w-3 opacity-0 group-hover:opacity-50" />
                  <div className="relative shrink-0">
                    <FunctionSquare className="h-4 w-4 text-yellow-600" />
                    <Lightbulb className="h-2.5 w-2.5 text-amber-500 absolute -top-1 -right-1" />
                  </div>
                  <span className="truncate">{edu.metric}</span>
                  <span className="text-[10px] text-muted-foreground px-1 py-0.5 bg-muted rounded ml-auto shrink-0">
                    {(edu.comparator ?? '').replace(/_/g, ' ')}
                  </span>
                  {driverCount > 0 && (
                    <span className="text-[10px] text-muted-foreground shrink-0" title={`${driverCount} driver${driverCount !== 1 ? 's' : ''}`}>
                      {driverCount}d
                    </span>
                  )}
                </div>
                {/* Virtual fields: Value (measure) and Description (dimension) */}
                <div
                  className="flex items-center gap-2 px-2 py-0.5 text-xs hover:bg-accent rounded cursor-grab group ml-4"
                  draggable
                  data-testid={`fields-edu-vf-value-${edu.id}`}
                  data-drag-type="measure"
                  data-drag-measure={`${edu.metric}.Value`}
                  onDragStart={(e) => {
                    e.dataTransfer.setData(
                      'application/json',
                      JSON.stringify({ type: 'EDUVirtualField', field_type: 'Value', edu_id: edu.id, playbook: playbook.name, name: `${edu.metric}.Value` })
                    )
                    e.dataTransfer.effectAllowed = 'copy'
                  }}
                >
                  <GripVertical className="h-2.5 w-2.5 opacity-0 group-hover:opacity-50" />
                  <FunctionSquare className="h-3 w-3 text-yellow-500" />
                  <span className="truncate text-muted-foreground">.Value</span>
                  <span className="text-[9px] text-muted-foreground ml-auto">Σ delta</span>
                </div>
                <div
                  className="flex items-center gap-2 px-2 py-0.5 text-xs hover:bg-accent rounded cursor-grab group ml-4"
                  draggable
                  data-testid={`fields-edu-vf-desc-${edu.id}`}
                  data-drag-type="dimension"
                  data-drag-column={`${edu.metric}.Description`}
                  onDragStart={(e) => {
                    e.dataTransfer.setData(
                      'application/json',
                      JSON.stringify({ type: 'EDUVirtualField', field_type: 'Description', edu_id: edu.id, playbook: playbook.name, name: `${edu.metric}.Description` })
                    )
                    e.dataTransfer.effectAllowed = 'copy'
                  }}
                >
                  <GripVertical className="h-2.5 w-2.5 opacity-0 group-hover:opacity-50" />
                  <AlignLeft className="h-3 w-3 text-blue-500" />
                  <span className="truncate text-muted-foreground">.Description</span>
                  <span className="text-[9px] text-muted-foreground ml-auto">drivers</span>
                </div>
              </div>
            )
          })}
        </div>
      </CollapsibleContent>
    </Collapsible>
  )
}

// Tables section for Fields pane - with "Tables" parent wrapper
function FieldsTables({ tables, measures, searchTerm, expandGeneration, expandDefault, isModelView, modelLayoutTableSet, usedFieldKeys }: {
  tables: TableInfo[]
  measures: string[]
  searchTerm: string
  expandGeneration?: number
  expandDefault?: boolean
  isModelView: boolean
  modelLayoutTableSet: Set<string> | null
  usedFieldKeys?: Set<string>
}) {
  const [isOpen, setIsOpen] = useState(true)
  
  // Filter out virtual tables (field params, calc groups, what-if params)
  const physicalTables = tables.filter(t => !t.virtual && !t.semantic_type)
  
  useEffect(() => {
    if (expandGeneration !== undefined && expandGeneration > 0) {
      setIsOpen(!!expandDefault)
    }
  }, [expandGeneration, expandDefault])

  // Filter tables based on search
  const filteredTables = physicalTables.filter((table) => {
    const tableMatch = table.name.toLowerCase().includes(searchTerm.toLowerCase())
    const columnMatch = (table.columns || []).some(col =>
      col.toLowerCase().includes(searchTerm.toLowerCase())
    )
    const measureMatch = measures.some(m =>
      m.toLowerCase().includes(searchTerm.toLowerCase()) &&
      m.startsWith(table.name + '[')
    )
    return !searchTerm || tableMatch || columnMatch || measureMatch
  })

  if (searchTerm && filteredTables.length === 0) return null
  if (physicalTables.length === 0) return null
  
  return (
    <Collapsible open={isOpen} onOpenChange={setIsOpen}>
      <CollapsibleTrigger asChild>
        <Button
          variant="ghost"
          className="w-full justify-start gap-2 px-2 h-8 font-normal hover:bg-accent"
          data-testid="fields-tables"
        >
          {isOpen ? <ChevronDown className="h-4 w-4 shrink-0" /> : <ChevronRight className="h-4 w-4 shrink-0" />}
          <Table2 className="h-4 w-4 shrink-0 text-slate-600" />
          <span className="truncate">Tables</span>
        </Button>
      </CollapsibleTrigger>
      <CollapsibleContent>
        <div className="ml-4 border-l pl-2">
          {(searchTerm ? filteredTables : physicalTables).map((table) => (
            <TableItem 
              key={table.name} 
              table={table}
              measures={measures}
              searchTerm={searchTerm}
              expandGeneration={expandGeneration}
              expandDefault={expandDefault}
              draggableAsTable={isModelView && modelLayoutTableSet !== null}
              isInModelLayout={modelLayoutTableSet !== null && modelLayoutTableSet.has(table.name.toUpperCase())}
              usedFieldKeys={usedFieldKeys}
            />
          ))}
        </div>
      </CollapsibleContent>
    </Collapsible>
  )
}

// Role item component for security view
interface Role {
  name: string
  rls?: Record<string, string>
  ols?: {
    tables?: string[]
    measures?: string[]
    columns?: Record<string, string[]>
  }
}

interface RoleItemProps {
  role: Role
  isActive: boolean
  onSelect: () => void
  onEdit: () => void
}

function RoleItem({ role, isActive, onSelect, onEdit }: RoleItemProps) {
  const [isOpen, setIsOpen] = useState(false)
  const rlsTables = role.rls ? Object.keys(role.rls) : []
  // Collect OLS-hidden items: tables, measures, and columns
  const olsHiddenTables = role.ols?.tables || []
  const olsHiddenMeasures = role.ols?.measures || []
  const olsHiddenColumns = role.ols?.columns ? Object.keys(role.ols.columns) : []
  const hasOls = olsHiddenTables.length > 0 || olsHiddenMeasures.length > 0 || olsHiddenColumns.length > 0
  const hasRules = rlsTables.length > 0 || hasOls

  return (
    <div className={cn(
      "rounded-md border",
      isActive && "border-primary bg-primary/5"
    )}>
      <div className="flex items-center gap-2 px-3 py-2">
        <button
          onClick={() => setIsOpen(!isOpen)}
          disabled={!hasRules}
          className="p-0.5 hover:bg-accent rounded disabled:opacity-30"
        >
          {isOpen ? (
            <ChevronDown className="h-4 w-4" />
          ) : (
            <ChevronRight className="h-4 w-4" />
          )}
        </button>
        <Shield className={cn(
          "h-4 w-4",
          isActive ? "text-primary" : "text-muted-foreground"
        )} />
        <span className="text-sm font-medium flex-1">{role.name}</span>
        <Button
          variant="ghost"
          size="icon"
          className="h-6 w-6"
          onClick={onEdit}
          data-testid={`edit-role-${role.name}`}
          aria-label="Edit role"
          title="Edit role"
        >
          <Pencil className="h-3 w-3" />
        </Button>
        <Button
          variant={isActive ? "default" : "outline"}
          size="sm"
          className="h-6 text-xs"
          onClick={onSelect}
        >
          {isActive ? 'Active' : 'Switch'}
        </Button>
      </div>

      {isOpen && hasRules && (
        <div className="px-3 pb-3 pt-1 border-t space-y-3">
          {/* RLS rules */}
          {rlsTables.length > 0 && (
            <div>
              <div className="flex items-center gap-1 mb-2">
                <Eye className="h-3 w-3 text-muted-foreground" />
                <span className="text-xs font-medium">Row-Level Security</span>
              </div>
              <div className="space-y-1">
                {rlsTables.map(table => (
                  <Tooltip key={table}>
                    <TooltipTrigger asChild>
                      <div className="text-xs px-2 py-1 bg-muted rounded cursor-help">
                        <span className="font-medium">{table}</span>
                        <span className="text-muted-foreground ml-1">(filtered)</span>
                      </div>
                    </TooltipTrigger>
                    <TooltipContent side="right" className="max-w-xs">
                      <code className="text-xs">{role.rls![table]}</code>
                    </TooltipContent>
                  </Tooltip>
                ))}
              </div>
            </div>
          )}

          {/* OLS rules */}
          {hasOls && (
            <div>
              <div className="flex items-center gap-1 mb-2">
                <EyeOff className="h-3 w-3 text-muted-foreground" />
                <span className="text-xs font-medium">Object-Level Security</span>
              </div>
              <div className="space-y-1">
                {olsHiddenTables.length > 0 && (
                  <div className="text-xs px-2 py-1 bg-muted rounded">
                    <span className="font-medium">Hidden tables:</span>
                    <span className="text-muted-foreground ml-1">
                      {olsHiddenTables.join(', ')}
                    </span>
                  </div>
                )}
                {olsHiddenMeasures.length > 0 && (
                  <div className="text-xs px-2 py-1 bg-muted rounded">
                    <span className="font-medium">Hidden measures:</span>
                    <span className="text-muted-foreground ml-1">
                      {olsHiddenMeasures.join(', ')}
                    </span>
                  </div>
                )}
                {olsHiddenColumns.map(table => (
                  <div key={table} className="text-xs px-2 py-1 bg-muted rounded">
                    <span className="font-medium">{table}</span>
                    <span className="text-muted-foreground ml-1">
                      [{role.ols!.columns![table].length} columns hidden]
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export function LeftSidebar({ className }: LeftSidebarProps) {
  const leftSidebarOpen = useAppStore(s => s.leftSidebarOpen)
  const tables = useAppStore(s => s.tables)
  const measures = useAppStore(s => s.measures)
  const relationships = useAppStore(s => s.relationships)
  const roles = useAppStore(s => s.roles)
  const currentRole = useAppStore(s => s.currentRole)
  const setCurrentRole = useAppStore(s => s.setCurrentRole)
  const viewMode = useAppStore(s => s.viewMode)
  const explanations = useAppStore(s => s.explanations)
  const setExplanations = useAppStore(s => s.setExplanations)
  const setFormulaBarSelection = useFormulaBarStore(s => s.setSelection)
  const layouts = useModelViewStore(s => s.layouts)
  const activeLayoutId = useModelViewStore(s => s.activeLayoutId)
  const [searchTerm, setSearchTerm] = useState('')

  // Independent pane open/close state
  const [fieldsOpen, setFieldsOpen] = useState(true)
  const [modelOpen, setModelOpen] = useState(false)

  // Pane resize
  const { width: fieldsWidth, handleProps: fieldsResizeProps } = usePanelResize({ defaultWidth: 260, minWidth: 180, maxWidth: 500, direction: 'right' })
  const { width: modelWidth, handleProps: modelResizeProps } = usePanelResize({ defaultWidth: 260, minWidth: 180, maxWidth: 500, direction: 'right' })

  // Model View: determine if we're in model view and which tables are in the active layout
  const isModelView = viewMode === 'model'
  const activeLayout = useMemo(
    () => layouts.find((l) => l.id === activeLayoutId),
    [layouts, activeLayoutId]
  )
  const modelLayoutTableSet = useMemo(() => {
    if (!isModelView || !activeLayout || activeLayout.visibleTables === null) return null
    return new Set(activeLayout.visibleTables.map((t) => t.toUpperCase()))
  }, [isModelView, activeLayout])

  // Compute used fields from the selected visual's encodings
  const selectedVisualId = useReportStore(s => s.selectedVisualId)
  const visuals = useReportStore(s => s.visuals)
  const { usedFieldKeys } = useMemo(() => {
    if (!selectedVisualId) return { usedFieldKeys: undefined }
    const visual = visuals.find(v => v.id === selectedVisualId)
    if (!visual?.encodings) return { usedFieldKeys: undefined }
    return extractUsedFields(visual.encodings as Record<string, unknown>)
  }, [selectedVisualId, visuals])
  const hierarchyTables = useMemo(() => (tables ?? []).map((t) => ({
    name: t.name,
    columns: t.columns || [],
  })), [tables])
  
  // Model authoring state
  const { 
    measures: rawMeasuresList, 
    calcTables: rawCalcTablesList, 
    calcColumns: rawCalcColumnsList,
    loadMeasures,
    loadCalcTables,
    loadCalcColumns,
    removeMeasure,
    removeCalcTable,
    removeCalcColumn,
  } = useModelAuthoring()
  
  // Apply default fallbacks for potentially undefined arrays
  const measuresList = rawMeasuresList ?? []
  const calcTablesList = rawCalcTablesList ?? []
  const calcColumnsList = rawCalcColumnsList ?? []
  
  // Field Parameters state
  const {
    fieldParams,
    fieldParamDefs,
    selections: _fieldParamSelections,
    load: loadFieldParams,
    updateSelection: _updateFieldParamSelection,
  } = useFieldParameters()
  
  // Calculation Groups state
  const {
    calcGroups,
    calcGroupDefs,
    selections: calcGroupSelections,
    load: loadCalcGroups,
    updateSelection: updateCalcGroupSelection,
  } = useCalcGroups()
  
  // What-If Parameters state
  const {
    whatIfParams,
    whatIfDefs,
    load: loadWhatIfParams,
    updateSelection: updateWhatIfSelection,
    getValue: getWhatIfValue,
  } = useWhatIfParameters()

  const {
    hierarchies,
    isHierarchiesDirty,
    applyHierarchy,
    removeHierarchy,
    resetHierarchiesDraft,
  } = useHierarchies()
  
  // Editor state
  const [measureEditorOpen, setMeasureEditorOpen] = useState(false)
  const [calcTableEditorOpen, setCalcTableEditorOpen] = useState(false)
  const [calcColumnEditorOpen, setCalcColumnEditorOpen] = useState(false)
  const [editingMeasure, setEditingMeasure] = useState<MeasureDetail | undefined>()
  const [editingCalcTable, setEditingCalcTable] = useState<CalcTableDetail | undefined>()
  const [editingCalcColumn, setEditingCalcColumn] = useState<CalcColumnDetail | undefined>()
  
  // Parameter editor state
  const [fieldParamEditorOpen, setFieldParamEditorOpen] = useState(false)
  const [editingFieldParam, setEditingFieldParam] = useState<{ name: string; def: FieldParameterDef } | null>(null)
  
  const [calcGroupEditorOpen, setCalcGroupEditorOpen] = useState(false)
  const [editingCalcGroup, setEditingCalcGroup] = useState<{ name: string; def: CalcGroupDef } | null>(null)
  
  const [whatIfEditorOpen, setWhatIfEditorOpen] = useState(false)
  const [editingWhatIf, setEditingWhatIf] = useState<{ name: string; def: WhatIfParameterDef } | null>(null)

  const [hierarchyEditorOpen, setHierarchyEditorOpen] = useState(false)
  const [editingHierarchy, setEditingHierarchy] = useState<{ name: string; def: HierarchyDef } | null>(null)
  
  // Playbook editor state
  const [playbookEditorOpen, setPlaybookEditorOpen] = useState(false)
  const [editingPlaybook, setEditingPlaybook] = useState<PlaybookMeta | null>(null)
  
  // EDU sub-wizard state (standalone)
  const [eduWizardOpen, setEduWizardOpen] = useState(false)
  
  // Role editor state
  const [roleEditorOpen, setRoleEditorOpen] = useState(false)
  const [editingRole, setEditingRole] = useState<SecurityRoleRaw | null>(null)
  const [rawRoles, setRawRoles] = useState<SecurityRoleRaw[]>([])
  const [defaultRole, setDefaultRole] = useState<string | null>(null)
  const projectPath = useAppStore(s => s.projectPath)
  
  // Model sub-navigation state
  type ModelSection = 'tables' | 'relationships' | 'measures' | 'calc-tables' | 'calc-cols' | 'field-params' | 'calc-groups' | 'what-if' | 'hierarchies' | 'explanations'
  const [modelActiveSection, setModelActiveSection] = useState<ModelSection>('measures')
  
  // Fields pane expand/collapse all counter — increment collapses, decrement expands
  const [fieldsExpandGeneration, setFieldsExpandGeneration] = useState(0)
  const [fieldsAllExpanded, setFieldsAllExpanded] = useState(true)
  const handleExpandAll = useCallback(() => {
    setFieldsExpandGeneration(g => g + 1)
    setFieldsAllExpanded(true)
  }, [])
  const handleCollapseAll = useCallback(() => {
    setFieldsExpandGeneration(g => g + 1)
    setFieldsAllExpanded(false)
  }, [])
  
  // Load raw roles when security tab is active
  const loadRawRoles = async () => {
    try {
      const result = await getSecurityRoles(projectPath || undefined)
      if (!result.error && result.data) {
        setRawRoles(result.data.roles || [])
        setDefaultRole(result.data.default_role)
      }
    } catch (e) {
      console.error('Failed to load raw roles:', e)
    }
  }
  
  // Raw roles are loaded when needed by other components
  // (security tab removed — role selector lives in toolbar)
  
  // Load model data when either pane is open
  useEffect(() => {
    if (fieldsOpen || modelOpen) {
      loadMeasures()
      loadCalcTables()
      loadCalcColumns()
      loadFieldParams()
      loadCalcGroups()
      loadWhatIfParams()
    }
  }, [fieldsOpen, modelOpen, loadMeasures, loadCalcTables, loadCalcColumns, loadFieldParams, loadCalcGroups, loadWhatIfParams])
  
  // Handlers for opening editors
  const openMeasureEditor = (measure?: MeasureDetail) => {
    setEditingMeasure(measure)
    setMeasureEditorOpen(true)
  }
  const closeMeasureEditor = () => {
    setMeasureEditorOpen(false)
    setEditingMeasure(undefined)
    loadMeasures() // Refresh list
  }
  
  const openCalcTableEditor = (calcTable?: CalcTableDetail) => {
    setEditingCalcTable(calcTable)
    setCalcTableEditorOpen(true)
  }
  const closeCalcTableEditor = () => {
    setCalcTableEditorOpen(false)
    setEditingCalcTable(undefined)
    loadCalcTables()
  }
  
  const openCalcColumnEditor = (calcColumn?: CalcColumnDetail) => {
    setEditingCalcColumn(calcColumn)
    setCalcColumnEditorOpen(true)
  }
  const closeCalcColumnEditor = () => {
    setCalcColumnEditorOpen(false)
    setEditingCalcColumn(undefined)
    loadCalcColumns()
  }
  
  const handleDeleteMeasure = async (measure: MeasureDetail) => {
    if (confirm(`Delete measure "${measure.name}"?`)) {
      await removeMeasure(measure.name)
    }
  }
  
  const handleDeleteCalcTable = async (calcTable: CalcTableDetail) => {
    if (confirm(`Delete calculated table "${calcTable.name}"?`)) {
      await removeCalcTable(calcTable.name)
    }
  }
  
  const handleDeleteCalcColumn = async (calcColumn: CalcColumnDetail) => {
    if (confirm(`Delete calculated column "${calcColumn.table}[${calcColumn.column}]"?`)) {
      await removeCalcColumn(calcColumn.table, calcColumn.column)
    }
  }
  
  // Parameter editor handlers
  const openFieldParamEditor = (param?: FieldParameterMeta) => {
    if (param) {
      // Get the def from fieldParamDefs using the param name
      const def = fieldParamDefs[param.name] || { items: param.items }
      setEditingFieldParam({ name: param.name, def })
    } else {
      setEditingFieldParam(null)
    }
    setFieldParamEditorOpen(true)
  }
  const closeFieldParamEditor = () => {
    setFieldParamEditorOpen(false)
    setEditingFieldParam(null)
    loadFieldParams()
  }
  
  const openCalcGroupEditor = (group?: CalcGroupMeta) => {
    if (group) {
      // Get the def from calcGroupDefs using the group name
      const def = calcGroupDefs[group.name] || { items: group.items }
      setEditingCalcGroup({ name: group.name, def })
    } else {
      setEditingCalcGroup(null)
    }
    setCalcGroupEditorOpen(true)
  }
  const closeCalcGroupEditor = () => {
    setCalcGroupEditorOpen(false)
    setEditingCalcGroup(null)
    loadCalcGroups()
  }
  
  const openWhatIfEditor = (param?: WhatIfParameterMeta) => {
    if (param) {
      // Get the def from whatIfDefs using the param name
      const def = whatIfDefs[param.name] || { 
        min: param.min, 
        max: param.max, 
        step: param.step, 
        default: param.default 
      }
      setEditingWhatIf({ name: param.name, def })
    } else {
      setEditingWhatIf(null)
    }
    setWhatIfEditorOpen(true)
  }
  const closeWhatIfEditor = () => {
    setWhatIfEditorOpen(false)
    setEditingWhatIf(null)
    loadWhatIfParams()
  }

  const openHierarchyEditor = (hierarchy?: { name: string; def: HierarchyDef }) => {
    setEditingHierarchy(hierarchy ?? null)
    setHierarchyEditorOpen(true)
  }
  const closeHierarchyEditor = () => {
    setHierarchyEditorOpen(false)
    setEditingHierarchy(null)
  }

  // Playbook editor handlers
  const openPlaybookEditor = (playbook?: PlaybookMeta) => {
    setEditingPlaybook(playbook ?? null)
    setPlaybookEditorOpen(true)
  }
  const closePlaybookEditor = () => {
    setPlaybookEditorOpen(false)
    setEditingPlaybook(null)
  }
  const refreshPlaybooks = async () => {
    try {
      const result = await listPlaybooks(projectPath || undefined)
      if (!result.error && result.data) setExplanations(result.data.playbooks as unknown as PlaybookMeta[])
    } catch (e) { console.error('Failed to refresh playbooks:', e) }
  }

  const handleApplyHierarchy = (name: string, def: HierarchyDef, previousName?: string) => {
    applyHierarchy(name, def, previousName)
  }

  const handleDeleteHierarchy = (name: string) => {
    if (confirm(`Delete hierarchy "${name}"?`)) {
      removeHierarchy(name)
    }
  }
  
  // Role editor handlers
  const openRoleEditor = (role?: SecurityRoleRaw) => {
    setEditingRole(role || null)
    setRoleEditorOpen(true)
  }
  const closeRoleEditor = async () => {
    setRoleEditorOpen(false)
    setEditingRole(null)
    await loadRawRoles() // Refresh local roles list
    // Also refresh the store's roles so the role selector updates
    try {
      const result = await getSecurityRoles(projectPath || undefined)
      if (!result.error && result.data) {
        const securityRoles = result.data.roles.map((r: any) => {
          let rls: Record<string, string> | undefined = undefined
          if (r.rls && r.rls.length > 0) {
            rls = Object.fromEntries(r.rls.map((item: any) => [item.table, item.filter]))
          }
          let ols: Record<string, string[]> | undefined = undefined
          if (r.ols && r.ols.columns && Object.keys(r.ols.columns).length > 0) {
            ols = r.ols.columns
          }
          return { name: r.name, rls, ols }
        })
        useAppStore.getState().setRoles(securityRoles, result.data.default_role)
      }
    } catch (e) {
      console.error('Failed to refresh store roles:', e)
    }
  }

  if (!leftSidebarOpen) {
    return null
  }

  return (
    <aside
      className={cn(
        'flex shrink-0 bg-sidebar-background min-h-0 overflow-hidden',
        className
      )}
      data-testid="left-sidebar"
    >
      {/* ── Fields pane ── */}
      {!fieldsOpen ? (
        <button
          className="flex flex-col items-center justify-start pt-3 gap-2 w-8 hover:bg-accent/50 transition-colors cursor-pointer border-r"
          onClick={() => setFieldsOpen(true)}
          title="Open Fields Pane"
          data-testid="fields-pane-open"
        >
          <ListTree className="h-4 w-4 text-muted-foreground" />
          <span className="text-[9px] text-muted-foreground [writing-mode:vertical-lr] tracking-widest">
            FIELDS
          </span>
        </button>
      ) : (
        <div className="relative flex flex-col h-full border-r" style={{ width: fieldsWidth }}>
          <div {...fieldsResizeProps} data-testid="fields-resize-handle" />
          {/* Fields title bar */}
          <div className="flex items-center justify-between px-2 py-1.5 border-b shrink-0">
            <div className="flex items-center gap-1.5">
              <ListTree className="h-3.5 w-3.5 text-muted-foreground" />
              <span className="text-xs font-semibold tracking-wide">Fields</span>
            </div>
            <Button
              variant="ghost"
              size="sm"
              className="h-6 w-6 p-0"
              onClick={() => setFieldsOpen(false)}
              title="Close Fields Pane"
              data-testid="fields-pane-close"
            >
              <X className="h-3.5 w-3.5" />
            </Button>
          </div>

        {/* Fields content */}
          <div className="flex flex-col flex-1 min-h-0">
          {/* Search + Expand/Collapse */}
          <div className="p-2 border-b flex gap-1 items-center bg-muted/20">
            <Input
              placeholder="Search fields..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="h-8 text-sm flex-1"
              data-testid="field-search"
              aria-label="Search fields"
            />
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-8 w-8 shrink-0"
                  data-testid="fields-expand-all"
                  onClick={handleExpandAll}
                >
                  <ChevronsUpDown className="h-4 w-4" />
                </Button>
              </TooltipTrigger>
              <TooltipContent>Expand All</TooltipContent>
            </Tooltip>
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-8 w-8 shrink-0"
                  data-testid="fields-collapse-all"
                  onClick={handleCollapseAll}
                >
                  <ChevronsDownUp className="h-4 w-4" />
                </Button>
              </TooltipTrigger>
              <TooltipContent>Collapse All</TooltipContent>
            </Tooltip>
          </div>
          
          {/* Field list */}
          <ScrollArea className="flex-1 min-h-0">
            <div className="p-2">
              {tables.length === 0 && measures.length === 0 ? (
                <p className="text-xs text-muted-foreground text-center py-6 italic">
                  No fields available
                </p>
              ) : (
                <>
                  <StandaloneMeasures 
                    measures={measures} 
                    searchTerm={searchTerm} 
                    measureDetails={measuresList}
                    expandGeneration={fieldsExpandGeneration}
                    expandDefault={fieldsAllExpanded}
                    usedFieldKeys={usedFieldKeys}
                  />
                  
                  {/* Explanations / EDUs — draggable measure items with lightbulb badge */}
                  {HAS_EDU_RELATIONSHIPS && explanations && explanations.length > 0 && (
                    <FieldsExplanations
                      explanations={explanations}
                      searchTerm={searchTerm}
                      expandGeneration={fieldsExpandGeneration}
                      expandDefault={fieldsAllExpanded}
                    />
                  )}
                  
                  {/* Calculation Groups in Fields pane */}
                  {calcGroupDefs && Object.keys(calcGroupDefs).length > 0 && (
                    <FieldsCalcGroups
                      calcGroupDefs={calcGroupDefs}
                      tables={tables}
                      searchTerm={searchTerm}
                      expandGeneration={fieldsExpandGeneration}
                      expandDefault={fieldsAllExpanded}
                    />
                  )}

                  {/* Hierarchies in Fields pane */}
                  {hierarchies && Object.keys(hierarchies).length > 0 && (
                    <FieldsHierarchies
                      hierarchies={hierarchies}
                      searchTerm={searchTerm}
                      expandGeneration={fieldsExpandGeneration}
                      expandDefault={fieldsAllExpanded}
                    />
                  )}
                  
                  {/* Field Parameters in Fields pane */}
                  {fieldParamDefs && Object.keys(fieldParamDefs).length > 0 && (
                    <FieldsFieldParams
                      fieldParamDefs={fieldParamDefs}
                      tables={tables}
                      searchTerm={searchTerm}
                      expandGeneration={fieldsExpandGeneration}
                      expandDefault={fieldsAllExpanded}
                    />
                  )}
                  
                  {/* What-If Parameters in Fields pane */}
                  {whatIfDefs && Object.keys(whatIfDefs).length > 0 && (
                    <FieldsWhatIfParams
                      whatIfDefs={whatIfDefs}
                      tables={tables}
                      searchTerm={searchTerm}
                      expandGeneration={fieldsExpandGeneration}
                      expandDefault={fieldsAllExpanded}
                    />
                  )}
                  
                  {/* Tables in Fields pane */}
                  {tables.length > 0 && (
                    <FieldsTables
                      tables={tables}
                      measures={measures}
                      searchTerm={searchTerm}
                      expandGeneration={fieldsExpandGeneration}
                      expandDefault={fieldsAllExpanded}
                      isModelView={isModelView}
                      modelLayoutTableSet={modelLayoutTableSet}
                      usedFieldKeys={usedFieldKeys}
                    />
                  )}
                </>
              )}
            </div>
          </ScrollArea>
          </div>
        </div>
      )}

      {/* ── Model pane ── */}
      {!modelOpen ? (
        <button
          className="flex flex-col items-center justify-start pt-3 gap-2 w-8 hover:bg-accent/50 transition-colors cursor-pointer border-r"
          onClick={() => setModelOpen(true)}
          title="Open Model Pane"
          data-testid="model-pane-open"
        >
          <Layers className="h-4 w-4 text-muted-foreground" />
          <span className="text-[9px] text-muted-foreground [writing-mode:vertical-lr] tracking-widest">
            MODEL
          </span>
        </button>
      ) : (
        <div className="relative flex flex-col h-full border-r" style={{ width: modelWidth }}>
          <div {...modelResizeProps} data-testid="model-resize-handle" />
          {/* Model title bar */}
          <div className="flex items-center justify-between px-2 py-1.5 border-b shrink-0">
            <div className="flex items-center gap-1.5">
              <Layers className="h-3.5 w-3.5 text-muted-foreground" />
              <span className="text-xs font-semibold tracking-wide">Model</span>
            </div>
            <Button
              variant="ghost"
              size="sm"
              className="h-6 w-6 p-0"
              onClick={() => setModelOpen(false)}
              title="Close Model Pane"
              data-testid="model-pane-close"
            >
              <X className="h-3.5 w-3.5" />
            </Button>
          </div>

          <div className="flex-1 flex flex-col min-h-0">
          {/* Model sub-navigation bar */}
          <div className="flex flex-wrap gap-1 px-2 py-1.5 border-b bg-muted/30" data-testid="model-sub-nav">
            {([
              { key: 'tables' as ModelSection, label: 'Tables', testid: 'model-nav-tables' },
              { key: 'relationships' as ModelSection, label: 'Relations', testid: 'model-nav-relationships' },
              { key: 'measures' as ModelSection, label: 'Measures', testid: 'model-nav-measures' },
              { key: 'calc-tables' as ModelSection, label: 'Calc Tables', testid: 'model-nav-calc-tables' },
              { key: 'calc-cols' as ModelSection, label: 'Calc Cols', testid: 'model-nav-calc-cols' },
              { key: 'field-params' as ModelSection, label: 'Field Params', testid: 'model-nav-field-params' },
              { key: 'calc-groups' as ModelSection, label: 'Calc Groups', testid: 'model-nav-calc-groups' },
              { key: 'what-if' as ModelSection, label: 'What-If', testid: 'model-nav-what-if' },
              { key: 'hierarchies' as ModelSection, label: 'Hierarchies', testid: 'model-nav-hierarchies' },
              ...(HAS_EDU_RELATIONSHIPS ? [{ key: 'explanations' as ModelSection, label: 'Explanations', testid: 'model-nav-explanations' }] : []),
            ]).map((item) => (
              <Button
                key={item.key}
                variant={modelActiveSection === item.key ? 'secondary' : 'ghost'}
                size="sm"
                className="h-6 text-[10px] px-2"
                onClick={() => setModelActiveSection(item.key)}
                data-testid={item.testid}
              >
                {item.label}
              </Button>
            ))}
          </div>
          <ScrollArea className="flex-1 min-h-0">
            <div className="p-4 space-y-4">
              {/* Tables */}
              {modelActiveSection === 'tables' && (() => {
                const allTables = tables ?? []
                const physicalTables = allTables.filter(t => !t.virtual)
                const fieldParamTables = allTables.filter(t => t.semantic_type === 'field_parameter')
                const whatIfTables = allTables.filter(t => t.semantic_type === 'what_if_parameter')
                const calcGroupTables = allTables.filter(t => t.semantic_type === 'calculation_group')
                
                const storageBadge = (mode?: string | null) => {
                  if (!mode || mode === 'import') return <span className="text-[9px] px-1 py-0.5 rounded bg-emerald-100 text-emerald-700 dark:bg-emerald-900 dark:text-emerald-300 shrink-0">Import</span>
                  if (mode === 'direct_query') return <span className="text-[9px] px-1 py-0.5 rounded bg-blue-100 text-blue-700 dark:bg-blue-900 dark:text-blue-300 shrink-0">DQ</span>
                  if (mode === 'direct_lake') return <span className="text-[9px] px-1 py-0.5 rounded bg-purple-100 text-purple-700 dark:bg-purple-900 dark:text-purple-300 shrink-0">DL</span>
                  return null
                }

                const renderTableRow = (t: typeof allTables[0]) => (
                  <div 
                    key={t.name}
                    className="text-xs px-2 py-1.5 bg-muted rounded flex items-center gap-1.5"
                    title={`${t.name}${t.storage_mode ? ` (${t.storage_mode})` : ''}`}
                    data-testid={`model-table-${t.name}`}
                  >
                    <span className="truncate flex-1">{t.name}</span>
                    {t.table_type && (
                      <span className="text-[9px] px-1 py-0.5 rounded bg-muted-foreground/10 text-muted-foreground shrink-0 uppercase">{t.table_type}</span>
                    )}
                    {!t.virtual && storageBadge(t.storage_mode)}
                  </div>
                )

                return (
                  <div className="space-y-4 max-h-[60vh] overflow-y-auto pr-1" data-testid="model-tables-scroll-area">
                    {/* Physical Tables */}
                    <div>
                      <h4 className="text-xs font-medium mb-2 flex items-center gap-2">
                        <Table2 className="h-4 w-4" />
                        Tables ({physicalTables.length})
                      </h4>
                      {physicalTables.length === 0 ? (
                        <p className="text-xs text-muted-foreground py-2 italic text-center">No physical tables</p>
                      ) : (
                        <div className="space-y-1">
                          {physicalTables.map(renderTableRow)}
                        </div>
                      )}
                    </div>

                    {/* Field Parameters */}
                    {fieldParamTables.length > 0 && (
                      <div>
                        <h4 className="text-xs font-medium mb-2 flex items-center gap-2 text-orange-600">
                          <SlidersHorizontal className="h-4 w-4" />
                          Field Parameters ({fieldParamTables.length})
                        </h4>
                        <div className="space-y-1">
                          {fieldParamTables.map(t => (
                            <div
                              key={t.name}
                              className="text-xs px-2 py-1.5 bg-orange-50 dark:bg-orange-950/30 rounded flex items-center gap-1.5"
                              title={t.name}
                              data-testid={`model-table-${t.name}`}
                            >
                              <span className="truncate flex-1">{t.name}</span>
                              <span className="text-[9px] px-1 py-0.5 rounded bg-orange-100 text-orange-700 dark:bg-orange-900 dark:text-orange-300 shrink-0">FP</span>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                    {/* What-If Parameters */}
                    {whatIfTables.length > 0 && (
                      <div>
                        <h4 className="text-xs font-medium mb-2 flex items-center gap-2 text-violet-600">
                          <SlidersHorizontal className="h-4 w-4" />
                          What-If Parameters ({whatIfTables.length})
                        </h4>
                        <div className="space-y-1">
                          {whatIfTables.map(t => (
                            <div
                              key={t.name}
                              className="text-xs px-2 py-1.5 bg-violet-50 dark:bg-violet-950/30 rounded flex items-center gap-1.5"
                              title={t.name}
                              data-testid={`model-table-${t.name}`}
                            >
                              <span className="truncate flex-1">{t.name}</span>
                              <span className="text-[9px] px-1 py-0.5 rounded bg-violet-100 text-violet-700 dark:bg-violet-900 dark:text-violet-300 shrink-0">WI</span>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                    {/* Calculation Groups */}
                    {calcGroupTables.length > 0 && (
                      <div>
                        <h4 className="text-xs font-medium mb-2 flex items-center gap-2 text-cyan-600">
                          <Calculator className="h-4 w-4" />
                          Calculation Groups ({calcGroupTables.length})
                        </h4>
                        <div className="space-y-1">
                          {calcGroupTables.map(t => (
                            <div
                              key={t.name}
                              className="text-xs px-2 py-1.5 bg-cyan-50 dark:bg-cyan-950/30 rounded flex items-center gap-1.5"
                              title={t.name}
                              data-testid={`model-table-${t.name}`}
                            >
                              <span className="truncate flex-1">{t.name}</span>
                              <span className="text-[9px] px-1 py-0.5 rounded bg-cyan-100 text-cyan-700 dark:bg-cyan-900 dark:text-cyan-300 shrink-0">CG</span>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                )
              })()}

              {/* Relationships */}
              {modelActiveSection === 'relationships' && (
              <div className="max-h-[60vh] overflow-y-auto pr-1" data-testid="model-relationships-scroll-area">
                <RelationshipManager />
              </div>
              )}

              {/* Measures - Editable */}
              {modelActiveSection === 'measures' && (
              <div className="flex min-h-0 flex-col">
                <div className="flex items-center justify-between mb-2">
                  <h4 className="text-xs font-medium mb-2 flex items-center gap-2">
                    <FunctionSquare className="h-4 w-4 text-yellow-600" />
                    Measures ({measuresList.length})
                  </h4>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-6 w-6"
                    onClick={() => openMeasureEditor()}
                    data-testid="add-measure-btn"
                    aria-label="Add measure"
                    title="Add measure"
                  >
                    <Plus className="h-3 w-3" />
                  </Button>
                </div>
                <div className="space-y-1 min-h-0 max-h-[60vh] overflow-y-auto pr-1" data-testid="model-measures-list">
                  {measuresList.length === 0 ? (
                    <p className="text-xs text-muted-foreground py-2 italic text-center">No measures defined</p>
                  ) : (
                    measuresList.map(m => (
                      <div 
                        key={m.name}
                        className="text-xs px-2 py-1 bg-muted rounded flex items-center gap-1 group cursor-pointer hover:bg-muted/80"
                        onClick={() => setFormulaBarSelection({ kind: 'measure', name: m.name })}
                        data-testid={`select-measure-${m.name}`}
                      >
                        <span className="truncate flex-1" title={m.dax}>{m.name}</span>
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-5 w-5 opacity-0 group-hover:opacity-100"
                          onClick={(e) => { e.stopPropagation(); openMeasureEditor(m); }}
                          data-testid={`edit-measure-${m.name}`}
                          aria-label="Edit measure"
                          title="Edit measure"
                        >
                          <Pencil className="h-3 w-3" />
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-5 w-5 opacity-0 group-hover:opacity-100 text-destructive"
                          onClick={(e) => { e.stopPropagation(); handleDeleteMeasure(m); }}
                          data-testid={`delete-measure-${m.name}`}
                          aria-label="Delete measure"
                          title="Delete measure"
                        >
                          <Trash2 className="h-3 w-3" />
                        </Button>
                      </div>
                    ))
                  )}
                </div>
              </div>
              )}

              {/* Calculated Tables */}
              {modelActiveSection === 'calc-tables' && (
              <div className="flex min-h-0 flex-col">
                <div className="flex items-center justify-between mb-2">
                  <h4 className="text-xs font-medium flex items-center gap-2">
                    <TableProperties className="h-4 w-4 text-blue-600" />
                    Calculated Tables ({calcTablesList.length})
                  </h4>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-6 w-6"
                    onClick={() => openCalcTableEditor()}
                    data-testid="add-calctable-btn"
                    aria-label="Add calculated table"
                    title="Add calculated table"
                  >
                    <Plus className="h-3 w-3" />
                  </Button>
                </div>
                <div className="space-y-1 min-h-0 max-h-[60vh] overflow-y-auto pr-1" data-testid="model-calc-tables-list">
                  {calcTablesList.length === 0 ? (
                    <p className="text-xs text-muted-foreground py-2 italic text-center">No calculated tables</p>
                  ) : (
                    calcTablesList.map(ct => (
                      <div 
                        key={ct.name}
                        className="text-xs px-2 py-1 bg-muted rounded flex items-center gap-1 group cursor-pointer hover:bg-muted/80"
                        onClick={() => setFormulaBarSelection({ kind: 'calc_table', name: ct.name })}
                        data-testid={`select-calctable-${ct.name}`}
                      >
                        <span className="truncate flex-1" title={ct.expression || ct.dax}>{ct.name}</span>
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-5 w-5 opacity-0 group-hover:opacity-100"
                          onClick={(e) => { e.stopPropagation(); openCalcTableEditor(ct); }}
                          data-testid={`edit-calctable-${ct.name}`}
                          aria-label="Edit calculated table"
                          title="Edit calculated table"
                        >
                          <Pencil className="h-3 w-3" />
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-5 w-5 opacity-0 group-hover:opacity-100 text-destructive"
                          onClick={(e) => { e.stopPropagation(); handleDeleteCalcTable(ct); }}
                          data-testid={`delete-calctable-${ct.name}`}
                          aria-label="Delete calculated table"
                          title="Delete calculated table"
                        >
                          <Trash2 className="h-3 w-3" />
                        </Button>
                      </div>
                    ))
                  )}
                </div>
              </div>
              )}

              {/* Calculated Columns */}
              {modelActiveSection === 'calc-cols' && (
              <>
              <div className="flex min-h-0 flex-col">
                <div className="flex items-center justify-between mb-2">
                  <h4 className="text-xs font-medium flex items-center gap-2">
                    <Calculator className="h-4 w-4 text-green-600" />
                    Calculated Columns ({calcColumnsList.length})
                  </h4>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-6 w-6"
                    onClick={() => openCalcColumnEditor()}
                    data-testid="add-calccolumn-btn"
                    aria-label="Add calculated column"
                    title="Add calculated column"
                  >
                    <Plus className="h-3 w-3" />
                  </Button>
                </div>
                <div className="space-y-1 min-h-0 max-h-[60vh] overflow-y-auto pr-1" data-testid="model-calc-cols-list">
                  {calcColumnsList.length === 0 ? (
                    <p className="text-xs text-muted-foreground py-2 italic text-center">No calculated columns</p>
                  ) : (
                    calcColumnsList.map(cc => (
                      <div 
                        key={`${cc.table}.${cc.column}`}
                        className="text-xs px-2 py-1 bg-muted rounded flex items-center gap-1 group cursor-pointer hover:bg-muted/80"
                        onClick={() => setFormulaBarSelection({ kind: 'calc_column', table: cc.table, column: cc.column })}
                        data-testid={`select-calccolumn-${cc.table}-${cc.column}`}
                      >
                        <span className="truncate flex-1" title={cc.dax}>
                          {cc.table}[{cc.column}]
                        </span>
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-5 w-5 opacity-0 group-hover:opacity-100"
                          onClick={(e) => { e.stopPropagation(); openCalcColumnEditor(cc); }}
                          data-testid={`edit-calccolumn-${cc.table}-${cc.column}`}
                          aria-label="Edit calculated column"
                          title="Edit calculated column"
                        >
                          <Pencil className="h-3 w-3" />
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-5 w-5 opacity-0 group-hover:opacity-100 text-destructive"
                          onClick={(e) => { e.stopPropagation(); handleDeleteCalcColumn(cc); }}
                          data-testid={`delete-calccolumn-${cc.table}-${cc.column}`}
                          aria-label="Delete calculated column"
                          title="Delete calculated column"
                        >
                          <Trash2 className="h-3 w-3" />
                        </Button>
                      </div>
                    ))
                  )}
                </div>
              </div>
              </>
              )}

              {/* Field Parameters */}
              {modelActiveSection === 'field-params' && (
              <div data-testid="model-section-field-parameters" className="flex min-h-0 flex-col">
                <div className="flex items-center justify-between mb-2" data-testid="model-field-params-header">
                  <h4 className="text-xs font-medium flex items-center gap-2">
                    <ListFilter className="h-4 w-4 text-cyan-600" />
                    Field Parameters ({fieldParams.length})
                  </h4>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-6 w-6"
                    onClick={() => openFieldParamEditor()}
                    data-testid="add-field-param"
                    aria-label="Add field parameter"
                    title="Add field parameter"
                  >
                    <Plus className="h-3 w-3" />
                  </Button>
                </div>
                <div className="space-y-2 min-h-0 max-h-[60vh] overflow-y-auto pr-1" data-testid="model-field-params-list">
                  {fieldParams.length === 0 ? (
                    <p className="text-xs text-muted-foreground py-2 italic text-center">No field parameters defined</p>
                  ) : (
                    fieldParams.map(fp => {
                      /** Format item ref as NAMEOF reference */
                      const formatRef = (ref?: { type: string; table?: string; column?: string; name?: string }) => {
                        if (!ref) return null
                        if (ref.type === 'ColumnRef' && ref.table && ref.column) return `NAMEOF('${ref.table}'[${ref.column}])`
                        if (ref.type === 'MeasureRef' && ref.name) return `NAMEOF([${ref.name}])`
                        return null
                      }
                      return (
                        <div 
                          key={fp.name}
                          className="group text-xs rounded border"
                          data-testid={`field-param-${fp.name}`}
                        >
                          <div className="flex items-center justify-between px-2 py-1.5 bg-muted/50">
                            <div
                              className="flex items-center gap-1.5 cursor-pointer flex-1"
                              onClick={() => setFormulaBarSelection({ kind: 'field_parameter', name: fp.name })}
                            >
                              <ListFilter className="h-3.5 w-3.5 text-blue-600" />
                              <span className="font-medium">{fp.name}</span>
                            </div>
                            <Button
                              variant="ghost"
                              size="icon"
                              className="h-5 w-5 opacity-0 group-hover:opacity-100"
                              onClick={() => openFieldParamEditor(fp)}
                              data-testid={`edit-field-param-${fp.name}`}
                              aria-label="Edit field parameter"
                              title="Edit field parameter"
                            >
                              <Pencil className="h-3 w-3" />
                            </Button>
                          </div>
                          {/* Items tree (like calc groups) */}
                          <div className="px-2 py-1 space-y-0.5">
                            <span className="text-[10px] text-muted-foreground">Items ({fp.items.length}):</span>
                            {fp.items.map((item, idx) => {
                              const refStr = formatRef((item as any).ref)
                              return (
                                <div
                                  key={item.name}
                                  className="flex items-center gap-2 px-2 py-1 hover:bg-accent rounded cursor-pointer"
                                  data-testid={`field-param-item-${fp.name}-${item.name}`}
                                  onClick={() => setFormulaBarSelection({ kind: 'field_parameter', name: fp.name })}
                                  title={refStr ? `(\"${item.name}\", ${refStr}, ${(item as any).sort ?? idx})` : item.name}
                                >
                                  <Type className="h-3.5 w-3.5 text-blue-500" />
                                  <span className="truncate">{item.name}</span>
                                  {refStr && (
                                    <span className="ml-auto text-[10px] text-muted-foreground truncate max-w-[120px]" title={refStr}>
                                      {refStr}
                                    </span>
                                  )}
                                </div>
                              )
                            })}
                          </div>
                        </div>
                      )
                    })
                  )}
                </div>
              </div>
              )}

              {/* Calculation Groups */}
              {modelActiveSection === 'calc-groups' && (
              <div data-testid="model-section-calculation-groups" className="flex min-h-0 flex-col">
                <div className="flex items-center justify-between mb-2" data-testid="model-calc-groups-header">
                  <h4 className="text-xs font-medium flex items-center gap-2">
                    <Layers className="h-4 w-4 text-orange-600" />
                    Calculation Groups ({calcGroups.length})
                  </h4>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-6 w-6"
                    onClick={() => openCalcGroupEditor()}
                    data-testid="add-calc-group"
                    aria-label="Add calculation group"
                    title="Add calculation group"
                  >
                    <Plus className="h-3 w-3" />
                  </Button>
                </div>
                <div className="space-y-2 min-h-0 max-h-[60vh] overflow-y-auto pr-1" data-testid="model-calc-groups-list">
                  {calcGroups.length === 0 ? (
                    <p className="text-xs text-muted-foreground py-2 italic text-center">No calculation groups defined</p>
                  ) : (
                    calcGroups.map(cg => (
                      <div 
                        key={cg.name}
                        className="group text-xs rounded border"
                        data-testid={`calc-group-${cg.name}`}
                      >
                        <div className="flex items-center justify-between px-2 py-1.5 bg-muted/50">
                          <div className="flex items-center gap-1.5">
                            <Layers className="h-3.5 w-3.5 text-purple-600" />
                            <span className="font-medium">{cg.name}</span>
                          </div>
                          <Button
                            variant="ghost"
                            size="icon"
                            className="h-5 w-5 opacity-0 group-hover:opacity-100"
                            onClick={() => openCalcGroupEditor(cg)}
                            data-testid={`edit-calc-group-${cg.name}`}
                            aria-label="Edit calculation group"
                            title="Edit calculation group"
                          >
                            <Pencil className="h-3 w-3" />
                          </Button>
                        </div>
                        {/* Active item selector */}
                        <div className="px-2 py-1 border-b">
                          <div className="flex items-center gap-1 mb-1">
                            <span className="text-[10px] text-muted-foreground">Active:</span>
                          </div>
                          <Select
                            value={calcGroupSelections[cg.name] || cg.items[0]?.name || ''}
                            onValueChange={(val) => updateCalcGroupSelection(cg.name, val)}
                          >
                            <SelectTrigger className="h-7 text-xs" data-testid={`calc-group-select-${cg.name}`} aria-label="Select active calculation item">
                              <SelectValue placeholder="Select item..." />
                            </SelectTrigger>
                            <SelectContent>
                              {cg.items.map(item => (
                                <SelectItem key={item.name} value={item.name}>
                                  {item.name}
                                </SelectItem>
                              ))}
                            </SelectContent>
                          </Select>
                        </div>
                        {/* Calculation items tree */}
                        <div className="px-2 py-1 space-y-0.5">
                          <span className="text-[10px] text-muted-foreground">Items ({cg.items.length}):</span>
                          {cg.items.map(item => (
                            <div
                              key={item.name}
                              className="flex items-center gap-2 px-2 py-1 hover:bg-accent rounded cursor-pointer"
                              data-testid={`calc-group-item-${cg.name}-${item.name}`}
                              onClick={() => setFormulaBarSelection({ kind: 'calc_item', group: cg.name, item: item.name })}
                            >
                              <Calculator className="h-3.5 w-3.5 text-purple-500" />
                              <span className="truncate">{item.name}</span>
                            </div>
                          ))}
                        </div>
                      </div>
                    ))
                  )}
                </div>
              </div>
              )}

              {/* What-If Parameters */}
              {modelActiveSection === 'what-if' && (
              <div data-testid="model-section-what-if" className="flex min-h-0 flex-col">
                <div className="flex items-center justify-between mb-2">
                  <h4 className="text-xs font-medium flex items-center gap-2">
                    <Gauge className="h-4 w-4 text-pink-600" />
                    What-If Parameters ({whatIfParams.length})
                  </h4>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-6 w-6"
                    onClick={() => openWhatIfEditor()}
                    data-testid="add-what-if"
                    aria-label="Add what-if parameter"
                    title="Add what-if parameter"
                  >
                    <Plus className="h-3 w-3" />
                  </Button>
                </div>
                <div className="space-y-2 min-h-0 max-h-[60vh] overflow-y-auto pr-1" data-testid="model-what-if-list">
                  {whatIfParams.length === 0 ? (
                    <p className="text-xs text-muted-foreground py-2 italic text-center">No what-if parameters defined</p>
                  ) : (
                    whatIfParams.map(wip => (
                      <div 
                        key={wip.name}
                        className="group text-xs px-2 py-2 bg-muted rounded space-y-2"
                        data-testid={`what-if-param-${wip.name}`}
                      >
                        <div className="flex items-center justify-between">
                          <span className="font-medium">{wip.name}</span>
                          <div className="flex items-center gap-1">
                            <span className="text-muted-foreground">
                              {getWhatIfValue(wip.name)}
                            </span>
                            <Button
                              variant="ghost"
                              size="icon"
                              className="h-5 w-5 opacity-0 group-hover:opacity-100"
                              onClick={() => openWhatIfEditor(wip)}
                              data-testid={`edit-what-if-${wip.name}`}
                              aria-label="Edit what-if parameter"
                              title="Edit what-if parameter"
                            >
                              <Pencil className="h-3 w-3" />
                            </Button>
                          </div>
                        </div>
                        <Slider
                          value={[getWhatIfValue(wip.name)]}
                          min={wip.min}
                          max={wip.max}
                          step={wip.step || 1}
                          onValueChange={(vals: number[]) => updateWhatIfSelection(wip.name, vals[0])}
                          data-testid={`what-if-slider-${wip.name}`}
                          aria-label="What-if parameter slider"
                        />
                        <div className="flex justify-between text-muted-foreground text-[10px]">
                          <span>{wip.min}</span>
                          <span>{wip.max}</span>
                        </div>
                      </div>
                    ))
                  )}
                </div>
              </div>
              )}

              {/* Hierarchies */}
              {modelActiveSection === 'hierarchies' && (
              <div data-testid="model-section-hierarchies" className="flex min-h-0 flex-col">
                <div className="flex items-center justify-between mb-2">
                  <h4 className="text-xs font-medium flex items-center gap-2">
                    <ListTree className="h-4 w-4 text-emerald-600" />
                    Hierarchies ({Object.keys(hierarchies).length})
                  </h4>
                  <div className="flex items-center gap-1">
                    {isHierarchiesDirty && (
                      <span className="text-[10px] text-amber-600" data-testid="hierarchies-dirty">
                        Unsaved
                      </span>
                    )}
                    {isHierarchiesDirty && (
                      <Button
                        variant="ghost"
                        size="sm"
                        className="h-6 text-[10px]"
                        onClick={() => resetHierarchiesDraft()}
                        data-testid="hierarchies-discard-btn"
                      >
                        Discard
                      </Button>
                    )}
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-6 w-6"
                      onClick={() => openHierarchyEditor()}
                      data-testid="add-hierarchy"
                      aria-label="Add hierarchy"
                      title="Add hierarchy"
                    >
                      <Plus className="h-3 w-3" />
                    </Button>
                  </div>
                </div>
                <div className="space-y-2 min-h-0 max-h-[60vh] overflow-y-auto pr-1" data-testid="model-hierarchies-list">
                  {Object.keys(hierarchies).length === 0 ? (
                    <p className="text-xs text-muted-foreground py-2 italic text-center">No hierarchies defined</p>
                  ) : (
                    Object.entries(hierarchies)
                      .sort(([a], [b]) => a.localeCompare(b))
                      .map(([name, def]) => (
                        <div
                          key={name}
                          className="group text-xs rounded border"
                          data-testid={`hierarchy-${name}`}
                        >
                          <div className="flex items-center justify-between px-2 py-1.5 bg-muted/50">
                            <div
                              className="flex items-center gap-1.5"
                            >
                              <ListTree className="h-3.5 w-3.5 text-emerald-600" />
                              <span className="font-medium">{name}</span>
                            </div>
                            <div className="flex items-center gap-1">
                              <Button
                                variant="ghost"
                                size="icon"
                                className="h-5 w-5 opacity-0 group-hover:opacity-100"
                                onClick={() => openHierarchyEditor({ name, def })}
                                data-testid={`edit-hierarchy-${name}`}
                                aria-label="Edit hierarchy"
                                title="Edit hierarchy"
                              >
                                <Pencil className="h-3 w-3" />
                              </Button>
                              <Button
                                variant="ghost"
                                size="icon"
                                className="h-5 w-5 opacity-0 group-hover:opacity-100 text-destructive"
                                onClick={() => handleDeleteHierarchy(name)}
                                data-testid={`delete-hierarchy-${name}`}
                                aria-label="Delete hierarchy"
                                title="Delete hierarchy"
                              >
                                <Trash2 className="h-3 w-3" />
                              </Button>
                            </div>
                          </div>
                          <div className="px-2 py-1 space-y-0.5">
                            <span className="text-[10px] text-muted-foreground">
                              {def.table} • {def.levels.length} levels
                            </span>
                            {(def.levels || []).map((level) => (
                              <div
                                key={`${name}-${level.name || level.column}`}
                                className="flex items-center gap-2 px-2 py-1 hover:bg-accent rounded cursor-pointer"
                                data-testid={`hierarchy-level-${name}-${level.name || level.column}`}
                              >
                                <Type className="h-3.5 w-3.5 text-muted-foreground" />
                                <span className="truncate">{level.name || level.column}</span>
                                {level.name && level.column !== level.name && (
                                  <span className="ml-auto text-[10px] text-muted-foreground truncate max-w-[120px]" title={level.column}>
                                    {level.column}
                                  </span>
                                )}
                              </div>
                            ))}
                          </div>
                        </div>
                      ))
                  )}
                </div>
              </div>
              )}

              {/* Explanations / Playbooks */}
              {HAS_EDU_RELATIONSHIPS && modelActiveSection === 'explanations' && (
              <div data-testid="model-section-explanations" className="flex min-h-0 flex-col">
                <div className="flex items-center justify-between mb-2">
                  <h4 className="text-xs font-medium flex items-center gap-2">
                    <BookOpen className="h-4 w-4 text-amber-600" />
                    Explanations ({explanations.length})
                  </h4>
                  <div className="flex items-center gap-1">
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-6 w-6"
                      onClick={() => setEduWizardOpen(true)}
                      data-testid="open-edu-wizard"
                      aria-label="EDU setup wizard"
                      title="EDU setup wizard"
                    >
                      <Lightbulb className="h-3 w-3" />
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-6 w-6"
                      onClick={() => openPlaybookEditor()}
                      data-testid="add-playbook"
                      aria-label="Add playbook"
                      title="Add playbook"
                    >
                      <Plus className="h-3 w-3" />
                    </Button>
                  </div>
                </div>

                {explanations.length === 0 ? (
                  <p className="text-xs text-muted-foreground py-2">
                    No explanation playbooks found. Click + to create one.
                  </p>
                ) : (
                  <div className="space-y-2 min-h-0 max-h-[60vh] overflow-y-auto pr-1" data-testid="model-explanations-list">
                    {explanations.map((pb) => {
                      const eduList = pb.edus || []
                      const driverCount = (pb.drivers || []).length
                      return (
                        <div
                          key={pb.name}
                          className="group text-xs rounded border"
                          data-testid={`explanation-${pb.name}`}
                        >
                          <div className="flex items-center justify-between px-2 py-1.5 bg-muted/50">
                            <div className="flex items-center gap-1.5">
                              <Lightbulb className="h-3.5 w-3.5 text-amber-500" />
                              <span className="font-medium">{pb.name}</span>
                            </div>
                            <div className="flex items-center gap-1">
                              <Button
                                variant="ghost"
                                size="icon"
                                className="h-5 w-5 opacity-0 group-hover:opacity-100"
                                onClick={() => openPlaybookEditor(pb)}
                                data-testid={`edit-playbook-${pb.name}`}
                                aria-label="Edit playbook"
                                title="Edit playbook"
                              >
                                <Pencil className="h-3 w-3" />
                              </Button>
                              <Button
                                variant="ghost"
                                size="icon"
                                className="h-5 w-5 opacity-0 group-hover:opacity-100 text-destructive"
                                onClick={async () => {
                                  if (!confirm(`Delete playbook "${pb.name}"?`)) return
                                  try {
                                    await deletePlaybook(pb.name, projectPath || undefined)
                                    await refreshPlaybooks()
                                  } catch (e) { console.error('Failed to delete playbook:', e) }
                                }}
                                data-testid={`delete-playbook-${pb.name}`}
                                aria-label="Delete playbook"
                                title="Delete playbook"
                              >
                                <Trash2 className="h-3 w-3" />
                              </Button>
                            </div>
                          </div>

                          {/* Playbook description */}
                          {pb.description && (
                            <div className="px-2 py-1 text-[11px] text-muted-foreground italic border-b bg-amber-50/30">
                              {pb.description}
                            </div>
                          )}

                          {/* EDU list */}
                          <div className="px-2 py-1 space-y-0.5">
                            <span className="text-[10px] text-muted-foreground">
                              {eduList.length} EDU{eduList.length !== 1 ? 's' : ''}
                              {driverCount > 0 && ` · ${driverCount} driver${driverCount !== 1 ? 's' : ''}`}
                            </span>
                            {eduList.map((edu) => (
                              <div
                                key={edu.id}
                                className="flex items-center gap-2 px-2 py-1 hover:bg-accent rounded"
                                data-testid={`model-edu-${edu.id}`}
                              >
                                <div className="relative shrink-0">
                                  <FunctionSquare className="h-3.5 w-3.5 text-yellow-600" />
                                  <Lightbulb className="h-2.5 w-2.5 text-amber-500 absolute -top-1 -right-1" />
                                </div>
                                <span className="truncate">{edu.metric || edu.id}</span>
                                <span className="text-[10px] text-muted-foreground px-1 py-0.5 bg-muted rounded ml-auto shrink-0">
                                  {edu.comparator?.replace(/_/g, ' ') || 'vs'}
                                </span>
                              </div>
                            ))}
                          </div>
                        </div>
                      )
                    })}
                  </div>
                )}
              </div>
              )}
            </div>
          </ScrollArea>
          </div>
        </div>
      )}
      
      {/* Model Editors */}
      <MeasureEditor 
        open={measureEditorOpen} 
        onClose={closeMeasureEditor} 
        editMeasure={editingMeasure}
      />
      <CalcTableEditor 
        open={calcTableEditorOpen} 
        onClose={closeCalcTableEditor} 
        editCalcTable={editingCalcTable}
      />
      <CalcColumnEditor 
        open={calcColumnEditorOpen} 
        onClose={closeCalcColumnEditor} 
        editCalcColumn={editingCalcColumn}
      />
      
      {/* Parameter Editors */}
      <FieldParameterEditor
        open={fieldParamEditorOpen}
        onClose={closeFieldParamEditor}
        editParam={editingFieldParam}
        existingDefs={fieldParamDefs}
      />
      <CalcGroupEditor
        open={calcGroupEditorOpen}
        onClose={closeCalcGroupEditor}
        editGroup={editingCalcGroup}
        existingDefs={calcGroupDefs}
      />
      <WhatIfParameterEditor
        open={whatIfEditorOpen}
        onClose={closeWhatIfEditor}
        editParam={editingWhatIf}
        existingDefs={whatIfDefs}
      />
      <HierarchyEditor
        open={hierarchyEditorOpen}
        onClose={closeHierarchyEditor}
        editHierarchy={editingHierarchy}
        existingHierarchies={hierarchies}
        tables={hierarchyTables}
        onApply={handleApplyHierarchy}
      />
      {HAS_EDU_RELATIONSHIPS && <PlaybookEditor
        open={playbookEditorOpen}
        onClose={closePlaybookEditor}
        editPlaybook={editingPlaybook}
        measures={measures}
        tables={(tables ?? []).map(t => ({ name: t.name, columns: t.columns || [] }))}
        projectPath={projectPath}
        onSaved={refreshPlaybooks}
      />}
      
      {/* Role Editor */}
      <RoleEditor
        open={roleEditorOpen}
        onClose={closeRoleEditor}
        editRole={editingRole}
        existingRoles={rawRoles}
        defaultRole={defaultRole}
      />

      {/* Standalone EDU Sub-Wizard */}
      {HAS_EDU_RELATIONSHIPS && <EDUSubWizard
        open={eduWizardOpen}
        onOpenChange={setEduWizardOpen}
        availableMeasures={measures ?? []}
        availableDimensions={[]}
        onApply={(_config: EDUConfig) => {
          // Standalone mode: log the configuration for now
          // In future, this could auto-create/update playbook EDUs
          setEduWizardOpen(false)
        }}
      />}
    </aside>
  )
}

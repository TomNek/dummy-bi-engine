import { useState, useCallback, useEffect } from 'react'
import { 
  Filter, 
  Sliders, 
  Eye,
  X,
  ChevronDown,
  ChevronRight,
  Plus,
  ChartBar,
  ChartColumn,
  Table2,
  CreditCard,
  LineChart,
  Grid3X3,
  ScatterChart,
  Pencil,
  Code,
  AlertCircle,
  Layers,
  Copy,
  Check,
  RotateCcw,
  SlidersHorizontal,
  LayoutGrid,
  CopyPlus,
  Trash2,
  Bookmark as BookmarkIcon,
  Type,
  MousePointer2,
  Square,
  ImageIcon,
  TrendingUp,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Separator } from '@/components/ui/separator'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { useAppStore, useReportStore, useFilterStore, type Filter as FilterType } from '@/stores'
import { useSelectionStateStore } from '@/stores/selection-state-store'
import { FilterEditor } from '@/components/filters'
import { SlicerDefEditor, SlicerInstanceEditor } from '@/components/slicers'
import { EncodingsPanel, type FieldExpr, TablixSettingsPanel, InteractionModePanel, FormatOptionsPanel, VisualCalculationsPanel, type TablixSettings, type InteractionSettings, type FormatOptions, LayerEditor, type ComboLayer } from '@/components/visuals'
import { StaticContentEditor } from '@/components/visuals/StaticContentEditor'
import { isStaticVisualType } from '@/components/visuals/StaticVisualContent'
import { updateVisual as apiUpdateVisual, putVisualCalculations, validateVisualCalculation, type SlicerDef, type SlicerInstance, type StaticContent, type VisualCalculationDef } from '@/lib/api'
import { useCreateVisual, useSlicers, useVisualRender, usePanelResize } from '@/hooks'
import { BookmarksPanel } from '@/components/bookmarks'
import { ExplorationModeToggle } from '@/components/slicers/ExplorationModeToggle'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

interface RightSidebarProps {
  className?: string
  onOpenSyncSlicers?: () => void
}

interface FilterItemProps {
  filter: FilterType
  onRemove?: () => void
  onEdit?: () => void
}

/**
 * Helper: extract display label from a filter's column reference.
 * The API returns column as a nested ColumnRef {type, table, column},
 * but old code and manually created filters use flat {table, column} strings.
 */
function filterLabel(f: FilterType): string {
  const col = f.column
  if (col && typeof col === 'object') {
    const c = col as { table?: string; column?: string }
    return `${c.table ?? '?'}[${c.column ?? '?'}]`
  }
  return `${f.table ?? '?'}[${col ?? '?'}]`
}

function FilterItem({ filter, onRemove, onEdit }: FilterItemProps) {
  const [isOpen, setIsOpen] = useState(true)
  
  // Phase 23F: Look up possible/total counts from selection state engine
  const filterCol = filter.column as { table?: string; column?: string } | undefined
  const fieldKey = filterCol && typeof filterCol === 'object'
    ? `${filterCol.table ?? filter.table ?? ''}.${filterCol.column ?? ''}`
    : `${filter.table ?? ''}.${String(filter.column ?? '')}`
  const fieldState = useSelectionStateStore(s => s.fields[fieldKey])
  const possibleCount = fieldState?.possible?.size
  const totalCount = fieldState?.allValues?.length
  
  const scopeLabel = 
    filter.type === 'report' ? 'Report' :
    filter.type === 'page' ? 'Page' :
    filter.type === 'visual' ? 'Visual' :
    'Interaction'

  const displayValues = Array.isArray(filter.values) 
    ? filter.values.slice(0, 5).map(String).join(', ')
    : String(filter.values)

  return (
    <Collapsible open={isOpen} onOpenChange={setIsOpen}>
      <div className="group rounded-md border bg-card">
        <CollapsibleTrigger asChild>
          <div className="flex items-center justify-between px-3 py-2 cursor-pointer hover:bg-accent/50">
            <div className="flex items-center gap-2 min-w-0">
              {isOpen ? (
                <ChevronDown className="h-4 w-4 shrink-0" />
              ) : (
                <ChevronRight className="h-4 w-4 shrink-0" />
              )}
              <span className="text-xs font-medium truncate">
                {filterLabel(filter)}
              </span>
              {/* Phase 23F: "(N of M possible)" annotation */}
              {possibleCount !== undefined && totalCount !== undefined && possibleCount < totalCount && (
                <span
                  className={cn(
                    'text-[10px] tabular-nums shrink-0 ml-1',
                    possibleCount === 0
                      ? 'text-destructive font-medium'
                      : 'text-muted-foreground'
                  )}
                  data-testid={`filter-possible-count-${filter.id}`}
                >
                  {possibleCount === 0
                    ? '(0 possible — filter conflict)'
                    : `(${possibleCount} of ${totalCount} possible)`}
                </span>
              )}
            </div>
            <div className="flex items-center gap-1">
              <span className="text-[10px] text-muted-foreground px-1.5 py-0.5 rounded bg-muted">
                {scopeLabel}
              </span>
              {onEdit && (
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-6 w-6 opacity-0 group-hover:opacity-100"
                  onClick={(e) => {
                    e.stopPropagation()
                    onEdit()
                  }}
                  data-testid={`edit-filter-${filter.id}`}
                  aria-label="Edit filter"
                  title="Edit filter"
                >
                  <Pencil className="h-3 w-3" />
                </Button>
              )}
              {onRemove && (
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-6 w-6 opacity-0 group-hover:opacity-100"
                  onClick={(e) => {
                    e.stopPropagation()
                    onRemove()
                  }}
                  data-testid={`remove-filter-${filter.id}`}
                  aria-label="Remove filter"
                  title="Remove filter"
                >
                  <X className="h-3 w-3" />
                </Button>
              )}
            </div>
          </div>
        </CollapsibleTrigger>
        <CollapsibleContent>
          <div className="px-3 pb-2 pt-1 border-t">
            <div className="text-xs text-muted-foreground">
              {filter.operator && (
                <span className="font-mono mr-1">{filter.operator}</span>
              )}
              {(!filter.operator || !['isblank', 'isnotblank'].includes(filter.operator)) && (
                <>
                  Values: {displayValues}
                  {Array.isArray(filter.values) && filter.values.length > 5 && (
                    <span className="ml-1">... +{filter.values.length - 5} more</span>
                  )}
                </>
              )}
            </div>
          </div>
        </CollapsibleContent>
      </div>
    </Collapsible>
  )
}

interface FilterSectionProps {
  title: string
  filters: FilterType[]
  onAdd?: () => void
  onRemove?: (id: string) => void
  onEdit?: (filter: FilterType) => void
  onClearAll?: () => void
}

function FilterSection({ title, filters, onAdd, onRemove, onEdit, onClearAll }: FilterSectionProps) {
  const [isOpen, setIsOpen] = useState(true)
  const slug = title.toLowerCase().replace(/\s+/g, '-')

  return (
    <Collapsible open={isOpen} onOpenChange={setIsOpen}>
      <CollapsibleTrigger asChild>
        <Button
          variant="ghost"
          className="w-full justify-between px-2 h-8 font-medium hover:bg-accent"
          data-testid={`filter-section-${slug}`}
        >
          <div className="flex items-center gap-2">
            {isOpen ? (
              <ChevronDown className="h-4 w-4" />
            ) : (
              <ChevronRight className="h-4 w-4" />
            )}
            <span className="text-xs">{title}</span>
            <span className="text-[10px] text-muted-foreground">({filters.length})</span>
          </div>
          <div className="flex items-center gap-1" onClick={(e) => e.stopPropagation()}>
            {onClearAll && filters.length > 0 && (
              <Button
                variant="ghost"
                size="sm"
                className="h-6 text-xs px-2"
                onClick={onClearAll}
                data-testid={`clear-filters-${slug}`}
              >
                Clear
              </Button>
            )}
            {onAdd && (
              <Button
                variant="ghost"
                size="icon"
                className="h-6 w-6"
                onClick={onAdd}
                data-testid={`add-filter-${slug}`}
                aria-label="Add filter"
                title="Add filter"
              >
                <Plus className="h-3 w-3" />
              </Button>
            )}
          </div>
        </Button>
      </CollapsibleTrigger>
      <CollapsibleContent>
        <div className="space-y-2 px-2 pb-2">
          {filters.length === 0 ? (
            <p className="text-xs text-muted-foreground py-4 text-center italic">
              No filters applied to this page
            </p>
          ) : (
            filters.map((filter) => (
              <FilterItem
                key={filter.id}
                filter={filter}
                onRemove={onRemove ? () => onRemove(filter.id) : undefined}
                onEdit={onEdit ? () => onEdit(filter) : undefined}
              />
            ))
          )}
        </div>
      </CollapsibleContent>
    </Collapsible>
  )
}

// Visual type icons and labels
const VISUAL_TYPE_ICONS = [
  { type: 'bar', icon: ChartBar, label: 'Bar Chart', color: 'text-blue-500' },
  { type: 'column', icon: ChartColumn, label: 'Column Chart', color: 'text-indigo-500' },
  { type: 'line', icon: LineChart, label: 'Line Chart', color: 'text-emerald-500' },
  { type: 'scatter', icon: ScatterChart, label: 'Scatter Chart', color: 'text-rose-500' },
  { type: 'table', icon: Table2, label: 'Table', color: 'text-cyan-500' },
  { type: 'matrix', icon: Grid3X3, label: 'Matrix', color: 'text-violet-500' },
  { type: 'card', icon: CreditCard, label: 'Card', color: 'text-orange-500' },
  { type: 'slicer', icon: SlidersHorizontal, label: 'Slicer', color: 'text-purple-500' },
  // IBCS visuals (pure SVG)
  { type: 'ibcs_bar', icon: ChartBar, label: 'IBCS Bar', color: 'text-slate-600 dark:text-slate-400' },
  { type: 'ibcs_column', icon: ChartColumn, label: 'IBCS Column', color: 'text-slate-600 dark:text-slate-400' },
  { type: 'ibcs_line', icon: LineChart, label: 'IBCS Line', color: 'text-slate-600 dark:text-slate-400' },
  { type: 'ibcs_card', icon: CreditCard, label: 'IBCS Card', color: 'text-slate-600 dark:text-slate-400' },
  { type: 'ibcs_waterfall', icon: TrendingUp, label: 'IBCS Waterfall', color: 'text-slate-600 dark:text-slate-400' },
  { type: 'ibcs_table', icon: Table2, label: 'IBCS Table', color: 'text-slate-600 dark:text-slate-400' },
]

const INSERT_TYPE_ICONS = [
  { type: 'textbox', icon: Type, label: 'Text Box' },
  { type: 'button', icon: MousePointer2, label: 'Button' },
  { type: 'shape', icon: Square, label: 'Shape' },
  { type: 'image', icon: ImageIcon, label: 'Image' },
]

const IBCS_SWITCH_FAMILY = new Set(['ibcs_bar', 'ibcs_column', 'ibcs_waterfall'])

function shouldPreserveEncodingsOnTypeSwitch(fromType: string | undefined, toType: string): boolean {
  if (!fromType) return false
  return IBCS_SWITCH_FAMILY.has(fromType) && IBCS_SWITCH_FAMILY.has(toType)
}

/* ─── Visual Size Editor ─────────────────────────────────── */
function VisualSizeEditor({
  visual,
  onUpdate,
}: {
  visual: { x?: number; y?: number; width?: number; height?: number; layout?: { x: number; y: number; w: number; h: number } }
  onUpdate: (updates: { x?: number; y?: number; width?: number; height?: number }) => void
}) {
  const canvasWidth = useAppStore((s) => s.canvasWidth)
  const canvasHeight = useAppStore((s) => s.canvasHeight)

  // Read from layout first (matches Canvas.tsx priority)
  const x = visual.layout?.x ?? visual.x ?? 0
  const y = visual.layout?.y ?? visual.y ?? 0
  const w = visual.layout?.w ?? visual.width ?? 400
  const h = visual.layout?.h ?? visual.height ?? 300

  const handleChange = (field: 'x' | 'y' | 'width' | 'height', raw: string) => {
    const v = parseInt(raw, 10)
    if (isNaN(v)) return
    let clamped = v
    if (field === 'x') clamped = Math.max(0, Math.min(v, canvasWidth - 20))
    else if (field === 'y') clamped = Math.max(0, Math.min(v, canvasHeight - 20))
    else if (field === 'width') clamped = Math.max(40, Math.min(v, canvasWidth - x))
    else if (field === 'height') clamped = Math.max(30, Math.min(v, canvasHeight - y))
    onUpdate({ [field]: clamped })
  }

  return (
    <div>
      <h4 className="text-xs font-medium mb-2">Position & Size</h4>
      <div className="grid grid-cols-2 gap-2 text-xs">
        <div className="space-y-0.5">
          <Label className="text-[10px] text-muted-foreground">X</Label>
          <Input
            type="number"
            value={x}
            min={0}
            max={canvasWidth - 20}
            onChange={(e) => handleChange('x', e.target.value)}
            className="h-6 text-xs px-1.5"
            data-testid="visual-pos-x"
          />
        </div>
        <div className="space-y-0.5">
          <Label className="text-[10px] text-muted-foreground">Y</Label>
          <Input
            type="number"
            value={y}
            min={0}
            max={canvasHeight - 20}
            onChange={(e) => handleChange('y', e.target.value)}
            className="h-6 text-xs px-1.5"
            data-testid="visual-pos-y"
          />
        </div>
        <div className="space-y-0.5">
          <Label className="text-[10px] text-muted-foreground">Width</Label>
          <Input
            type="number"
            value={w}
            min={40}
            max={canvasWidth - x}
            onChange={(e) => handleChange('width', e.target.value)}
            className="h-6 text-xs px-1.5"
            data-testid="visual-size-w"
          />
        </div>
        <div className="space-y-0.5">
          <Label className="text-[10px] text-muted-foreground">Height</Label>
          <Input
            type="number"
            value={h}
            min={30}
            max={canvasHeight - y}
            onChange={(e) => handleChange('height', e.target.value)}
            className="h-6 text-xs px-1.5"
            data-testid="visual-size-h"
          />
        </div>
      </div>
      <p className="text-[10px] text-muted-foreground mt-1">Canvas: {canvasWidth} × {canvasHeight}</p>
    </div>
  )
}

export function RightSidebar({ className, onOpenSyncSlicers }: RightSidebarProps) {
  const rightSidebarOpen = useAppStore(s => s.rightSidebarOpen)
  const interactionSidebarOpen = useAppStore(s => s.interactionSidebarOpen)
  const visualTypes = useAppStore(s => s.visualTypes)
  const projectPath = useAppStore(s => s.projectPath)
  const tables = useAppStore(s => s.tables)
  const setDirty = useAppStore(s => s.setDirty)
  const selectedVisualId = useReportStore(s => s.selectedVisualId)
  const visuals = useReportStore(s => s.visuals)
  const currentPageId = useReportStore(s => s.currentPageId)
  const updateVisual = useReportStore(s => s.updateVisual)
  const { quickCreateVisual } = useCreateVisual()
  const { render: renderVisualById, renderAll } = useVisualRender()
  const {
    slicerDefs: rawSlicerDefs,
    slicerInstances: rawSlicerInstances,
    loadAll: loadSlicers,
    removeDef: removeSlicerDef,
    removeInstance: removeSlicerInstance,
    duplicatePlacement,
    duplicateIndependent,
  } = useSlicers()
  const slicerDefs = rawSlicerDefs ?? []
  const slicerInstances = rawSlicerInstances ?? []
  const reportFilters = useFilterStore(s => s.reportFilters)
  const pageFilters = useFilterStore(s => s.pageFilters)
  const visualFilters = useFilterStore(s => s.visualFilters)
  const interactionFilters = useFilterStore(s => s.interactionFilters)
  const removeFilter = useFilterStore(s => s.removeFilter)
  const clearInteractionFilters = useFilterStore(s => s.clearInteractionFilters)
  const setVisualFilters = useFilterStore(s => s.setVisualFilters)
  const setPageFilters = useFilterStore(s => s.setPageFilters)
  const setReportFilters = useFilterStore(s => s.setReportFilters)

  // Filter editor state
  const [filterEditorOpen, setFilterEditorOpen] = useState(false)
  const [filterEditorScope, setFilterEditorScope] = useState<'report' | 'page' | 'visual'>('report')
  const [filterEditorScopeId, setFilterEditorScopeId] = useState<string | undefined>(undefined)
  const [editingFilter, setEditingFilter] = useState<FilterType | undefined>(undefined)
  const [sqlOpen, setSqlOpen] = useState(false)
  const [irOpen, setIrOpen] = useState(false)
  const [errorsOpen, setErrorsOpen] = useState(false)
  const [encodingsOpen, setEncodingsOpen] = useState(true)
  const [copiedSection, setCopiedSection] = useState<string | null>(null)
  const [patchOpen, setPatchOpen] = useState(false)
  const [patchText, setPatchText] = useState('')
  const [patchError, setPatchError] = useState<string | null>(null)

  // Slicer editor state
  const [slicerDefEditorOpen, setSlicerDefEditorOpen] = useState(false)
  const [slicerInstanceEditorOpen, setSlicerInstanceEditorOpen] = useState(false)
  const [editingSlicerDef, setEditingSlicerDef] = useState<SlicerDef | undefined>()
  const [editingSlicerInstance, setEditingSlicerInstance] = useState<SlicerInstance | undefined>()

  // Independent pane open/close state
  const [filtersOpen, setFiltersOpen] = useState(true)
  const [formatOpen, setFormatOpen] = useState(false)
  const [slicersOpen, setSlicersOpen] = useState(false)
  const [bookmarksOpen, setBookmarksOpen] = useState(false)

  // Auto-open format pane when a visual is selected
  useEffect(() => {
    if (selectedVisualId) {
      setFormatOpen(true)
    }
  }, [selectedVisualId])

  // Pane resize
  const { width: filtersWidth, handleProps: filtersResizeProps } = usePanelResize({ defaultWidth: 280, minWidth: 180, maxWidth: 500, direction: 'left' })
  const { width: formatWidth, handleProps: formatResizeProps } = usePanelResize({ defaultWidth: 280, minWidth: 180, maxWidth: 500, direction: 'left' })
  const { width: slicersWidth, handleProps: slicersResizeProps } = usePanelResize({ defaultWidth: 280, minWidth: 180, maxWidth: 500, direction: 'left' })
  const { width: bookmarksWidth, handleProps: bookmarksResizeProps } = usePanelResize({ defaultWidth: 280, minWidth: 180, maxWidth: 500, direction: 'left' })

  // Load slicers when pane is open or project changes
  useEffect(() => {
    if (projectPath && slicersOpen) {
      loadSlicers()
    }
  }, [projectPath, slicersOpen, loadSlicers])

  // Refresh slicer list when a new slicer is created via VisualsPane
  useEffect(() => {
    const handler = () => { loadSlicers() }
    window.addEventListener('slicers-changed', handler)
    return () => window.removeEventListener('slicers-changed', handler)
  }, [loadSlicers])

  const openSlicerDefEditor = (def?: SlicerDef) => {
    setEditingSlicerDef(def)
    setSlicerDefEditorOpen(true)
  }
  const closeSlicerDefEditor = () => {
    setSlicerDefEditorOpen(false)
    setEditingSlicerDef(undefined)
    loadSlicers()
  }
  const openSlicerInstanceEditor = (instance?: SlicerInstance) => {
    setEditingSlicerInstance(instance)
    setSlicerInstanceEditorOpen(true)
  }
  const closeSlicerInstanceEditor = () => {
    setSlicerInstanceEditorOpen(false)
    setEditingSlicerInstance(undefined)
    loadSlicers()
  }
  const handleDeleteSlicerDef = async (def: SlicerDef) => {
    if (confirm(`Delete slicer definition "${def.name}"? This will fail if instances exist.`)) {
      await removeSlicerDef(def.id)
    }
  }
  const handleDeleteSlicerInstance = async (instance: SlicerInstance) => {
    const def = slicerDefs.find(d => d.id?.toLowerCase() === instance.def_id?.toLowerCase())
    if (confirm(`Delete slicer instance "${def?.name || instance.def_id}" from page?`)) {
      await removeSlicerInstance(instance.id)
    }
  }
  const handleDuplicatePlacement = async (instance: SlicerInstance) => {
    await duplicatePlacement(instance)
  }
  const handleDuplicateIndependent = async (instance: SlicerInstance) => {
    await duplicateIndependent(instance)
  }

  const copyToClipboard = useCallback((text: string, section: string) => {
    navigator.clipboard.writeText(text).then(() => {
      setCopiedSection(section)
      setTimeout(() => setCopiedSection(null), 1500)
    }).catch(() => {})
  }, [])

  if (!rightSidebarOpen) {
    return null
  }

  const selectedVisual = visuals.find(v => v.id === selectedVisualId)
  const currentVisualFilters = selectedVisualId ? (visualFilters[selectedVisualId] || []) : []
  
  // Get page filters for current page
  const currentPageFilters = currentPageId ? (pageFilters[currentPageId] || []) : []
  
  // Get render state for selected visual (per-visual subscription to avoid cascade)
  const selectedRenderState = useReportStore(s => selectedVisualId ? s.renderStates[selectedVisualId] : undefined)

  const openFilterEditor = (scope: 'report' | 'page' | 'visual', scopeId?: string, filter?: FilterType) => {
    setFilterEditorScope(scope)
    setFilterEditorScopeId(scopeId)
    // Normalize column: server may send {type: "ColumnRef", table, column} object
    if (filter && typeof filter.column === 'object' && filter.column !== null) {
      const colObj = filter.column as unknown as { table?: string; column?: string }
      setEditingFilter({
        ...filter,
        table: colObj.table || filter.table,
        column: colObj.column || '',
      })
    } else {
      setEditingFilter(filter)
    }
    setFilterEditorOpen(true)
  }

  const closeFilterEditor = () => {
    setFilterEditorOpen(false)
    setEditingFilter(undefined)
  }

  // Get slots for the selected visual type
  const selectedVisualType = selectedVisual?.visual_type
  const slots = selectedVisualType && visualTypes[selectedVisualType]?.slots

  const handleVisualTypeChange = useCallback(async (newType: string) => {
    if (!selectedVisual?.id || !selectedVisual.visual_type || newType === selectedVisual.visual_type) return
    const preserveEncodings = shouldPreserveEncodingsOnTypeSwitch(selectedVisual.visual_type, newType)
    await apiUpdateVisual(selectedVisual.id, { visual_type: newType })
    if (preserveEncodings) {
      useReportStore.getState().updateVisual(selectedVisual.id, {
        visual_type: newType,
      })
    } else {
      await apiUpdateVisual(selectedVisual.id, { encodings: {} })
      useReportStore.getState().updateVisual(selectedVisual.id, {
        visual_type: newType,
        encodings: {},
      })
    }
  }, [selectedVisual])

  // Handle encoding updates
  const handleUpdateEncoding = useCallback(async (slotName: string, value: FieldExpr | FieldExpr[] | null) => {
    if (!selectedVisual || !selectedVisualId) return

    const newEncodings = {
      ...(selectedVisual.encodings || {}),
      [slotName]: value,
    }

    // Update local state immediately
    updateVisual(selectedVisualId, { encodings: newEncodings })

    // Persist to server
    try {
      await apiUpdateVisual(selectedVisualId, { encodings: newEncodings }, projectPath || undefined)
    } catch (err) {
      console.error('Failed to update encoding:', err)
    }

    // Auto-refresh the visual if autoRefresh is enabled
    const autoRefresh = useAppStore.getState().autoRefresh
    if (autoRefresh) {
      renderVisualById(selectedVisualId, { force: true })
    }
  }, [selectedVisual, selectedVisualId, updateVisual, projectPath, renderVisualById])

  return (
    <aside
      className={cn(
        'flex shrink-0 bg-sidebar-background min-h-0 overflow-hidden',
        className
      )}
      data-testid="right-sidebar"
    >
      {/* ── Filters pane ── */}
      {!filtersOpen ? (
        <button
          className="flex flex-col items-center justify-start pt-3 gap-2 w-8 hover:bg-accent/50 transition-colors cursor-pointer border-l"
          onClick={() => setFiltersOpen(true)}
          title="Open Filters Pane"
          data-testid="filters-pane-open"
        >
          <Filter className="h-4 w-4 text-muted-foreground" />
          <span className="text-[9px] text-muted-foreground [writing-mode:vertical-lr] tracking-widest">
            FILTERS
          </span>
        </button>
      ) : (
        <div className="relative flex flex-col h-full border-l" style={{ width: filtersWidth }}>
          <div {...filtersResizeProps} data-testid="filters-resize-handle" />
          {/* Filters title bar */}
          <div className="flex items-center justify-between px-2 py-1.5 border-b shrink-0">
            <div className="flex items-center gap-1.5">
              <Filter className="h-3.5 w-3.5 text-muted-foreground" />
              <span className="text-xs font-semibold tracking-wide">Filters</span>
            </div>
            <div className="flex items-center gap-1">
              {/* Phase 23F: Exploration mode toggle */}
              {currentPageId && (
                <ExplorationModeToggle pageId={currentPageId} />
              )}
              <Button
                variant="ghost"
                size="sm"
                className="h-6 w-6 p-0"
                onClick={() => setFiltersOpen(false)}
                title="Close Filters Pane"
                data-testid="filters-pane-close"
              >
                <X className="h-3.5 w-3.5" />
              </Button>
            </div>
          </div>

        {/* Filters content */}
          <ScrollArea className="flex-1 min-h-0">
            <div className="p-2 space-y-1">
              {/* Interaction filters (read-only) */}
              {interactionFilters.length > 0 && (
                <>
                  <div className="flex items-center justify-between px-2 py-1">
                    <span className="text-xs font-medium text-muted-foreground">
                      Interaction Filters ({interactionFilters.length})
                    </span>
                    <Button
                      variant="ghost"
                      size="sm"
                      className="h-6 text-xs"
                      onClick={() => clearInteractionFilters()}
                      data-testid="clear-interaction-filters"
                    >
                      Clear all
                    </Button>
                  </div>
                  <div className="space-y-1 px-2 pb-2">
                    {interactionFilters.map((f, i) => (
                      <div key={i} className="text-xs px-2 py-1 bg-muted rounded" data-testid={`interaction-filter-${i}`}>
                        <span className="font-medium">{filterLabel(f as unknown as FilterType)}</span>
                        <span className="text-muted-foreground ml-1">
                          via {f.source_visual_id.replace(/^v(\d+)$/, 'Visual $1')}
                        </span>
                      </div>
                    ))}
                  </div>
                  <Separator className="my-2" />
                </>
              )}

              {/* Filters on this visual */}
              {selectedVisualId && (
                <>
                  <FilterSection
                    title="Filters on this visual"
                    filters={currentVisualFilters}
                    onAdd={() => openFilterEditor('visual', selectedVisualId)}
                    onRemove={(id) => removeFilter(id, 'visual', selectedVisualId)}
                    onEdit={(filter) => openFilterEditor('visual', selectedVisualId, filter)}
                    onClearAll={() => setVisualFilters(selectedVisualId, [])}
                  />
                  <Separator className="my-2" />
                </>
              )}

              {/* Filters on this page */}
              <FilterSection
                title="Filters on this page"
                filters={currentPageFilters}
                onAdd={() => openFilterEditor('page', currentPageId ?? undefined)}
                onRemove={(id) => removeFilter(id, 'page', currentPageId ?? undefined)}
                onEdit={(filter) => openFilterEditor('page', currentPageId ?? undefined, filter)}
                onClearAll={() => currentPageId && setPageFilters(currentPageId, [])}
              />

              <Separator className="my-2" />

              {/* Filters on all pages */}
              <FilterSection
                title="Filters on all pages"
                filters={reportFilters}
                onAdd={() => openFilterEditor('report')}
                onRemove={(id) => removeFilter(id, 'report')}
                onEdit={(filter) => openFilterEditor('report', undefined, filter)}
                onClearAll={() => setReportFilters([])}
              />

              {/* Filter overview per visual */}
              {Object.keys(visualFilters).length > 0 && (
                <>
                  <Separator className="my-2" />
                  <Collapsible>
                    <CollapsibleTrigger className="flex items-center justify-between w-full px-2 py-1 text-xs font-medium text-muted-foreground hover:text-foreground">
                      <span>Filter overview by visual</span>
                      <ChevronDown className="h-3 w-3" />
                    </CollapsibleTrigger>
                    <CollapsibleContent>
                      <div className="space-y-1 px-2 pb-2" data-testid="filter-overview-per-visual">
                        {Object.entries(visualFilters).map(([visualId, filters]) => {
                          if (!filters || filters.length === 0) return null
                          const visual = visuals.find(v => v.id === visualId)
                          const visualName = visual?.title || visual?.id || visualId
                          return (
                            <div key={visualId} className="text-xs border rounded p-2 space-y-1">
                              <div className="flex items-center justify-between">
                                <span className="font-medium truncate">{visualName}</span>
                                <span className="text-muted-foreground ml-1">({filters.length})</span>
                              </div>
                              {filters.map((f) => (
                                <div key={f.id} className="pl-2 text-muted-foreground">
                                  {filterLabel(f)}
                                </div>
                              ))}
                            </div>
                          )
                        })}
                      </div>
                    </CollapsibleContent>
                  </Collapsible>
                </>
              )}
            </div>
          </ScrollArea>
        </div>
      )}

      {/* ── Format pane ── */}
      {!formatOpen ? (
        <button
          className="flex flex-col items-center justify-start pt-3 gap-2 w-8 hover:bg-accent/50 transition-colors cursor-pointer border-l"
          onClick={() => setFormatOpen(true)}
          title="Open Format Pane"
          data-testid="format-pane-open"
        >
          <Sliders className="h-4 w-4 text-muted-foreground" />
          <span className="text-[9px] text-muted-foreground [writing-mode:vertical-lr] tracking-widest">
            FORMAT
          </span>
        </button>
      ) : (
        <div className="relative flex flex-col h-full border-l" style={{ width: formatWidth }}>
          <div {...formatResizeProps} data-testid="format-resize-handle" />
          {/* Format title bar */}
          <div className="flex items-center justify-between px-2 py-1.5 border-b shrink-0">
            <div className="flex items-center gap-1.5">
              <Sliders className="h-3.5 w-3.5 text-muted-foreground" />
              <span className="text-xs font-semibold tracking-wide">Format</span>
            </div>
            <Button
              variant="ghost"
              size="sm"
              className="h-6 w-6 p-0"
              onClick={() => setFormatOpen(false)}
              title="Close Format Pane"
              data-testid="format-pane-close"
            >
              <X className="h-3.5 w-3.5" />
            </Button>
          </div>

        {/* Format content */}
          <ScrollArea className="flex-1 min-h-0">
            <div className="p-4">
              {selectedVisual ? (
                <div className="space-y-4">
                  <div>
                    <h4 className="text-xs font-medium mb-2">Visual Properties</h4>
                    <div className="space-y-2 text-xs">
                      <div className="flex justify-between">
                        <span className="text-muted-foreground">Identifier</span>
                        <span className="font-mono">{selectedVisual.id}</span>
                      </div>
                      <div className="flex justify-between items-center">
                        <span className="text-muted-foreground">Type</span>
                        <Select
                          value={selectedVisual.visual_type}
                          onValueChange={handleVisualTypeChange}
                        >
                          <SelectTrigger className="h-6 w-[120px] text-xs" data-testid="visual-type-selector" aria-label="Visual type">
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            {Object.entries(visualTypes).map(([key, info]) => (
                              <SelectItem key={key} value={key} className="text-xs">
                                {info.label || key}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      </div>
                      <div className="flex justify-between">
                        <span className="text-muted-foreground">Title</span>
                        <span>{selectedVisual.title || '-'}</span>
                      </div>
                    </div>
                  </div>
                  
                  <Separator />

                  {/* Encodings Section */}
                  <Collapsible open={encodingsOpen} onOpenChange={setEncodingsOpen}>
                    <CollapsibleTrigger asChild>
                      <Button
                        variant="ghost"
                        className="w-full justify-between px-0 h-8 font-medium hover:bg-transparent"
                        data-testid="encodings-section-toggle"
                      >
                        <div className="flex items-center gap-2">
                          {encodingsOpen ? (
                            <ChevronDown className="h-4 w-4" />
                          ) : (
                            <ChevronRight className="h-4 w-4" />
                          )}
                          <Layers className="h-3 w-3" />
                          <span className="text-xs">Encodings</span>
                        </div>
                      </Button>
                    </CollapsibleTrigger>
                    <CollapsibleContent>
                      <div className="py-2">
                        {isStaticVisualType(selectedVisualType ?? '') ? (
                          <StaticContentEditor
                            visualType={selectedVisualType ?? ''}
                            content={(selectedVisual.static_content ?? {}) as StaticContent}
                            onChange={async (newContent: StaticContent) => {
                              const result = await apiUpdateVisual(selectedVisual.id, { static_content: newContent }, projectPath ?? undefined)
                              if (result.data) {
                                updateVisual(selectedVisual.id, { static_content: newContent })
                              }
                            }}
                          />
                        ) : slots ? (
                          <EncodingsPanel
                            slots={slots}
                            encodings={(selectedVisual.encodings || {}) as Record<string, FieldExpr | FieldExpr[] | null>}
                            onUpdateEncoding={handleUpdateEncoding}
                            tables={tables}
                          />
                        ) : (
                          <p className="text-xs text-muted-foreground">
                            Unknown visual type: {selectedVisualType}
                          </p>
                        )}
                      </div>
                    </CollapsibleContent>
                  </Collapsible>
                  
                  <Separator />
                  
                  <VisualSizeEditor
                    visual={selectedVisual}
                    onUpdate={async (updates) => {
                      if (!selectedVisual.id) return
                      // Compute full position/size (merge updates with current values, layout-first priority)
                      const curX = selectedVisual.layout?.x ?? selectedVisual.x ?? 0
                      const curY = selectedVisual.layout?.y ?? selectedVisual.y ?? 0
                      const curW = selectedVisual.layout?.w ?? selectedVisual.width ?? 400
                      const curH = selectedVisual.layout?.h ?? selectedVisual.height ?? 300
                      const newX = updates.x ?? curX
                      const newY = updates.y ?? curY
                      const newW = updates.width ?? curW
                      const newH = updates.height ?? curH
                      const layout = { x: newX, y: newY, w: newW, h: newH }
                      // Update store (both flat fields and layout, matching persistLayout in useVisualDragResize)
                      useReportStore.getState().updateVisual(selectedVisual.id, {
                        x: newX, y: newY, width: newW, height: newH,
                        layout,
                      } as Partial<typeof selectedVisual>)
                      // Persist to backend
                      await apiUpdateVisual(selectedVisual.id, { layout }, projectPath || undefined)
                    }}
                  />
                  
                  <Separator />
                  
                  {/* Combo Layer Editor (for combo visuals only) */}
                  {selectedVisualType === 'combo' && (
                    <>
                      <LayerEditor
                        layers={((selectedVisual.encodings?.layers || []) as ComboLayer[])}
                        tables={tables}
                        layoutMode={(selectedVisual.encodings?.layout_mode as 'overlay' | 'stacked') || 'overlay'}
                        onLayoutModeChange={(mode) => {
                          if (!selectedVisual.id) return
                          const encodings = { ...selectedVisual.encodings, layout_mode: mode }
                          useReportStore.getState().updateVisual(selectedVisual.id, { encodings } as Partial<typeof selectedVisual>)
                          renderVisualById(selectedVisual.id, { force: true })
                        }}
                        onChange={(newLayers) => {
                          if (!selectedVisual.id) return
                          const encodings = { ...selectedVisual.encodings, layers: newLayers }
                          useReportStore.getState().updateVisual(selectedVisual.id, { encodings } as Partial<typeof selectedVisual>)
                          renderVisualById(selectedVisual.id, { force: true })
                        }}
                      />
                      <Separator />
                    </>
                  )}
                  
                  {/* Tablix Settings (for matrix visuals) */}
                  {selectedVisualType === 'matrix' && (
                    <>
                      <TablixSettingsPanel
                        settings={(selectedVisual.encodings?.tablix || {}) as TablixSettings}
                        rowFields={(selectedVisual.encodings?.rows || []) as Array<{ table?: string; column: string }>}
                        colFields={(selectedVisual.encodings?.cols || []) as Array<{ table?: string; column: string }>}
                        onUpdate={(key, value) => {
                          if (!selectedVisual.id) return
                          const latestVisual = useReportStore.getState().visuals.find(v => v.id === selectedVisual.id) || selectedVisual
                          const latestEncodings = latestVisual.encodings || {}
                          const tablix = { ...(latestEncodings.tablix || {}), [key]: value }
                          useReportStore.getState().updateVisual(selectedVisual.id, {
                            encodings: { ...latestEncodings, tablix }
                          })
                          setDirty(true)
                          renderVisualById(selectedVisual.id, { force: true })
                        }}
                      />
                      <Separator />
                    </>
                  )}
                  
                  {/* Interaction Mode — always visible when a visual is selected */}
                  <div data-testid="interaction-sidebar-section">
                    <InteractionModePanel
                      settings={(selectedVisual.interactions || {}) as InteractionSettings}
                      visualId={selectedVisual.id}
                      onUpdate={async (key, value) => {
                        if (!selectedVisual.id) return
                        const interactions = { ...(selectedVisual.interactions || {}), [key]: value }
                        await apiUpdateVisual(selectedVisual.id, { interactions })
                        // Update local state
                        useReportStore.getState().updateVisual(selectedVisual.id, { interactions })
                        // If interaction filters are active, re-render all visuals so the
                        // new mode (filter↔highlight) takes effect immediately.
                        const activeInteraction = useFilterStore.getState().interactionFilters
                        if (activeInteraction.length > 0) {
                          renderAll({ force: true })
                        }
                      }}
                    />
                    <Separator />
                  </div>

                  {/* Visual Calculations (for chart visuals with encodings, including matrix) */}
                  {!isStaticVisualType(selectedVisualType ?? '') && (
                    <>
                      <VisualCalculationsPanel
                        calculations={((selectedVisual as { visual_calculations?: VisualCalculationDef[] }).visual_calculations || []) as VisualCalculationDef[]}
                        onChange={async (calcs) => {
                          if (!selectedVisual.id) return
                          // Save-only persistence: update in-memory state and persist via dedicated API
                          useReportStore.getState().updateVisual(selectedVisual.id, { visual_calculations: calcs } as Partial<typeof selectedVisual>)
                          await putVisualCalculations(selectedVisual.id, calcs, projectPath || undefined)
                          // Re-render the visual so window function results appear
                          renderVisualById(selectedVisual.id, { force: true })
                        }}
                        onValidate={async (name, expression) => {
                          if (!selectedVisual.id) return null
                          try {
                            const res = await validateVisualCalculation(selectedVisual.id, name, expression, projectPath || undefined)
                            if (res.data && !(res.data as { ok?: boolean }).ok) {
                              return (res.data as { error?: string }).error || 'Validation failed'
                            }
                            return null
                          } catch {
                            return 'Validation request failed'
                          }
                        }}
                      />
                      <Separator />
                    </>
                  )}
                  
                  {/* Format Options (for chart visuals) */}
                  {['bar', 'column', 'line', 'area', 'pie', 'scatter', 'combo',
                    'histogram', 'box', 'violin', 'strip', 'ecdf',
                    'funnel', 'funnel_area',
                    'density_contour', 'density_heatmap',
                    'treemap', 'sunburst', 'icicle',
                    'scatter_polar', 'line_polar', 'bar_polar',
                    'scatter_3d', 'line_3d',
                    'bubble', 'bubble_3d',
                    'candlestick', 'ohlc', 'waterfall', 'gauge', 'sankey',
                    'ibcs_bar', 'ibcs_column', 'ibcs_line', 'ibcs_card', 'ibcs_waterfall', 'ibcs_table',
                  ].includes(selectedVisualType || '') && (
                    <>
                      <FormatOptionsPanel
                        options={(selectedVisual.format || {}) as FormatOptions}
                        visualType={selectedVisualType || ''}
                        visualEncodings={(selectedVisual.encodings || {}) as Record<string, unknown>}
                        onUpdate={async (key, value) => {
                          if (!selectedVisual.id) return
                          const format = { ...((selectedVisual as { format?: FormatOptions }).format || {}), [key]: value }
                          // Save-only persistence: keep format edits local until Save All.
                          // Update local state so panel and visual reflect the in-memory change.
                          useReportStore.getState().updateVisual(selectedVisual.id, { format } as Partial<typeof selectedVisual>)
                          // Re-render only the affected visual
                          renderVisualById(selectedVisual.id, { force: true })
                        }}
                      />
                      <Separator />
                    </>
                  )}

                  {/* Tooltip Page assignment (for chart visuals with tooltip page support) */}
                  {['bar', 'column', 'line', 'area', 'pie', 'scatter', 'combo',
                    'histogram', 'box', 'violin', 'strip', 'ecdf',
                    'funnel', 'funnel_area',
                    'density_contour', 'density_heatmap',
                    'treemap', 'sunburst', 'icicle',
                    'scatter_polar', 'line_polar', 'bar_polar',
                    'scatter_3d', 'line_3d',
                    'bubble', 'bubble_3d',
                  ].includes(selectedVisualType || '') && (() => {
                    const tooltipPages = useReportStore.getState().pages.filter(p => p.page_type === 'tooltip')
                    if (tooltipPages.length === 0) return null
                    const currentTooltipPageId = (selectedVisual as { tooltip_page_id?: string | null }).tooltip_page_id || ''
                    return (
                      <>
                        <div className="px-1 py-2" data-testid="tooltip-page-section">
                          <Label className="text-xs font-medium text-muted-foreground mb-1 block">Tooltip Page</Label>
                          <Select
                            value={currentTooltipPageId || '__none__'}
                            onValueChange={(val) => {
                              if (!selectedVisual.id) return
                              const newVal = val === '__none__' ? null : val
                              useReportStore.getState().updateVisual(selectedVisual.id, { tooltip_page_id: newVal } as Partial<typeof selectedVisual>)
                            }}
                          >
                            <SelectTrigger className="h-7 text-xs" data-testid="tooltip-page-select">
                              <SelectValue placeholder="None" />
                            </SelectTrigger>
                            <SelectContent>
                              <SelectItem value="__none__">None (default tooltip)</SelectItem>
                              {tooltipPages.map(tp => (
                                <SelectItem key={tp.id} value={tp.id}>{tp.title}</SelectItem>
                              ))}
                            </SelectContent>
                          </Select>
                        </div>
                        <Separator />
                      </>
                    )
                  })()}

                  {/* Advanced Plotly Patch Editor (for chart visuals) */}
                  {['bar', 'column', 'line', 'area', 'pie', 'scatter', 'combo',
                    'histogram', 'box', 'violin', 'strip', 'ecdf',
                    'funnel', 'funnel_area',
                    'density_contour', 'density_heatmap',
                    'treemap', 'sunburst', 'icicle',
                    'scatter_polar', 'line_polar', 'bar_polar',
                    'scatter_3d', 'line_3d',
                    'bubble', 'bubble_3d',
                    'candlestick', 'ohlc', 'waterfall', 'gauge', 'sankey',
                  ].includes(selectedVisualType || '') && (
                    <Collapsible open={patchOpen} onOpenChange={(open) => {
                      setPatchOpen(open)
                      if (open) {
                        setPatchText(JSON.stringify(selectedVisual.advanced_plotly_patch || {}, null, 2))
                        setPatchError(null)
                      }
                    }}>
                      <CollapsibleTrigger asChild>
                        <Button
                          variant="ghost"
                          className="w-full justify-between px-0 h-8 font-medium hover:bg-transparent"
                          data-testid="patch-section-toggle"
                        >
                          <div className="flex items-center gap-2">
                            {patchOpen ? (
                              <ChevronDown className="h-4 w-4" />
                            ) : (
                              <ChevronRight className="h-4 w-4" />
                            )}
                            <Pencil className="h-3 w-3" />
                            <span className="text-xs">Advanced Plotly Patch</span>
                          </div>
                        </Button>
                      </CollapsibleTrigger>
                      <CollapsibleContent>
                        <div className="space-y-2 py-2">
                          <Textarea
                            className="font-mono text-[10px] min-h-[80px]"
                            value={patchText}
                            onChange={e => setPatchText(e.target.value)}
                            placeholder='{"layout": {"title": "Custom"}}'
                            data-testid="patch-editor"
                            aria-label="Plotly patch JSON editor"
                          />
                          {patchError && (
                            <p className="text-[10px] text-destructive" data-testid="patch-error">{patchError}</p>
                          )}
                          <div className="flex gap-2">
                            <Button
                              size="sm"
                              className="h-6 text-xs"
                              data-testid="patch-apply-btn"
                              onClick={async () => {
                                if (!selectedVisual.id) return
                                setPatchError(null)
                                const txt = patchText.trim()
                                let obj: Record<string, unknown> = {}
                                try {
                                  obj = txt ? JSON.parse(txt) : {}
                                } catch (e) {
                                  setPatchError(`Invalid JSON: ${e}`)
                                  return
                                }
                                if (typeof obj !== 'object' || obj === null || Array.isArray(obj)) {
                                  setPatchError('Patch must be a JSON object (e.g. {}).')
                                  return
                                }
                                await apiUpdateVisual(selectedVisual.id, { advanced_plotly_patch: obj }, projectPath || undefined)
                                // Update local state (panel reflects new values)
                                useReportStore.getState().updateVisual(selectedVisual.id, { advanced_plotly_patch: obj } as Partial<typeof selectedVisual>)
                                // Re-render only the affected visual
                                renderVisualById(selectedVisual.id, { force: true })
                              }}
                            >
                              Apply
                            </Button>
                            <Button
                              size="sm"
                              variant="outline"
                              className="h-6 text-xs"
                              data-testid="patch-reset-btn"
                              onClick={() => {
                                setPatchText(JSON.stringify(selectedVisual.advanced_plotly_patch || {}, null, 2))
                                setPatchError(null)
                              }}
                            >
                              <RotateCcw className="h-3 w-3 mr-1" />
                              Reset
                            </Button>
                          </div>
                          {/* Load current figure config so users can see all available Plotly properties */}
                          <Button
                            size="sm"
                            variant="ghost"
                            className="h-6 text-xs w-full text-muted-foreground"
                            data-testid="patch-load-current-btn"
                            onClick={() => {
                              const rs = selectedVisualId ? useReportStore.getState().renderStates[selectedVisualId] : undefined
                              const figData = rs?.data as { figure?: { data?: unknown[]; layout?: Record<string, unknown> } } | undefined
                              if (!figData?.figure) {
                                setPatchError('No rendered figure available — render the visual first.')
                                return
                              }
                              // Build a patch-friendly object showing layout + first trace config
                              const current: Record<string, unknown> = {}
                              if (figData.figure.layout) {
                                current['layout'] = figData.figure.layout
                              }
                              if (figData.figure.data && figData.figure.data.length > 0) {
                                // Show first trace as a reference for trace-level overrides
                                const firstTrace = figData.figure.data[0] as Record<string, unknown>
                                // Extract only stylistic properties (exclude raw data arrays)
                                const traceRef: Record<string, unknown> = {}
                                for (const [k, v] of Object.entries(firstTrace)) {
                                  if (['x', 'y', 'z', 'text', 'hovertext', 'hovertemplate', 'customdata', 'ids', 'labels', 'values', 'parents'].includes(k)) continue
                                  traceRef[k] = v
                                }
                                current['data'] = [traceRef]
                              }
                              setPatchText(JSON.stringify(current, null, 2))
                              setPatchError(null)
                            }}
                          >
                            <Eye className="h-3 w-3 mr-1" />
                            Load current figure config
                          </Button>
                        </div>
                      </CollapsibleContent>
                    </Collapsible>
                  )}
                  
                  <Separator />
                  {/* SQL Query Section */}
                  <Collapsible open={sqlOpen} onOpenChange={setSqlOpen}>
                    <CollapsibleTrigger asChild>
                      <Button
                        variant="ghost"
                        className="w-full justify-between px-0 h-8 font-medium hover:bg-transparent"
                        data-testid="sql-section-toggle"
                      >
                        <div className="flex items-center gap-2">
                          {sqlOpen ? (
                            <ChevronDown className="h-4 w-4" />
                          ) : (
                            <ChevronRight className="h-4 w-4" />
                          )}
                          <Code className="h-3 w-3" />
                          <span className="text-xs">SQL Query</span>
                        </div>
                      </Button>
                    </CollapsibleTrigger>
                    <CollapsibleContent>
                      <div className="space-y-2 py-2">
                        {selectedRenderState?.query?.sql ? (
                          <>
                            <div className="relative">
                              <pre 
                                className="text-[10px] bg-muted p-2 pr-8 rounded overflow-x-auto max-h-40 whitespace-pre-wrap font-mono"
                                data-testid="sql-display"
                              >
                                {selectedRenderState.query.sql}
                              </pre>
                              <Button
                                variant="ghost"
                                size="icon"
                                className="absolute top-1 right-1 h-6 w-6"
                                onClick={() => copyToClipboard(selectedRenderState.query!.sql!, 'sql')}
                                data-testid="copy-sql-btn"
                                aria-label="Copy SQL"
                                title="Copy SQL to clipboard"
                              >
                                {copiedSection === 'sql' ? (
                                  <Check className="h-3 w-3 text-green-500" />
                                ) : (
                                  <Copy className="h-3 w-3" />
                                )}
                              </Button>
                            </div>
                            {(selectedRenderState.query.execution_ms !== undefined || 
                              selectedRenderState.query.row_count !== undefined) && (
                              <div className="text-[10px] text-muted-foreground" data-testid="sql-meta">
                                {selectedRenderState.query.execution_ms !== undefined && (
                                  <span>{Math.round(selectedRenderState.query.execution_ms)} ms</span>
                                )}
                                {selectedRenderState.query.row_count !== undefined && (
                                  <span className="ml-2">· {selectedRenderState.query.row_count} rows</span>
                                )}
                              </div>
                            )}
                          </>
                        ) : (
                          <p className="text-xs text-muted-foreground">No query available</p>
                        )}
                      </div>
                    </CollapsibleContent>
                  </Collapsible>
                  
                  {/* IR Section */}
                  <Collapsible open={irOpen} onOpenChange={setIrOpen}>
                    <CollapsibleTrigger asChild>
                      <Button
                        variant="ghost"
                        className="w-full justify-between px-0 h-8 font-medium hover:bg-transparent"
                        data-testid="ir-section-toggle"
                      >
                        <div className="flex items-center gap-2">
                          {irOpen ? (
                            <ChevronDown className="h-4 w-4" />
                          ) : (
                            <ChevronRight className="h-4 w-4" />
                          )}
                          <Layers className="h-3 w-3" />
                          <span className="text-xs">Query Plan</span>
                        </div>
                      </Button>
                    </CollapsibleTrigger>
                    <CollapsibleContent>
                      <div className="space-y-2 py-2">
                        {selectedRenderState?.query?.ir ? (
                          <div className="relative">
                            <pre 
                              className="text-[10px] bg-muted p-2 pr-8 rounded overflow-x-auto max-h-40 whitespace-pre-wrap font-mono"
                              data-testid="ir-display"
                            >
                              {typeof selectedRenderState.query.ir === 'string'
                                ? selectedRenderState.query.ir
                                : JSON.stringify(selectedRenderState.query.ir, null, 2)}
                            </pre>
                            <Button
                              variant="ghost"
                              size="icon"
                              className="absolute top-1 right-1 h-6 w-6"
                              onClick={() => {
                                const irText = typeof selectedRenderState.query!.ir === 'string'
                                  ? selectedRenderState.query!.ir
                                  : JSON.stringify(selectedRenderState.query!.ir, null, 2)
                                copyToClipboard(irText, 'ir')
                              }}
                              data-testid="copy-ir-btn"
                              aria-label="Copy IR"
                              title="Copy IR to clipboard"
                            >
                              {copiedSection === 'ir' ? (
                                <Check className="h-3 w-3 text-green-500" />
                              ) : (
                                <Copy className="h-3 w-3" />
                              )}
                            </Button>
                          </div>
                        ) : (
                          <p className="text-xs text-muted-foreground">IR not available</p>
                        )}
                      </div>
                    </CollapsibleContent>
                  </Collapsible>
                  
                  {/* Errors Section */}
                  {selectedRenderState?.error && (
                    <Collapsible open={errorsOpen} onOpenChange={setErrorsOpen}>
                      <CollapsibleTrigger asChild>
                        <Button
                          variant="ghost"
                          className="w-full justify-between px-0 h-8 font-medium hover:bg-transparent text-destructive"
                          data-testid="errors-section-toggle"
                        >
                          <div className="flex items-center gap-2">
                            {errorsOpen ? (
                              <ChevronDown className="h-4 w-4" />
                            ) : (
                              <ChevronRight className="h-4 w-4" />
                            )}
                            <AlertCircle className="h-3 w-3" />
                            <span className="text-xs">Errors</span>
                          </div>
                        </Button>
                      </CollapsibleTrigger>
                      <CollapsibleContent>
                        <div className="py-2">
                          <div className="relative">
                            <pre 
                              className="text-[10px] bg-destructive/10 text-destructive p-2 pr-8 rounded overflow-x-auto max-h-40 whitespace-pre-wrap font-mono"
                              data-testid="errors-display"
                            >
                              {selectedRenderState.error}
                            </pre>
                            <Button
                              variant="ghost"
                              size="icon"
                              className="absolute top-1 right-1 h-6 w-6"
                              onClick={() => copyToClipboard(selectedRenderState.error!, 'errors')}
                              data-testid="copy-errors-btn"
                              aria-label="Copy errors"
                              title="Copy errors to clipboard"
                            >
                              {copiedSection === 'errors' ? (
                                <Check className="h-3 w-3 text-green-500" />
                              ) : (
                                <Copy className="h-3 w-3" />
                              )}
                            </Button>
                          </div>
                        </div>
                      </CollapsibleContent>
                    </Collapsible>
                  )}
                </div>
              ) : (
                <p className="text-sm text-muted-foreground text-center py-8 italic">
                  Select a visual to view its properties
                </p>
              )}
            </div>
          </ScrollArea>
        </div>
      )}

      {/* ── Slicers pane ── */}
      {!slicersOpen ? (
        <button
          className="flex flex-col items-center justify-start pt-3 gap-2 w-8 hover:bg-accent/50 transition-colors cursor-pointer border-l"
          onClick={() => setSlicersOpen(true)}
          title="Open Slicers Pane"
          data-testid="slicers-pane-open"
        >
          <SlidersHorizontal className="h-4 w-4 text-muted-foreground" />
          <span className="text-[9px] text-muted-foreground [writing-mode:vertical-lr] tracking-widest">
            SLICERS
          </span>
        </button>
      ) : (
        <div className="relative flex flex-col h-full border-l" style={{ width: slicersWidth }}>
          <div {...slicersResizeProps} data-testid="slicers-resize-handle" />
          {/* Slicers title bar */}
          <div className="flex items-center justify-between px-2 py-1.5 border-b shrink-0">
            <div className="flex items-center gap-1.5">
              <SlidersHorizontal className="h-3.5 w-3.5 text-muted-foreground" />
              <span className="text-xs font-semibold tracking-wide">Slicers</span>
            </div>
            <Button
              variant="ghost"
              size="sm"
              className="h-6 w-6 p-0"
              onClick={() => setSlicersOpen(false)}
              title="Close Slicers Pane"
              data-testid="slicers-pane-close"
            >
              <X className="h-3.5 w-3.5" />
            </Button>
          </div>

          <ScrollArea className="flex-1 min-h-0">
            <div className="p-2 space-y-3">
              {/* Sync Slicers button (Power BI-style) */}
              {onOpenSyncSlicers && (
                <Button
                  variant="outline"
                  size="sm"
                  className="w-full justify-start gap-2 text-xs"
                  onClick={onOpenSyncSlicers}
                  data-testid="open-sync-slicers-btn"
                >
                  <SlidersHorizontal className="h-3.5 w-3.5" />
                  Sync slicers
                </Button>
              )}

              {/* Slicer Definitions */}
              <div>
                <div className="flex items-center justify-between mb-2">
                  <h4 className="text-xs font-medium mb-2 flex items-center gap-2">
                    <SlidersHorizontal className="h-4 w-4 text-purple-600" />
                    Definitions ({slicerDefs.length})
                  </h4>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-6 w-6"
                    onClick={() => openSlicerDefEditor()}
                    data-testid="add-slicerdef-btn"
                    aria-label="Add slicer definition"
                    title="Add slicer definition"
                  >
                    <Plus className="h-3 w-3" />
                  </Button>
                </div>
                <div className="space-y-1">
                  {slicerDefs.length === 0 ? (
                    <p className="text-xs text-muted-foreground py-2 text-center italic">No slicer definitions</p>
                  ) : (
                    slicerDefs.map(def => (
                      <div 
                        key={def.id}
                        className="text-xs px-2 py-1 bg-muted rounded flex items-center gap-1 group"
                      >
                        <span className="truncate flex-1" title={`${def.column.table}[${def.column.column}]`}>
                          {def.name}
                        </span>
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-5 w-5 opacity-0 group-hover:opacity-100"
                          onClick={() => openSlicerDefEditor(def)}
                          data-testid={`edit-slicerdef-${def.id}`}
                          aria-label="Edit slicer definition"
                          title="Edit slicer definition"
                        >
                          <Pencil className="h-3 w-3" />
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-5 w-5 opacity-0 group-hover:opacity-100 text-destructive"
                          onClick={() => handleDeleteSlicerDef(def)}
                          data-testid={`delete-slicerdef-${def.id}`}
                          aria-label="Delete slicer definition"
                          title="Delete slicer definition"
                        >
                          <Trash2 className="h-3 w-3" />
                        </Button>
                      </div>
                    ))
                  )}
                </div>
              </div>

              <Separator />

              {/* Slicer Instances */}
              <div>
                <div className="flex items-center justify-between mb-2">
                  <h4 className="text-xs font-medium mb-2 flex items-center gap-2">
                    <LayoutGrid className="h-4 w-4 text-indigo-600" />
                    Instances ({slicerInstances.length})
                  </h4>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-6 w-6"
                    onClick={() => openSlicerInstanceEditor()}
                    data-testid="add-slicerinstance-btn"
                    aria-label="Add slicer instance"
                    title="Add slicer instance"
                    disabled={slicerDefs.length === 0}
                  >
                    <Plus className="h-3 w-3" />
                  </Button>
                </div>
                <div className="space-y-1">
                  {slicerInstances.length === 0 ? (
                    <p className="text-xs text-muted-foreground py-2 text-center italic">
                      {slicerDefs.length === 0 
                        ? 'Create a slicer definition first' 
                        : 'No slicer instances placed'}
                    </p>
                  ) : (
                    slicerInstances.map(inst => {
                      const def = slicerDefs.find(d => d.id?.toLowerCase() === inst.def_id?.toLowerCase())
                      return (
                        <div 
                          key={inst.id}
                          className="text-xs px-2 py-1 bg-muted rounded flex items-center gap-1 group"
                        >
                          <span className="truncate flex-1">
                            {def?.name || inst.def_id} on {inst.page_id}
                          </span>
                          <Button
                            variant="ghost"
                            size="icon"
                            className="h-5 w-5 opacity-0 group-hover:opacity-100"
                            onClick={() => openSlicerInstanceEditor(inst)}
                            data-testid={`edit-slicerinstance-${inst.id}`}
                            aria-label="Edit slicer instance"
                            title="Edit slicer instance"
                          >
                            <Pencil className="h-3 w-3" />
                          </Button>
                          <Button
                            variant="ghost"
                            size="icon"
                            className="h-5 w-5 opacity-0 group-hover:opacity-100"
                            onClick={() => handleDuplicatePlacement(inst)}
                            data-testid={`duplicate-placement-slicerinstance-${inst.id}`}
                            aria-label="Duplicate placement"
                            title="Duplicate placement (same definition)"
                          >
                            <Copy className="h-3 w-3" />
                          </Button>
                          <Button
                            variant="ghost"
                            size="icon"
                            className="h-5 w-5 opacity-0 group-hover:opacity-100"
                            onClick={() => handleDuplicateIndependent(inst)}
                            data-testid={`duplicate-independent-slicerinstance-${inst.id}`}
                            aria-label="Duplicate independent"
                            title="Duplicate independent (new definition)"
                          >
                            <CopyPlus className="h-3 w-3" />
                          </Button>
                          <Button
                            variant="ghost"
                            size="icon"
                            className="h-5 w-5 opacity-0 group-hover:opacity-100 text-destructive"
                            onClick={() => handleDeleteSlicerInstance(inst)}
                            data-testid={`delete-slicerinstance-${inst.id}`}
                            aria-label="Delete slicer instance"
                            title="Delete slicer instance"
                          >
                            <Trash2 className="h-3 w-3" />
                          </Button>
                        </div>
                      )
                    })
                  )}
                </div>
              </div>
            </div>
          </ScrollArea>
        </div>
      )}

      {/* ── Bookmarks pane ── */}
      {!bookmarksOpen ? (
        <button
          className="flex flex-col items-center justify-start pt-3 gap-2 w-8 hover:bg-accent/50 transition-colors cursor-pointer border-l"
          onClick={() => setBookmarksOpen(true)}
          title="Open Bookmarks Pane"
          data-testid="bookmarks-pane-open"
        >
          <BookmarkIcon className="h-4 w-4 text-muted-foreground" />
          <span className="text-[9px] text-muted-foreground [writing-mode:vertical-lr] tracking-widest">
            BOOKMARKS
          </span>
        </button>
      ) : (
        <div className="relative flex flex-col h-full border-l" style={{ width: bookmarksWidth }}>
          <div {...bookmarksResizeProps} data-testid="bookmarks-resize-handle" />
          {/* Bookmarks title bar */}
          <div className="flex items-center justify-between px-2 py-1.5 border-b shrink-0">
            <div className="flex items-center gap-1.5">
              <BookmarkIcon className="h-3.5 w-3.5 text-muted-foreground" />
              <span className="text-xs font-semibold tracking-wide">Bookmarks</span>
            </div>
            <Button
              variant="ghost"
              size="sm"
              className="h-6 w-6 p-0"
              onClick={() => setBookmarksOpen(false)}
              title="Close Bookmarks Pane"
              data-testid="bookmarks-pane-close"
            >
              <X className="h-3.5 w-3.5" />
            </Button>
          </div>
          <BookmarksPanel />
        </div>
      )}

      {/* Filter Editor Dialog */}
      <FilterEditor
        open={filterEditorOpen}
        onClose={closeFilterEditor}
        scope={filterEditorScope}
        scopeId={filterEditorScopeId}
        editFilter={editingFilter}
      />

      {/* Slicer Editors */}
      <SlicerDefEditor
        open={slicerDefEditorOpen}
        onClose={closeSlicerDefEditor}
        editDef={editingSlicerDef}
      />
      <SlicerInstanceEditor
        open={slicerInstanceEditorOpen}
        onClose={closeSlicerInstanceEditor}
        editInstance={editingSlicerInstance}
        pageId={currentPageId || undefined}
      />
    </aside>
  )
}

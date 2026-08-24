import { useState, useMemo } from 'react'
import {
  ChartBar,
  ChartColumn,
  Table2,
  CreditCard,
  LineChart,
  Grid3X3,
  PieChart,
  ScatterChart,
  AreaChart,
  TrendingUp,
  Type,
  MousePointer2,
  Square,
  ImageIcon,
  SlidersHorizontal,
  ChevronLeft,
  ChevronRight,
  BarChart3,
  BoxSelect,
  Activity,
  GripHorizontal,
  Filter,
  Target,
  LayoutGrid,
  TreePine,
  Sun,
  ChevronsDown,
  Radar,
  Compass,
  Box,
  Combine,
  CircleDot,
  CandlestickChart,
  Droplets,
  Gauge,
  GitFork,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { Separator } from '@/components/ui/separator'
import { useCreateVisual, usePanelResize } from '@/hooks'
import type { VisualType } from '@/hooks/useCreateVisual'
import { useReportStore } from '@/stores/report-store'
import { isVisualTypeAvailable } from '@/lib/edition'

/**
 * Compact visual-type icon sidebar, always visible to the right of the canvas.
 *
 * Inspired by Power BI's Visualizations pane — a grid of small visual-type icons
 * that lets the user quickly add a visual to the canvas.
 *
 * Collapsed: narrow strip with expand toggle.
 * Expanded: icon grid with labels.
 */

interface VisualTypeEntry {
  type: VisualType
  icon: React.ComponentType<{ className?: string }>
  label: string
  group: 'chart' | 'statistical' | 'hierarchical' | 'polar' | '3d' | 'data' | 'ibcs' | 'slicer' | 'static' | 'financial' | 'flow'
  color: string
}

const VISUAL_TYPES: VisualTypeEntry[] = [
  // Charts
  { type: 'bar', icon: ChartBar, label: 'Bar', group: 'chart', color: 'text-blue-500' },
  { type: 'column', icon: ChartColumn, label: 'Column', group: 'chart', color: 'text-indigo-500' },
  { type: 'line', icon: LineChart, label: 'Line', group: 'chart', color: 'text-emerald-500' },
  { type: 'area', icon: AreaChart, label: 'Area', group: 'chart', color: 'text-teal-500' },
  { type: 'pie', icon: PieChart, label: 'Pie', group: 'chart', color: 'text-amber-500' },
  { type: 'scatter', icon: ScatterChart, label: 'Scatter', group: 'chart', color: 'text-rose-500' },
  { type: 'combo', icon: Combine, label: 'Combo', group: 'chart', color: 'text-fuchsia-500' },
  { type: 'bubble', icon: CircleDot, label: 'Bubble', group: 'chart', color: 'text-pink-500' },
  { type: 'funnel', icon: Filter, label: 'Funnel', group: 'chart', color: 'text-cyan-600' },
  { type: 'funnel_area', icon: Filter, label: 'Funnel Area', group: 'chart', color: 'text-cyan-400' },
  // Statistical
  { type: 'histogram', icon: BarChart3, label: 'Histogram', group: 'statistical', color: 'text-blue-400' },
  { type: 'box', icon: BoxSelect, label: 'Box Plot', group: 'statistical', color: 'text-violet-400' },
  { type: 'violin', icon: Activity, label: 'Violin', group: 'statistical', color: 'text-purple-400' },
  { type: 'strip', icon: GripHorizontal, label: 'Strip', group: 'statistical', color: 'text-pink-400' },
  { type: 'ecdf', icon: TrendingUp, label: 'ECDF', group: 'statistical', color: 'text-emerald-400' },
  { type: 'density_contour', icon: Target, label: 'Contour', group: 'statistical', color: 'text-orange-400' },
  { type: 'density_heatmap', icon: LayoutGrid, label: 'Heatmap', group: 'statistical', color: 'text-red-400' },
  // Hierarchical
  { type: 'treemap', icon: TreePine, label: 'Treemap', group: 'hierarchical', color: 'text-green-500' },
  { type: 'sunburst', icon: Sun, label: 'Sunburst', group: 'hierarchical', color: 'text-yellow-500' },
  { type: 'icicle', icon: ChevronsDown, label: 'Icicle', group: 'hierarchical', color: 'text-sky-400' },
  // Polar
  { type: 'scatter_polar', icon: Radar, label: 'Polar', group: 'polar', color: 'text-indigo-400' },
  { type: 'line_polar', icon: Radar, label: 'Radar', group: 'polar', color: 'text-teal-400' },
  { type: 'bar_polar', icon: Compass, label: 'Wind Rose', group: 'polar', color: 'text-lime-400' },
  // 3D
  { type: 'scatter_3d', icon: Box, label: '3D Scatter', group: '3d', color: 'text-violet-500' },
  { type: 'line_3d', icon: Box, label: '3D Line', group: '3d', color: 'text-blue-600' },
  { type: 'bubble_3d', icon: CircleDot, label: '3D Bubble', group: '3d', color: 'text-pink-600' },
  // Data
  { type: 'table', icon: Table2, label: 'Table', group: 'data', color: 'text-cyan-500' },
  { type: 'matrix', icon: Grid3X3, label: 'Matrix', group: 'data', color: 'text-violet-500' },
  { type: 'card', icon: CreditCard, label: 'Card', group: 'data', color: 'text-orange-500' },
  // Slicer
  { type: 'slicer', icon: SlidersHorizontal, label: 'Slicer', group: 'slicer', color: 'text-purple-500' },
  // IBCS
  { type: 'ibcs_bar', icon: ChartBar, label: 'Bar', group: 'ibcs', color: 'text-slate-600 dark:text-slate-400' },
  { type: 'ibcs_column', icon: ChartColumn, label: 'Column', group: 'ibcs', color: 'text-slate-600 dark:text-slate-400' },
  { type: 'ibcs_line', icon: LineChart, label: 'Line', group: 'ibcs', color: 'text-slate-600 dark:text-slate-400' },
  { type: 'ibcs_card', icon: CreditCard, label: 'Card', group: 'ibcs', color: 'text-slate-600 dark:text-slate-400' },
  { type: 'ibcs_waterfall', icon: TrendingUp, label: 'Waterfall', group: 'ibcs', color: 'text-slate-600 dark:text-slate-400' },
  { type: 'ibcs_table', icon: Table2, label: 'Table', group: 'ibcs', color: 'text-slate-600 dark:text-slate-400' },
  // Financial
  { type: 'candlestick', icon: CandlestickChart, label: 'Candlestick', group: 'financial', color: 'text-green-600' },
  { type: 'ohlc', icon: CandlestickChart, label: 'OHLC', group: 'financial', color: 'text-emerald-600' },
  // Flow / Specialized
  { type: 'waterfall', icon: Droplets, label: 'Waterfall', group: 'flow', color: 'text-sky-500' },
  { type: 'gauge', icon: Gauge, label: 'Gauge', group: 'flow', color: 'text-orange-600' },
  { type: 'sankey', icon: GitFork, label: 'Sankey', group: 'flow', color: 'text-violet-600' },
  // Static content
  { type: 'textbox', icon: Type, label: 'Text', group: 'static', color: 'text-gray-500' },
  { type: 'button', icon: MousePointer2, label: 'Button', group: 'static', color: 'text-sky-500' },
  { type: 'shape', icon: Square, label: 'Shape', group: 'static', color: 'text-lime-500' },
  { type: 'image', icon: ImageIcon, label: 'Image', group: 'static', color: 'text-pink-500' },
]

const AVAILABLE_VISUAL_TYPES = VISUAL_TYPES.filter((entry) => isVisualTypeAvailable(entry.type))

interface VisualsPaneProps {
  className?: string
}

export function VisualsPane({ className }: VisualsPaneProps) {
  const [expanded, setExpanded] = useState(false)
  const { quickCreateVisual } = useCreateVisual()
  const { width: visualsWidth, handleProps: visualsResizeProps } = usePanelResize({ defaultWidth: 130, minWidth: 100, maxWidth: 300, direction: 'left' })

  // Derive the visual type of the currently selected visual
  const selectedVisualId = useReportStore((s) => s.selectedVisualId)
  const visuals = useReportStore((s) => s.visuals)
  const selectedVisualType = useMemo(() => {
    if (!selectedVisualId) return null
    const v = visuals.find((vis) => vis.id === selectedVisualId)
    return v?.visual_type?.toLowerCase() || null
  }, [selectedVisualId, visuals])

  const charts = AVAILABLE_VISUAL_TYPES.filter((v) => v.group === 'chart')
  const statistical = AVAILABLE_VISUAL_TYPES.filter((v) => v.group === 'statistical')
  const hierarchical = AVAILABLE_VISUAL_TYPES.filter((v) => v.group === 'hierarchical')
  const polar = AVAILABLE_VISUAL_TYPES.filter((v) => v.group === 'polar')
  const threeDee = AVAILABLE_VISUAL_TYPES.filter((v) => v.group === '3d')
  const data = AVAILABLE_VISUAL_TYPES.filter((v) => v.group === 'data')
  const slicers = AVAILABLE_VISUAL_TYPES.filter((v) => v.group === 'slicer')
  const ibcs = AVAILABLE_VISUAL_TYPES.filter((v) => v.group === 'ibcs')
  const financial = AVAILABLE_VISUAL_TYPES.filter((v) => v.group === 'financial')
  const flow = AVAILABLE_VISUAL_TYPES.filter((v) => v.group === 'flow')
  const statics = AVAILABLE_VISUAL_TYPES.filter((v) => v.group === 'static')

  const handleCreate = (type: VisualType) => {
    quickCreateVisual(type)
  }

  const handleDragStart = (e: React.DragEvent, type: VisualType) => {
    e.dataTransfer.setData('application/x-visual-type', type)
    e.dataTransfer.effectAllowed = 'copy'
  }

  // Collapsed view: single column of icon buttons
  if (!expanded) {
    return (
      <aside
        className={cn(
          'flex flex-col border-l bg-sidebar-background overflow-y-auto overflow-x-hidden',
          className,
        )}
        style={{ width: 40 }}
        data-testid="visuals-pane"
      >
        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              variant="ghost"
              size="icon"
              className="h-7 w-7 mx-auto mt-1 mb-0.5"
              onClick={() => setExpanded(true)}
              data-testid="visuals-pane-expand"
              aria-label="Expand visualizations pane"
            >
              <ChevronLeft className="h-3.5 w-3.5" />
            </Button>
          </TooltipTrigger>
          <TooltipContent side="left">Expand</TooltipContent>
        </Tooltip>

        <Separator className="my-0.5" />

        {AVAILABLE_VISUAL_TYPES.map(({ type, icon: Icon, label, color }) => (
          <Tooltip key={type}>
            <TooltipTrigger asChild>
              <Button
                variant="ghost"
                size="icon"
                className={cn(
                  "h-7 w-7 mx-auto my-[1px] shrink-0",
                  selectedVisualType === type && "bg-accent ring-1 ring-primary/40"
                )}
                onClick={() => handleCreate(type)}
                draggable
                onDragStart={(e) => handleDragStart(e, type)}
                data-testid={`vpane-${type}`}
                aria-label={label}
              >
                <Icon className={cn("h-3.5 w-3.5", color)} />
              </Button>
            </TooltipTrigger>
            <TooltipContent side="left">{label}</TooltipContent>
          </Tooltip>
        ))}
      </aside>
    )
  }

  // Expanded view: grouped icon grid with labels
  const renderGroup = (title: string, entries: VisualTypeEntry[]) => (
    <div className="space-y-1">
      <h4 className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wide px-1">
        {title}
      </h4>
      <div className="grid grid-cols-3 gap-0.5">
        {entries.map(({ type, icon: Icon, label, color }) => (
          <Button
            key={type}
            variant="ghost"
            className={cn(
              "h-auto py-1.5 px-1 flex-col gap-0.5 rounded-md",
              selectedVisualType === type && "bg-accent ring-1 ring-primary/40"
            )}
            onClick={() => handleCreate(type)}
            draggable
            onDragStart={(e) => handleDragStart(e, type)}
            data-testid={`vpane-${type}`}
            aria-label={label}
          >
            <Icon className={cn("h-4 w-4", color)} />
            <span className="text-[9px] leading-tight truncate w-full text-center">{label}</span>
          </Button>
        ))}
      </div>
    </div>
  )

  return (
    <aside
      className={cn(
        'relative flex flex-col border-l bg-sidebar-background overflow-y-auto overflow-x-hidden',
        className,
      )}
      style={{ width: visualsWidth }}
      data-testid="visuals-pane"
    >
      <div {...visualsResizeProps} data-testid="visuals-resize-handle" />
      {/* Collapse toggle */}
      <div className="flex items-center justify-between px-1 py-1">
        <span className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wide">
          Visuals
        </span>
        <Button
          variant="ghost"
          size="icon"
          className="h-6 w-6"
          onClick={() => setExpanded(false)}
          data-testid="visuals-pane-collapse"
          aria-label="Collapse visualizations pane"
        >
          <ChevronRight className="h-3.5 w-3.5" />
        </Button>
      </div>

      <Separator className="mb-1" />

      <div className="flex flex-col gap-2 px-1 pb-2">
        {renderGroup('Charts', charts)}
        {renderGroup('Statistical', statistical)}
        {renderGroup('Hierarchical', hierarchical)}
        {renderGroup('Polar', polar)}
        {renderGroup('3D', threeDee)}
        {renderGroup('Data', data)}
        {renderGroup('Slicer', slicers)}
        {renderGroup('IBCS', ibcs)}
        {renderGroup('Financial', financial)}
        {renderGroup('Flow', flow)}
        <Separator />
        {renderGroup('Insert', statics)}
      </div>
    </aside>
  )
}

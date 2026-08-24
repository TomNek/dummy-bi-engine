import { useState } from 'react'
import {
  Plus,
  Loader2,
  ChartBar,
  ChartColumn,
  LineChart,
  PieChart,
  Table2,
  CreditCard,
  Grid3X3,
  AreaChart,
  SlidersHorizontal,
  TrendingUp,
  Type,
  MousePointer2,
  Square,
  ImageIcon,
  Database,
  Wand2,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
  DropdownMenuSeparator,
  DropdownMenuLabel,
  DropdownMenuSub,
  DropdownMenuSubTrigger,
  DropdownMenuSubContent,
} from '@/components/ui/dropdown-menu'
import { useAppStore, useReportStore } from '@/stores'
import { useMenuBar } from '@/components/layout/MenuBarContext'
import { useCreateVisual } from '@/hooks'
import { useAutogenStore } from '@/stores/autogen-store'
import { ImportDataDialog } from '@/components/model/ImportDataDialog'
import { DataSourceManager } from '@/components/model/DataSourceManager'
import type { VisualType } from '@/hooks/useCreateVisual'
import type { StaticContent } from '@/lib/api'
import { HAS_REPORT_AUTOGENERATION, IS_OPEN_CORE, isVisualTypeAvailable } from '@/lib/edition'

// ─── Visual type catalog ────────────────────────────────────────────
const visualTypeMenuItems: { type: VisualType; icon: typeof ChartBar; label: string }[] = [
  { type: 'bar', icon: ChartBar, label: 'Bar Chart' },
  { type: 'column', icon: ChartColumn, label: 'Column Chart' },
  { type: 'line', icon: LineChart, label: 'Line Chart' },
  { type: 'area', icon: AreaChart, label: 'Area Chart' },
  { type: 'pie', icon: PieChart, label: 'Pie Chart' },
  { type: 'table', icon: Table2, label: 'Table' },
  { type: 'matrix', icon: Grid3X3, label: 'Matrix' },
  { type: 'card', icon: CreditCard, label: 'Card' },
  { type: 'slicer', icon: SlidersHorizontal, label: 'Slicer' },
  { type: 'ibcs_bar', icon: ChartBar, label: 'IBCS Bar' },
  { type: 'ibcs_column', icon: ChartColumn, label: 'IBCS Column' },
  { type: 'ibcs_line', icon: LineChart, label: 'IBCS Line' },
  { type: 'ibcs_card', icon: CreditCard, label: 'IBCS Card' },
  { type: 'ibcs_waterfall', icon: TrendingUp, label: 'IBCS Waterfall' },
  { type: 'ibcs_table', icon: Table2, label: 'IBCS Table' },
]

/** Power BI button type catalog */
const BUTTON_SUB_TYPES: { buttonType: string; label: string }[] = [
  { buttonType: 'left-arrow', label: 'Left Arrow' },
  { buttonType: 'right-arrow', label: 'Right Arrow' },
  { buttonType: 'reset', label: 'Reset' },
  { buttonType: 'back', label: 'Back' },
  { buttonType: 'information', label: 'Information' },
  { buttonType: 'help', label: 'Help' },
  { buttonType: 'bookmark', label: 'Bookmark' },
  { buttonType: 'blank', label: 'Blank' },
  { buttonType: 'apply-all-slicers', label: 'Apply All Slicers' },
  { buttonType: 'clear-all-slicers', label: 'Clear All Slicers' },
  { buttonType: 'navigator', label: 'Navigator' },
]

/** Shape categories */
const SHAPE_SUB_TYPES: { category: string; shapes: { shapeType: string; label: string }[] }[] = [
  {
    category: 'Rectangles',
    shapes: [
      { shapeType: 'rectangle', label: 'Rectangle' },
      { shapeType: 'rounded-rectangle', label: 'Rounded' },
      { shapeType: 'snip-corner', label: 'Snip Corner' },
      { shapeType: 'beveled', label: 'Beveled' },
    ],
  },
  {
    category: 'Basic Shapes',
    shapes: [
      { shapeType: 'circle', label: 'Circle' },
      { shapeType: 'ellipse', label: 'Ellipse' },
      { shapeType: 'triangle', label: 'Triangle' },
      { shapeType: 'diamond', label: 'Diamond' },
      { shapeType: 'pentagon', label: 'Pentagon' },
      { shapeType: 'hexagon', label: 'Hexagon' },
      { shapeType: 'octagon', label: 'Octagon' },
      { shapeType: 'heart', label: 'Heart' },
      { shapeType: 'parallelogram', label: 'Parallelogram' },
      { shapeType: 'trapezoid', label: 'Trapezoid' },
      { shapeType: 'chevron', label: 'Chevron' },
      { shapeType: 'line', label: 'Line' },
    ],
  },
  {
    category: 'Block Arrows',
    shapes: [
      { shapeType: 'arrow-right', label: 'Arrow Right' },
      { shapeType: 'arrow-left', label: 'Arrow Left' },
      { shapeType: 'arrow-up', label: 'Arrow Up' },
      { shapeType: 'arrow-down', label: 'Arrow Down' },
    ],
  },
]

export function InsertMenu() {
  const menuBar = useMenuBar('insert')
  const projectPath = useAppStore(s => s.projectPath)
  const viewMode = useAppStore(s => s.viewMode)
  const currentPageId = useReportStore(s => s.currentPageId)
  const { quickCreateVisual, creating: creatingVisual } = useCreateVisual()
  const [importOpen, setImportOpen] = useState(false)
  const [dsmOpen, setDsmOpen] = useState(false)

  return (
    <>
      <DropdownMenu modal={false} onOpenChange={menuBar?.onOpenChange}>
        <DropdownMenuTrigger asChild>
          <Button
            ref={menuBar?.triggerRef}
            variant="ghost"
            size="sm"
            data-testid="insert-menu-trigger"
            aria-label="Insert menu"
            onMouseEnter={menuBar?.onTriggerMouseEnter}
          >
            {creatingVisual ? (
              <Loader2 className="h-4 w-4 animate-spin mr-1" />
            ) : (
              <Plus className="h-4 w-4 mr-1" />
            )}
            <span>Insert</span>
          </Button>
        </DropdownMenuTrigger>

        <DropdownMenuContent align="start" className="w-56" data-testid="insert-menu">
          {/* Visual Types — only enabled in report view with a page */}
          <DropdownMenuLabel>Visual Types</DropdownMenuLabel>
          <DropdownMenuSeparator />
          {visualTypeMenuItems.filter(item => isVisualTypeAvailable(item.type)).map(({ type, icon: Icon, label }) => (
            <DropdownMenuItem
              key={type}
              onClick={() => quickCreateVisual(type)}
              disabled={viewMode !== 'report' || !currentPageId || creatingVisual}
              data-testid={`add-visual-${type}`}
            >
              <Icon className="h-4 w-4 mr-2" />
              {label}
            </DropdownMenuItem>
          ))}

          {!IS_OPEN_CORE && <>
          <DropdownMenuSeparator />
          <DropdownMenuLabel>Static Content</DropdownMenuLabel>
          <DropdownMenuSeparator />

          <DropdownMenuItem
            onClick={() => quickCreateVisual('textbox' as VisualType)}
            disabled={viewMode !== 'report' || !currentPageId || creatingVisual}
            data-testid="add-visual-textbox"
          >
            <Type className="h-4 w-4 mr-2" />
            Text Box
          </DropdownMenuItem>

          <DropdownMenuSub>
            <DropdownMenuSubTrigger
              data-testid="add-visual-button-menu"
              disabled={viewMode !== 'report' || !currentPageId}
            >
              <MousePointer2 className="h-4 w-4 mr-2" />
              Buttons
            </DropdownMenuSubTrigger>
            <DropdownMenuSubContent>
              {BUTTON_SUB_TYPES.map(({ buttonType, label }) => (
                <DropdownMenuItem
                  key={buttonType}
                  onClick={() => quickCreateVisual('button' as VisualType, { staticContent: { buttonType, label } as StaticContent })}
                  data-testid={`add-button-${buttonType}`}
                >
                  {label}
                </DropdownMenuItem>
              ))}
            </DropdownMenuSubContent>
          </DropdownMenuSub>

          <DropdownMenuSub>
            <DropdownMenuSubTrigger
              data-testid="add-visual-shape-menu"
              disabled={viewMode !== 'report' || !currentPageId}
            >
              <Square className="h-4 w-4 mr-2" />
              Shapes
            </DropdownMenuSubTrigger>
            <DropdownMenuSubContent>
              {SHAPE_SUB_TYPES.map(({ category, shapes }) => (
                <div key={category}>
                  <DropdownMenuLabel className="text-[10px]">{category}</DropdownMenuLabel>
                  {shapes.map(({ shapeType, label }) => (
                    <DropdownMenuItem
                      key={shapeType}
                      onClick={() => quickCreateVisual('shape' as VisualType, { staticContent: { shapeType } as StaticContent })}
                      data-testid={`add-shape-${shapeType}`}
                    >
                      {label}
                    </DropdownMenuItem>
                  ))}
                </div>
              ))}
            </DropdownMenuSubContent>
          </DropdownMenuSub>

          <DropdownMenuItem
            onClick={() => quickCreateVisual('image' as VisualType)}
            disabled={viewMode !== 'report' || !currentPageId || creatingVisual}
            data-testid="add-visual-image"
          >
            <ImageIcon className="h-4 w-4 mr-2" />
            Image
          </DropdownMenuItem>
          </>}

          <DropdownMenuSeparator />
          <DropdownMenuLabel>Data</DropdownMenuLabel>
          <DropdownMenuSeparator />

          {/* Import Data */}
          <DropdownMenuItem
            onClick={() => setImportOpen(true)}
            disabled={!projectPath}
            data-testid="insert-menu-import-data"
          >
            <Database className="h-4 w-4 mr-2" />
            Import Data…
          </DropdownMenuItem>

          {/* Manage Data Sources */}
          <DropdownMenuItem
            onClick={() => setDsmOpen(true)}
            disabled={!projectPath}
            data-testid="insert-menu-manage-sources"
          >
            <SlidersHorizontal className="h-4 w-4 mr-2" />
            Manage Data Sources…
          </DropdownMenuItem>

          {/* Auto-Generate Report */}
          {HAS_REPORT_AUTOGENERATION && <DropdownMenuItem
            onClick={() => useAutogenStore.getState().setOpen(true)}
            disabled={!projectPath}
            data-testid="insert-menu-autogen"
          >
            <Wand2 className="h-4 w-4 mr-2" />
            Auto-Generate Report…
          </DropdownMenuItem>}
        </DropdownMenuContent>
      </DropdownMenu>

      <ImportDataDialog open={importOpen} onOpenChange={setImportOpen} />
      <DataSourceManager
        open={dsmOpen}
        onOpenChange={setDsmOpen}
        onOpenImport={() => setImportOpen(true)}
      />
    </>
  )
}

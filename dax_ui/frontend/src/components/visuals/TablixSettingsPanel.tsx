/**
 * TablixSettingsPanel - Settings for Matrix visual configuration
 * Includes subtotals, gridlines, density, and sizing options
 */

import { useState, useMemo, useEffect } from 'react'
import { ChevronDown, ChevronRight, Plus, Trash2, ArrowUp, ArrowDown, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import {
  DropdownMenu, DropdownMenuTrigger, DropdownMenuContent, DropdownMenuCheckboxItem, DropdownMenuSeparator,
} from '@/components/ui/dropdown-menu'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { Separator } from '@/components/ui/separator'
import { useAppStore } from '@/stores'
import { useCalcGroups } from '@/hooks'

/**
 * MeasureBlockDef — matches the server's ColumnMeasureBlock / RowMeasureBlock shape.
 *
 * measureMode:
 *   - 'explicit' (default) — the block uses `measureId` as a specific measure
 *   - 'base'               — the block reuses the matrix's Values measures
 *   - 'base_calc'          — base measures wrapped with a calculation group item
 *   - 'blank'              — empty cells (spacer column/row)
 */
export type MeasureMode = 'explicit' | 'base' | 'base_calc' | 'blank'

export interface ColumnFieldRef {
  table: string
  column: string
}

export interface MeasureBlockDef {
  id?: string
  measureId?: string
  measureMode?: MeasureMode
  columnFields?: ColumnFieldRef[]   // CMB only: grouping columns for mini-matrix
  rowFields?: ColumnFieldRef[]      // RMB only: grouping rows for mini-matrix
  placement?: string                // 'left'|'right' for CMB, 'top'|'bottom' for RMB
  label?: string
  width?: number | null             // CMB pixel width
  height?: number | null            // RMB pixel height
  appliesTo?: string[]              // Row scope: 'leaf','group','subtotal','grand_total'
  calcGroupItem?: string | null     // 'GroupName|ItemName' for base_calc mode
  showSubtotals?: boolean           // Preferred camelCase per-block subtotal toggle
  subtotalLevels?: Record<number, boolean>  // Preferred camelCase per-level subtotal toggles
  show_subtotals?: boolean          // Per-block subtotal toggle (null = inherit from global)
  subtotal_levels?: Record<number, boolean>  // Per-level subtotal toggles within the block
  // Legacy compat: if the block was created with the old generic shape
  measures?: Array<string | { measure: string; table?: string }>
}

export type HeaderBandType = 'label' | 'row_attribute' | 'col_attribute' | 'measure'

export interface HeaderBandDef {
  bandType?: HeaderBandType
  label?: string
  spans?: string[]
  spanScope?: 'main' | 'all'
  spanBlocks?: string[]   // specific block IDs to include in the span
  rowIndex?: number
  rotate?: boolean
  merge?: boolean
  measureId?: string | null
  pathLevel?: number
  appliesTo?: string[]
  width?: number
  height?: number
  displayLevel?: number   // position index (0 = outermost)
}

export interface TablixSettings {
  show_subtotals?: boolean
  show_col_subtotals?: boolean
  row_subtotal_levels?: Record<number, boolean>   // per-level row subtotal toggles (key = level index)
  col_subtotal_levels?: Record<number, boolean>   // per-level col subtotal toggles (key = level index)
  subtotal_placement?: 'before_children' | 'after_children'
  grand_total_visibility?: 'none' | 'rows' | 'columns' | 'both'
  repeat_row_headers?: boolean
  repeat_column_headers?: boolean
  gridlines?: 'none' | 'light' | 'dark'
  density?: 'compact' | 'normal' | 'comfortable'
  columnHeaderBackColor?: string | null
  row_header_width_mode?: 'auto' | 'fixed'
  column_width_mode?: 'fit_to_content' | 'grow_to_fit' | 'fixed' | string
  more_granular_column_widths?: boolean
  mobile_column_widths?: Record<string, number>
  autofit_columns?: boolean
  autofit_rows?: boolean
  snap_columns_to_fit?: boolean
  default_column_width?: number
  default_row_height?: number
  suppressBlankCols?: boolean
  columnMeasureBlocks?: MeasureBlockDef[]
  rowMeasureBlocks?: MeasureBlockDef[]
  colHeaderBands?: HeaderBandDef[]
  rowHeaderBands?: HeaderBandDef[]
}

/** Field reference from visual encodings (rows/cols arrays). */
export interface FieldRef {
  table?: string
  column: string
}

interface TablixSettingsPanelProps {
  settings: TablixSettings
  rowFields?: FieldRef[]    // base matrix row hierarchy fields
  colFields?: FieldRef[]    // base matrix column hierarchy fields
  onUpdate: (key: keyof TablixSettings, value: unknown) => void
}

export function TablixSettingsPanel({ settings, rowFields, colFields, onUpdate }: TablixSettingsPanelProps) {
  const [subtotalsOpen, setSubtotalsOpen] = useState(true)
  const [displayOpen, setDisplayOpen] = useState(true)
  const [sizingOpen, setSizingOpen] = useState(false)
  const [colBlocksOpen, setColBlocksOpen] = useState(false)
  const [rowBlocksOpen, setRowBlocksOpen] = useState(false)
  const [colBandsOpen, setColBandsOpen] = useState(false)
  const [rowBandsOpen, setRowBandsOpen] = useState(false)
  const measures = useAppStore(s => s.measures) ?? []

  const showSubtotals = settings.show_subtotals !== false
  const showColSubtotals = settings.show_col_subtotals !== false
  const columnMeasureBlocks = settings.columnMeasureBlocks || []
  const rowMeasureBlocks = settings.rowMeasureBlocks || []
  const subtotalPlacement = settings.subtotal_placement || 'after_children'
  const grandTotalVisibility = settings.grand_total_visibility || 'both'
  const repeatRowHeaders = settings.repeat_row_headers !== false
  const repeatColumnHeaders = settings.repeat_column_headers !== false
  const suppressBlankCols = settings.suppressBlankCols === true
  const gridlines = settings.gridlines || 'light'
  const density = settings.density || 'normal'
  const rowHeaderWidthMode = settings.row_header_width_mode || 'auto'
  const autofitColumns = settings.autofit_columns !== false
  const autofitRows = settings.autofit_rows !== false
  const snapColumnsToFit = settings.snap_columns_to_fit !== false
  const columnWidthMode = String(settings.column_width_mode || (autofitColumns ? (snapColumnsToFit ? 'grow_to_fit' : 'fit_to_content') : 'fixed'))
  const moreGranularColumnWidths = settings.more_granular_column_widths === true
  const mobileColumnWidthsCount = Object.keys(settings.mobile_column_widths || {}).length
  const defaultColumnWidth = settings.default_column_width ?? 100
  const defaultRowHeight = settings.default_row_height ?? 32

  const getBlockShowSubtotals = (block: MeasureBlockDef): boolean => {
    if (block.showSubtotals !== undefined) return block.showSubtotals !== false
    return block.show_subtotals !== false
  }

  const getBlockSubtotalLevels = (block: MeasureBlockDef): Record<number, boolean> => {
    return (block.subtotalLevels || block.subtotal_levels || {}) as Record<number, boolean>
  }

  return (
    <div className="space-y-3" data-testid="tablix-settings-panel">
      {/* Subtotals Section */}
      <Collapsible open={subtotalsOpen} onOpenChange={setSubtotalsOpen}>
        <CollapsibleTrigger asChild>
          <Button
            variant="ghost"
            className="w-full justify-between px-0 h-7 font-medium hover:bg-transparent"
            data-testid="tablix-subtotals-toggle"
          >
            <div className="flex items-center gap-2">
              {subtotalsOpen ? (
                <ChevronDown className="h-3 w-3" />
              ) : (
                <ChevronRight className="h-3 w-3" />
              )}
              <span className="text-xs">Subtotals & Totals</span>
            </div>
          </Button>
        </CollapsibleTrigger>
        <CollapsibleContent>
          <div className="space-y-3 py-2 pl-5">
            <div className="flex items-center justify-between">
              <Label htmlFor="show-row-subtotals" className="text-xs">
                Show row subtotals
              </Label>
              <Switch
                id="show-row-subtotals"
                checked={showSubtotals}
                onCheckedChange={(checked: boolean) => onUpdate('show_subtotals', checked)}
                data-testid="tablix-show-row-subtotals"
              />
            </div>

            {/* Per-level row subtotal toggles (only non-leaf levels can have subtotals) */}
            {showSubtotals && rowFields && rowFields.length > 1 && (
              <div className="space-y-1 pl-4 border-l border-muted">
                {rowFields.slice(0, -1).map((f, lvl) => {
                  const levelEnabled = settings.row_subtotal_levels?.[lvl] !== false
                  return (
                    <div key={lvl} className="flex items-center justify-between" data-testid={`row-subtotal-level-${lvl}`}>
                      <Label className="text-[11px] text-muted-foreground">{f.column} subtotals</Label>
                      <Switch
                        checked={levelEnabled}
                        onCheckedChange={(checked: boolean) => {
                          const levels = { ...(settings.row_subtotal_levels || {}) }
                          levels[lvl] = checked
                          onUpdate('row_subtotal_levels', levels)
                        }}
                        className="scale-75"
                      />
                    </div>
                  )
                })}
              </div>
            )}

            <div className="flex items-center justify-between">
              <Label htmlFor="show-col-subtotals" className="text-xs">
                Show column subtotals
              </Label>
              <Switch
                id="show-col-subtotals"
                checked={showColSubtotals}
                onCheckedChange={(checked: boolean) => onUpdate('show_col_subtotals', checked)}
                data-testid="tablix-show-col-subtotals"
              />
            </div>

            {/* Per-level column subtotal toggles */}
            {showColSubtotals && colFields && colFields.length > 1 && (
              <div className="space-y-1 pl-4 border-l border-muted">
                {colFields.slice(0, -1).map((f, lvl) => {
                  const levelEnabled = settings.col_subtotal_levels?.[lvl] !== false
                  return (
                    <div key={lvl} className="flex items-center justify-between" data-testid={`col-subtotal-level-${lvl}`}>
                      <Label className="text-[11px] text-muted-foreground">{f.column} subtotals</Label>
                      <Switch
                        checked={levelEnabled}
                        onCheckedChange={(checked: boolean) => {
                          const levels = { ...(settings.col_subtotal_levels || {}) }
                          levels[lvl] = checked
                          onUpdate('col_subtotal_levels', levels)
                        }}
                        className="scale-75"
                      />
                    </div>
                  )
                })}
              </div>
            )}

            {showColSubtotals && columnMeasureBlocks.length > 0 && (
              <div className="space-y-1">
                <Label className="text-[11px]">CMB subtotal levels</Label>
                <div className="space-y-2 pl-4 border-l border-muted" data-testid="tablix-cmb-subtotals-list">
                  {columnMeasureBlocks.map((block, blockIdx) => {
                    const blockName = block.label || block.measureId || `CMB ${blockIdx + 1}`
                    const blockFields = block.columnFields || []
                    const blockSubtotalsOn = getBlockShowSubtotals(block)
                    return (
                      <div key={`cmb-subtotals-${block.id || blockIdx}`} className="space-y-1" data-testid={`tablix-cmb-subtotals-${blockIdx}`}>
                        <div className="flex items-center justify-between">
                          <Label className="text-[10px] text-muted-foreground">{blockName}</Label>
                          <Switch
                            checked={blockSubtotalsOn}
                            onCheckedChange={(checked: boolean) => {
                              const nextBlocks = [...columnMeasureBlocks]
                              const current = nextBlocks[blockIdx] || {}
                              nextBlocks[blockIdx] = { ...current, showSubtotals: checked, show_subtotals: checked }
                              onUpdate('columnMeasureBlocks' as keyof TablixSettings, nextBlocks)
                            }}
                            className="scale-75"
                            data-testid={`tablix-cmb-subtotals-toggle-${blockIdx}`}
                          />
                        </div>
                        {blockSubtotalsOn && blockFields.length > 1 && (
                          <div className="space-y-0.5 pl-3 border-l border-muted">
                            {blockFields.slice(0, -1).map((field, levelIdx) => {
                              const enabled = getBlockSubtotalLevels(block)?.[levelIdx] !== false
                              return (
                                <div key={`${blockIdx}-${levelIdx}`} className="flex items-center justify-between" data-testid={`tablix-cmb-subtotal-level-${blockIdx}-${levelIdx}`}>
                                  <Label className="text-[10px] text-muted-foreground">{field.column}</Label>
                                  <Switch
                                    checked={enabled}
                                    onCheckedChange={(checked: boolean) => {
                                      const nextBlocks = [...columnMeasureBlocks]
                                      const current = nextBlocks[blockIdx] || {}
                                      const levels = { ...((current as MeasureBlockDef).subtotalLevels || (current as MeasureBlockDef).subtotal_levels || {}) }
                                      levels[levelIdx] = checked
                                      nextBlocks[blockIdx] = { ...current, subtotalLevels: levels, subtotal_levels: levels }
                                      onUpdate('columnMeasureBlocks' as keyof TablixSettings, nextBlocks)
                                    }}
                                    className="scale-75"
                                  />
                                </div>
                              )
                            })}
                          </div>
                        )}
                      </div>
                    )
                  })}
                </div>
              </div>
            )}

            {showSubtotals && rowMeasureBlocks.length > 0 && (
              <div className="space-y-1">
                <Label className="text-[11px]">RMB subtotal levels</Label>
                <div className="space-y-2 pl-4 border-l border-muted" data-testid="tablix-rmb-subtotals-list">
                  {rowMeasureBlocks.map((block, blockIdx) => {
                    const blockName = block.label || block.measureId || `RMB ${blockIdx + 1}`
                    const blockFields = block.rowFields || []
                    const blockSubtotalsOn = getBlockShowSubtotals(block)
                    return (
                      <div key={`rmb-subtotals-${block.id || blockIdx}`} className="space-y-1" data-testid={`tablix-rmb-subtotals-${blockIdx}`}>
                        <div className="flex items-center justify-between">
                          <Label className="text-[10px] text-muted-foreground">{blockName}</Label>
                          <Switch
                            checked={blockSubtotalsOn}
                            onCheckedChange={(checked: boolean) => {
                              const nextBlocks = [...rowMeasureBlocks]
                              const current = nextBlocks[blockIdx] || {}
                              nextBlocks[blockIdx] = { ...current, showSubtotals: checked, show_subtotals: checked }
                              onUpdate('rowMeasureBlocks' as keyof TablixSettings, nextBlocks)
                            }}
                            className="scale-75"
                            data-testid={`tablix-rmb-subtotals-toggle-${blockIdx}`}
                          />
                        </div>
                        {blockSubtotalsOn && blockFields.length > 1 && (
                          <div className="space-y-0.5 pl-3 border-l border-muted">
                            {blockFields.slice(0, -1).map((field, levelIdx) => {
                              const enabled = getBlockSubtotalLevels(block)?.[levelIdx] !== false
                              return (
                                <div key={`${blockIdx}-${levelIdx}`} className="flex items-center justify-between" data-testid={`tablix-rmb-subtotal-level-${blockIdx}-${levelIdx}`}>
                                  <Label className="text-[10px] text-muted-foreground">{field.column}</Label>
                                  <Switch
                                    checked={enabled}
                                    onCheckedChange={(checked: boolean) => {
                                      const nextBlocks = [...rowMeasureBlocks]
                                      const current = nextBlocks[blockIdx] || {}
                                      const levels = { ...((current as MeasureBlockDef).subtotalLevels || (current as MeasureBlockDef).subtotal_levels || {}) }
                                      levels[levelIdx] = checked
                                      nextBlocks[blockIdx] = { ...current, subtotalLevels: levels, subtotal_levels: levels }
                                      onUpdate('rowMeasureBlocks' as keyof TablixSettings, nextBlocks)
                                    }}
                                    className="scale-75"
                                  />
                                </div>
                              )
                            })}
                          </div>
                        )}
                      </div>
                    )
                  })}
                </div>
              </div>
            )}

            <div className="space-y-1">
              <Label className="text-xs">Subtotal placement</Label>
              <Select
                value={subtotalPlacement}
                onValueChange={(val) => onUpdate('subtotal_placement', val)}
              >
                <SelectTrigger className="h-7 text-xs" data-testid="tablix-subtotal-placement">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="before_children">Before children</SelectItem>
                  <SelectItem value="after_children">After children</SelectItem>
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-1">
              <Label className="text-xs">Grand totals</Label>
              <Select
                value={grandTotalVisibility}
                onValueChange={(val) => onUpdate('grand_total_visibility', val)}
              >
                <SelectTrigger className="h-7 text-xs" data-testid="tablix-grand-totals">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="none">None</SelectItem>
                  <SelectItem value="rows">Rows only</SelectItem>
                  <SelectItem value="columns">Columns only</SelectItem>
                  <SelectItem value="both">Both</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>
        </CollapsibleContent>
      </Collapsible>

      <Separator />

      {/* Display Section */}
      <Collapsible open={displayOpen} onOpenChange={setDisplayOpen}>
        <CollapsibleTrigger asChild>
          <Button
            variant="ghost"
            className="w-full justify-between px-0 h-7 font-medium hover:bg-transparent"
            data-testid="tablix-display-toggle"
          >
            <div className="flex items-center gap-2">
              {displayOpen ? (
                <ChevronDown className="h-3 w-3" />
              ) : (
                <ChevronRight className="h-3 w-3" />
              )}
              <span className="text-xs">Display</span>
            </div>
          </Button>
        </CollapsibleTrigger>
        <CollapsibleContent>
          <div className="space-y-3 py-2 pl-5">
            <div className="flex items-center justify-between">
              <Label htmlFor="repeat-row-headers" className="text-xs">
                Repeat row headers
              </Label>
              <Switch
                id="repeat-row-headers"
                checked={repeatRowHeaders}
                onCheckedChange={(checked: boolean) => onUpdate('repeat_row_headers', checked)}
                data-testid="tablix-repeat-row-headers"
              />
            </div>

            <div className="flex items-center justify-between">
              <Label htmlFor="repeat-column-headers" className="text-xs">
                Repeat column headers
              </Label>
              <Switch
                id="repeat-column-headers"
                checked={repeatColumnHeaders}
                onCheckedChange={(checked: boolean) => onUpdate('repeat_column_headers', checked)}
                data-testid="tablix-repeat-column-headers"
              />
            </div>

            <div className="flex items-center justify-between">
              <Label htmlFor="suppress-blank-cols" className="text-xs">
                Suppress blank columns
              </Label>
              <Switch
                id="suppress-blank-cols"
                checked={suppressBlankCols}
                onCheckedChange={(checked: boolean) => onUpdate('suppressBlankCols', checked)}
                data-testid="tablix-suppress-blank-cols"
              />
            </div>

            <div className="space-y-1">
              <Label className="text-xs">Gridlines</Label>
              <Select
                value={gridlines}
                onValueChange={(val) => onUpdate('gridlines', val)}
              >
                <SelectTrigger className="h-7 text-xs" data-testid="tablix-gridlines">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="none">None</SelectItem>
                  <SelectItem value="light">Light</SelectItem>
                  <SelectItem value="dark">Dark</SelectItem>
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-1">
              <Label className="text-xs">Density</Label>
              <Select
                value={density}
                onValueChange={(val) => onUpdate('density', val)}
              >
                <SelectTrigger className="h-7 text-xs" data-testid="tablix-density">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="compact">Compact</SelectItem>
                  <SelectItem value="normal">Normal</SelectItem>
                  <SelectItem value="comfortable">Comfortable</SelectItem>
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-1">
              <Label className="text-xs">Column Header Background</Label>
              <div className="flex items-center gap-2">
                <input
                  type="color"
                  title="Column header background color"
                  value={settings.columnHeaderBackColor || '#e5e7eb'}
                  onChange={(e) => onUpdate('columnHeaderBackColor', e.target.value)}
                  className="h-7 w-10 rounded border cursor-pointer"
                  data-testid="tablix-col-header-bg"
                />
                {settings.columnHeaderBackColor && (
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-7 px-2 text-xs"
                    onClick={() => onUpdate('columnHeaderBackColor', null)}
                  >
                    Reset
                  </Button>
                )}
              </div>
            </div>

            <div className="space-y-1">
              <Label className="text-xs">Row header width</Label>
              <Select
                value={rowHeaderWidthMode}
                onValueChange={(val) => onUpdate('row_header_width_mode', val)}
              >
                <SelectTrigger className="h-7 text-xs" data-testid="tablix-row-header-width-mode">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="auto">Auto</SelectItem>
                  <SelectItem value="fixed">Fixed</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>
        </CollapsibleContent>
      </Collapsible>

      <Separator />

      {/* Sizing Section */}
      <Collapsible open={sizingOpen} onOpenChange={setSizingOpen}>
        <CollapsibleTrigger asChild>
          <Button
            variant="ghost"
            className="w-full justify-between px-0 h-7 font-medium hover:bg-transparent"
            data-testid="tablix-sizing-toggle"
          >
            <div className="flex items-center gap-2">
              {sizingOpen ? (
                <ChevronDown className="h-3 w-3" />
              ) : (
                <ChevronRight className="h-3 w-3" />
              )}
              <span className="text-xs">Sizing</span>
            </div>
          </Button>
        </CollapsibleTrigger>
        <CollapsibleContent>
          <div className="space-y-3 py-2 pl-5">
            <div className="flex items-center justify-between">
              <Label htmlFor="autofit-columns" className="text-xs">
                Autofit columns
              </Label>
              <Switch
                id="autofit-columns"
                checked={autofitColumns}
                onCheckedChange={(checked: boolean) => onUpdate('autofit_columns', checked)}
                data-testid="tablix-autofit-columns"
              />
            </div>

            <div className="flex items-center justify-between">
              <Label htmlFor="snap-columns-to-fit" className="text-xs">
                Snap columns to fit
              </Label>
              <Switch
                id="snap-columns-to-fit"
                checked={snapColumnsToFit}
                onCheckedChange={(checked: boolean) => onUpdate('snap_columns_to_fit', checked)}
                data-testid="tablix-snap-columns-to-fit"
              />
            </div>

            <div className="space-y-1">
              <Label className="text-xs">Column width mode</Label>
              <Select
                value={columnWidthMode}
                onValueChange={(value) => {
                  onUpdate('column_width_mode', value)
                  if (value === 'fixed') {
                    onUpdate('autofit_columns', false)
                    onUpdate('snap_columns_to_fit', false)
                  } else if (value === 'grow_to_fit') {
                    onUpdate('autofit_columns', true)
                    onUpdate('snap_columns_to_fit', true)
                  } else {
                    onUpdate('autofit_columns', true)
                    onUpdate('snap_columns_to_fit', false)
                  }
                }}
              >
                <SelectTrigger className="h-7 text-xs" data-testid="tablix-column-width-mode">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="fit_to_content">Fit to content</SelectItem>
                  <SelectItem value="grow_to_fit">Grow to fit</SelectItem>
                  <SelectItem value="fixed">Fixed width</SelectItem>
                </SelectContent>
              </Select>
            </div>

            <div className="flex items-center justify-between">
              <Label htmlFor="more-granular-column-widths" className="text-xs">
                More granular leaf widths
              </Label>
              <Switch
                id="more-granular-column-widths"
                checked={moreGranularColumnWidths}
                onCheckedChange={(checked: boolean) => onUpdate('more_granular_column_widths', checked)}
                data-testid="tablix-more-granular-column-widths"
              />
            </div>

            <div className="flex items-center justify-between">
              <Label htmlFor="autofit-rows" className="text-xs">
                Autofit rows
              </Label>
              <Switch
                id="autofit-rows"
                checked={autofitRows}
                onCheckedChange={(checked: boolean) => onUpdate('autofit_rows', checked)}
                data-testid="tablix-autofit-rows"
              />
            </div>

            <div className="space-y-1">
              <Label className="text-xs">Default column width (px)</Label>
              <Input
                type="number"
                className="h-7 text-xs w-20"
                value={defaultColumnWidth}
                min={30}
                max={500}
                onChange={e => {
                  const val = parseInt(e.target.value, 10)
                  onUpdate('default_column_width', isNaN(val) ? 100 : val)
                }}
                data-testid="tablix-default-column-width"
              />
            </div>

            <div className="space-y-1">
              <Label className="text-xs">Default row height (px)</Label>
              <Input
                type="number"
                className="h-7 text-xs w-20"
                value={defaultRowHeight}
                min={20}
                max={200}
                onChange={e => {
                  const val = parseInt(e.target.value, 10)
                  onUpdate('default_row_height', isNaN(val) ? 32 : val)
                }}
                data-testid="tablix-default-row-height"
              />
            </div>

            {mobileColumnWidthsCount > 0 && (
              <div className="rounded border bg-muted/30 px-2 py-1 text-[10px] text-muted-foreground" data-testid="tablix-mobile-widths-preserved">
                {mobileColumnWidthsCount} mobile width override{mobileColumnWidthsCount === 1 ? '' : 's'} preserved for mobile layout metadata.
              </div>
            )}
          </div>
        </CollapsibleContent>
      </Collapsible>

      <Separator />

      {/* Column Measure Blocks */}
      <Collapsible open={colBlocksOpen} onOpenChange={setColBlocksOpen}>
        <CollapsibleTrigger asChild>
          <Button
            variant="ghost"
            className="w-full justify-between px-0 h-7 font-medium hover:bg-transparent"
            data-testid="tablix-col-blocks-toggle"
          >
            <div className="flex items-center gap-2">
              {colBlocksOpen ? (
                <ChevronDown className="h-3 w-3" />
              ) : (
                <ChevronRight className="h-3 w-3" />
              )}
              <span className="text-xs">Column Measure Blocks</span>
            </div>
          </Button>
        </CollapsibleTrigger>
        <CollapsibleContent>
          <div className="space-y-2 py-2 pl-5">
            <MeasureBlockList
              blocks={settings.columnMeasureBlocks || []}
              axis="column"
              availableMeasures={measures}
              onUpdate={(blocks) => onUpdate('columnMeasureBlocks' as keyof TablixSettings, blocks)}
            />
          </div>
        </CollapsibleContent>
      </Collapsible>

      <Separator />

      {/* Row Measure Blocks */}
      <Collapsible open={rowBlocksOpen} onOpenChange={setRowBlocksOpen}>
        <CollapsibleTrigger asChild>
          <Button
            variant="ghost"
            className="w-full justify-between px-0 h-7 font-medium hover:bg-transparent"
            data-testid="tablix-row-blocks-toggle"
          >
            <div className="flex items-center gap-2">
              {rowBlocksOpen ? (
                <ChevronDown className="h-3 w-3" />
              ) : (
                <ChevronRight className="h-3 w-3" />
              )}
              <span className="text-xs">Row Measure Blocks</span>
            </div>
          </Button>
        </CollapsibleTrigger>
        <CollapsibleContent>
          <div className="space-y-2 py-2 pl-5">
            <MeasureBlockList
              blocks={settings.rowMeasureBlocks || []}
              axis="row"
              availableMeasures={measures}
              onUpdate={(blocks) => onUpdate('rowMeasureBlocks' as keyof TablixSettings, blocks)}
            />
          </div>
        </CollapsibleContent>
      </Collapsible>

      <Separator />

      {/* Column Header Bands */}
      <Collapsible open={colBandsOpen} onOpenChange={setColBandsOpen}>
        <CollapsibleTrigger asChild>
          <Button
            variant="ghost"
            className="w-full justify-between px-0 h-7 font-medium hover:bg-transparent"
            data-testid="tablix-col-bands-toggle"
          >
            <div className="flex items-center gap-2">
              {colBandsOpen ? (
                <ChevronDown className="h-3 w-3" />
              ) : (
                <ChevronRight className="h-3 w-3" />
              )}
              <span className="text-xs">Column Header Bands</span>
            </div>
          </Button>
        </CollapsibleTrigger>
        <CollapsibleContent>
          <div className="space-y-2 py-2 pl-5">
            <HeaderBandList
              bands={settings.colHeaderBands || []}
              axis="col"
              availableMeasures={measures}
              onUpdate={(bands) => onUpdate('colHeaderBands' as keyof TablixSettings, bands)}
              availableBlocks={settings.columnMeasureBlocks || []}
            />
          </div>
        </CollapsibleContent>
      </Collapsible>

      <Separator />

      {/* Row Header Bands */}
      <Collapsible open={rowBandsOpen} onOpenChange={setRowBandsOpen}>
        <CollapsibleTrigger asChild>
          <Button
            variant="ghost"
            className="w-full justify-between px-0 h-7 font-medium hover:bg-transparent"
            data-testid="tablix-row-bands-toggle"
          >
            <div className="flex items-center gap-2">
              {rowBandsOpen ? (
                <ChevronDown className="h-3 w-3" />
              ) : (
                <ChevronRight className="h-3 w-3" />
              )}
              <span className="text-xs">Row Header Bands</span>
            </div>
          </Button>
        </CollapsibleTrigger>
        <CollapsibleContent>
          <div className="space-y-2 py-2 pl-5">
            <HeaderBandList
              bands={settings.rowHeaderBands || []}
              axis="row"
              availableMeasures={measures}
              onUpdate={(bands) => onUpdate('rowHeaderBands' as keyof TablixSettings, bands)}
              availableBlocks={settings.rowMeasureBlocks || []}
            />
          </div>
        </CollapsibleContent>
      </Collapsible>
    </div>
  )
}

// -- Measure Block List sub-component --
// Matches the old UI's renderColumnMeasureBlocksUI / renderRowMeasureBlocksUI
interface MeasureBlockListProps {
  blocks: MeasureBlockDef[]
  axis: 'column' | 'row'
  availableMeasures: string[]
  onUpdate: (blocks: MeasureBlockDef[]) => void
}

const MEASURE_MODES: { value: MeasureMode; label: string; title: string }[] = [
  { value: 'explicit', label: 'Explicit', title: 'Pick a specific measure' },
  { value: 'base', label: 'Base', title: 'Use all measures from the matrix Values field' },
  { value: 'base_calc', label: 'Base+CG', title: 'Base measures + calculation group item' },
  { value: 'blank', label: 'Blank', title: 'Empty cells (spacer)' },
]

const ROW_TYPES = [
  { value: 'leaf', label: 'Leaf', title: 'Detail/leaf rows' },
  { value: 'group', label: 'Grp', title: 'Group header rows' },
  { value: 'subtotal', label: 'Sub', title: 'Subtotal rows' },
  { value: 'grand_total', label: 'GT', title: 'Grand total row' },
]

function MeasureBlockList({ blocks, axis, availableMeasures, onUpdate }: MeasureBlockListProps) {
  const tables = useAppStore(s => s.tables) ?? []
  const { calcGroups, load: loadCalcGroups } = useCalcGroups()

  // Load calc groups on mount so the CG item picker has data
  useEffect(() => { loadCalcGroups() }, [loadCalcGroups])

  // Build calc group items list: "GroupName|ItemName"
  const calcGroupItems = useMemo(() => {
    const items: { value: string; label: string }[] = []
    for (const cg of calcGroups) {
      const groupName = cg.name || ''
      for (const item of cg.items || []) {
        const itemName = item.name || ''
        if (groupName && itemName) {
          items.push({ value: `${groupName}|${itemName}`, label: `${groupName}[${itemName}]` })
        }
      }
    }
    return items
  }, [calcGroups])

  const safeBlocks = Array.isArray(blocks) ? blocks : []

  const addBlock = () => {
    const newBlock: MeasureBlockDef = {
      measureId: availableMeasures[0] || '',
      measureMode: 'explicit',
      placement: axis === 'column' ? 'right' : 'bottom',
      label: '',
      width: null,
      height: null,
      appliesTo: ['leaf', 'group', 'subtotal', 'grand_total'],
      columnFields: [],
      rowFields: [],
      calcGroupItem: null,
    }
    onUpdate([...safeBlocks, newBlock])
  }

  const removeBlock = (idx: number) => {
    onUpdate(safeBlocks.filter((_, i) => i !== idx))
  }

  const updateBlock = (idx: number, patch: Partial<MeasureBlockDef>) => {
    onUpdate(safeBlocks.map((b, i) => i === idx ? { ...b, ...patch } : b))
  }

  const getBlockShowSubtotals = (block: MeasureBlockDef): boolean => {
    if (block.showSubtotals !== undefined) return block.showSubtotals !== false
    return block.show_subtotals !== false
  }

  const getBlockSubtotalLevels = (block: MeasureBlockDef): Record<number, boolean> => {
    return (block.subtotalLevels || block.subtotal_levels || {}) as Record<number, boolean>
  }

  const moveBlock = (idx: number, direction: -1 | 1) => {
    const target = idx + direction
    if (target < 0 || target >= safeBlocks.length) return
    const updated = [...safeBlocks]
    ;[updated[idx], updated[target]] = [updated[target], updated[idx]]
    onUpdate(updated)
  }

  const addColumnField = (blockIdx: number, table: string, column: string) => {
    const block = safeBlocks[blockIdx]
    const fieldKey = axis === 'column' ? 'columnFields' : 'rowFields'
    const existing = (block[fieldKey] || []) as ColumnFieldRef[]
    // Avoid duplicates
    if (existing.some(f => f.table === table && f.column === column)) return
    updateBlock(blockIdx, { [fieldKey]: [...existing, { table, column }] })
  }

  const removeColumnField = (blockIdx: number, fieldIdx: number) => {
    const block = safeBlocks[blockIdx]
    const fieldKey = axis === 'column' ? 'columnFields' : 'rowFields'
    const existing = (block[fieldKey] || []) as ColumnFieldRef[]
    updateBlock(blockIdx, { [fieldKey]: existing.filter((_, i) => i !== fieldIdx) })
  }

  return (
    <div className="space-y-3">
      {safeBlocks.map((block, idx) => {
        const mode: MeasureMode = block.measureMode || 'explicit'
        const placements = axis === 'column'
          ? [{ value: 'left', label: 'Left' }, { value: 'right', label: 'Right' }]
          : [{ value: 'top', label: 'Top' }, { value: 'bottom', label: 'Bottom' }]
        const currentAppliesTo = Array.isArray(block.appliesTo)
          ? block.appliesTo
          : ['leaf', 'group', 'subtotal', 'grand_total']
        const fieldKey = axis === 'column' ? 'columnFields' : 'rowFields'
        const currentFields = (block[fieldKey] || []) as ColumnFieldRef[]

        return (
          <div
            key={idx}
            className="border rounded p-2 space-y-2"
            data-testid={`${axis}-block-${idx}`}
          >
            {/* Row 1: Reorder + Mode + Measure/Indicator + Placement + Delete */}
            <div className="flex items-center gap-1 flex-wrap">
              {/* Move up/down */}
              <Button
                variant="ghost" size="icon" className="h-5 w-5"
                disabled={idx === 0}
                onClick={() => moveBlock(idx, -1)}
                data-testid={`${axis}-block-up-${idx}`}
                title="Move up"
              >
                <ArrowUp className="h-3 w-3" />
              </Button>
              <Button
                variant="ghost" size="icon" className="h-5 w-5"
                disabled={idx === safeBlocks.length - 1}
                onClick={() => moveBlock(idx, 1)}
                data-testid={`${axis}-block-down-${idx}`}
                title="Move down"
              >
                <ArrowDown className="h-3 w-3" />
              </Button>

              {/* Measure Mode selector */}
              <Select
                value={mode}
                onValueChange={(v) => {
                  const newMode = v as MeasureMode
                  const patch: Partial<MeasureBlockDef> = { measureMode: newMode }
                  if (newMode !== 'base_calc') patch.calcGroupItem = null
                  updateBlock(idx, patch)
                }}
              >
                <SelectTrigger
                  className="h-6 text-xs w-[80px]"
                  data-testid={`${axis}-block-measure-mode-${idx}`}
                  title="Measure mode"
                >
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {MEASURE_MODES.map(mm => (
                    <SelectItem key={mm.value} value={mm.value} className="text-xs" title={mm.title}>
                      {mm.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>

              {/* Measure dropdown (only in explicit mode) */}
              {mode === 'explicit' && (
                <Select
                  value={block.measureId || ''}
                  onValueChange={(v) => updateBlock(idx, { measureId: v })}
                >
                  <SelectTrigger
                    className="h-6 text-xs flex-1 min-w-[80px]"
                    data-testid={`${axis}-block-measure-${idx}`}
                  >
                    <SelectValue placeholder="Select measure..." />
                  </SelectTrigger>
                  <SelectContent>
                    {(availableMeasures ?? []).map(name => (
                      <SelectItem key={name} value={name} className="text-xs">
                        [{name}]
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              )}

              {/* Base mode indicator */}
              {(mode === 'base' || mode === 'base_calc') && (
                <span
                  className="text-[10px] text-muted-foreground italic bg-muted px-1.5 py-0.5 rounded"
                  data-testid={`${axis}-block-base-indicator-${idx}`}
                  title="Block uses all measures from the matrix Values field"
                >
                  (matrix values)
                </span>
              )}

              {/* Blank mode indicator */}
              {mode === 'blank' && (
                <span
                  className="text-[10px] text-muted-foreground italic bg-muted px-1.5 py-0.5 rounded"
                  data-testid={`${axis}-block-blank-indicator-${idx}`}
                  title="Block emits blank/empty cells"
                >
                  (empty)
                </span>
              )}

              {/* Placement */}
              <Select
                value={block.placement || placements[1].value}
                onValueChange={(v) => updateBlock(idx, { placement: v })}
              >
                <SelectTrigger
                  className="h-6 text-xs w-[62px]"
                  data-testid={`${axis}-block-placement-${idx}`}
                >
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {placements.map(p => (
                    <SelectItem key={p.value} value={p.value} className="text-xs">
                      {p.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>

              {/* Delete */}
              <Button
                variant="ghost" size="icon" className="h-5 w-5"
                onClick={() => removeBlock(idx)}
                data-testid={`${axis}-block-${idx}-delete`}
              >
                <Trash2 className="h-3 w-3 text-destructive" />
              </Button>
            </div>

            {/* Row 2: Calc Group Item picker (base_calc only) */}
            {mode === 'base_calc' && (
              <div className="flex items-center gap-1" data-testid={`${axis}-block-cg-item-${idx}`}>
                <span className="text-[10px] text-muted-foreground">CG Item:</span>
                <Select
                  value={block.calcGroupItem || ''}
                  onValueChange={(v) => updateBlock(idx, { calcGroupItem: v || null })}
                >
                  <SelectTrigger
                    className="h-6 text-xs flex-1"
                    data-testid={`${axis}-block-cg-item-select-${idx}`}
                  >
                    <SelectValue placeholder="-- Select CG Item --" />
                  </SelectTrigger>
                  <SelectContent>
                    {calcGroupItems.map(cgi => (
                      <SelectItem key={cgi.value} value={cgi.value} className="text-xs">
                        {cgi.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            )}

            {/* Row 3: Column/Row Fields (for grouped mini-matrix) */}
            <div className="flex items-center gap-1 flex-wrap">
              {currentFields.map((cf, cfIdx) => (
                <span
                  key={cfIdx}
                  className="inline-flex items-center gap-0.5 text-[10px] bg-blue-50 dark:bg-blue-900/30 px-1.5 py-0.5 rounded"
                  data-testid={`${axis}-block-field-chip-${idx}-${cfIdx}`}
                >
                  {cf.table}.{cf.column}
                  <button
                    className="text-muted-foreground hover:text-destructive"
                    onClick={() => removeColumnField(idx, cfIdx)}
                    title="Remove field"
                  >
                    <X className="h-2.5 w-2.5" />
                  </button>
                </span>
              ))}
              <Select
                onValueChange={(v) => {
                  const [table, column] = v.split('|')
                  if (table && column) addColumnField(idx, table, column)
                }}
              >
                <SelectTrigger
                  className="h-5 text-[10px] w-[70px]"
                  data-testid={`${axis}-block-add-field-${idx}`}
                >
                  <SelectValue placeholder={axis === 'column' ? '+Col' : '+Row'} />
                </SelectTrigger>
                <SelectContent>
                  {tables.map(t => (
                    t.columns.map(col => (
                      <SelectItem key={`${t.name}|${col}`} value={`${t.name}|${col}`} className="text-xs">
                        {t.name}.{col}
                      </SelectItem>
                    ))
                  )).flat()}
                </SelectContent>
              </Select>
            </div>

            {/* Row 4: AppliesTo + Label + Width/Height */}
            <div className="flex items-center gap-2 flex-wrap">
              {/* AppliesTo checkboxes */}
              <div className="flex items-center gap-1" data-testid={`${axis}-block-applies-to-${idx}`}>
                {ROW_TYPES.map(rt => {
                  const checked = currentAppliesTo.includes(rt.value)
                  return (
                    <label
                      key={rt.value}
                      className="flex items-center gap-0.5 text-[10px] cursor-pointer"
                      title={rt.title}
                    >
                      <input
                        type="checkbox"
                        className="h-3 w-3"
                        checked={checked}
                        onChange={() => {
                          const newAppliesTo = checked
                            ? currentAppliesTo.filter(v => v !== rt.value)
                            : [...currentAppliesTo, rt.value]
                          updateBlock(idx, { appliesTo: newAppliesTo.length > 0 ? newAppliesTo : ['leaf'] })
                        }}
                        data-testid={`${axis}-block-applies-${rt.value}-${idx}`}
                      />
                      {rt.label}
                    </label>
                  )
                })}
              </div>

              {/* Label */}
              <Input
                className="h-6 text-xs w-[70px]"
                value={block.label || ''}
                onChange={e => updateBlock(idx, { label: e.target.value || undefined })}
                placeholder="Label"
                data-testid={`${axis}-block-label-${idx}`}
              />

              {/* Width (CMB) or Height (RMB) */}
              <Input
                type="number"
                className="h-6 text-xs w-[55px]"
                value={block[axis === 'column' ? 'width' : 'height'] ?? ''}
                placeholder={axis === 'column' ? 'Width' : 'Height'}
                min={0}
                onChange={e => {
                  const val = parseInt(e.target.value, 10)
                  const key = axis === 'column' ? 'width' : 'height'
                  updateBlock(idx, { [key]: isNaN(val) ? null : val })
                }}
                data-testid={`${axis}-block-${axis === 'column' ? 'width' : 'height'}-${idx}`}
              />
            </div>

            {/* Row 5: Per-block subtotal toggle (only for grouped blocks) */}
            {currentFields.length > 0 && (
              <div className="space-y-1 pt-1 border-t border-muted/50">
                <div className="flex items-center justify-between">
                  <Label className="text-[10px] text-muted-foreground">Block subtotals</Label>
                  <Switch
                    checked={getBlockShowSubtotals(block)}
                    onCheckedChange={(checked: boolean) => updateBlock(idx, { showSubtotals: checked, show_subtotals: checked })}
                    className="scale-75"
                    data-testid={`${axis}-block-subtotals-${idx}`}
                  />
                </div>
                {getBlockShowSubtotals(block) && currentFields.length > 1 && (
                  <div className="space-y-0.5 pl-3 border-l border-muted">
                    {currentFields.slice(0, -1).map((cf, cfLvl) => {
                      const lvlEnabled = getBlockSubtotalLevels(block)?.[cfLvl] !== false
                      return (
                        <div key={cfLvl} className="flex items-center justify-between" data-testid={`${axis}-block-subtotal-level-${idx}-${cfLvl}`}>
                          <Label className="text-[10px] text-muted-foreground">{cf.column}</Label>
                          <Switch
                            checked={lvlEnabled}
                            onCheckedChange={(checked: boolean) => {
                              const levels = { ...(block.subtotalLevels || block.subtotal_levels || {}) }
                              levels[cfLvl] = checked
                              updateBlock(idx, { subtotalLevels: levels, subtotal_levels: levels })
                            }}
                            className="scale-75"
                          />
                        </div>
                      )
                    })}
                  </div>
                )}
              </div>
            )}
          </div>
        )
      })}

      <Button
        variant="outline"
        size="sm"
        className="w-full h-7 text-xs"
        onClick={addBlock}
        data-testid={`${axis}-block-add`}
      >
        <Plus className="h-3 w-3 mr-1" />
        Add {axis} block
      </Button>
    </div>
  )
}

// -- Header Band List sub-component --
interface HeaderBandListProps {
  bands: HeaderBandDef[]
  axis: 'col' | 'row'
  availableMeasures: string[]
  onUpdate: (bands: HeaderBandDef[]) => void
  availableBlocks: MeasureBlockDef[]  // CMBs for col axis, RMBs for row axis
}

const BAND_TYPES_COL: { value: HeaderBandType; label: string }[] = [
  { value: 'label', label: 'Label' },
  { value: 'col_attribute', label: 'Col Attribute' },
  { value: 'measure', label: 'Measure' },
]
const BAND_TYPES_ROW: { value: HeaderBandType; label: string }[] = [
  { value: 'label', label: 'Label' },
  { value: 'row_attribute', label: 'Row Attribute' },
  { value: 'measure', label: 'Measure' },
]
const ROW_SCOPE_OPTIONS = [
  { value: 'leaf', label: 'L', title: 'Leaf rows' },
  { value: 'subtotal', label: 'S', title: 'Subtotal rows' },
  { value: 'grand_total', label: 'G', title: 'Grand total row' },
]

function HeaderBandList({ bands, axis, availableMeasures, onUpdate, availableBlocks }: HeaderBandListProps) {
  const safeBands = Array.isArray(bands) ? bands : []
  const bandTypes = axis === 'col' ? BAND_TYPES_COL : BAND_TYPES_ROW

  const addBand = () => {
    const newBand: HeaderBandDef = {
      bandType: 'label',
      label: `Band ${safeBands.length + 1}`,
      ...(axis === 'row' ? { appliesTo: ['leaf', 'subtotal', 'grand_total'] } : {}),
    }
    onUpdate([...safeBands, newBand])
  }

  const removeBand = (idx: number) => {
    onUpdate(safeBands.filter((_, i) => i !== idx))
  }

  const updateBand = (idx: number, patch: Partial<HeaderBandDef>) => {
    onUpdate(safeBands.map((b, i) => i === idx ? { ...b, ...patch } : b))
  }

  const moveBand = (idx: number, direction: -1 | 1) => {
    const target = idx + direction
    if (target < 0 || target >= safeBands.length) return
    const updated = [...safeBands]
    ;[updated[idx], updated[target]] = [updated[target], updated[idx]]
    onUpdate(updated)
  }

  const hasSpans = (band: HeaderBandDef) =>
    band.spans && Array.isArray(band.spans) && band.spans.length > 0

  // Compute the span summary label for the dropdown button
  const getSpanLabel = (band: HeaderBandDef): string => {
    const selectedBlocks = band.spanBlocks || []
    const includesBase = selectedBlocks.length === 0 || selectedBlocks.includes('__base__')
    const blockLabels = selectedBlocks
      .filter(id => id !== '__base__')
      .map(id => {
        const blk = availableBlocks.find(b => (b.id || `blk-${availableBlocks.indexOf(b)}`) === id)
        return blk ? (blk.label || blk.measureId || id) : id
      })
    const parts = [...(includesBase ? ['Base'] : []), ...blockLabels]
    return parts.length > 0 ? parts.join(', ') : 'None'
  }

  return (
    <div className="space-y-3">
      {safeBands.map((band, idx) => (
        <div
          key={idx}
          className="border rounded p-2 space-y-2"
          data-testid={`${axis}-header-band-item-${idx}`}
        >
          {/* Row 1: type selector + label/controls + actions */}
          <div className="flex items-center gap-1">
            {hasSpans(band) ? (
              <>
                <Input
                  className="h-6 text-xs flex-1 min-w-0"
                  value={band.label || ''}
                  onChange={e => updateBand(idx, { label: e.target.value })}
                  placeholder="Label"
                  data-testid={`${axis}-header-band-label-${idx}`}
                />
                <span className="text-[10px] text-muted-foreground shrink-0" data-testid={`${axis}-header-band-spans-${idx}`}>
                  Spans: {band.spans!.map(s => s.replace(':', ' ')).join(', ')}
                </span>
              </>
            ) : (
              <>
                <Select
                  value={band.bandType || 'label'}
                  onValueChange={(v) => updateBand(idx, { bandType: v as HeaderBandType })}
                >
                  <SelectTrigger className="h-6 text-xs w-20 shrink-0" data-testid={`${axis}-header-band-type-${idx}`}>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {bandTypes.map(bt => (
                      <SelectItem key={bt.value} value={bt.value} className="text-xs">
                        {bt.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>

                {/* Type-specific input */}
                {(band.bandType === 'label' || !band.bandType) && (
                  <Input
                    className="h-6 text-xs flex-1 min-w-0"
                    value={band.label || ''}
                    onChange={e => updateBand(idx, { label: e.target.value })}
                    placeholder="Label"
                    data-testid={`${axis}-header-band-label-${idx}`}
                  />
                )}
                {band.bandType === (axis === 'col' ? 'col_attribute' : 'row_attribute') && (
                  <Input
                    type="number"
                    className="h-6 text-xs w-14"
                    value={band.pathLevel ?? 0}
                    min={-10}
                    max={10}
                    onChange={e => {
                      const lvl = parseInt(e.target.value, 10)
                      updateBand(idx, { pathLevel: isNaN(lvl) ? 0 : lvl })
                    }}
                    title={`${axis === 'col' ? 'Column' : 'Row'} path level (0=first, -1=last)`}
                    data-testid={`${axis}-header-band-level-${idx}`}
                  />
                )}
                {band.bandType === 'measure' && (
                  <Select
                    value={band.measureId || ''}
                    onValueChange={(v) => updateBand(idx, { measureId: v || null })}
                  >
                    <SelectTrigger className="h-6 text-xs flex-1 min-w-0" data-testid={`${axis}-header-band-measure-${idx}`}>
                      <SelectValue placeholder="--" />
                    </SelectTrigger>
                    <SelectContent>
                      {availableMeasures.map(m => (
                        <SelectItem key={m} value={m} className="text-xs">
                          [{m}]
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                )}
              </>
            )}

            {/* Action buttons */}
            <div className="flex items-center shrink-0">
              <Button variant="ghost" size="icon" className="h-5 w-5" disabled={idx === 0}
                onClick={() => moveBand(idx, -1)} data-testid={`${axis}-header-band-move-up-${idx}`} title="Move up">
                <ArrowUp className="h-3 w-3" />
              </Button>
              <Button variant="ghost" size="icon" className="h-5 w-5" disabled={idx === safeBands.length - 1}
                onClick={() => moveBand(idx, 1)} data-testid={`${axis}-header-band-move-down-${idx}`} title="Move down">
                <ArrowDown className="h-3 w-3" />
              </Button>
              <Button variant="ghost" size="icon" className="h-5 w-5"
                onClick={() => removeBand(idx)} data-testid={`${axis}-header-band-remove-${idx}`} title="Remove">
                <Trash2 className="h-3 w-3 text-destructive" />
              </Button>
            </div>
          </div>

          {/* Row 2: span scope dropdown + size + row-specific options */}
          {!hasSpans(band) && (
            <div className="flex items-center gap-2 flex-wrap text-[10px]">
              {/* Span scope dropdown (always visible, shows Base + blocks) */}
              {availableBlocks.length > 0 ? (
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <Button
                      variant="outline"
                      size="sm"
                      className="h-6 text-[10px] px-2"
                      data-testid={`${axis}-header-band-blockpicker-${idx}`}
                      title="Select which areas the header band spans across"
                    >
                      Span: {getSpanLabel(band)}
                      <ChevronDown className="h-3 w-3 ml-1" />
                    </Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="start" className="min-w-[140px]">
                    <DropdownMenuCheckboxItem
                      checked={(band.spanBlocks || []).includes('__base__') || !(band.spanBlocks && band.spanBlocks.length > 0)}
                      onCheckedChange={() => {
                        const cur = band.spanBlocks || []
                        const hasBase = cur.includes('__base__') || cur.length === 0
                        let newBlocks: string[]
                        if (hasBase) {
                          // Remove base — keep only block IDs
                          newBlocks = cur.filter(id => id !== '__base__')
                        } else {
                          // Add base
                          newBlocks = ['__base__', ...cur]
                        }
                        updateBand(idx, {
                          spanBlocks: newBlocks.length > 0 ? newBlocks : undefined,
                          spanScope: 'main',
                        })
                      }}
                      className="text-xs"
                    >
                      Base Matrix
                    </DropdownMenuCheckboxItem>
                    <DropdownMenuSeparator />
                    {availableBlocks.map((blk, bi) => {
                      const blockId = blk.id || `blk-${bi}`
                      const blockLabel = blk.label || blk.measureId || `Block #${bi}`
                      const selectedBlocks = band.spanBlocks || []
                      const isSelected = selectedBlocks.includes(blockId)
                      return (
                        <DropdownMenuCheckboxItem
                          key={blockId}
                          checked={isSelected}
                          onCheckedChange={() => {
                            let newBlocks: string[]
                            if (isSelected) {
                              newBlocks = selectedBlocks.filter(id => id !== blockId)
                            } else {
                              // If no spanBlocks yet, implicitly add __base__ too
                              const base = selectedBlocks.length === 0 ? ['__base__'] : []
                              newBlocks = [...base, ...selectedBlocks, blockId]
                            }
                            updateBand(idx, {
                              spanBlocks: newBlocks.length > 0 ? newBlocks : undefined,
                              spanScope: 'main',
                            })
                          }}
                          className="text-xs"
                          data-testid={`${axis}-header-band-block-${bi}-${idx}`}
                        >
                          {blockLabel}
                        </DropdownMenuCheckboxItem>
                      )
                    })}
                  </DropdownMenuContent>
                </DropdownMenu>
              ) : (
                <Select
                  value={band.spanScope || 'main'}
                  onValueChange={(v) => updateBand(idx, { spanScope: v as 'main' | 'all' })}
                >
                  <SelectTrigger
                    className="h-6 text-xs w-16"
                    data-testid={`${axis}-header-band-spanscope-${idx}`}
                    title={axis === 'col'
                      ? 'Span scope: Main = pivot columns only, All = span across CMBs too'
                      : 'Span scope: Main = pivot rows only, All = span across RMBs too'}
                  >
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="main" className="text-xs">Main</SelectItem>
                    <SelectItem value="all" className="text-xs">All</SelectItem>
                  </SelectContent>
                </Select>
              )}

              {/* Size input + Reset to Auto */}
              <div className="flex items-center gap-0.5">
                <Input
                  type="number"
                  className="h-6 text-xs w-12"
                  value={(axis === 'row' ? band.width : band.height) ?? ''}
                  placeholder="Auto"
                  min={0}
                  onChange={e => {
                    const v = parseInt(e.target.value, 10)
                    updateBand(idx, axis === 'row'
                      ? { width: isNaN(v) ? undefined : v }
                      : { height: isNaN(v) ? undefined : v }
                    )
                  }}
                  title={axis === 'row' ? 'Width (px), empty = auto' : 'Height (px), empty = auto'}
                  data-testid={`${axis}-header-band-${axis === 'row' ? 'width' : 'height'}-${idx}`}
                />
                {((axis === 'row' ? band.width : band.height) != null && (axis === 'row' ? band.width : band.height)! > 0) && (
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-5 w-5 text-muted-foreground"
                    onClick={() => updateBand(idx, axis === 'row' ? { width: undefined } : { height: undefined })}
                    title="Reset to auto size"
                    data-testid={`${axis}-header-band-reset-size-${idx}`}
                  >
                    <span className="text-[9px]">⟳</span>
                  </Button>
                )}
              </div>

              {/* Display level (position index) */}
              <Input
                type="number"
                className="h-6 text-xs w-10"
                value={band.displayLevel ?? idx}
                min={0}
                max={10}
                onChange={e => {
                  const v = parseInt(e.target.value, 10)
                  updateBand(idx, { displayLevel: isNaN(v) ? undefined : v })
                }}
                title={`Position level (0 = ${axis === 'row' ? 'leftmost' : 'topmost'}, same level = side by side)`}
                data-testid={`${axis}-header-band-level-${idx}`}
              />

              {/* Row-band specific: appliesTo + merge + rotate */}
              {axis === 'row' && (
                <>
                  {ROW_SCOPE_OPTIONS.map(rt => {
                    const appliesTo = Array.isArray(band.appliesTo)
                      ? band.appliesTo
                      : ['leaf', 'subtotal', 'grand_total']
                    const checked = appliesTo.includes(rt.value)
                    return (
                      <label key={rt.value} className="flex items-center gap-0.5 cursor-pointer" title={rt.title}>
                        <input type="checkbox" className="h-3 w-3" checked={checked}
                          onChange={() => {
                            const newAppliesTo = checked
                              ? appliesTo.filter(v => v !== rt.value)
                              : [...appliesTo, rt.value]
                            updateBand(idx, { appliesTo: newAppliesTo.length > 0 ? newAppliesTo : ['leaf'] })
                          }}
                          data-testid={`${axis}-header-band-applies-${rt.value}-${idx}`}
                        />
                        {rt.label}
                      </label>
                    )
                  })}
                  <label className="flex items-center gap-0.5 cursor-pointer" title="Merge cells in each section">
                    <input type="checkbox" className="h-3 w-3" checked={band.merge !== false}
                      onChange={() => updateBand(idx, { merge: band.merge === false })}
                      data-testid={`${axis}-header-band-merge-${idx}`}
                    />
                    Merge
                  </label>
                  <label className="flex items-center gap-0.5 cursor-pointer" title="Rotate text 90°">
                    <input type="checkbox" className="h-3 w-3" checked={band.rotate === true}
                      onChange={() => updateBand(idx, { rotate: !band.rotate })}
                      data-testid={`${axis}-header-band-rotate-${idx}`}
                    />
                    Rotate
                  </label>
                </>
              )}
            </div>
          )}
        </div>
      ))}
      <Button
        variant="outline"
        size="sm"
        className="w-full h-7 text-xs"
        onClick={addBand}
        data-testid={`${axis}-header-band-add`}
      >
        <Plus className="h-3 w-3 mr-1" />
        Add {axis} header band
      </Button>
    </div>
  )
}

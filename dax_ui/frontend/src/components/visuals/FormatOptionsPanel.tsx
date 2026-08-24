/**
 * FormatOptionsPanel - Advanced Visual Editor
 * Structured formatting controls for Plotly chart visuals.
 * Sections: Title, Legend, X Axis, Y Axis, Data Labels, Chart Style, Colors.
 * Each section is collapsible. Controls are conditional on visual type.
 */

import { useState, useCallback } from 'react'
import { ChevronDown, ChevronRight } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { Input } from '@/components/ui/input'
import { Switch } from '@/components/ui/switch'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { Separator } from '@/components/ui/separator'
import { type FormatOptions } from '@/lib/api'
import { EncodingsPanel, type FieldExpr, type SlotSpec } from './FieldWell'

export type { FormatOptions }

const CHART_TYPES = [
  'bar', 'column', 'line', 'area', 'pie', 'scatter', 'combo',
  'histogram', 'box', 'violin', 'strip', 'ecdf',
  'funnel', 'funnel_area',
  'density_contour', 'density_heatmap',
  'treemap', 'sunburst', 'icicle',
  'scatter_polar', 'line_polar', 'bar_polar',
  'scatter_3d', 'line_3d',
  'bubble', 'bubble_3d',
  'candlestick', 'ohlc', 'waterfall', 'gauge', 'sankey',
  'ibcs_bar', 'ibcs_column', 'ibcs_line', 'ibcs_card', 'ibcs_waterfall',
]
const BAR_TYPES = ['bar', 'column', 'histogram', 'funnel']
const IBCS_BAR_TYPES = ['ibcs_bar', 'ibcs_column']
const LINE_TYPES = ['line', 'area', 'ecdf']
const SCATTER_TYPES = ['scatter', 'scatter_3d', 'bubble', 'bubble_3d']
const PIE_TYPES = ['pie', 'funnel_area']
const STAT_TYPES = ['box', 'violin', 'strip']
const HIERARCHICAL_TYPES = ['treemap', 'sunburst', 'icicle']
const POLAR_TYPES = ['scatter_polar', 'line_polar', 'bar_polar']
const GRIDLINE_TYPES = ['bar', 'column', 'line', 'area', 'scatter', 'combo', 'histogram', 'box', 'violin', 'strip', 'ecdf', 'funnel', 'density_contour', 'density_heatmap', 'bubble', 'waterfall', 'candlestick', 'ohlc']
const IBCS_TYPES = ['ibcs_bar', 'ibcs_column', 'ibcs_line', 'ibcs_card', 'ibcs_waterfall', 'ibcs_table']
const TRENDLINE_TYPES = ['scatter', 'line', 'area', 'bar', 'column', 'bubble']
const MARGINAL_TYPES = ['scatter', 'histogram', 'bubble']
const PATTERN_TYPES = ['bar', 'column', 'histogram', 'pie', 'funnel']
const ERROR_BAR_TYPES = ['scatter', 'bar', 'column', 'line', 'bubble']
const FINANCIAL_TYPES = ['candlestick', 'ohlc']
const FLOW_TYPES = ['sankey', 'waterfall']

const COLOR_SEQUENCES = ['Plotly', 'D3', 'Pastel', 'Bold', 'Vivid', 'Safe']

const FONT_FAMILY_DEFAULT = '__default__'

const FONT_FAMILY_OPTIONS = [
  { value: FONT_FAMILY_DEFAULT, label: 'Default (system)' },
  { value: 'Arial, Helvetica, sans-serif', label: 'Arial' },
  { value: 'Helvetica, Arial, sans-serif', label: 'Helvetica' },
  { value: 'Verdana, Geneva, sans-serif', label: 'Verdana' },
  { value: 'Tahoma, Geneva, sans-serif', label: 'Tahoma' },
  { value: "'Segoe UI', Tahoma, sans-serif", label: 'Segoe UI' },
  { value: "'Trebuchet MS', sans-serif", label: 'Trebuchet MS' },
  { value: 'Georgia, serif', label: 'Georgia' },
  { value: "'Times New Roman', Times, serif", label: 'Times New Roman' },
  { value: "'Courier New', Courier, monospace", label: 'Courier New' },
  { value: "'Lucida Console', Monaco, monospace", label: 'Lucida Console' },
  { value: 'Calibri, sans-serif', label: 'Calibri' },
  { value: "'Century Gothic', sans-serif", label: 'Century Gothic' },
  { value: "'DIN Alternate', sans-serif", label: 'DIN' },
]

interface FormatOptionsPanelProps {
  options: FormatOptions
  visualType: string
  visualEncodings?: Record<string, unknown>
  onUpdate: (key: keyof FormatOptions, value: unknown) => void
}

/* ─── Collapsible Section wrapper ──────────────────────────── */
function Section({
  title,
  open,
  onOpenChange,
  testId,
  children,
}: {
  title: string
  open: boolean
  onOpenChange: (v: boolean) => void
  testId: string
  children: React.ReactNode
}) {
  return (
    <Collapsible open={open} onOpenChange={onOpenChange}>
      <CollapsibleTrigger asChild>
        <Button
          variant="ghost"
          className="w-full justify-between px-0 h-7 font-medium hover:bg-transparent"
          data-testid={testId}
        >
          <div className="flex items-center gap-2">
            {open ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
            <span className="text-xs">{title}</span>
          </div>
        </Button>
      </CollapsibleTrigger>
      <CollapsibleContent>
        <div className="space-y-3 py-2 pl-5">{children}</div>
      </CollapsibleContent>
    </Collapsible>
  )
}

/* ─── Reusable row helpers ─────────────────────────────────── */
function ToggleRow({
  id,
  label,
  checked,
  onChange,
  testId,
}: {
  id: string
  label: string
  checked: boolean
  onChange: (v: boolean) => void
  testId: string
}) {
  return (
    <div className="flex items-center justify-between">
      <Label htmlFor={id} className="text-xs">{label}</Label>
      <Switch id={id} checked={checked} onCheckedChange={onChange} data-testid={testId} />
    </div>
  )
}

function SelectRow({
  label,
  value,
  options,
  onChange,
  testId,
}: {
  label: string
  value: string
  options: { value: string; label: string }[]
  onChange: (v: string) => void
  testId: string
}) {
  return (
    <div className="space-y-1">
      <Label className="text-xs">{label}</Label>
      <Select value={value} onValueChange={onChange}>
        <SelectTrigger className="h-7 text-xs" data-testid={testId}>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {options.map((o) => (
            <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  )
}

function TextRow({
  label,
  value,
  onChange,
  testId,
  placeholder,
}: {
  label: string
  value: string
  onChange: (v: string) => void
  testId: string
  placeholder?: string
}) {
  return (
    <div className="space-y-1">
      <Label className="text-xs">{label}</Label>
      <Input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="h-7 text-xs"
        data-testid={testId}
      />
    </div>
  )
}

function SliderRow({
  label,
  value,
  min,
  max,
  step,
  onChange,
  testId,
}: {
  label: string
  value: number
  min: number
  max: number
  step?: number
  onChange: (v: number) => void
  testId: string
}) {
  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between">
        <Label className="text-xs">{label}</Label>
        <span className="text-xs text-muted-foreground tabular-nums" data-testid={`${testId}-value`}>
          {Number.isInteger(value) ? value : parseFloat(value.toFixed(2))}
        </span>
      </div>
      <Input
        type="range"
        value={value}
        min={min}
        max={max}
        step={step ?? 1}
        onChange={(e) => onChange(Number(e.target.value))}
        className="h-5 w-full cursor-pointer"
        data-testid={testId}
      />
    </div>
  )
}

function ColorRow({
  label,
  value,
  onChange,
  testId,
}: {
  label: string
  value: string
  onChange: (v: string) => void
  testId: string
}) {
  return (
    <div className="space-y-1">
      <Label className="text-xs">{label}</Label>
      <div className="flex items-center gap-2">
        <input
          type="color"
          value={value || '#000000'}
          onChange={(e) => onChange(e.target.value)}
          className="h-7 w-10 cursor-pointer rounded border border-input bg-transparent"
          data-testid={testId}
        />
        <Input
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder="#000000"
          className="h-7 text-xs flex-1"
          data-testid={`${testId}-text`}
        />
        {value && (
          <Button
            variant="ghost"
            size="sm"
            className="h-7 px-2 text-xs"
            onClick={() => onChange('')}
          >
            Clear
          </Button>
        )}
      </div>
    </div>
  )
}

function ImageUploadRow({
  label,
  value,
  onChange,
  testId,
}: {
  label: string
  value: string
  onChange: (v: string) => void
  testId: string
}) {
  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    if (!file.type.startsWith('image/')) return
    const reader = new FileReader()
    reader.onload = () => {
      if (typeof reader.result === 'string') {
        onChange(reader.result)
      }
    }
    reader.readAsDataURL(file)
  }

  return (
    <div className="space-y-1">
      <Label className="text-xs">{label}</Label>
      <div className="flex items-center gap-2">
        {value && (
          <div
            className="h-7 w-10 rounded border border-input bg-cover bg-center flex-shrink-0"
            style={{ backgroundImage: `url(${value})` }}
          />
        )}
        <div className="flex-1 flex items-center gap-1">
          <label className="cursor-pointer">
            <input
              type="file"
              accept="image/*"
              className="hidden"
              onChange={handleFileChange}
              data-testid={testId}
            />
            <span className="inline-flex items-center justify-center h-7 px-3 text-xs rounded border border-input bg-background hover:bg-accent cursor-pointer">
              {value ? 'Change' : 'Upload'}
            </span>
          </label>
          <Input
            value={value?.startsWith('data:') ? '(uploaded)' : value}
            onChange={(e) => onChange(e.target.value)}
            placeholder="URL or upload"
            className="h-7 text-xs flex-1"
            readOnly={value?.startsWith('data:')}
            data-testid={`${testId}-text`}
          />
          {value && (
            <Button
              variant="ghost"
              size="sm"
              className="h-7 px-2 text-xs"
              onClick={() => onChange('')}
            >
              Clear
            </Button>
          )}
        </div>
      </div>
    </div>
  )
}

/* ─── Main component ───────────────────────────────────────── */
export function FormatOptionsPanel({ options, visualType, visualEncodings, onUpdate }: FormatOptionsPanelProps) {
  const [titleOpen, setTitleOpen] = useState(true)
  const [legendOpen, setLegendOpen] = useState(false)
  const [xAxisOpen, setXAxisOpen] = useState(false)
  const [yAxisOpen, setYAxisOpen] = useState(false)
  const [dataLabelsOpen, setDataLabelsOpen] = useState(false)
  const [chartStyleOpen, setChartStyleOpen] = useState(false)
  const [colorsOpen, setColorsOpen] = useState(false)
  const [analyticsOpen, setAnalyticsOpen] = useState(false)
  const [ibcsOpen, setIbcsOpen] = useState(true)
  const [canvasOpen, setCanvasOpen] = useState(false)
  const [smallMultiplesOpen, setSmallMultiplesOpen] = useState(false)
  const [slicerOpen, setSlicerOpen] = useState(true)
  const [matrixOpen, setMatrixOpen] = useState(true)
  const [cardOpen, setCardOpen] = useState(true)
  const [shapeOpen, setShapeOpen] = useState(true)

  const isChart = CHART_TYPES.includes(visualType)
  const isBar = BAR_TYPES.includes(visualType)
  const isIbcsBar = IBCS_BAR_TYPES.includes(visualType)
  const isIbcsWaterfall = visualType === 'ibcs_waterfall'
  const isIbcsCard = visualType === 'ibcs_card'
  const isIbcs = IBCS_TYPES.includes(visualType)
  const isLine = LINE_TYPES.includes(visualType)
  const isScatter = SCATTER_TYPES.includes(visualType)
  const isPie = PIE_TYPES.includes(visualType)
  const isStat = STAT_TYPES.includes(visualType)
  const isHierarchical = HIERARCHICAL_TYPES.includes(visualType)
  const isPolar = POLAR_TYPES.includes(visualType)
  const isFinancial = FINANCIAL_TYPES.includes(visualType)
  const isFlow = FLOW_TYPES.includes(visualType)
  const isGauge = visualType === 'gauge'
  const isSankey = visualType === 'sankey'
  const isWaterfall = visualType === 'waterfall'
  const isHistogram = visualType === 'histogram'
  const isSlicer = visualType === 'slicer'
  const isMatrix = visualType === 'matrix'
  const isCardType = visualType === 'card'
  const isTable = visualType === 'table'
  const isShape = visualType === 'shape'
  const isNonChart = isSlicer || isMatrix || isCardType || isTable || isShape
  const isBox = visualType === 'box'
  const isViolin = visualType === 'violin'
  const isStrip = visualType === 'strip'
  const hasGridlines = GRIDLINE_TYPES.includes(visualType)
  const hasTrendline = TRENDLINE_TYPES.includes(visualType)
  const hasMarginals = MARGINAL_TYPES.includes(visualType)
  const hasPattern = PATTERN_TYPES.includes(visualType)
  const hasErrorBars = ERROR_BAR_TYPES.includes(visualType)
  const hasWebGL = ['scatter', 'line', 'scatter_3d'].includes(visualType)
  const hasContinuousColor = ['density_heatmap', 'density_contour', 'scatter', 'scatter_3d', 'bubble', 'bubble_3d'].includes(visualType)
  const hasAnalytics = hasTrendline || hasMarginals || hasErrorBars
  const hasChartStyle = isChart && !isIbcs
  const ibcsIsHorizontal = isIbcsBar && (options.ibcsOrientation || (visualType === 'ibcs_column' ? 'vertical' : 'horizontal')) === 'horizontal'
  const rawCardGraphicSourceType = (options.ibcsCardGraphicSourceType || 'custom')
  const cardGraphicSourceType = rawCardGraphicSourceType === 'generated' ? 'generated' : 'custom'
  const cardGraphicGeneratedType = (options.ibcsCardGraphicGeneratedType || 'ibcs_bar')
  const cardGraphicEditorOpen = options.ibcsCardGraphicEditorOpen === true
  const cardGraphicEditorIsBar = cardGraphicGeneratedType === 'ibcs_bar'
  const cardGraphicEditorIsWaterfall = cardGraphicGeneratedType === 'ibcs_waterfall'
  const cardGraphicBarIsHorizontal = (options.ibcsCardGraphicGeneratedOrientation || 'horizontal') === 'horizontal'

  const cardGraphicEncodingSlots: Record<string, SlotSpec> = {
    category: { kind: 'dimension', required: false, multi: false },
    ac: { kind: 'measure', required: false, multi: false },
    py: { kind: 'measure', required: false, multi: false },
    pl: { kind: 'measure', required: false, multi: false },
    fc: { kind: 'measure', required: false, multi: false },
  }
  const cardGraphicEncodings: Record<string, FieldExpr | FieldExpr[] | null> = {
    category: (options.ibcsCardGraphicEncodingCategory as FieldExpr | null | undefined)
      || (visualEncodings?.category as FieldExpr | undefined)
      || null,
    ac: (options.ibcsCardGraphicEncodingAC as FieldExpr | null | undefined)
      || (visualEncodings?.ac as FieldExpr | undefined)
      || null,
    py: (options.ibcsCardGraphicEncodingPY as FieldExpr | null | undefined)
      || (visualEncodings?.py as FieldExpr | undefined)
      || null,
    pl: (options.ibcsCardGraphicEncodingPL as FieldExpr | null | undefined)
      || (visualEncodings?.pl as FieldExpr | undefined)
      || null,
    fc: (options.ibcsCardGraphicEncodingFC as FieldExpr | null | undefined)
      || (visualEncodings?.fc as FieldExpr | undefined)
      || null,
  }
  const handleCardGraphicEncodingUpdate = useCallback((slotName: string, value: FieldExpr | FieldExpr[] | null) => {
    const keyMap: Record<string, keyof FormatOptions> = {
      category: 'ibcsCardGraphicEncodingCategory',
      ac: 'ibcsCardGraphicEncodingAC',
      py: 'ibcsCardGraphicEncodingPY',
      pl: 'ibcsCardGraphicEncodingPL',
      fc: 'ibcsCardGraphicEncodingFC',
    }
    const targetKey = keyMap[slotName]
    if (!targetKey) return
    onUpdate(targetKey, value)
  }, [onUpdate])

  if (!isChart && !isNonChart) return null

  return (
    <div className="space-y-1" data-testid="format-options-panel">
      {/* ─── Slicer Format ──────────────────────────────── */}
      {isSlicer && (
        <>
          <Section title="Slicer Layout" open={slicerOpen} onOpenChange={setSlicerOpen} testId="format-slicer-toggle">
            <SelectRow
              label="Style"
              value={(options as Record<string, unknown>).slicerStyle as string || 'Cards'}
              options={[
                { value: 'Cards', label: 'Cards' },
                { value: 'Flow', label: 'Flow' },
              ]}
              onChange={(v) => onUpdate('slicerStyle' as keyof FormatOptions, v)}
              testId="format-slicer-style"
            />
            <SliderRow
              label="Row count"
              value={(options as Record<string, unknown>).slicerRowCount as number ?? 1}
              min={1}
              max={10}
              onChange={(v) => onUpdate('slicerRowCount' as keyof FormatOptions, v)}
              testId="format-slicer-row-count"
            />
            <SliderRow
              label="Column count"
              value={(options as Record<string, unknown>).slicerColumnCount as number ?? 1}
              min={1}
              max={10}
              onChange={(v) => onUpdate('slicerColumnCount' as keyof FormatOptions, v)}
              testId="format-slicer-column-count"
            />
            <SelectRow
              label="Tile shape"
              value={(options as Record<string, unknown>).slicerTileShape as string || 'rectangleRoundedByPixel'}
              options={[
                { value: 'rectangleRoundedByPixel', label: 'Rounded Rectangle' },
                { value: 'rectangle', label: 'Rectangle' },
                { value: 'oval', label: 'Oval' },
              ]}
              onChange={(v) => onUpdate('slicerTileShape' as keyof FormatOptions, v)}
              testId="format-slicer-tile-shape"
            />
            <SliderRow
              label="Corner radius"
              value={(options as Record<string, unknown>).slicerRoundedCurve as number ?? 15}
              min={0}
              max={50}
              onChange={(v) => onUpdate('slicerRoundedCurve' as keyof FormatOptions, v)}
              testId="format-slicer-rounded-curve"
            />
          </Section>
          <Separator />
          <Section title="Value Text" open={false} onOpenChange={() => {}} testId="format-slicer-value-toggle">
            <SelectRow
              label="Alignment"
              value={(options as Record<string, unknown>).slicerValueAlignment as string || 'center'}
              options={[
                { value: 'left', label: 'Left' },
                { value: 'center', label: 'Center' },
                { value: 'right', label: 'Right' },
              ]}
              onChange={(v) => onUpdate('slicerValueAlignment' as keyof FormatOptions, v)}
              testId="format-slicer-value-alignment"
            />
            <SliderRow
              label="Font size"
              value={(options as Record<string, unknown>).slicerValueFontSize as number ?? 9}
              min={6}
              max={36}
              onChange={(v) => onUpdate('slicerValueFontSize' as keyof FormatOptions, v)}
              testId="format-slicer-value-font-size"
            />
          </Section>
          <Separator />
          <Section title="Overflow" open={false} onOpenChange={() => {}} testId="format-slicer-overflow-toggle">
            <SelectRow
              label="Overflow style"
              value={String((options as Record<string, unknown>).slicerOverflowStyle ?? 0)}
              options={[
                { value: '0', label: 'None' },
                { value: '1', label: 'Wrap' },
              ]}
              onChange={(v) => onUpdate('slicerOverflowStyle' as keyof FormatOptions, Number(v))}
              testId="format-slicer-overflow-style"
            />
            <SelectRow
              label="Overflow direction"
              value={String((options as Record<string, unknown>).slicerOverflowDirection ?? 0)}
              options={[
                { value: '0', label: 'Horizontal' },
                { value: '1', label: 'Vertical' },
              ]}
              onChange={(v) => onUpdate('slicerOverflowDirection' as keyof FormatOptions, Number(v))}
              testId="format-slicer-overflow-direction"
            />
          </Section>
          <Separator />
          <Section title="Padding" open={false} onOpenChange={() => {}} testId="format-slicer-padding-toggle">
            <SelectRow
              label="Padding"
              value={(options as Record<string, unknown>).slicerPaddingSelection as string || 'Narrow'}
              options={[
                { value: 'None', label: 'None' },
                { value: 'Narrow', label: 'Narrow' },
                { value: 'Medium', label: 'Medium' },
                { value: 'Wide', label: 'Wide' },
              ]}
              onChange={(v) => onUpdate('slicerPaddingSelection' as keyof FormatOptions, v)}
              testId="format-slicer-padding-selection"
            />
            <ToggleRow
              id="slicer-fill-custom"
              label="Custom fill"
              checked={(options as Record<string, unknown>).slicerFillCustomShow === true}
              onChange={(v) => onUpdate('slicerFillCustomShow' as keyof FormatOptions, v)}
              testId="format-slicer-fill-custom"
            />
            <SliderRow
              label="Padding top"
              value={(options as Record<string, unknown>).slicerPaddingTop as number ?? 0}
              min={0}
              max={50}
              onChange={(v) => onUpdate('slicerPaddingTop' as keyof FormatOptions, v)}
              testId="format-slicer-padding-top"
            />
            <SliderRow
              label="Padding bottom"
              value={(options as Record<string, unknown>).slicerPaddingBottom as number ?? 0}
              min={0}
              max={50}
              onChange={(v) => onUpdate('slicerPaddingBottom' as keyof FormatOptions, v)}
              testId="format-slicer-padding-bottom"
            />
            <ToggleRow
              id="slicer-customize-padding"
              label="Customize padding"
              checked={(options as Record<string, unknown>).slicerCustomizePadding === true}
              onChange={(v) => onUpdate('slicerCustomizePadding' as keyof FormatOptions, v)}
              testId="format-slicer-customize-padding"
            />
          </Section>
          <Separator />
          <Section title="Image" open={false} onOpenChange={() => {}} testId="format-slicer-image-toggle">
            <SelectRow
              label="Image fit"
              value={(options as Record<string, unknown>).slicerImageFit as string || 'Normal'}
              options={[
                { value: 'Normal', label: 'Normal' },
                { value: 'Fit', label: 'Fit' },
                { value: 'Fill', label: 'Fill' },
              ]}
              onChange={(v) => onUpdate('slicerImageFit' as keyof FormatOptions, v)}
              testId="format-slicer-image-fit"
            />
            <SelectRow
              label="Position"
              value={(options as Record<string, unknown>).slicerImagePosition as string || 'Behind'}
              options={[
                { value: 'Behind', label: 'Behind' },
                { value: 'Front', label: 'Front' },
              ]}
              onChange={(v) => onUpdate('slicerImagePosition' as keyof FormatOptions, v)}
              testId="format-slicer-image-position"
            />
            <SliderRow
              label="Padding"
              value={(options as Record<string, unknown>).slicerImagePadding as number ?? 0}
              min={0}
              max={50}
              onChange={(v) => onUpdate('slicerImagePadding' as keyof FormatOptions, v)}
              testId="format-slicer-image-padding"
            />
            <SliderRow
              label="Saturation"
              value={(options as Record<string, unknown>).slicerImageSaturation as number ?? 100}
              min={0}
              max={100}
              onChange={(v) => onUpdate('slicerImageSaturation' as keyof FormatOptions, v)}
              testId="format-slicer-image-saturation"
            />
            <ToggleRow
              id="slicer-image-bg"
              label="Set as background"
              checked={(options as Record<string, unknown>).slicerImageAsBackground === true}
              onChange={(v) => onUpdate('slicerImageAsBackground' as keyof FormatOptions, v)}
              testId="format-slicer-image-as-background"
            />
            <ToggleRow
              id="slicer-image-ignore-pad"
              label="Ignore padding"
              checked={(options as Record<string, unknown>).slicerImageIgnorePadding === true}
              onChange={(v) => onUpdate('slicerImageIgnorePadding' as keyof FormatOptions, v)}
              testId="format-slicer-image-ignore-padding"
            />
          </Section>
          <Separator />
          <Section title="Advanced" open={false} onOpenChange={() => {}} testId="format-slicer-advanced-toggle">
            <SelectRow
              label="Orientation"
              value={String((options as Record<string, unknown>).slicerOrientation ?? 0)}
              options={[
                { value: '0', label: 'Vertical' },
                { value: '1', label: 'Horizontal' },
              ]}
              onChange={(v) => onUpdate('slicerOrientation' as keyof FormatOptions, Number(v))}
              testId="format-slicer-orientation"
            />
            <ToggleRow
              id="slicer-rounded-curve-custom"
              label="Custom corner radius"
              checked={(options as Record<string, unknown>).slicerRoundedCurveCustom === true}
              onChange={(v) => onUpdate('slicerRoundedCurveCustom' as keyof FormatOptions, v)}
              testId="format-slicer-rounded-curve-custom"
            />
          </Section>
          <Separator />
        </>
      )}

      {/* ─── Matrix Format ──────────────────────────────── */}
      {isMatrix && (
        <>
          <Section title="Matrix Layout" open={matrixOpen} onOpenChange={setMatrixOpen} testId="format-matrix-toggle">
            <SelectRow
              label="Layout"
              value={(options as Record<string, unknown>).matrixLayout as string || 'Tabular'}
              options={[
                { value: 'Tabular', label: 'Tabular' },
                { value: 'Compact', label: 'Compact' },
                { value: 'Outline', label: 'Outline' },
              ]}
              onChange={(v) => onUpdate('matrixLayout' as keyof FormatOptions, v)}
              testId="format-matrix-layout"
            />
            <SliderRow
              label="Stepped indentation"
              value={(options as Record<string, unknown>).matrixSteppedIndentation as number ?? 10}
              min={0}
              max={40}
              onChange={(v) => onUpdate('matrixSteppedIndentation' as keyof FormatOptions, v)}
              testId="format-matrix-stepped-indentation"
            />
            <ToggleRow
              id="matrix-grid-h"
              label="Horizontal gridlines"
              checked={(options as Record<string, unknown>).matrixGridHorizontal !== false}
              onChange={(v) => onUpdate('matrixGridHorizontal' as keyof FormatOptions, v)}
              testId="format-matrix-grid-horizontal"
            />
            <ToggleRow
              id="matrix-auto-size"
              label="Auto-size columns"
              checked={(options as Record<string, unknown>).matrixAutoSizeColumns !== false}
              onChange={(v) => onUpdate('matrixAutoSizeColumns' as keyof FormatOptions, v)}
              testId="format-matrix-auto-size-columns"
            />
          </Section>
          <Separator />
          <Section title="Column Headers" open={false} onOpenChange={() => {}} testId="format-matrix-headers-toggle">
            <ColorRow
              label="Background color"
              value={(options as Record<string, unknown>).matrixColumnHeaderBg as string || ''}
              onChange={(v) => onUpdate('matrixColumnHeaderBg' as keyof FormatOptions, v)}
              testId="format-matrix-header-bg"
            />
            <ToggleRow
              id="matrix-header-wrap"
              label="Word wrap"
              checked={(options as Record<string, unknown>).matrixColumnHeaderWordWrap !== false}
              onChange={(v) => onUpdate('matrixColumnHeaderWordWrap' as keyof FormatOptions, v)}
              testId="format-matrix-header-word-wrap"
            />
            <SelectRow
              label="Outline"
              value={String((options as Record<string, unknown>).matrixColumnHeaderOutline ?? 1)}
              options={[
                { value: '0', label: 'None' },
                { value: '1', label: 'Bottom only' },
                { value: '2', label: 'All' },
              ]}
              onChange={(v) => onUpdate('matrixColumnHeaderOutline' as keyof FormatOptions, Number(v))}
              testId="format-matrix-header-outline"
            />
          </Section>
          <Separator />
        </>
      )}

      {/* ─── Card Format ────────────────────────────────── */}
      {isCardType && (
        <>
          <Section title="Card Values" open={cardOpen} onOpenChange={setCardOpen} testId="format-card-toggle">
            <SliderRow
              label="Value font size"
              value={(options as Record<string, unknown>).cardValueFontSize as number ?? 14}
              min={8}
              max={72}
              onChange={(v) => onUpdate('cardValueFontSize' as keyof FormatOptions, v)}
              testId="format-card-value-font-size"
            />
            <ToggleRow
              id="card-category-show"
              label="Show category labels"
              checked={(options as Record<string, unknown>).cardCategoryLabelsShow !== false}
              onChange={(v) => onUpdate('cardCategoryLabelsShow' as keyof FormatOptions, v)}
              testId="format-card-category-show"
            />
            <SliderRow
              label="Category font size"
              value={(options as Record<string, unknown>).cardCategoryFontSize as number ?? 12}
              min={6}
              max={36}
              onChange={(v) => onUpdate('cardCategoryFontSize' as keyof FormatOptions, v)}
              testId="format-card-category-font-size"
            />
            <ColorRow
              label="Category color"
              value={(options as Record<string, unknown>).cardCategoryColor as string || ''}
              onChange={(v) => onUpdate('cardCategoryColor' as keyof FormatOptions, v)}
              testId="format-card-category-color"
            />
          </Section>
          <Separator />
          <Section title="Card Accent Bar" open={false} onOpenChange={() => {}} testId="format-card-bar-toggle">
            <ColorRow
              label="Bar color"
              value={(options as Record<string, unknown>).cardBarColor as string || ''}
              onChange={(v) => onUpdate('cardBarColor' as keyof FormatOptions, v)}
              testId="format-card-bar-color"
            />
            <SliderRow
              label="Bar weight"
              value={(options as Record<string, unknown>).cardBarWeight as number ?? 3}
              min={0}
              max={10}
              onChange={(v) => onUpdate('cardBarWeight' as keyof FormatOptions, v)}
              testId="format-card-bar-weight"
            />
          </Section>
          <Separator />
        </>
      )}

      {/* ─── Shape Outline ──────────────────────────────── */}
      {isShape && (
        <>
          <Section title="Shape Outline" open={shapeOpen} onOpenChange={setShapeOpen} testId="format-shape-toggle">
            <ToggleRow
              id="shape-outline-show"
              label="Show outline"
              checked={(options as Record<string, unknown>).shape_outline_show !== false}
              onChange={(v) => onUpdate('shape_outline_show' as keyof FormatOptions, v)}
              testId="format-shape-outline-show"
            />
            <ColorRow
              label="Outline color"
              value={(options as Record<string, unknown>).shape_outline_color as string || ''}
              onChange={(v) => onUpdate('shape_outline_color' as keyof FormatOptions, v)}
              testId="format-shape-outline-color"
            />
            <SliderRow
              label="Outline weight"
              value={(options as Record<string, unknown>).shape_outline_weight as number ?? 1}
              min={0}
              max={10}
              onChange={(v) => onUpdate('shape_outline_weight' as keyof FormatOptions, v)}
              testId="format-shape-outline-weight"
            />
          </Section>
          <Separator />
        </>
      )}
      {/* ─── IBCS Chart Style ─────────────────────────────── */}
      {isIbcs && (
        <>
          <Section title="Chart Style" open={ibcsOpen} onOpenChange={setIbcsOpen} testId="format-ibcs-toggle">
            {isIbcsBar && (
              <SelectRow
                label="Orientation"
                value={options.ibcsOrientation || (visualType === 'ibcs_column' ? 'vertical' : 'horizontal')}
                options={[
                  { value: 'vertical', label: 'Column (Vertical)' },
                  { value: 'horizontal', label: 'Bar (Horizontal)' },
                ]}
                onChange={(v) => onUpdate('ibcsOrientation' as keyof FormatOptions, v)}
                testId="format-ibcs-orientation"
              />
            )}
            {isIbcsBar && (
              <SelectRow
                label="Main chart mode"
                value={options.ibcsMainChartMode || 'comparison'}
                options={[
                  { value: 'comparison', label: 'Comparison bars' },
                  { value: 'waterfall', label: 'Waterfall bridge' },
                ]}
                onChange={(v) => onUpdate('ibcsMainChartMode' as keyof FormatOptions, v)}
                testId="format-ibcs-main-mode"
              />
            )}
            {isIbcsBar && (
              <SelectRow
                label="Data label position"
                value={options.ibcsLabelPosition || 'top-inside'}
                options={[
                  { value: 'top-inside', label: 'Top of bar (inside)' },
                  { value: 'top-outside', label: 'Top of bar (outside)' },
                  { value: 'middle', label: 'Middle of bar' },
                  { value: 'bottom', label: 'Bottom of bar' },
                ]}
                onChange={(v) => onUpdate('ibcsLabelPosition' as keyof FormatOptions, v)}
                testId="format-ibcs-label-position"
              />
            )}
            <SliderRow
              label="Font size"
              value={options.ibcsFontSize ?? 16}
              min={6}
              max={50}
              onChange={(v) => onUpdate('ibcsFontSize' as keyof FormatOptions, v)}
              testId="format-ibcs-font-size"
            />
            <SliderRow
              label="Data label font size"
              value={options.ibcsDataLabelFontSize ?? 16}
              min={6}
              max={50}
              onChange={(v) => onUpdate('ibcsDataLabelFontSize' as keyof FormatOptions, v)}
              testId="format-ibcs-data-label-font-size"
            />
            <SelectRow
              label="Font family"
              value={options.ibcsFontFamily || FONT_FAMILY_DEFAULT}
              options={FONT_FAMILY_OPTIONS}
              onChange={(v) => onUpdate('ibcsFontFamily' as keyof FormatOptions, v === FONT_FAMILY_DEFAULT ? '' : v)}
              testId="format-ibcs-font-family"
            />
            {isIbcsBar && (
              <SliderRow
                label={ibcsIsHorizontal ? 'Y axis label rotation' : 'X axis label rotation'}
                value={options.ibcsXAxisRotation ?? 0}
                min={-90}
                max={90}
                step={5}
                onChange={(v) => onUpdate('ibcsXAxisRotation' as keyof FormatOptions, v)}
                testId="format-ibcs-xaxis-rotation"
              />
            )}
            {isIbcsBar && (
              <ToggleRow
                id="ibcs-show-variance-panels"
                label="Show variance panels"
                checked={options.ibcsShowVariancePanels !== false}
                onChange={(v) => onUpdate('ibcsShowVariancePanels' as keyof FormatOptions, v)}
                testId="format-ibcs-show-variance-panels"
              />
            )}
            {isIbcsWaterfall && (
              <SelectRow
                label="Value scenario"
                value={options.ibcsWaterfallScenario || 'ac'}
                options={[
                  { value: 'ac', label: 'Actual (AC)' },
                  { value: 'py', label: 'Previous Year (PY)' },
                  { value: 'pl', label: 'Plan/Budget (PL)' },
                  { value: 'fc', label: 'Forecast (FC)' },
                ]}
                onChange={(v) => onUpdate('ibcsWaterfallScenario' as keyof FormatOptions, v)}
                testId="format-ibcs-waterfall-scenario"
              />
            )}
            {isIbcsWaterfall && (
              <ToggleRow
                id="ibcs-waterfall-show-totals"
                label="Show totals"
                checked={options.ibcsWaterfallShowTotals !== false}
                onChange={(v) => onUpdate('ibcsWaterfallShowTotals' as keyof FormatOptions, v)}
                testId="format-ibcs-waterfall-show-totals"
              />
            )}
            {isIbcsWaterfall && (
              <ToggleRow
                id="ibcs-waterfall-show-connectors"
                label="Show connector lines"
                checked={options.ibcsWaterfallShowConnectors !== false}
                onChange={(v) => onUpdate('ibcsWaterfallShowConnectors' as keyof FormatOptions, v)}
                testId="format-ibcs-waterfall-show-connectors"
              />
            )}
            {isIbcsWaterfall && (
              <ToggleRow
                id="ibcs-waterfall-allow-subtotal-toggle"
                label="Shift-click toggles subtotal"
                checked={options.ibcsWaterfallAllowSubtotalToggle === true}
                onChange={(v) => onUpdate('ibcsWaterfallAllowSubtotalToggle' as keyof FormatOptions, v)}
                testId="format-ibcs-waterfall-allow-subtotal-toggle"
              />
            )}
            {isIbcsWaterfall && (
              <TextRow
                label="Subtotal labels (comma-separated)"
                value={options.ibcsWaterfallSubtotalLabels || ''}
                onChange={(v) => onUpdate('ibcsWaterfallSubtotalLabels' as keyof FormatOptions, v)}
                testId="format-ibcs-waterfall-subtotal-labels"
                placeholder="e.g. Gross Profit, EBITDA"
              />
            )}
            {isIbcsCard && (
              <ToggleRow
                id="ibcs-card-show-graphic"
                label="Show SVG graphic"
                checked={options.ibcsCardShowGraphic === true}
                onChange={(v) => onUpdate('ibcsCardShowGraphic' as keyof FormatOptions, v)}
                testId="format-ibcs-card-show-graphic"
              />
            )}
            {isIbcsCard && options.ibcsCardShowGraphic === true && (
              <SelectRow
                label="Graphic source"
                value={cardGraphicSourceType}
                options={[
                  { value: 'custom', label: 'Custom SVG (URL/inline)' },
                  { value: 'generated', label: 'Generated IBCS visual (prefilled)' },
                ]}
                onChange={(v) => onUpdate('ibcsCardGraphicSourceType' as keyof FormatOptions, v)}
                testId="format-ibcs-card-graphic-source"
              />
            )}
            {isIbcsCard && options.ibcsCardShowGraphic === true && (
              <SelectRow
                label="Graphic position"
                value={options.ibcsCardGraphicPosition || 'bottom'}
                options={[
                  { value: 'top', label: 'Top' },
                  { value: 'left', label: 'Left' },
                  { value: 'bottom', label: 'Bottom' },
                  { value: 'right', label: 'Right' },
                ]}
                onChange={(v) => onUpdate('ibcsCardGraphicPosition' as keyof FormatOptions, v)}
                testId="format-ibcs-card-graphic-position"
              />
            )}
            {isIbcsCard && (
              <SelectRow
                label="DI overlay position"
                value={options.ibcsCardDiPosition || 'bottom'}
                options={[
                  { value: 'top', label: 'Top' },
                  { value: 'left', label: 'Left' },
                  { value: 'bottom', label: 'Bottom' },
                  { value: 'right', label: 'Right' },
                ]}
                onChange={(v) => onUpdate('ibcsCardDiPosition' as keyof FormatOptions, v)}
                testId="format-ibcs-card-di-position"
              />
            )}
            {isIbcsCard && (
              <ToggleRow
                id="ibcs-card-show-edu-summary"
                label="Show EDU summary"
                checked={options.ibcsCardShowEduSummary !== false}
                onChange={(v) => onUpdate('ibcsCardShowEduSummary' as keyof FormatOptions, v)}
                testId="format-ibcs-card-show-edu-summary"
              />
            )}
            {isIbcsCard && options.ibcsCardShowEduSummary !== false && (
              <SelectRow
                label="EDU summary position"
                value={options.ibcsCardEduPosition || 'inline'}
                options={[
                  { value: 'inline', label: 'Inline (below KPI)' },
                  { value: 'top', label: 'Top' },
                  { value: 'left', label: 'Left' },
                  { value: 'bottom', label: 'Bottom' },
                  { value: 'right', label: 'Right' },
                ]}
                onChange={(v) => onUpdate('ibcsCardEduPosition' as keyof FormatOptions, v)}
                testId="format-ibcs-card-edu-position"
              />
            )}
            {isIbcsCard && (
              <ToggleRow
                id="ibcs-card-show-signals"
                label="Show signal chips"
                checked={options.ibcsCardShowSignals !== false}
                onChange={(v) => onUpdate('ibcsCardShowSignals' as keyof FormatOptions, v)}
                testId="format-ibcs-card-show-signals"
              />
            )}
            {isIbcsCard && options.ibcsCardShowGraphic === true && cardGraphicSourceType === 'custom' && (
              <TextRow
                label="Graphic SVG (URL or inline <svg>)"
                value={options.ibcsCardGraphicSvg || ''}
                onChange={(v) => onUpdate('ibcsCardGraphicSvg' as keyof FormatOptions, v)}
                testId="format-ibcs-card-graphic-svg"
                placeholder="/assets/ibcs/signal.svg or <svg ...>...</svg>"
              />
            )}
            {isIbcsCard && options.ibcsCardShowGraphic === true && cardGraphicSourceType === 'generated' && (
              <>
                <SelectRow
                  label="Graphic visual type"
                  value={options.ibcsCardGraphicGeneratedType || 'ibcs_bar'}
                  options={[
                    { value: 'ibcs_bar', label: 'IBCS Bar' },
                    { value: 'ibcs_line', label: 'IBCS Line' },
                    { value: 'ibcs_waterfall', label: 'IBCS Waterfall' },
                  ]}
                  onChange={(v) => onUpdate('ibcsCardGraphicGeneratedType' as keyof FormatOptions, v)}
                  testId="format-ibcs-card-graphic-generated-type"
                />
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  className="h-7 text-xs"
                  onClick={() => onUpdate('ibcsCardGraphicEditorOpen' as keyof FormatOptions, !cardGraphicEditorOpen)}
                  data-testid="format-ibcs-card-graphic-open-editor"
                >
                  {cardGraphicEditorOpen ? 'Close IBCS visual editor' : 'Open IBCS visual editor'}
                </Button>
                <div className="text-[11px] text-muted-foreground" data-testid="format-ibcs-card-graphic-editor-hint">
                  Tip: click the embedded graphic inside the card to open the IBCS visual editor.
                </div>
                {cardGraphicEditorOpen && (
                  <div className="space-y-3 rounded-md border border-border bg-muted/20 p-2" data-testid="format-ibcs-card-graphic-editor-panel">
                    <div className="text-[11px] font-semibold text-foreground" data-testid="format-ibcs-card-graphic-editor-title">
                      Embedded IBCS Visual Editor
                    </div>
                    <div className="space-y-2" data-testid="format-ibcs-card-graphic-encodings">
                      <div className="text-[11px] font-semibold text-foreground">Encodings</div>
                      <EncodingsPanel
                        slots={cardGraphicEncodingSlots}
                        encodings={cardGraphicEncodings}
                        onUpdateEncoding={handleCardGraphicEncodingUpdate}
                      />
                    </div>
                    <Separator />
                    {cardGraphicEditorIsBar && (
                      <SelectRow
                        label="Orientation"
                        value={options.ibcsCardGraphicGeneratedOrientation || 'horizontal'}
                        options={[
                          { value: 'vertical', label: 'Column (Vertical)' },
                          { value: 'horizontal', label: 'Bar (Horizontal)' },
                        ]}
                        onChange={(v) => onUpdate('ibcsCardGraphicGeneratedOrientation' as keyof FormatOptions, v)}
                        testId="format-ibcs-orientation"
                      />
                    )}
                    {cardGraphicEditorIsBar && (
                      <SelectRow
                        label="Main chart mode"
                        value={options.ibcsCardGraphicIbcsMainChartMode || 'comparison'}
                        options={[
                          { value: 'comparison', label: 'Comparison bars' },
                          { value: 'waterfall', label: 'Waterfall bridge' },
                        ]}
                        onChange={(v) => onUpdate('ibcsCardGraphicIbcsMainChartMode' as keyof FormatOptions, v)}
                        testId="format-ibcs-main-mode"
                      />
                    )}
                    {cardGraphicEditorIsBar && (
                      <SelectRow
                        label="Data label position"
                        value={options.ibcsCardGraphicIbcsLabelPosition || 'top-inside'}
                        options={[
                          { value: 'top-inside', label: 'Top of bar (inside)' },
                          { value: 'top-outside', label: 'Top of bar (outside)' },
                          { value: 'middle', label: 'Middle of bar' },
                          { value: 'bottom', label: 'Bottom of bar' },
                        ]}
                        onChange={(v) => onUpdate('ibcsCardGraphicIbcsLabelPosition' as keyof FormatOptions, v)}
                        testId="format-ibcs-label-position"
                      />
                    )}
                    <SliderRow
                      label="Font size"
                      value={options.ibcsCardGraphicIbcsFontSize ?? 16}
                      min={6}
                      max={50}
                      onChange={(v) => onUpdate('ibcsCardGraphicIbcsFontSize' as keyof FormatOptions, v)}
                      testId="format-ibcs-font-size"
                    />
                    <SliderRow
                      label="Data label font size"
                      value={options.ibcsCardGraphicIbcsDataLabelFontSize ?? 16}
                      min={6}
                      max={50}
                      onChange={(v) => onUpdate('ibcsCardGraphicIbcsDataLabelFontSize' as keyof FormatOptions, v)}
                      testId="format-ibcs-data-label-font-size"
                    />
                    <SelectRow
                      label="Font family"
                      value={options.ibcsCardGraphicIbcsFontFamily || FONT_FAMILY_DEFAULT}
                      options={FONT_FAMILY_OPTIONS}
                      onChange={(v) => onUpdate('ibcsCardGraphicIbcsFontFamily' as keyof FormatOptions, v === FONT_FAMILY_DEFAULT ? '' : v)}
                      testId="format-ibcs-font-family"
                    />
                    {cardGraphicEditorIsBar && (
                      <SliderRow
                        label={cardGraphicBarIsHorizontal ? 'Y axis label rotation' : 'X axis label rotation'}
                        value={options.ibcsCardGraphicIbcsXAxisRotation ?? 0}
                        min={-90}
                        max={90}
                        step={5}
                        onChange={(v) => onUpdate('ibcsCardGraphicIbcsXAxisRotation' as keyof FormatOptions, v)}
                        testId="format-ibcs-xaxis-rotation"
                      />
                    )}
                    {cardGraphicEditorIsBar && (
                      <ToggleRow
                        id="ibcs-card-graphic-ibcs-show-variance-panels"
                        label="Show variance panels"
                        checked={options.ibcsCardGraphicIbcsShowVariancePanels !== false}
                        onChange={(v) => onUpdate('ibcsCardGraphicIbcsShowVariancePanels' as keyof FormatOptions, v)}
                        testId="format-ibcs-show-variance-panels"
                      />
                    )}
                    {cardGraphicEditorIsWaterfall && (
                      <SelectRow
                        label="Value scenario"
                        value={options.ibcsCardGraphicGeneratedScenario || 'ac'}
                        options={[
                          { value: 'ac', label: 'Actual (AC)' },
                          { value: 'py', label: 'Previous Year (PY)' },
                          { value: 'pl', label: 'Plan/Budget (PL)' },
                          { value: 'fc', label: 'Forecast (FC)' },
                        ]}
                        onChange={(v) => onUpdate('ibcsCardGraphicGeneratedScenario' as keyof FormatOptions, v)}
                        testId="format-ibcs-waterfall-scenario"
                      />
                    )}
                    {cardGraphicEditorIsWaterfall && (
                      <ToggleRow
                        id="ibcs-card-graphic-generated-show-totals"
                        label="Show totals"
                        checked={options.ibcsCardGraphicGeneratedShowTotals !== false}
                        onChange={(v) => onUpdate('ibcsCardGraphicGeneratedShowTotals' as keyof FormatOptions, v)}
                        testId="format-ibcs-waterfall-show-totals"
                      />
                    )}
                    {cardGraphicEditorIsWaterfall && (
                      <ToggleRow
                        id="ibcs-card-graphic-waterfall-show-connectors"
                        label="Show connector lines"
                        checked={options.ibcsCardGraphicIbcsWaterfallShowConnectors !== false}
                        onChange={(v) => onUpdate('ibcsCardGraphicIbcsWaterfallShowConnectors' as keyof FormatOptions, v)}
                        testId="format-ibcs-waterfall-show-connectors"
                      />
                    )}
                    {(cardGraphicEditorIsBar || cardGraphicEditorIsWaterfall) && (
                      <SliderRow
                        label="Horizontal padding"
                        value={options.ibcsCardGraphicIbcsCanvasPaddingH ?? 10}
                        min={0}
                        max={60}
                        onChange={(v) => onUpdate('ibcsCardGraphicIbcsCanvasPaddingH' as keyof FormatOptions, v)}
                        testId="format-ibcs-canvas-padding-h"
                      />
                    )}
                    {(cardGraphicEditorIsBar || cardGraphicEditorIsWaterfall) && (
                      <SliderRow
                        label="Vertical padding"
                        value={options.ibcsCardGraphicIbcsCanvasPaddingV ?? 10}
                        min={0}
                        max={60}
                        onChange={(v) => onUpdate('ibcsCardGraphicIbcsCanvasPaddingV' as keyof FormatOptions, v)}
                        testId="format-ibcs-canvas-padding-v"
                      />
                    )}
                  </div>
                )}
              </>
            )}
          </Section>
          <Separator />

          {/* ─── Visual Canvas ────────────────────────────────── */}
          <Section title="Visual Canvas" open={canvasOpen} onOpenChange={setCanvasOpen} testId="format-canvas-toggle">
            <ToggleRow
              id="show-visual-header"
              label="Show header"
              checked={options.showVisualHeader !== false}
              onChange={(v) => onUpdate('showVisualHeader' as keyof FormatOptions, v)}
              testId="format-show-visual-header"
            />
            <ToggleRow
              id="show-visual-border"
              label="Show border"
              checked={options.showVisualBorder !== false}
              onChange={(v) => onUpdate('showVisualBorder' as keyof FormatOptions, v)}
              testId="format-show-visual-border"
            />
            <ToggleRow
              id="show-header-border"
              label="Header separator line"
              checked={options.showHeaderBorder !== false}
              onChange={(v) => onUpdate('showHeaderBorder' as keyof FormatOptions, v)}
              testId="format-show-header-border"
            />
            <SliderRow
              label="Header font size"
              value={options.visualHeaderFontSize ?? 14}
              min={8}
              max={32}
              onChange={(v) => onUpdate('visualHeaderFontSize' as keyof FormatOptions, v)}
              testId="format-header-font-size"
            />
            <SelectRow
              label="Header font family"
              value={options.headerFontFamily || FONT_FAMILY_DEFAULT}
              options={FONT_FAMILY_OPTIONS}
              onChange={(v) => onUpdate('headerFontFamily' as keyof FormatOptions, v === FONT_FAMILY_DEFAULT ? '' : v)}
              testId="format-header-font-family"
            />
            <ColorRow
              label="Header background"
              value={options.headerBgColor || ''}
              onChange={(v) => onUpdate('headerBgColor' as keyof FormatOptions, v)}
              testId="format-header-bg-color"
            />
            <SliderRow
              label="Horizontal padding"
              value={options.ibcsCanvasPaddingH ?? 10}
              min={0}
              max={60}
              onChange={(v) => onUpdate('ibcsCanvasPaddingH' as keyof FormatOptions, v)}
              testId="format-ibcs-canvas-padding-h"
            />
            <SliderRow
              label="Vertical padding"
              value={options.ibcsCanvasPaddingV ?? 10}
              min={0}
              max={60}
              onChange={(v) => onUpdate('ibcsCanvasPaddingV' as keyof FormatOptions, v)}
              testId="format-ibcs-canvas-padding-v"
            />
            <ColorRow
              label="Background color"
              value={options.visualBgColor || ''}
              onChange={(v) => onUpdate('visualBgColor' as keyof FormatOptions, v)}
              testId="format-visual-bg-color"
            />
            <ImageUploadRow
              label="Background image"
              value={options.visualBgImage || ''}
              onChange={(v) => onUpdate('visualBgImage' as keyof FormatOptions, v)}
              testId="format-visual-bg-image"
            />
            <SliderRow
              label="Border radius"
              value={options.visualBorderRadius ?? 8}
              min={0}
              max={24}
              onChange={(v) => onUpdate('visualBorderRadius' as keyof FormatOptions, v)}
              testId="format-visual-border-radius"
            />
          </Section>
          <Separator />
        </>
      )}

      {/* For IBCS types, only show IBCS-specific controls */}
      {isIbcs ? null : (
      <>
      {/* ─── Title ────────────────────────────────────────── */}
      <Section title="Title" open={titleOpen} onOpenChange={setTitleOpen} testId="format-title-toggle">
        <ToggleRow
          id="show-title"
          label="Show title"
          checked={options.showTitle !== false}
          onChange={(v) => onUpdate('showTitle', v)}
          testId="format-show-title"
        />
        {options.showTitle !== false && (
          <>
            <TextRow
              label="Title text"
              value={options.title || ''}
              onChange={(v) => onUpdate('title', v)}
              testId="format-title-input"
              placeholder="Visual title"
            />
            <SliderRow
              label="Font size"
              value={options.titleFontSize ?? 16}
              min={8}
              max={48}
              onChange={(v) => onUpdate('titleFontSize', v)}
              testId="format-title-font-size"
            />
            <ColorRow
              label="Font color"
              value={options.titleFontColor || ''}
              onChange={(v) => onUpdate('titleFontColor', v)}
              testId="format-title-font-color"
            />
          </>
        )}
      </Section>

      <Separator />

      {/* ─── Legend ───────────────────────────────────────── */}
      <Section title="Legend" open={legendOpen} onOpenChange={setLegendOpen} testId="format-legend-toggle">
        <ToggleRow
          id="show-legend"
          label="Show legend"
          checked={options.showLegend !== false}
          onChange={(v) => onUpdate('showLegend', v)}
          testId="format-show-legend"
        />
        {options.showLegend !== false && (
          <>
            <SelectRow
              label="Position"
              value={options.legendPosition || 'right'}
              options={[
                { value: 'top', label: 'Top' },
                { value: 'bottom', label: 'Bottom' },
                { value: 'left', label: 'Left' },
                { value: 'right', label: 'Right' },
              ]}
              onChange={(v) => onUpdate('legendPosition', v)}
              testId="format-legend-position"
            />
            <ToggleRow
              id="legend-show-gradient"
              label="Show gradient"
              checked={(options as Record<string, unknown>).legendShowGradient === true}
              onChange={(v) => onUpdate('legendShowGradient' as keyof FormatOptions, v)}
              testId="format-legend-show-gradient"
            />
          </>
        )}
      </Section>

      <Separator />

      {/* ─── X Axis ──────────────────────────────────────── */}
      {hasGridlines && (
        <>
          <Section title="X Axis" open={xAxisOpen} onOpenChange={setXAxisOpen} testId="format-xaxis-toggle">
            <ToggleRow
              id="show-x-axis"
              label="Show axis"
              checked={options.showXAxis !== false}
              onChange={(v) => onUpdate('showXAxis' as keyof FormatOptions, v)}
              testId="format-show-x-axis"
            />
            {options.showXAxis !== false && (
              <>
                <ToggleRow
                  id="show-x-axis-title"
                  label="Show axis label"
                  checked={(options as Record<string, unknown>).showXAxisTitle !== false}
                  onChange={(v) => onUpdate('showXAxisTitle' as keyof FormatOptions, v)}
                  testId="format-show-x-axis-title"
                />
                {(options as Record<string, unknown>).showXAxisTitle !== false && (
                  <TextRow
                    label="Axis label"
                    value={options.xAxisLabel || ''}
                    onChange={(v) => onUpdate('xAxisLabel', v)}
                    testId="format-xaxis-label"
                    placeholder="Auto"
                  />
                )}
                <SliderRow
                  label="Tick angle"
                  value={options.xAxisTickAngle ?? 0}
                  min={-90}
                  max={90}
                  step={5}
                  onChange={(v) => onUpdate('xAxisTickAngle', v)}
                  testId="format-xaxis-tick-angle"
                />
                <ToggleRow
                  id="show-x-gridlines"
                  label="Show gridlines"
                  checked={options.showXAxisGridlines !== false}
                  onChange={(v) => onUpdate('showXAxisGridlines', v)}
                  testId="format-show-x-gridlines"
                />
                <ToggleRow
                  id="log-x"
                  label="Log scale"
                  checked={(options as Record<string, unknown>).logX === true}
                  onChange={(v) => onUpdate('logX' as keyof FormatOptions, v)}
                  testId="format-log-x"
                />
                <ToggleRow
                  id="show-range-slider"
                  label="Range slider"
                  checked={(options as Record<string, unknown>).showRangeSlider === true}
                  onChange={(v) => onUpdate('showRangeSlider' as keyof FormatOptions, v)}
                  testId="format-show-range-slider"
                />
                <ToggleRow
                  id="show-range-selector"
                  label="Range selector"
                  checked={(options as Record<string, unknown>).showRangeSelector === true}
                  onChange={(v) => onUpdate('showRangeSelector' as keyof FormatOptions, v)}
                  testId="format-show-range-selector"
                />
              </>
            )}
          </Section>

          <Separator />

          {/* ─── Y Axis ──────────────────────────────────── */}
          <Section title="Y Axis" open={yAxisOpen} onOpenChange={setYAxisOpen} testId="format-yaxis-toggle">
            <ToggleRow
              id="show-y-axis"
              label="Show axis"
              checked={options.showYAxis !== false}
              onChange={(v) => onUpdate('showYAxis' as keyof FormatOptions, v)}
              testId="format-show-y-axis"
            />
            {options.showYAxis !== false && (
              <>
                <ToggleRow
                  id="show-y-axis-title"
                  label="Show axis label"
                  checked={(options as Record<string, unknown>).showYAxisTitle !== false}
                  onChange={(v) => onUpdate('showYAxisTitle' as keyof FormatOptions, v)}
                  testId="format-show-y-axis-title"
                />
                {(options as Record<string, unknown>).showYAxisTitle !== false && (
                  <TextRow
                    label="Axis label"
                    value={options.yAxisLabel || ''}
                    onChange={(v) => onUpdate('yAxisLabel', v)}
                    testId="format-yaxis-label"
                    placeholder="Auto"
                  />
                )}
                <SliderRow
                  label="Tick angle"
                  value={options.yAxisTickAngle ?? 0}
                  min={-90}
                  max={90}
                  step={5}
                  onChange={(v) => onUpdate('yAxisTickAngle', v)}
                  testId="format-yaxis-tick-angle"
                />
                <ToggleRow
                  id="show-y-gridlines"
                  label="Show gridlines"
                  checked={options.showYAxisGridlines !== false}
                  onChange={(v) => onUpdate('showYAxisGridlines', v)}
                  testId="format-show-y-gridlines"
                />
                <ToggleRow
                  id="log-y"
                  label="Log scale"
                  checked={(options as Record<string, unknown>).logY === true}
                  onChange={(v) => onUpdate('logY' as keyof FormatOptions, v)}
                  testId="format-log-y"
                />
                {visualType === 'combo' && (
                  <>
                    <Separator />
                    <div className="text-xs font-medium text-muted-foreground px-1 pt-1">Secondary Y Axis</div>
                    <TextRow
                      label="Secondary Y label"
                      value={(options as Record<string, unknown>).y2AxisLabel as string || ''}
                      onChange={(v) => onUpdate('y2AxisLabel' as keyof FormatOptions, v)}
                      testId="format-y2axis-label"
                      placeholder="Auto"
                    />
                    <ToggleRow
                      id="show-y2-gridlines"
                      label="Secondary gridlines"
                      checked={(options as Record<string, unknown>).showY2AxisGridlines === true}
                      onChange={(v) => onUpdate('showY2AxisGridlines' as keyof FormatOptions, v)}
                      testId="format-show-y2-gridlines"
                    />
                  </>
                )}
              </>
            )}
          </Section>

          <Separator />
        </>
      )}

      {/* ─── Data Labels ─────────────────────────────────── */}
      <Section title="Data Labels" open={dataLabelsOpen} onOpenChange={setDataLabelsOpen} testId="format-datalabels-toggle">
        <ToggleRow
          id="show-data-labels"
          label="Show data labels"
          checked={options.showDataLabels === true}
          onChange={(v) => onUpdate('showDataLabels', v)}
          testId="format-show-data-labels"
        />
        {options.showDataLabels && isBar && (
          <SelectRow
            label="Label position"
            value={options.dataLabelPosition || 'auto'}
            options={[
              { value: 'auto', label: 'Auto' },
              { value: 'inside', label: 'Inside' },
              { value: 'outside', label: 'Outside' },
            ]}
            onChange={(v) => onUpdate('dataLabelPosition', v)}
            testId="format-data-label-position"
          />
        )}
        {options.showDataLabels && (isLine || isScatter) && (
          <SelectRow
            label="Label position"
            value={options.dataLabelPosition || 'top center'}
            options={[
              { value: 'top center', label: 'Top' },
              { value: 'bottom center', label: 'Bottom' },
              { value: 'top right', label: 'Top Right' },
              { value: 'top left', label: 'Top Left' },
              { value: 'middle right', label: 'Right' },
              { value: 'middle left', label: 'Left' },
            ]}
            onChange={(v) => onUpdate('dataLabelPosition', v)}
            testId="format-data-label-position"
          />
        )}
        {options.showDataLabels && (
          <ColorRow
            label="Label color"
            value={(options as Record<string, unknown>).dataLabelColor as string || ''}
            onChange={(v) => onUpdate('dataLabelColor' as keyof FormatOptions, v)}
            testId="format-data-label-color"
          />
        )}
        {options.showDataLabels && (
          <SliderRow
            label="Label font size"
            value={options.dataLabelFontSize ?? 12}
            min={6}
            max={50}
            step={1}
            onChange={(v) => onUpdate('dataLabelFontSize', v)}
            testId="format-data-label-font-size"
          />
        )}
        {options.showDataLabels && (
          <SelectRow
            label="Label font family"
            value={options.dataLabelFontFamily || FONT_FAMILY_DEFAULT}
            options={FONT_FAMILY_OPTIONS}
            onChange={(v) => onUpdate('dataLabelFontFamily', v === FONT_FAMILY_DEFAULT ? '' : v)}
            testId="format-data-label-font-family"
          />
        )}
        {options.showDataLabels && (
          <SelectRow
            label="Display units"
            value={options.dataLabelDisplayUnits || 'auto'}
            options={[
              { value: 'auto', label: 'Auto' },
              { value: 'none', label: 'None' },
              { value: 'thousands', label: 'Thousands' },
              { value: 'millions', label: 'Millions' },
              { value: 'billions', label: 'Billions' },
              { value: 'trillions', label: 'Trillions' },
            ]}
            onChange={(v) => onUpdate('dataLabelDisplayUnits', v)}
            testId="format-data-label-display-units"
          />
        )}
        {options.showDataLabels && (
          <SliderRow
            label="Decimal places"
            value={options.dataLabelPrecision ?? 0}
            min={0}
            max={10}
            step={1}
            onChange={(v) => onUpdate('dataLabelPrecision', v)}
            testId="format-data-label-precision"
          />
        )}
        {options.showDataLabels && (
          <SelectRow
            label="Show blank as"
            value={options.dataLabelShowBlankAs || '__default__'}
            options={[
              { value: '__default__', label: '(Default)' },
              { value: '(Blank)', label: '(Blank)' },
              { value: '0', label: 'Zero' },
              { value: '-', label: 'Dash' },
            ]}
            onChange={(v) => onUpdate('dataLabelShowBlankAs', v === '__default__' ? '' : v)}
            testId="format-data-label-show-blank-as"
          />
        )}
        {options.showDataLabels && (
          <SliderRow
            label="Label transparency (%)"
            value={options.dataLabelTransparency ?? 0}
            min={0}
            max={100}
            step={1}
            onChange={(v) => onUpdate('dataLabelTransparency', v)}
            testId="format-data-label-transparency"
          />
        )}
        <ToggleRow
          id="data-point-border"
          label="Data point border"
          checked={(options as Record<string, unknown>).dataPointBorderShow === true}
          onChange={(v) => onUpdate('dataPointBorderShow' as keyof FormatOptions, v)}
          testId="format-data-point-border"
        />
      </Section>

      {/* ─── Chart Style ─────────────────────────────────── */}
      {hasChartStyle && (
        <>
          <Separator />
          <Section title="Chart Style" open={chartStyleOpen} onOpenChange={setChartStyleOpen} testId="format-chartstyle-toggle">
            {isBar && (
              <>
                <SelectRow
                  label="Bar mode"
                  value={options.barMode || 'group'}
                  options={[
                    { value: 'group', label: 'Grouped' },
                    { value: 'stack', label: 'Stacked' },
                    { value: 'relative', label: 'Relative' },
                  ]}
                  onChange={(v) => onUpdate('barMode', v)}
                  testId="format-bar-mode"
                />
                <SelectRow
                  label="Orientation"
                  value={options.orientation || 'v'}
                  options={[
                    { value: 'v', label: 'Vertical' },
                    { value: 'h', label: 'Horizontal' },
                  ]}
                  onChange={(v) => onUpdate('orientation', v)}
                  testId="format-orientation"
                />
                <SliderRow
                  label="Bar gap"
                  value={(options as Record<string, unknown>).bargap as number ?? 0.2}
                  min={0}
                  max={1}
                  step={0.05}
                  onChange={(v) => onUpdate('bargap' as keyof FormatOptions, v)}
                  testId="format-bargap"
                />
                <SliderRow
                  label="Bar group gap"
                  value={(options as Record<string, unknown>).bargroupgap as number ?? 0.1}
                  min={0}
                  max={1}
                  step={0.05}
                  onChange={(v) => onUpdate('bargroupgap' as keyof FormatOptions, v)}
                  testId="format-bargroupgap"
                />
                <SliderRow
                  label="Data label angle"
                  value={(options as Record<string, unknown>).dataLabelAngle as number ?? 0}
                  min={-90}
                  max={90}
                  step={5}
                  onChange={(v) => onUpdate('dataLabelAngle' as keyof FormatOptions, v)}
                  testId="format-data-label-angle"
                />
              </>
            )}

            {isLine && (
              <>
                <SelectRow
                  label="Line shape"
                  value={options.lineShape || 'linear'}
                  options={[
                    { value: 'linear', label: 'Linear' },
                    { value: 'spline', label: 'Spline' },
                    { value: 'hv', label: 'Step (H→V)' },
                    { value: 'vh', label: 'Step (V→H)' },
                    { value: 'hvh', label: 'Step (H→V→H)' },
                    { value: 'vhv', label: 'Step (V→H→V)' },
                  ]}
                  onChange={(v) => onUpdate('lineShape', v)}
                  testId="format-line-shape"
                />
                <SelectRow
                  label="Line dash"
                  value={(options as Record<string, unknown>).lineDash as string || 'solid'}
                  options={[
                    { value: 'solid', label: 'Solid' },
                    { value: 'dot', label: 'Dotted' },
                    { value: 'dash', label: 'Dashed' },
                    { value: 'dashdot', label: 'Dash-Dot' },
                    { value: 'longdash', label: 'Long Dash' },
                    { value: 'longdashdot', label: 'Long Dash-Dot' },
                  ]}
                  onChange={(v) => onUpdate('lineDash' as keyof FormatOptions, v)}
                  testId="format-line-dash"
                />
                <SliderRow
                  label="Line width"
                  value={(options as Record<string, unknown>).lineWidth as number ?? 2}
                  min={1}
                  max={8}
                  onChange={(v) => onUpdate('lineWidth' as keyof FormatOptions, v)}
                  testId="format-line-width"
                />
                <ToggleRow
                  id="show-markers"
                  label="Show markers"
                  checked={options.showMarkers !== false}
                  onChange={(v) => onUpdate('showMarkers', v)}
                  testId="format-show-markers"
                />
                {visualType === 'line' && (
                  <ToggleRow
                    id="fill-area"
                    label="Fill area below line"
                    checked={(options as Record<string, unknown>).fillArea === true}
                    onChange={(v) => onUpdate('fillArea' as keyof FormatOptions, v)}
                    testId="format-fill-area"
                  />
                )}
              </>
            )}

            {isScatter && (
              <>
                <SliderRow
                  label="Marker size"
                  value={options.markerSize ?? 8}
                  min={2}
                  max={30}
                  onChange={(v) => onUpdate('markerSize', v)}
                  testId="format-marker-size"
                />
                <SliderRow
                  label="Marker opacity"
                  value={(options as Record<string, unknown>).markerOpacity as number ?? 1}
                  min={0}
                  max={1}
                  step={0.05}
                  onChange={(v) => onUpdate('markerOpacity' as keyof FormatOptions, v)}
                  testId="format-marker-opacity"
                />
                <SelectRow
                  label="Marker symbol"
                  value={(options as Record<string, unknown>).markerSymbol as string || 'circle'}
                  options={[
                    { value: 'circle', label: 'Circle' },
                    { value: 'square', label: 'Square' },
                    { value: 'diamond', label: 'Diamond' },
                    { value: 'cross', label: 'Cross' },
                    { value: 'x', label: 'X' },
                    { value: 'triangle-up', label: 'Triangle Up' },
                    { value: 'triangle-down', label: 'Triangle Down' },
                    { value: 'star', label: 'Star' },
                    { value: 'hexagon', label: 'Hexagon' },
                    { value: 'pentagon', label: 'Pentagon' },
                  ]}
                  onChange={(v) => onUpdate('markerSymbol' as keyof FormatOptions, v)}
                  testId="format-marker-symbol"
                />
              </>
            )}

            {/* ── Pie / Donut style ──────────────────────── */}
            {isPie && (
              <>
                <SliderRow
                  label="Donut hole size"
                  value={(options as Record<string, unknown>).pieHole as number ?? 0}
                  min={0}
                  max={0.8}
                  step={0.05}
                  onChange={(v) => onUpdate('pieHole' as keyof FormatOptions, v)}
                  testId="format-pie-hole"
                />
                <SelectRow
                  label="Slice text"
                  value={(options as Record<string, unknown>).pieTextInfo as string || 'percent'}
                  options={[
                    { value: 'percent', label: 'Percent' },
                    { value: 'value', label: 'Value' },
                    { value: 'label', label: 'Label' },
                    { value: 'label+percent', label: 'Label + Percent' },
                    { value: 'label+value', label: 'Label + Value' },
                    { value: 'value+percent', label: 'Value + Percent' },
                    { value: 'none', label: 'None' },
                  ]}
                  onChange={(v) => onUpdate('pieTextInfo' as keyof FormatOptions, v)}
                  testId="format-pie-text-info"
                />
                <SelectRow
                  label="Text position"
                  value={(options as Record<string, unknown>).pieTextPosition as string || 'auto'}
                  options={[
                    { value: 'auto', label: 'Auto' },
                    { value: 'inside', label: 'Inside' },
                    { value: 'outside', label: 'Outside' },
                    { value: 'none', label: 'None' },
                  ]}
                  onChange={(v) => onUpdate('pieTextPosition' as keyof FormatOptions, v)}
                  testId="format-pie-text-position"
                />
                <SliderRow
                  label="Explode slices"
                  value={(options as Record<string, unknown>).piePull as number ?? 0}
                  min={0}
                  max={0.2}
                  step={0.01}
                  onChange={(v) => onUpdate('piePull' as keyof FormatOptions, v)}
                  testId="format-pie-pull"
                />
                <SliderRow
                  label="Start angle"
                  value={(options as Record<string, unknown>).pieStartAngle as number ?? 0}
                  min={0}
                  max={360}
                  step={5}
                  onChange={(v) => onUpdate('pieStartAngle' as keyof FormatOptions, v)}
                  testId="format-pie-start-angle"
                />
              </>
            )}

            {/* ── Histogram style ────────────────────────── */}
            {isHistogram && (
              <>
                <SliderRow
                  label="Number of bins (0=auto)"
                  value={(options as Record<string, unknown>).histNbins as number ?? 0}
                  min={0}
                  max={200}
                  onChange={(v) => onUpdate('histNbins' as keyof FormatOptions, v)}
                  testId="format-hist-nbins"
                />
                <SelectRow
                  label="Aggregation"
                  value={(options as Record<string, unknown>).histFunc as string || 'count'}
                  options={[
                    { value: 'count', label: 'Count' },
                    { value: 'sum', label: 'Sum' },
                    { value: 'avg', label: 'Average' },
                    { value: 'min', label: 'Min' },
                    { value: 'max', label: 'Max' },
                  ]}
                  onChange={(v) => onUpdate('histFunc' as keyof FormatOptions, v)}
                  testId="format-hist-func"
                />
                <SelectRow
                  label="Normalization"
                  value={(options as Record<string, unknown>).histNorm as string || '__none__'}
                  options={[
                    { value: '__none__', label: 'None' },
                    { value: 'percent', label: 'Percent' },
                    { value: 'probability', label: 'Probability' },
                    { value: 'density', label: 'Density' },
                    { value: 'probability density', label: 'Probability Density' },
                  ]}
                  onChange={(v) => onUpdate('histNorm' as keyof FormatOptions, v === '__none__' ? '' : v)}
                  testId="format-hist-norm"
                />
                <ToggleRow
                  id="cumulative"
                  label="Cumulative"
                  checked={(options as Record<string, unknown>).cumulative === true}
                  onChange={(v) => onUpdate('cumulative' as keyof FormatOptions, v)}
                  testId="format-cumulative"
                />
              </>
            )}

            {/* ── Box style ──────────────────────────────── */}
            {isBox && (
              <>
                <SelectRow
                  label="Show points"
                  value={(options as Record<string, unknown>).boxPoints as string || 'outliers'}
                  options={[
                    { value: 'all', label: 'All' },
                    { value: 'outliers', label: 'Outliers' },
                    { value: 'suspectedoutliers', label: 'Suspected Outliers' },
                    { value: 'false', label: 'None' },
                  ]}
                  onChange={(v) => onUpdate('boxPoints' as keyof FormatOptions, v)}
                  testId="format-box-points"
                />
                <SelectRow
                  label="Show mean"
                  value={(options as Record<string, unknown>).boxMean as string || '__none__'}
                  options={[
                    { value: '__none__', label: 'None' },
                    { value: 'true', label: 'Line' },
                    { value: 'sd', label: 'With Std Dev' },
                  ]}
                  onChange={(v) => onUpdate('boxMean' as keyof FormatOptions, v === '__none__' ? '' : v)}
                  testId="format-box-mean"
                />
                <ToggleRow
                  id="notched"
                  label="Notched"
                  checked={(options as Record<string, unknown>).notched === true}
                  onChange={(v) => onUpdate('notched' as keyof FormatOptions, v)}
                  testId="format-notched"
                />
              </>
            )}

            {/* ── Violin style ───────────────────────────── */}
            {isViolin && (
              <>
                <SelectRow
                  label="Violin side"
                  value={(options as Record<string, unknown>).violinSide as string || 'both'}
                  options={[
                    { value: 'both', label: 'Both' },
                    { value: 'positive', label: 'Positive' },
                    { value: 'negative', label: 'Negative' },
                  ]}
                  onChange={(v) => onUpdate('violinSide' as keyof FormatOptions, v)}
                  testId="format-violin-side"
                />
                <SelectRow
                  label="Show points"
                  value={(options as Record<string, unknown>).violinPoints as string || 'false'}
                  options={[
                    { value: 'all', label: 'All' },
                    { value: 'outliers', label: 'Outliers' },
                    { value: 'false', label: 'None' },
                  ]}
                  onChange={(v) => onUpdate('violinPoints' as keyof FormatOptions, v)}
                  testId="format-violin-points"
                />
                <ToggleRow
                  id="violin-box"
                  label="Show box inside"
                  checked={(options as Record<string, unknown>).violinBox === true}
                  onChange={(v) => onUpdate('violinBox' as keyof FormatOptions, v)}
                  testId="format-violin-box"
                />
              </>
            )}

            {/* ── Strip style ────────────────────────────── */}
            {isStrip && (
              <SliderRow
                label="Jitter"
                value={(options as Record<string, unknown>).stripJitter as number ?? 0.3}
                min={0}
                max={1}
                step={0.05}
                onChange={(v) => onUpdate('stripJitter' as keyof FormatOptions, v)}
                testId="format-strip-jitter"
              />
            )}

            {/* ── Hierarchical style ─────────────────────── */}
            {isHierarchical && (
              <>
                <SliderRow
                  label="Max depth (-1=all)"
                  value={(options as Record<string, unknown>).maxDepth as number ?? -1}
                  min={-1}
                  max={10}
                  onChange={(v) => onUpdate('maxDepth' as keyof FormatOptions, v)}
                  testId="format-max-depth"
                />
                <SelectRow
                  label="Text info"
                  value={(options as Record<string, unknown>).hierTextInfo as string || 'label+value'}
                  options={[
                    { value: 'label', label: 'Label' },
                    { value: 'value', label: 'Value' },
                    { value: 'label+value', label: 'Label + Value' },
                    { value: 'label+percent entry', label: 'Label + %' },
                    { value: 'percent entry', label: '% of Entry' },
                    { value: 'percent parent', label: '% of Parent' },
                    { value: 'percent root', label: '% of Root' },
                    { value: 'none', label: 'None' },
                  ]}
                  onChange={(v) => onUpdate('hierTextInfo' as keyof FormatOptions, v)}
                  testId="format-hier-text-info"
                />
                <SelectRow
                  label="Branch values"
                  value={(options as Record<string, unknown>).branchValues as string || 'remainder'}
                  options={[
                    { value: 'remainder', label: 'Remainder' },
                    { value: 'total', label: 'Total' },
                  ]}
                  onChange={(v) => onUpdate('branchValues' as keyof FormatOptions, v)}
                  testId="format-branch-values"
                />
              </>
            )}

            {/* ── Polar style ────────────────────────────── */}
            {isPolar && (
              <>
                <SelectRow
                  label="Angular direction"
                  value={(options as Record<string, unknown>).polarAngularDirection as string || 'clockwise'}
                  options={[
                    { value: 'clockwise', label: 'Clockwise' },
                    { value: 'counterclockwise', label: 'Counter-clockwise' },
                  ]}
                  onChange={(v) => onUpdate('polarAngularDirection' as keyof FormatOptions, v)}
                  testId="format-polar-direction"
                />
                <SliderRow
                  label="Start angle"
                  value={(options as Record<string, unknown>).polarStartAngle as number ?? 90}
                  min={0}
                  max={360}
                  step={5}
                  onChange={(v) => onUpdate('polarStartAngle' as keyof FormatOptions, v)}
                  testId="format-polar-start-angle"
                />
                <SelectRow
                  label="Fill mode"
                  value={(options as Record<string, unknown>).polarFill as string || '__none__'}
                  options={[
                    { value: '__none__', label: 'None' },
                    { value: 'toself', label: 'Fill to Self' },
                    { value: 'tonext', label: 'Fill to Next' },
                  ]}
                  onChange={(v) => onUpdate('polarFill' as keyof FormatOptions, v === '__none__' ? '' : v)}
                  testId="format-polar-fill"
                />
              </>
            )}

            {/* ── Financial style (candlestick/OHLC) ─────── */}
            {isFinancial && (
              <>
                <ColorRow
                  label="Increasing color"
                  value={(options as Record<string, unknown>).financialIncreasingColor as string || '#26A69A'}
                  onChange={(v) => onUpdate('financialIncreasingColor' as keyof FormatOptions, v)}
                  testId="format-financial-increasing-color"
                />
                <ColorRow
                  label="Decreasing color"
                  value={(options as Record<string, unknown>).financialDecreasingColor as string || '#EF5350'}
                  onChange={(v) => onUpdate('financialDecreasingColor' as keyof FormatOptions, v)}
                  testId="format-financial-decreasing-color"
                />
              </>
            )}

            {/* ── Gauge style ────────────────────────────── */}
            {isGauge && (
              <>
                <SelectRow
                  label="Gauge shape"
                  value={(options as Record<string, unknown>).gaugeShape as string || 'angular'}
                  options={[
                    { value: 'angular', label: 'Angular (semicircle)' },
                    { value: 'bullet', label: 'Bullet (horizontal)' },
                  ]}
                  onChange={(v) => onUpdate('gaugeShape' as keyof FormatOptions, v)}
                  testId="format-gauge-shape"
                />
                <SliderRow
                  label="Axis max (0=auto)"
                  value={(options as Record<string, unknown>).gaugeAxisRangeMax as number ?? 0}
                  min={0}
                  max={1000000}
                  step={1000}
                  onChange={(v) => onUpdate('gaugeAxisRangeMax' as keyof FormatOptions, v)}
                  testId="format-gauge-axis-range-max"
                />
                <ColorRow
                  label="Bar color"
                  value={(options as Record<string, unknown>).gaugeBarColor as string || ''}
                  onChange={(v) => onUpdate('gaugeBarColor' as keyof FormatOptions, v)}
                  testId="format-gauge-bar-color"
                />
                <ToggleRow
                  id="gauge-steps"
                  label="Background steps"
                  checked={(options as Record<string, unknown>).gaugeSteps !== false}
                  onChange={(v) => onUpdate('gaugeSteps' as keyof FormatOptions, v)}
                  testId="format-gauge-steps"
                />
              </>
            )}

            {/* ── Sankey style ───────────────────────────── */}
            {isSankey && (
              <>
                <SliderRow
                  label="Node thickness"
                  value={(options as Record<string, unknown>).sankeyNodeThickness as number ?? 20}
                  min={5}
                  max={50}
                  onChange={(v) => onUpdate('sankeyNodeThickness' as keyof FormatOptions, v)}
                  testId="format-sankey-node-thickness"
                />
                <SliderRow
                  label="Node padding"
                  value={(options as Record<string, unknown>).sankeyNodePadding as number ?? 10}
                  min={2}
                  max={50}
                  onChange={(v) => onUpdate('sankeyNodePadding' as keyof FormatOptions, v)}
                  testId="format-sankey-node-padding"
                />
                <SelectRow
                  label="Orientation"
                  value={(options as Record<string, unknown>).sankeyOrientation as string || 'h'}
                  options={[
                    { value: 'h', label: 'Horizontal' },
                    { value: 'v', label: 'Vertical' },
                  ]}
                  onChange={(v) => onUpdate('sankeyOrientation' as keyof FormatOptions, v)}
                  testId="format-sankey-orientation"
                />
              </>
            )}

            {/* ── Waterfall style ────────────────────────── */}
            {isWaterfall && (
              <>
                <ToggleRow
                  id="waterfall-connector"
                  label="Connector lines"
                  checked={(options as Record<string, unknown>).waterfallConnectorLine !== false}
                  onChange={(v) => onUpdate('waterfallConnectorLine' as keyof FormatOptions, v)}
                  testId="format-waterfall-connector"
                />
                <ColorRow
                  label="Increasing color"
                  value={(options as Record<string, unknown>).waterfallIncreasingColor as string || '#26A69A'}
                  onChange={(v) => onUpdate('waterfallIncreasingColor' as keyof FormatOptions, v)}
                  testId="format-waterfall-increasing-color"
                />
                <ColorRow
                  label="Decreasing color"
                  value={(options as Record<string, unknown>).waterfallDecreasingColor as string || '#EF5350'}
                  onChange={(v) => onUpdate('waterfallDecreasingColor' as keyof FormatOptions, v)}
                  testId="format-waterfall-decreasing-color"
                />
                <ColorRow
                  label="Total bar color"
                  value={(options as Record<string, unknown>).waterfallTotalColor as string || '#42A5F5'}
                  onChange={(v) => onUpdate('waterfallTotalColor' as keyof FormatOptions, v)}
                  testId="format-waterfall-total-color"
                />
              </>
            )}

            {/* ── Global chart style ─────────────────────── */}
            <SelectRow
              label="Hover mode"
              value={(options as Record<string, unknown>).hoverMode as string || '__default__'}
              options={[
                { value: '__default__', label: 'Default' },
                { value: 'closest', label: 'Closest' },
                { value: 'x', label: 'X axis' },
                { value: 'y', label: 'Y axis' },
                { value: 'x unified', label: 'X unified' },
                { value: 'y unified', label: 'Y unified' },
                { value: 'false', label: 'Off' },
              ]}
              onChange={(v) => onUpdate('hoverMode' as keyof FormatOptions, v === '__default__' ? '' : v)}
              testId="format-hover-mode"
            />
            <SelectRow
              label="Chart font"
              value={(options as Record<string, unknown>).chartFontFamily as string || '__default__'}
              options={[
                { value: '__default__', label: 'Default' },
                { value: 'Arial', label: 'Arial' },
                { value: 'Helvetica', label: 'Helvetica' },
                { value: 'Inter', label: 'Inter' },
                { value: 'Segoe UI', label: 'Segoe UI' },
                { value: 'Courier New', label: 'Courier New' },
                { value: 'Georgia', label: 'Georgia' },
                { value: 'Times New Roman', label: 'Times New Roman' },
              ]}
              onChange={(v) => onUpdate('chartFontFamily' as keyof FormatOptions, v === '__default__' ? '' : v)}
              testId="format-chart-font-family"
            />
            <SliderRow
              label="Chart font size"
              value={(options as Record<string, unknown>).chartFontSize as number ?? 12}
              min={8}
              max={24}
              onChange={(v) => onUpdate('chartFontSize' as keyof FormatOptions, v)}
              testId="format-chart-font-size"
            />
            {hasPattern && (
              <SelectRow
                label="Pattern / hatching"
                value={(options as Record<string, unknown>).patternShape as string || '__none__'}
                options={[
                  { value: '__none__', label: 'None' },
                  { value: '/', label: '/ diagonal' },
                  { value: '\\', label: '\\ back-diagonal' },
                  { value: 'x', label: 'x cross-hatch' },
                  { value: '+', label: '+ plus' },
                  { value: '.', label: '. dots' },
                  { value: '-', label: '- horizontal' },
                  { value: '|', label: '| vertical' },
                ]}
                onChange={(v) => onUpdate('patternShape' as keyof FormatOptions, v === '__none__' ? '' : v)}
                testId="format-pattern-shape"
              />
            )}
            {hasWebGL && (
              <SelectRow
                label="Render mode"
                value={(options as Record<string, unknown>).renderMode as string || '__default__'}
                options={[
                  { value: '__default__', label: 'SVG (default)' },
                  { value: 'webgl', label: 'WebGL (fast)' },
                ]}
                onChange={(v) => onUpdate('renderMode' as keyof FormatOptions, v === '__default__' ? '' : v)}
                testId="format-render-mode"
              />
            )}
            <ToggleRow
              id="latex-enabled"
              label="LaTeX math text"
              checked={(options as Record<string, unknown>).latexEnabled === true}
              onChange={(v) => onUpdate('latexEnabled' as keyof FormatOptions, v)}
              testId="format-latex-enabled"
            />
          </Section>
        </>
      )}

      {/* ─── Analytics ───────────────────────────────────── */}
      {hasAnalytics && (
        <>
          <Separator />
          <Section title="Analytics" open={analyticsOpen} onOpenChange={setAnalyticsOpen} testId="format-analytics-toggle">
            {hasTrendline && (
              <>
                <SelectRow
                  label="Trendline"
                  value={(options as Record<string, unknown>).trendline as string || '__none__'}
                  options={[
                    { value: '__none__', label: 'None' },
                    { value: 'ols', label: 'Linear (OLS)' },
                    { value: 'lowess', label: 'LOWESS' },
                    { value: 'expanding', label: 'Expanding mean' },
                    { value: 'rolling', label: 'Rolling mean' },
                    { value: 'ewm', label: 'Exponential (EWM)' },
                  ]}
                  onChange={(v) => onUpdate('trendline' as keyof FormatOptions, v === '__none__' ? '' : v)}
                  testId="format-trendline"
                />
                {(options as Record<string, unknown>).trendline && (
                  <SelectRow
                    label="Trendline scope"
                    value={(options as Record<string, unknown>).trendlineScope as string || 'trace'}
                    options={[
                      { value: 'trace', label: 'Per trace' },
                      { value: 'overall', label: 'Overall' },
                    ]}
                    onChange={(v) => onUpdate('trendlineScope' as keyof FormatOptions, v)}
                    testId="format-trendline-scope"
                  />
                )}
              </>
            )}
            {hasMarginals && (
              <>
                <SelectRow
                  label="Marginal X"
                  value={(options as Record<string, unknown>).marginalX as string || '__none__'}
                  options={[
                    { value: '__none__', label: 'None' },
                    { value: 'histogram', label: 'Histogram' },
                    { value: 'rug', label: 'Rug' },
                    { value: 'box', label: 'Box' },
                    { value: 'violin', label: 'Violin' },
                  ]}
                  onChange={(v) => onUpdate('marginalX' as keyof FormatOptions, v === '__none__' ? '' : v)}
                  testId="format-marginal-x"
                />
                <SelectRow
                  label="Marginal Y"
                  value={(options as Record<string, unknown>).marginalY as string || '__none__'}
                  options={[
                    { value: '__none__', label: 'None' },
                    { value: 'histogram', label: 'Histogram' },
                    { value: 'rug', label: 'Rug' },
                    { value: 'box', label: 'Box' },
                    { value: 'violin', label: 'Violin' },
                  ]}
                  onChange={(v) => onUpdate('marginalY' as keyof FormatOptions, v === '__none__' ? '' : v)}
                  testId="format-marginal-y"
                />
              </>
            )}
            {hasErrorBars && (
              <>
                <ToggleRow
                  id="error-bars-y"
                  label="Show Y error bars"
                  checked={(options as Record<string, unknown>).errorBarsY === true}
                  onChange={(v) => onUpdate('errorBarsY' as keyof FormatOptions, v)}
                  testId="format-error-bars-y"
                />
                {(options as Record<string, unknown>).errorBarsY && (
                  <SliderRow
                    label="Y error ±%"
                    value={(options as Record<string, unknown>).errorBarsYValue as number ?? 10}
                    min={0}
                    max={100}
                    onChange={(v) => onUpdate('errorBarsYValue' as keyof FormatOptions, v)}
                    testId="format-error-bars-y-value"
                  />
                )}
              </>
            )}
          </Section>
        </>
      )}

      {/* ─── Colors ──────────────────────────────────────── */}
      <Separator />
      <Section title="Colors" open={colorsOpen} onOpenChange={setColorsOpen} testId="format-colors-toggle">
        <SelectRow
          label="Color palette"
          value={options.colorSequence || '__default__'}
          options={[
            { value: '__default__', label: 'Default' },
            ...COLOR_SEQUENCES.map((s) => ({ value: s, label: s })),
          ]}
          onChange={(v) => onUpdate('colorSequence', v === '__default__' ? '' : v)}
          testId="format-color-sequence"
        />
        <ColorRow
          label="Plot background"
          value={options.plotBgColor || ''}
          onChange={(v) => onUpdate('plotBgColor', v)}
          testId="format-plot-bg-color"
        />
        <ColorRow
          label="Paper background"
          value={options.paperBgColor || ''}
          onChange={(v) => onUpdate('paperBgColor', v)}
          testId="format-paper-bg-color"
        />
        {hasContinuousColor && (
          <SelectRow
            label="Continuous color scale"
            value={(options as Record<string, unknown>).colorContinuousScale as string || '__default__'}
            options={[
              { value: '__default__', label: 'Default' },
              { value: 'Viridis', label: 'Viridis' },
              { value: 'Cividis', label: 'Cividis' },
              { value: 'Inferno', label: 'Inferno' },
              { value: 'Magma', label: 'Magma' },
              { value: 'Plasma', label: 'Plasma' },
              { value: 'Turbo', label: 'Turbo' },
              { value: 'Blues', label: 'Blues' },
              { value: 'Reds', label: 'Reds' },
              { value: 'YlGnBu', label: 'Yellow-Green-Blue' },
              { value: 'RdBu', label: 'Red-Blue (diverging)' },
              { value: 'Spectral', label: 'Spectral (diverging)' },
            ]}
            onChange={(v) => onUpdate('colorContinuousScale' as keyof FormatOptions, v === '__default__' ? '' : v)}
            testId="format-color-continuous-scale"
          />
        )}
      </Section>

      {/* ─── Small Multiples ───────────────────────────── */}
      {visualEncodings?.small_multiples && (
        <>
          <Separator />
          <Section title="Small Multiples" open={smallMultiplesOpen} onOpenChange={setSmallMultiplesOpen} testId="format-small-multiples-toggle">
            <SliderRow
              label={`Columns: ${(options.smallMultiplesMaxColumns ?? 0) === 0 ? 'Auto' : options.smallMultiplesMaxColumns}`}
              value={options.smallMultiplesMaxColumns ?? 0}
              min={0}
              max={8}
              step={1}
              onChange={(v) => onUpdate('smallMultiplesMaxColumns' as keyof FormatOptions, v)}
              testId="format-small-multiples-max-columns"
            />
          </Section>
        </>
      )}

      {/* ─── Visual Canvas (non-IBCS) ──────────────────── */}
      <Separator />
      <Section title="Visual Canvas" open={canvasOpen} onOpenChange={setCanvasOpen} testId="format-canvas-toggle">
        <ToggleRow
          id="show-visual-header"
          label="Show header"
          checked={options.showVisualHeader !== false}
          onChange={(v) => onUpdate('showVisualHeader' as keyof FormatOptions, v)}
          testId="format-show-visual-header"
        />
        <ToggleRow
          id="show-header-border"
          label="Header separator line"
          checked={options.showHeaderBorder !== false}
          onChange={(v) => onUpdate('showHeaderBorder' as keyof FormatOptions, v)}
          testId="format-show-header-border"
        />
        <ToggleRow
          id="show-visual-border"
          label="Show border"
          checked={options.showVisualBorder !== false}
          onChange={(v) => onUpdate('showVisualBorder' as keyof FormatOptions, v)}
          testId="format-show-visual-border"
        />
        <SliderRow
          label="Header font size"
          value={options.visualHeaderFontSize ?? 14}
          min={8}
          max={32}
          onChange={(v) => onUpdate('visualHeaderFontSize' as keyof FormatOptions, v)}
          testId="format-header-font-size"
        />
        <SelectRow
          label="Header font family"
          value={options.headerFontFamily || FONT_FAMILY_DEFAULT}
          options={FONT_FAMILY_OPTIONS}
          onChange={(v) => onUpdate('headerFontFamily' as keyof FormatOptions, v === FONT_FAMILY_DEFAULT ? '' : v)}
          testId="format-header-font-family"
        />
        <ColorRow
          label="Header background"
          value={options.headerBgColor || ''}
          onChange={(v) => onUpdate('headerBgColor' as keyof FormatOptions, v)}
          testId="format-header-bg-color"
        />
        <ToggleRow
          id="transparent-bg"
          label="Transparent background"
          checked={(options as Record<string, unknown>).transparentBg === true}
          onChange={(v) => onUpdate('transparentBg' as keyof FormatOptions, v)}
          testId="format-transparent-bg"
        />
        <SliderRow
          label="Border radius"
          value={options.visualBorderRadius ?? 8}
          min={0}
          max={24}
          onChange={(v) => onUpdate('visualBorderRadius' as keyof FormatOptions, v)}
          testId="format-visual-border-radius"
        />
      </Section>
      </>
      )}
    </div>
  )
}

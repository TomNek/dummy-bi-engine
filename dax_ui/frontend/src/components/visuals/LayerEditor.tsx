/**
 * LayerEditor — composable layer configuration for combo charts.
 *
 * Each layer defines: mark type, Y measure (via FieldWell drag-drop),
 * secondary_y toggle, optional color encoding, and per-layer format options.
 * Layers can be added, removed, and reordered (drag handle).
 *
 * Architecture note: layers are stored as `encodings.layers` in the visual
 * JSON. The backend's _build_combo() reads this array directly.
 */

import { useState, useCallback } from 'react'
import { Plus, Trash2, ChevronDown, ChevronRight, GripVertical, ArrowUp, ArrowDown } from 'lucide-react'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '@/components/ui/collapsible'
import { FieldWell, type FieldExpr, type SlotSpec } from './FieldWell'

/* ── Types ─────────────────────────────────────────────────────── */

export interface ComboLayer {
  type: 'bar' | 'line' | 'scatter' | 'area'
  y: FieldExpr | null
  secondary_y: boolean
  color?: FieldExpr | null
  name?: string
  format: Record<string, unknown>
}

const MARK_TYPES = [
  { value: 'bar', label: 'Bar' },
  { value: 'line', label: 'Line' },
  { value: 'scatter', label: 'Scatter' },
  { value: 'area', label: 'Area' },
] as const

const COLORSCALE_OPTIONS = [
  'Viridis', 'Plasma', 'Inferno', 'Magma', 'Cividis',
  'Turbo', 'Blues', 'Reds', 'Greens', 'YlOrRd',
]

const LINE_DASH_OPTIONS = [
  { value: 'solid', label: 'Solid' },
  { value: 'dot', label: 'Dot' },
  { value: 'dash', label: 'Dash' },
  { value: 'dashdot', label: 'Dash-Dot' },
  { value: 'longdash', label: 'Long Dash' },
]

const MARKER_SYMBOL_OPTIONS = [
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
]

/* ── Per-layer format sub-panel ────────────────────────────────── */

interface LayerFormatProps {
  layerType: string
  format: Record<string, unknown>
  onUpdate: (key: string, value: unknown) => void
}

function LayerFormatPanel({ layerType, format, onUpdate }: LayerFormatProps) {
  const isLine = layerType === 'line' || layerType === 'area'
  const hasMarkers = layerType === 'scatter' || layerType === 'line'

  return (
    <div className="space-y-2 pl-2 border-l border-muted" data-testid="layer-format-panel">
      {/* Colorscale */}
      <div className="flex items-center justify-between gap-2">
        <Label className="text-[10px]">Color Scale</Label>
        <Select
          value={(format.colorscale as string) || '__none__'}
          onValueChange={(v) => onUpdate('colorscale', v === '__none__' ? undefined : v)}
        >
          <SelectTrigger className="h-6 text-[10px] w-[100px]" data-testid="layer-colorscale">
            <SelectValue placeholder="None" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="__none__">None</SelectItem>
            {COLORSCALE_OPTIONS.map(cs => (
              <SelectItem key={cs} value={cs}>{cs}</SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {/* Opacity */}
      <div className="flex items-center justify-between gap-2">
        <Label className="text-[10px]">Opacity</Label>
        <input
          type="number"
          min={0} max={1} step={0.1}
          className="h-6 w-[60px] text-[10px] border rounded px-1"
          value={(format.opacity as number) ?? 1}
          onChange={(e) => onUpdate('opacity', parseFloat(e.target.value))}
          data-testid="layer-opacity"
        />
      </div>

      {/* Line-specific */}
      {isLine && (
        <>
          <div className="flex items-center justify-between gap-2">
            <Label className="text-[10px]">Line Width</Label>
            <input
              type="number"
              min={1} max={10} step={0.5}
              className="h-6 w-[60px] text-[10px] border rounded px-1"
              value={(format.lineWidth as number) ?? 2}
              onChange={(e) => onUpdate('lineWidth', parseFloat(e.target.value))}
              data-testid="layer-line-width"
            />
          </div>
          <div className="flex items-center justify-between gap-2">
            <Label className="text-[10px]">Dash</Label>
            <Select
              value={(format.lineDash as string) || 'solid'}
              onValueChange={(v) => onUpdate('lineDash', v)}
            >
              <SelectTrigger className="h-6 text-[10px] w-[100px]" data-testid="layer-line-dash">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {LINE_DASH_OPTIONS.map(d => (
                  <SelectItem key={d.value} value={d.value}>{d.label}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </>
      )}

      {/* Marker-specific */}
      {hasMarkers && (
        <>
          {layerType === 'line' && (
            <div className="flex items-center justify-between gap-2">
              <Label className="text-[10px]">Show Markers</Label>
              <Switch
                checked={(format.showMarkers as boolean) ?? true}
                onCheckedChange={(v) => onUpdate('showMarkers', v)}
                data-testid="layer-show-markers"
              />
            </div>
          )}
          <div className="flex items-center justify-between gap-2">
            <Label className="text-[10px]">Marker Size</Label>
            <input
              type="number"
              min={2} max={20} step={1}
              className="h-6 w-[60px] text-[10px] border rounded px-1"
              value={(format.markerSize as number) ?? (layerType === 'scatter' ? 8 : 6)}
              onChange={(e) => onUpdate('markerSize', parseInt(e.target.value))}
              data-testid="layer-marker-size"
            />
          </div>
          <div className="flex items-center justify-between gap-2">
            <Label className="text-[10px]">Marker Shape</Label>
            <Select
              value={(format.markerSymbol as string) || 'circle'}
              onValueChange={(v) => onUpdate('markerSymbol', v)}
            >
              <SelectTrigger className="h-6 text-[10px] w-[100px]" data-testid="layer-marker-symbol">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {MARKER_SYMBOL_OPTIONS.map(s => (
                  <SelectItem key={s.value} value={s.value}>{s.label}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </>
      )}

      {/* Data Labels (G4) */}
      <div className="flex items-center justify-between gap-2">
        <Label className="text-[10px]">Data Labels</Label>
        <Switch
          checked={(format.showDataLabels as boolean) ?? false}
          onCheckedChange={(v) => onUpdate('showDataLabels', v)}
          data-testid="layer-show-data-labels"
        />
      </div>
      {(format.showDataLabels as boolean) && (
        <div className="flex items-center justify-between gap-2">
          <Label className="text-[10px]">Label Position</Label>
          <Select
            value={(format.dataLabelPosition as string) || 'auto'}
            onValueChange={(v) => onUpdate('dataLabelPosition', v)}
          >
            <SelectTrigger className="h-6 text-[10px] w-[100px]" data-testid="layer-data-label-position">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="auto">Auto</SelectItem>
              <SelectItem value="top center">Top</SelectItem>
              <SelectItem value="bottom center">Bottom</SelectItem>
              <SelectItem value="inside">Inside</SelectItem>
              <SelectItem value="outside">Outside</SelectItem>
            </SelectContent>
          </Select>
        </div>
      )}

      {/* Mark Border (G17) — bar/scatter */}
      {(layerType === 'bar' || layerType === 'scatter') && (
        <>
          <div className="flex items-center justify-between gap-2">
            <Label className="text-[10px]">Border Color</Label>
            <input
              type="color"
              title="Border color"
              className="h-6 w-[40px] p-0 border rounded cursor-pointer"
              value={(format.borderColor as string) || '#000000'}
              onChange={(e) => onUpdate('borderColor', e.target.value)}
              data-testid="layer-border-color"
            />
          </div>
          <div className="flex items-center justify-between gap-2">
            <Label className="text-[10px]">Border Width</Label>
            <input
              type="number"
              title="Border width"
              min={0} max={5} step={0.5}
              className="h-6 w-[60px] text-[10px] border rounded px-1"
              value={(format.borderWidth as number) ?? 0}
              onChange={(e) => onUpdate('borderWidth', parseFloat(e.target.value))}
              data-testid="layer-border-width"
            />
          </div>
        </>
      )}
    </div>
  )
}

/* ── Single layer card ─────────────────────────────────────────── */

interface LayerCardProps {
  layer: ComboLayer
  index: number
  totalLayers: number
  tables?: Array<{ name: string; columns: string[] }>
  onChange: (updated: ComboLayer) => void
  onRemove: () => void
  onMoveUp: () => void
  onMoveDown: () => void
}

function LayerCard({ layer, index, totalLayers, tables, onChange, onRemove, onMoveUp, onMoveDown }: LayerCardProps) {
  const [open, setOpen] = useState(index === 0)

  const ySlot: SlotSpec = { kind: 'measure', required: true, multi: false }
  const colorSlot: SlotSpec = { kind: 'dimension', required: false, multi: false }

  const handleFormatUpdate = useCallback((key: string, value: unknown) => {
    const newFormat = { ...layer.format, [key]: value }
    // Remove undefined values
    Object.keys(newFormat).forEach(k => {
      if (newFormat[k] === undefined) delete newFormat[k]
    })
    onChange({ ...layer, format: newFormat })
  }, [layer, onChange])

  return (
    <Collapsible open={open} onOpenChange={setOpen}>
      <div
        className="flex items-center gap-1 px-1 py-0.5 rounded hover:bg-muted/50 group"
        data-testid={`combo-layer-${index}`}
      >
        <GripVertical className="h-3 w-3 text-muted-foreground cursor-grab" />

        <CollapsibleTrigger asChild>
          <button className="flex items-center gap-1 flex-1 text-left text-xs">
            {open ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
            <span className="font-medium">
              Layer {index + 1}
              <span className="ml-1 text-muted-foreground">
                ({layer.type}{layer.secondary_y ? ', 2nd Y' : ''})
              </span>
            </span>
          </button>
        </CollapsibleTrigger>

        <div className="flex items-center gap-0.5">
          <Button
            variant="ghost"
            size="sm"
            className="h-5 w-5 p-0 opacity-0 group-hover:opacity-100"
            onClick={onMoveUp}
            disabled={index === 0}
            data-testid={`combo-layer-move-up-${index}`}
            aria-label={`Move layer ${index + 1} up`}
          >
            <ArrowUp className="h-3 w-3" />
          </Button>
          <Button
            variant="ghost"
            size="sm"
            className="h-5 w-5 p-0 opacity-0 group-hover:opacity-100"
            onClick={onMoveDown}
            disabled={index === totalLayers - 1}
            data-testid={`combo-layer-move-down-${index}`}
            aria-label={`Move layer ${index + 1} down`}
          >
            <ArrowDown className="h-3 w-3" />
          </Button>
          <Button
            variant="ghost"
            size="sm"
            className="h-5 w-5 p-0 opacity-0 group-hover:opacity-100"
            onClick={onRemove}
            data-testid={`combo-layer-remove-${index}`}
            aria-label={`Remove layer ${index + 1}`}
          >
            <Trash2 className="h-3 w-3 text-destructive" />
          </Button>
        </div>
      </div>

      <CollapsibleContent className="pl-4 pb-2 space-y-2">
        {/* Mark type */}
        <div className="flex items-center gap-2">
          <Label className="text-xs w-16">Type</Label>
          <Select
            value={layer.type}
            onValueChange={(v) => onChange({ ...layer, type: v as ComboLayer['type'] })}
          >
            <SelectTrigger className="h-7 text-xs flex-1" data-testid={`layer-type-${index}`}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {MARK_TYPES.map(mt => (
                <SelectItem key={mt.value} value={mt.value}>{mt.label}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        {/* Y measure (drag-drop field well) */}
        <FieldWell
          slotName={`layer-${index}-y`}
          slotSpec={ySlot}
          values={layer.y}
          onAdd={(expr) => onChange({ ...layer, y: expr })}
          onRemove={() => onChange({ ...layer, y: null })}
          onClear={() => onChange({ ...layer, y: null })}
          tables={tables}
        />

        {/* Secondary Y toggle */}
        <div className="flex items-center justify-between gap-2">
          <Label className="text-xs">Secondary Y Axis</Label>
          <Switch
            checked={layer.secondary_y}
            onCheckedChange={(v) => onChange({ ...layer, secondary_y: v })}
            data-testid={`layer-secondary-y-${index}`}
          />
        </div>

        {/* Optional color encoding */}
        <FieldWell
          slotName={`layer-${index}-color`}
          slotSpec={colorSlot}
          values={layer.color ?? null}
          onAdd={(expr) => onChange({ ...layer, color: expr })}
          onRemove={() => onChange({ ...layer, color: null })}
          onClear={() => onChange({ ...layer, color: null })}
          tables={tables}
        />

        {/* Layer name override */}
        <div className="flex items-center gap-2">
          <Label className="text-xs w-16">Name</Label>
          <input
            type="text"
            className="h-7 text-xs flex-1 border rounded px-2"
            placeholder="(auto from Y measure)"
            value={layer.name || ''}
            onChange={(e) => onChange({ ...layer, name: e.target.value || undefined })}
            data-testid={`layer-name-${index}`}
          />
        </div>

        {/* Per-layer format options */}
        <Collapsible>
          <CollapsibleTrigger asChild>
            <Button variant="ghost" size="sm" className="h-6 text-[10px] px-1 w-full justify-start">
              Format Options
            </Button>
          </CollapsibleTrigger>
          <CollapsibleContent>
            <LayerFormatPanel
              layerType={layer.type}
              format={layer.format}
              onUpdate={handleFormatUpdate}
            />
          </CollapsibleContent>
        </Collapsible>
      </CollapsibleContent>
    </Collapsible>
  )
}

/* ── Main LayerEditor ──────────────────────────────────────────── */

interface LayerEditorProps {
  layers: ComboLayer[]
  tables?: Array<{ name: string; columns: string[] }>
  onChange: (layers: ComboLayer[]) => void
  layoutMode?: 'overlay' | 'stacked'
  onLayoutModeChange?: (mode: 'overlay' | 'stacked') => void
}

export function LayerEditor({ layers, tables, onChange, layoutMode = 'overlay', onLayoutModeChange }: LayerEditorProps) {
  const addLayer = useCallback(() => {
    const newLayer: ComboLayer = {
      type: 'bar',
      y: null,
      secondary_y: false,
      format: {},
    }
    onChange([...layers, newLayer])
  }, [layers, onChange])

  const updateLayer = useCallback((index: number, updated: ComboLayer) => {
    const next = [...layers]
    next[index] = updated
    onChange(next)
  }, [layers, onChange])

  const removeLayer = useCallback((index: number) => {
    const next = layers.filter((_, i) => i !== index)
    onChange(next)
  }, [layers, onChange])

  const moveLayer = useCallback((fromIndex: number, toIndex: number) => {
    if (toIndex < 0 || toIndex >= layers.length) return
    const next = [...layers]
    const [moved] = next.splice(fromIndex, 1)
    next.splice(toIndex, 0, moved)
    onChange(next)
  }, [layers, onChange])

  return (
    <div className="space-y-1" data-testid="layer-editor">
      <div className="flex items-center justify-between">
        <Label className="text-xs font-medium">Layers</Label>
        <Button
          variant="ghost"
          size="sm"
          className="h-6 text-xs px-2 gap-1"
          onClick={addLayer}
          data-testid="add-combo-layer"
        >
          <Plus className="h-3 w-3" />
          Add Layer
        </Button>
      </div>

      {/* Layout mode toggle */}
      {onLayoutModeChange && (
        <div className="flex items-center justify-between gap-2 px-1" data-testid="layout-mode-toggle">
          <Label className="text-xs">Layout</Label>
          <Select
            value={layoutMode}
            onValueChange={(v) => onLayoutModeChange(v as 'overlay' | 'stacked')}
          >
            <SelectTrigger className="h-7 text-xs w-[110px]" data-testid="layout-mode-select">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="overlay">Overlay</SelectItem>
              <SelectItem value="stacked">Stacked</SelectItem>
            </SelectContent>
          </Select>
        </div>
      )}

      {layers.length === 0 && (
        <p className="text-[10px] text-muted-foreground px-1">
          No layers configured. Add a layer or use the Y field well for auto mode.
        </p>
      )}

      <div className="space-y-0.5">
        {layers.map((layer, index) => (
          <LayerCard
            key={index}
            layer={layer}
            index={index}
            totalLayers={layers.length}
            tables={tables}
            onChange={(updated) => updateLayer(index, updated)}
            onRemove={() => removeLayer(index)}
            onMoveUp={() => moveLayer(index, index - 1)}
            onMoveDown={() => moveLayer(index, index + 1)}
          />
        ))}
      </div>
    </div>
  )
}

import { useMemo, useState, type ComponentType } from 'react'
import {
  Activity,
  AlertTriangle,
  ArrowUpDown,
  Filter,
  Image,
  Info,
  Layers,
  MessageSquare,
  MoreVertical,
  MousePointer2,
  Paintbrush,
  SlidersHorizontal,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import type { VisualInfo } from '@/lib/api'

type LooseRecord = Record<string, unknown>

type SidecarVisual = VisualInfo & {
  visual_header?: LooseRecord
  visual_actions?: unknown[]
  container_format?: LooseRecord
  selection_state?: LooseRecord
  slicer_state?: LooseRecord
  static_asset?: LooseRecord
  static_resources?: unknown[]
  analytics?: unknown[]
  native_calcs?: unknown[]
  sparklines?: unknown[]
  conditional_formatting?: unknown[]
  table_matrix_format?: LooseRecord
  tooltip?: LooseRecord
  documentation_parameters?: LooseRecord[]
}

interface SidecarBadgeItem {
  id: string
  label: string
  summary: string
  count: number
  icon: ComponentType<{ className?: string }>
  tone?: 'default' | 'warning'
  details: string[]
}

interface PowerBISidecarBadgesProps {
  visual: VisualInfo
  pages?: Array<{ id: string; title?: string; name?: string }>
}

export function PowerBISidecarBadges({ visual, pages = [] }: PowerBISidecarBadgesProps) {
  const items = useMemo(() => buildSidecarItems(visual as SidecarVisual, pages), [visual, pages])
  const [activeId, setActiveId] = useState<string | null>(null)

  if (items.length === 0) return null

  const active = items.find(item => item.id === activeId) ?? null
  const ActiveIcon = active?.icon

  return (
    <>
      <div
        className="absolute bottom-1 left-1 z-[45] flex max-w-[calc(100%-0.5rem)] flex-wrap gap-1 pointer-events-auto"
        data-testid={`powerbi-sidecar-badges-${visual.id}`}
      >
        {items.map(item => {
          const Icon = item.icon
          const isActive = activeId === item.id
          return (
            <button
              key={item.id}
              type="button"
              className={cn(
                'inline-flex h-6 min-w-6 items-center justify-center gap-1 rounded border px-1 text-[10px] shadow-sm backdrop-blur-sm transition-colors',
                item.tone === 'warning'
                  ? 'border-amber-300 bg-amber-50/95 text-amber-800 hover:bg-amber-100 dark:border-amber-700 dark:bg-amber-950/90 dark:text-amber-200'
                  : 'border-border/70 bg-background/95 text-muted-foreground hover:bg-muted',
                isActive && 'ring-1 ring-primary text-foreground'
              )}
              title={`${item.label}: ${item.summary}`}
              aria-label={`${item.label}: ${item.summary}`}
              data-testid={`powerbi-sidecar-badge-${item.id}`}
              data-sidecar-kind={item.id}
              data-sidecar-count={item.count}
              onClick={(event) => {
                event.stopPropagation()
                setActiveId(isActive ? null : item.id)
              }}
            >
              <Icon className="h-3.5 w-3.5" />
              <span className="tabular-nums">{item.count}</span>
            </button>
          )
        })}
      </div>

      {active && ActiveIcon && (
        <div
          className="absolute bottom-8 left-1 z-[46] w-[min(320px,calc(100%-0.5rem))] rounded border bg-popover/98 p-2 text-popover-foreground shadow-lg pointer-events-auto"
          data-testid={`powerbi-sidecar-detail-${visual.id}`}
          data-sidecar-kind={active.id}
          onClick={(event) => event.stopPropagation()}
        >
          <div className="mb-1 flex items-center gap-1.5 text-xs font-medium">
            <ActiveIcon className="h-3.5 w-3.5" />
            <span>{active.label}</span>
            <span className="ml-auto rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">
              {active.count}
            </span>
          </div>
          <p className="mb-1.5 text-[11px] leading-snug text-muted-foreground">{active.summary}</p>
          <div className="max-h-28 overflow-auto space-y-1 text-[10px] leading-snug">
            {active.details.slice(0, 5).map((detail, index) => (
              <div key={`${active.id}-${index}`} className="rounded bg-muted/40 px-1.5 py-1">
                {detail}
              </div>
            ))}
          </div>
        </div>
      )}
    </>
  )
}

function buildSidecarItems(visual: SidecarVisual, pages: Array<{ id: string; title?: string; name?: string }>): SidecarBadgeItem[] {
  const items: SidecarBadgeItem[] = []
  const looseVisual = visual as unknown as LooseRecord
  const format = asRecord(visual.format)
  const staticContent = asRecord(visual.static_content)
  const documentationParameters = asArray(visual.documentation_parameters).filter(isRecord)

  addItem(items, {
    id: 'visual-header',
    label: 'Visual Header',
    payload: visual.visual_header,
    icon: MoreVertical,
    summary: summarizeVisualHeader(visual.visual_header),
  })

  const selectorRows = selectorFormatRows(format)
  if (selectorRows.length > 0) {
    items.push({
      id: 'selector-formatting',
      label: 'Selector Formatting',
      summary: `${selectorRows.length} selector-bound format row${selectorRows.length === 1 ? '' : 's'} preserved`,
      count: selectorRows.length,
      icon: Paintbrush,
      details: selectorRows.map(previewValue),
    })
  }

  const slicerFormatKeys = Object.keys(format || {}).filter(key => key.startsWith('slicer'))
  if (hasPayload(visual.slicer_state) || hasPayload(visual.slicer_config) || slicerFormatKeys.length > 0) {
    const slicerDetails = [visual.slicer_state, visual.slicer_config, pickKeys(format, slicerFormatKeys)]
      .filter(hasPayload)
      .map(previewValue)
    items.push({
      id: 'slicer-mode',
      label: 'Slicer Mode',
      summary: summarizeSlicer(visual.slicer_state, visual.slicer_config, slicerFormatKeys),
      count: countPayload(visual.slicer_state) + countPayload(visual.slicer_config) + slicerFormatKeys.length,
      icon: SlidersHorizontal,
      details: slicerDetails,
    })
  }

  if (hasPayload(visual.static_asset) || hasPayload(visual.static_resources)) {
    const details = [visual.static_asset, visual.static_resources].filter(hasPayload).map(previewValue)
    items.push({
      id: 'static-asset',
      label: 'Static Asset',
      summary: summarizeStaticAsset(visual.static_asset, visual.static_resources),
      count: countPayload(visual.static_asset) + countPayload(visual.static_resources),
      icon: Image,
      details,
    })
  }

  if (hasPayload(visual.visual_actions) || hasPayload(staticContent?.action)) {
    const details = [visual.visual_actions, staticContent?.action].filter(hasPayload).map(previewValue)
    items.push({
      id: 'actions',
      label: 'Actions',
      summary: summarizeActions(visual.visual_actions, staticContent?.action),
      count: Math.max(1, countPayload(visual.visual_actions) + countPayload(staticContent?.action)),
      icon: MousePointer2,
      details,
    })
  }

  if (hasPayload(visual.analytics)) {
    items.push({
      id: 'analytics',
      label: 'Analytics',
      summary: `${summarizeRows(visual.analytics, 'analytics object')}; preserved unless it maps to a supported Plotly analytic`,
      count: countPayload(visual.analytics),
      icon: Activity,
      tone: 'warning',
      details: asArray(visual.analytics).map(previewValue),
    })
  }

  if (hasPayload(visual.native_calcs) || hasPayload(visual.sparklines)) {
    items.push({
      id: 'native-calcs',
      label: 'Visual Calc/Sparkline',
      summary: 'Power BI visual calculation and sparkline metadata preserved; executable only when an expression/time-series payload is present',
      count: countPayload(visual.native_calcs) + countPayload(visual.sparklines),
      icon: Activity,
      tone: 'warning',
      details: [visual.native_calcs, visual.sparklines].filter(hasPayload).map(previewValue),
    })
  }

  const filterRows = documentationParameters.filter(parameterSurfaceEquals('filter'))
  if (filterRows.length > 0 || hasPayload(looseVisual.visual_filters)) {
    const details = [...filterRows.map(previewValue), previewValue(looseVisual.visual_filters)].filter(Boolean)
    items.push({
      id: 'filters',
      label: 'Filters',
      summary: filterRows.length > 0 ? `${filterRows.length} imported filter parameter${filterRows.length === 1 ? '' : 's'}` : 'visual filter sidecar preserved',
      count: filterRows.length || countPayload(looseVisual.visual_filters),
      icon: Filter,
      details,
    })
  }

  addItem(items, {
    id: 'container-chrome',
    label: 'Container Chrome',
    payload: visual.container_format,
    icon: Layers,
    summary: summarizeObjectPayload(visual.container_format, 'container chrome object'),
  })

  addItem(items, {
    id: 'selection',
    label: 'Selection',
    payload: visual.selection_state,
    icon: ArrowUpDown,
    summary: summarizeSelection(visual.selection_state),
  })

  addItem(items, {
    id: 'table-matrix-format',
    label: 'Table/Matrix Format',
    payload: visual.table_matrix_format,
    icon: Layers,
    summary: summarizeObjectPayload(visual.table_matrix_format, 'table or matrix format object'),
  })

  if (hasPayload(visual.tooltip) || visual.tooltip_page_id) {
    items.push({
      id: 'tooltip',
      label: 'Tooltip',
      summary: summarizeTooltip(visual.tooltip, visual.tooltip_page_id, pages),
      count: Math.max(1, countPayload(visual.tooltip)),
      icon: MessageSquare,
      tone: tooltipMissing(visual.tooltip_page_id, pages) ? 'warning' : 'default',
      details: [previewValue(visual.tooltip), visual.tooltip_page_id ? `tooltip_page_id: ${visual.tooltip_page_id}` : ''].filter(Boolean),
    })
  }

  if (hasPayload(visual.unsupported_visual) || visual.render_blocked?.reason === 'unsupported_power_bi_visual') {
    items.push({
      id: 'unsupported-visual',
      label: 'Unsupported Visual',
      summary: summarizeUnsupported(visual),
      count: 1,
      icon: AlertTriangle,
      tone: 'warning',
      details: [visual.unsupported_visual, visual.render_blocked].filter(hasPayload).map(previewValue),
    })
  }

  if (hasPayload(visual.conditional_formatting)) {
    items.push({
      id: 'conditional-formatting',
      label: 'Conditional Formatting',
      summary: summarizeRows(visual.conditional_formatting, 'conditional format row'),
      count: countPayload(visual.conditional_formatting),
      icon: Paintbrush,
      details: asArray(visual.conditional_formatting).map(previewValue),
    })
  }

  if (items.length === 0 && documentationParameters.length > 0) {
    items.push({
      id: 'documentation-parameters',
      label: 'Documentation Parameters',
      summary: `${documentationParameters.length} imported parameter${documentationParameters.length === 1 ? '' : 's'} preserved`,
      count: documentationParameters.length,
      icon: Info,
      details: documentationParameters.slice(0, 5).map(previewValue),
    })
  }

  return items
}

function addItem(
  items: SidecarBadgeItem[],
  item: Omit<SidecarBadgeItem, 'count' | 'details'> & { payload: unknown },
) {
  if (!hasPayload(item.payload)) return
  items.push({
    id: item.id,
    label: item.label,
    summary: item.summary,
    count: countPayload(item.payload),
    icon: item.icon,
    tone: item.tone,
    details: [previewValue(item.payload)],
  })
}

function selectorFormatRows(format: LooseRecord | null): unknown[] {
  if (!format) return []
  const rows: unknown[] = []
  rows.push(...asArray(format.datapoint_selectors))
  rows.push(...asArray(format.visual_selector_objects))
  rows.push(...asArray(format.selector_formatting))
  rows.push(...asArray(format.documentation_properties).filter(row => {
    if (!isRecord(row)) return false
    const selector = row.selector ?? row.Selector
    return typeof selector === 'string' && selector.trim().length > 0
  }))
  return rows
}

function summarizeVisualHeader(payload: unknown): string {
  const record = asRecord(payload)
  const icons = asRecord(record?.icons)
  const enabled = icons ? Object.entries(icons).filter(([, value]) => value === true).map(([key]) => key) : []
  if (enabled.length > 0) return `${enabled.length} imported header icon toggle${enabled.length === 1 ? '' : 's'}`
  return summarizeObjectPayload(payload, 'visual header property')
}

function summarizeSlicer(slicerState: unknown, slicerConfig: unknown, slicerFormatKeys: string[]): string {
  const state = asRecord(slicerState)
  const config = asRecord(slicerConfig)
  const mode = state?.slicer_mode ?? state?.mode ?? config?.mode ?? config?.style
  const modeText = mode ? `mode ${String(mode)}` : 'mode sidecar'
  const suffix = slicerFormatKeys.length > 0 ? `, ${slicerFormatKeys.length} format key${slicerFormatKeys.length === 1 ? '' : 's'}` : ''
  return `${modeText}${suffix}`
}

function summarizeStaticAsset(staticAsset: unknown, staticResources: unknown): string {
  const asset = asRecord(staticAsset)
  const props = asRecord(asset?.properties)
  const visualType = asset?.visual_type ? String(asset.visual_type) : 'static visual'
  const resourceCount = countPayload(staticResources)
  const detail = props?.rotation != null ? `rotation ${String(props.rotation)}` : props?.shape_type ? `shape ${String(props.shape_type)}` : ''
  return [visualType, detail, resourceCount > 0 ? `${resourceCount} resource${resourceCount === 1 ? '' : 's'}` : ''].filter(Boolean).join(', ')
}

function summarizeActions(actions: unknown, fallbackAction: unknown): string {
  const first = asArray(actions).find(isRecord) ?? asRecord(fallbackAction)
  if (!first) return 'action metadata preserved'
  const type = first.type ? String(first.type) : 'action'
  const target = isRecord(first.target) ? (first.target.id ?? first.target.url ?? first.target.type) : undefined
  return target ? `${type} -> ${String(target)}` : type
}

function summarizeRows(rows: unknown, noun: string): string {
  const count = countPayload(rows)
  return `${count} ${noun}${count === 1 ? '' : 's'} preserved`
}

function summarizeObjectPayload(payload: unknown, noun: string): string {
  const record = asRecord(payload)
  const objects = asRecord(record?.objects)
  if (objects) {
    const keys = Object.keys(objects)
    return `${keys.length} ${noun}${keys.length === 1 ? '' : 's'}: ${keys.slice(0, 3).join(', ')}`
  }
  const count = countPayload(payload)
  return `${count} ${noun}${count === 1 ? '' : 's'} preserved`
}

function summarizeSelection(payload: unknown): string {
  const record = asRecord(payload)
  if (record?.strict_single_select === true) return 'strict single-select imported'
  return summarizeObjectPayload(payload, 'selection property')
}

function summarizeTooltip(payload: unknown, tooltipPageId: string | null | undefined, pages: Array<{ id: string; title?: string; name?: string }>): string {
  if (!tooltipPageId) return summarizeObjectPayload(payload, 'tooltip property')
  const page = pages.find(candidate => candidate.id === tooltipPageId)
  if (page) return `tooltip page ${page.title || page.name || tooltipPageId}`
  return `missing tooltip page ${tooltipPageId}`
}

function tooltipMissing(tooltipPageId: string | null | undefined, pages: Array<{ id: string }>): boolean {
  return !!tooltipPageId && !pages.some(page => page.id === tooltipPageId)
}

function summarizeUnsupported(visual: SidecarVisual): string {
  const sourceType = visual.unsupported_visual?.source_visual_type
  if (sourceType) return `${sourceType} preserved as blocked metadata`
  return 'unsupported visual preserved as blocked metadata'
}

function parameterSurfaceEquals(surface: string) {
  return (parameter: LooseRecord) => {
    const value = parameter.Surface ?? parameter.surface
    return typeof value === 'string' && value.toLowerCase() === surface.toLowerCase()
  }
}

function pickKeys(record: LooseRecord | null, keys: string[]): LooseRecord {
  if (!record) return {}
  return Object.fromEntries(keys.map(key => [key, record[key]]))
}

function countPayload(payload: unknown): number {
  if (!hasPayload(payload)) return 0
  if (Array.isArray(payload)) return payload.length
  if (!isRecord(payload)) return 1
  const sourceParameters = asArray(payload.source_parameters)
  if (sourceParameters.length > 0) return sourceParameters.length
  const objects = asRecord(payload.objects)
  if (objects) return Object.keys(objects).length
  return Object.keys(payload).filter(key => payload[key] !== undefined && payload[key] !== null && key !== 'source_parameters').length || 1
}

function hasPayload(payload: unknown): boolean {
  if (payload == null) return false
  if (Array.isArray(payload)) return payload.length > 0
  if (isRecord(payload)) return Object.keys(payload).length > 0
  return true
}

function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : []
}

function isRecord(value: unknown): value is LooseRecord {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function asRecord(value: unknown): LooseRecord | null {
  return isRecord(value) ? value : null
}

function previewValue(value: unknown): string {
  if (!hasPayload(value)) return ''
  if (typeof value === 'string') return value
  try {
    const text = JSON.stringify(value)
    return text.length > 220 ? `${text.slice(0, 217)}...` : text
  } catch {
    return String(value)
  }
}
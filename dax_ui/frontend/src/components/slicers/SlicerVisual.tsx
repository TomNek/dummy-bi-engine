import { useState, useEffect, useCallback, useMemo, useRef } from 'react'
import type { CSSProperties } from 'react'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Checkbox } from '@/components/ui/checkbox'
import { ScrollArea } from '@/components/ui/scroll-area'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Loader2, Search, X, ChevronDown, ChevronRight, Calendar, ArrowUpDown, Check } from 'lucide-react'
import { useSlicers, useFilters } from '@/hooks'
import { useSelectionStateStore } from '@/stores/selection-state-store'
import { SelectionStateItem, type SelectionState } from './SelectionStateItem'
import { getReportResourceUrl, type SlicerDef, type SlicerInstance, type SlicerSelection } from '@/lib/api'
import { useAppStore } from '@/stores'
import { APPLY_ALL_SLICERS_EVENT, CLEAR_ALL_SLICERS_EVENT } from '@/lib/slicer-events'

export type SlicerSortMode = 'alphabetical' | 'relevance'
type InputSlicerOperator =
  | 'in'
  | 'not_in'
  | 'contains'
  | 'contains_any'
  | 'contains_all'
  | 'notcontains_any'
  | 'startswith'
  | 'startswith_any'
  | 'notstartswith_any'
  | 'endswith'
  | 'endswith_any'
  | 'notendswith_any'
  | '='
  | '!='
  | '>'
  | '>='
  | '<'
  | '<='

const INPUT_SLICER_OPERATORS: Array<{ value: InputSlicerOperator; label: string; multi: boolean }> = [
  { value: 'in', label: 'Is any', multi: true },
  { value: 'not_in', label: 'Is not any', multi: true },
  { value: 'contains', label: 'Contains', multi: false },
  { value: 'contains_any', label: 'Contains any', multi: true },
  { value: 'contains_all', label: 'Contains all', multi: true },
  { value: 'notcontains_any', label: 'Does not contain any', multi: true },
  { value: 'startswith', label: 'Starts with', multi: false },
  { value: 'startswith_any', label: 'Starts with any', multi: true },
  { value: 'notstartswith_any', label: 'Does not start with any', multi: true },
  { value: 'endswith', label: 'Ends with', multi: false },
  { value: 'endswith_any', label: 'Ends with any', multi: true },
  { value: 'notendswith_any', label: 'Does not end with any', multi: true },
  { value: '=', label: 'Equals', multi: false },
  { value: '!=', label: 'Is not', multi: false },
  { value: '>', label: 'Greater than', multi: false },
  { value: '>=', label: 'Greater/equal', multi: false },
  { value: '<', label: 'Less than', multi: false },
  { value: '<=', label: 'Less/equal', multi: false },
]

interface SlicerVisualProps {
  instance: SlicerInstance
  def: SlicerDef
  className?: string
  onSelectionChange?: (values: unknown[]) => void
}

function setsEqual(left: Set<string>, right: Set<string>): boolean {
  if (left.size !== right.size) return false
  for (const value of left) {
    if (!right.has(value)) return false
  }
  return true
}

function parsePastedSlicerValues(raw: string): string[] {
  return Array.from(new Set(
    raw
      .split(/[\n\r\t,;]+/)
      .map(value => value.trim())
      .filter(Boolean)
  ))
}

function slicerRecord(value: unknown): Record<string, unknown> | null {
  return typeof value === 'object' && value !== null && !Array.isArray(value) ? value as Record<string, unknown> : null
}

function slicerValueKey(value: unknown): string {
  const record = slicerRecord(value)
  if (record) {
    const raw = record.value ?? record.key ?? record.id ?? record.label
    if (raw != null) return String(raw)
  }
  return String(value)
}

function slicerValueLabel(value: unknown): string {
  const record = slicerRecord(value)
  if (record) {
    const raw = record.label ?? record.display ?? record.text ?? record.value ?? record.key
    if (raw != null) return String(raw)
  }
  return String(value)
}

function slicerValueDisplayLabel(value: unknown): string {
  const record = slicerRecord(value)
  const label = slicerValueLabel(value)
  const template = record?.item_template ?? record?.itemTemplate ?? record?.label_template ?? record?.labelTemplate ?? record?.template
  if (typeof template !== 'string' || !template.trim()) return label
  const replacements: Record<string, string> = {
    label,
    value: slicerValueKey(value),
    count: record?.count == null ? '' : String(record.count),
    highlight: record?.highlight == null ? '' : String(record.highlight),
  }
  return template.replace(/\{([A-Za-z0-9_]+)\}/g, (match, key) => replacements[key] ?? (record?.[key] == null ? match : String(record[key])))
}

type SlicerImageSource = {
  url?: string
  resource?: string
  fallback: boolean
}

function isDirectImageUrl(raw: string): boolean {
  return /^(data:|blob:|https?:\/\/|\/runtime\/|\/assets\/|\/static\/)/i.test(raw)
}

function slicerValueImageSource(value: unknown, projectPath?: string): SlicerImageSource {
  const record = slicerRecord(value)
  const directRaw = record?.image_url ?? record?.imageUrl ?? record?.url ?? record?.src ?? record?.image
  const direct = typeof directRaw === 'string' ? directRaw.trim() : ''
  if (direct && isDirectImageUrl(direct)) return { url: direct, fallback: true }

  const resourceRaw =
    record?.image_resource ??
    record?.imageResource ??
    record?.resource_id ??
    record?.resourceId ??
    record?.resource ??
    (direct && /\.(bmp|gif|ico|jpe?g|png|svg|webp)$/i.test(direct) ? direct : undefined)
  const resource = typeof resourceRaw === 'string' ? resourceRaw.trim() : ''
  if (resource) {
    return {
      url: getReportResourceUrl(resource, projectPath),
      resource,
      fallback: true,
    }
  }
  return { fallback: false }
}

type SlicerImagePresentation = {
  style: CSSProperties
  fit: string
  position: string
  saturation?: string
}

function pickSlicerImageSetting(record: Record<string, unknown> | null, def: SlicerDef, keys: string[]): unknown {
  for (const key of keys) {
    const raw = record?.[key]
    if (raw != null && String(raw).trim() !== '') return raw
  }
  const defRecord = def as unknown as Record<string, unknown>
  for (const key of keys) {
    const raw = defRecord[key]
    if (raw != null && String(raw).trim() !== '') return raw
  }
  return undefined
}

function normalizeSlicerImageFit(raw: unknown): CSSProperties['objectFit'] {
  const value = String(raw || 'cover').trim().toLowerCase()
  if (value === 'contain' || value === 'fit') return 'contain'
  if (value === 'fill' || value === 'stretch') return 'fill'
  if (value === 'none' || value === 'normal' || value === 'actual') return 'none'
  if (value === 'scale-down' || value === 'scaledown') return 'scale-down'
  return 'cover'
}

function normalizeSlicerImagePosition(raw: unknown): string {
  const value = String(raw || '').trim()
  if (!value) return 'center center'
  const compact = value.replace(/[_-]+/g, ' ').replace(/([a-z])([A-Z])/g, '$1 $2').toLowerCase()
  const tokens = compact.split(/\s+/).filter(Boolean)
  const vertical = tokens.find(token => token === 'top' || token === 'bottom') ?? (tokens.includes('center') ? 'center' : '')
  const horizontal = tokens.find(token => token === 'left' || token === 'right') ?? (tokens.includes('center') ? 'center' : '')
  if (horizontal || vertical) return `${horizontal || 'center'} ${vertical || 'center'}`
  return value
}

function normalizeSlicerCssLength(raw: unknown): string | undefined {
  if (raw == null) return undefined
  if (typeof raw === 'number' && Number.isFinite(raw)) return `${raw}px`
  const value = String(raw).trim()
  if (!value) return undefined
  if (/^-?\d+(\.\d+)?$/.test(value)) return `${value}px`
  return value
}

function normalizeSlicerImageSaturation(raw: unknown): string | undefined {
  if (raw == null || String(raw).trim() === '') return undefined
  if (typeof raw === 'number' && Number.isFinite(raw)) {
    return raw > 3 ? `${raw}%` : String(raw)
  }
  const value = String(raw).trim()
  if (!value) return undefined
  if (value.endsWith('%')) return value
  const numeric = Number(value)
  if (Number.isFinite(numeric)) return numeric > 3 ? `${numeric}%` : value
  return value
}

function slicerValueImagePresentation(value: unknown, def: SlicerDef): SlicerImagePresentation {
  const record = slicerRecord(value)
  const fit = normalizeSlicerImageFit(pickSlicerImageSetting(record, def, ['image_fit', 'imageFit', 'fit', 'object_fit', 'objectFit']))
  const position = normalizeSlicerImagePosition(pickSlicerImageSetting(record, def, ['image_position', 'imagePosition', 'position', 'object_position', 'objectPosition']))
  const saturation = normalizeSlicerImageSaturation(pickSlicerImageSetting(record, def, ['image_saturation', 'imageSaturation', 'saturation']))
  const background = pickSlicerImageSetting(record, def, ['image_background', 'imageBackground', 'image_bg', 'imageBg'])
  const padding = normalizeSlicerCssLength(pickSlicerImageSetting(record, def, ['image_padding', 'imagePadding', 'padding']))
  const style: CSSProperties = {
    objectFit: fit,
    objectPosition: position,
    ...(saturation ? { filter: `saturate(${saturation})` } : {}),
    ...(typeof background === 'string' && background.trim() ? { backgroundColor: background.trim() } : {}),
    ...(padding ? { padding, boxSizing: 'border-box' } : {}),
  }
  return { style, fit: String(fit), position, saturation }
}

type SlicerConditionalPresentation = {
  style?: CSSProperties
  summary?: string
}

function colorFromValue(value: unknown): string | undefined {
  if (typeof value === 'string' && value.trim()) return value.trim()
  const record = slicerRecord(value)
  if (!record) return undefined
  const direct = record.color ?? record.value
  if (typeof direct === 'string' && direct.trim()) return direct.trim()
  const solid = slicerRecord(record.solid)
  if (solid && typeof solid.color === 'string' && solid.color.trim()) return solid.color.trim()
  return undefined
}

function numberOrLength(value: unknown): string | undefined {
  if (typeof value === 'number' && Number.isFinite(value)) return `${value}px`
  if (typeof value !== 'string') return undefined
  const text = value.trim()
  if (!text) return undefined
  return /^-?\d+(\.\d+)?$/.test(text) ? `${text}px` : text
}

function slicerValueConditionalPresentation(value: unknown): SlicerConditionalPresentation {
  const record = slicerRecord(value)
  if (!record) return {}
  const format =
    slicerRecord(record.conditional_format) ??
    slicerRecord(record.conditionalFormat) ??
    slicerRecord(record.item_format) ??
    slicerRecord(record.itemFormat) ??
    slicerRecord(record.format) ??
    slicerRecord(record.style) ??
    record
  const style: CSSProperties = {}
  const background = colorFromValue(format.background ?? format.background_color ?? format.backgroundColor ?? format.fill ?? format.fill_color ?? format.fillColor)
  const foreground = colorFromValue(format.foreground ?? format.color ?? format.text_color ?? format.textColor ?? format.font_color ?? format.fontColor)
  const border = colorFromValue(format.border ?? format.border_color ?? format.borderColor ?? format.outline ?? format.outline_color ?? format.outlineColor)
  const borderWidth = numberOrLength(format.border_width ?? format.borderWidth ?? format.outline_weight ?? format.outlineWeight)
  const radius = numberOrLength(format.border_radius ?? format.borderRadius)
  const opacity = typeof format.opacity === 'number' ? format.opacity : Number(format.opacity)
  if (background) style.backgroundColor = background
  if (foreground) style.color = foreground
  if (border) {
    style.borderColor = border
    style.borderStyle = 'solid'
    style.borderWidth = borderWidth || '1px'
  } else if (borderWidth) {
    style.borderWidth = borderWidth
    style.borderStyle = 'solid'
  }
  if (radius) style.borderRadius = radius
  if (Number.isFinite(opacity)) style.opacity = Math.max(0, Math.min(1, opacity))
  if (format.bold != null) style.fontWeight = String(format.bold).toLowerCase() === 'true' ? 600 : 400
  if (format.font_weight != null || format.fontWeight != null) style.fontWeight = String(format.font_weight ?? format.fontWeight)
  if (format.italic != null) style.fontStyle = String(format.italic).toLowerCase() === 'true' ? 'italic' : 'normal'
  if (format.font_style != null || format.fontStyle != null) style.fontStyle = String(format.font_style ?? format.fontStyle)
  const entries = Object.entries(style)
  if (entries.length === 0) return {}
  return {
    style,
    summary: entries.map(([key, val]) => `${key}:${String(val)}`).join(';'),
  }
}

function slicerImageFallbackText(label: string): string {
  return label
    .split(/\s+/)
    .map(part => part.charAt(0))
    .join('')
    .slice(0, 2)
    .toUpperCase() || '?'
}

function SlicerImageMedia({
  image,
  label,
  presentation,
  className,
  testId,
}: {
  image: SlicerImageSource
  label: string
  presentation: SlicerImagePresentation
  className: string
  testId: string
}) {
  const [failed, setFailed] = useState(false)
  useEffect(() => {
    setFailed(false)
  }, [image.url])
  if (image.url && !failed) {
    return (
      <img
        src={image.url}
        alt=""
        className={className}
        style={presentation.style}
        loading="lazy"
        onError={() => setFailed(true)}
        data-testid={testId}
        data-image-fit={presentation.fit}
        data-image-position={presentation.position}
        data-image-saturation={presentation.saturation}
        data-image-resource={image.resource}
      />
    )
  }
  if (!image.fallback) return null
  return (
    <span
      className={cn(className, 'flex items-center justify-center border bg-muted text-[9px] font-semibold text-muted-foreground')}
      style={presentation.style}
      data-testid={`${testId}-fallback`}
      data-image-fit={presentation.fit}
      data-image-position={presentation.position}
      data-image-saturation={presentation.saturation}
      data-image-resource={image.resource}
      data-image-fallback="true"
    >
      {slicerImageFallbackText(label)}
    </span>
  )
}

function slicerValueIsLeaf(value: unknown): boolean {
  const record = slicerRecord(value)
  if (!record) return true
  const rawLeaf = record.is_leaf ?? record.isLeaf ?? record.leaf
  if (typeof rawLeaf === 'boolean') return rawLeaf
  const rawChildren = record.has_children ?? record.hasChildren
  if (typeof rawChildren === 'boolean') return !rawChildren
  const childrenCount = record.children_count ?? record.childrenCount
  if (typeof childrenCount === 'number') return childrenCount <= 0
  if (typeof childrenCount === 'string' && childrenCount.trim()) {
    const parsed = Number(childrenCount)
    if (Number.isFinite(parsed)) return parsed <= 0
  }
  return true
}

const HIERARCHY_PATH_SEPARATOR = '\u001f'

type SlicerHierarchyInfo = {
  path: string[]
  pathKey: string
  parentPathKey: string | null
  depth: number
}

function splitHierarchyPath(raw: unknown): string[] {
  if (Array.isArray(raw)) {
    return raw.map(part => String(part).trim()).filter(Boolean)
  }
  if (typeof raw === 'string' && raw.trim()) {
    const delimiter = raw.includes(HIERARCHY_PATH_SEPARATOR)
      ? HIERARCHY_PATH_SEPARATOR
      : raw.includes('|')
        ? '|'
        : raw.includes('>')
          ? '>'
          : ''
    return delimiter
      ? raw.split(delimiter).map(part => part.trim()).filter(Boolean)
      : [raw.trim()]
  }
  return []
}

function slicerHierarchyInfo(value: unknown): SlicerHierarchyInfo {
  const record = slicerRecord(value)
  const label = slicerValueLabel(value) || slicerValueKey(value)
  let path = splitHierarchyPath(record?.hierarchy_path ?? record?.hierarchyPath ?? record?.path)
  const parent = record?.parent ?? record?.parent_value ?? record?.parentValue
  if (path.length === 0 && parent != null && String(parent).trim()) {
    path = [String(parent).trim(), label]
  }
  if (path.length === 0) path = [label]
  const rawDepth = record?.depth ?? record?.level ?? record?.hierarchy_level ?? record?.hierarchyLevel
  const numericDepth = typeof rawDepth === 'number'
    ? rawDepth
    : typeof rawDepth === 'string' && rawDepth.trim()
      ? Number(rawDepth)
      : NaN
  const depth = Number.isFinite(numericDepth) ? Math.max(0, numericDepth) : Math.max(0, path.length - 1)
  const pathKey = path.join(HIERARCHY_PATH_SEPARATOR)
  const parentPathKey = path.length > 1 ? path.slice(0, -1).join(HIERARCHY_PATH_SEPARATOR) : null
  return { path, pathKey, parentPathKey, depth }
}

function hasHierarchyTreeMetadata(value: unknown): boolean {
  const record = slicerRecord(value)
  if (!record) return false
  const path = splitHierarchyPath(record.hierarchy_path ?? record.hierarchyPath ?? record.path)
  if (path.length > 1) return true
  if (record.parent != null || record.parent_value != null || record.parentValue != null) return true
  const rawDepth = record.depth ?? record.level ?? record.hierarchy_level ?? record.hierarchyLevel
  if (typeof rawDepth === 'number') return rawDepth > 0
  if (typeof rawDepth === 'string' && rawDepth.trim()) {
    const parsed = Number(rawDepth)
    return Number.isFinite(parsed) && parsed > 0
  }
  return false
}

function normalizeInputOperator(value: unknown): InputSlicerOperator {
  const normalized = String(value || '').trim().toLowerCase()
  if (normalized === 'is-any' || normalized === 'isany' || normalized === 'any') return 'in'
  if (normalized === 'not-in' || normalized === 'notin' || normalized === 'is-not-any' || normalized === 'isnotany') return 'not_in'
  if (normalized === 'equals' || normalized === 'eq') return '='
  if (normalized === 'not-equals' || normalized === 'neq') return '!='
  if (normalized === 'contains-any' || normalized === 'containsany') return 'contains_any'
  if (normalized === 'contains-all' || normalized === 'containsall') return 'contains_all'
  if (normalized === 'not-contains' || normalized === 'notcontains' || normalized === 'does-not-contain-any' || normalized === 'doesnotcontainany') return 'notcontains_any'
  if (normalized === 'starts-with' || normalized === 'startswith') return 'startswith'
  if (normalized === 'starts-with-any' || normalized === 'startswithany') return 'startswith_any'
  if (normalized === 'not-startswith' || normalized === 'notstartswith' || normalized === 'does-not-start-with-any' || normalized === 'doesnotstartwithany') return 'notstartswith_any'
  if (normalized === 'ends-with' || normalized === 'endswith') return 'endswith'
  if (normalized === 'ends-with-any' || normalized === 'endswithany') return 'endswith_any'
  if (normalized === 'not-endswith' || normalized === 'notendswith' || normalized === 'does-not-end-with-any' || normalized === 'doesnotendwithany') return 'notendswith_any'
  return INPUT_SLICER_OPERATORS.some(option => option.value === normalized) ? normalized as InputSlicerOperator : 'contains'
}

function operatorAllowsMultiple(operator: InputSlicerOperator): boolean {
  return INPUT_SLICER_OPERATORS.find(option => option.value === operator)?.multi === true
}

function relativeSelectionSummary(selection: SlicerSelection | undefined): { label: string; detail: string } | null {
  if (!selection || String(selection.mode || '').toLowerCase() !== 'relative') return null
  const direction = String(selection.direction || 'last').toLowerCase()
  const count = Number(selection.count || 1)
  const unit = String(selection.unit || 'day').toLowerCase()
  const window = String(selection.window || 'rolling').toLowerCase()
  const isTimeUnit = unit === 'minute' || unit === 'hour'
  const includeCurrent = isTimeUnit
    ? selection.include_current !== false && selection.include_today !== false
    : selection.include_today !== false
  const unitLabel = count === 1 ? unit : `${unit}s`
  const directionLabel = direction === 'this'
    ? 'This'
    : direction === 'next'
      ? 'Next'
      : 'Last'
  const label = direction === 'this' ? `${directionLabel} ${unit}` : `${directionLabel} ${count} ${unitLabel}`
  const detailParts = [
    isTimeUnit ? 'Shared anchor time' : window === 'calendar' ? 'Calendar window' : 'Rolling window',
    includeCurrent ? (isTimeUnit ? 'includes current time' : 'includes today') : (isTimeUnit ? 'excludes current time' : 'excludes today'),
  ]
  if (selection.anchor) detailParts.push(`anchor ${selection.anchor}`)
  return { label, detail: detailParts.join(' - ') }
}

export function SlicerVisual({ instance, def, className, onSelectionChange }: SlicerVisualProps) {
  const { fetchValues } = useSlicers()
  const { addSlicerFilter, removeSlicerFilter } = useFilters()
  const projectPath = useAppStore(s => s.projectPath)
  const autoApply = def.auto_apply !== false
  const forceSelection = def.force_selection === true
  
  // Selection state engine (Phase 23D) — per-field possible/excluded
  const fieldKey = `${def.column.table}.${def.column.column}`
  const fieldState = useSelectionStateStore(s => s.fields[fieldKey])
  const isInput = def.type === 'input'
  const isPureInput = isInput && (def.input_mode === 'input' || (!def.column.table && !def.column.column))
  
  // Phase 23F: sort mode and count display toggles
  const [sortMode, setSortMode] = useState<SlicerSortMode>('alphabetical')
  const [showCounts, setShowCounts] = useState(false)
  
  // Keyboard navigation refs (Phase 23F)
  const itemRefs = useRef<(HTMLDivElement | null)[]>([])
  const [focusedIndex, setFocusedIndex] = useState(-1)
  
  const [values, setValues] = useState<unknown[]>([])
  const [selectedValues, setSelectedValues] = useState<Set<string>>(new Set())
  const [committedValues, setCommittedValues] = useState<Set<string>>(new Set())
  const [inputValue, setInputValue] = useState('')
  const [editingInputPillIndex, setEditingInputPillIndex] = useState<number | null>(null)
  const [editingInputPillValue, setEditingInputPillValue] = useState('')
  const [inputOperator, setInputOperator] = useState<InputSlicerOperator>(() => normalizeInputOperator(def.filter_operator))
  const [pasteDraft, setPasteDraft] = useState('')
  const [searchQuery, setSearchQuery] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [collapsed, setCollapsed] = useState(false)
  const [expandedHierarchyKeys, setExpandedHierarchyKeys] = useState<Set<string>>(new Set())
  const [hasMore, setHasMore] = useState(false)
  const [total, setTotal] = useState<number | undefined>()
  
  // Initialize selected values from instance
  useEffect(() => {
    const initial = instance.selected_values
      ? new Set(instance.selected_values.map(v => slicerValueKey(v)))
      : new Set<string>()
    if (instance.selected_values) {
      setSelectedValues(initial)
    } else {
      setSelectedValues(initial)
    }
    setCommittedValues(initial)
    setInputValue(def.type === 'input' && operatorAllowsMultiple(normalizeInputOperator(def.filter_operator))
      ? Array.from(initial).join(', ')
      : Array.from(initial)[0] ?? '')
  }, [def.filter_operator, def.type, instance.selected_values])

  useEffect(() => {
    setInputOperator(normalizeInputOperator(def.filter_operator))
  }, [def.filter_operator])

  // Load values
  const loadValues = useCallback(async () => {
    if (isPureInput) {
      setLoading(false)
      setError(null)
      setValues([])
      setHasMore(false)
      setTotal(undefined)
      return
    }
    setLoading(true)
    setError(null)
    
    const result = await fetchValues({
      def_id: def.id,
      page_id: instance.page_id,
      q: searchQuery || undefined,
      limit: 200,
    })
    
    if (result.error) {
      setError(result.error)
      setValues([])
    } else {
      setValues(result.values || [])
      setHasMore(result.has_more || false)
      setTotal(result.total)
    }
    
    setLoading(false)
  }, [fetchValues, def.id, instance.page_id, isPureInput, searchQuery])

  // Load on mount and when search changes
  useEffect(() => {
    loadValues()
  }, [loadValues])

  // Filter values by search (client-side for already-loaded values)
  const filteredValues = useMemo(() => {
    if (!searchQuery) return values
    const q = searchQuery.toLowerCase()
    return values.filter(v => slicerValueDisplayLabel(v).toLowerCase().includes(q) || slicerValueKey(v).toLowerCase().includes(q))
  }, [values, searchQuery])

  // Phase 23F: Sort by state (relevance mode): selected → possible → excluded
  const sortedValues = useMemo(() => {
    if (sortMode !== 'relevance' || !fieldState) return filteredValues
    return [...filteredValues].sort((a, b) => {
      const aStr = slicerValueKey(a)
      const bStr = slicerValueKey(b)
      const aSelected = selectedValues.has(aStr)
      const bSelected = selectedValues.has(bStr)
      const aPossible = fieldState.possible.has(aStr)
      const bPossible = fieldState.possible.has(bStr)
      // Order: selected (0) → possible (1) → excluded (2)
      const aRank = aSelected ? 0 : aPossible ? 1 : 2
      const bRank = bSelected ? 0 : bPossible ? 1 : 2
      if (aRank !== bRank) return aRank - bRank
      // Within same rank: alphabetical
      return aStr.localeCompare(bStr)
    })
  }, [filteredValues, sortMode, fieldState, selectedValues])

  const isButtonLike = def.type === 'button' || def.type === 'tile'

  const hierarchyTreeEnabled = useMemo(
    () => !isButtonLike && sortedValues.some(hasHierarchyTreeMetadata),
    [isButtonLike, sortedValues]
  )

  const visibleSlicerValues = useMemo(() => {
    if (!hierarchyTreeEnabled) return sortedValues
    return sortedValues.filter(value => {
      const info = slicerHierarchyInfo(value)
      if (info.depth <= 0 || info.path.length <= 1) return true
      for (let index = 1; index < info.path.length; index += 1) {
        const ancestorKey = info.path.slice(0, index).join(HIERARCHY_PATH_SEPARATOR)
        if (!expandedHierarchyKeys.has(ancestorKey)) return false
      }
      return true
    })
  }, [expandedHierarchyKeys, hierarchyTreeEnabled, sortedValues])

  const loadedValueStrings = useMemo(() => new Set(values.map(v => slicerValueKey(v))), [values])
  const hiddenSelectedValues = useMemo(
    () => Array.from(selectedValues).filter(value => !loadedValueStrings.has(value)),
    [loadedValueStrings, selectedValues]
  )
  const isDateRange = def.type === 'date_range' || def.type === 'relative_date' || def.type === 'relative_time'
  const pasteValuesEnabled = def.paste_values === true && !isDateRange && !isInput
  const leafOnly = def.leaf_only === true

  const coerceForceSelection = useCallback((selection: Set<string>, preferCommitted = false) => {
    if (!forceSelection || selection.size > 0) return selection
    const fallback = preferCommitted
      ? Array.from(committedValues)[0] ?? Array.from(selectedValues)[0] ?? values.map(v => slicerValueKey(v))[0]
      : Array.from(selectedValues)[0] ?? Array.from(committedValues)[0] ?? values.map(v => slicerValueKey(v))[0]
    return fallback ? new Set([fallback]) : selection
  }, [committedValues, forceSelection, selectedValues, values])

  const commitSelection = useCallback((selection: Set<string>) => {
    const normalizedSelection = coerceForceSelection(selection, true)
    const selectedArray = Array.from(normalizedSelection)
    onSelectionChange?.(selectedArray)
    if (selectedArray.length > 0 && !isPureInput) {
      addSlicerFilter(
        def.column.table,
        def.column.column,
        selectedArray,
        instance.id,
        instance.page_id || null,
        isInput ? inputOperator : 'in',
      )
    } else {
      removeSlicerFilter(instance.id)
    }
    setCommittedValues(new Set(normalizedSelection))
    setSelectedValues(new Set(normalizedSelection))
    setInputValue(isInput && operatorAllowsMultiple(inputOperator)
      ? Array.from(normalizedSelection).join(', ')
      : Array.from(normalizedSelection)[0] ?? '')
  }, [coerceForceSelection, def.column.table, def.column.column, instance.id, instance.page_id, inputOperator, isInput, isPureInput, onSelectionChange, addSlicerFilter, removeSlicerFilter])

  const updateSelection = useCallback((selection: Set<string>) => {
    const normalizedSelection = coerceForceSelection(selection)
    setSelectedValues(normalizedSelection)
    if (autoApply) {
      commitSelection(normalizedSelection)
    }
  }, [autoApply, coerceForceSelection, commitSelection])

  useEffect(() => {
    if (!forceSelection || loading || selectedValues.size > 0 || values.length === 0) return
    updateSelection(new Set([slicerValueKey(values[0])]))
  }, [forceSelection, loading, selectedValues.size, updateSelection, values])

  // Handle selection change
  const handleToggle = useCallback((value: unknown) => {
    if (leafOnly && !slicerValueIsLeaf(value)) return
    const strValue = slicerValueKey(value)
    const newSelected = new Set(selectedValues)
    
    if (def.selection_type === 'single') {
      // Single select: clear others
      newSelected.clear()
      if (!selectedValues.has(strValue)) {
        newSelected.add(strValue)
      }
    } else {
      // Multi select: toggle
      if (newSelected.has(strValue)) {
        newSelected.delete(strValue)
      } else {
        newSelected.add(strValue)
      }
    }
    
    updateSelection(newSelected)
  }, [leafOnly, selectedValues, def.selection_type, updateSelection])

  // Handle "Select All"
  const handleSelectAll = useCallback(() => {
    const selectableValues = leafOnly ? filteredValues.filter(slicerValueIsLeaf) : filteredValues
    const allSelected = selectableValues.length > 0 && selectableValues.every(v => selectedValues.has(slicerValueKey(v)))
    
    const newSelected = new Set(selectedValues)
    if (allSelected) {
      // Deselect all filtered values
      selectableValues.forEach(v => newSelected.delete(slicerValueKey(v)))
    } else {
      // Select all filtered values
      selectableValues.forEach(v => newSelected.add(slicerValueKey(v)))
    }
    
    updateSelection(newSelected)
  }, [filteredValues, leafOnly, selectedValues, updateSelection])

  // Clear selection
  const handleClear = useCallback(() => {
    setEditingInputPillIndex(null)
    setEditingInputPillValue('')
    updateSelection(new Set())
    if (!forceSelection) setInputValue('')
  }, [forceSelection, updateSelection])

  const handleApply = useCallback(() => {
    commitSelection(selectedValues)
  }, [commitSelection, selectedValues])

  const handleInputApply = useCallback(() => {
    const parsed = operatorAllowsMultiple(inputOperator)
      ? parsePastedSlicerValues(inputValue)
      : [inputValue.trim()].filter(Boolean)
    const next = new Set(parsed)
    updateSelection(next)
    if (!autoApply) commitSelection(next)
  }, [autoApply, commitSelection, inputOperator, inputValue, updateSelection])

  const removeInputPill = useCallback((value: string) => {
    const next = new Set(selectedValues)
    next.delete(value)
    setInputValue(operatorAllowsMultiple(inputOperator) ? Array.from(next).join(', ') : Array.from(next)[0] ?? '')
    updateSelection(next)
  }, [inputOperator, selectedValues, updateSelection])

  const startEditingInputPill = useCallback((index: number, value: string) => {
    setEditingInputPillIndex(index)
    setEditingInputPillValue(value)
  }, [])

  const cancelEditingInputPill = useCallback(() => {
    setEditingInputPillIndex(null)
    setEditingInputPillValue('')
  }, [])

  const commitEditingInputPill = useCallback(() => {
    if (editingInputPillIndex == null) return
    const currentValues = Array.from(selectedValues)
    const trimmed = editingInputPillValue.trim()
    const nextValues = currentValues
      .map((value, index) => (index === editingInputPillIndex ? trimmed : value))
      .filter(Boolean)
    const next = new Set(nextValues)
    setInputValue(operatorAllowsMultiple(inputOperator) ? Array.from(next).join(', ') : Array.from(next)[0] ?? '')
    setEditingInputPillIndex(null)
    setEditingInputPillValue('')
    updateSelection(next)
  }, [editingInputPillIndex, editingInputPillValue, inputOperator, selectedValues, updateSelection])

  const handlePasteApply = useCallback(() => {
    const parsed = parsePastedSlicerValues(pasteDraft)
    const lookup = new Map<string, string>()
    values.forEach(value => {
      if (leafOnly && !slicerValueIsLeaf(value)) return
      lookup.set(slicerValueKey(value).toLowerCase(), slicerValueKey(value))
      lookup.set(slicerValueLabel(value).toLowerCase(), slicerValueKey(value))
    })
    const resolved = parsed.map(value => lookup.get(value.toLowerCase()) ?? value)
    const valuesToApply = def.selection_type === 'single' ? resolved.slice(0, 1) : resolved
    const next = new Set(valuesToApply)
    updateSelection(next)
    setPasteDraft('')
  }, [def.selection_type, leafOnly, pasteDraft, updateSelection, values])

  const selectableFilteredValues = useMemo(
    () => leafOnly ? filteredValues.filter(slicerValueIsLeaf) : filteredValues,
    [filteredValues, leafOnly]
  )
  const allSelected = selectableFilteredValues.length > 0 && selectableFilteredValues.every(v => selectedValues.has(slicerValueKey(v)))
  const someSelected = selectedValues.size > 0
  const hasPendingSelection = !setsEqual(selectedValues, committedValues)
  const selectedInputValues = useMemo(() => Array.from(selectedValues), [selectedValues])
  const syncSummary = useMemo(() => {
    const entries = Object.entries(def.pages || {})
    const synced = entries.filter(([, page]) => page.sync !== false).length
    const visible = entries.filter(([, page]) => page.visible !== false).length
    if (!def.sync_group && entries.length <= 1 && synced === entries.length && visible === entries.length) return null
    const total = entries.length || 1
    return {
      label: def.sync_group || `${synced}/${total}`,
      detail: [
        def.sync_group ? `Group ${def.sync_group}` : 'No sync group',
        `${synced} synced page${synced === 1 ? '' : 's'}`,
        `${visible} visible page${visible === 1 ? '' : 's'}`,
      ].join(' - '),
    }
  }, [def.pages, def.sync_group])

  const handleInputOperatorChange = useCallback((value: string) => {
    const nextOperator = normalizeInputOperator(value)
    setInputOperator(nextOperator)
    if (!operatorAllowsMultiple(nextOperator) && selectedValues.size > 1) {
      const first = Array.from(selectedValues)[0]
      const next = first ? new Set([first]) : new Set<string>()
      setSelectedValues(next)
      setInputValue(first ?? '')
      if (autoApply) commitSelection(next)
    }
  }, [autoApply, commitSelection, selectedValues])

  useEffect(() => {
    const handleGlobalApply = () => {
      if (!autoApply) {
        commitSelection(selectedValues)
      }
    }
    const handleGlobalClear = () => {
      const next = coerceForceSelection(new Set<string>(), true)
      setSelectedValues(new Set(next))
      setInputValue(Array.from(next)[0] ?? '')
      commitSelection(next)
    }
    window.addEventListener(APPLY_ALL_SLICERS_EVENT, handleGlobalApply)
    window.addEventListener(CLEAR_ALL_SLICERS_EVENT, handleGlobalClear)
    document.addEventListener(APPLY_ALL_SLICERS_EVENT, handleGlobalApply)
    document.addEventListener(CLEAR_ALL_SLICERS_EVENT, handleGlobalClear)
    return () => {
      window.removeEventListener(APPLY_ALL_SLICERS_EVENT, handleGlobalApply)
      window.removeEventListener(CLEAR_ALL_SLICERS_EVENT, handleGlobalClear)
      document.removeEventListener(APPLY_ALL_SLICERS_EVENT, handleGlobalApply)
      document.removeEventListener(CLEAR_ALL_SLICERS_EVENT, handleGlobalClear)
    }
  }, [autoApply, coerceForceSelection, commitSelection, selectedValues])

  const toggleHierarchyNode = useCallback((pathKey: string) => {
    setExpandedHierarchyKeys(prev => {
      const next = new Set(prev)
      if (next.has(pathKey)) {
        next.delete(pathKey)
      } else {
        next.add(pathKey)
      }
      return next
    })
  }, [])

  // Phase 23F: Keyboard navigation handler for slicer items
  const handleItemKeyDown = useCallback((e: React.KeyboardEvent, idx: number) => {
    const total = visibleSlicerValues.length
    if (total === 0) return

    let nextIdx = -1
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      nextIdx = idx < total - 1 ? idx + 1 : 0
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      nextIdx = idx > 0 ? idx - 1 : total - 1
    } else if (e.key === 'Home') {
      e.preventDefault()
      nextIdx = 0
    } else if (e.key === 'End') {
      e.preventDefault()
      nextIdx = total - 1
    }

    if (nextIdx >= 0 && itemRefs.current[nextIdx]) {
      setFocusedIndex(nextIdx)
      itemRefs.current[nextIdx]?.focus()
    }
  }, [visibleSlicerValues.length])

  // Phase 23F: Possible count info for filter pane annotations
  const possibleCount = fieldState ? fieldState.possible.size : undefined
  const totalCount = fieldState ? fieldState.allValues.length : undefined

  return (
    <div 
      className={cn(
        'flex flex-col bg-card border rounded-md shadow-sm overflow-hidden',
        className
      )}
      style={{
        width: instance.width ?? 200,
        height: instance.height ?? 300,
      }}
      data-testid={`slicer-${instance.id}`}
    >
      {/* Header */}
      <div className="flex items-center gap-2 px-3 py-2 border-b bg-muted/30">
        <button 
          onClick={() => setCollapsed(!collapsed)}
          className="p-0.5 hover:bg-accent rounded"
        >
          {collapsed ? (
            <ChevronRight className="h-4 w-4" />
          ) : (
            <ChevronDown className="h-4 w-4" />
          )}
        </button>
        <span className="text-sm font-medium flex-1 truncate" title={def.name}>
          {def.name}
        </span>
        {syncSummary && (
          <span
            className="max-w-24 shrink-0 truncate rounded border bg-background px-1.5 py-0.5 text-[10px] text-muted-foreground"
            title={syncSummary.detail}
            data-testid={`slicer-${instance.id}-sync-summary`}
          >
            {syncSummary.label}
          </span>
        )}
        {/* Phase 23F: Filter pane annotation — "(N of M possible)" */}
        {possibleCount !== undefined && totalCount !== undefined && possibleCount < totalCount && (
          <span
            className={cn(
              'text-[10px] tabular-nums shrink-0',
              possibleCount === 0
                ? 'text-destructive font-medium'
                : 'text-muted-foreground'
            )}
            data-testid={`slicer-${instance.id}-possible-count`}
          >
            {possibleCount === 0
              ? '(0 possible — filter conflict)'
              : `(${possibleCount} of ${totalCount} possible)`}
          </span>
        )}
        {/* Phase 23F: Sort toggle */}
        {def.type !== 'dropdown' && !isDateRange && !isInput && (
          <Button
            variant="ghost"
            size="icon"
            className={cn(
              'h-5 w-5',
              sortMode === 'relevance' && 'text-primary'
            )}
            onClick={() => setSortMode(m => m === 'alphabetical' ? 'relevance' : 'alphabetical')}
            title={sortMode === 'alphabetical' ? 'Sort by relevance' : 'Sort alphabetically'}
            data-testid={`slicer-${instance.id}-sort-toggle`}
          >
            <ArrowUpDown className="h-3 w-3" />
          </Button>
        )}
        {/* Phase 23F: Count display toggle */}
        {def.type !== 'dropdown' && !isDateRange && !isInput && (
          <Button
            variant="ghost"
            size="icon"
            className={cn(
              'h-5 w-5 text-[10px] font-mono',
              showCounts && 'text-primary'
            )}
            onClick={() => setShowCounts(c => !c)}
            title={showCounts ? 'Hide counts' : 'Show counts'}
            data-testid={`slicer-${instance.id}-counts-toggle`}
          >
            #
          </Button>
        )}
        {someSelected && (
          <Button
            variant="ghost"
            size="icon"
            className="h-5 w-5"
            onClick={handleClear}
            title="Clear selection"
            data-testid={`slicer-${instance.id}-clear`}
          >
            <X className="h-3 w-3" />
          </Button>
        )}
      </div>

      {!collapsed && (
        <>
          {/* Dropdown type */}
          {isInput ? (
            <div className="p-2 space-y-2" data-testid={`slicer-${instance.id}-input`}>
              {isPureInput ? (
                <div
                  className="rounded border bg-muted/40 px-2 py-1 text-[10px] font-medium text-muted-foreground"
                  data-testid={`slicer-${instance.id}-input-mode`}
                >
                  Input only
                </div>
              ) : (
                <Select value={inputOperator} onValueChange={handleInputOperatorChange}>
                  <SelectTrigger
                    className="h-8 text-xs"
                    data-testid={`slicer-${instance.id}-input-operator`}
                  >
                    <SelectValue placeholder="Operator" />
                  </SelectTrigger>
                  <SelectContent>
                    {INPUT_SLICER_OPERATORS.map(option => (
                      <SelectItem key={option.value} value={option.value}>
                        {option.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              )}
              <Input
                value={inputValue}
                onChange={e => setInputValue(e.target.value)}
                onKeyDown={e => {
                  if (e.key === 'Enter') handleInputApply()
                }}
                placeholder={operatorAllowsMultiple(inputOperator) ? 'Values' : 'Value'}
                className="h-8 text-xs"
                data-testid={`slicer-${instance.id}-input-value`}
              />
              {selectedInputValues.length > 0 && (
                <div
                  className="flex flex-wrap gap-1"
                  data-testid={`slicer-${instance.id}-input-pills`}
                >
                  {selectedInputValues.map((value, i) => (
                    <span
                      key={`${value}-${i}`}
                      className="inline-flex max-w-full items-center gap-1 rounded border bg-muted/50 px-2 py-0.5 text-[11px]"
                      data-testid={`slicer-${instance.id}-input-pill-${i}`}
                    >
                      {editingInputPillIndex === i ? (
                        <>
                          <Input
                            value={editingInputPillValue}
                            onChange={e => setEditingInputPillValue(e.target.value)}
                            onKeyDown={e => {
                              if (e.key === 'Enter') commitEditingInputPill()
                              if (e.key === 'Escape') cancelEditingInputPill()
                            }}
                            onBlur={commitEditingInputPill}
                            className="h-5 min-w-16 max-w-32 px-1 text-[11px]"
                            autoFocus
                            data-testid={`slicer-${instance.id}-input-pill-edit-${i}`}
                          />
                          <button
                            type="button"
                            className="rounded hover:bg-background"
                            onMouseDown={e => e.preventDefault()}
                            onClick={commitEditingInputPill}
                            title="Save value"
                            data-testid={`slicer-${instance.id}-input-pill-save-${i}`}
                          >
                            <Check className="h-3 w-3" />
                          </button>
                        </>
                      ) : (
                        <>
                          <button
                            type="button"
                            className="max-w-full truncate rounded text-left hover:bg-background"
                            onClick={() => startEditingInputPill(i, value)}
                            title={`Edit ${value}`}
                            data-testid={`slicer-${instance.id}-input-pill-edit-trigger-${i}`}
                          >
                            {value || '(blank)'}
                          </button>
                          <button
                            type="button"
                            className="rounded hover:bg-background"
                            onClick={() => removeInputPill(value)}
                            title="Remove value"
                            data-testid={`slicer-${instance.id}-input-pill-remove-${i}`}
                          >
                            <X className="h-3 w-3" />
                          </button>
                        </>
                      )}
                    </span>
                  ))}
                </div>
              )}
              <Button
                size="sm"
                variant="secondary"
                className="h-7 w-full text-xs"
                onClick={handleInputApply}
                data-testid={`slicer-${instance.id}-input-apply`}
              >
                <Check className="h-3 w-3 mr-1" />
                Apply
              </Button>
            </div>
          ) : (def.type === 'dropdown') ? (
            <div className="p-2" data-testid={`slicer-${instance.id}-dropdown`}>
              {loading ? (
                <div className="flex items-center justify-center py-4">
                  <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
                </div>
              ) : error ? (
                <div className="text-xs text-red-600">{error}</div>
              ) : (
                <Select
                  value={selectedValues.size === 1 ? Array.from(selectedValues)[0] : ''}
                  onValueChange={(val) => handleToggle(val)}
                >
                  <SelectTrigger className="h-8 text-xs" data-testid={`slicer-${instance.id}-dropdown-trigger`}>
                    <SelectValue placeholder="Select..." />
                  </SelectTrigger>
                  <SelectContent>
                    {filteredValues.map((value, i) => (
                      <SelectItem
                        key={`${slicerValueKey(value)}-${i}`}
                        value={slicerValueKey(value)}
                        disabled={leafOnly && !slicerValueIsLeaf(value)}
                      >
                        {slicerValueLabel(value) || '(blank)'}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              )}
            </div>
          ) : isDateRange ? (
            /* Date range type */
            <DateRangeSlicer
              instanceId={instance.id}
              slicerType={def.type}
              selection={def.selection}
              selectedValues={selectedValues}
              onChange={(start, end) => {
                const vals = [start, end].filter(Boolean)
                updateSelection(new Set(vals))
              }}
            />
          ) : (
            /* Default: list type (checkbox) */
            <>
              {pasteValuesEnabled && (
                <div className="border-b p-2 space-y-1" data-testid={`slicer-${instance.id}-paste-values`}>
                  <Textarea
                    value={pasteDraft}
                    onChange={e => setPasteDraft(e.target.value)}
                    placeholder="Paste values"
                    className="min-h-14 text-xs"
                    data-testid={`slicer-${instance.id}-paste-input`}
                  />
                  <Button
                    size="sm"
                    variant="secondary"
                    className="h-7 w-full text-xs"
                    onClick={handlePasteApply}
                    disabled={!pasteDraft.trim() && !forceSelection}
                    data-testid={`slicer-${instance.id}-paste-apply`}
                  >
                    Paste values
                  </Button>
                </div>
              )}

              {/* Search */}
              {def.search_enabled !== false && (
            <div className="p-2 border-b">
              <div className="relative">
                <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
                <Input
                  value={searchQuery}
                  onChange={e => setSearchQuery(e.target.value)}
                  placeholder="Search..."
                  className="h-7 pl-7 text-xs"
                  data-testid={`slicer-${instance.id}-search`}
                />
              </div>
            </div>
          )}

          {/* Content */}
          <ScrollArea className="flex-1" data-slicer-interactive>
            {loading ? (
              <div className="flex items-center justify-center py-8">
                <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
              </div>
            ) : error ? (
              <div className="p-3 text-xs text-red-600">
                {error}
              </div>
            ) : filteredValues.length === 0 ? (
              <div className="p-3 text-xs text-muted-foreground text-center">
                No values found
              </div>
            ) : (
              <div className="p-1">
                {/* Select All */}
                {def.show_select_all !== false && def.selection_type !== 'single' && (
                  <div 
                    className="flex items-center gap-2 px-2 py-1.5 hover:bg-accent rounded cursor-pointer text-xs"
                    onClick={handleSelectAll}
                    data-testid={`slicer-${instance.id}-select-all`}
                  >
                    <Checkbox 
                      checked={allSelected}
                      className="h-3.5 w-3.5"
                    />
                    <span className="font-medium">Select All</span>
                    {total !== undefined && (
                      <span className="text-muted-foreground ml-auto">({total})</span>
                    )}
                  </div>
                )}

                {hiddenSelectedValues.length > 0 && (
                  <div className="mb-1 rounded border bg-muted/30 px-2 py-1 text-[10px] text-muted-foreground" data-testid={`slicer-${instance.id}-hidden-selected`}>
                    <span>{hiddenSelectedValues.length} active value{hiddenSelectedValues.length === 1 ? '' : 's'} outside the loaded list:</span>
                    <div className="mt-1 flex flex-wrap gap-1">
                      {hiddenSelectedValues.map(value => (
                        <span key={value} className="rounded border bg-background px-1 py-0.5 text-foreground">
                          {value || '(blank)'}
                        </span>
                      ))}
                    </div>
                  </div>
                )}

                {/* Values — Phase 23F: SelectionStateItem with 3-state + icons + counts + keyboard */}
                <div aria-label={`${def.name} values`} data-testid={`slicer-${instance.id}-values`}>
                {visibleSlicerValues.map((value, i) => {
                  const strValue = slicerValueKey(value)
                  const label = slicerValueDisplayLabel(value)
                  const imageSource = slicerValueImageSource(value, projectPath || undefined)
                  const imagePresentation = slicerValueImagePresentation(value, def)
                  const conditionalItem = slicerValueConditionalPresentation(value)
                  const hierarchyInfo = slicerHierarchyInfo(value)
                  const isLeaf = slicerValueIsLeaf(value)
                  const isExpandable = hierarchyTreeEnabled && !isLeaf
                  const isExpanded = isExpandable && expandedHierarchyKeys.has(hierarchyInfo.pathKey)
                  const isDisabled = leafOnly && !isLeaf
                  const isSelected = selectedValues.has(strValue)
                  const isExcluded = fieldState ? fieldState.excluded.has(strValue) : false
                  const isPossible = fieldState ? fieldState.possible.has(strValue) : true
                  const state: SelectionState = isSelected ? 'selected' : isExcluded ? 'excluded' : 'possible'
                  const count = showCounts && fieldState?.counts ? fieldState.counts[strValue] : undefined
                  
                  if (isButtonLike) {
                    return (
                      <button
                        key={`${strValue}-${i}`}
                        type="button"
                        data-selected={isSelected ? 'true' : 'false'}
                        className={cn(
                          'm-0.5 inline-flex min-h-7 max-w-full items-center rounded border px-2 py-1 text-xs transition-colors',
                          isSelected
                            ? 'border-primary bg-primary text-primary-foreground'
                            : 'border-border bg-background hover:bg-accent',
                          isExcluded && !isSelected && 'opacity-45',
                          isDisabled && 'cursor-not-allowed opacity-50 hover:bg-background',
                        )}
                        style={conditionalItem.style}
                        disabled={isDisabled}
                        onClick={() => handleToggle(value)}
                        data-testid={`slicer-${instance.id}-button-value-${i}`}
                        data-leaf={isLeaf ? 'true' : 'false'}
                        data-conditional-format={conditionalItem.summary}
                      >
                        <SlicerImageMedia
                          image={imageSource}
                          label={label}
                          presentation={imagePresentation}
                          className="mr-1 h-5 w-5 shrink-0 rounded object-cover"
                          testId={`slicer-${instance.id}-button-image-${i}`}
                        />
                        <span className="truncate">{label || '(blank)'}</span>
                        {count !== undefined && <span className="ml-1 opacity-70">{count}</span>}
                      </button>
                    )
                  }
                  return (
                    <SelectionStateItem
                      key={`${strValue}-${i}`}
                      ref={(el: HTMLDivElement | null) => { itemRefs.current[i] = el }}
                      label={label}
                      state={state}
                      checked={isSelected}
                      count={count}
                      imageUrl={imageSource.url}
                      imageFallback={imageSource.fallback}
                      imageResource={imageSource.resource}
                      imageStyle={imagePresentation.style}
                      itemStyle={conditionalItem.style}
                      conditionalFormat={conditionalItem.summary}
                      imageFit={imagePresentation.fit}
                      imagePosition={imagePresentation.position}
                      imageSaturation={imagePresentation.saturation}
                      leading={hierarchyTreeEnabled ? (
                        isExpandable ? (
                          <button
                            type="button"
                            className="flex h-4 w-4 shrink-0 items-center justify-center rounded hover:bg-muted"
                            aria-label={isExpanded ? `Collapse ${label}` : `Expand ${label}`}
                            aria-expanded={isExpanded}
                            onClick={(event) => {
                              event.stopPropagation()
                              toggleHierarchyNode(hierarchyInfo.pathKey)
                            }}
                            onKeyDown={(event) => {
                              if (event.key === 'Enter' || event.key === ' ') {
                                event.preventDefault()
                                event.stopPropagation()
                                toggleHierarchyNode(hierarchyInfo.pathKey)
                              }
                            }}
                            data-testid={`slicer-${instance.id}-hierarchy-toggle-${i}`}
                          >
                            {isExpanded ? (
                              <ChevronDown className="h-3 w-3" />
                            ) : (
                              <ChevronRight className="h-3 w-3" />
                            )}
                          </button>
                        ) : (
                          <span className="h-4 w-4 shrink-0" aria-hidden />
                        )
                      ) : undefined}
                      indentLevel={hierarchyTreeEnabled ? hierarchyInfo.depth : 0}
                      disabled={isDisabled}
                      onToggle={() => handleToggle(value)}
                      tabIndex={i === focusedIndex || (focusedIndex === -1 && i === 0) ? 0 : -1}
                      onKeyDown={(e) => handleItemKeyDown(e, i)}
                      data-testid={`slicer-${instance.id}-value-${i}`}
                      data-leaf={isLeaf ? 'true' : 'false'}
                      data-hierarchy-path={hierarchyInfo.pathKey}
                      data-expanded={isExpandable ? (isExpanded ? 'true' : 'false') : undefined}
                    />
                  )
                })}
                </div>

                {/* Has more indicator */}
                {hasMore && (
                  <div className="px-2 py-1 text-xs text-muted-foreground text-center">
                    ... more values available
                  </div>
                )}
              </div>
            )}
          </ScrollArea>

          {/* Footer with selection count */}
          {someSelected && (
            <div className="px-3 py-1.5 border-t text-xs text-muted-foreground">
              {selectedValues.size} selected
            </div>
          )}
            </>
          )}

          {!autoApply && !isInput && (
            <div className="flex items-center gap-1 border-t px-2 py-1.5">
              <Button
                size="sm"
                className="h-7 flex-1 text-xs"
                onClick={handleApply}
                disabled={!hasPendingSelection}
                data-testid={`slicer-${instance.id}-apply`}
              >
                Apply
              </Button>
              <Button
                size="sm"
                variant="ghost"
                className="h-7 text-xs"
                onClick={() => setSelectedValues(new Set(committedValues))}
                disabled={!hasPendingSelection}
                data-testid={`slicer-${instance.id}-revert`}
              >
                Revert
              </Button>
            </div>
          )}
        </>
      )}
    </div>
  )
}

/** ──────────────────────────────────────────────────────
 *  Enhanced Date Range Slicer — better than PBI's slider
 *  Features: quick presets, dual-thumb range slider,
 *  date input pickers, auto-apply, duration badge
 * ────────────────────────────────────────────────────── */

type DatePreset = {
  label: string
  /** returns [startISO, endISO] or null for "All" */
  range: () => [string, string] | null
}

const DATE_PRESETS: DatePreset[] = [
  { label: 'All', range: () => null },
  { label: 'Today', range: () => { const d = _isoToday(); return [d, d] } },
  { label: 'Last 7d', range: () => [_isoOffset(-6), _isoToday()] },
  { label: 'Last 30d', range: () => [_isoOffset(-29), _isoToday()] },
  { label: 'MTD', range: () => { const t = new Date(); return [_iso(new Date(t.getFullYear(), t.getMonth(), 1)), _isoToday()] } },
  { label: 'QTD', range: () => { const t = new Date(); const qm = Math.floor(t.getMonth() / 3) * 3; return [_iso(new Date(t.getFullYear(), qm, 1)), _isoToday()] } },
  { label: 'YTD', range: () => [_iso(new Date(new Date().getFullYear(), 0, 1)), _isoToday()] },
  { label: 'Last Year', range: () => { const y = new Date().getFullYear() - 1; return [_iso(new Date(y, 0, 1)), _iso(new Date(y, 11, 31))] } },
]

function _isoToday(): string { return _iso(new Date()) }
function _isoOffset(days: number): string { const d = new Date(); d.setDate(d.getDate() + days); return _iso(d) }
function _iso(d: Date): string { return d.toISOString().slice(0, 10) }
function _daysBetween(a: string, b: string): number {
  const ms = new Date(b).getTime() - new Date(a).getTime()
  return Math.max(0, Math.round(ms / 86_400_000))
}
function _fmtShort(dateStr: string): string {
  if (!dateStr) return ''
  const d = new Date(dateStr + 'T00:00:00')
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })
}

function DateRangeSlicer({
  instanceId,
  slicerType,
  selection,
  selectedValues,
  onChange,
}: {
  instanceId: string
  slicerType?: SlicerDef['type']
  selection?: SlicerSelection
  selectedValues: Set<string>
  onChange: (start: string, end: string) => void
}) {
  const vals = Array.from(selectedValues).sort()
  const rangeStart = selection?.mode === 'range' && typeof selection.start === 'string' ? selection.start : ''
  const rangeEnd = selection?.mode === 'range' && typeof selection.end === 'string' ? selection.end : ''
  const [startDate, setStartDate] = useState(rangeStart || vals[0] || '')
  const [endDate, setEndDate] = useState(rangeEnd || vals[1] || vals[0] || '')
  const relativeSummary = slicerType === 'relative_date' || slicerType === 'relative_time' ? relativeSelectionSummary(selection) : null
  const [activePreset, setActivePreset] = useState<string | null>(startDate || relativeSummary ? null : 'All')

  // Auto-apply when start/end change (debounced to avoid excessive calls during typing)
  const applyTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const applyRange = useCallback((s: string, e: string) => {
    if (applyTimerRef.current) clearTimeout(applyTimerRef.current)
    applyTimerRef.current = setTimeout(() => {
      if (s && e) {
        // Ensure start <= end
        const [sNorm, eNorm] = s <= e ? [s, e] : [e, s]
        onChange(sNorm, eNorm)
      } else if (!s && !e) {
        onChange('', '')
      }
    }, 300)
  }, [onChange])

  const handleStartChange = useCallback((v: string) => {
    setStartDate(v)
    setActivePreset(null)
    applyRange(v, endDate)
  }, [endDate, applyRange])

  const handleEndChange = useCallback((v: string) => {
    setEndDate(v)
    setActivePreset(null)
    applyRange(startDate, v)
  }, [startDate, applyRange])

  const handlePreset = useCallback((preset: DatePreset) => {
    setActivePreset(preset.label)
    const r = preset.range()
    if (r) {
      setStartDate(r[0])
      setEndDate(r[1])
      onChange(r[0], r[1])
    } else {
      // "All" = clear selection
      setStartDate('')
      setEndDate('')
      onChange('', '')
    }
  }, [onChange])

  const handleClear = useCallback(() => {
    setStartDate('')
    setEndDate('')
    setActivePreset('All')
    onChange('', '')
  }, [onChange])

  const dayCount = startDate && endDate ? _daysBetween(startDate, endDate) + 1 : 0

  return (
    <div className="px-2 py-1 space-y-1" data-slicer-interactive data-testid={`slicer-${instanceId}-daterange`}>
      {relativeSummary && (
        <div
          className="flex items-start gap-1.5 rounded border bg-muted/40 px-2 py-1 text-[10px]"
          data-testid={`slicer-${instanceId}-relative-summary`}
        >
          <Calendar className="mt-0.5 h-3 w-3 shrink-0 text-muted-foreground" />
          <div className="min-w-0">
            <div className="truncate font-medium text-foreground">{relativeSummary.label}</div>
            <div className="truncate text-muted-foreground">{relativeSummary.detail}</div>
          </div>
        </div>
      )}

      {/* Quick presets — compact single row */}
      <div className="flex flex-wrap gap-0.5" data-testid={`slicer-${instanceId}-presets`}>
        {DATE_PRESETS.map(preset => (
          <button
            key={preset.label}
            onClick={() => handlePreset(preset)}
            className={cn(
              'px-1 py-px text-[9px] rounded border transition-colors leading-tight',
              activePreset === preset.label
                ? 'bg-primary text-primary-foreground border-primary'
                : 'bg-muted/40 text-muted-foreground border-border hover:bg-accent hover:text-accent-foreground'
            )}
            data-testid={`slicer-${instanceId}-preset-${preset.label.replace(/\s/g, '')}`}
          >
            {preset.label}
          </button>
        ))}
      </div>

      {/* Date inputs — compact side by side */}
      <div className="grid grid-cols-2 gap-1">
        <div className="flex items-center gap-1">
          <label className="text-[9px] text-muted-foreground shrink-0 w-5">Fr</label>
          <Input
            type="date"
            value={startDate}
            onChange={e => handleStartChange(e.target.value)}
            className="h-6 text-[10px] px-1"
            data-testid={`slicer-${instanceId}-date-start`}
          />
        </div>
        <div className="flex items-center gap-1">
          <label className="text-[9px] text-muted-foreground shrink-0 w-5">To</label>
          <Input
            type="date"
            value={endDate}
            onChange={e => handleEndChange(e.target.value)}
            className="h-6 text-[10px] px-1"
            data-testid={`slicer-${instanceId}-date-end`}
          />
        </div>
      </div>

      {/* Compact summary line */}
      {startDate && endDate ? (
        <div className="flex items-center justify-between text-[9px] leading-tight">
          <span className="text-muted-foreground truncate">
            {_fmtShort(startDate)} — {_fmtShort(endDate)}
          </span>
          <div className="flex items-center gap-0.5 shrink-0">
            <span className="bg-primary/10 text-primary px-1 py-px rounded-full font-medium text-[9px]">
              {dayCount}d
            </span>
            <button
              onClick={handleClear}
              className="p-0.5 hover:bg-accent rounded"
              title="Clear date range"
              data-testid={`slicer-${instanceId}-date-clear`}
            >
              <X className="h-2.5 w-2.5 text-muted-foreground" />
            </button>
          </div>
        </div>
      ) : null}
    </div>
  )
}

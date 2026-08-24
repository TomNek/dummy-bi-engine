/**
 * Static visual renderers — Text Box, Button, Shape, Image.
 *
 * These visual types do not query data. They render decorative/layout
 * content purely from the `static_content` field on the visual definition.
 *
 * Button types mirror Power BI: blank, back, left-arrow, right-arrow, reset,
 * information, help, bookmark, apply-all-slicers, clear-all-slicers, navigator.
 *
 * Shapes mirror Power BI categories: Rectangles, Basic Shapes, Block Arrows.
 *
 * Both buttons and shapes support an optional `action` (bookmark / URL / page).
 */

import { useCallback } from 'react'
import { useAppStore } from '@/stores'
import { useReportStore } from '@/stores'
import { useDrillthroughStore } from '@/stores/drillthrough-store'
import { applyBookmark } from '@/lib/api'
import type { StaticContent, StaticAction } from '@/lib/api'
import { APPLY_ALL_SLICERS_EVENT, CLEAR_ALL_SLICERS_EVENT, dispatchSlicerEvent } from '@/lib/slicer-events'

interface StaticVisualContentProps {
  visualType: string
  staticContent?: StaticContent
  staticAsset?: Record<string, unknown>
  staticResources?: Array<Record<string, unknown>>
}

/**
 * Returns true if `visualType` is a static visual type that should be
 * rendered by this component instead of going through the data pipeline.
 */
export function isStaticVisualType(visualType: string): boolean {
  return ['textbox', 'button', 'shape', 'image'].includes(visualType.toLowerCase())
}

// ─── Action handler ──────────────────────────────────────────────────────────

function useStaticAction() {
  const projectPath = useAppStore((s) => s.projectPath)
  const setCurrentPage = useReportStore((s) => s.setCurrentPage)
  const goBackPage = useReportStore((s) => s.goBackPage)
  const drillthroughActive = useDrillthroughStore((s) => s.active)
  const drillthroughSourcePageId = useDrillthroughStore((s) => s.sourcePageId)
  const endDrillthrough = useDrillthroughStore((s) => s.endDrillthrough)

  return useCallback(async (action: StaticAction | undefined) => {
    if (!action || action.type === 'none') return
    switch (action.type) {
      case 'url':
        if (action.target) window.open(action.target, '_blank', 'noopener,noreferrer')
        break
      case 'page':
        if (action.target) setCurrentPage(action.target)
        break
      case 'bookmark': {
        if (action.target) await applyBookmark(action.target, projectPath ?? undefined)
        break
      }
      case 'back':
        if (drillthroughActive && drillthroughSourcePageId) {
          setCurrentPage(drillthroughSourcePageId, { replace: true })
        } else {
          goBackPage()
        }
        endDrillthrough()
        break
      case 'drillthrough':
        // Button-click drillthrough has no per-row payload — just navigate.
        if (action.target) setCurrentPage(action.target)
        break
      case 'apply-all-slicers':
        dispatchSlicerEvent(APPLY_ALL_SLICERS_EVENT)
        // Fallback path: explicitly trigger enabled per-slicer Apply buttons.
        const clickEnabledSlicerApplyButtons = () => {
          document
            .querySelectorAll<HTMLButtonElement>('button[data-testid^="slicer-"][data-testid$="-apply"]:not(:disabled)')
            .forEach((button) => button.click())
        }
        clickEnabledSlicerApplyButtons()
        window.setTimeout(clickEnabledSlicerApplyButtons, 0)
        window.setTimeout(clickEnabledSlicerApplyButtons, 50)
        break
      case 'clear-all-slicers':
        dispatchSlicerEvent(CLEAR_ALL_SLICERS_EVENT)
        break
    }
  }, [projectPath, setCurrentPage, goBackPage, drillthroughActive, drillthroughSourcePageId, endDrillthrough])
}

function isTargetlessAction(type: StaticAction['type'] | undefined): boolean {
  return type === 'back' || type === 'apply-all-slicers' || type === 'clear-all-slicers'
}

function hasRunnableAction(action: StaticAction | undefined): boolean {
  if (!action || action.type === 'none') return false
  return isTargetlessAction(action.type) || Boolean(action.target)
}

function staticActionDisabledReason(action: StaticAction | undefined): string | undefined {
  if (!action || action.type === 'none' || isTargetlessAction(action.type)) return undefined
  if (!action.target) {
    if (action.type === 'url') return 'Missing URL target'
    if (action.type === 'page') return 'Missing page target'
    if (action.type === 'bookmark') return 'Missing bookmark target'
    if (action.type === 'drillthrough') return 'Missing drillthrough page target'
    return 'Missing action target'
  }
  return undefined
}

export function StaticVisualContent({ visualType, staticContent, staticAsset, staticResources }: StaticVisualContentProps) {
  const sc = mergeStaticAssetContent(staticContent ?? {}, staticAsset, staticResources)
  const handleAction = useStaticAction()
  const rotation = Number.isFinite(sc.rotation) ? Number(sc.rotation) : 0
  const contentStyle: React.CSSProperties = rotation
    ? { transform: `rotate(${rotation}deg)`, transformOrigin: 'center center' }
    : {}

  let content: React.ReactNode
  switch (visualType.toLowerCase()) {
    case 'textbox':
      content = <TextBoxContent content={sc} />
      break
    case 'button':
      content = <ButtonContent content={sc} onAction={handleAction} />
      break
    case 'shape':
      content = <ShapeContent content={sc} onAction={handleAction} />
      break
    case 'image':
      content = <ImageContent content={sc} />
      break
    default:
      content = (
        <div className="flex items-center justify-center h-full text-muted-foreground text-xs">
          Unknown static type: {visualType}
        </div>
      )
  }

  return (
    <div
      className="h-full w-full"
      style={contentStyle}
      data-testid="static-content-root"
      data-rotation={rotation ? String(rotation) : undefined}
    >
      {content}
    </div>
  )
}

function mergeStaticAssetContent(
  content: StaticContent,
  staticAsset?: Record<string, unknown>,
  staticResources?: Array<Record<string, unknown>>,
): StaticContent {
  if (!staticAsset && (!staticResources || staticResources.length === 0)) return content
  const next: StaticContent = { ...content }
  const props = isRecord(staticAsset?.properties) ? staticAsset.properties : {}
  const paragraphs = Array.isArray(staticAsset?.paragraphs) ? staticAsset.paragraphs : []
  const paragraphText = paragraphs
    .map((paragraph) => isRecord(paragraph) ? String(paragraph.text ?? paragraph.plain_text ?? '') : '')
    .filter(Boolean)
    .join('\n')

  if (!next.text && paragraphText) next.text = paragraphText
  if (next.richText == null && paragraphs.length > 0) {
    const richText: NonNullable<StaticContent['richText']> = []
    paragraphs.forEach((paragraph) => {
      if (!isRecord(paragraph)) return
      const text = String(paragraph.text ?? paragraph.plain_text ?? '')
      if (!text) return
      richText.push({
        text,
        color: typeof paragraph.color === 'string' ? paragraph.color : undefined,
        fontWeight: typeof paragraph.fontWeight === 'string' ? paragraph.fontWeight : undefined,
        fontStyle: typeof paragraph.fontStyle === 'string' ? paragraph.fontStyle : undefined,
      })
    })
    next.richText = richText
  }

  const shapeType = props.shape_type ?? props.shapeType
  if (!next.shapeType && typeof shapeType === 'string') {
    next.shapeType = normalizeShapeType(shapeType)
  }
  const rotation = props.rotation ?? props.angle
  if (next.rotation == null && typeof rotation === 'number') next.rotation = rotation
  if (next.rotation == null && typeof rotation === 'string' && rotation.trim()) next.rotation = Number(rotation)
  const imageFit = props.image_fit ?? props.fit ?? props.scaling ?? staticResources?.[0]?.scaling
  if (!next.fit && typeof imageFit === 'string') next.fit = normalizeObjectFit(imageFit)
  const imagePosition = props.image_position ?? props.position ?? props.objectPosition
  if (!next.objectPosition && typeof imagePosition === 'string') next.objectPosition = imagePosition
  const resourceUrl = staticResources?.find(resource => typeof resource.url === 'string')?.url
    ?? staticResources?.find(resource => typeof resource.resource === 'string')?.resource
  if (!next.url && typeof resourceUrl === 'string' && /^https?:\/\//i.test(resourceUrl)) next.url = resourceUrl
  return next
}

function normalizeShapeType(value: string): string {
  return value
    .replace(/([a-z])([A-Z])/g, '$1-$2')
    .replace(/_/g, '-')
    .toLowerCase()
}

function normalizeObjectFit(value: string): string {
  const normalized = value.trim().toLowerCase()
  if (normalized === 'fill') return 'fill'
  if (normalized === 'fit' || normalized === 'fit-to-size') return 'contain'
  if (normalized === 'crop' || normalized === 'fill-to-size') return 'cover'
  if (normalized === 'normal') return 'none'
  return normalized
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

// ─── Text Box ────────────────────────────────────────────────────────────────

function TextBoxContent({ content }: { content: StaticContent }) {
  const {
    text = '',
    fontSize = 14,
    fontWeight = 'normal',
    textAlign = 'left',
    color = '#000000',
    backgroundColor = 'transparent',
    richText,
  } = content

  return (
    <div
      className="h-full w-full px-1 overflow-auto whitespace-pre-wrap"
      style={{
        fontSize: `${fontSize}px`,
        fontWeight: fontWeight as React.CSSProperties['fontWeight'],
        textAlign: textAlign as React.CSSProperties['textAlign'],
        color,
        backgroundColor,
      }}
      data-testid="static-textbox"
    >
      {richText && richText.length > 0 ? (
        richText.map((span, index) => (
          <span
            key={`${span.text}-${index}`}
            style={{
              color: span.color,
              fontWeight: span.fontWeight as React.CSSProperties['fontWeight'],
              fontStyle: span.fontStyle as React.CSSProperties['fontStyle'],
            }}
          >
            {span.text}
          </span>
        ))
      ) : text || (
        <span className="text-muted-foreground italic text-xs">
          (empty text box)
        </span>
      )}
    </div>
  )
}

// ─── Button ──────────────────────────────────────────────────────────────────

/** SVG icon paths for Power BI button types */
const BUTTON_TYPE_ICONS: Record<string, React.ReactNode> = {
  'left-arrow': (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-5 w-5 shrink-0">
      <path d="M19 12H5M12 19l-7-7 7-7" />
    </svg>
  ),
  'right-arrow': (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-5 w-5 shrink-0">
      <path d="M5 12h14M12 5l7 7-7 7" />
    </svg>
  ),
  'reset': (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-5 w-5 shrink-0">
      <path d="M3 12a9 9 0 1 1 3 6.7" /><path d="M3 7v5h5" />
    </svg>
  ),
  'back': (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-5 w-5 shrink-0">
      <circle cx="12" cy="12" r="10" /><path d="M14 8l-4 4 4 4" />
    </svg>
  ),
  'information': (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-5 w-5 shrink-0">
      <circle cx="12" cy="12" r="10" /><path d="M12 16v-4M12 8h.01" />
    </svg>
  ),
  'help': (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-5 w-5 shrink-0">
      <circle cx="12" cy="12" r="10" /><path d="M9 9a3 3 0 0 1 5.12 2.13c0 1.6-2.12 2.37-2.12 3.87M12 17h.01" />
    </svg>
  ),
  'bookmark': (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-5 w-5 shrink-0">
      <path d="M19 21l-7-4-7 4V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2v16z" />
    </svg>
  ),
  'apply-all-slicers': (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-5 w-5 shrink-0">
      <rect x="3" y="3" width="7" height="7" rx="1" /><rect x="14" y="3" width="7" height="7" rx="1" /><rect x="3" y="14" width="7" height="7" rx="1" /><path d="M17.5 14l-3.5 4 2 2 5-6" />
    </svg>
  ),
  'clear-all-slicers': (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-5 w-5 shrink-0">
      <rect x="3" y="3" width="7" height="7" rx="1" /><rect x="14" y="3" width="7" height="7" rx="1" /><rect x="3" y="14" width="7" height="7" rx="1" /><path d="M15 15l6 6M21 15l-6 6" />
    </svg>
  ),
  'navigator': (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-5 w-5 shrink-0">
      <rect x="3" y="3" width="7" height="7" /><rect x="14" y="3" width="7" height="7" /><rect x="3" y="14" width="7" height="7" /><rect x="14" y="14" width="7" height="7" />
    </svg>
  ),
}

function ButtonContent({
  content,
  onAction,
}: {
  content: StaticContent
  onAction: (action: StaticAction | undefined) => void
}) {
  const {
    label = 'Button',
    url = '',
    backgroundColor = '#0078d4',
    color = '#ffffff',
    borderRadius = 4,
    buttonType = 'blank',
    action,
  } = content
  const disabledReason = staticActionDisabledReason(action)

  const handleClick = (e: React.MouseEvent<HTMLButtonElement>) => {
    e.stopPropagation()
    if (disabledReason) return
    // Action takes priority
    if (hasRunnableAction(action)) {
      onAction(action)
      return
    }
    // Legacy URL fallback
    if (url) {
      window.open(url, '_blank', 'noopener,noreferrer')
    }
  }

  const icon = BUTTON_TYPE_ICONS[buttonType]

  return (
    <div className="flex items-center justify-center h-full w-full p-2">
      <button
        className={`px-4 py-2 font-medium transition-opacity w-full h-full text-sm flex items-center justify-center gap-2 ${disabledReason ? 'cursor-not-allowed opacity-55' : 'cursor-pointer hover:opacity-90 active:opacity-80'}`}
        style={{
          backgroundColor,
          color,
          borderRadius: `${borderRadius}px`,
          border: 'none',
        }}
        onClick={handleClick}
        onPointerDown={(e) => e.stopPropagation()}
        disabled={Boolean(disabledReason)}
        title={disabledReason}
        data-testid="static-button"
        data-action-type={action?.type}
        data-action-disabled-reason={disabledReason}
      >
        {icon}
        {label}
      </button>
    </div>
  )
}

// ─── Shape ───────────────────────────────────────────────────────────────────

/** SVG definitions for all supported shapes */
function ShapeSVG({ shapeType, fill, stroke, strokeWidth }: {
  shapeType: string; fill: string; stroke: string; strokeWidth: number
}) {
  switch (shapeType) {
    // Rectangles (snip-corner and beveled are SVG)
    case 'snip-corner':
      return (
        <svg width="100%" height="100%" viewBox="0 0 100 100" preserveAspectRatio="none">
          <polygon points="12,0 100,0 100,88 88,100 0,100 0,12" fill={fill} stroke={stroke} strokeWidth={strokeWidth} />
        </svg>
      )
    case 'beveled':
      return (
        <svg width="100%" height="100%" viewBox="0 0 100 100" preserveAspectRatio="none">
          <polygon points="6,0 94,0 100,6 100,94 94,100 6,100 0,94 0,6" fill={fill} stroke={stroke} strokeWidth={strokeWidth} />
        </svg>
      )
    // Basic Shapes
    case 'circle':
      return (
        <svg width="100%" height="100%" viewBox="0 0 100 100" preserveAspectRatio="xMidYMid meet">
          <circle cx="50" cy="50" r="48" fill={fill} stroke={stroke} strokeWidth={strokeWidth} />
        </svg>
      )
    case 'ellipse':
      return (
        <svg width="100%" height="100%" viewBox="0 0 100 100" preserveAspectRatio="none">
          <ellipse cx="50" cy="50" rx="48" ry="35" fill={fill} stroke={stroke} strokeWidth={strokeWidth} />
        </svg>
      )
    case 'triangle':
      return (
        <svg width="100%" height="100%" viewBox="0 0 100 100" preserveAspectRatio="none">
          <polygon points="50,2 98,98 2,98" fill={fill} stroke={stroke} strokeWidth={strokeWidth} />
        </svg>
      )
    case 'diamond':
      return (
        <svg width="100%" height="100%" viewBox="0 0 100 100" preserveAspectRatio="none">
          <polygon points="50,2 98,50 50,98 2,50" fill={fill} stroke={stroke} strokeWidth={strokeWidth} />
        </svg>
      )
    case 'pentagon':
      return (
        <svg width="100%" height="100%" viewBox="0 0 100 100" preserveAspectRatio="none">
          <polygon points="50,2 97,38 79,97 21,97 3,38" fill={fill} stroke={stroke} strokeWidth={strokeWidth} />
        </svg>
      )
    case 'hexagon':
      return (
        <svg width="100%" height="100%" viewBox="0 0 100 100" preserveAspectRatio="none">
          <polygon points="25,2 75,2 98,50 75,98 25,98 2,50" fill={fill} stroke={stroke} strokeWidth={strokeWidth} />
        </svg>
      )
    case 'octagon':
      return (
        <svg width="100%" height="100%" viewBox="0 0 100 100" preserveAspectRatio="none">
          <polygon points="30,2 70,2 98,30 98,70 70,98 30,98 2,70 2,30" fill={fill} stroke={stroke} strokeWidth={strokeWidth} />
        </svg>
      )
    case 'heart':
      return (
        <svg width="100%" height="100%" viewBox="0 0 100 100" preserveAspectRatio="xMidYMid meet">
          <path d="M50 90 C20 60 0 40 10 22 C18 8 35 8 50 25 C65 8 82 8 90 22 C100 40 80 60 50 90Z" fill={fill} stroke={stroke} strokeWidth={strokeWidth} />
        </svg>
      )
    case 'parallelogram':
      return (
        <svg width="100%" height="100%" viewBox="0 0 100 100" preserveAspectRatio="none">
          <polygon points="20,5 98,5 80,95 2,95" fill={fill} stroke={stroke} strokeWidth={strokeWidth} />
        </svg>
      )
    case 'trapezoid':
      return (
        <svg width="100%" height="100%" viewBox="0 0 100 100" preserveAspectRatio="none">
          <polygon points="20,5 80,5 98,95 2,95" fill={fill} stroke={stroke} strokeWidth={strokeWidth} />
        </svg>
      )
    case 'chevron':
      return (
        <svg width="100%" height="100%" viewBox="0 0 100 100" preserveAspectRatio="none">
          <polygon points="0,0 75,0 100,50 75,100 0,100 25,50" fill={fill} stroke={stroke} strokeWidth={strokeWidth} />
        </svg>
      )
    case 'line':
      return (
        <svg width="100%" height="100%" viewBox="0 0 100 100" preserveAspectRatio="none">
          <line x1="2" y1="50" x2="98" y2="50" stroke={stroke} strokeWidth={Math.max(strokeWidth, 2)} />
        </svg>
      )
    // Block arrows
    case 'arrow-right':
      return (
        <svg width="100%" height="100%" viewBox="0 0 100 100" preserveAspectRatio="none">
          <polygon points="0,25 65,25 65,5 100,50 65,95 65,75 0,75" fill={fill} stroke={stroke} strokeWidth={strokeWidth} />
        </svg>
      )
    case 'arrow-left':
      return (
        <svg width="100%" height="100%" viewBox="0 0 100 100" preserveAspectRatio="none">
          <polygon points="100,25 35,25 35,5 0,50 35,95 35,75 100,75" fill={fill} stroke={stroke} strokeWidth={strokeWidth} />
        </svg>
      )
    case 'arrow-up':
      return (
        <svg width="100%" height="100%" viewBox="0 0 100 100" preserveAspectRatio="none">
          <polygon points="25,100 25,35 5,35 50,0 95,35 75,35 75,100" fill={fill} stroke={stroke} strokeWidth={strokeWidth} />
        </svg>
      )
    case 'arrow-down':
      return (
        <svg width="100%" height="100%" viewBox="0 0 100 100" preserveAspectRatio="none">
          <polygon points="25,0 25,65 5,65 50,100 95,65 75,65 75,0" fill={fill} stroke={stroke} strokeWidth={strokeWidth} />
        </svg>
      )
    default:
      return null
  }
}

/** Shape types that render as CSS divs (rectangles) */
const DIV_SHAPES = new Set(['rectangle', 'rounded-rectangle'])

function ShapeContent({
  content,
  onAction,
}: {
  content: StaticContent
  onAction: (action: StaticAction | undefined) => void
}) {
  const {
    shapeType = 'rectangle',
    fill = '#0078d4',
    stroke = '#005a9e',
    strokeWidth = 1,
    opacity = 1.0,
    borderRadius = 0,
    action,
  } = content

  const disabledReason = staticActionDisabledReason(action)
  const hasAction = !disabledReason && hasRunnableAction(action)
  const cursorClass = disabledReason ? 'cursor-not-allowed opacity-55' : hasAction ? 'cursor-pointer' : ''

  const handleClick = (e: React.MouseEvent<HTMLDivElement>) => {
    e.stopPropagation()
    if (hasAction) onAction(action)
  }

  // Div-based rectangle shapes
  if (DIV_SHAPES.has(shapeType)) {
    return (
      <div
        className={`h-full w-full ${cursorClass}`}
        style={{
          backgroundColor: fill,
          border: strokeWidth > 0 ? `${strokeWidth}px solid ${stroke}` : 'none',
          borderRadius: shapeType === 'rounded-rectangle' ? '12px' : `${borderRadius}px`,
          opacity,
        }}
        onClick={handleClick}
        onPointerDown={(e) => e.stopPropagation()}
        data-testid="static-shape"
        data-action-type={action?.type}
        data-action-disabled-reason={disabledReason}
      />
    )
  }

  // SVG-based shapes
  return (
    <div
      className={`h-full w-full flex items-center justify-center p-1 ${cursorClass}`}
      style={{ opacity }}
      onClick={handleClick}
      onPointerDown={(e) => e.stopPropagation()}
      data-testid="static-shape"
      data-action-type={action?.type}
      data-action-disabled-reason={disabledReason}
    >
      <ShapeSVG shapeType={shapeType} fill={fill} stroke={stroke} strokeWidth={strokeWidth} />
    </div>
  )
}

// ─── Image ───────────────────────────────────────────────────────────────────

function ImageContent({ content }: { content: StaticContent }) {
  const {
    url = '',
    alt = '',
    fit = 'contain',
    objectPosition = 'center center',
  } = content

  if (!url) {
    return (
      <div className="flex flex-col items-center justify-center h-full w-full text-muted-foreground gap-2" data-testid="static-image">
        <svg className="h-8 w-8" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
          <rect x="3" y="3" width="18" height="18" rx="2" />
          <circle cx="8.5" cy="8.5" r="1.5" />
          <path d="M21 15l-5-5L5 21" />
        </svg>
        <span className="text-xs">(no image URL)</span>
      </div>
    )
  }

  return (
    <div className="h-full w-full" data-testid="static-image">
      <img
        src={url}
        alt={alt}
        className="w-full h-full"
        style={{ objectFit: fit as React.CSSProperties['objectFit'], objectPosition }}
        onError={(e) => {
          // Show broken image placeholder on load failure
          const target = e.target as HTMLImageElement
          target.style.display = 'none'
          const parent = target.parentElement
          if (parent) {
            const placeholder = document.createElement('div')
            placeholder.className = 'flex items-center justify-center h-full text-muted-foreground text-xs'
            placeholder.textContent = 'Failed to load image'
            parent.appendChild(placeholder)
          }
        }}
      />
    </div>
  )
}

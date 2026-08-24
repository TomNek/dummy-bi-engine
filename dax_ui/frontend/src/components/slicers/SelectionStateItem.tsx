/**
 * SelectionStateItem — Phase 23F
 *
 * A slicer list item that renders in one of three visual states:
 *   - selected (blue highlight, checkmark icon)
 *   - possible (white/normal, no icon)
 *   - excluded (grey + reduced opacity + strikethrough + × icon)
 *
 * Accessibility: State communicated via color AND icon (not color-only).
 * WCAG 2.1 AA contrast. aria-label includes state text.
 * Keyboard: focusable, Enter/Space toggles, Arrow keys handled by parent.
 */
import { forwardRef, useCallback, useEffect, useState } from 'react'
import type { CSSProperties, ReactNode } from 'react'
import { cn } from '@/lib/utils'
import { Checkbox } from '@/components/ui/checkbox'
import { Check, X as XIcon } from 'lucide-react'

export type SelectionState = 'selected' | 'possible' | 'excluded'

export interface SelectionStateItemProps {
  /** Display label */
  label: string
  /** Current selection state */
  state: SelectionState
  /** Whether the checkbox is checked (selected by user) */
  checked: boolean
  /** Optional row count under current selection */
  count?: number
  /** Optional image URL/resource for image-backed slicer items */
  imageUrl?: string
  /** Whether to render a compact fallback when an image resource cannot load */
  imageFallback?: boolean
  /** Source resource id/path for imported report resources */
  imageResource?: string
  /** CSS applied to image-backed slicer item media */
  imageStyle?: CSSProperties
  /** CSS applied to the item row, e.g. imported conditional formatting */
  itemStyle?: CSSProperties
  /** Human-readable conditional-format metadata for tests/inspection */
  conditionalFormat?: string
  /** Normalized image fit metadata for tests/inspection */
  imageFit?: string
  /** Normalized image position metadata for tests/inspection */
  imagePosition?: string
  /** Normalized image saturation metadata for tests/inspection */
  imageSaturation?: string
  /** Optional leading control/icon before checkbox, e.g. hierarchy expander */
  leading?: ReactNode
  /** Hierarchy indentation depth */
  indentLevel?: number
  /** Whether the item is disabled (for example, hierarchy parent when leaf-only is active) */
  disabled?: boolean
  /** Called when the item is toggled */
  onToggle: () => void
  /** data-testid for testing */
  'data-testid'?: string
  /** leaf/provenance flag for hierarchy slicer tests */
  'data-leaf'?: string
  /** hierarchy path/provenance flag for hierarchy slicer tests */
  'data-hierarchy-path'?: string
  /** expanded flag for hierarchy slicer tests */
  'data-expanded'?: string
  /** Index for keyboard navigation */
  tabIndex?: number
  /** Keyboard event handler (delegated from parent for arrow nav) */
  onKeyDown?: (e: React.KeyboardEvent) => void
}

/**
 * Format a count number with locale separators (e.g. 1204 → "1,204").
 */
function formatCount(n: number): string {
  return n.toLocaleString()
}

/**
 * Build an accessible label that includes the value name plus its state.
 */
function buildAriaLabel(label: string, state: SelectionState, count?: number): string {
  const stateText =
    state === 'selected'
      ? 'selected'
      : state === 'excluded'
        ? 'excluded under current selection'
        : 'possible'
  const countText = count !== undefined ? `, ${formatCount(count)} rows` : ''
  return `${label} — ${stateText}${countText}`
}

export const SelectionStateItem = forwardRef<HTMLDivElement, SelectionStateItemProps>(
  function SelectionStateItem(
    {
      label,
      state,
      checked,
      count,
      imageUrl,
      imageFallback = false,
      imageResource,
      imageStyle,
      itemStyle,
      conditionalFormat,
      imageFit,
      imagePosition,
      imageSaturation,
      leading,
      indentLevel = 0,
      disabled = false,
      onToggle,
      tabIndex,
      onKeyDown,
      ...rest
    },
    ref
  ) {
    const [imageFailed, setImageFailed] = useState(false)

    useEffect(() => {
      setImageFailed(false)
    }, [imageUrl])

    const handleKeyDown = useCallback(
      (e: React.KeyboardEvent) => {
        if (disabled) {
          onKeyDown?.(e)
          return
        }
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault()
          onToggle()
        }
        // Delegate arrow / tab to parent handler
        onKeyDown?.(e)
      },
      [disabled, onToggle, onKeyDown]
    )
    const rootStyle: CSSProperties | undefined = itemStyle || indentLevel > 0
      ? {
          ...(itemStyle || {}),
          ...(indentLevel > 0 ? { paddingLeft: `${8 + indentLevel * 14}px` } : {}),
        }
      : undefined
    const fallbackText = label
      .split(/\s+/)
      .map(part => part.charAt(0))
      .join('')
      .slice(0, 2)
      .toUpperCase() || '?'

    return (
      <div
        ref={ref}
        role="option"
        aria-selected={checked ? true : undefined}
        aria-disabled={disabled && !leading ? true : undefined}
        aria-label={buildAriaLabel(label, state, count)}
        tabIndex={tabIndex ?? -1}
        className={cn(
          // Base
          'flex items-center gap-2 px-2 py-1.5 rounded text-xs',
          'transition-all duration-150 ease-in-out',
          'outline-none focus-visible:ring-2 focus-visible:ring-ring',
          disabled ? 'cursor-not-allowed opacity-50' : 'cursor-pointer',
          // State-dependent styling
          state === 'selected' && !disabled && 'bg-accent/50 hover:bg-accent/70',
          state === 'possible' && !disabled && 'hover:bg-accent',
          state === 'excluded' && !checked && !disabled && 'opacity-40 hover:opacity-60'
        )}
        onClick={disabled ? undefined : onToggle}
        onKeyDown={handleKeyDown}
        style={rootStyle}
        data-testid={rest['data-testid']}
        data-leaf={rest['data-leaf']}
        data-hierarchy-path={rest['data-hierarchy-path']}
        data-expanded={rest['data-expanded']}
        data-conditional-format={conditionalFormat}
        data-selection-state={state}
        data-disabled={disabled ? 'true' : 'false'}
      >
        {leading}

        {/* Checkbox — pointer-events-none so clicks pass through to parent div */}
        <Checkbox
          checked={checked}
          className={cn(
            'h-3.5 w-3.5 transition-opacity duration-150 pointer-events-none',
            state === 'excluded' && !checked && 'opacity-50'
          )}
          tabIndex={-1} // managed by parent
          aria-hidden
        />

        {/* State icon — accessibility: not color-only */}
        {state === 'excluded' && !checked && (
          <XIcon
            className="h-3 w-3 text-muted-foreground shrink-0"
            aria-hidden
          />
        )}
        {state === 'selected' && checked && (
          <Check
            className="h-3 w-3 text-primary shrink-0"
            aria-hidden
          />
        )}

        {imageUrl && !imageFailed ? (
          <img
            src={imageUrl}
            alt=""
            className="h-5 w-5 shrink-0 rounded object-cover"
            style={imageStyle}
            loading="lazy"
            onError={() => setImageFailed(true)}
            data-testid={rest['data-testid'] ? `${rest['data-testid']}-image` : undefined}
            data-image-fit={imageFit}
            data-image-position={imagePosition}
            data-image-saturation={imageSaturation}
            data-image-resource={imageResource}
          />
        ) : imageFallback ? (
          <span
            className="flex h-5 w-5 shrink-0 items-center justify-center rounded border bg-muted text-[9px] font-semibold text-muted-foreground"
            style={imageStyle}
            data-testid={rest['data-testid'] ? `${rest['data-testid']}-image-fallback` : undefined}
            data-image-fit={imageFit}
            data-image-position={imagePosition}
            data-image-saturation={imageSaturation}
            data-image-resource={imageResource}
            data-image-fallback="true"
          >
            {fallbackText}
          </span>
        ) : null}

        {/* Label */}
        <span
          className={cn(
            'truncate flex-1 transition-all duration-150',
            state === 'excluded' && !checked && 'line-through text-muted-foreground'
          )}
        >
          {label || '(blank)'}
        </span>

        {/* Count badge */}
        {count !== undefined && (
          <span
            className={cn(
              'text-[10px] tabular-nums text-muted-foreground ml-auto shrink-0',
              'transition-opacity duration-150',
              state === 'excluded' && !checked && 'opacity-60'
            )}
          >
            ({formatCount(count)})
          </span>
        )}
      </div>
    )
  }
)

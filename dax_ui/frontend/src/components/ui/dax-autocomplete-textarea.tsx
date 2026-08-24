/**
 * DaxAutocompleteTextarea — Drop-in replacement for <textarea>/<Textarea>
 * that provides DAX autocomplete.
 *
 * Usage:
 *   <DaxAutocompleteTextarea value={dax} onChange={setDax} ... />
 *
 * The component wraps a <textarea> with a floating popup that shows
 * DAX function, measure, column, and table completions.
 */

import React, { useCallback, useRef, useEffect } from 'react'
import { cn } from '@/lib/utils'
import { useDaxAutocomplete, type AutocompleteItem } from '@/hooks/useDaxAutocomplete'

interface DaxAutocompleteTextareaProps {
  value: string
  onChange: (value: string) => void
  placeholder?: string
  className?: string
  disabled?: boolean
  rows?: number
  'data-testid'?: string
  'aria-label'?: string
  id?: string
}

const KIND_ICONS: Record<string, string> = {
  function: 'ƒ',
  measure: 'M',
  column: 'C',
  table: 'T',
  field_parameter: 'P',
  calculation_group: 'G',
}

const KIND_COLORS: Record<string, string> = {
  function: 'text-blue-600',
  measure: 'text-amber-600',
  column: 'text-green-600',
  table: 'text-purple-600',
  field_parameter: 'text-cyan-600',
  calculation_group: 'text-rose-600',
}

function AutocompletePopup({
  items,
  selectedIndex,
  onSelect,
  listRef,
}: {
  items: AutocompleteItem[]
  selectedIndex: number
  onSelect: (item: AutocompleteItem) => void
  listRef: React.RefObject<HTMLDivElement | null>
}) {
  // Scroll selected item into view
  useEffect(() => {
    const container = listRef.current
    if (!container) return
    const selected = container.children[selectedIndex] as HTMLElement | undefined
    if (selected) {
      selected.scrollIntoView({ block: 'nearest' })
    }
  }, [selectedIndex, listRef])

  return (
    <div
      ref={listRef}
      data-testid="dax-autocomplete-popup"
      className="absolute left-0 right-0 top-full mt-0.5 border border-border bg-popover rounded-md shadow-md max-h-40 overflow-auto z-50"
    >
      {items.map((item, i) => (
        <div
          key={`${item.kind}-${item.text}`}
          data-testid={`dax-autocomplete-item-${i}`}
          className={cn(
            'flex items-center gap-2 px-2 py-1 cursor-pointer text-sm font-mono border-b border-border last:border-b-0',
            i === selectedIndex && 'bg-accent text-accent-foreground'
          )}
          onMouseDown={(e) => {
            e.preventDefault() // prevent blur
            onSelect(item)
          }}
        >
          <span className={cn('w-4 text-center font-bold text-xs', KIND_COLORS[item.kind] || 'text-muted-foreground')}>
            {KIND_ICONS[item.kind] || '?'}
          </span>
          <span className="truncate">{item.text}</span>
        </div>
      ))}
    </div>
  )
}

export function DaxAutocompleteTextarea({
  value,
  onChange,
  placeholder,
  className,
  disabled,
  rows = 3,
  id,
  ...rest
}: DaxAutocompleteTextareaProps) {
  const testId = rest['data-testid']
  const ariaLabel = rest['aria-label']
  const { acState, handleInput, handleKeyDown, insertCompletion, hide, textareaRef } = useDaxAutocomplete()
  const wrapperRef = useRef<HTMLDivElement>(null)
  const listRef = useRef<HTMLDivElement>(null)
  const localRef = useRef<HTMLTextAreaElement>(null)

  // Sync refs
  const setRef = useCallback((el: HTMLTextAreaElement | null) => {
    localRef.current = el
    textareaRef.current = el
  }, [textareaRef])

  const handleChange = useCallback((e: React.ChangeEvent<HTMLTextAreaElement>) => {
    onChange(e.target.value)
    handleInput(e.target)
  }, [onChange, handleInput])

  const onKeyDown = useCallback((e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    handleKeyDown(e)
  }, [handleKeyDown])

  // Hide popup on blur (with small delay so mousedown on popup fires first)
  const handleBlur = useCallback(() => {
    setTimeout(() => {
      hide()
    }, 150)
  }, [hide])

  return (
    <div ref={wrapperRef} className="relative">
      <textarea
        ref={setRef}
        id={id}
        data-testid={testId}
        aria-label={ariaLabel}
        rows={rows}
        className={cn(
          'flex min-h-[80px] w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50',
          className
        )}
        value={value}
        onChange={handleChange}
        onKeyDown={onKeyDown}
        onBlur={handleBlur}
        placeholder={placeholder}
        disabled={disabled}
      />
      {acState.visible && acState.items.length > 0 && (
        <AutocompletePopup
          items={acState.items}
          selectedIndex={acState.index}
          onSelect={insertCompletion}
          listRef={listRef}
        />
      )}
    </div>
  )
}

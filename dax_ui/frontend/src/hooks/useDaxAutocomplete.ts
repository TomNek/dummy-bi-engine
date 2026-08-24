/**
 * useDaxAutocomplete — DAX autocomplete hook
 *
 * Manages prefix extraction, debounced server fetch, keyboard navigation,
 * and completion insertion for DAX textareas.
 *
 * Parity with old UI: dax_ui/static/runtime_modules/model/index.js
 */

import { useState, useCallback, useRef, useEffect } from 'react'
import { getAutocomplete } from '@/lib/api'
import { useAppStore } from '@/stores'

export interface AutocompleteItem {
  kind: 'function' | 'measure' | 'column' | 'table' | 'field_parameter' | 'calculation_group'
  text: string
}

interface AutocompleteState {
  visible: boolean
  items: AutocompleteItem[]
  index: number
  prefix: string
}

const DEBOUNCE_MS = 200
const MAX_ITEMS = 30

/**
 * Extract the DAX prefix from the text at cursor position.
 *
 * Rules (matching old UI):
 * - If `[` is typed → bracket mode → show measures + columns
 * - If inside `[Tok...` → bracketed token
 * - Otherwise: trailing `[A-Za-z_]+` → alphabetic token
 * - Min prefix length: `[` requires 1 char; unbracketed requires 2 chars
 */
function computeDaxPrefix(text: string, cursorPos: number): { prefix: string; replaceLen: number; bracket: boolean } | null {
  const before = text.slice(0, cursorPos)

  // Check if we're inside brackets: find last unmatched [
  const lastOpen = before.lastIndexOf('[')
  const lastClose = before.lastIndexOf(']')

  if (lastOpen > lastClose) {
    // Inside brackets — extract token after [
    const token = before.slice(lastOpen) // includes the [
    return { prefix: token, replaceLen: token.length, bracket: true }
  }

  // Outside brackets — extract trailing alphabetic token
  const match = before.match(/([A-Za-z_]+)$/)
  if (match && match[1].length >= 2) {
    return { prefix: match[1], replaceLen: match[1].length, bracket: false }
  }

  // Bare [ just typed
  if (before.endsWith('[')) {
    return { prefix: '[', replaceLen: 1, bracket: true }
  }

  return null
}

/**
 * Build the autocomplete items list from the server response,
 * matching the old UI's sorting: functions → measures → columns.
 */
function buildItems(
  resp: {
    tables: string[]
    columns: string[]
    measures: string[]
    field_parameters: string[]
    calculation_groups: string[]
    functions: string[]
  },
  bracket: boolean
): AutocompleteItem[] {
  const items: AutocompleteItem[] = []

  // Functions only when not in bracket mode
  if (!bracket) {
    for (const f of resp.functions) {
      items.push({ kind: 'function', text: f })
    }
  }

  // Measures
  for (const m of resp.measures) {
    items.push({ kind: 'measure', text: m })
  }

  // Columns (when not in a bare-bracket-only mode showing measures)
  if (!bracket || resp.columns.length > 0) {
    for (const c of resp.columns) {
      items.push({ kind: 'column', text: c })
    }
  }

  // Tables (when not in bracket mode)
  if (!bracket) {
    for (const t of resp.tables) {
      items.push({ kind: 'table', text: t })
    }
    for (const fp of resp.field_parameters) {
      items.push({ kind: 'field_parameter', text: fp })
    }
    for (const cg of resp.calculation_groups) {
      items.push({ kind: 'calculation_group', text: cg })
    }
  }

  return items.slice(0, MAX_ITEMS)
}

export function useDaxAutocomplete() {
  const [state, setState] = useState<AutocompleteState>({
    visible: false,
    items: [],
    index: 0,
    prefix: '',
  })
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const prefixInfoRef = useRef<{ prefix: string; replaceLen: number; bracket: boolean } | null>(null)
  const textareaRef = useRef<HTMLTextAreaElement | null>(null)

  const projectPath = useAppStore(s => s.projectPath)
  const currentRole = useAppStore(s => s.currentRole)

  const hide = useCallback(() => {
    setState(s => ({ ...s, visible: false, items: [], index: 0 }))
    prefixInfoRef.current = null
  }, [])

  const fetchCompletions = useCallback(async (prefix: string, bracket: boolean) => {
    // Strip leading [ for the server query
    const serverPrefix = bracket ? prefix.replace(/^\[/, '') : prefix
    if (!serverPrefix && !bracket) {
      hide()
      return
    }

    try {
      const resp = await getAutocomplete(
        serverPrefix,
        projectPath || undefined,
        currentRole || undefined
      )
      if (resp.data) {
        const items = buildItems(resp.data, bracket)
        if (items.length > 0) {
          setState({ visible: true, items, index: 0, prefix })
        } else {
          hide()
        }
      } else {
        hide()
      }
    } catch {
      hide()
    }
  }, [projectPath, currentRole, hide])

  const handleInput = useCallback((textarea: HTMLTextAreaElement) => {
    textareaRef.current = textarea
    if (timerRef.current) clearTimeout(timerRef.current)

    timerRef.current = setTimeout(() => {
      const cursorPos = textarea.selectionStart ?? textarea.value.length
      const info = computeDaxPrefix(textarea.value, cursorPos)

      if (!info) {
        hide()
        return
      }

      prefixInfoRef.current = info
      fetchCompletions(info.prefix, info.bracket)
    }, DEBOUNCE_MS)
  }, [fetchCompletions, hide])

  const insertCompletion = useCallback((item: AutocompleteItem) => {
    const ta = textareaRef.current
    const info = prefixInfoRef.current
    if (!ta || !info) return

    let insertText = item.text
    // Functions get a trailing (
    if (item.kind === 'function') {
      insertText += '('
    }

    const cursorPos = ta.selectionStart ?? ta.value.length
    const before = ta.value.slice(0, cursorPos - info.replaceLen)
    const after = ta.value.slice(cursorPos)
    const newValue = before + insertText + after
    const newCursor = before.length + insertText.length

    // Update via native setter to trigger React's onChange
    const nativeInputValueSetter = Object.getOwnPropertyDescriptor(
      window.HTMLTextAreaElement.prototype, 'value'
    )?.set
    if (nativeInputValueSetter) {
      nativeInputValueSetter.call(ta, newValue)
      ta.dispatchEvent(new Event('input', { bubbles: true }))
    }

    // Set cursor position
    requestAnimationFrame(() => {
      ta.setSelectionRange(newCursor, newCursor)
      ta.focus()
    })

    hide()
  }, [hide])

  const handleKeyDown = useCallback((e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (!state.visible) return false

    switch (e.key) {
      case 'ArrowDown':
        e.preventDefault()
        setState(s => ({ ...s, index: Math.min(s.index + 1, s.items.length - 1) }))
        return true
      case 'ArrowUp':
        e.preventDefault()
        setState(s => ({ ...s, index: Math.max(s.index - 1, 0) }))
        return true
      case 'Enter':
      case 'Tab':
        if (state.items[state.index]) {
          e.preventDefault()
          insertCompletion(state.items[state.index])
          return true
        }
        return false
      case 'Escape':
        e.preventDefault()
        hide()
        return true
      default:
        return false
    }
  }, [state.visible, state.items, state.index, insertCompletion, hide])

  // Cleanup timer on unmount
  useEffect(() => {
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current)
    }
  }, [])

  return {
    acState: state,
    handleInput,
    handleKeyDown,
    insertCompletion,
    hide,
    textareaRef,
  }
}

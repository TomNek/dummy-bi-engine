/**
 * MenuBarContext — shared state for hover-to-switch menu bar behavior.
 *
 * When any DropdownMenu is open, hovering over another menu's trigger
 * automatically closes the currently open menu and opens the hovered one,
 * mimicking the standard desktop menu bar UX (Windows, macOS, VS Code, etc.).
 *
 * Strategy:
 * - All DropdownMenus remain **uncontrolled** (no `open` prop). This avoids
 *   fighting with Radix's internal `useControllableState` which fires
 *   `onOpenChange(false)` whenever the prop disagrees with internal state.
 * - The context tracks which menu is currently open via a ref (no re-renders).
 * - On hover-switch, we dispatch a **synthetic `pointerdown`** on the hovered
 *   trigger. Radix's DismissableLayer (capture listener on `document`) sees
 *   this as an outside click and closes the old menu. Then the trigger's own
 *   `onPointerDown` handler fires and opens the new menu.
 */

import { createContext, useContext, useRef, type ReactNode } from 'react'

interface MenuBarContextValue {
  /** Currently open menu name, tracked via ref (no re-render). */
  activeMenuRef: React.MutableRefObject<string | null>
  /** Map of menu name → trigger DOM element. */
  triggerRefs: React.MutableRefObject<Map<string, HTMLButtonElement>>
}

const MenuBarCtx = createContext<MenuBarContextValue | null>(null)

export function MenuBarProvider({ children }: { children: ReactNode }) {
  const activeMenuRef = useRef<string | null>(null)
  const triggerRefs = useRef(new Map<string, HTMLButtonElement>())

  return (
    <MenuBarCtx.Provider value={{ activeMenuRef, triggerRefs }}>
      {children}
    </MenuBarCtx.Provider>
  )
}

/**
 * Hook for individual menus to integrate with the shared menu bar.
 *
 * @param name — unique identifier for this menu (e.g. 'file', 'insert', 'view')
 * @returns callbacks and a ref callback, or `null` if no MenuBarProvider.
 *
 * Usage:
 * ```tsx
 * const menuBar = useMenuBar('file')
 * <DropdownMenu modal={false} onOpenChange={menuBar?.onOpenChange}>
 *   <DropdownMenuTrigger asChild>
 *     <Button ref={menuBar?.triggerRef} onMouseEnter={menuBar?.onTriggerMouseEnter}>
 * ```
 */
export function useMenuBar(name: string) {
  const ctx = useContext(MenuBarCtx)
  if (!ctx) return null

  /** Notify context when this menu opens/closes. */
  const onOpenChange = (isOpen: boolean) => {
    if (isOpen) {
      ctx.activeMenuRef.current = name
    } else if (ctx.activeMenuRef.current === name) {
      ctx.activeMenuRef.current = null
    }
  }

  /** Ref callback to register the trigger DOM element. */
  const triggerRef = (el: HTMLButtonElement | null) => {
    if (el) ctx.triggerRefs.current.set(name, el)
    else ctx.triggerRefs.current.delete(name)
  }

  /**
   * When hovering a trigger while another menu is open, dispatch a synthetic
   * pointerdown on THIS trigger. This causes:
   * 1) Radix's DismissableLayer (capture on document) to detect "outside
   *    interaction" and close the old menu.
   * 2) Radix's trigger handler to fire and toggle this menu open.
   */
  const onTriggerMouseEnter = () => {
    if (ctx.activeMenuRef.current !== null && ctx.activeMenuRef.current !== name) {
      const el = ctx.triggerRefs.current.get(name)
      if (el) {
        el.dispatchEvent(
          new PointerEvent('pointerdown', {
            bubbles: true,
            cancelable: true,
            button: 0,
          })
        )
      }
    }
  }

  return { onOpenChange, onTriggerMouseEnter, triggerRef }
}

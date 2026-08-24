import { useEffect, useCallback, useMemo } from 'react'
import { useAppStore } from '@/stores'

export type ThemeMode = 'light' | 'dark' | 'system'
export type EffectiveTheme = 'light' | 'dark'

/**
 * Theme management hook.
 * Resolves 'system' to the OS preference, applies the `dark` class on <html>,
 * and returns current/effective theme + setter.
 */
export function useTheme() {
  const theme = useAppStore((s) => s.theme)
  const setTheme = useAppStore((s) => s.setTheme)

  // Resolve effective theme (system → OS pref, otherwise direct)
  const effectiveTheme: EffectiveTheme = useMemo(() => {
    if (theme !== 'system') return theme
    if (typeof window === 'undefined') return 'light'
    return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
  }, [theme])

  // Apply dark class on <html>
  useEffect(() => {
    const root = document.documentElement

    const applyTheme = (resolved: EffectiveTheme) => {
      if (resolved === 'dark') {
        root.classList.add('dark')
      } else {
        root.classList.remove('dark')
      }
    }

    if (theme === 'system') {
      // Listen for OS preference changes
      const mq = window.matchMedia('(prefers-color-scheme: dark)')
      const handler = (e: MediaQueryListEvent) => {
        applyTheme(e.matches ? 'dark' : 'light')
      }
      applyTheme(mq.matches ? 'dark' : 'light')
      mq.addEventListener('change', handler)
      return () => mq.removeEventListener('change', handler)
    } else {
      applyTheme(theme)
    }
  }, [theme])

  // Cycle: light → dark → system → light
  const cycleTheme = useCallback(() => {
    const order: ThemeMode[] = ['light', 'dark', 'system']
    const idx = order.indexOf(theme)
    setTheme(order[(idx + 1) % order.length])
  }, [theme, setTheme])

  return { theme, effectiveTheme, setTheme, cycleTheme }
}

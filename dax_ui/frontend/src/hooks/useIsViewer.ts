import { useAppStore } from '@/stores'

/**
 * Returns true when the current user can only view (not edit).
 *
 * This is true when:
 * - Server mode is 'server' AND user role is 'viewer'
 *
 * In author mode (desktop), this always returns false (full editing).
 * On the server, admins and editors can also edit — only viewers are read-only.
 */
export function useIsViewer(): boolean {
  const mode = useAppStore((s) => s.serverMode)
  const role = useAppStore((s) => s.userRole)
  // Desktop mode: never viewer
  if (mode === 'author') return false
  // Server mode: only 'viewer' role is restricted
  return role === 'viewer'
}

/**
 * Returns true when the user has admin privileges.
 * Admins can manage API keys, server config, and edit reports.
 */
export function useIsAdmin(): boolean {
  const mode = useAppStore((s) => s.serverMode)
  const role = useAppStore((s) => s.userRole)
  // Desktop mode: always admin
  if (mode === 'author') return true
  return role === 'admin'
}

/**
 * Returns true when the user can edit reports (admin or editor).
 */
export function useCanEdit(): boolean {
  return !useIsViewer()
}

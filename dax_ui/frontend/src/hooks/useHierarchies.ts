import { useCallback } from 'react'
import { useAppStore } from '@/stores'
import type { HierarchyDef, HierarchiesMap } from '@/lib/api'

export function useHierarchies() {
  const hierarchies = useAppStore(s => s.hierarchies)
  const hierarchiesSaved = useAppStore(s => s.hierarchiesSaved)
  const isHierarchiesDirty = useAppStore(s => s.isHierarchiesDirty)
  const updateHierarchiesDraft = useAppStore(s => s.updateHierarchiesDraft)
  const resetHierarchiesDraft = useAppStore(s => s.resetHierarchiesDraft)

  const applyHierarchy = useCallback((name: string, def: HierarchyDef, previousName?: string) => {
    const nextName = name.trim()
    if (!nextName) return

    const next: HierarchiesMap = { ...hierarchies }
    if (previousName && previousName !== nextName) {
      delete next[previousName]
    }
    next[nextName] = def
    updateHierarchiesDraft(next)
  }, [hierarchies, updateHierarchiesDraft])

  const removeHierarchy = useCallback((name: string) => {
    const next: HierarchiesMap = { ...hierarchies }
    delete next[name]
    updateHierarchiesDraft(next)
  }, [hierarchies, updateHierarchiesDraft])

  const replaceAll = useCallback((next: HierarchiesMap) => {
    updateHierarchiesDraft(next)
  }, [updateHierarchiesDraft])

  return {
    hierarchies,
    hierarchiesSaved,
    isHierarchiesDirty,
    applyHierarchy,
    removeHierarchy,
    replaceAll,
    resetHierarchiesDraft,
  }
}

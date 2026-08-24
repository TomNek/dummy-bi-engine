/**
 * useCalcGroups - Hook for managing Calculation Groups
 * 
 * Calculation Groups allow users to define reusable calculations 
 * that can be applied across measures (like Time Intelligence).
 */

import { useState, useCallback } from 'react'
import { useAppStore } from '@/stores'
import { 
  getCalcGroupSelections,
  updateCalcGroupSelections,
  getRuntimeState,
  getCalculationGroups,
  type CalcGroupMeta,
  type CalcGroupDef,
} from '@/lib/api'

export function useCalcGroups() {
  const projectPath = useAppStore(s => s.projectPath)
  const currentRole = useAppStore(s => s.currentRole)
  
  const [calcGroups, setCalcGroups] = useState<CalcGroupMeta[]>([])
  const [calcGroupDefs, setCalcGroupDefs] = useState<Record<string, CalcGroupDef>>({})
  const [selections, setSelections] = useState<Record<string, string>>({})
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    if (!projectPath) {
      setCalcGroups([])
      setCalcGroupDefs({})
      setSelections({})
      setLoading(false)
      setError(null)
      return
    }
    setLoading(true)
    setError(null)
    try {
      // Fetch calc groups from runtime state, defs from API, and selections
      const [stateResult, defsResult, selectionsResult] = await Promise.all([
        getRuntimeState({ project: projectPath, role: currentRole || undefined }),
        getCalculationGroups(projectPath),
        getCalcGroupSelections(projectPath),
      ])
      
      // Parse calc_groups from runtime state response
      if (stateResult.data?.calc_groups && Array.isArray(stateResult.data.calc_groups)) {
        setCalcGroups(stateResult.data.calc_groups as CalcGroupMeta[])
      }
      
      // Store calculation group defs
      if (defsResult.data) {
        setCalcGroupDefs(defsResult.data.calculation_groups || {})
      }
      
      if (selectionsResult.data) {
        setSelections(selectionsResult.data.selections || {})
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setLoading(false)
    }
  }, [projectPath, currentRole])

  const updateSelection = useCallback(async (groupName: string, itemName: string) => {
    try {
      const newSelections = { ...selections, [groupName]: itemName }
      const result = await updateCalcGroupSelections(newSelections, projectPath || undefined)
      if (result.data) {
        setSelections(result.data.selections || {})
      }
      return { ok: true }
    } catch (err) {
      return { ok: false, error: err instanceof Error ? err.message : String(err) }
    }
  }, [selections, projectPath])

  return {
    calcGroups,
    calcGroupDefs,
    selections,
    loading,
    error,
    load,
    updateSelection,
  }
}

/**
 * useWhatIfParameters - Hook for managing What-If Parameters
 * 
 * What-If Parameters let users create sliders/inputs to dynamically 
 * change numeric values in DAX calculations.
 */

import { useState, useCallback } from 'react'
import { useAppStore } from '@/stores'
import { 
  getWhatIfParameters, 
  updateWhatIfParameters,
  getWhatIfSelections,
  updateWhatIfSelections,
  type WhatIfParameterMeta,
  type WhatIfParameterDef,
} from '@/lib/api'

export function useWhatIfParameters() {
  const projectPath = useAppStore(s => s.projectPath)
  const currentRole = useAppStore(s => s.currentRole)
  
  const [whatIfParams, setWhatIfParams] = useState<WhatIfParameterMeta[]>([])
  const [whatIfDefs, setWhatIfDefs] = useState<Record<string, WhatIfParameterDef>>({})
  const [selections, setSelections] = useState<Record<string, number>>({})
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [paramsResult, selectionsResult] = await Promise.all([
        getWhatIfParameters(projectPath || undefined, currentRole || undefined),
        getWhatIfSelections(projectPath || undefined),
      ])
      
      if (paramsResult.data) {
        setWhatIfParams(paramsResult.data.what_if_parameters || [])
        setWhatIfDefs(paramsResult.data.what_if_parameters_defs || {})
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

  const updateSelection = useCallback(async (paramName: string, value: number) => {
    try {
      const newSelections = { ...selections, [paramName]: value }
      const result = await updateWhatIfSelections(newSelections, projectPath || undefined)
      if (result.data) {
        setSelections(result.data.selections || {})
      }
      return { ok: true }
    } catch (err) {
      return { ok: false, error: err instanceof Error ? err.message : String(err) }
    }
  }, [selections, projectPath])

  const saveDefs = useCallback(async (defs: Record<string, WhatIfParameterDef>) => {
    try {
      const result = await updateWhatIfParameters(defs, projectPath || undefined)
      if (result.data) {
        setWhatIfParams(result.data.what_if_parameters || [])
        setWhatIfDefs(result.data.what_if_parameters_defs || {})
      }
      return { ok: true }
    } catch (err) {
      return { ok: false, error: err instanceof Error ? err.message : String(err) }
    }
  }, [projectPath])

  // Get current value for a parameter (selection or default)
  const getValue = useCallback((paramName: string): number => {
    if (paramName in selections) {
      return selections[paramName]
    }
    const param = whatIfParams.find(p => p.name === paramName)
    return param?.default ?? 0
  }, [selections, whatIfParams])

  return {
    whatIfParams,
    whatIfDefs,
    selections,
    loading,
    error,
    load,
    updateSelection,
    saveDefs,
    getValue,
  }
}

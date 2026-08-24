/**
 * useFieldParameters - Hook for managing Field Parameters
 * 
 * Field Parameters allow users to dynamically switch between different columns/measures in visuals.
 */

import { useState, useCallback } from 'react'
import { useAppStore } from '@/stores'
import { 
  getFieldParameters, 
  updateFieldParameters,
  getFieldParameterSelections,
  updateFieldParameterSelections,
  type FieldParameterMeta,
  type FieldParameterDef,
} from '@/lib/api'

export function useFieldParameters() {
  const projectPath = useAppStore(s => s.projectPath)
  const currentRole = useAppStore(s => s.currentRole)
  
  const [fieldParams, setFieldParams] = useState<FieldParameterMeta[]>([])
  const [fieldParamDefs, setFieldParamDefs] = useState<Record<string, FieldParameterDef>>({})
  const [selections, setSelections] = useState<Record<string, string>>({})
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [paramsResult, selectionsResult] = await Promise.all([
        getFieldParameters(projectPath || undefined, currentRole || undefined),
        getFieldParameterSelections(projectPath || undefined, currentRole || undefined),
      ])
      
      if (paramsResult.data) {
        setFieldParams(paramsResult.data.field_parameters || [])
        setFieldParamDefs(paramsResult.data.field_parameters_defs || {})
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

  const updateSelection = useCallback(async (paramName: string, itemName: string) => {
    try {
      const newSelections = { ...selections, [paramName]: itemName }
      const result = await updateFieldParameterSelections(newSelections, projectPath || undefined)
      if (result.data) {
        setSelections(result.data.selections || {})
      }
      return { ok: true }
    } catch (err) {
      return { ok: false, error: err instanceof Error ? err.message : String(err) }
    }
  }, [selections, projectPath])

  const saveDefs = useCallback(async (defs: Record<string, FieldParameterDef>) => {
    try {
      const result = await updateFieldParameters(defs, projectPath || undefined)
      if (result.data) {
        setFieldParams(result.data.field_parameters || [])
        setFieldParamDefs(result.data.field_parameters_defs || {})
      }
      return { ok: true }
    } catch (err) {
      return { ok: false, error: err instanceof Error ? err.message : String(err) }
    }
  }, [projectPath])

  return {
    fieldParams,
    fieldParamDefs,
    selections,
    loading,
    error,
    load,
    updateSelection,
    saveDefs,
  }
}

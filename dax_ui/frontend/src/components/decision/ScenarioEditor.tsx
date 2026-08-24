/**
 * Phase 18 — Scenario Editor for hypothesis simulation.
 *
 * Allows users to specify driver overrides (delta/target) for existing
 * EDU drivers and run deterministic scenario simulations. Validation-first
 * flow: user must validate before running simulation.
 *
 * State is in-memory only — no persistence without explicit Save.
 */

import { useState, useCallback } from 'react'

export interface DriverOverrideInput {
  driver_id: string
  mode: 'delta' | 'target'
  value: number
}

interface ScenarioEditorProps {
  kpiId: string
  availableDrivers: Array<{ id: string; label: string }>
  onValidate: (overrides: DriverOverrideInput[]) => Promise<{ valid: boolean; reasons: string[] }>
  onRunSimulation: (overrides: DriverOverrideInput[]) => Promise<void>
  disabled?: boolean
}

export function ScenarioEditor({
  kpiId,
  availableDrivers,
  onValidate,
  onRunSimulation,
  disabled = false,
}: ScenarioEditorProps) {
  const [overrides, setOverrides] = useState<DriverOverrideInput[]>([
    { driver_id: availableDrivers.length > 0 ? availableDrivers[0].id : '', mode: 'delta', value: 0 },
  ])
  const [validationErrors, setValidationErrors] = useState<string[]>([])
  const [isValidating, setIsValidating] = useState(false)
  const [isRunning, setIsRunning] = useState(false)
  const [validated, setValidated] = useState(false)

  const handleAddOverride = useCallback(() => {
    setOverrides((prev) => [...prev, { driver_id: '', mode: 'delta', value: 0 }])
    setValidated(false)
  }, [])

  const handleRemoveOverride = useCallback((index: number) => {
    setOverrides((prev) => prev.filter((_, i) => i !== index))
    setValidated(false)
  }, [])

  const handleOverrideChange = useCallback(
    (index: number, field: keyof DriverOverrideInput, value: string | number) => {
      setOverrides((prev) => {
        const next = [...prev]
        next[index] = { ...next[index], [field]: value }
        return next
      })
      setValidated(false)
    },
    []
  )

  const handleValidate = useCallback(async () => {
    setIsValidating(true)
    setValidationErrors([])
    try {
      const result = await onValidate(overrides)
      if (result.valid) {
        setValidated(true)
        setValidationErrors([])
      } else {
        setValidated(false)
        setValidationErrors(result.reasons)
      }
    } catch (err) {
      setValidationErrors([err instanceof Error ? err.message : 'Validation failed'])
    } finally {
      setIsValidating(false)
    }
  }, [overrides, onValidate])

  const handleRun = useCallback(async () => {
    if (!validated) return
    setIsRunning(true)
    try {
      await onRunSimulation(overrides)
    } finally {
      setIsRunning(false)
    }
  }, [validated, overrides, onRunSimulation])

  return (
    <div data-testid="scenario-editor" className="space-y-4 p-4 border rounded-lg bg-card">
      <h3 className="text-sm font-semibold">Scenario Editor</h3>
      <p className="text-xs text-muted-foreground">
        KPI: <span className="font-medium">{kpiId}</span>
      </p>

      <div className="space-y-2">
        {overrides.map((ovr, idx) => (
          <div key={idx} className="flex items-center gap-2" data-testid={`scenario-override-${idx}`}>
            <select
              className="h-8 rounded border bg-background px-2 text-xs flex-1"
              value={ovr.driver_id}
              onChange={(e) => handleOverrideChange(idx, 'driver_id', e.target.value)}
              disabled={disabled}
              data-testid={`scenario-driver-select-${idx}`}
            >
              <option value="">Select driver...</option>
              {availableDrivers.map((d) => (
                <option key={d.id} value={d.id}>
                  {d.label}
                </option>
              ))}
            </select>
            <select
              className="h-8 w-24 rounded border bg-background px-2 text-xs"
              value={ovr.mode}
              onChange={(e) =>
                handleOverrideChange(idx, 'mode', e.target.value as 'delta' | 'target')
              }
              disabled={disabled}
              data-testid={`scenario-mode-select-${idx}`}
            >
              <option value="delta">Delta</option>
              <option value="target">Target</option>
            </select>
            <input
              type="number"
              className="h-8 w-24 rounded border bg-background px-2 text-xs"
              value={ovr.value}
              onChange={(e) => handleOverrideChange(idx, 'value', parseFloat(e.target.value) || 0)}
              disabled={disabled}
              data-testid={`scenario-value-input-${idx}`}
            />
            {overrides.length > 1 && (
              <button
                className="h-8 w-8 rounded border text-xs hover:bg-destructive/10"
                onClick={() => handleRemoveOverride(idx)}
                disabled={disabled}
                title="Remove override"
              >
                ×
              </button>
            )}
          </div>
        ))}
      </div>

      <button
        className="text-xs text-primary underline"
        onClick={handleAddOverride}
        disabled={disabled}
      >
        + Add override
      </button>

      {validationErrors.length > 0 && (
        <div
          data-testid="scenario-validation-errors"
          className="rounded border border-destructive bg-destructive/10 p-2 text-xs text-destructive"
        >
          <p className="font-semibold mb-1">Validation errors:</p>
          <ul className="list-disc pl-4">
            {validationErrors.map((err, i) => (
              <li key={i}>{err}</li>
            ))}
          </ul>
        </div>
      )}

      <div className="flex gap-2">
        <button
          data-testid="scenario-validate-btn"
          className="px-3 py-1.5 text-xs rounded border bg-secondary hover:bg-secondary/80 disabled:opacity-50"
          onClick={handleValidate}
          disabled={disabled || isValidating}
        >
          {isValidating ? 'Validating...' : 'Validate'}
        </button>
        <button
          data-testid="scenario-run-btn"
          className="px-3 py-1.5 text-xs rounded bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
          onClick={handleRun}
          disabled={disabled || !validated || isRunning}
          title={!validated ? 'Validate first before running simulation' : undefined}
        >
          {isRunning ? 'Simulating...' : 'Run Simulation'}
        </button>
      </div>
    </div>
  )
}

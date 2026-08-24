/**
 * Phase 18 — Scenario Panel (composite wrapper).
 *
 * Integrates ScenarioEditor, ScenarioResult, and WhyTracePanel.
 * In-memory state only — no persistence without explicit Save.
 * Hidden when not on a KPI detail page.
 */

import { useState, useCallback } from 'react'
import { ScenarioEditor, type DriverOverrideInput } from './ScenarioEditor'
import { ScenarioResult, type SimulationResultData } from './ScenarioResult'
import { WhyTracePanel, type WhyTraceEntryData } from './WhyTracePanel'

const BASE_URL = '/runtime'

interface ScenarioPanelProps {
  kpiId: string
  availableDrivers: Array<{ id: string; label: string }>
  visible?: boolean
  project?: string
}

interface SimulationAPIResponse {
  ok: boolean
  simulation?: SimulationResultData & {
    why_trace?: WhyTraceEntryData[]
    assumptions?: string[]
  }
  error?: string
  reasons?: string[]
  computability_state?: string
  computability_reasons?: string[]
}

export function ScenarioPanel({
  kpiId,
  availableDrivers,
  visible = true,
  project,
}: ScenarioPanelProps) {
  const [result, setResult] = useState<SimulationResultData | null>(null)
  const [whyTrace, setWhyTrace] = useState<WhyTraceEntryData[]>([])
  const [assumptions, setAssumptions] = useState<string[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const buildBody = useCallback(
    (overrides: DriverOverrideInput[]) => ({
      kpi_id: kpiId,
      overrides: overrides.map((o) => ({
        driver_id: o.driver_id,
        mode: o.mode,
        value: o.value,
      })),
      project: project || undefined,
    }),
    [kpiId, project]
  )

  const handleValidate = useCallback(
    async (overrides: DriverOverrideInput[]) => {
      try {
        const resp = await fetch(`${BASE_URL}/decision/simulate/validate`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(buildBody(overrides)),
        })
        const data = await resp.json()
        if (data.ok) {
          return { valid: true, reasons: [] as string[] }
        }
        return {
          valid: false,
          reasons: data.reasons || [data.error || 'Validation failed'],
        }
      } catch (err) {
        return {
          valid: false,
          reasons: [err instanceof Error ? err.message : 'Validation request failed'],
        }
      }
    },
    [buildBody]
  )

  const handleRun = useCallback(
    async (overrides: DriverOverrideInput[]) => {
      setLoading(true)
      setError(null)
      try {
        const resp = await fetch(`${BASE_URL}/decision/simulate`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(buildBody(overrides)),
        })
        const data: SimulationAPIResponse = await resp.json()
        if (data.ok && data.simulation) {
          setResult(data.simulation)
          setWhyTrace(data.simulation.why_trace || [])
          setAssumptions(data.simulation.assumptions || [])
          setError(null)
        } else {
          // NonComputable or error
          if (data.computability_state === 'NonComputable') {
            setResult({
              projected_kpi_value: 0,
              projected_variance_vs_comparator: 0,
              projected_parent_impacts: [],
              uncertainty_band: 'Wide',
              confidence_tier: 'Low',
              simulation_mode: 'NonComputable',
              computability_state: 'NonComputable',
              computability_reasons: data.computability_reasons || [],
              scenario_status_detail: 'InsufficientData',
              assumptions: [],
            })
            setWhyTrace([])
            setAssumptions([])
          } else {
            setError(data.error || 'Simulation failed')
          }
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Simulation request failed')
      } finally {
        setLoading(false)
      }
    },
    [buildBody]
  )

  if (!visible) return null

  return (
    <div data-testid="scenario-panel" className="space-y-4">
      <ScenarioEditor
        kpiId={kpiId}
        availableDrivers={availableDrivers}
        onValidate={handleValidate}
        onRunSimulation={handleRun}
        disabled={loading}
      />

      {error && (
        <div className="p-2 border border-destructive rounded text-xs text-destructive bg-destructive/5">
          {error}
        </div>
      )}

      <ScenarioResult result={result} loading={loading} />
      <WhyTracePanel trace={whyTrace} assumptions={assumptions} />
    </div>
  )
}

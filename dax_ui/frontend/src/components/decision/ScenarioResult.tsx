/**
 * Phase 18 — Scenario Result display component.
 *
 * Renders projected KPI value, variance, confidence tier, uncertainty band,
 * and parent impact list. Conditional rendering based on computability_state:
 * - Computable: full result surface
 * - Degraded: "Directional Result" banner + wide-band constraints
 * - NonComputable: explicit blocked state with reasons
 */

export interface SimulationResultData {
  projected_kpi_value: number
  projected_variance_vs_comparator: number
  projected_parent_impacts: Array<{
    driver_id: string
    contribution: number
    override_mode: string
    override_value: number
    weight: number
  }>
  uncertainty_band: 'Narrow' | 'Medium' | 'Wide'
  confidence_tier: 'High' | 'Medium' | 'Low'
  simulation_mode: string
  computability_state: 'Computable' | 'Degraded' | 'NonComputable'
  computability_reasons: string[]
  scenario_status_detail: 'Computable' | 'DirectionalOnly' | 'InsufficientData'
  assumptions: string[]
}

interface ScenarioResultProps {
  result: SimulationResultData | null
  loading?: boolean
}

function bandColor(band: string): string {
  switch (band) {
    case 'Narrow':
      return 'text-green-600 bg-green-50 dark:text-green-400 dark:bg-green-950'
    case 'Medium':
      return 'text-yellow-600 bg-yellow-50 dark:text-yellow-400 dark:bg-yellow-950'
    case 'Wide':
      return 'text-red-600 bg-red-50 dark:text-red-400 dark:bg-red-950'
    default:
      return ''
  }
}

function confidenceColor(tier: string): string {
  switch (tier) {
    case 'High':
      return 'text-green-700 dark:text-green-400'
    case 'Medium':
      return 'text-yellow-700 dark:text-yellow-400'
    case 'Low':
      return 'text-red-700 dark:text-red-400'
    default:
      return ''
  }
}

export function ScenarioResult({ result, loading }: ScenarioResultProps) {
  if (loading) {
    return (
      <div data-testid="scenario-result" className="p-4 border rounded-lg bg-card animate-pulse">
        <div className="h-4 bg-muted rounded w-32 mb-2" />
        <div className="h-8 bg-muted rounded w-24" />
      </div>
    )
  }

  if (!result) return null

  const isNonComputable = result.computability_state === 'NonComputable'
  const isDegraded = result.computability_state === 'Degraded'

  // NonComputable: blocked state
  if (isNonComputable) {
    return (
      <div
        data-testid="scenario-result"
        className="p-4 border border-destructive rounded-lg bg-destructive/5"
      >
        <div
          data-testid="scenario-blocked-state"
          className="text-sm font-semibold text-destructive mb-2"
        >
          Simulation Blocked
        </div>
        <p className="text-xs text-muted-foreground mb-2">
          This scenario cannot be computed due to missing prerequisites:
        </p>
        <ul className="list-disc pl-4 text-xs text-destructive">
          {result.computability_reasons.map((reason, i) => (
            <li key={i}>{reason}</li>
          ))}
        </ul>
      </div>
    )
  }

  return (
    <div data-testid="scenario-result" className="p-4 border rounded-lg bg-card space-y-3">
      {/* Directional Result banner for Degraded */}
      {isDegraded && (
        <div
          data-testid="scenario-directional-banner"
          className="px-3 py-1.5 rounded bg-yellow-100 dark:bg-yellow-900 text-yellow-800 dark:text-yellow-200 text-xs font-medium"
        >
          ⚠ Directional Result — confidence is limited; use for directional guidance only.
        </div>
      )}

      {/* Projected Value */}
      <div className="flex items-baseline gap-3">
        <div>
          <p className="text-xs text-muted-foreground">Projected KPI Value</p>
          <p data-testid="scenario-projected-value" className="text-2xl font-bold">
            {result.projected_kpi_value.toLocaleString(undefined, {
              maximumFractionDigits: 2,
            })}
          </p>
        </div>
        <div className="text-right">
          <p className="text-xs text-muted-foreground">Variance</p>
          <p
            className={`text-sm font-medium ${
              result.projected_variance_vs_comparator >= 0 ? 'text-green-600' : 'text-red-600'
            }`}
          >
            {result.projected_variance_vs_comparator >= 0 ? '+' : ''}
            {result.projected_variance_vs_comparator.toLocaleString(undefined, {
              maximumFractionDigits: 2,
            })}
          </p>
        </div>
      </div>

      {/* Confidence & Uncertainty */}
      <div className="flex gap-3">
        <div data-testid="scenario-confidence">
          <span className="text-xs text-muted-foreground mr-1">Confidence:</span>
          <span className={`text-xs font-medium ${confidenceColor(result.confidence_tier)}`}>
            {result.confidence_tier}
          </span>
        </div>
        <div data-testid="scenario-uncertainty-band">
          <span className="text-xs text-muted-foreground mr-1">Uncertainty:</span>
          <span className={`text-xs font-medium px-1.5 py-0.5 rounded ${bandColor(result.uncertainty_band)}`}>
            {result.uncertainty_band}
          </span>
        </div>
      </div>

      {/* Parent Impacts */}
      {result.projected_parent_impacts.length > 0 && (
        <div>
          <p className="text-xs font-medium mb-1">Driver Contributions</p>
          <div className="space-y-1">
            {result.projected_parent_impacts.map((impact, i) => (
              <div
                key={i}
                className="flex justify-between text-xs px-2 py-1 rounded bg-muted/50"
                data-testid={`scenario-impact-${i}`}
              >
                <span>{impact.driver_id}</span>
                <span className="font-mono">
                  {impact.contribution >= 0 ? '+' : ''}
                  {impact.contribution.toFixed(2)}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Simulation mode badge */}
      <div className="text-xs text-muted-foreground">
        Mode: {result.simulation_mode}
      </div>
    </div>
  )
}

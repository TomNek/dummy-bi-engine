/**
 * Phase 18 — Why-Trace Panel.
 *
 * Renders the causal contribution chain from a scenario simulation.
 * Template-driven assumption bullets. Ordered by absolute contribution.
 */

export interface WhyTraceEntryData {
  driver_id: string
  contribution: number
  path: string[]
  description: string
}

interface WhyTracePanelProps {
  trace: WhyTraceEntryData[]
  assumptions: string[]
}

export function WhyTracePanel({ trace, assumptions }: WhyTracePanelProps) {
  if (!trace.length && !assumptions.length) return null

  return (
    <div data-testid="why-trace-panel" className="p-4 border rounded-lg bg-card space-y-3">
      <h4 className="text-sm font-semibold">Why-Trace</h4>

      {trace.length > 0 && (
        <div className="space-y-1">
          {trace.map((entry, i) => (
            <div
              key={i}
              data-testid="why-trace-entry"
              className="p-2 rounded bg-muted/50 text-xs space-y-0.5"
            >
              <div className="flex justify-between">
                <span className="font-medium">{entry.driver_id}</span>
                <span className="font-mono">
                  {entry.contribution >= 0 ? '+' : ''}
                  {entry.contribution.toFixed(4)}
                </span>
              </div>
              <div className="text-muted-foreground">{entry.description}</div>
              {entry.path.length > 0 && (
                <div className="text-muted-foreground/70">
                  Path: {entry.path.join(' → ')}
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {assumptions.length > 0 && (
        <div>
          <p className="text-xs font-medium mb-1">Assumptions</p>
          <ul className="list-disc pl-4 text-xs text-muted-foreground space-y-0.5">
            {assumptions.map((a, i) => (
              <li key={i}>{a}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}

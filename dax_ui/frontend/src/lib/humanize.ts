/**
 * Humanize utility for Decision Intelligence surfaces.
 * Converts internal signal tokens, severity codes, and technical labels
 * into end-user-friendly display text and styling.
 */

// ─── Signal Name Mapping ────────────────────────────────────────────────────

const SIGNAL_DISPLAY_NAMES: Record<string, string> = {
  // ── Canonical v2 signal names ──
  STRUCTURAL: 'Structural',
  EMERGING: 'Emerging',
  TRUST_DOWNGRADE: 'Trust Downgrade',
  VALUE_AT_STAKE: 'Value at Stake',
  // ── Legacy / backward-compat mappings ──
  STRUCTURAL_DETERIORATION: 'Structural',
  HIGH_CONFIDENCE_GROWTH: 'Structural',
  EMERGING_RISK_ACCELERATION: 'Emerging',
  REGIME_SHIFT: 'Regime Shift',
  KPI_TRUST_DOWNGRADE: 'Trust Downgrade',
  VALUE_AT_STAKE_ALERT: 'Value at Stake',
  ATTRIBUTION_BREAKDOWN: 'Attribution Breakdown',
  DRIVER_LEADERSHIP_FLIP: 'Driver Leadership Flip',
  FORECAST_DIVERGENCE: 'Forecast Divergence',
  TREND_REVERSAL: 'Trend Reversal',
  ANOMALY_DETECTED: 'Anomaly Detected',
  RANK_SHIFT: 'Rank Shift',
  VOLATILITY_SPIKE: 'Volatility Spike',
  SEASONAL_DEVIATION: 'Seasonal Deviation',
  BUDGET_OVERRUN: 'Budget Overrun',
  TARGET_MISS: 'Target Miss',
  GROWTH_STALL: 'Growth Stall',
  MARGIN_COMPRESSION: 'Margin Pressure',
  DEMAND_DROP: 'Demand Drop',
  COST_ESCALATION: 'Cost Escalation',
}

/**
 * Converts a raw signal ID (SCREAMING_SNAKE_CASE) to a human-readable label.
 */
export function humanizeSignalName(raw: string): string {
  if (!raw) return 'Unknown Signal'
  const mapped = SIGNAL_DISPLAY_NAMES[raw.toUpperCase()]
  if (mapped) return mapped
  // Fallback: convert SCREAMING_SNAKE_CASE to Title Case
  return raw
    .replace(/_/g, ' ')
    .toLowerCase()
    .replace(/\b\w/g, (c) => c.toUpperCase())
}

// ─── Severity Styling ───────────────────────────────────────────────────────

export interface SeverityStyle {
  bg: string
  text: string
  border: string
  dot: string
  label: string
}

const SEVERITY_STYLES: Record<string, SeverityStyle> = {
  High: {
    bg: '#fef2f2',
    text: '#991b1b',
    border: '#fecaca',
    dot: '#ef4444',
    label: 'High',
  },
  Medium: {
    bg: '#fffbeb',
    text: '#92400e',
    border: '#fde68a',
    dot: '#f59e0b',
    label: 'Medium',
  },
  Low: {
    bg: '#f9fafb',
    text: '#6b7280',
    border: '#e5e7eb',
    dot: '#9ca3af',
    label: 'Low',
  },
}

export function getSeverityStyle(severity: string): SeverityStyle {
  return SEVERITY_STYLES[severity] || SEVERITY_STYLES.Low
}

// ─── Impact Level Styling ───────────────────────────────────────────────────

export interface ImpactStyle {
  bg: string
  text: string
  border: string
  icon: string // emoji/text icon
  label: string
}

const IMPACT_STYLES: Record<string, ImpactStyle> = {
  Critical: {
    bg: '#fef2f2',
    text: '#991b1b',
    border: '#fecaca',
    icon: '⬤',
    label: 'Critical',
  },
  High: {
    bg: '#fff7ed',
    text: '#9a3412',
    border: '#fed7aa',
    icon: '⬤',
    label: 'High',
  },
  Moderate: {
    bg: '#fffbeb',
    text: '#92400e',
    border: '#fde68a',
    icon: '⬤',
    label: 'Moderate',
  },
  Low: {
    bg: '#f0fdf4',
    text: '#166534',
    border: '#bbf7d0',
    icon: '⬤',
    label: 'Low',
  },
}

export function getImpactStyle(impact: string): ImpactStyle {
  return IMPACT_STYLES[impact] || IMPACT_STYLES.Low
}

// ─── Confidence Level Styling ───────────────────────────────────────────────

export interface ConfidenceStyle {
  bg: string
  text: string
  label: string
}

const CONFIDENCE_STYLES: Record<string, ConfidenceStyle> = {
  High: { bg: '#f0fdf4', text: '#166534', label: 'High' },
  Moderate: { bg: '#fffbeb', text: '#92400e', label: 'Moderate' },
  Low: { bg: '#f9fafb', text: '#6b7280', label: 'Low' },
  Uncomputable: { bg: '#f3f4f6', text: '#9ca3af', label: 'Insufficient Data' },
  Unknown: { bg: '#f3f4f6', text: '#9ca3af', label: 'Unknown' },
}

export function getConfidenceStyle(confidence: string): ConfidenceStyle {
  return CONFIDENCE_STYLES[confidence] || CONFIDENCE_STYLES.Unknown
}

// ─── Stability Badge Styling ────────────────────────────────────────────────

export interface StabilityStyle {
  bg: string
  text: string
  label: string
}

const STABILITY_STYLES: Record<string, StabilityStyle> = {
  Stable: { bg: '#f0fdf4', text: '#166534', label: 'Stable' },
  Watch: { bg: '#fffbeb', text: '#92400e', label: 'Watch' },
  Volatile: { bg: '#fef2f2', text: '#991b1b', label: 'Volatile' },
}

export function getStabilityStyle(stability: string): StabilityStyle {
  return STABILITY_STYLES[stability] || { bg: '#f3f4f6', text: '#9ca3af', label: stability || 'N/A' }
}

// ─── Trajectory Display ─────────────────────────────────────────────────────

export interface TrajectoryInfo {
  icon: string
  label: string
  color: string
}

const TRAJECTORY_MAP: Record<string, TrajectoryInfo> = {
  improving: { icon: '↗', label: 'Improving', color: '#16a34a' },
  worsening: { icon: '↘', label: 'Worsening', color: '#dc2626' },
  stable: { icon: '→', label: 'Stable', color: '#6b7280' },
}

export function getTrajectoryInfo(trajectory: string): TrajectoryInfo {
  return TRAJECTORY_MAP[trajectory] || { icon: '?', label: trajectory || 'Unknown', color: '#6b7280' }
}

// ─── Summary Text Generators ────────────────────────────────────────────────

/**
 * Generates a clean, human-readable summary line for the collapsed decision bar.
 */
export function generateDecisionSummary(opts: {
  impact: string
  confidence: string
  signalCount: number
  isNonComputable: boolean
  computabilityReasonText?: string
}): string {
  if (opts.isNonComputable) {
    return opts.computabilityReasonText || 'Insufficient data for analysis'
  }
  const parts: string[] = []
  parts.push(`${opts.impact} impact`)
  if (opts.signalCount > 0) {
    parts.push(`${opts.signalCount} signal${opts.signalCount !== 1 ? 's' : ''} detected`)
  }
  parts.push(`${opts.confidence} confidence`)
  return parts.join('  ·  ')
}

/**
 * Humanizes a data-sufficiency token to user-friendly text.
 */
export function humanizeDataSufficiency(token: string): string {
  const map: Record<string, string> = {
    OK: 'Sufficient',
    'Short History': 'Limited History',
    'Missing Artifact': 'Missing Data',
    Insufficient: 'Insufficient',
  }
  return map[token] || token || 'Unknown'
}

/**
 * Humanizes a computability state for end users.
 */
export function humanizeComputability(state: string, detail?: string): string {
  if (!state) return 'Unknown'
  const lower = state.toLowerCase().replace(/[^a-z]/g, '')
  if (lower === 'computable') return 'Fully Computable'
  if (lower === 'noncomputable') return 'Not Computable'
  if (lower === 'degraded' || lower === 'directionalonly') {
    return detail ? `Directional Only — ${detail}` : 'Directional Only'
  }
  return state
}

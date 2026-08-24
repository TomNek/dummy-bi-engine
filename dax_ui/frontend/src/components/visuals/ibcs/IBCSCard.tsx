/**
 * IBCSCard — IBCS-compliant KPI card / scorecard visual.
 *
 * Features:
 * - Large primary KPI value with label
 * - Scenario codes extracted from column names (AC, PY, BU/BUD, PL, FC)
 * - Colored variance bar (green/red) with ΔAbs and Δ%
 * - Variance arrow indicator (up/down triangle)
 * - Inline sparkline for trend visualization
 * - Supports multiple KPIs in a vertical stack
 * - Invert support (costs: negative delta = good — flips green/red)
 * - Tooltip on hover with full values
 * - Dark mode support
 * - data-testid on all key elements
 */

import { useMemo, useState, useCallback, useRef, useEffect } from 'react'
import {
  IBCS,
  formatCompact,
  formatVariance,
  formatPercent,
  varianceColor,
} from './IBCSChartUtils'
import { IBCSSparkline } from './IBCSSparkline'
import { IBCSBarChart } from './IBCSBarChart'
import { IBCSLineChart } from './IBCSLineChart'
import { IBCSWaterfall } from './IBCSWaterfall'
import {
  humanizeSignalName,
  getSeverityStyle,
  getImpactStyle,
  getConfidenceStyle,
  generateDecisionSummary,
  humanizeComputability,
} from '../../../lib/humanize'

// ─── Props ──────────────────────────────────────────────────────────────────

/**
 * Per-driver entry for the EDU (Executive Driver Ungrouped) summary zone.
 * Describes a single driver contribution to a comparator's variance.
 */
export interface EDUSummaryDriver {
  /** Display label (e.g., "Price", "Volume", "Mix") */
  label: string
  /** Absolute delta contribution (e.g., +30000, -5000) */
  delta: number
  /** Relative delta (0.05 = +5%) — optional */
  relDelta?: number
  /** Per-driver narrative explanation text — optional */
  narrative?: string
}

/**
 * Per-comparator EDU summary, carrying up to 3 drivers.
 * Rendered in Zone 3 of the KPI card.
 */
export interface EDUSummaryEntry {
  /** Comparator scenario code (e.g., "PY", "BUD") */
  comparator: string
  /** Top 2-3 drivers, pre-sorted by |delta| descending */
  drivers: EDUSummaryDriver[]
  /** Root narrative text summarizing overall variance — optional */
  narrative?: string
}

export interface IBCSCardProps {
  columns: string[]
  rows: Array<Record<string, unknown>>
  decisionOverlays?: unknown[]
  packSummary?: Record<string, unknown> | null
  overlayMeta?: Record<string, unknown> | null
  /**
   * Optional EDU summary: top 2-3 drivers per comparator.
   * Rendered in Zone 3 of the card when available.
   * Density rule: max 3 drivers per comparator, no hierarchy.
   */
  eduSummary?: EDUSummaryEntry[] | null
  /** Optional precomputed dataset for embedded generated graphic */
  graphicColumns?: string[]
  graphicRows?: Array<Record<string, unknown>>
  isDark?: boolean
  /** Invert variance colors (for cost metrics: lower is better) */
  invert?: boolean
  /** Optional decorative SVG (URL/data URI/inline SVG markup) */
  graphicSvg?: string
  /** Source mode for optional decorative graphic */
  graphicSourceType?: 'custom' | 'generated'
  /** Optional source visual id for generated mini-visual context */
  graphicVisualId?: string
  /** Generated mini-visual type for card graphic source */
  graphicGeneratedType?: 'ibcs_bar' | 'ibcs_line' | 'ibcs_waterfall'
  /** Optional category label for generated mini-visual when card has no category field */
  graphicCategoryLabel?: string
  /** Optional explicit field encodings for embedded generated graphic */
  graphicEncodingCategory?: Record<string, unknown> | null
  graphicEncodingAC?: Record<string, unknown> | null
  graphicEncodingPY?: Record<string, unknown> | null
  graphicEncodingPL?: Record<string, unknown> | null
  graphicEncodingFC?: Record<string, unknown> | null
  /** Generated mini-visual orientation (for bar) */
  graphicGeneratedOrientation?: 'horizontal' | 'vertical'
  /** Generated mini-visual scenario (for waterfall) */
  graphicGeneratedScenario?: 'ac' | 'py' | 'pl' | 'fc'
  /** Generated mini-visual totals toggle (for waterfall) */
  graphicGeneratedShowTotals?: boolean
  /** IBCS sub-visual format options (same behavior as separate visuals) */
  graphicIbcsMainChartMode?: 'comparison' | 'waterfall'
  graphicIbcsLabelPosition?: 'top-inside' | 'top-outside' | 'middle' | 'bottom'
  graphicIbcsFontSize?: number
  graphicIbcsDataLabelFontSize?: number
  graphicIbcsFontFamily?: string
  graphicIbcsXAxisRotation?: number
  graphicIbcsShowVariancePanels?: boolean
  graphicIbcsWaterfallShowConnectors?: boolean
  graphicIbcsCanvasPaddingH?: number
  graphicIbcsCanvasPaddingV?: number
  /** Request parent editor to open generated IBCS graphic editor */
  onGraphicEditorRequest?: () => void
  /** Optional graphic placement when enabled */
  graphicPosition?: 'top' | 'right' | 'bottom' | 'left'
  /** Decision Intelligence surface placement (default: bottom) */
  diPosition?: 'top' | 'bottom' | 'left' | 'right'
  /** EDU summary zone placement (default: inline below KPI) */
  eduPosition?: 'top' | 'bottom' | 'left' | 'right' | 'inline'
  /** Toggle EDU summary visibility (default: true when data present) */
  showEduSummary?: boolean
  /** Toggle signal chips visibility on DI surface (default: true) */
  showSignals?: boolean
  /** Toggle for decorative graphic rendering */
  showGraphic?: boolean
  /** Optional width constraint */
  width?: number
  /** Optional height constraint */
  height?: number
}

// ─── Internal Types ─────────────────────────────────────────────────────────

interface KPIData {
  label: string
  scenarioCode: string
  value: number
  comparisons: Array<{
    label: string
    scenarioCode: string
    value: number
    delta: number
    deltaPct: number
  }>
  /** Historical values for sparkline (when multi-row data is available) */
  sparklineValues: number[]
}

interface OverlaySignalData {
  signalId: string
  severity: string
}

interface DecisionOverlayData {
  kpiKey: string
  impactLevel: string
  confidenceTier: string
  pattern: string
  stabilityBadge: string
  dataSufficiency: string
  episodeState: string
  computabilityState: string
  scenarioStatusDetail: string
  computabilityReasons: string[]
  rationale: string[]
  rankIndex: number | null
  signals: OverlaySignalData[]
  signalRulesVersion: string
  episodeId: string
  continuityKey: string
  episodeTrajectory: string
  episodeDurationPeriods: number | null
  evidenceBundleId: string
  comparatorSnapshotId: string
  provenanceId: string
  contextFingerprint: string
}

interface PackSummaryData {
  packConfidenceTier: string
  highSeveritySignalCount: number | null
  activeEpisodeCount: number | null
  nonComputableKpiCount: number | null
}

// ─── Helpers ────────────────────────────────────────────────────────────────

/** Extract scenario code from column name: "Revenue AC" → "AC", "GP PY" → "PY" */
function extractScenario(colName: string): string {
  const parts = colName.trim().split(/\s+/)
  const last = parts[parts.length - 1]?.toUpperCase() ?? ''
  if (['AC', 'PY', 'PL', 'BUD', 'FC', 'BU'].includes(last)) return last
  return ''
}

/** Extract metric name without scenario: "Revenue AC" → "Revenue" */
function extractMetricName(colName: string): string {
  const sc = extractScenario(colName)
  if (!sc) return colName
  return colName.replace(new RegExp(`\\s+${sc}$`, 'i'), '').trim()
}

/** Get variance color respecting invert flag */
function getVarianceColor(delta: number, isDark: boolean, invert: boolean): string {
  const effectiveDelta = invert ? -delta : delta
  return varianceColor(effectiveDelta, isDark)
}

function normalizeGraphicSrc(source: string): string {
  const trimmed = source.trim()
  if (!trimmed) return ''
  if (
    trimmed.startsWith('data:image/') ||
    trimmed.startsWith('http://') ||
    trimmed.startsWith('https://') ||
    trimmed.startsWith('/') ||
    trimmed.startsWith('./')
  ) {
    return trimmed
  }
  if (trimmed.startsWith('<svg')) {
    return `data:image/svg+xml;utf8,${encodeURIComponent(trimmed)}`
  }
  return trimmed
}

function asRecord(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null
  return value as Record<string, unknown>
}

function asString(value: unknown): string {
  return typeof value === 'string' ? value.trim() : ''
}

function asNumber(value: unknown): number | null {
  if (typeof value === 'number' && Number.isFinite(value)) return value
  return null
}

function normalizeToken(value: string): string {
  return value.trim().toLowerCase().replace(/[^a-z0-9]/g, '')
}

function toDiReasonCode(value: string): string {
  const normalized = value
    .trim()
    .toUpperCase()
    .replace(/[^A-Z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '')
  if (!normalized) return ''
  return normalized.startsWith('DI_') ? normalized : `DI_${normalized}`
}

function toComputabilityDisplayLabel(rawState: string, rawScenarioDetail: string): string {
  const scenarioDetailKey = normalizeToken(rawScenarioDetail)
  if (scenarioDetailKey === 'directionalonly') return 'Directional Result'
  if (scenarioDetailKey === 'insufficientdata') return 'Insufficient Data'

  const key = normalizeToken(rawState)
  if (key === 'computable') return 'Computable'
  if (key === 'directionalonly' || key === 'directionalresult') return 'Directional Result'
  if (key === 'insufficientdata') return 'Insufficient Data'
  if (key === 'noncomputable') return 'Non-computable'
  if (key === 'degraded') return 'Degraded'
  if (key === 'full') return 'Full'
  return 'Unknown'
}

/**
 * Signal contradiction + priority rules (v2: 4-signal executive model).
 *
 * Canonical signals: STRUCTURAL, EMERGING, TRUST_DOWNGRADE, VALUE_AT_STAKE
 * Deprecated legacy tokens are mapped to canonical equivalents.
 * STRUCTURAL and EMERGING never coexist (contradiction).
 * Priority: VALUE_AT_STAKE > STRUCTURAL > TRUST_DOWNGRADE > EMERGING.
 */
const CANONICAL_SIGNAL_MAP: Record<string, string> = {
  structuraldeterioration: 'structural',
  highconfidencegrowth: 'structural',
  emergingriskacceleration: 'emerging',
  regimeshift: '__internal__',     // internal only — not rendered on card
  kpitrustdowngrade: 'trustdowngrade',
  valueatstakealert: 'valueatstake',
  structural: 'structural',
  emerging: 'emerging',
  trustdowngrade: 'trustdowngrade',
  valueatstake: 'valueatstake',
  trust_downgrade: 'trustdowngrade',
  value_at_stake: 'valueatstake',
}

const SIGNAL_PRIORITY_ORDER: Record<string, number> = {
  valueatstake: 0,
  structural: 1,
  trustdowngrade: 2,
  emerging: 3,
}

function canonicalizeSignalToken(raw: string): string {
  const token = normalizeToken(raw)
  return CANONICAL_SIGNAL_MAP[token] ?? token
}

function applySignalContradictionRules(signals: OverlaySignalData[]): OverlaySignalData[] {
  // Filter out internal-only signals (e.g., REGIME_SHIFT)
  let filtered = signals.filter(s => canonicalizeSignalToken(s.signalId) !== '__internal__')
  // STRUCTURAL and EMERGING cannot coexist — STRUCTURAL wins
  const hasStructural = filtered.some(s => canonicalizeSignalToken(s.signalId) === 'structural')
  if (hasStructural) {
    filtered = filtered.filter(s => canonicalizeSignalToken(s.signalId) !== 'emerging')
  }
  return filtered
}

function severityOrder(value: string): number {
  const key = normalizeToken(value)
  if (key === 'high') return 3
  if (key === 'medium') return 2
  if (key === 'low') return 1
  return 0
}

/**
 * Normalize, deduplicate, apply contradictions, and cap signals to 2.
 * Uses canonical token mapping and priority-based ordering.
 * Density rule: max 2 signals on summary card.
 */
function normalizeOverlaySignals(signals: OverlaySignalData[]): OverlaySignalData[] {
  // Deduplicate by canonical token, keeping highest severity
  const byCanonical = new Map<string, OverlaySignalData>()
  for (const signal of signals) {
    const canon = canonicalizeSignalToken(signal.signalId)
    if (!canon) continue
    const existing = byCanonical.get(canon)
    if (!existing) {
      byCanonical.set(canon, signal)
      continue
    }
    if (severityOrder(signal.severity) > severityOrder(existing.severity)) {
      byCanonical.set(canon, signal)
    }
  }

  const deduped = Array.from(byCanonical.values())
  const nonContradictory = applySignalContradictionRules(deduped)

  // Sort by priority order (VALUE_AT_STAKE > STRUCTURAL > TRUST > EMERGING)
  nonContradictory.sort((left, right) => {
    const lp = SIGNAL_PRIORITY_ORDER[canonicalizeSignalToken(left.signalId)] ?? 99
    const rp = SIGNAL_PRIORITY_ORDER[canonicalizeSignalToken(right.signalId)] ?? 99
    if (lp !== rp) return lp - rp
    return severityOrder(right.severity) - severityOrder(left.severity)
  })

  // Density rule: max 2 signals on summary card
  return nonContradictory.slice(0, 2)
}

function normalizeDecisionOverlays(value: unknown[] | undefined): DecisionOverlayData[] {
  if (!Array.isArray(value)) return []
  const overlays: DecisionOverlayData[] = []
  for (const item of value) {
    const entry = asRecord(item)
    if (!entry) continue
    const simulation = asRecord(entry.simulation)
    const episode = asRecord(entry.episode)
    const evidence = asRecord(entry.evidence)
    const provenance = asRecord(entry.provenance)
    const rawSignals = Array.isArray(entry.signals) ? entry.signals : []
    const signals = rawSignals
      .map((signal): OverlaySignalData | null => {
        const s = asRecord(signal)
        if (!s) return null
        return {
          signalId: asString(s.signal_id || s.signalId),
          severity: asString(s.severity),
        }
      })
      .filter((signal): signal is OverlaySignalData => !!signal)
    const normalizedSignals = normalizeOverlaySignals(signals)
    const scenarioStatusDetail = asString(
      entry.scenario_status_detail ||
      entry.scenarioStatusDetail ||
      simulation?.scenario_status_detail ||
      simulation?.scenarioStatusDetail,
    )

    overlays.push({
      kpiKey: asString(entry.kpi_key || entry.kpiKey),
      impactLevel: asString(entry.impact_level || entry.impactLevel),
      confidenceTier: asString(entry.confidence_tier || entry.confidenceTier),
      pattern: asString(entry.pattern),
      stabilityBadge: asString(entry.stability_badge || entry.stabilityBadge),
      dataSufficiency: asString(entry.data_sufficiency || entry.dataSufficiency),
      episodeState: asString(entry.episode_state || entry.episodeState || episode?.episode_state || episode?.state),
      computabilityState: asString(
        entry.computability_state || entry.computabilityState || simulation?.computability_state || simulation?.computabilityState,
      ),
      scenarioStatusDetail,
      computabilityReasons: Array.isArray(entry.computability_reasons)
        ? entry.computability_reasons.map(asString).filter(Boolean)
        : (Array.isArray(simulation?.computability_reasons)
          ? simulation.computability_reasons.map(asString).filter(Boolean)
          : (Array.isArray(simulation?.computabilityReasons)
            ? simulation.computabilityReasons.map(asString).filter(Boolean)
            : [])),
      rationale: Array.isArray(entry.rationale)
        ? entry.rationale.map(asString).filter(Boolean)
        : [],
      rankIndex: asNumber(entry.rank_index ?? entry.rankIndex),
      signals: normalizedSignals,
      signalRulesVersion: asString(
        entry.signal_rules_version ||
        entry.signalRulesVersion ||
        simulation?.signal_rules_version ||
        simulation?.signalRulesVersion ||
        provenance?.signal_rules_version,
      ),
      episodeId: asString(entry.episode_id || entry.episodeId || episode?.episode_id || episode?.id),
      continuityKey: asString(entry.continuity_key || entry.continuityKey || episode?.continuity_key || episode?.continuityKey),
      episodeTrajectory: asString(entry.trajectory || entry.episode_trajectory || entry.episodeTrajectory || episode?.trajectory),
      episodeDurationPeriods: asNumber(
        entry.duration_periods ?? entry.durationPeriods ?? entry.episode_duration_periods ?? episode?.duration_periods,
      ),
      evidenceBundleId: asString(entry.evidence_bundle_id || entry.evidenceBundleId || evidence?.bundle_id || evidence?.evidence_bundle_id),
      comparatorSnapshotId: asString(
        entry.comparator_snapshot_id || entry.comparatorSnapshotId || evidence?.comparator_snapshot_id || evidence?.snapshot_id,
      ),
      provenanceId: asString(entry.provenance_id || entry.provenanceId || provenance?.id || evidence?.provenance_id),
      contextFingerprint: asString(entry.context_fingerprint || entry.contextFingerprint || provenance?.context_fingerprint),
    })
  }
  return overlays
}

function normalizePackSummary(value: Record<string, unknown> | null | undefined): PackSummaryData | null {
  const entry = asRecord(value)
  if (!entry) return null
  return {
    packConfidenceTier: asString(entry.pack_confidence_tier || entry.packConfidenceTier),
    highSeveritySignalCount: asNumber(entry.high_severity_signal_count ?? entry.highSeveritySignalCount),
    activeEpisodeCount: asNumber(entry.active_episode_count ?? entry.activeEpisodeCount),
    nonComputableKpiCount: asNumber(entry.non_computable_kpi_count ?? entry.nonComputableKpiCount),
  }
}

function matchOverlayForKpi(overlays: DecisionOverlayData[], kpiLabel: string, index: number): DecisionOverlayData | null {
  if (overlays.length === 0) return null
  const target = kpiLabel.trim().toLowerCase()
  if (target) {
    const byLabel = overlays.find(o => o.kpiKey.trim().toLowerCase() === target)
    if (byLabel) return byLabel
  }
  if (index >= 0 && index < overlays.length) return overlays[index]
  return overlays[0] || null
}

// ─── Tooltip Component ──────────────────────────────────────────────────────

interface TooltipState {
  x: number
  y: number
  content: string[]
}

function KPITooltip({ tooltip, isDark }: { tooltip: TooltipState | null; isDark: boolean }) {
  if (!tooltip) return null
  return (
    <div
      data-testid="kpi-tooltip"
      className="fixed z-[9999] pointer-events-none px-3 py-2 rounded shadow-lg text-xs max-w-[280px]"
      style={{
        left: tooltip.x + 12,
        top: tooltip.y - 8,
        backgroundColor: isDark ? '#2a2a2a' : '#fff',
        color: isDark ? '#e0e0e0' : '#333',
        border: `1px solid ${isDark ? '#555' : '#ddd'}`,
      }}
    >
      {tooltip.content.map((line, i) => (
        <div key={i} className={i === 0 ? 'font-semibold mb-1' : ''}>{line}</div>
      ))}
    </div>
  )
}

// ─── Main Component ─────────────────────────────────────────────────────────

export function IBCSCard({
  columns,
  rows,
  decisionOverlays,
  packSummary,
  overlayMeta,
  eduSummary,
  graphicColumns,
  graphicRows,
  isDark = false,
  invert = false,
  graphicSvg,
  graphicSourceType = 'custom',
  graphicVisualId,
  graphicGeneratedType = 'ibcs_bar',
  graphicCategoryLabel,
  graphicEncodingCategory,
  graphicEncodingAC,
  graphicEncodingPY,
  graphicEncodingPL,
  graphicEncodingFC,
  graphicGeneratedOrientation = 'horizontal',
  graphicGeneratedScenario = 'ac',
  graphicGeneratedShowTotals = true,
  graphicIbcsMainChartMode = 'comparison',
  graphicIbcsLabelPosition = 'top-inside',
  graphicIbcsFontSize,
  graphicIbcsDataLabelFontSize,
  graphicIbcsFontFamily,
  graphicIbcsXAxisRotation,
  graphicIbcsShowVariancePanels,
  graphicIbcsWaterfallShowConnectors,
  graphicIbcsCanvasPaddingH,
  graphicIbcsCanvasPaddingV,
  onGraphicEditorRequest,
  graphicPosition = 'bottom',
  diPosition = 'bottom',
  eduPosition = 'inline',
  showEduSummary = true,
  showSignals = true,
  showGraphic = false,
  width,
  height,
}: IBCSCardProps) {
  void overlayMeta
  const [tooltip, setTooltip] = useState<TooltipState | null>(null)
  const containerRef = useRef<HTMLDivElement>(null)
  const [containerSize, setContainerSize] = useState({ w: 0, h: 0 })
  const normalizedOverlays = useMemo(() => normalizeDecisionOverlays(decisionOverlays), [decisionOverlays])
  const normalizedPackSummary = useMemo(() => normalizePackSummary(packSummary), [packSummary])
  const [hoveredOverlayIndex, setHoveredOverlayIndex] = useState<number | null>(null)
  const [pinnedOverlayIndex, setPinnedOverlayIndex] = useState<number | null>(null)

  // ResizeObserver for responsive sizing
  useEffect(() => {
    if (width && height) {
      setContainerSize({ w: width, h: height })
      return
    }
    const el = containerRef.current
    if (!el) return
    const ro = new ResizeObserver((entries) => {
      const entry = entries[0]
      if (entry) {
        setContainerSize({
          w: entry.contentRect.width,
          h: entry.contentRect.height,
        })
      }
    })
    ro.observe(el)
    return () => ro.disconnect()
  }, [width, height])

  // Parse KPIs from data
  const kpis = useMemo<KPIData[]>(() => {
    if (rows.length === 0 || columns.length === 0) return []

    // Determine if first column is a category (non-numeric) or a value
    const firstVal = rows[0]?.[columns[0]]
    const hasCategory = typeof firstVal === 'string' && isNaN(Number(firstVal))
    const valueCols = hasCategory ? columns.slice(1) : columns

    // Single-row: group columns by metric name
    if (rows.length === 1) {
      const row = rows[0]

      // If we have multiple value columns, first is primary (AC), rest are comparisons
      if (valueCols.length >= 2) {
        const primary = valueCols[0]
        const acVal = Number(row[primary] ?? 0)
        const metricName = extractMetricName(primary)
        const comparisons = valueCols.slice(1).map(col => {
          const cVal = Number(row[col] ?? 0)
          const delta = acVal - cVal
          const deltaPct = cVal !== 0 ? delta / Math.abs(cVal) : 0
          return {
            label: col,
            scenarioCode: extractScenario(col),
            value: cVal,
            delta,
            deltaPct,
          }
        })
        return [{
          label: metricName || primary,
          scenarioCode: extractScenario(primary),
          value: acVal,
          comparisons,
          sparklineValues: [],
        }]
      }

      // Single value column
      const val = Number(row[valueCols[0]] ?? 0)
      return [{
        label: extractMetricName(valueCols[0] ?? columns[0]),
        scenarioCode: extractScenario(valueCols[0] ?? columns[0]),
        value: val,
        comparisons: [],
        sparklineValues: [],
      }]
    }

    // Multi-row: each row is a KPI
    const catCol = columns[0]
    // Collect sparkline values from the primary value column across all rows
    const allPrimaryValues = rows.map(r => Number(r[valueCols[0]] ?? 0))

    return rows.map((row, idx) => {
      const label = String(row[catCol] ?? '')
      const acVal = Number(row[valueCols[0]] ?? 0)
      const comparisons = valueCols.slice(1).map(col => {
        const cVal = Number(row[col] ?? 0)
        const delta = acVal - cVal
        const deltaPct = cVal !== 0 ? delta / Math.abs(cVal) : 0
        return {
          label: col,
          scenarioCode: extractScenario(col),
          value: cVal,
          delta,
          deltaPct,
        }
      })
      return {
        label,
        scenarioCode: extractScenario(valueCols[0]),
        value: acVal,
        comparisons,
        // For multi-row, each KPI gets sparkline of values up to its position
        sparklineValues: allPrimaryValues.slice(0, idx + 1),
      }
    })
  }, [columns, rows])

  // Tooltip handlers
  const showTooltip = useCallback((e: React.MouseEvent, kpi: KPIData) => {
    const lines = [`${kpi.label} (${kpi.scenarioCode || 'AC'})`]
    lines.push(`Value: ${kpi.value.toLocaleString()}`)
    for (const cmp of kpi.comparisons) {
      lines.push(`vs ${cmp.scenarioCode || cmp.label}: ${cmp.value.toLocaleString()} (Δ ${cmp.delta >= 0 ? '+' : ''}${cmp.delta.toLocaleString()}, ${(cmp.deltaPct * 100).toFixed(1)}%)`)
    }
    setTooltip({ x: e.clientX, y: e.clientY, content: lines })
  }, [])

  const hideTooltip = useCallback(() => setTooltip(null), [])

  // Color tokens
  const txtPrimary = isDark ? IBCS.dark.textPrimary : IBCS.textPrimary
  const txtSecondary = isDark ? IBCS.dark.textSecondary : IBCS.textSecondary
  const txtMuted = isDark ? IBCS.dark.textMuted : IBCS.textMuted
  const gridColor = isDark ? IBCS.dark.gridLine : IBCS.gridLine

  // ─── Zone 3: EDU Summary (top drivers per comparator) ──────────────────
  const renderEDUSummary = useCallback(() => {
    if (!showEduSummary || !eduSummary || eduSummary.length === 0) return null
    return (
      <div
        data-testid="kpi-edu-summary"
        style={{
          display: 'flex',
          flexDirection: 'column',
          gap: 6,
          padding: '6px 0',
          borderTop: `1px solid ${gridColor}`,
          borderBottom: `1px solid ${gridColor}`,
          marginTop: 4,
          marginBottom: 2,
        }}
      >
        {eduSummary.map((entry) => (
          <div
            key={entry.comparator}
            data-testid="kpi-edu-comparator"
            style={{ display: 'flex', flexDirection: 'column', gap: 4 }}
          >
            {/* Root narrative */}
            {entry.narrative && (
              <div
                data-testid="kpi-edu-narrative"
                style={{
                  fontSize: 11,
                  lineHeight: 1.4,
                  color: txtSecondary,
                  padding: '2px 0',
                }}
              >
                {entry.narrative}
              </div>
            )}
            {/* Driver chips */}
            <div
              style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 11 }}
            >
              <span
                style={{
                  fontWeight: 600,
                  color: txtMuted,
                  textTransform: 'uppercase' as const,
                  width: 28,
                  textAlign: 'center' as const,
                  flexShrink: 0,
                  fontSize: 10,
                }}
              >
                {entry.comparator}
              </span>
              <span
                data-testid="kpi-edu-drivers"
                style={{
                  display: 'flex',
                  gap: 8,
                  color: txtSecondary,
                  flexWrap: 'wrap' as const,
                }}
              >
                {entry.drivers.slice(0, 3).map((drv, di) => {
                  const sign = drv.delta >= 0 ? '+' : ''
                  const color = drv.delta >= 0 ? '#16a34a' : '#dc2626'
                  return (
                    <span key={di} style={{ whiteSpace: 'nowrap' as const }}>
                      <span style={{ color: txtSecondary }}>{drv.label}</span>
                      {' '}
                      <span style={{ color, fontWeight: 500, fontVariantNumeric: 'tabular-nums' }}>
                        {sign}{formatCompact(drv.delta)}
                      </span>
                    </span>
                  )
                })}
              </span>
            </div>
            {/* Per-driver narrative details */}
            {entry.drivers.some(d => d.narrative) && (
              <div
                data-testid="kpi-edu-driver-narratives"
                style={{
                  display: 'flex',
                  flexDirection: 'column',
                  gap: 3,
                  paddingLeft: 28,
                  marginTop: 2,
                }}
              >
                {entry.drivers.filter(d => d.narrative).slice(0, 3).map((drv, di) => (
                  <div
                    key={di}
                    style={{
                      fontSize: 10,
                      lineHeight: 1.35,
                      color: txtMuted,
                    }}
                  >
                    {drv.narrative}
                  </div>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>
    )
  }, [showEduSummary, eduSummary, gridColor, txtMuted, txtSecondary])

  // ─── Zone 4: Decision Intelligence Surface ─────────────────────────────

  const renderDecisionSurface = useCallback((kpi: KPIData, index: number) => {
    const overlay = matchOverlayForKpi(normalizedOverlays, kpi.label, index)
    if (!overlay) return null

    const isOpen = hoveredOverlayIndex === index || pinnedOverlayIndex === index
    const panelId = `kpi-decision-panel-${index}`
    const fullSignals = overlay.signals
    const confidence = overlay.confidenceTier || 'Unknown'
    const impact = overlay.impactLevel || 'Unknown'
    const computabilityToken = normalizeToken(overlay.computabilityState)
    const scenarioDetailToken = normalizeToken(overlay.scenarioStatusDetail)
    const isNonComputable = (
      computabilityToken === 'noncomputable'
      || computabilityToken === 'insufficientdata'
      || scenarioDetailToken === 'insufficientdata'
    )
    const compactSignals = (!isNonComputable && showSignals) ? fullSignals : []

    const computabilityReasonText = isNonComputable
      ? 'Insufficient data for analysis'
      : (computabilityToken === 'degraded'
        ? 'Directional result only — limited confidence'
        : '')

    const summaryText = generateDecisionSummary({
      impact,
      confidence,
      signalCount: compactSignals.length,
      isNonComputable,
      computabilityReasonText,
    })

    const impactStyle = getImpactStyle(impact)
    const confStyle = getConfidenceStyle(confidence)

    return (
      <div className="w-full mt-2" data-testid="kpi-decision-container">
        {/* ─── Clean Summary Bar ─── */}
        <button
          type="button"
          className="w-full text-left rounded-lg px-3 py-2 text-xs flex items-center gap-3 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-1 transition-colors"
          style={{
            backgroundColor: isOpen ? impactStyle.bg : '#fafafa',
            borderLeft: `3px solid ${impactStyle.border}`,
            border: `1px solid ${isOpen ? impactStyle.border : '#e5e7eb'}`,
            borderLeftWidth: 3,
            borderLeftColor: impactStyle.border,
            color: '#374151',
          }}
          data-testid="kpi-decision-summary"
          aria-label={`Decision summary for ${kpi.label}: ${summaryText}. ${isOpen ? 'Collapse' : 'Expand'} details.`}
          title={`Click to ${isOpen ? 'collapse' : 'expand'} decision details`}
          aria-expanded={isOpen}
          aria-controls={panelId}
          onMouseEnter={() => setHoveredOverlayIndex(index)}
          onMouseLeave={() => setHoveredOverlayIndex(current => (current === index ? null : current))}
          onFocus={() => setHoveredOverlayIndex(index)}
          onBlur={() => setHoveredOverlayIndex(current => (current === index ? null : current))}
          onClick={() => {
            setPinnedOverlayIndex(current => (current === index ? null : index))
          }}
        >
          {/* Impact dot */}
          <span
            style={{
              width: 8,
              height: 8,
              borderRadius: '50%',
              backgroundColor: impactStyle.border,
              flexShrink: 0,
            }}
            data-testid="kpi-decision-summary-impact"
          />
          {/* Summary text */}
          <span className="truncate flex-1" style={{ fontWeight: 500 }}>
            {summaryText}
          </span>
          {/* Signal count badge */}
          {!isNonComputable && compactSignals.length > 0 && (
            <span
              data-testid="kpi-decision-summary-signals"
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: 2,
                flexShrink: 0,
              }}
            >
              {compactSignals.map((sig) => {
                const sev = getSeverityStyle(sig.severity)
                return (
                  <span
                    key={sig.signalId}
                    style={{
                      width: 6,
                      height: 6,
                      borderRadius: '50%',
                      backgroundColor: sev.dot,
                    }}
                    title={humanizeSignalName(sig.signalId)}
                  />
                )
              })}
            </span>
          )}
          {/* Confidence badge */}
          <span
            data-testid="kpi-decision-summary-confidence"
            style={{
              padding: '1px 6px',
              borderRadius: 4,
              fontSize: 10,
              fontWeight: 600,
              backgroundColor: confStyle.bg,
              color: confStyle.text,
              flexShrink: 0,
              letterSpacing: '0.02em',
            }}
          >
            {confStyle.label}
          </span>
          {/* Chevron */}
          <span style={{ color: '#9ca3af', fontSize: 10, flexShrink: 0 }}>
            {isOpen ? '▲' : '▼'}
          </span>
        </button>

        {/* ─── Expanded Detail Panel ─── */}
        {isOpen && (
          <div
            className="mt-1 rounded-lg overflow-hidden"
            style={{ border: `1px solid ${impactStyle.border}`, backgroundColor: '#fff' }}
            data-testid="kpi-decision-panel"
            id={panelId}
          >
            {/* Top status row */}
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 10,
                padding: '10px 14px',
                backgroundColor: impactStyle.bg,
                borderBottom: `1px solid ${impactStyle.border}`,
              }}
              data-testid="decision-context-block"
            >
              <span
                data-testid="kpi-decision-impact"
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: 4,
                  padding: '3px 10px',
                  borderRadius: 6,
                  fontSize: 12,
                  fontWeight: 600,
                  backgroundColor: impactStyle.border,
                  color: impactStyle.text,
                }}
              >
                {impact} Impact
              </span>
              <span
                data-testid="kpi-decision-confidence"
                style={{
                  padding: '3px 10px',
                  borderRadius: 6,
                  fontSize: 12,
                  fontWeight: 500,
                  backgroundColor: confStyle.bg,
                  color: confStyle.text,
                  border: `1px solid ${confStyle.bg}`,
                }}
              >
                {confidence} Confidence
              </span>
              <span
                data-testid="kpi-decision-computability"
                style={{
                  marginLeft: 'auto',
                  fontSize: 11,
                  color: '#6b7280',
                  fontStyle: 'italic',
                }}
              >
                <span data-testid="kpi-computability-label">
                  {humanizeComputability(overlay.computabilityState, overlay.scenarioStatusDetail)}
                </span>
              </span>
            </div>

            <div style={{ padding: '12px 14px' }}>
              {/* Rationale block */}
              {overlay.rationale.length > 0 && (
                <div
                  data-testid="kpi-decision-rationale"
                  style={{
                    padding: '8px 12px',
                    borderRadius: 8,
                    backgroundColor: '#f9fafb',
                    borderLeft: '3px solid #d1d5db',
                    fontSize: 12,
                    color: '#4b5563',
                    lineHeight: 1.5,
                    fontStyle: 'italic',
                    marginBottom: 12,
                  }}
                >
                  {overlay.rationale.join(' · ')}
                </div>
              )}

              {/* Signal chips (humanized) */}
              {!isNonComputable && fullSignals.length > 0 && (
                <div data-testid="signals-panel" style={{ marginBottom: 12 }}>
                  <div style={{
                    fontSize: 11,
                    fontWeight: 600,
                    color: '#6b7280',
                    textTransform: 'uppercase' as const,
                    letterSpacing: '0.05em',
                    marginBottom: 6,
                  }}>
                    Active Signals
                  </div>
                  <div
                    data-testid="kpi-decision-signals-full"
                    style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}
                  >
                    {fullSignals.map(signal => {
                      const sev = getSeverityStyle(signal.severity)
                      return (
                        <span
                          key={signal.signalId}
                          style={{
                            display: 'inline-flex',
                            alignItems: 'center',
                            gap: 5,
                            padding: '3px 10px',
                            borderRadius: 14,
                            fontSize: 11,
                            fontWeight: 500,
                            backgroundColor: sev.bg,
                            color: sev.text,
                            border: `1px solid ${sev.border}`,
                          }}
                        >
                          <span style={{
                            width: 6,
                            height: 6,
                            borderRadius: '50%',
                            backgroundColor: sev.dot,
                          }} />
                          {humanizeSignalName(signal.signalId)}
                          <span style={{ fontSize: 9, opacity: 0.7, fontWeight: 600 }}>{signal.severity}</span>
                        </span>
                      )
                    })}
                  </div>
                </div>
              )}

              {/* Non-computable notice */}
              {isNonComputable && computabilityReasonText && (
                <div
                  data-testid="kpi-decision-computability-reason"
                  style={{
                    padding: '8px 12px',
                    borderRadius: 8,
                    backgroundColor: '#f3f4f6',
                    fontSize: 12,
                    color: '#6b7280',
                    marginBottom: 12,
                    textAlign: 'center' as const,
                  }}
                >
                  {computabilityReasonText}
                </div>
              )}

              {/* Episode summary (if present) — clean, no IDs */}
              {overlay.episodeState && (
                <div data-testid="evidence-episode-panel" style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 10,
                  padding: '8px 12px',
                  borderRadius: 8,
                  backgroundColor: '#f9fafb',
                  fontSize: 12,
                  color: '#4b5563',
                  marginBottom: 8,
                }}>
                  <span data-testid="kpi-decision-episode" style={{ fontWeight: 500 }}>
                    Episode: {overlay.episodeState}
                  </span>
                  {overlay.episodeTrajectory && (
                    <span data-testid="kpi-decision-episode-trajectory" style={{ color: '#6b7280' }}>
                      · {overlay.episodeTrajectory}
                    </span>
                  )}
                  {overlay.episodeDurationPeriods != null && (
                    <span data-testid="kpi-decision-episode-duration" style={{ color: '#9ca3af' }}>
                      · {overlay.episodeDurationPeriods} period{overlay.episodeDurationPeriods !== 1 ? 's' : ''}
                    </span>
                  )}
                  {!isNonComputable && overlay.pattern && (
                    <span data-testid="kpi-decision-pattern" style={{ color: '#9ca3af', marginLeft: 'auto' }}>
                      {overlay.pattern}
                    </span>
                  )}
                </div>
              )}

              {/* Pack summary (first KPI only) */}
              {index === 0 && normalizedPackSummary && (
                <div data-testid="kpi-decision-pack-summary" style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 8,
                  fontSize: 11,
                  color: '#9ca3af',
                  paddingTop: 4,
                }}>
                  <span data-testid="kpi-decision-pack-summary-confidence-tier" style={{
                    padding: '1px 6px',
                    borderRadius: 4,
                    backgroundColor: '#f3f4f6',
                    fontWeight: 500,
                  }}>
                    {normalizedPackSummary.packConfidenceTier || 'Unknown'} confidence
                  </span>
                  {normalizedPackSummary.highSeveritySignalCount != null && (
                    <span data-testid="kpi-decision-pack-summary-high-severity-signal-count">
                      {normalizedPackSummary.highSeveritySignalCount} high-severity
                    </span>
                  )}
                  {normalizedPackSummary.activeEpisodeCount != null && (
                    <span data-testid="kpi-decision-pack-summary-active-episode-count">
                      · {normalizedPackSummary.activeEpisodeCount} episode{normalizedPackSummary.activeEpisodeCount !== 1 ? 's' : ''}
                    </span>
                  )}
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    )
  }, [gridColor, hoveredOverlayIndex, normalizedOverlays, normalizedPackSummary, pinnedOverlayIndex, txtSecondary])

  // Compact mode when container is small
  const isCompact = containerSize.w > 0 && containerSize.w < 250

  const graphicSrc = useMemo(() => {
    if (!showGraphic) return ''
    if (graphicSourceType === 'generated') return ''
    if (!graphicSvg) return ''
    return normalizeGraphicSrc(graphicSvg)
  }, [showGraphic, graphicSvg, graphicSourceType])
  const hasGeneratedGraphic = showGraphic && graphicSourceType === 'generated'
  const hasImageGraphic = graphicSrc.length > 0
  const hasGraphic = hasGeneratedGraphic || hasImageGraphic

  const isHorizontalGraphic = graphicPosition === 'left' || graphicPosition === 'right'
  const isHorizontalDI = diPosition === 'left' || diPosition === 'right'
  const isHorizontalEdu = eduPosition === 'left' || eduPosition === 'right'
  const isEduInline = eduPosition === 'inline'

  const graphicSlotClass = useMemo(() => {
    if (graphicPosition === 'left' || graphicPosition === 'right') {
      return 'w-[48%] min-w-[120px] max-w-[360px] self-stretch'
    }
    return 'w-full flex-1 min-h-[72px]'
  }, [graphicPosition])

  // ─── EDU Summary as standalone slot (non-inline positions) ─────────────
  const renderEduSlot = useCallback(() => {
    if (isEduInline) return null
    const eduContent = renderEDUSummary()
    if (!eduContent) return null
    return (
      <div
        className={isHorizontalEdu
          ? 'flex flex-col gap-1 overflow-auto flex-shrink-0'
          : 'w-full flex-shrink-0'}
        style={isHorizontalEdu ? {
          width: '30%',
          minWidth: 120,
          maxWidth: 220,
          flexShrink: 0,
        } : undefined}
        data-testid="kpi-edu-slot"
        data-edu-position={eduPosition}
      >
        {eduContent}
      </div>
    )
  }, [isEduInline, isHorizontalEdu, eduPosition, renderEDUSummary])

  // Render multi-KPI DI surfaces collected (for extraction from body)
  const renderAllDecisionSurfaces = useCallback((kpis: KPIData[]) => {
    const surfaces = kpis.map((kpi, i) => renderDecisionSurface(kpi, i)).filter(Boolean)
    if (surfaces.length === 0) return null
    return (
      <div
        className={isHorizontalDI ? 'flex flex-col gap-1 overflow-auto' : 'w-full flex flex-col gap-1'}
        style={isHorizontalDI ? {
          width: '40%',
          minWidth: 180,
          maxWidth: 280,
          flexShrink: 0,
        } : undefined}
        data-testid="kpi-decision-surface-slot"
      >
        {surfaces}
      </div>
    )
  }, [isHorizontalDI, renderDecisionSurface])

  const renderGraphicContent = useCallback(() => {
    if (!hasGraphic) return null

    if (hasGeneratedGraphic) {
      const generatedRows = (graphicRows && graphicRows.length > 0) ? graphicRows : rows
      const generatedColumns = (graphicColumns && graphicColumns.length > 0) ? graphicColumns : columns
      if (generatedRows.length === 0 || generatedColumns.length === 0) return null

      const normalizeName = (value: string): string => value.toLowerCase().replace(/[^a-z0-9]/g, '')
      const resolveEncodingName = (expr: Record<string, unknown> | null | undefined): string | undefined => {
        if (!expr || typeof expr !== 'object') return undefined
        const table = typeof expr.table === 'string' ? expr.table : undefined
        const column = typeof expr.column === 'string' ? expr.column : undefined
        const measure = typeof expr.measure === 'string' ? expr.measure : undefined
        const name = typeof expr.name === 'string' ? expr.name : undefined

        const candidates = [
          column,
          measure,
          name,
          table && column ? `${table}[${column}]` : undefined,
          table && column ? `${table}.${column}` : undefined,
          table && column ? `${table}_${column}` : undefined,
        ].filter((value): value is string => !!value)

        for (const candidate of candidates) {
          if (generatedColumns.includes(candidate)) return candidate
        }

        for (const candidate of candidates) {
          const match = generatedColumns.find((col) => col.toLowerCase() === candidate.toLowerCase())
          if (match) return match
        }

        for (const candidate of candidates) {
          const normalizedCandidate = normalizeName(candidate)
          const match = generatedColumns.find((col) => normalizeName(col) === normalizedCandidate)
          if (match) return match
        }

        if (column) {
          const columnLower = column.toLowerCase()
          const suffixMatch = generatedColumns.find((col) => {
            const lower = col.toLowerCase()
            return lower.endsWith(`[${columnLower}]`) || lower.endsWith(`.${columnLower}`) || lower.endsWith(`_${columnLower}`)
          })
          if (suffixMatch) return suffixMatch
        }

        return candidates[0]
      }

      const encodedCategory = resolveEncodingName(graphicEncodingCategory)
      const encodedSeries = [
        resolveEncodingName(graphicEncodingAC),
        resolveEncodingName(graphicEncodingPY),
        resolveEncodingName(graphicEncodingPL),
        resolveEncodingName(graphicEncodingFC),
      ].filter((value): value is string => !!value)
      const uniqueEncodedSeries = [...new Set(encodedSeries)]
      const hasEncodedSelection = !!encodedCategory || uniqueEncodedSeries.length > 0

      const projectedColumns = hasEncodedSelection
        ? [
            ...(encodedCategory ? [encodedCategory] : []),
            ...(uniqueEncodedSeries.length > 0 ? uniqueEncodedSeries : generatedColumns.slice(1)),
          ]
        : generatedColumns
      const projectedRows = hasEncodedSelection
        ? generatedRows.map((row) => {
            const nextRow: Record<string, unknown> = {}
            for (const col of projectedColumns) {
              nextRow[col] = row[col]
            }
            return nextRow
          })
        : generatedRows

      const firstColumn = projectedColumns[0]
      const firstRaw = projectedRows[0]?.[firstColumn]
      const firstAsString = firstRaw == null ? '' : String(firstRaw).trim()
      const hasRealCategory = typeof firstRaw === 'string' && firstAsString.length > 0 && Number.isNaN(Number(firstAsString))

      const useSyntheticCategory = !hasRealCategory
      const embeddedCategoryKey = '__embedded_category__'
      const normalizedColumns = useSyntheticCategory
        ? [embeddedCategoryKey, ...projectedColumns]
        : projectedColumns
      const normalizedRows = useSyntheticCategory
        ? projectedRows.map((row, index) => ({
            ...row,
            [embeddedCategoryKey]: projectedRows.length === 1
              ? (graphicCategoryLabel || '')
              : (graphicCategoryLabel ? `${graphicCategoryLabel} ${index + 1}` : `${index + 1}`),
          }))
        : projectedRows

      if (graphicGeneratedType === 'ibcs_line') {
        return (
          <div className="pointer-events-none w-full h-full" data-testid="kpi-card-graphic-generated">
            <IBCSLineChart
              columns={normalizedColumns}
              rows={normalizedRows}
              isDark={isDark}
            />
          </div>
        )
      }

      if (graphicGeneratedType === 'ibcs_waterfall') {
        const waterfallValueColumn = normalizedColumns.find((c) => /\s+(PY|PL|BUD|FC)$/i.test(c)) || normalizedColumns[1]
        return (
          <div className="pointer-events-none w-full h-full" data-testid="kpi-card-graphic-generated">
            <IBCSWaterfall
              columns={normalizedColumns}
              rows={normalizedRows}
              isDark={isDark}
              scenario={graphicGeneratedScenario}
              showTotals={graphicGeneratedShowTotals}
              valueColumnName={waterfallValueColumn}
              showConnectors={graphicIbcsWaterfallShowConnectors !== false}
              fontSize={graphicIbcsFontSize}
              dataLabelFontSize={graphicIbcsDataLabelFontSize}
              fontFamily={graphicIbcsFontFamily}
              xAxisRotation={graphicIbcsXAxisRotation}
            />
          </div>
        )
      }

      return (
        <div className="pointer-events-none w-full h-full" data-testid="kpi-card-graphic-generated">
          <IBCSBarChart
            columns={normalizedColumns}
            rows={normalizedRows}
            isDark={isDark}
            orientation={graphicGeneratedOrientation}
            labelPosition={graphicIbcsLabelPosition}
            fontSize={graphicIbcsFontSize}
            dataLabelFontSize={graphicIbcsDataLabelFontSize}
            fontFamily={graphicIbcsFontFamily}
            xAxisRotation={graphicIbcsXAxisRotation}
            canvasPaddingH={graphicIbcsCanvasPaddingH}
            canvasPaddingV={graphicIbcsCanvasPaddingV}
            showVariancePanels={graphicIbcsShowVariancePanels}
            mainChartMode={graphicIbcsMainChartMode}
          />
        </div>
      )
    }

    return (
      <img
        src={graphicSrc}
        alt=""
        className={isHorizontalGraphic ? 'max-h-full max-w-full object-contain opacity-90' : 'h-12 max-w-full object-contain opacity-90'}
        data-testid="kpi-card-graphic-image"
      />
    )
  }, [
    hasGraphic,
    hasGeneratedGraphic,
    rows,
    columns,
    graphicGeneratedType,
    graphicCategoryLabel,
    graphicEncodingCategory,
    graphicEncodingAC,
    graphicEncodingPY,
    graphicEncodingPL,
    graphicEncodingFC,
    graphicGeneratedScenario,
    graphicGeneratedShowTotals,
    graphicGeneratedOrientation,
    graphicIbcsMainChartMode,
    graphicIbcsLabelPosition,
    graphicIbcsFontSize,
    graphicIbcsDataLabelFontSize,
    graphicIbcsFontFamily,
    graphicIbcsXAxisRotation,
    graphicIbcsShowVariancePanels,
    graphicIbcsWaterfallShowConnectors,
    graphicIbcsCanvasPaddingH,
    graphicIbcsCanvasPaddingV,
    isDark,
    graphicSrc,
    isHorizontalGraphic,
  ])

  if (kpis.length === 0) {
    return (
      <div
        ref={containerRef}
        className="flex items-center justify-center h-full text-muted-foreground text-xs"
        data-testid="kpi-card"
        style={{ width: width ?? undefined, height: height ?? undefined }}
      >
        No data
      </div>
    )
  }

  // ─── Single KPI → large centered display ───────────────────────────────

  if (kpis.length === 1) {
    const kpi = kpis[0]
    const diSurface = renderDecisionSurface(kpi, 0)
    const hasDI = !!diSurface

    // Build the body+graphic inner section (the "core" card content)
    const bodyClass = hasGraphic && isHorizontalGraphic
      ? 'flex flex-col justify-center flex-1 min-w-0 gap-2 px-1 py-1'
      : 'flex flex-col items-center justify-center gap-2 w-full px-1 py-1'

    const coreContent = (
      <div
        className={hasGraphic
          ? (isHorizontalGraphic
            ? `flex ${graphicPosition === 'left' ? 'flex-row-reverse' : 'flex-row'} items-stretch flex-1 min-h-0 gap-3`
            : `flex ${graphicPosition === 'top' ? 'flex-col-reverse' : 'flex-col'} items-stretch flex-1 min-h-0 gap-2`)
          : 'flex flex-col items-center justify-center flex-1 min-h-0 gap-2'}
      >
        <div className={bodyClass} data-testid="kpi-performance-row">
          <span
            className="text-xs uppercase tracking-wide"
            style={{ color: txtSecondary }}
            data-testid="kpi-label"
          >
            {kpi.label}
          </span>

          <div className="flex items-baseline gap-2">
            <span
              className={isCompact ? 'text-2xl font-bold' : 'text-4xl font-bold'}
              style={{ color: txtPrimary, fontVariantNumeric: 'tabular-nums' }}
              data-testid="kpi-value"
            >
              {formatCompact(kpi.value)}
            </span>
            {kpi.scenarioCode && (
              <span
                className="text-xs font-semibold uppercase"
                style={{ color: txtMuted }}
              >
                {kpi.scenarioCode}
              </span>
            )}
          </div>

          {kpi.comparisons.map((cmp, ci) => (
            <div
              key={ci}
              className="flex items-center gap-2 w-full"
              data-testid="kpi-delta"
            >
              <span
                className="text-[10px] font-semibold uppercase w-6 text-center"
                style={{ color: txtMuted }}
              >
                {cmp.scenarioCode || 'CMP'}
              </span>
              <span
                className="text-sm min-w-[52px]"
                style={{ color: txtSecondary, fontVariantNumeric: 'tabular-nums' }}
              >
                {formatCompact(cmp.value)}
              </span>
              <VarianceBar
                delta={cmp.delta}
                maxDelta={Math.max(...kpi.comparisons.map(c => Math.abs(c.delta)), 1)}
                isDark={isDark}
                invert={invert}
              />
              <VarianceArrow delta={cmp.delta} isDark={isDark} invert={invert} />
              <span
                className="text-sm font-semibold min-w-[48px] text-right"
                style={{ color: getVarianceColor(cmp.delta, isDark, invert), fontVariantNumeric: 'tabular-nums' }}
              >
                {formatVariance(cmp.delta)}
              </span>
              <span
                className="text-xs min-w-[42px] text-right"
                style={{ color: getVarianceColor(cmp.deltaPct, isDark, invert), fontVariantNumeric: 'tabular-nums' }}
              >
                {formatPercent(cmp.deltaPct)}
              </span>
            </div>
          ))}

          {/* ─── Zone 3: EDU Summary (inline only) ─── */}
          {isEduInline && renderEDUSummary()}

          {kpi.sparklineValues.length > 2 && (
            <div className={hasGraphic && graphicPosition === 'right' ? 'mt-0' : 'mt-1'}>
              <IBCSSparkline
                values={kpi.sparklineValues}
                width={isCompact ? 60 : 90}
                height={22}
                showArea
                isDark={isDark}
              />
            </div>
          )}
        </div>

        {hasGraphic && (
          <div
            className={`${graphicSlotClass} flex items-center justify-center p-1 overflow-hidden cursor-pointer`}
            data-testid="kpi-card-graphic-slot"
            data-position={graphicPosition}
            data-source={graphicSourceType}
            onClick={hasGeneratedGraphic ? onGraphicEditorRequest : undefined}
            title={hasGeneratedGraphic ? 'Open IBCS graphic editor' : undefined}
          >
            {renderGraphicContent()}
          </div>
        )}
      </div>
    )

    // DI surface slot — compact sidebar or strip
    const diSlot = hasDI ? (
      <div
        className={isHorizontalDI
          ? 'flex flex-col gap-1 overflow-auto flex-shrink-0'
          : 'w-full flex-shrink-0'}
        style={isHorizontalDI ? { width: '35%', minWidth: 160, maxWidth: 260 } : undefined}
        data-testid="kpi-decision-surface-slot"
        data-di-position={diPosition}
      >
        {diSurface}
      </div>
    ) : null

    const eduSlot = renderEduSlot()

    // When EDU is horizontal (left/right), use a nested layout:
    // outer = flex-row for EDU side placement
    // inner = original column/row layout for core + DI
    if (isHorizontalEdu && eduSlot) {
      const innerClass = hasDI
        ? (isHorizontalDI
          ? `flex ${diPosition === 'left' ? 'flex-row-reverse' : 'flex-row'} flex-1 min-w-0 min-h-0 gap-2`
          : `flex ${diPosition === 'top' ? 'flex-col-reverse' : 'flex-col'} flex-1 min-w-0 min-h-0 gap-1`)
        : 'flex flex-col flex-1 min-w-0 min-h-0'

      return (
        <div
          ref={containerRef}
          className={`flex ${eduPosition === 'left' ? 'flex-row-reverse' : 'flex-row'} h-full p-3 gap-3`}
          data-testid="kpi-card"
          style={{ width: width ?? undefined, height: height ?? undefined }}
          onMouseMove={(e) => showTooltip(e, kpi)}
          onMouseLeave={hideTooltip}
        >
          <div className={innerClass}>
            {diPosition === 'top' && diSlot}
            {diPosition === 'left' && diSlot}
            {coreContent}
            {diPosition === 'right' && diSlot}
            {diPosition === 'bottom' && diSlot}
          </div>
          {eduSlot}
          <KPITooltip tooltip={tooltip} isDark={isDark} />
        </div>
      )
    }

    // Outer layout: place core + DI + EDU according to positions
    const outerClass = hasDI
      ? (isHorizontalDI
        ? `flex ${diPosition === 'left' ? 'flex-row-reverse' : 'flex-row'} h-full p-3 gap-2`
        : `flex ${diPosition === 'top' ? 'flex-col-reverse' : 'flex-col'} h-full p-3 gap-1`)
      : (hasGraphic
        ? (isHorizontalGraphic
          ? `flex ${graphicPosition === 'left' ? 'flex-row-reverse' : 'flex-row'} items-stretch justify-between h-full p-3 gap-3`
          : `flex ${graphicPosition === 'top' ? 'flex-col-reverse' : 'flex-col'} items-stretch justify-between h-full p-3 gap-2`)
        : 'flex flex-col items-center justify-center h-full p-3 gap-2')

    return (
      <div
        ref={containerRef}
        className={outerClass}
        data-testid="kpi-card"
        style={{ width: width ?? undefined, height: height ?? undefined }}
        onMouseMove={(e) => showTooltip(e, kpi)}
        onMouseLeave={hideTooltip}
      >
        {eduPosition === 'top' && eduSlot}
        {diPosition === 'top' && diSlot}
        {eduPosition === 'left' && eduSlot}
        {diPosition === 'left' && diSlot}
        {coreContent}
        {diPosition === 'right' && diSlot}
        {eduPosition === 'right' && eduSlot}
        {diPosition === 'bottom' && diSlot}
        {eduPosition === 'bottom' && eduSlot}
        <KPITooltip tooltip={tooltip} isDark={isDark} />
      </div>
    )
  }

  // ─── Multi-KPI → stacked rows ──────────────────────────────────────────

  const diSurfaceMulti = renderAllDecisionSurfaces(kpis)
  const hasDIMulti = !!diSurfaceMulti

  // Core content: KPI rows + graphic
  const multiCore = (
    <div
      className={hasGraphic
        ? (isHorizontalGraphic
          ? `flex ${graphicPosition === 'left' ? 'flex-row-reverse' : 'flex-row'} flex-1 min-h-0 overflow-hidden gap-2`
          : `flex ${graphicPosition === 'top' ? 'flex-col-reverse' : 'flex-col'} flex-1 min-h-0 overflow-hidden gap-2`)
        : 'flex flex-col flex-1 min-h-0 overflow-auto gap-0'}
    >
      <div className={hasGraphic && isHorizontalGraphic ? 'flex-1 overflow-auto px-2' : 'w-full px-2'}>
        {kpis.map((kpi, i) => (
          <div
            key={kpi.label + i}
            className="flex flex-col py-2"
            style={{
              borderBottom: i < kpis.length - 1 ? `1px solid ${gridColor}` : undefined,
            }}
            data-testid="kpi-delta"
            onMouseMove={(e) => showTooltip(e, kpi)}
            onMouseLeave={hideTooltip}
          >
            <div className="flex items-center justify-between gap-2" data-testid="kpi-performance-row">
              <div className="flex-shrink-0 w-1/4 min-w-0">
                <span
                  className="text-xs truncate block"
                  style={{ color: txtSecondary }}
                  title={kpi.label}
                  data-testid="kpi-label"
                >
                  {kpi.label}
                </span>
              </div>

              <div className="flex items-baseline gap-1 flex-shrink-0">
                <span
                  className="text-sm font-bold"
                  style={{ color: txtPrimary, fontVariantNumeric: 'tabular-nums' }}
                  data-testid="kpi-value"
                >
                  {formatCompact(kpi.value)}
                </span>
                {kpi.scenarioCode && (
                  <span className="text-[9px] uppercase" style={{ color: txtMuted }}>
                    {kpi.scenarioCode}
                  </span>
                )}
              </div>

              {kpi.sparklineValues.length > 2 && !isCompact && (
                <IBCSSparkline
                  values={kpi.sparklineValues}
                  width={56}
                  height={16}
                  isDark={isDark}
                />
              )}

              <div className="flex items-center gap-1.5 flex-shrink-0 min-w-[120px] justify-end">
                {kpi.comparisons.length > 0 && (() => {
                  const cmp = kpi.comparisons[0]
                  return (
                    <>
                      <VarianceBar
                        delta={cmp.delta}
                        maxDelta={Math.max(...kpis.map(k => k.comparisons[0] ? Math.abs(k.comparisons[0].delta) : 1))}
                        isDark={isDark}
                        invert={invert}
                        width={40}
                      />
                      <VarianceArrow delta={cmp.delta} isDark={isDark} invert={invert} size={8} />
                      <span
                        className="text-xs font-semibold"
                        style={{ color: getVarianceColor(cmp.delta, isDark, invert), fontVariantNumeric: 'tabular-nums' }}
                      >
                        {formatVariance(cmp.delta)}
                      </span>
                      <span
                        className="text-[10px]"
                        style={{ color: getVarianceColor(cmp.deltaPct, isDark, invert), fontVariantNumeric: 'tabular-nums' }}
                      >
                        {formatPercent(cmp.deltaPct)}
                      </span>
                    </>
                  )
                })()}
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* ─── Zone 3: EDU Summary (multi-KPI, inline only) ─── */}
      {isEduInline && renderEDUSummary()}

      {hasGraphic && (
        <div
          className={`${graphicSlotClass} flex items-center justify-center p-1 overflow-hidden cursor-pointer`}
          data-testid="kpi-card-graphic-slot"
          data-position={graphicPosition}
          data-source={graphicSourceType}
          onClick={hasGeneratedGraphic ? onGraphicEditorRequest : undefined}
          title={hasGeneratedGraphic ? 'Open IBCS graphic editor' : undefined}
        >
          {renderGraphicContent()}
        </div>
      )}
    </div>
  )

  // DI slot for multi-KPI
  const diSlotMulti = hasDIMulti ? (
    <div
      className={isHorizontalDI
        ? 'flex flex-col gap-1 overflow-auto flex-shrink-0'
        : 'w-full flex-shrink-0'}
      style={isHorizontalDI ? { width: '35%', minWidth: 160, maxWidth: 260 } : undefined}
      data-testid="kpi-decision-surface-slot"
      data-di-position={diPosition}
    >
      {diSurfaceMulti}
    </div>
  ) : null

  const eduSlotMulti = renderEduSlot()

  // When EDU is horizontal (left/right), use nested layout
  if (isHorizontalEdu && eduSlotMulti) {
    const multiInnerClass = hasDIMulti
      ? (isHorizontalDI
        ? `flex ${diPosition === 'left' ? 'flex-row-reverse' : 'flex-row'} flex-1 min-w-0 min-h-0 gap-2`
        : `flex ${diPosition === 'top' ? 'flex-col-reverse' : 'flex-col'} flex-1 min-w-0 min-h-0 gap-1`)
      : 'flex flex-col flex-1 min-w-0 min-h-0'

    return (
      <div
        ref={containerRef}
        className={`flex ${eduPosition === 'left' ? 'flex-row-reverse' : 'flex-row'} h-full p-2 gap-3`}
        data-testid="kpi-card"
        style={{ width: width ?? undefined, height: height ?? undefined }}
      >
        <div className={multiInnerClass}>
          {diPosition === 'top' && diSlotMulti}
          {diPosition === 'left' && diSlotMulti}
          {multiCore}
          {diPosition === 'right' && diSlotMulti}
          {diPosition === 'bottom' && diSlotMulti}
        </div>
        {eduSlotMulti}
        <KPITooltip tooltip={tooltip} isDark={isDark} />
      </div>
    )
  }

  // Outer layout: core + DI + EDU
  const multiOuterClass = hasDIMulti
    ? (isHorizontalDI
      ? `flex ${diPosition === 'left' ? 'flex-row-reverse' : 'flex-row'} h-full p-2 gap-2`
      : `flex ${diPosition === 'top' ? 'flex-col-reverse' : 'flex-col'} h-full p-2 gap-1`)
    : (hasGraphic
      ? (isHorizontalGraphic
        ? `flex ${graphicPosition === 'left' ? 'flex-row-reverse' : 'flex-row'} h-full overflow-hidden p-2 gap-2`
        : `flex ${graphicPosition === 'top' ? 'flex-col-reverse' : 'flex-col'} h-full overflow-hidden p-2 gap-2`)
      : 'flex flex-col h-full overflow-auto p-2 gap-0')

  return (
    <div
      ref={containerRef}
      className={multiOuterClass}
      data-testid="kpi-card"
      style={{ width: width ?? undefined, height: height ?? undefined }}
    >
      {eduPosition === 'top' && eduSlotMulti}
      {diPosition === 'top' && diSlotMulti}
      {eduPosition === 'left' && eduSlotMulti}
      {diPosition === 'left' && diSlotMulti}
      {multiCore}
      {diPosition === 'right' && diSlotMulti}
      {eduPosition === 'right' && eduSlotMulti}
      {diPosition === 'bottom' && diSlotMulti}
      {eduPosition === 'bottom' && eduSlotMulti}
      <KPITooltip tooltip={tooltip} isDark={isDark} />
    </div>
  )
}

// ─── Variance Bar (proportional horizontal green/red bar) ───────────────────

function VarianceBar({
  delta,
  maxDelta,
  isDark,
  invert = false,
  width = 50,
  height = 10,
}: {
  delta: number
  maxDelta: number
  isDark: boolean
  invert?: boolean
  width?: number
  height?: number
}) {
  const color = getVarianceColor(delta, isDark, invert)
  const barW = maxDelta > 0 ? (Math.abs(delta) / maxDelta) * (width / 2) : 0
  const isPositive = delta >= 0

  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      data-testid="kpi-variance-bar"
    >
      {/* Center marker */}
      <line
        x1={width / 2} y1={0} x2={width / 2} y2={height}
        stroke={isDark ? IBCS.dark.gridLine : IBCS.gridLine}
        strokeWidth={0.5}
      />
      {/* Proportional bar from center */}
      <rect
        x={isPositive ? width / 2 : width / 2 - barW}
        y={1}
        width={barW}
        height={height - 2}
        fill={color}
        rx={1}
      />
    </svg>
  )
}

// ─── Variance Arrow (up/down triangle indicator) ────────────────────────────

function VarianceArrow({
  delta,
  isDark,
  invert = false,
  size = 10,
}: {
  delta: number
  isDark: boolean
  invert?: boolean
  size?: number
}) {
  if (delta === 0) return null

  const color = getVarianceColor(delta, isDark, invert)
  const isUp = delta > 0

  // Triangle points: pointing up or down
  const points = isUp
    ? `${size / 2},0 ${size},${size} 0,${size}`    // ▲
    : `0,0 ${size},0 ${size / 2},${size}`            // ▼

  return (
    <svg
      width={size}
      height={size}
      viewBox={`0 0 ${size} ${size}`}
      data-testid="kpi-variance-arrow"
      style={{ display: 'inline-block', verticalAlign: 'middle' }}
    >
      <polygon points={points} fill={color} />
    </svg>
  )
}

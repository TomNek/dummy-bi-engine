import React, { useState, useEffect } from 'react'
import { BrainCircuit, ChevronDown, ChevronRight } from 'lucide-react'
import { TrustPanel, type TrustPanelProps } from './TrustPanel'
import { SignalChips, type SignalChipData } from './SignalChips'
import { EpisodeTimeline, type EpisodeData } from './EpisodeTimeline'
import { EvidenceExport } from './EvidenceExport'
import { getConfidenceStyle } from '../../lib/humanize'

export interface DecisionPanelProps {
  /** KPI key for this decision panel */
  kpiKey: string
  /** Decision overlays from render data */
  decisionOverlays?: unknown[]
  /** Pack summary from render data */
  packSummary?: Record<string, unknown> | null
  /** Overlay meta from render data */
  overlayMeta?: Record<string, unknown> | null
  /** Whether the panel should be visible */
  visible?: boolean
}

/**
 * Composite wrapper for all Phase 17 decision surfaces.
 * Integrates TrustPanel, SignalChips, EpisodeTimeline, EvidenceExport.
 * Hidden when decision artifacts are absent.
 */
export const DecisionPanel: React.FC<DecisionPanelProps> = ({
  kpiKey,
  decisionOverlays,
  packSummary,
  overlayMeta,
  visible = true,
}) => {
  // Extract trust/stability props from overlay meta
  const trustProps: TrustPanelProps = {
    stabilityBadge: (overlayMeta?.stability_badge as string) || 'N/A',
    driftEvent: Boolean(overlayMeta?.drift_event),
    rankChurnScore: Number(overlayMeta?.rank_churn_score ?? 0),
    unexplainedTrend: Boolean(overlayMeta?.unexplained_trend),
    forecastQualityBand: (overlayMeta?.forecast_quality_band as string) || 'N/A',
    dataSufficiency: (overlayMeta?.data_sufficiency as string) || 'N/A',
    stabilityRiskScore: Number(overlayMeta?.stability_risk_score ?? 0),
    rationale: (overlayMeta?.rationale as string) || '',
    provenance: overlayMeta?.provenance as Record<string, unknown> | undefined,
  }

  // Extract signals from decision overlays (nested signals array)
  const signals: SignalChipData[] = []
  if (Array.isArray(decisionOverlays)) {
    for (const overlay of decisionOverlays) {
      const ov = overlay as Record<string, unknown>
      // Signals are nested inside each overlay's "signals" array
      const rawSignals = Array.isArray(ov.signals) ? ov.signals : []
      for (const sig of rawSignals) {
        const s = sig as Record<string, unknown>
        if (s.signal_type || s.signal_id) {
          signals.push({
            signal_id: String(s.signal_id || ''),
            signal_type: String(s.signal_type || s.signal_id || ''),
            severity: String(s.severity || 'Low'),
            rationale: (s.rationale as string) || undefined,
            provenance: s.provenance as Record<string, unknown> | undefined,
            gated: Boolean(s.gated),
          })
        }
      }
      // Also check top-level signal_id/signal_type on overlay itself (flat format)
      if (ov.signal_type || ov.signal_id) {
        signals.push({
          signal_id: String(ov.signal_id || ''),
          signal_type: String(ov.signal_type || ov.signal_id || ''),
          severity: String(ov.severity || 'Low'),
          rationale: (ov.rationale as string) || undefined,
          provenance: ov.provenance as Record<string, unknown> | undefined,
          gated: Boolean(ov.gated),
        })
      }
    }
  }

  // Extract episodes from overlay meta
  const episodes: EpisodeData[] = []
  if (overlayMeta?.episodes && Array.isArray(overlayMeta.episodes)) {
    for (const ep of overlayMeta.episodes as Record<string, unknown>[]) {
      episodes.push({
        episode_id: String(ep.episode_id || ''),
        continuity_key: String(ep.continuity_key || ''),
        kpi_id: String(ep.kpi_id || kpiKey),
        signal_id: String(ep.signal_id || ''),
        start_period: String(ep.start_period || ''),
        end_period: String(ep.end_period || ''),
        max_severity: String(ep.max_severity || 'Low'),
        last_severity: String(ep.last_severity || 'Low'),
        duration_periods: Number(ep.duration_periods ?? 0),
        trajectory: String(ep.trajectory || 'stable'),
        provenance: ep.provenance as Record<string, unknown> | undefined,
      })
    }
  }

  // Evidence bundle from overlay meta
  const evidenceBundle = (overlayMeta?.evidence_bundle as Record<string, unknown>) || null

  // If no decision artifacts present, hide the panel
  const hasArtifacts = (
    (decisionOverlays && decisionOverlays.length > 0) ||
    (packSummary && Object.keys(packSummary).length > 0) ||
    (overlayMeta && Object.keys(overlayMeta).length > 0)
  )

  if (!visible || !hasArtifacts) return null

  const confStyle = getConfidenceStyle(String(packSummary?.pack_confidence_tier || 'Unknown'))
  const highSevCount = Number(packSummary?.high_severity_signal_count ?? 0)
  const activeEpCount = Number(packSummary?.active_episode_count ?? 0)

  return (
    <div
      data-testid="decision-panel"
      style={{
        marginTop: 12,
        border: '1px solid #e5e7eb',
        borderRadius: 12,
        overflow: 'hidden',
        backgroundColor: '#fff',
      }}
    >
      {/* Header */}
      <div style={{
        display: 'flex',
        alignItems: 'center',
        gap: 8,
        padding: '12px 16px',
        borderBottom: '1px solid #f3f4f6',
        backgroundColor: '#fafafa',
      }}>
        <BrainCircuit size={16} color="#6366f1" />
        <span style={{ fontWeight: 600, fontSize: 14, color: '#1f2937' }}>
          Decision Intelligence
        </span>
        {/* Quick status badges */}
        {signals.length > 0 && (
          <span style={{
            marginLeft: 'auto',
            display: 'inline-flex',
            alignItems: 'center',
            gap: 8,
            fontSize: 11,
          }}>
            {highSevCount > 0 && (
              <span style={{
                padding: '2px 8px',
                borderRadius: 10,
                backgroundColor: '#fef2f2',
                color: '#991b1b',
                fontWeight: 500,
              }}>
                {highSevCount} high severity
              </span>
            )}
            {activeEpCount > 0 && (
              <span style={{
                padding: '2px 8px',
                borderRadius: 10,
                backgroundColor: '#eff6ff',
                color: '#1e40af',
                fontWeight: 500,
              }}>
                {activeEpCount} active episode{activeEpCount !== 1 ? 's' : ''}
              </span>
            )}
          </span>
        )}
      </div>

      {/* Body */}
      <div style={{ padding: '12px 16px' }}>
        <TrustPanel {...trustProps} />

        {signals.length > 0 && (
          <div style={{ marginBottom: 4 }}>
            <div style={{ fontSize: 11, fontWeight: 600, color: '#6b7280', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 6 }}>
              Active Signals
            </div>
            <SignalChips signals={signals} kpiKey={kpiKey} />
          </div>
        )}

        {episodes.length > 0 && (
          <EpisodeTimeline episodes={episodes} />
        )}

        {/* Pack summary as a clean footer */}
        {packSummary && (
          <div
            data-testid="decision-pack-summary"
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 8,
              padding: '8px 12px',
              borderRadius: 8,
              backgroundColor: '#f9fafb',
              fontSize: 12,
              color: '#6b7280',
              marginBottom: 12,
            }}
          >
            <span style={{
              padding: '2px 8px',
              borderRadius: 6,
              backgroundColor: confStyle.bg,
              color: confStyle.text,
              fontWeight: 600,
              fontSize: 11,
            }}>
              {confStyle.label} confidence
            </span>
            <span style={{ color: '#d1d5db' }}>·</span>
            <span>{signals.length} signal{signals.length !== 1 ? 's' : ''}</span>
            <span style={{ color: '#d1d5db' }}>·</span>
            <span>{activeEpCount} episode{activeEpCount !== 1 ? 's' : ''}</span>
          </div>
        )}

        <EvidenceExport kpiId={kpiKey} evidenceBundle={evidenceBundle} />
      </div>
    </div>
  )
}

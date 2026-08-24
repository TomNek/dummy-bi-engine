import React, { useState } from 'react'
import { ChevronDown, ChevronRight, Activity, TrendingDown, AlertTriangle, BarChart3, Database, Gauge } from 'lucide-react'
import { getStabilityStyle, humanizeDataSufficiency } from '../../lib/humanize'

export interface TrustPanelProps {
  stabilityBadge?: string
  driftEvent?: boolean
  rankChurnScore?: number
  unexplainedTrend?: boolean
  forecastQualityBand?: string
  dataSufficiency?: string
  stabilityRiskScore?: number
  rationale?: string
  provenance?: Record<string, unknown>
}

export const TrustPanel: React.FC<TrustPanelProps> = ({
  stabilityBadge = 'N/A',
  driftEvent = false,
  rankChurnScore = 0,
  unexplainedTrend = false,
  forecastQualityBand = 'N/A',
  dataSufficiency = 'N/A',
  stabilityRiskScore = 0,
  rationale = '',
  provenance,
}) => {
  const [expanded, setExpanded] = useState(false)
  const stability = getStabilityStyle(stabilityBadge)

  // Risk score color
  const riskColor = stabilityRiskScore >= 7 ? '#dc2626' : stabilityRiskScore >= 4 ? '#f59e0b' : '#16a34a'
  const riskLabel = stabilityRiskScore >= 7 ? 'High' : stabilityRiskScore >= 4 ? 'Moderate' : 'Low'

  return (
    <div
      data-testid="trust-panel"
      style={{
        border: '1px solid #e5e7eb',
        borderRadius: 10,
        overflow: 'hidden',
        marginBottom: 12,
        backgroundColor: '#fff',
      }}
    >
      {/* Header */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 10,
          padding: '10px 14px',
          cursor: 'pointer',
          userSelect: 'none',
          borderBottom: expanded ? '1px solid #f3f4f6' : 'none',
        }}
        onClick={() => setExpanded((e) => !e)}
      >
        <span
          data-testid="stability-badge"
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: 4,
            padding: '3px 10px',
            borderRadius: 6,
            fontSize: 12,
            fontWeight: 600,
            letterSpacing: '0.02em',
            backgroundColor: stability.bg,
            color: stability.text,
          }}
        >
          {stabilityBadge}
        </span>
        <span style={{ fontSize: 13, color: '#374151', fontWeight: 500 }}>Trust & Stability</span>
        {/* Risk score pill in header */}
        <span
          style={{
            marginLeft: 'auto',
            display: 'inline-flex',
            alignItems: 'center',
            gap: 4,
            fontSize: 11,
            color: riskColor,
            fontWeight: 500,
          }}
        >
          <Gauge size={13} />
          Risk {stabilityRiskScore.toFixed(1)}
        </span>
        <span style={{ color: '#9ca3af', flexShrink: 0, marginLeft: 4 }}>
          {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        </span>
      </div>

      {/* Expanded details */}
      {expanded && (
        <div data-testid="trust-panel-details" style={{ padding: '12px 14px' }}>
          {/* Metric grid */}
          <div style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(3, 1fr)',
            gap: 10,
            marginBottom: rationale ? 12 : 0,
          }}>
            {/* Drift Event */}
            <div style={{
              display: 'flex',
              alignItems: 'center',
              gap: 6,
              padding: '6px 10px',
              borderRadius: 8,
              backgroundColor: driftEvent ? '#fef2f2' : '#f9fafb',
              border: `1px solid ${driftEvent ? '#fecaca' : '#f3f4f6'}`,
            }}>
              <Activity size={13} color={driftEvent ? '#dc2626' : '#9ca3af'} />
              <div>
                <div data-testid="trust-drift-event" style={{ fontSize: 11, fontWeight: 600, color: driftEvent ? '#991b1b' : '#6b7280' }}>
                  {driftEvent ? 'Drift Detected' : 'No Drift'}
                </div>
              </div>
            </div>

            {/* Rank Churn */}
            <div style={{
              display: 'flex',
              alignItems: 'center',
              gap: 6,
              padding: '6px 10px',
              borderRadius: 8,
              backgroundColor: '#f9fafb',
              border: '1px solid #f3f4f6',
            }}>
              <BarChart3 size={13} color="#6b7280" />
              <div>
                <div data-testid="trust-rank-churn" style={{ fontSize: 11, fontWeight: 600, color: '#374151' }}>
                  Churn {rankChurnScore.toFixed(2)}
                </div>
              </div>
            </div>

            {/* Unexplained Trend */}
            <div style={{
              display: 'flex',
              alignItems: 'center',
              gap: 6,
              padding: '6px 10px',
              borderRadius: 8,
              backgroundColor: unexplainedTrend ? '#fffbeb' : '#f9fafb',
              border: `1px solid ${unexplainedTrend ? '#fde68a' : '#f3f4f6'}`,
            }}>
              <TrendingDown size={13} color={unexplainedTrend ? '#d97706' : '#9ca3af'} />
              <div>
                <div data-testid="trust-unexplained-trend" style={{ fontSize: 11, fontWeight: 600, color: unexplainedTrend ? '#92400e' : '#6b7280' }}>
                  {unexplainedTrend ? 'Unexplained Trend' : 'Trend OK'}
                </div>
              </div>
            </div>

            {/* Forecast Quality */}
            <div style={{
              display: 'flex',
              alignItems: 'center',
              gap: 6,
              padding: '6px 10px',
              borderRadius: 8,
              backgroundColor: '#f9fafb',
              border: '1px solid #f3f4f6',
            }}>
              <AlertTriangle size={13} color="#6b7280" />
              <div>
                <div data-testid="trust-forecast-quality" style={{ fontSize: 11, fontWeight: 600, color: '#374151' }}>
                  Forecast: {forecastQualityBand}
                </div>
              </div>
            </div>

            {/* Data Sufficiency */}
            <div style={{
              display: 'flex',
              alignItems: 'center',
              gap: 6,
              padding: '6px 10px',
              borderRadius: 8,
              backgroundColor: dataSufficiency !== 'OK' ? '#fffbeb' : '#f9fafb',
              border: `1px solid ${dataSufficiency !== 'OK' ? '#fde68a' : '#f3f4f6'}`,
            }}>
              <Database size={13} color={dataSufficiency !== 'OK' ? '#d97706' : '#9ca3af'} />
              <div>
                <div data-testid="trust-data-sufficiency" style={{ fontSize: 11, fontWeight: 600, color: dataSufficiency !== 'OK' ? '#92400e' : '#374151' }}>
                  Data: {humanizeDataSufficiency(dataSufficiency)}
                </div>
              </div>
            </div>

            {/* Risk Score */}
            <div style={{
              display: 'flex',
              alignItems: 'center',
              gap: 6,
              padding: '6px 10px',
              borderRadius: 8,
              backgroundColor: stabilityRiskScore >= 7 ? '#fef2f2' : stabilityRiskScore >= 4 ? '#fffbeb' : '#f0fdf4',
              border: `1px solid ${stabilityRiskScore >= 7 ? '#fecaca' : stabilityRiskScore >= 4 ? '#fde68a' : '#bbf7d0'}`,
            }}>
              <Gauge size={13} color={riskColor} />
              <div>
                <div data-testid="trust-risk-score" style={{ fontSize: 11, fontWeight: 600, color: riskColor }}>
                  Risk: {stabilityRiskScore.toFixed(1)} ({riskLabel})
                </div>
              </div>
            </div>
          </div>

          {/* Rationale */}
          {rationale && (
            <div
              data-testid="trust-rationale"
              style={{
                padding: '8px 12px',
                borderRadius: 8,
                backgroundColor: '#f9fafb',
                borderLeft: '3px solid #d1d5db',
                fontSize: 12,
                fontStyle: 'italic',
                color: '#4b5563',
                lineHeight: 1.5,
              }}
            >
              {rationale}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

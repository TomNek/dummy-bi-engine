import React, { useState } from 'react'
import { humanizeSignalName, getSeverityStyle } from '../../lib/humanize'

export interface SignalChipData {
  signal_id: string
  signal_type: string
  severity: string
  rationale?: string
  provenance?: Record<string, unknown>
  gated?: boolean
}

export interface SignalChipsProps {
  signals: SignalChipData[]
  kpiKey?: string
}

export const SignalChips: React.FC<SignalChipsProps> = ({ signals, kpiKey }) => {
  const [hoveredId, setHoveredId] = useState<string | null>(null)

  if (!signals || signals.length === 0) return null

  return (
    <div data-testid="signal-chips" style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 12 }}>
      {signals.map((sig) => {
        const sev = getSeverityStyle(sig.severity)
        const displayName = humanizeSignalName(sig.signal_id || sig.signal_type)
        return (
          <div
            key={sig.signal_id}
            data-testid={`signal-chip-${sig.signal_id}`}
            style={{
              position: 'relative',
              display: 'inline-flex',
              alignItems: 'center',
              gap: 6,
              padding: '4px 12px',
              borderRadius: 16,
              fontSize: 12,
              fontWeight: 500,
              letterSpacing: '0.01em',
              backgroundColor: sig.gated ? '#f3f4f6' : sev.bg,
              color: sig.gated ? '#9ca3af' : sev.text,
              border: `1px solid ${sig.gated ? '#e5e7eb' : sev.border}`,
              textDecoration: sig.gated ? 'line-through' : 'none',
              cursor: 'default',
              opacity: sig.gated ? 0.5 : 1,
              transition: 'box-shadow 0.15s ease',
            }}
            onMouseEnter={() => setHoveredId(sig.signal_id)}
            onMouseLeave={() => setHoveredId(null)}
          >
            <span
              style={{
                width: 7,
                height: 7,
                borderRadius: '50%',
                backgroundColor: sig.gated ? '#d1d5db' : sev.dot,
                flexShrink: 0,
              }}
            />
            <span>{displayName}</span>
            <span style={{
              fontSize: 10,
              fontWeight: 600,
              opacity: 0.7,
              textTransform: 'uppercase',
              letterSpacing: '0.04em',
            }}>{sig.severity}</span>

            {hoveredId === sig.signal_id && sig.rationale && (
              <div
                data-testid={`signal-tooltip-${sig.signal_id}`}
                style={{
                  position: 'absolute',
                  bottom: '100%',
                  left: '50%',
                  transform: 'translateX(-50%)',
                  marginBottom: 6,
                  padding: '8px 12px',
                  borderRadius: 8,
                  backgroundColor: '#1f2937',
                  color: '#f3f4f6',
                  fontSize: 12,
                  lineHeight: 1.4,
                  maxWidth: 280,
                  whiteSpace: 'normal',
                  zIndex: 20,
                  pointerEvents: 'none',
                  boxShadow: '0 4px 12px rgba(0,0,0,0.15)',
                }}
              >
                {sig.rationale}
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}

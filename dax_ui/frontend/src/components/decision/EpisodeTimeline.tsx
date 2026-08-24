import React from 'react'
import { humanizeSignalName, getSeverityStyle, getTrajectoryInfo } from '../../lib/humanize'

export interface EpisodeData {
  episode_id: string
  continuity_key: string
  kpi_id: string
  signal_id: string
  start_period: string
  end_period: string
  max_severity: string
  last_severity: string
  duration_periods: number
  trajectory: string
  provenance?: Record<string, unknown>
}

export interface EpisodeTimelineProps {
  episodes: EpisodeData[]
}

export const EpisodeTimeline: React.FC<EpisodeTimelineProps> = ({ episodes }) => {
  if (!episodes || episodes.length === 0) {
    return (
      <div data-testid="episode-timeline" style={{ fontSize: 12, color: '#9ca3af', padding: '6px 0' }}>
        No episodes recorded.
      </div>
    )
  }

  return (
    <div
      data-testid="episode-timeline"
      style={{ border: '1px solid #e5e7eb', borderRadius: 10, overflow: 'hidden', marginBottom: 12 }}
    >
      <div style={{
        fontWeight: 600,
        fontSize: 13,
        padding: '10px 14px 8px',
        color: '#374151',
        borderBottom: '1px solid #f3f4f6',
      }}>
        Episode Timeline
      </div>
      <div style={{ display: 'flex', flexDirection: 'column' }}>
        {episodes.map((ep) => {
          const sev = getSeverityStyle(ep.max_severity)
          const traj = getTrajectoryInfo(ep.trajectory)
          return (
            <div
              key={ep.episode_id}
              data-testid={`episode-row-${ep.episode_id}`}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 10,
                padding: '8px 14px',
                fontSize: 12,
                borderBottom: '1px solid #f9fafb',
              }}
            >
              {/* Severity dot */}
              <span
                data-testid={`episode-severity-${ep.episode_id}`}
                style={{
                  width: 9,
                  height: 9,
                  borderRadius: '50%',
                  backgroundColor: sev.dot,
                  flexShrink: 0,
                  boxShadow: `0 0 0 2px ${sev.bg}`,
                }}
              />
              {/* Period range */}
              <span style={{ fontWeight: 500, color: '#374151', minWidth: 120 }}>
                {ep.start_period} – {ep.end_period}
              </span>
              {/* Duration */}
              <span style={{
                color: '#6b7280',
                fontSize: 11,
                backgroundColor: '#f3f4f6',
                padding: '1px 6px',
                borderRadius: 4,
              }}>
                {ep.duration_periods} period{ep.duration_periods !== 1 ? 's' : ''}
              </span>
              {/* Trajectory */}
              <span
                data-testid={`episode-trajectory-${ep.episode_id}`}
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: 3,
                  fontSize: 11,
                  color: traj.color,
                  fontWeight: 500,
                }}
                title={`Trajectory: ${traj.label}`}
              >
                <span style={{ fontSize: 14 }}>{traj.icon}</span>
                {traj.label}
              </span>
              {/* Signal name (humanized) */}
              <span style={{
                color: '#9ca3af',
                fontSize: 11,
                marginLeft: 'auto',
                fontStyle: 'italic',
              }}>
                {humanizeSignalName(ep.signal_id)}
              </span>
            </div>
          )
        })}
      </div>
    </div>
  )
}

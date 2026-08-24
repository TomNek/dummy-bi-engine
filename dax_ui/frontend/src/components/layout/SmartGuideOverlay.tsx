/**
 * SmartGuideOverlay — renders dynamic alignment guide lines on the canvas.
 *
 * Subscribes to the lightweight useSmartGuideStore to get activeGuides,
 * and renders them as thin dashed lines in an SVG overlay.
 *
 * The overlay is absolutely positioned over the canvas with pointer-events: none
 * so it never interferes with drag/resize interactions.
 *
 * Uses width/height="100%" so the SVG stretches to the full canvas inner size
 * (which can exceed the base canvasWidth/Height when visuals are placed beyond it).
 */

import React from 'react'
import { useSmartGuideStore } from '@/hooks/useSmartGuides'

export const SmartGuideOverlay: React.FC = React.memo(
  () => {
    const activeGuides = useSmartGuideStore((s) => s.activeGuides)

    if (activeGuides.length === 0) return null

    return (
      <svg
        data-testid="smart-guide-overlay"
        className="absolute inset-0 pointer-events-none"
        width="100%"
        height="100%"
        style={{ zIndex: 50, overflow: 'visible' }}
      >
        {activeGuides.map((guide, i) => {
          if (guide.orientation === 'vertical') {
            // Vertical line: fixed X, spans Y
            return (
              <line
                key={`guide-v-${i}`}
                x1={guide.position}
                y1={guide.start}
                x2={guide.position}
                y2={guide.end}
                stroke="#e11d48"
                strokeWidth={1.5}
                strokeDasharray="6 3"
                opacity={0.9}
              />
            )
          } else {
            // Horizontal line: fixed Y, spans X
            return (
              <line
                key={`guide-h-${i}`}
                x1={guide.start}
                y1={guide.position}
                x2={guide.end}
                y2={guide.position}
                stroke="#e11d48"
                strokeWidth={1.5}
                strokeDasharray="6 3"
                opacity={0.9}
              />
            )
          }
        })}
      </svg>
    )
  },
)

SmartGuideOverlay.displayName = 'SmartGuideOverlay'

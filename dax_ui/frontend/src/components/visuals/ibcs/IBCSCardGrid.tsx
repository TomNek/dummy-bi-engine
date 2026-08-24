/**
 * IBCSCardGrid — Layout wrapper for multiple IBCS KPI cards in a responsive grid.
 *
 * Features:
 * - Arranges IBCSCard instances in a row/grid layout
 * - Responsive columns (auto-calculates based on container width)
 * - Gap and padding configuration
 * - data-testid for testability
 */

import { useRef, useState, useEffect, useCallback } from 'react'
import { IBCSCard, type IBCSCardProps } from './IBCSCard'

export interface CardItem {
  /** Unique key for the card */
  id: string
  /** Column names for this card's data */
  columns: string[]
  /** Data rows for this card */
  rows: Array<Record<string, unknown>>
  /** Optional invert flag (costs: lower = better) */
  invert?: boolean
}

export interface IBCSCardGridProps {
  /** Array of card data sets */
  cards: CardItem[]
  /** Minimum card width in pixels (default: 200) */
  minCardWidth?: number
  /** Gap between cards in pixels (default: 12) */
  gap?: number
  /** Dark mode */
  isDark?: boolean
}

export function IBCSCardGrid({
  cards,
  minCardWidth = 200,
  gap = 12,
  isDark = false,
}: IBCSCardGridProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [cols, setCols] = useState(1)

  const updateCols = useCallback(() => {
    if (!containerRef.current) return
    const w = containerRef.current.offsetWidth
    const c = Math.max(1, Math.floor((w + gap) / (minCardWidth + gap)))
    setCols(c)
  }, [minCardWidth, gap])

  useEffect(() => {
    updateCols()
    const ro = new ResizeObserver(updateCols)
    if (containerRef.current) ro.observe(containerRef.current)
    return () => ro.disconnect()
  }, [updateCols])

  if (cards.length === 0) {
    return (
      <div
        className="flex items-center justify-center h-full text-muted-foreground text-xs"
        data-testid="kpi-card-grid-empty"
      >
        No cards
      </div>
    )
  }

  return (
    <div
      ref={containerRef}
      className="w-full h-full overflow-auto p-2"
      data-testid="kpi-card-grid"
      style={{
        display: 'grid',
        gridTemplateColumns: `repeat(${cols}, 1fr)`,
        gap: `${gap}px`,
      }}
    >
      {cards.map((card) => (
        <div
          key={card.id}
          className="border rounded-md overflow-hidden"
          style={{
            borderColor: isDark ? '#333' : '#e8e8e8',
            backgroundColor: isDark ? '#1a1a1a' : '#fff',
          }}
          data-testid="kpi-card-grid-item"
        >
          <IBCSCard
            columns={card.columns}
            rows={card.rows}
            isDark={isDark}
            invert={card.invert}
          />
        </div>
      ))}
    </div>
  )
}

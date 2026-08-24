import { useState, useCallback, useRef, useEffect, useMemo, lazy, Suspense } from 'react'
import { createPortal } from 'react-dom'
import { useReportStore } from '@/stores'
import { renderTooltipPage, type TooltipPageVisualResult } from '@/lib/api'

const Plot = lazy(() => import('react-plotly.js'))

interface TooltipHoverData {
  /** Page ID of the tooltip page to render */
  tooltipPageId: string
  /** Mouse position for popup placement */
  mouseX: number
  mouseY: number
  /** Category/dimension values from the hovered data point */
  filterContext: Record<string, unknown>
}

interface TooltipPopupProps {
  hoverData: TooltipHoverData | null
  onDismiss: () => void
}

/**
 * Floating popup that renders a tooltip page's visuals
 * when hovering over a chart data point.
 * Phase 2: fetches and renders actual Plotly figures from the backend.
 */
export function TooltipPopup({ hoverData, onDismiss }: TooltipPopupProps) {
  const pages = useReportStore(s => s.pages)
  const popupRef = useRef<HTMLDivElement>(null)
  const [position, setPosition] = useState({ left: 0, top: 0 })
  const [renderedVisuals, setRenderedVisuals] = useState<TooltipPageVisualResult[]>([])
  const [loading, setLoading] = useState(false)
  const [pageTitle, setPageTitle] = useState('')
  const abortRef = useRef<AbortController | null>(null)

  // Find the tooltip page
  const tooltipPage = useMemo(() => {
    if (!hoverData) return null
    return pages.find(p => p.id === hoverData.tooltipPageId) ?? null
  }, [pages, hoverData])

  // Compute popup position (offset from mouse, clamped to viewport)
  useEffect(() => {
    if (!hoverData) return
    const offset = 16
    const popupWidth = 320
    const popupHeight = 260
    const vw = window.innerWidth
    const vh = window.innerHeight

    let left = hoverData.mouseX + offset
    let top = hoverData.mouseY + offset

    // Clamp to viewport
    if (left + popupWidth > vw - 8) left = hoverData.mouseX - popupWidth - offset
    if (top + popupHeight > vh - 8) top = hoverData.mouseY - popupHeight - offset
    if (left < 8) left = 8
    if (top < 8) top = 8

    setPosition({ left, top })
  }, [hoverData])

  // Fetch rendered visuals from the backend when hover data changes
  useEffect(() => {
    if (!hoverData || !tooltipPage) {
      setRenderedVisuals([])
      setPageTitle('')
      return
    }

    // Abort any previous in-flight request
    if (abortRef.current) abortRef.current.abort()
    const controller = new AbortController()
    abortRef.current = controller

    setLoading(true)

    renderTooltipPage(hoverData.tooltipPageId, {
      filter_context: hoverData.filterContext,
    }).then(resp => {
      if (controller.signal.aborted) return
      if (resp.data?.ok) {
        setRenderedVisuals(resp.data.visuals || [])
        setPageTitle(resp.data.page_title || tooltipPage.title || '')
      }
    }).catch(() => {
      if (controller.signal.aborted) return
      // Silently degrade — keep showing the page title
    }).finally(() => {
      if (!controller.signal.aborted) setLoading(false)
    })

    return () => { controller.abort() }
  }, [hoverData?.tooltipPageId, hoverData?.filterContext, tooltipPage])

  if (!hoverData || !tooltipPage) return null

  return createPortal(
    <div
      ref={popupRef}
      className="fixed z-[100] pointer-events-none"
      style={{
        left: position.left,
        top: position.top,
        width: 320,
        minHeight: 80,
        maxHeight: 320,
      }}
      data-testid="tooltip-page-popup"
      onMouseLeave={onDismiss}
    >
      <div className="bg-popover text-popover-foreground border rounded-lg shadow-lg overflow-hidden">
        <div className="text-xs font-medium text-muted-foreground px-3 pt-2 pb-1 border-b">
          {pageTitle || tooltipPage.title}
        </div>
        <div className="p-1 overflow-auto" style={{ maxHeight: 280 }}>
          {loading && renderedVisuals.length === 0 && (
            <div className="text-xs text-muted-foreground italic p-2">Loading...</div>
          )}
          {renderedVisuals.length > 0 && (
            <div className="space-y-1">
              {renderedVisuals.map(v => (
                <TooltipVisualMini key={v.visual_id} visual={v} />
              ))}
            </div>
          )}
          {!loading && renderedVisuals.length === 0 && (
            <div className="text-xs text-muted-foreground italic p-2">
              No visuals on this tooltip page
            </div>
          )}
        </div>
      </div>
    </div>,
    document.body
  )
}

/** Renders a single visual in tooltip-mini size (Plotly figure or card value). */
function TooltipVisualMini({ visual }: { visual: TooltipPageVisualResult }) {
  if (visual.error) {
    return (
      <div className="text-xs text-destructive px-2 py-1" data-testid="tooltip-visual-error">
        {visual.title}: {visual.error}
      </div>
    )
  }

  const fig = visual.figure as { data?: unknown[]; layout?: Record<string, unknown> } | undefined

  // Card visual — show the scalar value
  if (visual.type === 'card' && visual.rows && visual.rows.length > 0) {
    const row = visual.rows[0]
    const val = Object.values(row)[0]
    return (
      <div className="px-2 py-1" data-testid="tooltip-visual-card">
        <div className="text-[10px] text-muted-foreground">{visual.title}</div>
        <div className="text-sm font-semibold">{String(val ?? '')}</div>
      </div>
    )
  }

  // Plotly figure
  if (fig?.data && Array.isArray(fig.data)) {
    const miniLayout: Record<string, unknown> = {
      ...(fig.layout ?? {}),
      width: 300,
      height: 140,
      margin: { l: 30, r: 10, t: 20, b: 25 },
      showlegend: false,
      paper_bgcolor: 'transparent',
      plot_bgcolor: 'transparent',
      font: { size: 9 },
    }
    return (
      <div className="px-1 py-0.5" data-testid="tooltip-visual-chart">
        {visual.title && (
          <div className="text-[10px] text-muted-foreground px-1">{visual.title}</div>
        )}
        <Suspense fallback={<div className="h-[140px] flex items-center justify-center text-xs text-muted-foreground">Loading chart...</div>}>
          <Plot
            data={fig.data as Plotly.Data[]}
            layout={miniLayout as Partial<Plotly.Layout>}
            config={{ displayModeBar: false, staticPlot: true, responsive: false }}
            style={{ width: 300, height: 140 }}
          />
        </Suspense>
      </div>
    )
  }

  // Table fallback — show rows
  if (visual.columns && visual.rows && visual.rows.length > 0) {
    return (
      <div className="px-2 py-1" data-testid="tooltip-visual-table">
        <div className="text-[10px] text-muted-foreground mb-0.5">{visual.title}</div>
        <table className="text-[10px] w-full">
          <thead>
            <tr>
              {visual.columns.map(c => (
                <th key={c} className="text-left font-medium px-1">{c}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {visual.rows.slice(0, 5).map((r, i) => (
              <tr key={i}>
                {visual.columns!.map(c => (
                  <td key={c} className="px-1">{String(r[c] ?? '')}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    )
  }

  return null
}

/**
 * Hook that manages tooltip page hover state for a visual.
 * Returns the current hover data and handlers to show/dismiss.
 */
export function useTooltipPage(tooltipPageId: string | null | undefined) {
  const [hoverData, setHoverData] = useState<TooltipHoverData | null>(null)
  const dismissTimerRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)

  const showTooltip = useCallback(
    (mouseX: number, mouseY: number, filterContext: Record<string, unknown>) => {
      if (!tooltipPageId) return
      if (dismissTimerRef.current) {
        clearTimeout(dismissTimerRef.current)
        dismissTimerRef.current = undefined
      }
      setHoverData({ tooltipPageId, mouseX, mouseY, filterContext })
    },
    [tooltipPageId]
  )

  const dismissTooltip = useCallback(() => {
    // Small delay to prevent flicker when moving between data points
    dismissTimerRef.current = setTimeout(() => {
      setHoverData(null)
    }, 150)
  }, [])

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (dismissTimerRef.current) clearTimeout(dismissTimerRef.current)
    }
  }, [])

  return {
    hoverData,
    showTooltip,
    dismissTooltip,
    hasTooltipPage: Boolean(tooltipPageId),
  }
}

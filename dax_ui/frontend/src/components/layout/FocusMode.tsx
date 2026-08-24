import { useCallback, useEffect, useMemo, lazy, Suspense } from 'react'
import { X, Download, Loader2, AlertTriangle, ShieldAlert } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { useAppStore, useReportStore } from '@/stores'
import { useVisualRender, useTheme } from '@/hooks'
import { EMPTY_RENDER_STATE } from '@/hooks/useVisualRender'
import { exportVisual } from '@/lib/api'
import { toast } from '@/components/ui/toast'
import { isHighlightResponse, mergeHighlightResponse } from '@/lib/highlightMerge'
import { MatrixVisual } from '@/components/visuals/MatrixVisual'
import type { TablixPlan } from '@/types/matrix'
import { useState } from 'react'

const Plot = lazy(() => import('react-plotly.js'))

// Helper component to avoid TypeScript issues with conditional rendering of unknown types
function ErrorDisplay({ show, error }: { show: boolean; error: unknown }): React.JSX.Element | null {
  if (!show) return null
  return (
    <div className="flex flex-col items-center justify-center h-full p-6 text-center">
      <AlertTriangle className="h-10 w-10 text-destructive mb-3" />
      <p className="text-sm text-destructive">{String(error ?? 'Unknown error')}</p>
    </div>
  )
}

/**
 * FocusMode — full-screen overlay for a single visual.
 * Renders the visual at maximum available viewport size.
 * Triggered via VisualCard focus button or context menu.
 */
export function FocusMode() {
  const focusedVisualId = useAppStore(s => s.focusedVisualId)
  const setFocusedVisualId = useAppStore(s => s.setFocusedVisualId)
  const projectPath = useAppStore(s => s.projectPath)
  const currentRole = useAppStore(s => s.currentRole)
  const visuals = useReportStore(s => s.visuals)
  const { render } = useVisualRender()
  const { effectiveTheme } = useTheme()
  const isDark = effectiveTheme === 'dark'
  const [exporting, setExporting] = useState(false)

  const visual = useMemo(
    () => visuals.find(v => v.id === focusedVisualId) ?? null,
    [visuals, focusedVisualId]
  )

  // Trigger a fresh render when focus mode opens
  useEffect(() => {
    if (focusedVisualId) {
      render(focusedVisualId, { force: true })
    }
  }, [focusedVisualId, render])

  // Close on Escape
  useEffect(() => {
    if (!focusedVisualId) return
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault()
        e.stopPropagation()
        setFocusedVisualId(null)
      }
    }
    document.addEventListener('keydown', handleKeyDown, true)
    return () => document.removeEventListener('keydown', handleKeyDown, true)
  }, [focusedVisualId, setFocusedVisualId])

  const handleClose = useCallback(() => {
    setFocusedVisualId(null)
  }, [setFocusedVisualId])

  const handleExport = useCallback(async () => {
    if (!focusedVisualId) return
    setExporting(true)
    try {
      await exportVisual(focusedVisualId, projectPath ?? undefined, currentRole ?? undefined)
      toast('Export complete', { variant: 'success' })
    } catch {
      toast('Export failed', { variant: 'error' })
    } finally {
      setExporting(false)
    }
  }, [focusedVisualId, projectPath, currentRole])

  // Per-visual reactive subscription — must be called unconditionally (hooks rules).
  // When focusedVisualId is null the selector returns EMPTY_RENDER_STATE (stable).
  const state = useReportStore(s =>
    focusedVisualId ? (s.renderStates[focusedVisualId] ?? EMPTY_RENDER_STATE) : EMPTY_RENDER_STATE
  )

  if (!focusedVisualId || !visual) return null

  const { loading, blocked, hiddenRefs, error } = state
  const data = state.data as unknown
  const visualType = visual.visual_type?.toLowerCase() || 'unknown'
  const showError: boolean = Boolean(error) && !loading && data == null

  return (
    <div
      className="fixed inset-0 z-[100] flex flex-col bg-background/95 backdrop-blur-sm"
      data-testid="focus-mode-overlay"
      onClick={handleClose}
    >
      {/* Header bar */}
      <div
        className="flex items-center justify-between px-6 py-3 border-b bg-card/80 backdrop-blur-sm shrink-0"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-3">
          <h2
            className="text-sm font-semibold truncate max-w-[600px]"
            data-testid="focus-mode-title"
          >
            {visual.title || visual.id}
          </h2>
          <span className="text-xs text-muted-foreground">
            {visual.visual_type}
          </span>
          {blocked && (
            <span className="inline-flex items-center text-destructive gap-1">
              <ShieldAlert className="h-3.5 w-3.5" />
              <span className="text-xs">Blocked</span>
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={handleExport}
            disabled={exporting}
            data-testid="focus-mode-export"
          >
            {exporting ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin mr-1.5" />
            ) : (
              <Download className="h-3.5 w-3.5 mr-1.5" />
            )}
            Export
          </Button>
          <Button
            variant="ghost"
            size="icon"
            onClick={handleClose}
            data-testid="focus-mode-close"
            aria-label="Close focus mode"
          >
            <X className="h-5 w-5" />
          </Button>
        </div>
      </div>

      {/* Content area — full remaining height */}
      <div
        className="flex-1 overflow-hidden p-6"
        data-testid="focus-mode-content"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="w-full h-full bg-card rounded-lg border shadow-sm overflow-hidden">
          {/* Loading spinner */}
          {loading && !data && (
            <div className="flex items-center justify-center h-full">
              <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
            </div>
          )}

          {/* Error state */}
          <ErrorDisplay show={showError} error={error} />

          {/* Blocked state (OLS) */}
          {blocked && !loading && (
            <div className="flex flex-col items-center justify-center h-full p-6 text-center bg-destructive/5">
              <ShieldAlert className="h-10 w-10 text-destructive mb-3" />
              <p className="text-sm text-destructive font-medium">Visual Blocked</p>
              <p className="text-sm text-muted-foreground mt-1">
                Contains fields hidden by the active security role.
              </p>
              {hiddenRefs && hiddenRefs.length > 0 && (
                <div className="mt-3 text-xs text-muted-foreground max-h-32 overflow-auto">
                  {hiddenRefs.map((ref: { kind: string; table?: string; column?: string; name?: string }, i: number) => (
                    <div key={i}>
                      {ref.kind === 'column' && `${ref.table}[${ref.column}]`}
                      {ref.kind === 'measure' && ref.name}
                      {ref.kind === 'table' && ref.table}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* Render visual content at full size */}
          {!blocked && data != null && (
            <FocusVisualContent
              visual={visual}
              data={data}
              visualType={visualType}
              isDark={isDark}
            />
          )}
        </div>
      </div>
    </div>
  )
}

// ─── Focused Visual Content Renderer ────────────────────────────────

interface FocusVisualContentProps {
  visual: { id: string; visual_type?: string; title?: string; encodings?: Record<string, unknown> }
  data: unknown
  visualType: string
  isDark: boolean
}

function FocusVisualContent({ visual: _visual, data, visualType, isDark }: FocusVisualContentProps) {
  // Handle highlight dual-query response merge
  let effectiveData = data
  if (isHighlightResponse(data)) {
    effectiveData = mergeHighlightResponse(visualType, data)
  }

  const rawData = effectiveData as {
    columns?: string[]
    rows?: Array<Record<string, unknown>>
    plotly_data?: unknown[]
    plotly_layout?: Record<string, unknown>
    figure?: { data?: unknown[]; layout?: Record<string, unknown> }
    value?: unknown
    title?: string
    tablix_plan?: TablixPlan
    tablix?: TablixPlan
    _highlight_merged?: boolean
    _card_title?: string
  }

  const renderData = {
    ...rawData,
    plotly_data: rawData.plotly_data ?? rawData.figure?.data,
    plotly_layout: rawData.plotly_layout ?? rawData.figure?.layout,
  }

  // Card
  if (visualType === 'card') {
    if (rawData._highlight_merged && rawData._card_title) {
      const cardTitle = typeof rawData._card_title === 'object'
        ? String((rawData._card_title as Record<string, unknown>).text ?? rawData._card_title)
        : String(rawData._card_title)
      return (
        <div className="flex flex-col items-center justify-center h-full p-8">
          <span className="text-6xl font-bold">{cardTitle}</span>
        </div>
      )
    }
    const rawValue = renderData.rows?.[0]
      ? Object.values(renderData.rows[0])[0]
      : renderData.value ?? null
    const value = rawValue == null ? '–' : typeof rawValue === 'number' ? rawValue.toLocaleString() : String(rawValue)
    return (
      <div className="flex flex-col items-center justify-center h-full p-8">
        <span className="text-6xl font-bold">{value}</span>
      </div>
    )
  }

  // Table/Tablix
  if (visualType === 'table' || visualType === 'tablix') {
    const columns = renderData.columns || []
    const rows = renderData.rows || []
    return (
      <div className="h-full overflow-auto">
        <table className="w-full text-sm">
          <thead className="sticky top-0 bg-muted">
            <tr>
              {columns.map((col) => (
                <th key={col} className="px-3 py-2 text-left font-medium border-b">
                  {col}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, i) => (
              <tr key={i} className="hover:bg-muted/50">
                {columns.map((col) => (
                  <td key={col} className="px-3 py-1.5 border-b">
                    {formatCellValue(row[col])}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    )
  }

  // Matrix
  if (visualType === 'matrix') {
    const tablixData = renderData.tablix_plan ?? renderData.tablix
    if (tablixData) {
      return <MatrixVisual data={tablixData} className="h-full" />
    }
    const columns = renderData.columns || []
    const rows = renderData.rows || []
    return (
      <div className="h-full overflow-auto">
        <table className="w-full text-sm">
          <thead className="sticky top-0 bg-muted">
            <tr>
              {columns.map((col) => (
                <th key={col} className="px-3 py-2 text-left font-medium border-b">{col}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, i) => (
              <tr key={i} className="hover:bg-muted/50">
                {columns.map((col) => (
                  <td key={col} className="px-3 py-1.5 border-b">{formatCellValue(row[col])}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    )
  }

  // Chart visuals
  if (['bar', 'column', 'line', 'pie', 'area', 'scatter', 'combo'].includes(visualType)) {
    if (renderData.plotly_data && renderData.plotly_data.length > 0) {
      return (
        <Suspense fallback={<FocusLoadingPlaceholder />}>
          <FocusPlotlyChart data={renderData.plotly_data} layout={renderData.plotly_layout} isDark={isDark} />
        </Suspense>
      )
    }
    return (
      <div className="flex items-center justify-center h-full text-muted-foreground">
        <span className="text-sm">No chart data</span>
      </div>
    )
  }

  // Unknown
  return (
    <div className="flex items-center justify-center h-full text-muted-foreground">
      <span className="text-sm">{visualType}</span>
    </div>
  )
}

// ─── Focused Plotly Chart (full-size, no click handlers) ────────────

function FocusPlotlyChart({
  data,
  layout,
  isDark,
}: {
  data: unknown[]
  layout?: Record<string, unknown>
  isDark: boolean
}) {
  const plotLayout = useMemo(() => {
    const fontColor = isDark ? '#e0e4ec' : '#1e293b'
    const gridColor = isDark ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.06)'
    return {
      autosize: true,
      margin: { l: 60, r: 40, t: 40, b: 60 },
      paper_bgcolor: 'transparent',
      plot_bgcolor: 'transparent',
      font: { size: 12, color: fontColor },
      xaxis: { gridcolor: gridColor, zerolinecolor: gridColor, ...(layout?.xaxis as Record<string, unknown> ?? {}) },
      yaxis: { gridcolor: gridColor, zerolinecolor: gridColor, ...(layout?.yaxis as Record<string, unknown> ?? {}) },
      legend: { font: { color: fontColor }, ...(layout?.legend as Record<string, unknown> ?? {}) },
      ...layout,
      ...(layout?.font ? {} : { font: { size: 12, color: fontColor } }),
    }
  }, [layout, isDark])

  return (
    <div className="w-full h-full" data-testid="focus-plotly-chart">
      <Suspense fallback={<FocusLoadingPlaceholder />}>
        <Plot
          data={data as Plotly.Data[]}
          layout={plotLayout as Partial<Plotly.Layout>}
          config={{ displayModeBar: true, responsive: true }}
          style={{ width: '100%', height: '100%' }}
          useResizeHandler
        />
      </Suspense>
    </div>
  )
}

function FocusLoadingPlaceholder() {
  return (
    <div className="flex items-center justify-center h-full">
      <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
    </div>
  )
}

function formatCellValue(value: unknown): string {
  if (value === null || value === undefined) return '-'
  if (typeof value === 'number') {
    return Number.isInteger(value)
      ? value.toLocaleString()
      : value.toLocaleString(undefined, { maximumFractionDigits: 2 })
  }
  if (typeof value === 'boolean') return value ? 'Yes' : 'No'
  return String(value)
}

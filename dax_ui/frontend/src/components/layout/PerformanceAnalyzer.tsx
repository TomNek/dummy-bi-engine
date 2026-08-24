import { useCallback, useRef, useState } from 'react'
import {
  Play,
  Square,
  Trash2,
  ChevronDown,
  ChevronRight,
  Copy,
  Check,
  RefreshCw,
  Timer,
  Database,
  Cpu,
  Wifi,
  X,
  ChevronsDown,
  ChevronsUp,
  AlertCircle,
  Sparkles,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { ScrollArea } from '@/components/ui/scroll-area'
import { usePerfStore, type PerfEvent } from '@/stores/perf-store'
import { useDaxAnalyzerStore } from '@/stores/dax-analyzer-store'
import { useVisualRender } from '@/hooks'

/**
 * Performance Analyzer panel — a bottom drawer (like PBI's Performance Analyzer)
 * that captures and displays render timing breakdowns per visual.
 *
 * Features:
 * - Start/Stop recording
 * - Refresh visuals (triggers a fresh render-all while recording)
 * - Clear captured events
 * - Expand event to see SQL + timing breakdown bar
 * - Copy SQL to clipboard
 */
export function PerformanceAnalyzer() {
  const isOpen = usePerfStore(s => s.isOpen)
  const isRecording = usePerfStore(s => s.isRecording)
  const events = usePerfStore(s => s.events)
  const expandedIds = usePerfStore(s => s.expandedIds)
  const close = usePerfStore(s => s.close)
  const startRecording = usePerfStore(s => s.startRecording)
  const stopRecording = usePerfStore(s => s.stopRecording)
  const clearEvents = usePerfStore(s => s.clearEvents)
  const toggleExpanded = usePerfStore(s => s.toggleExpanded)
  const expandAll = usePerfStore(s => s.expandAll)
  const collapseAll = usePerfStore(s => s.collapseAll)

  const { renderAll } = useVisualRender()
  const [copiedId, setCopiedId] = useState<number | null>(null)

  const handleRefreshVisuals = useCallback(() => {
    // Start recording if not already, then render all visuals
    if (!usePerfStore.getState().isRecording) {
      usePerfStore.getState().startRecording()
    }
    renderAll({ force: true })
  }, [renderAll])

  const copySQL = useCallback((sql: string, eventId: number) => {
    navigator.clipboard.writeText(sql).then(() => {
      setCopiedId(eventId)
      setTimeout(() => setCopiedId(null), 1500)
    }).catch(() => {})
  }, [])

  if (!isOpen) return null

  return (
    <div
      className="border-t bg-background flex flex-col"
      style={{ height: 280 }}
      data-testid="perf-analyzer-panel"
    >
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-1.5 border-b bg-muted/30 shrink-0">
        <div className="flex items-center gap-2">
          <Timer className="h-4 w-4 text-primary" />
          <span className="text-xs font-semibold">Performance Analyzer</span>
          {isRecording && (
            <span className="flex items-center gap-1 text-[10px] text-red-500 font-medium" data-testid="perf-recording-badge">
              <span className="h-2 w-2 rounded-full bg-red-500 animate-pulse" />
              Recording
            </span>
          )}
        </div>
        <div className="flex items-center gap-1">
          {/* Start / Stop */}
          {!isRecording ? (
            <Button
              variant="ghost"
              size="sm"
              className="h-7 text-xs gap-1"
              onClick={startRecording}
              data-testid="perf-start-btn"
            >
              <Play className="h-3 w-3" />
              Start
            </Button>
          ) : (
            <Button
              variant="ghost"
              size="sm"
              className="h-7 text-xs gap-1"
              onClick={stopRecording}
              data-testid="perf-stop-btn"
            >
              <Square className="h-3 w-3" />
              Stop
            </Button>
          )}

          {/* Refresh Visuals */}
          <Button
            variant="ghost"
            size="sm"
            className="h-7 text-xs gap-1"
            onClick={handleRefreshVisuals}
            data-testid="perf-refresh-btn"
          >
            <RefreshCw className="h-3 w-3" />
            Refresh visuals
          </Button>

          {/* Open DAX Analyzer */}
          <Button
            variant="ghost"
            size="sm"
            className="h-7 text-xs gap-1"
            onClick={() => useDaxAnalyzerStore.getState().open()}
            data-testid="perf-open-dax-analyzer"
          >
            <Sparkles className="h-3 w-3" />
            DAX Analyzer
          </Button>

          {/* Expand / Collapse all */}
          <Button variant="ghost" size="icon" className="h-7 w-7" onClick={expandAll} title="Expand all">
            <ChevronsDown className="h-3 w-3" />
          </Button>
          <Button variant="ghost" size="icon" className="h-7 w-7" onClick={collapseAll} title="Collapse all">
            <ChevronsUp className="h-3 w-3" />
          </Button>

          {/* Clear */}
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7"
            onClick={clearEvents}
            data-testid="perf-clear-btn"
            title="Clear events"
          >
            <Trash2 className="h-3 w-3" />
          </Button>

          {/* Close */}
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7"
            onClick={close}
            data-testid="perf-close-btn"
            title="Close"
          >
            <X className="h-3 w-3" />
          </Button>
        </div>
      </div>

      {/* Events list */}
      <ScrollArea className="flex-1 min-h-0">
        {events.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full py-8 text-muted-foreground">
            <Timer className="h-8 w-8 mb-2 opacity-40" />
            <p className="text-xs">
              {isRecording
                ? 'Recording… Interact with visuals or click "Refresh visuals" to capture events.'
                : 'Click "Start" to begin recording performance events.'}
            </p>
          </div>
        ) : (
          <div className="divide-y">
            {events.map(event => (
              <PerfEventRow
                key={event.id}
                event={event}
                isExpanded={expandedIds.has(event.id)}
                onToggle={() => toggleExpanded(event.id)}
                onCopySQL={() => copySQL(event.sql, event.id)}
                isCopied={copiedId === event.id}
              />
            ))}
          </div>
        )}
      </ScrollArea>
    </div>
  )
}

// ── Single event row ────────────────────────────────────────

interface PerfEventRowProps {
  event: PerfEvent
  isExpanded: boolean
  onToggle: () => void
  onCopySQL: () => void
  isCopied: boolean
}

function PerfEventRow({ event, isExpanded, onToggle, onCopySQL, isCopied }: PerfEventRowProps) {
  const maxBar = Math.max(event.totalMs, 1)

  const planPct = (event.planMs / maxBar) * 100
  const execPct = (event.executeMs / maxBar) * 100
  const otherPct = (event.otherMs / maxBar) * 100

  const timeLabel = new Date(event.timestamp).toLocaleTimeString()

  return (
    <div
      className={cn(
        'px-3 py-1.5 hover:bg-accent/30 transition-colors',
        !event.success && 'bg-destructive/5'
      )}
      data-testid={`perf-event-${event.id}`}
    >
      {/* Summary row */}
      <div
        className="flex items-center gap-2 cursor-pointer select-none"
        onClick={onToggle}
      >
        {isExpanded ? (
          <ChevronDown className="h-3 w-3 shrink-0 text-muted-foreground" />
        ) : (
          <ChevronRight className="h-3 w-3 shrink-0 text-muted-foreground" />
        )}

        {!event.success && <AlertCircle className="h-3 w-3 shrink-0 text-destructive" />}

        <span className="text-xs font-medium truncate min-w-0 flex-1" title={event.visualTitle}>
          {event.visualTitle || event.visualId}
        </span>

        <span className="text-[10px] text-muted-foreground px-1.5 py-0.5 bg-muted rounded shrink-0">
          {event.visualType}
        </span>

        <span
          className={cn(
            'text-xs font-mono tabular-nums shrink-0',
            event.totalMs > 1000 ? 'text-orange-500 font-semibold' : 'text-muted-foreground'
          )}
          data-testid={`perf-event-total-${event.id}`}
        >
          {formatMs(event.totalMs)}
        </span>

        <span className="text-[10px] text-muted-foreground shrink-0">{timeLabel}</span>
      </div>

      {/* Expanded details */}
      {isExpanded && (
        <div className="mt-2 ml-5 space-y-2" data-testid={`perf-event-detail-${event.id}`}>
          {/* Timing breakdown bar */}
          <div className="space-y-1">
            <div className="flex items-center gap-3 text-[10px]">
              <TimingChip icon={Cpu} label="Plan" value={event.planMs} color="bg-blue-500" />
              <TimingChip icon={Database} label="Execute" value={event.executeMs} color="bg-green-500" />
              <span title="Network latency + JSON serialization + server overhead (total time minus plan time minus execution time)">
                <TimingChip icon={Wifi} label="Other" value={event.otherMs} color="bg-amber-500" />
              </span>
            </div>

            {/* Stacked bar */}
            <div className="h-2 rounded-full bg-muted overflow-hidden flex">
              {planPct > 0 && (
                <div className="bg-blue-500 h-full" style={{ width: `${planPct}%` }} title={`Plan: ${formatMs(event.planMs)}`} />
              )}
              {execPct > 0 && (
                <div className="bg-green-500 h-full" style={{ width: `${execPct}%` }} title={`Execute: ${formatMs(event.executeMs)}`} />
              )}
              {otherPct > 0 && (
                <div className="bg-amber-500 h-full" style={{ width: `${otherPct}%` }} title={`Other: ${formatMs(event.otherMs)} (network + serialization + server overhead)`} />
              )}
            </div>

            <div className="text-[10px] text-muted-foreground">
              {event.rowCount !== undefined && <span>Rows: {event.rowCount}</span>}
            </div>
          </div>

          {/* SQL */}
          {event.sql && (
            <div className="relative">
              <pre className="text-[10px] bg-muted p-2 pr-8 rounded overflow-x-auto max-h-28 whitespace-pre-wrap font-mono">
                {event.sql}
              </pre>
              <Button
                variant="ghost"
                size="icon"
                className="absolute top-1 right-1 h-6 w-6"
                onClick={(e) => { e.stopPropagation(); onCopySQL() }}
                title="Copy SQL"
              >
                {isCopied ? (
                  <Check className="h-3 w-3 text-green-500" />
                ) : (
                  <Copy className="h-3 w-3" />
                )}
              </Button>
            </div>
          )}

          {/* Error */}
          {event.error && (
            <div className="text-[10px] text-destructive bg-destructive/10 p-2 rounded">
              {event.error}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ── Helpers ─────────────────────────────────────────────────

interface TimingChipProps {
  icon: React.ComponentType<{ className?: string }>
  label: string
  value: number
  color: string
}

function TimingChip({ icon: Icon, label, value, color }: TimingChipProps) {
  return (
    <span className="inline-flex items-center gap-1">
      <span className={cn('h-2 w-2 rounded-sm', color)} />
      <Icon className="h-3 w-3 text-muted-foreground" />
      <span className="text-muted-foreground">{label}:</span>
      <span className="font-mono tabular-nums">{formatMs(value)}</span>
    </span>
  )
}

function formatMs(ms: number): string {
  if (ms >= 1000) return `${(ms / 1000).toFixed(2)}s`
  return `${Math.round(ms)}ms`
}

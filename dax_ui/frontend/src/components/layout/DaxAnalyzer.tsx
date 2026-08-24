import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  X,
  Search,
  Copy,
  Check,
  AlertTriangle,
  Zap,
  Layers,
  GitBranch,
  Table2,
  ChevronDown,
  ChevronRight,
  Loader2,
  Trash2,
  Sparkles,
  Filter,
  BarChart3,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { ScrollArea } from '@/components/ui/scroll-area'
import { useDaxAnalyzerStore, type AnalyzedMeasure } from '@/stores/dax-analyzer-store'
import { listMeasures, type MeasureDetail } from '@/lib/api'

/**
 * DAX Analyzer panel — a bottom drawer (like the Performance Analyzer)
 * that lets users select measures, analyze their DAX → SQL compilation,
 * view complexity metrics, and get optimization suggestions.
 */
export function DaxAnalyzer() {
  const isOpen = useDaxAnalyzerStore(s => s.isOpen)
  const isAnalyzing = useDaxAnalyzerStore(s => s.isAnalyzing)
  const selectedMeasures = useDaxAnalyzerStore(s => s.selectedMeasures)
  const results = useDaxAnalyzerStore(s => s.results)
  const error = useDaxAnalyzerStore(s => s.error)
  const close = useDaxAnalyzerStore(s => s.close)
  const setSelectedMeasures = useDaxAnalyzerStore(s => s.setSelectedMeasures)
  const analyze = useDaxAnalyzerStore(s => s.analyze)
  const clear = useDaxAnalyzerStore(s => s.clear)

  // Fetch available measures when the panel opens
  const [measureList, setMeasureList] = useState<MeasureDetail[]>([])
  useEffect(() => {
    if (!isOpen) return
    listMeasures().then(res => {
      if (res.data?.measures) setMeasureList(res.data.measures)
    })
  }, [isOpen])

  const measureNames = useMemo(
    () => measureList.map(m => m.name).sort((a, b) => a.localeCompare(b)),
    [measureList],
  )

  const [filterText, setFilterText] = useState('')
  const filteredMeasures = useMemo(
    () => filterText
      ? measureNames.filter(n => n.toLowerCase().includes(filterText.toLowerCase()))
      : measureNames,
    [measureNames, filterText],
  )

  const [expandedNames, setExpandedNames] = useState<Set<string>>(new Set())
  const toggleExpanded = useCallback((name: string) => {
    setExpandedNames(prev => {
      const next = new Set(prev)
      if (next.has(name)) next.delete(name)
      else next.add(name)
      return next
    })
  }, [])

  // Auto-expand results when they arrive
  useEffect(() => {
    if (results.length > 0) {
      setExpandedNames(new Set(results.map(r => r.name)))
    }
  }, [results])

  const toggleMeasure = useCallback((name: string) => {
    setSelectedMeasures(
      selectedMeasures.includes(name)
        ? selectedMeasures.filter(n => n !== name)
        : [...selectedMeasures, name],
    )
  }, [selectedMeasures, setSelectedMeasures])

  const selectAll = useCallback(() => {
    setSelectedMeasures(filteredMeasures)
  }, [filteredMeasures, setSelectedMeasures])

  const selectNone = useCallback(() => {
    setSelectedMeasures([])
  }, [setSelectedMeasures])

  if (!isOpen) return null

  return (
    <div
      className="border-t bg-background flex flex-col"
      style={{ height: 340 }}
      data-testid="dax-analyzer-panel"
    >
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-1.5 border-b bg-muted/30 shrink-0">
        <div className="flex items-center gap-2">
          <Sparkles className="h-4 w-4 text-primary" />
          <span className="text-xs font-semibold">DAX Analyzer</span>
          {isAnalyzing && (
            <span className="flex items-center gap-1 text-[10px] text-blue-500 font-medium">
              <Loader2 className="h-3 w-3 animate-spin" />
              Analyzing…
            </span>
          )}
        </div>
        <div className="flex items-center gap-1">
          <Button
            variant="ghost"
            size="sm"
            className="h-7 text-xs gap-1"
            onClick={analyze}
            disabled={isAnalyzing || selectedMeasures.length === 0}
            data-testid="dax-analyze-btn"
          >
            <Search className="h-3 w-3" />
            Analyze {selectedMeasures.length > 0 && `(${selectedMeasures.length})`}
          </Button>
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7"
            onClick={clear}
            title="Clear results"
            data-testid="dax-analyzer-clear"
          >
            <Trash2 className="h-3 w-3" />
          </Button>
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7"
            onClick={close}
            title="Close"
            data-testid="dax-analyzer-close"
          >
            <X className="h-3 w-3" />
          </Button>
        </div>
      </div>

      {/* Content — two panes */}
      <div className="flex flex-1 overflow-hidden min-h-0">
        {/* Left: Measure picker */}
        <div className="w-56 border-r flex flex-col shrink-0">
          <div className="px-2 py-1.5 border-b">
            <input
              type="text"
              className="w-full h-6 px-2 text-[11px] rounded bg-muted border border-border focus:outline-none focus:ring-1 focus:ring-primary"
              placeholder="Filter measures…"
              value={filterText}
              onChange={e => setFilterText(e.target.value)}
              data-testid="dax-analyzer-filter"
            />
            <div className="flex gap-1 mt-1">
              <button
                className="text-[10px] text-primary hover:underline"
                onClick={selectAll}
              >
                All
              </button>
              <span className="text-[10px] text-muted-foreground">·</span>
              <button
                className="text-[10px] text-primary hover:underline"
                onClick={selectNone}
              >
                None
              </button>
              <span className="text-[10px] text-muted-foreground ml-auto">
                {selectedMeasures.length} selected
              </span>
            </div>
          </div>
          <ScrollArea className="flex-1 min-h-0">
            <div className="p-1">
              {filteredMeasures.length === 0 ? (
                <p className="text-[10px] text-muted-foreground px-2 py-4 text-center">
                  {measureNames.length === 0 ? 'No measures in project' : 'No matches'}
                </p>
              ) : (
                filteredMeasures.map(name => (
                  <label
                    key={name}
                    className="flex items-center gap-1.5 px-2 py-0.5 hover:bg-accent/30 rounded cursor-pointer"
                  >
                    <input
                      type="checkbox"
                      className="h-3 w-3 rounded"
                      checked={selectedMeasures.includes(name)}
                      onChange={() => toggleMeasure(name)}
                    />
                    <span className="text-[11px] truncate">{name}</span>
                  </label>
                ))
              )}
            </div>
          </ScrollArea>
        </div>

        {/* Right: Results panel */}
        <ScrollArea className="flex-1 min-h-0">
          {error && (
            <div className="m-2 p-2 rounded bg-destructive/10 text-destructive text-xs flex items-start gap-2">
              <AlertTriangle className="h-4 w-4 shrink-0 mt-0.5" />
              <span>{error}</span>
            </div>
          )}

          {results.length === 0 && !error && (
            <div className="flex flex-col items-center justify-center h-full py-8 text-muted-foreground">
              <Sparkles className="h-8 w-8 mb-2 opacity-40" />
              <p className="text-xs text-center max-w-xs">
                Select measures on the left and click <strong>Analyze</strong> to see DAX complexity,
                compiled SQL, and optimization suggestions.
              </p>
            </div>
          )}

          <div className="divide-y">
            {results.map(r => (
              <AnalyzedMeasureRow
                key={r.name}
                result={r}
                isExpanded={expandedNames.has(r.name)}
                onToggle={() => toggleExpanded(r.name)}
              />
            ))}
          </div>
        </ScrollArea>
      </div>
    </div>
  )
}


// ── Single analyzed measure row ────────────────────────────

interface AnalyzedMeasureRowProps {
  result: AnalyzedMeasure
  isExpanded: boolean
  onToggle: () => void
}

function AnalyzedMeasureRow({ result, isExpanded, onToggle }: AnalyzedMeasureRowProps) {
  const [copiedField, setCopiedField] = useState<string | null>(null)

  const copy = useCallback((text: string, field: string) => {
    navigator.clipboard.writeText(text).then(() => {
      setCopiedField(field)
      setTimeout(() => setCopiedField(null), 1500)
    }).catch(() => {})
  }, [])

  const { complexity } = result
  const severityColor = useMemo(() => {
    if (complexity.nesting_depth > 3 || complexity.iterator_count > 2) return 'text-red-500'
    if (complexity.nesting_depth > 1 || complexity.filter_contexts > 2) return 'text-amber-500'
    return 'text-green-500'
  }, [complexity])

  return (
    <div
      className={cn('px-3 py-1.5 hover:bg-accent/30 transition-colors', result.error && 'bg-destructive/5')}
      data-testid={`dax-result-${result.name}`}
    >
      {/* Summary */}
      <div className="flex items-center gap-2 cursor-pointer select-none" onClick={onToggle}>
        {isExpanded ? (
          <ChevronDown className="h-3 w-3 shrink-0 text-muted-foreground" />
        ) : (
          <ChevronRight className="h-3 w-3 shrink-0 text-muted-foreground" />
        )}

        <span className="text-xs font-medium truncate flex-1">{result.name}</span>

        {/* Pattern badge */}
        <span className="text-[10px] px-1.5 py-0.5 bg-muted rounded shrink-0">
          {result.complexity.pattern.replace(/_/g, ' ')}
        </span>

        {/* Severity indicator */}
        <Zap className={cn('h-3 w-3 shrink-0', severityColor)} />
      </div>

      {/* Expanded details */}
      {isExpanded && (
        <div className="mt-2 ml-5 space-y-3" data-testid={`dax-result-detail-${result.name}`}>
          {/* Complexity metrics */}
          <div className="flex flex-wrap gap-2">
            <MetricBadge icon={Layers} label="Nesting" value={complexity.nesting_depth} warn={complexity.nesting_depth > 2} />
            <MetricBadge icon={Filter} label="Filters" value={complexity.filter_contexts} warn={complexity.filter_contexts > 2} />
            <MetricBadge icon={BarChart3} label="Iterators" value={complexity.iterator_count} warn={complexity.iterator_count > 1} />
            <MetricBadge icon={Table2} label="Tables" value={complexity.tables_referenced.length} />
            <MetricBadge icon={GitBranch} label="Measure refs" value={complexity.measure_refs.length} warn={complexity.measure_refs.length > 3} />
          </div>

          {/* Referenced measures */}
          {complexity.measure_refs.length > 0 && (
            <div className="text-[10px] text-muted-foreground">
              <span className="font-medium">References: </span>
              {complexity.measure_refs.map((m, i) => (
                <span key={m}>
                  <span className="text-primary">[{m}]</span>
                  {i < complexity.measure_refs.length - 1 && ', '}
                </span>
              ))}
            </div>
          )}

          {/* DAX expression */}
          <div className="relative">
            <label className="text-[10px] font-medium text-muted-foreground mb-0.5 block">DAX</label>
            <pre className="text-[10px] bg-muted p-2 pr-8 rounded overflow-x-auto max-h-20 whitespace-pre-wrap font-mono">
              {result.dax}
            </pre>
            <Button
              variant="ghost"
              size="icon"
              className="absolute top-5 right-1 h-6 w-6"
              onClick={() => copy(result.dax, 'dax')}
              title="Copy DAX"
            >
              {copiedField === 'dax' ? <Check className="h-3 w-3 text-green-500" /> : <Copy className="h-3 w-3" />}
            </Button>
          </div>

          {/* Compiled SQL */}
          {result.compiled_sql && (
            <div className="relative">
              <label className="text-[10px] font-medium text-muted-foreground mb-0.5 block">Compiled SQL</label>
              <pre className="text-[10px] bg-muted p-2 pr-8 rounded overflow-x-auto max-h-28 whitespace-pre-wrap font-mono">
                {result.compiled_sql}
              </pre>
              <Button
                variant="ghost"
                size="icon"
                className="absolute top-5 right-1 h-6 w-6"
                onClick={() => copy(result.compiled_sql!, 'sql')}
                title="Copy SQL"
              >
                {copiedField === 'sql' ? <Check className="h-3 w-3 text-green-500" /> : <Copy className="h-3 w-3" />}
              </Button>
            </div>
          )}

          {/* SQL Explain plan */}
          {result.sql_plan && (
            <div>
              <label className="text-[10px] font-medium text-muted-foreground mb-0.5 block">Query Plan</label>
              <pre className="text-[10px] bg-muted p-2 rounded overflow-x-auto max-h-20 whitespace-pre-wrap font-mono text-muted-foreground">
                {result.sql_plan}
              </pre>
            </div>
          )}

          {/* Suggestions */}
          {result.suggestions.length > 0 && (
            <div>
              <label className="text-[10px] font-medium text-muted-foreground mb-0.5 block">Suggestions</label>
              <ul className="space-y-0.5">
                {result.suggestions.map((s, i) => (
                  <li key={i} className="text-[10px] flex items-start gap-1.5">
                    <Sparkles className="h-3 w-3 text-amber-500 shrink-0 mt-0.5" />
                    <span>{s}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Error */}
          {result.error && (
            <div className="text-[10px] text-destructive bg-destructive/10 p-2 rounded">
              {result.error}
            </div>
          )}
        </div>
      )}
    </div>
  )
}


// ── Helpers ─────────────────────────────────────────────────

interface MetricBadgeProps {
  icon: React.ComponentType<{ className?: string }>
  label: string
  value: number
  warn?: boolean
}

function MetricBadge({ icon: Icon, label, value, warn }: MetricBadgeProps) {
  return (
    <span className={cn(
      'inline-flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded',
      warn ? 'bg-amber-500/10 text-amber-600' : 'bg-muted text-muted-foreground',
    )}>
      <Icon className="h-3 w-3" />
      <span>{label}:</span>
      <span className="font-mono font-medium">{value}</span>
    </span>
  )
}

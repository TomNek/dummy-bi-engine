/**
 * SignalConfigPanel — Per-signal configuration editor.
 *
 * Shows each signal rule as a collapsible card with:
 * - Enable/disable toggle
 * - Severity override selector
 * - Description (editable)
 * - Threshold parameters (read-only display for now)
 * - Global settings (max signals, contradiction pairs, downgrade toggle)
 *
 * Persists via PUT /runtime/decision/signals/config on Save.
 */
import { useCallback, useEffect, useState } from 'react'
import { useAppStore } from '@/stores/app-store'
import { getSignalConfig, saveSignalConfig, type SignalConfig, type SignalRuleConfig } from '@/lib/api'
import { humanizeSignalName, getSeverityStyle } from '@/lib/humanize'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  AlertTriangle,
  ChevronDown,
  ChevronRight,
  Loader2,
  Save,
  ShieldAlert,
  TrendingUp,
  TrendingDown,
  Activity,
  Zap,
  Eye,
  RotateCcw,
} from 'lucide-react'
import { cn } from '@/lib/utils'

// Signal type metadata for display (v2: 4-signal executive model)
const SIGNAL_META: Record<string, { icon: typeof AlertTriangle; colorClass: string }> = {
  STRUCTURAL: { icon: TrendingDown, colorClass: 'text-red-600' },
  EMERGING: { icon: Activity, colorClass: 'text-amber-600' },
  TRUST_DOWNGRADE: { icon: ShieldAlert, colorClass: 'text-orange-600' },
  VALUE_AT_STAKE: { icon: AlertTriangle, colorClass: 'text-red-700' },
}

const SEVERITY_OPTIONS = [
  { value: '__auto__', label: 'Auto (computed)' },
  { value: 'High', label: 'High' },
  { value: 'Medium', label: 'Medium' },
  { value: 'Low', label: 'Low' },
]

// Canonical order for signal types (v2: priority order)
const SIGNAL_ORDER = [
  'VALUE_AT_STAKE',
  'STRUCTURAL',
  'TRUST_DOWNGRADE',
  'EMERGING',
]

export function SignalConfigPanel() {
  const projectPath = useAppStore((s) => s.projectPath)
  const [config, setConfig] = useState<SignalConfig | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [dirty, setDirty] = useState(false)
  const [expandedSignal, setExpandedSignal] = useState<string | null>(null)

  // Load config
  useEffect(() => {
    let cancelled = false
    async function load() {
      setLoading(true)
      setError(null)
      const { data, error: err } = await getSignalConfig(projectPath || undefined)
      if (cancelled) return
      if (err) {
        setError(err)
        setLoading(false)
        return
      }
      if (data?.config) {
        setConfig(data.config)
      }
      setLoading(false)
    }
    load()
    return () => { cancelled = true }
  }, [projectPath])

  const updateRule = useCallback((signalType: string, patch: Partial<SignalRuleConfig>) => {
    setConfig((prev) => {
      if (!prev) return prev
      const rules = { ...prev.signal_rules }
      rules[signalType] = { ...rules[signalType], ...patch }
      return { ...prev, signal_rules: rules }
    })
    setDirty(true)
  }, [])

  const updateGlobal = useCallback((key: string, value: unknown) => {
    setConfig((prev) => {
      if (!prev) return prev
      return {
        ...prev,
        global_settings: { ...prev.global_settings, [key]: value },
      }
    })
    setDirty(true)
  }, [])

  const handleSave = useCallback(async () => {
    if (!config) return
    setSaving(true)
    setError(null)
    const { error: err } = await saveSignalConfig(config, projectPath || undefined)
    setSaving(false)
    if (err) {
      setError(err)
      return
    }
    setDirty(false)
  }, [config, projectPath])

  if (loading) {
    return (
      <div className="flex items-center justify-center p-8 text-muted-foreground" data-testid="signal-config-loading">
        <Loader2 className="w-4 h-4 animate-spin mr-2" />
        <span className="text-xs">Loading signal configuration…</span>
      </div>
    )
  }

  if (!config) {
    return (
      <div className="p-4 text-xs text-muted-foreground" data-testid="signal-config-empty">
        No signal configuration available.
      </div>
    )
  }

  const rules = config.signal_rules
  const globals = config.global_settings

  return (
    <div className="flex flex-col h-full" data-testid="signal-config-panel">
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2 border-b bg-muted/30">
        <div className="text-xs font-semibold text-foreground">Signal Rules</div>
        <div className="flex items-center gap-2">
          {dirty && (
            <span className="text-[10px] text-amber-600 font-medium">Unsaved</span>
          )}
          <button
            onClick={handleSave}
            disabled={!dirty || saving}
            className={cn(
              'flex items-center gap-1 px-2.5 py-1 rounded text-[11px] font-medium transition-colors',
              dirty
                ? 'bg-primary text-primary-foreground hover:bg-primary/90'
                : 'bg-muted text-muted-foreground cursor-not-allowed'
            )}
            data-testid="signal-config-save"
          >
            {saving ? <Loader2 className="w-3 h-3 animate-spin" /> : <Save className="w-3 h-3" />}
            Save
          </button>
        </div>
      </div>

      {error && (
        <div className="mx-3 mt-2 px-2 py-1.5 rounded text-[11px] bg-red-50 text-red-700 border border-red-200" data-testid="signal-config-error">
          {error}
        </div>
      )}

      {/* Signal rule cards */}
      <div className="flex-1 overflow-y-auto px-3 py-2 space-y-1.5">
        {SIGNAL_ORDER.map((signalType) => {
          const rule = rules[signalType]
          if (!rule) return null
          const meta = SIGNAL_META[signalType] || { icon: AlertTriangle, colorClass: 'text-gray-500' }
          const Icon = meta.icon
          const isOpen = expandedSignal === signalType
          const severity = rule.severity_override || 'Auto'
          const sevStyle = rule.severity_override ? getSeverityStyle(rule.severity_override) : null

          return (
            <div
              key={signalType}
              className={cn(
                'border rounded-md transition-colors',
                rule.enabled ? 'bg-card' : 'bg-muted/40 opacity-70',
              )}
              data-testid={`signal-rule-${signalType}`}
            >
              {/* Collapsed header */}
              <button
                onClick={() => setExpandedSignal(isOpen ? null : signalType)}
                className="flex items-center w-full px-3 py-2 gap-2 text-left"
                data-testid={`signal-rule-toggle-${signalType}`}
              >
                {isOpen ? (
                  <ChevronDown className="w-3.5 h-3.5 text-muted-foreground flex-shrink-0" />
                ) : (
                  <ChevronRight className="w-3.5 h-3.5 text-muted-foreground flex-shrink-0" />
                )}
                <Icon className={cn('w-4 h-4 flex-shrink-0', meta.colorClass)} />
                <span className="text-xs font-medium flex-1 truncate">
                  {humanizeSignalName(signalType)}
                </span>
                {/* Status badges */}
                <span
                  className={cn(
                    'text-[10px] px-1.5 py-0.5 rounded-full font-medium',
                    rule.enabled
                      ? 'bg-emerald-50 text-emerald-700 border border-emerald-200'
                      : 'bg-gray-100 text-gray-500 border border-gray-200',
                  )}
                >
                  {rule.enabled ? 'Active' : 'Off'}
                </span>
                {sevStyle && (
                  <span
                    className="text-[10px] px-1.5 py-0.5 rounded-full font-medium"
                    style={{ background: sevStyle.bg, color: sevStyle.text, border: `1px solid ${sevStyle.border}` }}
                  >
                    {severity}
                  </span>
                )}
              </button>

              {/* Expanded panel */}
              {isOpen && (
                <div className="px-3 pb-3 pt-1 space-y-3 border-t" data-testid={`signal-rule-detail-${signalType}`}>
                  {/* Enable toggle */}
                  <div className="flex items-center justify-between">
                    <label className="text-[11px] text-muted-foreground font-medium">Enabled</label>
                    <button
                      onClick={() => updateRule(signalType, { enabled: !rule.enabled })}
                      className={cn(
                        'relative w-8 h-4.5 rounded-full transition-colors',
                        rule.enabled ? 'bg-primary' : 'bg-gray-300',
                      )}
                      style={{ height: '18px' }}
                      data-testid={`signal-rule-enabled-${signalType}`}
                    >
                      <span
                        className={cn(
                          'absolute top-0.5 w-3.5 h-3.5 rounded-full bg-white shadow transition-transform',
                          rule.enabled ? 'translate-x-4' : 'translate-x-0.5',
                        )}
                      />
                    </button>
                  </div>

                  {/* Severity override */}
                  <div className="space-y-1">
                    <label className="text-[11px] text-muted-foreground font-medium">Severity</label>
                    <Select
                      value={rule.severity_override || '__auto__'}
                      onValueChange={(v) =>
                        updateRule(signalType, {
                          severity_override: v === '__auto__' ? null : v,
                        })
                      }
                    >
                      <SelectTrigger className="h-7 text-xs" data-testid={`signal-rule-severity-${signalType}`}>
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {SEVERITY_OPTIONS.map((opt) => (
                          <SelectItem key={opt.value} value={opt.value} className="text-xs">
                            {opt.label}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>

                  {/* Description */}
                  <div className="space-y-1">
                    <label className="text-[11px] text-muted-foreground font-medium">Description</label>
                    <textarea
                      value={rule.description || ''}
                      onChange={(e) => updateRule(signalType, { description: e.target.value })}
                      className="w-full h-14 px-2 py-1.5 text-xs border rounded-md bg-background resize-none focus:outline-none focus:ring-1 focus:ring-primary"
                      data-testid={`signal-rule-description-${signalType}`}
                    />
                  </div>

                  {/* Thresholds (read-only display) */}
                  {rule.thresholds && Object.keys(rule.thresholds).length > 0 && (
                    <div className="space-y-1">
                      <label className="text-[11px] text-muted-foreground font-medium">Thresholds</label>
                      <div className="bg-muted/40 rounded px-2 py-1.5 space-y-0.5">
                        {Object.entries(rule.thresholds).map(([key, value]) => (
                          <div key={key} className="flex items-center justify-between text-[10px]">
                            <span className="text-muted-foreground">{humanizeThresholdKey(key)}</span>
                            <span className="font-mono text-foreground">{formatThresholdValue(value)}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>
          )
        })}

        {/* Global settings section */}
        <div className="mt-4 pt-3 border-t" data-testid="signal-global-settings">
          <div className="text-xs font-semibold text-foreground mb-2">Global Settings</div>
          <div className="space-y-3">
            {/* Max signals per KPI */}
            <div className="flex items-center justify-between">
              <label className="text-[11px] text-muted-foreground font-medium">Max signals per KPI</label>
              <Select
                value={String(globals.max_signals_per_kpi)}
                onValueChange={(v) => updateGlobal('max_signals_per_kpi', parseInt(v, 10))}
              >
                <SelectTrigger className="w-16 h-7 text-xs" data-testid="signal-global-max">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {[1, 2, 3, 4, 5].map((n) => (
                    <SelectItem key={n} value={String(n)} className="text-xs">
                      {n}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            {/* Severity downgrade toggle */}
            <div className="flex items-center justify-between">
              <div className="space-y-0.5">
                <label className="text-[11px] text-muted-foreground font-medium">
                  Severity downgrade on degraded
                </label>
                <p className="text-[10px] text-muted-foreground/70">
                  Reduce severity by one level when computability is Degraded
                </p>
              </div>
              <button
                onClick={() => updateGlobal('severity_downgrade_on_degraded', !globals.severity_downgrade_on_degraded)}
                className={cn(
                  'relative w-8 rounded-full transition-colors flex-shrink-0',
                  globals.severity_downgrade_on_degraded ? 'bg-primary' : 'bg-gray-300',
                )}
                style={{ height: '18px' }}
                data-testid="signal-global-downgrade"
              >
                <span
                  className={cn(
                    'absolute top-0.5 w-3.5 h-3.5 rounded-full bg-white shadow transition-transform',
                    globals.severity_downgrade_on_degraded ? 'translate-x-4' : 'translate-x-0.5',
                  )}
                />
              </button>
            </div>

            {/* Contradiction pairs (read-only) */}
            {globals.contradiction_pairs && globals.contradiction_pairs.length > 0 && (
              <div className="space-y-1">
                <label className="text-[11px] text-muted-foreground font-medium">Contradiction Pairs</label>
                <div className="bg-muted/40 rounded px-2 py-1.5 space-y-0.5">
                  {globals.contradiction_pairs.map((pair, i) => (
                    <div key={i} className="text-[10px] text-muted-foreground">
                      {humanizeSignalName(pair[0])} <span className="text-muted-foreground/50">↔</span>{' '}
                      {humanizeSignalName(pair[1])}
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

// Helpers

function humanizeThresholdKey(key: string): string {
  const map: Record<string, string> = {
    impact_levels: 'Impact Levels',
    pattern: 'Pattern',
    delta_positive: 'Delta Positive',
    min_impact_score: 'Min Impact Score',
    drift_event: 'Drift Event',
    stability_badge: 'Stability Badge',
    impact_level: 'Impact Level',
  }
  return map[key] || key.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}

function formatThresholdValue(value: unknown): string {
  if (Array.isArray(value)) return value.join(', ')
  if (typeof value === 'boolean') return value ? 'Yes' : 'No'
  if (value === null || value === undefined) return '—'
  return String(value)
}

/**
 * DataColumnProfile — Right panel showing statistics for a selected column.
 * Includes completeness ring, type-specific metrics, and value distribution.
 */
import { X } from 'lucide-react'
import { cn } from '@/lib/utils'
import { ScrollArea } from '@/components/ui/scroll-area'
import type { ColumnProfile } from '@/lib/api'

interface Props {
  column: ColumnProfile
  onClose: () => void
}

/** SVG donut showing completeness percentage */
function CompletenessRing({ value }: { value: number }) {
  const radius = 32
  const stroke = 6
  const circumference = 2 * Math.PI * radius
  const filled = (value / 100) * circumference
  const color = value >= 95 ? '#22c55e' : value >= 70 ? '#f59e0b' : '#ef4444'

  return (
    <div className="flex flex-col items-center gap-1">
      <svg width={80} height={80} viewBox="0 0 80 80">
        <circle
          cx={40} cy={40} r={radius}
          fill="none"
          stroke="currentColor"
          className="text-muted"
          strokeWidth={stroke}
        />
        <circle
          cx={40} cy={40} r={radius}
          fill="none"
          stroke={color}
          strokeWidth={stroke}
          strokeDasharray={`${filled} ${circumference - filled}`}
          strokeDashoffset={circumference * 0.25}
          strokeLinecap="round"
          className="transition-all duration-500"
        />
        <text
          x={40} y={40}
          textAnchor="middle"
          dominantBaseline="central"
          className="text-xs font-medium fill-foreground"
        >
          {value.toFixed(1)}%
        </text>
      </svg>
      <span className="text-[10px] text-muted-foreground">Completeness</span>
    </div>
  )
}

function StatRow({ label, value }: { label: string; value: string | number | undefined | null }) {
  if (value === undefined || value === null) return null
  const display = typeof value === 'number'
    ? Number.isInteger(value) ? value.toLocaleString() : value.toLocaleString(undefined, { maximumFractionDigits: 2 })
    : String(value)
  return (
    <div className="flex justify-between items-baseline py-1 border-b border-dashed border-muted last:border-0">
      <span className="text-xs text-muted-foreground">{label}</span>
      <span className="text-xs font-medium font-mono">{display}</span>
    </div>
  )
}

function MiniBarChart({ data }: { data: { value: string; count: number }[] }) {
  const items = data.slice(0, 10)
  const maxCount = Math.max(...items.map(d => d.count), 1)

  return (
    <div className="space-y-1">
      {items.map((d, i) => (
        <div key={i} className="flex items-center gap-2">
          <span className="text-[10px] text-muted-foreground truncate w-20 text-right shrink-0" title={d.value}>
            {d.value || '(empty)'}
          </span>
          <div className="flex-1 h-3 bg-muted rounded-sm overflow-hidden">
            <div
              className="h-full bg-primary/60 rounded-sm transition-all"
              style={{ width: `${(d.count / maxCount) * 100}%` }}
            />
          </div>
          <span className="text-[10px] font-mono text-muted-foreground w-10 text-right shrink-0">
            {d.count.toLocaleString()}
          </span>
        </div>
      ))}
    </div>
  )
}

function SectionHeader({ children }: { children: React.ReactNode }) {
  return (
    <h4 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mt-4 mb-2">
      {children}
    </h4>
  )
}

export function DataColumnProfile({ column: col, onClose }: Props) {
  const dtype = (col.type || 'unknown').toLowerCase()
  const isNumeric = /int|float|double|decimal|numeric|bigint|smallint|tinyint|hugeint/.test(dtype)
  const isDate = /date|time|timestamp/.test(dtype)
  const isBool = /bool/.test(dtype)
  const isText = /varchar|text|string|char/.test(dtype)

  return (
    <div className="w-72 border-l flex flex-col bg-background" data-testid="data-column-profile">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b">
        <div className="min-w-0 flex-1">
          <h3 className="text-sm font-medium truncate" title={col.name}>{col.name}</h3>
          <span className={cn(
            'text-[10px] px-1.5 py-0.5 rounded font-mono mt-0.5 inline-block',
            isNumeric ? 'bg-blue-100 text-blue-700 dark:bg-blue-900 dark:text-blue-300'
              : isDate ? 'bg-purple-100 text-purple-700 dark:bg-purple-900 dark:text-purple-300'
              : isBool ? 'bg-amber-100 text-amber-700 dark:bg-amber-900 dark:text-amber-300'
              : isText ? 'bg-green-100 text-green-700 dark:bg-green-900 dark:text-green-300'
              : 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400'
          )}>
            {col.type}
          </span>
        </div>
        <button onClick={onClose} className="p-1 rounded hover:bg-accent shrink-0">
          <X className="h-4 w-4" />
        </button>
      </div>

      <ScrollArea className="flex-1">
        <div className="p-4 space-y-1">
          {/* Completeness ring */}
          <div className="flex justify-center mb-3">
            <CompletenessRing value={col.completeness} />
          </div>

          {/* General stats */}
          <SectionHeader>General</SectionHeader>
          <StatRow label="Distinct values" value={col.distinct_count} />
          <StatRow label="Null count" value={col.null_count} />
          <StatRow label="Completeness" value={`${col.completeness.toFixed(1)}%`} />

          {/* Numeric stats */}
          {isNumeric && (
            <>
              <SectionHeader>Statistics</SectionHeader>
              <StatRow label="Min" value={col.min as number} />
              <StatRow label="Max" value={col.max as number} />
              <StatRow label="Mean" value={col.mean} />
              <StatRow label="Median" value={col.median} />
              <StatRow label="Std Dev" value={col.stddev} />
              <StatRow label="Sum" value={col.sum} />
              <StatRow label="25th %ile" value={col.p25} />
              <StatRow label="75th %ile" value={col.p75} />
            </>
          )}

          {/* Date stats */}
          {isDate && (
            <>
              <SectionHeader>Date Range</SectionHeader>
              <StatRow label="Earliest" value={col.min as string} />
              <StatRow label="Latest" value={col.max as string} />
              <StatRow label="Range (days)" value={col.date_range_days} />
            </>
          )}

          {/* Boolean stats */}
          {isBool && (
            <>
              <SectionHeader>Distribution</SectionHeader>
              <StatRow label="True" value={col.true_count} />
              <StatRow label="False" value={col.false_count} />
            </>
          )}

          {/* Text stats */}
          {isText && (
            <>
              <SectionHeader>Length</SectionHeader>
              <StatRow label="Min length" value={col.min_length} />
              <StatRow label="Max length" value={col.max_length} />
              <StatRow label="Avg length" value={col.avg_length} />
            </>
          )}

          {/* Value distribution */}
          {col.top_values && col.top_values.length > 0 && (
            <>
              <SectionHeader>Top Values</SectionHeader>
              <MiniBarChart data={col.top_values} />
            </>
          )}
        </div>
      </ScrollArea>
    </div>
  )
}

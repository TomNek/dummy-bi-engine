/**
 * ExplanationColumn — renders explanation cells in matrix/tablix visuals.
 *
 * Phase 10.9: Explanation Column in Tablix/Matrix.
 * When a visual has ExplanationRef bindings, the server returns explanation
 * data alongside the tablix plan. This component renders that data as an
 * additional virtual column with expand/collapse tree affordance.
 */
import { useState, useCallback } from 'react'
import { cn } from '@/lib/utils'
import { ChevronDown, ChevronRight } from 'lucide-react'

// ── Types ──────────────────────────────────────────────────────────────

export interface ExplNode {
  metric: string
  actual: number | null
  base: number | null
  abs_delta: number | null
  rel_delta: number | null
  narrative: string | null
  children: ExplNode[]
  is_material?: boolean
  driver_mode?: string | null
  unexplained_delta?: number | null
  sign?: number
  higher_is_better?: boolean
}

export interface ExplanationData {
  explanations?: Array<{
    playbook: string
    edu_id?: string
    version?: string
    error?: string
    per_row?: ExplNode[]
    nodes?: ExplNode[]
  }>
  comparator_label?: string
  narrative_depth?: string
}

// ── Helpers ────────────────────────────────────────────────────────────

function isFavorable(delta: number, higherIsBetter: boolean): boolean {
  return (delta > 0 && higherIsBetter) || (delta < 0 && !higherIsBetter)
}

function deltaColor(delta: number, higherIsBetter: boolean = true): string {
  if (delta === 0) return 'text-muted-foreground'
  return isFavorable(delta, higherIsBetter) ? 'text-green-700' : 'text-red-700'
}

function formatDelta(value: number | null): string {
  if (value == null) return '—'
  const sign = value >= 0 ? '+' : ''
  return `${sign}${Number(value).toLocaleString()}`
}

// ── ExplTreeChildren (recursive sub-tree) ──────────────────────────────

function ExplTreeChildren({ nodes, depth }: { nodes: ExplNode[]; depth: number }) {
  const [expanded, setExpanded] = useState<Set<number>>(new Set())

  if (depth > 6) return null // safety limit

  return (
    <div className="ml-3 border-l border-amber-200 pl-2 space-y-0.5" data-testid="expl-tree-children">
      {nodes.map((child, idx) => {
        const hasKids = Array.isArray(child.children) && child.children.length > 0
        const isOpen = expanded.has(idx)
        const higherIsBetter = child.higher_is_better !== false
        return (
          <div key={idx} className="text-[10px]">
            <div className="flex items-start gap-1">
              {hasKids && (
                <button
                  onClick={(e) => {
                    e.stopPropagation()
                    setExpanded(prev => {
                      const next = new Set(prev)
                      if (next.has(idx)) next.delete(idx); else next.add(idx)
                      return next
                    })
                  }}
                  className="mt-0.5 text-amber-600 hover:text-amber-800 flex-shrink-0"
                  data-testid={`expl-child-toggle-${depth}-${idx}`}
                >
                  {isOpen ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
                </button>
              )}
              <div className="flex-1 min-w-0">
                <span className="font-medium text-foreground">{child.metric}</span>
                {child.abs_delta != null && (
                  <span className={cn('ml-1.5', deltaColor(child.abs_delta, higherIsBetter))}>
                    {formatDelta(child.abs_delta)}
                  </span>
                )}
                {child.rel_delta != null && (
                  <span className="ml-1 text-muted-foreground">
                    ({(child.rel_delta * 100).toFixed(1)}%)
                  </span>
                )}
              </div>
            </div>
            {isOpen && hasKids && (
              <ExplTreeChildren nodes={child.children} depth={depth + 1} />
            )}
          </div>
        )
      })}
    </div>
  )
}

// ── ExplanationColumnHeader ────────────────────────────────────────────

interface ExplanationColumnHeaderProps {
  onExpandAll?: () => void
  onCollapseAll?: () => void
  className?: string
}

export function ExplanationColumnHeader({ onExpandAll, onCollapseAll, className }: ExplanationColumnHeaderProps) {
  return (
    <th
      className={cn(
        'px-2 py-1 text-left font-medium border-b bg-amber-100 text-amber-900 whitespace-nowrap',
        className,
      )}
      data-testid="matrix-explanation-column-header"
    >
      <div className="flex items-center gap-1.5">
        <span className="text-xs">💡 Explanation</span>
        <div className="flex gap-0.5 ml-auto">
          {onExpandAll && (
            <button
              onClick={onExpandAll}
              className="px-1 py-0.5 text-[9px] rounded bg-amber-200 hover:bg-amber-300 text-amber-800 font-medium"
              title="Expand all explanations"
              data-testid="matrix-expl-expand-all"
            >
              ⊞
            </button>
          )}
          {onCollapseAll && (
            <button
              onClick={onCollapseAll}
              className="px-1 py-0.5 text-[9px] rounded bg-amber-200 hover:bg-amber-300 text-amber-800 font-medium"
              title="Collapse all explanations"
              data-testid="matrix-expl-collapse-all"
            >
              ⊟
            </button>
          )}
        </div>
      </div>
    </th>
  )
}

// ── ExplanationCell ────────────────────────────────────────────────────

interface ExplanationCellProps {
  node: ExplNode | null
  rowIndex: number
  expanded: boolean
  onToggle: (rowIndex: number) => void
}

export function ExplanationCell({ node, rowIndex, expanded, onToggle }: ExplanationCellProps) {
  if (!node) {
    return (
      <td
        className="px-2 py-1 border-b bg-amber-50/30 text-xs"
        data-testid={`matrix-expl-cell-${rowIndex}`}
      >
        <span className="text-muted-foreground">—</span>
      </td>
    )
  }

  const hasChildren = Array.isArray(node.children) && node.children.length > 0
  const higherIsBetter = node.higher_is_better !== false

  const handleToggle = useCallback((e: React.MouseEvent) => {
    e.stopPropagation()
    onToggle(rowIndex)
  }, [onToggle, rowIndex])

  return (
    <td
      className="px-2 py-1 border-b bg-amber-50/30 text-xs align-top min-w-[180px] max-w-[320px]"
      data-testid={`matrix-expl-cell-${rowIndex}`}
    >
      <div className="space-y-0.5">
        {/* Primary driver summary + delta badge */}
        <div className="flex items-start gap-1">
          {hasChildren && (
            <button
              onClick={handleToggle}
              className="mt-0.5 text-amber-600 hover:text-amber-800 flex-shrink-0"
              data-testid={`matrix-expl-toggle-${rowIndex}`}
            >
              {expanded ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
            </button>
          )}
          <div className="flex-1 min-w-0">
            <span className="font-medium text-amber-900 text-[11px]">{node.metric}</span>
            {node.abs_delta != null && (
              <span
                className={cn(
                  'ml-1.5 text-[10px] font-semibold inline-flex items-center px-1 py-0 rounded',
                  isFavorable(node.abs_delta, higherIsBetter)
                    ? 'bg-green-100 text-green-800'
                    : 'bg-red-100 text-red-800',
                )}
                data-testid={`matrix-expl-delta-badge-${rowIndex}`}
              >
                {formatDelta(node.abs_delta)}
                {node.rel_delta != null && (
                  <span className="ml-0.5 opacity-70">
                    ({(node.rel_delta * 100).toFixed(1)}%)
                  </span>
                )}
              </span>
            )}
            {/* Brief narrative */}
            {node.narrative && (
              <div
                className="text-[10px] text-amber-700 italic leading-snug mt-0.5 line-clamp-2"
                title={node.narrative}
                data-testid={`matrix-expl-narrative-${rowIndex}`}
              >
                {node.narrative}
              </div>
            )}
          </div>
        </div>

        {/* Expanded child EDU tree */}
        {expanded && hasChildren && (
          <ExplTreeChildren nodes={node.children} depth={1} />
        )}
      </div>
    </td>
  )
}

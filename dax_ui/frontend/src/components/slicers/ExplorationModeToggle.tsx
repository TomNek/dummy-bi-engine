/**
 * ExplorationModeToggle — Phase 23F
 *
 * Per-page toggle that extends 3-state rendering (selected/possible/excluded)
 * to crossfilter interactions and filter pane items — not just slicers.
 *
 * When exploration mode is ON:
 * - Filter pane shows possible/excluded annotations on all filter fields
 * - Crossfilter interactions highlight possible/impossible values
 *
 * This toggle is NOT persisted — it's a runtime-only UI state.
 */
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { useSelectionStateStore } from '@/stores/selection-state-store'
import { Eye, EyeOff } from 'lucide-react'

interface ExplorationModeToggleProps {
  pageId: string
  className?: string
}

export function ExplorationModeToggle({ pageId, className }: ExplorationModeToggleProps) {
  const explorationMode = useSelectionStateStore(s => s.explorationMode[pageId] ?? false)
  const toggleExplorationMode = useSelectionStateStore(s => s.toggleExplorationMode)

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          className={cn(
            'h-6 w-6 transition-colors duration-150',
            explorationMode && 'text-primary bg-accent',
            className
          )}
          onClick={() => toggleExplorationMode(pageId)}
          data-testid="exploration-mode-toggle"
          aria-label={explorationMode ? 'Disable exploration mode' : 'Enable exploration mode'}
          aria-pressed={explorationMode}
        >
          {explorationMode ? (
            <Eye className="h-3.5 w-3.5" />
          ) : (
            <EyeOff className="h-3.5 w-3.5" />
          )}
        </Button>
      </TooltipTrigger>
      <TooltipContent side="left">
        <p className="text-xs">
          {explorationMode
            ? 'Exploration mode ON — showing possible/excluded states across all filters'
            : 'Enable exploration mode to see possible/excluded values across filters'}
        </p>
      </TooltipContent>
    </Tooltip>
  )
}

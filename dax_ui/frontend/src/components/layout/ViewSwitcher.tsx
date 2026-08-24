import { cn } from '@/lib/utils'
import { useAppStore } from '@/stores'
import {
  LayoutDashboard,
  Table2,
  GitFork,
  FileCode2,
} from 'lucide-react'
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from '@/components/ui/tooltip'
import { HAS_TRANSFORM_STUDIO } from '@/lib/edition'

const views = [
  { id: 'report' as const, label: 'Report', icon: LayoutDashboard },
  { id: 'data' as const, label: 'Data', icon: Table2 },
  { id: 'model' as const, label: 'Model', icon: GitFork },
  { id: 'transform' as const, label: 'Transform', icon: FileCode2 },
]

export function ViewSwitcher() {
  const viewMode = useAppStore(s => s.viewMode)
  const setViewMode = useAppStore(s => s.setViewMode)

  return (
    <div
      className="flex flex-col items-center gap-1 py-2 px-1 border-r bg-muted/30"
      data-testid="view-switcher"
    >
      {views.filter(v => v.id !== 'transform' || HAS_TRANSFORM_STUDIO).map(v => (
        <Tooltip key={v.id}>
          <TooltipTrigger asChild>
            <button
              onClick={() => setViewMode(v.id)}
              className={cn(
                'flex items-center justify-center w-8 h-8 rounded-md transition-colors',
                viewMode === v.id
                  ? 'bg-primary text-primary-foreground'
                  : 'text-muted-foreground hover:bg-accent hover:text-accent-foreground'
              )}
              data-testid={`view-switch-${v.id}`}
              aria-label={`Switch to ${v.label} view`}
              title={`${v.label} view`}
            >
              <v.icon className="h-4 w-4" />
            </button>
          </TooltipTrigger>
          <TooltipContent side="right">{v.label}</TooltipContent>
        </Tooltip>
      ))}
    </div>
  )
}

import { Layers, X, ChevronLeft, ChevronRight } from 'lucide-react'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { useAppStore } from '@/stores'
import { usePanelResize } from '@/hooks'
import { SelectionPane } from '@/components/bookmarks'

export function SelectionSidebar() {
  const open = useAppStore(s => s.selectionPaneOpen)
  const toggle = useAppStore(s => s.toggleSelectionPane)
  const setOpen = useAppStore(s => s.setSelectionPaneOpen)
  const { width: selectionWidth, handleProps: selectionResizeProps } = usePanelResize({ defaultWidth: 240, minWidth: 180, maxWidth: 500, direction: 'left' })

  return (
    <div
      className="flex shrink-0 border-l bg-sidebar-background"
      data-testid="selection-sidebar"
    >
      {/* Collapsed strip — always visible */}
      {!open && (
        <button
          className={cn(
            'flex flex-col items-center justify-start pt-3 gap-2 w-8',
            'hover:bg-accent/50 transition-colors cursor-pointer',
            'border-l border-transparent',
          )}
          onClick={() => setOpen(true)}
          title="Open Selection Pane"
          data-testid="selection-sidebar-open"
        >
          <Layers className="h-4 w-4 text-muted-foreground" />
          <span className="text-[9px] text-muted-foreground [writing-mode:vertical-lr] tracking-widest">
            SELECTION
          </span>
        </button>
      )}

      {/* Expanded panel */}
      {open && (
        <div
          className="relative flex flex-col h-full"
          style={{ width: selectionWidth }}
        >
          <div {...selectionResizeProps} data-testid="selection-resize-handle" />
          {/* Title bar */}
          <div className="flex items-center justify-between px-2 py-1.5 border-b shrink-0">
            <div className="flex items-center gap-1.5">
              <Layers className="h-3.5 w-3.5 text-muted-foreground" />
              <span className="text-xs font-semibold tracking-wide">Selection</span>
            </div>
            <Button
              variant="ghost"
              size="sm"
              className="h-6 w-6 p-0"
              onClick={() => setOpen(false)}
              title="Close Selection Pane"
              data-testid="selection-sidebar-close"
            >
              <X className="h-3.5 w-3.5" />
            </Button>
          </div>

          {/* Content */}
          <SelectionPane className="flex-1 min-h-0" />
        </div>
      )}
    </div>
  )
}

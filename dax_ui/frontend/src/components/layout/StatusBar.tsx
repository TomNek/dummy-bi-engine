import { useCallback, useEffect } from 'react'
import { ZoomIn, ZoomOut } from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from '@/components/ui/tooltip'
import { useAppStore } from '@/stores'

const ZOOM_STEP = 10
const ZOOM_MIN = 50
const ZOOM_MAX = 200

export function StatusBar() {
  const zoomLevel = useAppStore((s) => s.canvasZoom)
  const setCanvasZoom = useAppStore((s) => s.setCanvasZoom)

  // Remove any previously set document-level zoom on mount
  useEffect(() => {
    document.documentElement.style.zoom = ''
  }, [])

  const zoomIn = useCallback(() => {
    setCanvasZoom(Math.min(ZOOM_MAX, zoomLevel + ZOOM_STEP))
  }, [zoomLevel, setCanvasZoom])
  const zoomOut = useCallback(() => {
    setCanvasZoom(Math.max(ZOOM_MIN, zoomLevel - ZOOM_STEP))
  }, [zoomLevel, setCanvasZoom])
  const zoomReset = useCallback(() => {
    setCanvasZoom(100)
  }, [setCanvasZoom])

  // Ctrl+= / Ctrl+- / Ctrl+0 keyboard shortcuts
  useEffect(() => {
    const handleZoomKeys = (e: KeyboardEvent) => {
      if (e.ctrlKey && (e.key === '=' || e.key === '+')) {
        e.preventDefault()
        zoomIn()
      } else if (e.ctrlKey && e.key === '-') {
        e.preventDefault()
        zoomOut()
      } else if (e.ctrlKey && e.key === '0') {
        e.preventDefault()
        zoomReset()
      }
    }
    document.addEventListener('keydown', handleZoomKeys)
    return () => document.removeEventListener('keydown', handleZoomKeys)
  }, [zoomIn, zoomOut, zoomReset])

  return (
    <div
      className="flex items-center justify-end h-6 px-2 border-t bg-muted/40 text-xs shrink-0 select-none"
      data-testid="status-bar"
    >
      {/* Zoom controls — bottom right */}
      <div className="flex items-center gap-0.5" data-testid="zoom-controls">
        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              variant="ghost"
              size="icon"
              className="h-5 w-5"
              onClick={zoomOut}
              disabled={zoomLevel <= ZOOM_MIN}
              data-testid="zoom-out"
              aria-label="Zoom out (Ctrl+-)"
            >
              <ZoomOut className="h-3 w-3" />
            </Button>
          </TooltipTrigger>
          <TooltipContent side="top">Zoom out (Ctrl+-)</TooltipContent>
        </Tooltip>

        <Tooltip>
          <TooltipTrigger asChild>
            <button
              className="text-[11px] text-muted-foreground hover:text-foreground w-9 text-center tabular-nums cursor-pointer"
              onClick={zoomReset}
              data-testid="zoom-level"
              aria-label="Reset zoom (Ctrl+0)"
            >
              {zoomLevel}%
            </button>
          </TooltipTrigger>
          <TooltipContent side="top">Reset to 100% (Ctrl+0)</TooltipContent>
        </Tooltip>

        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              variant="ghost"
              size="icon"
              className="h-5 w-5"
              onClick={zoomIn}
              disabled={zoomLevel >= ZOOM_MAX}
              data-testid="zoom-in"
              aria-label="Zoom in (Ctrl+=)"
            >
              <ZoomIn className="h-3 w-3" />
            </Button>
          </TooltipTrigger>
          <TooltipContent side="top">Zoom in (Ctrl+=)</TooltipContent>
        </Tooltip>
      </div>
    </div>
  )
}

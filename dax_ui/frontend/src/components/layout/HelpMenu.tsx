import { useState, useEffect } from 'react'
import {
  HelpCircle,
  BookOpen,
  Keyboard,
  Info,
  RefreshCw,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { useMenuBar } from '@/components/layout/MenuBarContext'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
  DropdownMenuSeparator,
} from '@/components/ui/dropdown-menu'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { getFingerprint } from '@/lib/api'
import { requestUpdateCheck } from '@/lib/update-events'
import { IS_OPEN_CORE } from '@/lib/edition'
import { PRODUCT_NAME } from '@/lib/product'

export function HelpMenu() {
  const menuBar = useMenuBar('help')
  const [aboutOpen, setAboutOpen] = useState(false)
  const [detailsOpen, setDetailsOpen] = useState(false)
  const [buildStamp, setBuildStamp] = useState<{
    sha: string
    serverFile: string
    python: string
  } | null>(null)

  // Fetch build stamp on mount
  useEffect(() => {
    getFingerprint().then((res) => {
      if (res.data) {
        const sha = res.data.git_head ? res.data.git_head.slice(0, 8) : '?'
        const serverFile = res.data.server_file
          ? res.data.server_file.split(/[\\/]/).pop() ?? '?'
          : '?'
        const python = res.data.python
          ? res.data.python.split(/[\\/]/).pop() ?? '?'
          : '?'
        setBuildStamp({ sha, serverFile, python })
      }
    }).catch(() => { /* ignore fingerprint errors */ })
  }, [])

  return (
    <>
      <DropdownMenu modal={false} onOpenChange={menuBar?.onOpenChange}>
        <DropdownMenuTrigger asChild>
          <Button
            ref={menuBar?.triggerRef}
            variant="ghost"
            size="sm"
            data-testid="help-menu-trigger"
            aria-label="Help menu"
            onMouseEnter={menuBar?.onTriggerMouseEnter}
          >
            <HelpCircle className="h-4 w-4 mr-1" />
            <span>Help</span>
          </Button>
        </DropdownMenuTrigger>

        <DropdownMenuContent align="start" className="w-56" data-testid="help-menu">
          <DropdownMenuItem
            disabled
            data-testid="help-menu-docs"
          >
            <BookOpen className="h-4 w-4 mr-2" />
            Documentation
            <span className="ml-auto text-xs text-muted-foreground">Coming soon</span>
          </DropdownMenuItem>

          <DropdownMenuItem
            disabled
            data-testid="help-menu-shortcuts"
          >
            <Keyboard className="h-4 w-4 mr-2" />
            Keyboard Shortcuts
            <span className="ml-auto text-xs text-muted-foreground">Coming soon</span>
          </DropdownMenuItem>

          <DropdownMenuSeparator />

          {IS_OPEN_CORE && <>
          <DropdownMenuItem onClick={requestUpdateCheck} data-testid="help-menu-check-updates">
            <RefreshCw className="h-4 w-4 mr-2" />
            Check for Updates
          </DropdownMenuItem>
          <DropdownMenuSeparator />
          </>}

          <DropdownMenuItem
            onClick={() => setAboutOpen(true)}
            data-testid="help-menu-about"
          >
            <Info className="h-4 w-4 mr-2" />
            About
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>

      {/* About dialog */}
      <Dialog open={aboutOpen} onOpenChange={setAboutOpen}>
        <DialogContent className="max-w-sm" data-testid="about-dialog">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <img src="/app-icon.png" alt="" className="h-6 w-6" />
              {PRODUCT_NAME}
            </DialogTitle>
            <DialogDescription className="sr-only">About {PRODUCT_NAME}</DialogDescription>
          </DialogHeader>
          <div className="space-y-2 text-sm text-muted-foreground">
            <div className="flex justify-between">
              <span>Version:</span>
              <span className="font-mono">
                {buildStamp ? (buildStamp.sha !== '?' ? buildStamp.sha.slice(0, 7) : 'dev') : 'dev'}
              </span>
            </div>
            {buildStamp && (
              <>
                <Button
                  variant="ghost"
                  size="sm"
                  className="w-full justify-start px-0 text-xs text-muted-foreground"
                  onClick={() => setDetailsOpen((v) => !v)}
                >
                  {detailsOpen ? 'Hide details' : 'Show details'}
                </Button>
                {detailsOpen && (
                  <div className="space-y-1 pl-1">
                    <div className="flex justify-between">
                      <span>Build:</span>
                      <span className="font-mono">{buildStamp.sha}</span>
                    </div>
                    <div className="flex justify-between">
                      <span>Server:</span>
                      <span className="font-mono">{buildStamp.serverFile}</span>
                    </div>
                    <div className="flex justify-between">
                      <span>Python:</span>
                      <span className="font-mono">{buildStamp.python}</span>
                    </div>
                  </div>
                )}
              </>
            )}
          </div>
        </DialogContent>
      </Dialog>
    </>
  )
}

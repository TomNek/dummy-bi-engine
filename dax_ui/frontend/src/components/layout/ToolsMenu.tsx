import { useState, useCallback } from 'react'
import {
  Download,
  RefreshCw,
  Loader2,
  Bell,
  Wrench,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
  DropdownMenuSeparator,
} from '@/components/ui/dropdown-menu'
import { useAppStore, useReportStore } from '@/stores'
import { useMenuBar } from '@/components/layout/MenuBarContext'
import { useRuntimeState } from '@/hooks'
import { exportPage } from '@/lib/api'
import { toast } from '@/components/ui/toast'
import { HAS_SUBSCRIPTIONS } from '@/lib/edition'

export function ToolsMenu() {
  const menuBar = useMenuBar('tools')
  const projectPath = useAppStore(s => s.projectPath)
  const currentRole = useAppStore(s => s.currentRole)
  const currentPageId = useReportStore(s => s.currentPageId)
  const { reload, reloading } = useRuntimeState()
  const [exporting, setExporting] = useState(false)
  const [subscriptionOpen, setSubscriptionOpen] = useState(false)

  // Export current page handler
  const handleExportPage = useCallback(async () => {
    if (!currentPageId) return
    setExporting(true)
    try {
      await exportPage(currentPageId, projectPath ?? undefined, currentRole ?? undefined)
      toast('Page exported', { variant: 'success' })
    } catch (err) {
      console.error('Export page failed:', err)
      toast('Page export failed', { variant: 'error' })
    } finally {
      setExporting(false)
    }
  }, [currentPageId, projectPath, currentRole])

  return (
    <>
      <DropdownMenu modal={false} onOpenChange={menuBar?.onOpenChange}>
        <DropdownMenuTrigger asChild>
          <Button
            ref={menuBar?.triggerRef}
            variant="ghost"
            size="sm"
            data-testid="tools-menu-trigger"
            aria-label="Tools menu"
            onMouseEnter={menuBar?.onTriggerMouseEnter}
          >
            <Wrench className="h-4 w-4 mr-1" />
            <span>Tools</span>
          </Button>
        </DropdownMenuTrigger>

        <DropdownMenuContent align="start" className="w-56" data-testid="tools-menu">
          {/* Export Page */}
          <DropdownMenuItem
            onClick={handleExportPage}
            disabled={!currentPageId || exporting}
            data-testid="tools-menu-export-page"
          >
            {exporting ? (
              <Loader2 className="h-4 w-4 mr-2 animate-spin" />
            ) : (
              <Download className="h-4 w-4 mr-2" />
            )}
            Export Page to Excel
          </DropdownMenuItem>

          {/* Reload Project */}
          <DropdownMenuItem
            onClick={reload}
            disabled={reloading}
            data-testid="tools-menu-reload"
          >
            {reloading ? (
              <Loader2 className="h-4 w-4 mr-2 animate-spin" />
            ) : (
              <RefreshCw className="h-4 w-4 mr-2" />
            )}
            Reload Project
          </DropdownMenuItem>

          {HAS_SUBSCRIPTIONS && <>
          <DropdownMenuSeparator />

          {/* Subscriptions */}
          <DropdownMenuItem
            onClick={() => setSubscriptionOpen(true)}
            data-testid="tools-menu-subscriptions"
          >
            <Bell className="h-4 w-4 mr-2" />
            Subscriptions…
          </DropdownMenuItem>
          </>}
        </DropdownMenuContent>
      </DropdownMenu>

      {/* Subscription Dialog (standalone, triggered from menu item) */}
      {HAS_SUBSCRIPTIONS && subscriptionOpen && (
        <SubscriptionDialogStandalone
          open={subscriptionOpen}
          onOpenChange={setSubscriptionOpen}
        />
      )}
    </>
  )
}

// ─── Standalone Subscription Dialog ──────────────────────────────────
// The existing SubscriptionDialog is a self-contained button+dialog.
// We need a variant that accepts open/onOpenChange from the menu.
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { SubscriptionList } from '@/components/subscriptions/SubscriptionList'

function SubscriptionDialogStandalone({
  open,
  onOpenChange,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl max-h-[85vh] flex flex-col p-0" data-testid="subscription-dialog">
        <DialogHeader className="px-4 pt-4 pb-0">
          <DialogTitle className="text-sm font-semibold">Subscription Management</DialogTitle>
          <DialogDescription className="sr-only">Manage report subscriptions and notification settings</DialogDescription>
        </DialogHeader>
        <div className="flex-1 min-h-0 overflow-hidden">
          <SubscriptionList className="h-full" />
        </div>
      </DialogContent>
    </Dialog>
  )
}

import { useCallback, useEffect, useRef, useState } from 'react'
import { Download, Loader2, RefreshCw } from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { toast } from '@/components/ui/toast'
import { CHECK_FOR_UPDATES_EVENT } from '@/lib/update-events'

const LAST_CHECK_KEY = 'smw:last-update-check'
const AUTO_CHECK_INTERVAL_MS = 24 * 60 * 60 * 1000
const AUTO_CHECK_DELAY_MS = 5000
type AvailableUpdate = Awaited<ReturnType<(typeof import('@tauri-apps/plugin-updater'))['check']>>

function isTauriRuntime(): boolean {
  return typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window
}

export function UpdateManager() {
  const updateRef = useRef<AvailableUpdate>(null)
  const checkingRef = useRef(false)
  const [open, setOpen] = useState(false)
  const [version, setVersion] = useState('')
  const [notes, setNotes] = useState<string | null>(null)
  const [installing, setInstalling] = useState(false)
  const [progress, setProgress] = useState<number | null>(null)

  const checkForUpdate = useCallback(async (manual: boolean) => {
    if (!isTauriRuntime()) {
      if (manual) toast('Update checks are available in the installed desktop app.')
      return
    }
    if (checkingRef.current || installing) return
    checkingRef.current = true
    try {
      if (manual) toast('Checking for updates…')
      const { check } = await import('@tauri-apps/plugin-updater')
      const update = await check()
      localStorage.setItem(LAST_CHECK_KEY, String(Date.now()))
      if (!update) {
        if (manual) toast('You already have the latest version.', { variant: 'success' })
        return
      }
      updateRef.current = update
      setVersion(update.version)
      setNotes(update.body ?? null)
      setProgress(null)
      setOpen(true)
    } catch (error) {
      if (manual) {
        const message = error instanceof Error ? error.message : String(error)
        toast(`Update check failed: ${message}`, { variant: 'error' })
      }
    } finally {
      checkingRef.current = false
    }
  }, [installing])

  useEffect(() => {
    const onManualCheck = () => void checkForUpdate(true)
    window.addEventListener(CHECK_FOR_UPDATES_EVENT, onManualCheck)
    const lastCheck = Number(localStorage.getItem(LAST_CHECK_KEY) || 0)
    const timer = window.setTimeout(() => {
      if (Date.now() - lastCheck >= AUTO_CHECK_INTERVAL_MS) void checkForUpdate(false)
    }, AUTO_CHECK_DELAY_MS)
    return () => {
      window.clearTimeout(timer)
      window.removeEventListener(CHECK_FOR_UPDATES_EVENT, onManualCheck)
    }
  }, [checkForUpdate])

  const dismiss = useCallback(async () => {
    if (installing) return
    setOpen(false)
    await updateRef.current?.close()
    updateRef.current = null
  }, [installing])

  const install = useCallback(async () => {
    const update = updateRef.current
    if (!update) return
    setInstalling(true)
    setProgress(0)
    let downloaded = 0
    let total = 0
    try {
      await update.downloadAndInstall((event) => {
        if (event.event === 'Started') total = event.data.contentLength ?? 0
        else if (event.event === 'Progress') {
          downloaded += event.data.chunkLength
          setProgress(total > 0 ? Math.min(100, Math.round((downloaded / total) * 100)) : null)
        } else if (event.event === 'Finished') setProgress(100)
      })
      const { relaunch } = await import('@tauri-apps/plugin-process')
      await relaunch()
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error)
      toast(`Update installation failed: ${message}`, { variant: 'error' })
      setInstalling(false)
    }
  }, [])

  return (
    <Dialog open={open} onOpenChange={(next) => { if (!next) void dismiss() }}>
      <DialogContent className="max-w-md" data-testid="update-available-dialog">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            {installing ? <Loader2 className="h-5 w-5 animate-spin" /> : <RefreshCw className="h-5 w-5" />}
            Update available
          </DialogTitle>
          <DialogDescription>
            Version {version} is ready to install. Your project files remain on this computer.
          </DialogDescription>
        </DialogHeader>
        {notes && <div className="max-h-40 overflow-auto whitespace-pre-wrap rounded-md bg-muted p-3 text-sm">{notes}</div>}
        {installing && (
          <div className="space-y-2" data-testid="update-progress">
            <div className="h-2 overflow-hidden rounded-full bg-muted">
              <div className="h-full bg-primary transition-all" style={{ width: `${progress ?? 15}%` }} />
            </div>
            <p className="text-xs text-muted-foreground">
              {progress === null ? 'Downloading update…' : `Downloading update… ${progress}%`}
            </p>
          </div>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={() => void dismiss()} disabled={installing} data-testid="update-later">Later</Button>
          <Button onClick={() => void install()} disabled={installing} data-testid="update-install">
            {installing ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Download className="mr-2 h-4 w-4" />}
            {installing ? 'Installing…' : 'Update now'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

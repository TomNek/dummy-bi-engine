/**
 * ThemeImportWizard — Import a Power BI theme from a PBIR .Report directory.
 *
 * Standalone dialog accessible from File → Import Power BI Theme.
 * Extracts PBI theme colors, fonts, and semantic colors and previews
 * them before applying to the current project's reporting theme.
 */
import { useCallback, useState } from 'react'
import {
  Loader2,
  Palette,
  Check,
  AlertTriangle,
  Type,
  Paintbrush,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { toast } from '@/components/ui/toast'
import {
  extractPbiTheme,
  type PbiThemeResult,
} from '@/lib/api'
import { useThemeStore } from '@/stores/theme-store'
import { saveCustomPreset, loadCustomPresets } from '@/lib/theme-defaults'

interface ThemeImportWizardProps {
  open: boolean
  onOpenChange: (open: boolean) => void
}

type WizardStep = 'source' | 'preview' | 'done'

export function ThemeImportWizard({
  open,
  onOpenChange,
}: ThemeImportWizardProps) {
  const [step, setStep] = useState<WizardStep>('source')
  const [reportDir, setReportDir] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [theme, setTheme] = useState<PbiThemeResult | null>(null)
  const setReportingTheme = useThemeStore((s) => s.setReportingTheme)

  const handleOpenChange = useCallback(
    (open: boolean) => {
      if (!open) {
        setStep('source')
        setReportDir('')
        setLoading(false)
        setError(null)
        setTheme(null)
      }
      onOpenChange(open)
    },
    [onOpenChange],
  )

  // Step 1: Extract theme for preview
  const handleExtract = useCallback(async () => {
    const trimmed = reportDir.trim()
    if (!trimmed) {
      setError('Please enter the path to the .Report directory.')
      return
    }
    setLoading(true)
    setError(null)
    try {
      const res = await extractPbiTheme(trimmed, false)
      if (res.error || !res.data) {
        setError(res.error || 'Failed to extract theme')
        return
      }
      setTheme(res.data)
      setStep('preview')
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setLoading(false)
    }
  }, [reportDir])

  // Step 2: Apply theme and save as a custom preset
  const handleApply = useCallback(async () => {
    if (!theme) return
    setLoading(true)
    setError(null)
    try {
      // Apply to server (save to disk)
      const res = await extractPbiTheme(reportDir.trim(), true)
      if (res.error || !res.data) {
        setError(res.error || 'Failed to apply theme')
        return
      }
      // Build clean theme (strip _pbi_meta)
      const cleanTheme = { ...res.data }
      delete (cleanTheme as Record<string, unknown>)._pbi_meta

      // Update the in-memory theme store
      setReportingTheme(cleanTheme as never)

      // Save as a custom preset so it appears in the preset dropdown
      const presetName = cleanTheme.name || theme.name || 'PBI Import'
      saveCustomPreset(presetName, cleanTheme as never)
      // Reload presets in the store so the dropdown picks it up
      useThemeStore.getState().reloadCustomPresets()

      setStep('done')
      toast(`Theme imported: "${presetName}" applied and saved as preset`, { variant: 'success' })
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setLoading(false)
    }
  }, [theme, reportDir, setReportingTheme])

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent
        className="sm:max-w-lg"
        data-testid="theme-import-wizard"
      >
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Palette className="h-5 w-5" />
            Import Power BI Theme
          </DialogTitle>
          <DialogDescription>
            {step === 'source' && 'Extract and apply a Power BI theme from a PBIR .Report directory.'}
            {step === 'preview' && 'Preview the extracted theme before applying.'}
            {step === 'done' && 'Theme imported successfully.'}
          </DialogDescription>
        </DialogHeader>

        {/* ─── Step: Source ─── */}
        {step === 'source' && (
          <div className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="theme-report-dir">
                PBIR .Report Directory
              </Label>
              <Input
                id="theme-report-dir"
                data-testid="theme-report-dir-input"
                placeholder="C:\...\Model.Report"
                value={reportDir}
                onChange={(e) => setReportDir(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && handleExtract()}
              />
              <p className="text-xs text-muted-foreground">
                Same path used for report transfer. The theme will be extracted from the report&apos;s BaseThemes folder.
              </p>
            </div>

            {error && (
              <div className="flex items-start gap-2 text-sm text-destructive bg-destructive/10 p-2 rounded">
                <AlertTriangle className="h-4 w-4 mt-0.5 shrink-0" />
                <span>{error}</span>
              </div>
            )}
          </div>
        )}

        {/* ─── Step: Preview ─── */}
        {step === 'preview' && theme && (
          <div className="space-y-4">
            {/* Theme name */}
            <div className="text-sm font-medium">{theme.name}</div>

            {/* Data Colors */}
            <div className="space-y-1.5">
              <div className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
                <Paintbrush className="h-3.5 w-3.5" />
                Data Colors ({theme.dataColors.length})
              </div>
              <div className="flex flex-wrap gap-1.5">
                {theme.dataColors.map((color, i) => (
                  <div
                    key={i}
                    className="flex items-center gap-1 group"
                    title={color}
                  >
                    <div
                      className="w-7 h-7 rounded border border-border shadow-sm"
                      style={{ backgroundColor: color }}
                    />
                    <span className="text-[10px] text-muted-foreground opacity-0 group-hover:opacity-100 transition-opacity">
                      {color}
                    </span>
                  </div>
                ))}
              </div>
            </div>

            {/* Font info */}
            <div className="space-y-1">
              <div className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
                <Type className="h-3.5 w-3.5" />
                Typography
              </div>
              <div className="text-sm grid grid-cols-2 gap-x-4 gap-y-1">
                <span className="text-muted-foreground">Font:</span>
                <span>{String(theme.font?.family || 'Default')}</span>
                <span className="text-muted-foreground">Body size:</span>
                <span>{String(theme.font?.sizeBody || 11)}px</span>
                <span className="text-muted-foreground">Title size:</span>
                <span>{String(theme.font?.sizeTitle || 14)}px</span>
              </div>
            </div>

            {/* Semantic colors */}
            {theme._pbi_meta && (
              <div className="space-y-1">
                <div className="text-xs font-medium text-muted-foreground">
                  Semantic Colors
                </div>
                <div className="flex flex-wrap gap-2">
                  {([
                    ['Foreground', theme._pbi_meta.foreground],
                    ['Background', theme._pbi_meta.background],
                    ['Accent', theme._pbi_meta.tableAccent],
                    ['Good', theme._pbi_meta.good],
                    ['Bad', theme._pbi_meta.bad],
                    ['Neutral', theme._pbi_meta.neutral],
                  ] as [string, string][])
                    .filter(([, c]) => c)
                    .map(([label, color]) => (
                      <div key={label} className="flex items-center gap-1" title={`${label}: ${color}`}>
                        <div
                          className="w-4 h-4 rounded-sm border border-border"
                          style={{ backgroundColor: color }}
                        />
                        <span className="text-xs text-muted-foreground">{label}</span>
                      </div>
                    ))}
                </div>
              </div>
            )}

            {error && (
              <div className="flex items-start gap-2 text-sm text-destructive bg-destructive/10 p-2 rounded">
                <AlertTriangle className="h-4 w-4 mt-0.5 shrink-0" />
                <span>{error}</span>
              </div>
            )}
          </div>
        )}

        {/* ─── Step: Done ─── */}
        {step === 'done' && (
          <div className="flex flex-col items-center gap-3 py-4">
            <div className="w-12 h-12 rounded-full bg-green-100 dark:bg-green-900/30 flex items-center justify-center">
              <Check className="h-6 w-6 text-green-600 dark:text-green-400" />
            </div>
            <p className="text-sm text-center">
              Theme <strong>{theme?.name}</strong> has been applied and saved as a custom preset.
            </p>
            <p className="text-xs text-muted-foreground text-center">
              The theme is now active. You can switch presets or customize further in the Theme Editor.
            </p>
          </div>
        )}

        <DialogFooter>
          {step === 'source' && (
            <Button
              onClick={handleExtract}
              disabled={loading || !reportDir.trim()}
              data-testid="theme-extract-btn"
            >
              {loading && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}
              Extract Theme
            </Button>
          )}
          {step === 'preview' && (
            <div className="flex gap-2 w-full justify-end">
              <Button
                variant="outline"
                onClick={() => { setStep('source'); setTheme(null); setError(null) }}
              >
                Back
              </Button>
              <Button
                onClick={handleApply}
                disabled={loading}
                data-testid="theme-apply-btn"
              >
                {loading && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}
                Apply Theme
              </Button>
            </div>
          )}
          {step === 'done' && (
            <Button onClick={() => handleOpenChange(false)}>
              Close
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

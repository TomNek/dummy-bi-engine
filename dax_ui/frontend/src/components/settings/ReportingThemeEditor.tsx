/**
 * ReportingThemeEditor — Full-featured theme editor dialog
 * 
 * Covers: data colors, visual card layout specs, font settings,
 * chart defaults, canvas background, default visual dimensions.
 * 
 * Power BI–inspired theming: changes apply immediately in-memory
 * but only persist to disk on Save (save-only persistence).
 */
import { useState, useCallback, useRef } from 'react'
import { Palette, Plus, Trash2, RotateCcw, Save, Download, Upload, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Separator } from '@/components/ui/separator'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { ScrollArea } from '@/components/ui/scroll-area'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '@/components/ui/dialog'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { ChevronDown, ChevronRight } from 'lucide-react'
import { useThemeStore } from '@/stores'
import { PRESET_THEMES, validateThemeJson, mergeTheme, DEFAULT_REPORTING_THEME } from '@/lib/theme-defaults'
import type {
  ReportingTheme,
  ReportingThemeVisualCard,
  ReportingThemeFont,
  ReportingThemeChart,
} from '@/lib/theme-defaults'

// ─── Reusable Controls ──────────────────────────────────────

function ColorInput({
  label,
  value,
  onChange,
  testId,
}: {
  label: string
  value: string
  onChange: (v: string) => void
  testId: string
}) {
  return (
    <div className="space-y-1">
      <Label className="text-xs">{label}</Label>
      <div className="flex items-center gap-2">
        <input
          type="color"
          value={value || '#000000'}
          onChange={(e) => onChange(e.target.value)}
          className="h-7 w-10 cursor-pointer rounded border border-input bg-transparent"
          data-testid={testId}
        />
        <Input
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder="Default"
          className="h-7 text-xs flex-1"
          data-testid={`${testId}-text`}
        />
        {value && (
          <Button
            variant="ghost"
            size="sm"
            className="h-7 px-2 text-xs"
            onClick={() => onChange('')}
          >
            Clear
          </Button>
        )}
      </div>
    </div>
  )
}

function SliderInput({
  label,
  value,
  min,
  max,
  step,
  unit,
  onChange,
  testId,
}: {
  label: string
  value: number
  min: number
  max: number
  step?: number
  unit?: string
  onChange: (v: number) => void
  testId: string
}) {
  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between">
        <Label className="text-xs">{label}</Label>
        <span className="text-xs text-muted-foreground tabular-nums" data-testid={`${testId}-value`}>
          {value}{unit ?? 'px'}
        </span>
      </div>
      <Input
        type="range"
        value={value}
        min={min}
        max={max}
        step={step ?? 1}
        onChange={(e) => onChange(Number(e.target.value))}
        className="h-5 w-full cursor-pointer"
        data-testid={testId}
      />
    </div>
  )
}

function Section({
  title,
  defaultOpen,
  testId,
  children,
}: {
  title: string
  defaultOpen?: boolean
  testId: string
  children: React.ReactNode
}) {
  const [open, setOpen] = useState(defaultOpen ?? false)
  return (
    <Collapsible open={open} onOpenChange={setOpen}>
      <CollapsibleTrigger asChild>
        <Button
          variant="ghost"
          className="w-full justify-between px-0 h-8 font-medium hover:bg-transparent"
          data-testid={testId}
        >
          <div className="flex items-center gap-2">
            {open ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
            <span className="text-sm">{title}</span>
          </div>
        </Button>
      </CollapsibleTrigger>
      <CollapsibleContent>
        <div className="space-y-3 py-2 pl-4">{children}</div>
      </CollapsibleContent>
    </Collapsible>
  )
}

// ─── Tab: Data Colors ───────────────────────────────────────

function DataColorsTab() {
  const reportingTheme = useThemeStore(s => s.reportingTheme)
  const setDataColor = useThemeStore(s => s.setDataColor)
  const addDataColor = useThemeStore(s => s.addDataColor)
  const removeDataColor = useThemeStore(s => s.removeDataColor)
  const colors = reportingTheme.dataColors

  return (
    <div className="space-y-4" data-testid="theme-tab-colors">
      <p className="text-xs text-muted-foreground">
        Data colors are applied to chart series in order. Drag to reorder or click to change.
      </p>
      <div className="grid grid-cols-2 gap-3">
        {colors.map((color, i) => (
          <div key={i} className="flex items-center gap-2">
            <input
              type="color"
              value={color}
              onChange={(e) => setDataColor(i, e.target.value)}
              className="h-8 w-10 cursor-pointer rounded border border-input bg-transparent"
              data-testid={`theme-data-color-${i}`}
            />
            <Input
              value={color}
              onChange={(e) => setDataColor(i, e.target.value)}
              className="h-7 text-xs flex-1 font-mono"
              data-testid={`theme-data-color-${i}-text`}
            />
            {colors.length > 2 && (
              <Button
                variant="ghost"
                size="icon"
                className="h-7 w-7 text-destructive hover:text-destructive"
                onClick={() => removeDataColor(i)}
                data-testid={`theme-remove-color-${i}`}
              >
                <Trash2 className="h-3 w-3" />
              </Button>
            )}
          </div>
        ))}
      </div>
      {colors.length < 12 && (
        <Button
          variant="outline"
          size="sm"
          onClick={addDataColor}
          className="w-full"
          data-testid="theme-add-color"
        >
          <Plus className="h-3 w-3 mr-1" />
          Add Color
        </Button>
      )}

      <Separator />

      {/* Semantic / Conditional Formatting Colors */}
      <SemanticColorsSection />
    </div>
  )
}

// ─── Section: Semantic Colors ───────────────────────────────

function SemanticColorsSection() {
  const semantic = useThemeStore(s => s.reportingTheme.semantic)
  const updateReportingTheme = useThemeStore(s => s.updateReportingTheme)

  const updateSemantic = useCallback(
    (key: string, value: string) => {
      const current = semantic ?? { foreground: '', tableAccent: '', good: '', bad: '', neutral: '', hyperlink: '' }
      updateReportingTheme({
        semantic: { ...current, [key]: value },
      })
    },
    [semantic, updateReportingTheme]
  )

  return (
    <Section title="Semantic / Conditional Colors" defaultOpen={false} testId="theme-semantic-section">
      <p className="text-xs text-muted-foreground mb-2">
        Semantic colors from Power BI themes for conditional formatting and accents.
      </p>
      <ColorInput
        label="Foreground"
        value={semantic?.foreground ?? ''}
        onChange={(v) => updateSemantic('foreground', v)}
        testId="theme-semantic-foreground"
      />
      <ColorInput
        label="Table Accent"
        value={semantic?.tableAccent ?? ''}
        onChange={(v) => updateSemantic('tableAccent', v)}
        testId="theme-semantic-table-accent"
      />
      <ColorInput
        label="Good (Positive)"
        value={semantic?.good ?? ''}
        onChange={(v) => updateSemantic('good', v)}
        testId="theme-semantic-good"
      />
      <ColorInput
        label="Bad (Negative)"
        value={semantic?.bad ?? ''}
        onChange={(v) => updateSemantic('bad', v)}
        testId="theme-semantic-bad"
      />
      <ColorInput
        label="Neutral"
        value={semantic?.neutral ?? ''}
        onChange={(v) => updateSemantic('neutral', v)}
        testId="theme-semantic-neutral"
      />
      <ColorInput
        label="Hyperlink"
        value={semantic?.hyperlink ?? ''}
        onChange={(v) => updateSemantic('hyperlink', v)}
        testId="theme-semantic-hyperlink"
      />
    </Section>
  )
}

// ─── Tab: Visual Card Layout ────────────────────────────────

function VisualCardTab() {
  const reportingTheme = useThemeStore(s => s.reportingTheme)
  const updateReportingTheme = useThemeStore(s => s.updateReportingTheme)
  const card = reportingTheme.visualCard

  const updateCard = useCallback(
    (key: keyof ReportingThemeVisualCard, value: unknown) => {
      updateReportingTheme({
        visualCard: { ...card, [key]: value },
      })
    },
    [card, updateReportingTheme]
  )

  return (
    <div className="space-y-4" data-testid="theme-tab-visual-card">
      <p className="text-xs text-muted-foreground">
        Configure the default appearance of visual cards on the canvas.
      </p>

      <Section title="Border" defaultOpen={true} testId="theme-card-border-section">
        <SliderInput
          label="Border Radius"
          value={card.borderRadius}
          min={0}
          max={20}
          onChange={(v) => updateCard('borderRadius', v)}
          testId="theme-card-border-radius"
        />
        <SliderInput
          label="Border Width"
          value={card.borderWidth}
          min={0}
          max={4}
          onChange={(v) => updateCard('borderWidth', v)}
          testId="theme-card-border-width"
        />
        <ColorInput
          label="Border Color"
          value={card.borderColor}
          onChange={(v) => updateCard('borderColor', v)}
          testId="theme-card-border-color"
        />
      </Section>

      <Separator />

      <Section title="Shadow & Spacing" defaultOpen={true} testId="theme-card-shadow-section">
        <div className="space-y-1">
          <Label className="text-xs">Shadow</Label>
          <Select
            value={card.shadow}
            onValueChange={(v) => updateCard('shadow', v)}
          >
            <SelectTrigger className="h-7 text-xs" data-testid="theme-card-shadow">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="none">None</SelectItem>
              <SelectItem value="sm">Small</SelectItem>
              <SelectItem value="md">Medium</SelectItem>
              <SelectItem value="lg">Large</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <SliderInput
          label="Padding"
          value={card.padding}
          min={0}
          max={24}
          onChange={(v) => updateCard('padding', v)}
          testId="theme-card-padding"
        />
      </Section>

      <Separator />

      <Section title="Background" defaultOpen={false} testId="theme-card-bg-section">
        <ColorInput
          label="Card Background"
          value={card.background}
          onChange={(v) => updateCard('background', v)}
          testId="theme-card-background"
        />
      </Section>
    </div>
  )
}

// ─── Tab: Fonts ─────────────────────────────────────────────

function FontsTab() {
  const reportingTheme = useThemeStore(s => s.reportingTheme)
  const updateReportingTheme = useThemeStore(s => s.updateReportingTheme)
  const font = reportingTheme.font

  const updateFont = useCallback(
    (key: keyof ReportingThemeFont, value: unknown) => {
      updateReportingTheme({
        font: { ...font, [key]: value },
      })
    },
    [font, updateReportingTheme]
  )

  return (
    <div className="space-y-4" data-testid="theme-tab-fonts">
      <p className="text-xs text-muted-foreground">
        Set the default font family and sizes used across visuals.
      </p>

      <div className="space-y-1">
        <Label className="text-xs">Font Family</Label>
        <Select
          value={font.family || '__default'}
          onValueChange={(v) => updateFont('family', v === '__default' ? '' : v)}
        >
          <SelectTrigger className="h-7 text-xs" data-testid="theme-font-family">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="__default">System Default</SelectItem>
            <SelectItem value="Segoe UI, sans-serif">Segoe UI</SelectItem>
            <SelectItem value="DIN, sans-serif">DIN</SelectItem>
            <SelectItem value="Inter, system-ui, sans-serif">Inter</SelectItem>
            <SelectItem value="Helvetica Neue, sans-serif">Helvetica Neue</SelectItem>
            <SelectItem value="Arial, sans-serif">Arial</SelectItem>
            <SelectItem value="Georgia, serif">Georgia</SelectItem>
            <SelectItem value="ui-monospace, monospace">Monospace</SelectItem>
          </SelectContent>
        </Select>
      </div>

      <Separator />

      <SliderInput
        label="Title Font Size"
        value={font.sizeTitle}
        min={10}
        max={32}
        onChange={(v) => updateFont('sizeTitle', v)}
        testId="theme-font-size-title"
      />
      <ColorInput
        label="Title Font Color"
        value={font.colorTitle}
        onChange={(v) => updateFont('colorTitle', v)}
        testId="theme-font-color-title"
      />

      <Separator />

      <SliderInput
        label="Body Font Size"
        value={font.sizeBody}
        min={8}
        max={24}
        onChange={(v) => updateFont('sizeBody', v)}
        testId="theme-font-size-body"
      />
      <ColorInput
        label="Body Font Color"
        value={font.colorBody}
        onChange={(v) => updateFont('colorBody', v)}
        testId="theme-font-color-body"
      />
    </div>
  )
}

// ─── Tab: Chart & Canvas ────────────────────────────────────

function ChartCanvasTab() {
  const reportingTheme = useThemeStore(s => s.reportingTheme)
  const updateReportingTheme = useThemeStore(s => s.updateReportingTheme)
  const chart = reportingTheme.chart
  const canvas = reportingTheme.canvas
  const defaultSize = reportingTheme.defaultSize

  const updateChart = useCallback(
    (key: keyof ReportingThemeChart, value: unknown) => {
      updateReportingTheme({
        chart: { ...chart, [key]: value },
      })
    },
    [chart, updateReportingTheme]
  )

  return (
    <div className="space-y-4" data-testid="theme-tab-chart">
      <p className="text-xs text-muted-foreground">
        Default chart styling and canvas appearance.
      </p>

      <Section title="Gridlines & Axes" defaultOpen={true} testId="theme-chart-grid-section">
        <div className="flex items-center justify-between">
          <Label className="text-xs">Show Gridlines</Label>
          <Switch
            checked={chart.showGridlines}
            onCheckedChange={(v) => updateChart('showGridlines', v)}
            data-testid="theme-chart-show-gridlines"
          />
        </div>
        <ColorInput
          label="Gridline Color"
          value={chart.gridlineColor}
          onChange={(v) => updateChart('gridlineColor', v)}
          testId="theme-chart-gridline-color"
        />
        <ColorInput
          label="Axis Color"
          value={chart.axisColor}
          onChange={(v) => updateChart('axisColor', v)}
          testId="theme-chart-axis-color"
        />
      </Section>

      <Separator />

      <Section title="Chart Background" defaultOpen={false} testId="theme-chart-bg-section">
        <ColorInput
          label="Plot Background"
          value={chart.plotBackground}
          onChange={(v) => updateChart('plotBackground', v)}
          testId="theme-chart-plot-bg"
        />
      </Section>

      <Separator />

      <Section title="Legend" defaultOpen={false} testId="theme-chart-legend-section">
        <div className="space-y-1">
          <Label className="text-xs">Default Legend Position</Label>
          <Select
            value={chart.legendPosition}
            onValueChange={(v) => updateChart('legendPosition', v)}
          >
            <SelectTrigger className="h-7 text-xs" data-testid="theme-chart-legend-position">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="top">Top</SelectItem>
              <SelectItem value="bottom">Bottom</SelectItem>
              <SelectItem value="left">Left</SelectItem>
              <SelectItem value="right">Right</SelectItem>
            </SelectContent>
          </Select>
        </div>
      </Section>

      <Separator />

      <Section title="Canvas" defaultOpen={true} testId="theme-canvas-section">
        <ColorInput
          label="Canvas Background"
          value={canvas.background ?? ''}
          onChange={(v) => updateReportingTheme({ canvas: { background: v } })}
          testId="theme-canvas-background"
        />
        <div className="space-y-1.5">
          <label className="text-xs font-medium">Background Image</label>
          <div className="flex items-center gap-2">
            {canvas.backgroundImage && (
              <div
                className="h-7 w-10 rounded border border-input bg-cover bg-center flex-shrink-0"
                style={{ backgroundImage: `url(${canvas.backgroundImage})` }}
              />
            )}
            <label className="cursor-pointer">
              <input
                type="file"
                accept="image/*"
                className="hidden"
                data-testid="theme-canvas-bg-image-upload"
                onChange={(e) => {
                  const file = e.target.files?.[0]
                  if (!file || !file.type.startsWith('image/')) return
                  const reader = new FileReader()
                  reader.onload = () => {
                    if (typeof reader.result === 'string') {
                      updateReportingTheme({ canvas: { backgroundImage: reader.result } })
                    }
                  }
                  reader.readAsDataURL(file)
                }}
              />
              <span className="inline-flex items-center justify-center h-7 px-3 text-xs rounded border border-input bg-background hover:bg-accent cursor-pointer">
                {canvas.backgroundImage ? 'Change' : 'Upload'}
              </span>
            </label>
            {canvas.backgroundImage && (
              <button
                className="h-7 px-2 text-xs rounded hover:bg-accent"
                onClick={() => updateReportingTheme({ canvas: { backgroundImage: '' } })}
              >
                Clear
              </button>
            )}
          </div>
        </div>
      </Section>

      <Separator />

      <Section title="Default Visual Size" defaultOpen={false} testId="theme-default-size-section">
        <SliderInput
          label="Default Width"
          value={defaultSize.width}
          min={200}
          max={1200}
          step={10}
          onChange={(v) => updateReportingTheme({ defaultSize: { ...defaultSize, width: v } })}
          testId="theme-default-width"
        />
        <SliderInput
          label="Default Height"
          value={defaultSize.height}
          min={150}
          max={900}
          step={10}
          onChange={(v) => updateReportingTheme({ defaultSize: { ...defaultSize, height: v } })}
          testId="theme-default-height"
        />
      </Section>
    </div>
  )
}

// ─── Main Editor Dialog ─────────────────────────────────────

interface ReportingThemeEditorProps {
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function ReportingThemeEditor({ open, onOpenChange }: ReportingThemeEditorProps) {
  const reportingTheme = useThemeStore(s => s.reportingTheme)
  const setReportingTheme = useThemeStore(s => s.setReportingTheme)
  const resetReportingTheme = useThemeStore(s => s.resetReportingTheme)
  const updateReportingTheme = useThemeStore(s => s.updateReportingTheme)
  const customPresets = useThemeStore(s => s.customPresets)
  const saveAsPreset = useThemeStore(s => s.saveAsPreset)
  const removeCustomPreset = useThemeStore(s => s.removeCustomPreset)
  const [activeTab, setActiveTab] = useState('colors')
  const [savePresetName, setSavePresetName] = useState('')
  const [showSaveDialog, setShowSaveDialog] = useState(false)
  const [importError, setImportError] = useState<string | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const handlePresetSelect = useCallback(
    (presetName: string) => {
      // Check built-in presets first, then custom
      const preset = PRESET_THEMES[presetName] ?? customPresets[presetName]
      if (preset) {
        setReportingTheme({ ...preset, dataColors: [...preset.dataColors] })
      }
    },
    [setReportingTheme, customPresets]
  )

  const handleNameChange = useCallback(
    (name: string) => {
      updateReportingTheme({ name })
    },
    [updateReportingTheme]
  )

  const handleSaveAsPreset = useCallback(() => {
    const name = savePresetName.trim()
    if (!name) return
    // Prevent overwriting built-in presets
    if (PRESET_THEMES[name]) {
      setImportError(`Cannot overwrite built-in preset "${name}".`)
      return
    }
    saveAsPreset(name)
    setSavePresetName('')
    setShowSaveDialog(false)
    setImportError(null)
  }, [savePresetName, saveAsPreset])

  const handleExportTheme = useCallback(() => {
    const json = JSON.stringify(reportingTheme, null, 2)
    const blob = new Blob([json], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${reportingTheme.name.replace(/[^a-zA-Z0-9_-]/g, '_')}_theme.json`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
  }, [reportingTheme])

  const handleImportTheme = useCallback((event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    if (!file) return
    setImportError(null)
    const reader = new FileReader()
    reader.onload = (e) => {
      try {
        const raw = JSON.parse(e.target?.result as string)
        // Support Power BI theme format: { name, dataColors, ... }
        if (validateThemeJson(raw)) {
          // Full theme object — fill any missing sections with defaults
          const imported = mergeTheme(DEFAULT_REPORTING_THEME, raw as Partial<ReportingTheme>)
          setReportingTheme({ ...imported, dataColors: [...imported.dataColors] })
          setImportError(null)
        } else if (raw && typeof raw === 'object' && Array.isArray(raw.dataColors)) {
          // Partial theme with at least dataColors (e.g., Power BI .json theme)
          const imported = mergeTheme(DEFAULT_REPORTING_THEME, {
            name: raw.name ?? file.name.replace(/\.json$/i, ''),
            dataColors: raw.dataColors,
          })
          setReportingTheme({ ...imported, dataColors: [...imported.dataColors] })
          setImportError(null)
        } else {
          setImportError('Invalid theme file. Must contain at least "name" and "dataColors".')
        }
      } catch {
        setImportError('Could not parse JSON file.')
      }
    }
    reader.readAsText(file)
    // Reset file input so same file can be re-imported
    if (fileInputRef.current) fileInputRef.current.value = ''
  }, [setReportingTheme])

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg max-h-[85vh] flex flex-col" data-testid="reporting-theme-editor">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Palette className="h-5 w-5" />
            Reporting Theme
          </DialogTitle>
          <DialogDescription>
            Customize the visual appearance of your report. Changes apply immediately but are only saved with Save All.
          </DialogDescription>
        </DialogHeader>

        {/* Theme name + preset selector + actions row */}
        <div className="flex items-end gap-2 py-1">
          <div className="flex-1 space-y-1">
            <Label className="text-xs">Theme Name</Label>
            <Input
              value={reportingTheme.name}
              onChange={(e) => handleNameChange(e.target.value)}
              className="h-7 text-xs"
              data-testid="theme-name-input"
            />
          </div>
          <div className="space-y-1">
            <Label className="text-xs">Preset</Label>
            <Select
              value=""
              onValueChange={handlePresetSelect}
            >
              <SelectTrigger className="h-7 text-xs w-36" data-testid="theme-preset-select">
                <SelectValue placeholder="Load preset…" />
              </SelectTrigger>
              <SelectContent>
                {/* Built-in presets */}
                <SelectItem value="_label_builtin" disabled className="text-[10px] font-semibold text-muted-foreground">
                  Built-in
                </SelectItem>
                {Object.keys(PRESET_THEMES).map((name) => (
                  <SelectItem key={name} value={name}>{name}</SelectItem>
                ))}
                {/* Custom presets (if any) */}
                {Object.keys(customPresets).length > 0 && (
                  <>
                    <SelectItem value="_label_custom" disabled className="text-[10px] font-semibold text-muted-foreground mt-1">
                      Custom
                    </SelectItem>
                    {Object.keys(customPresets).map((name) => (
                      <SelectItem key={`custom-${name}`} value={name}>{name}</SelectItem>
                    ))}
                  </>
                )}
              </SelectContent>
            </Select>
          </div>
        </div>

        {/* Action buttons: Save as Preset, Import, Export, Delete custom */}
        <div className="flex items-center gap-1.5 flex-wrap">
          <Button
            variant="outline"
            size="sm"
            className="h-7 text-xs"
            onClick={() => { setSavePresetName(reportingTheme.name); setShowSaveDialog(true); setImportError(null) }}
            data-testid="theme-save-preset-btn"
          >
            <Save className="h-3 w-3 mr-1" />
            Save as Preset
          </Button>
          <Button
            variant="outline"
            size="sm"
            className="h-7 text-xs"
            onClick={() => fileInputRef.current?.click()}
            data-testid="theme-import-btn"
          >
            <Upload className="h-3 w-3 mr-1" />
            Import
          </Button>
          <input
            ref={fileInputRef}
            type="file"
            accept=".json"
            className="hidden"
            onChange={handleImportTheme}
            data-testid="theme-import-input"
          />
          <Button
            variant="outline"
            size="sm"
            className="h-7 text-xs"
            onClick={handleExportTheme}
            data-testid="theme-export-btn"
          >
            <Download className="h-3 w-3 mr-1" />
            Export
          </Button>
          {/* Delete custom preset dropdown */}
          {Object.keys(customPresets).length > 0 && (
            <Select
              value=""
              onValueChange={(name) => { removeCustomPreset(name) }}
            >
              <SelectTrigger className="h-7 text-xs w-auto gap-1 text-destructive border-destructive/30" data-testid="theme-delete-preset-select">
                <Trash2 className="h-3 w-3" />
                <SelectValue placeholder="Delete preset…" />
              </SelectTrigger>
              <SelectContent>
                {Object.keys(customPresets).map((name) => (
                  <SelectItem key={`del-${name}`} value={name} className="text-destructive">{name}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          )}
        </div>

        {/* Import error message */}
        {importError && (
          <div className="flex items-center gap-2 text-xs text-destructive bg-destructive/10 rounded px-2 py-1">
            <span>{importError}</span>
            <button onClick={() => setImportError(null)} className="ml-auto">
              <X className="h-3 w-3" />
            </button>
          </div>
        )}

        {/* Save-as-preset inline dialog */}
        {showSaveDialog && (
          <div className="flex items-center gap-2 bg-muted/50 rounded px-2 py-1.5 border">
            <Label className="text-xs whitespace-nowrap">Preset name:</Label>
            <Input
              value={savePresetName}
              onChange={(e) => setSavePresetName(e.target.value)}
              className="h-7 text-xs flex-1"
              placeholder="My Theme"
              autoFocus
              onKeyDown={(e) => { if (e.key === 'Enter') handleSaveAsPreset(); if (e.key === 'Escape') setShowSaveDialog(false) }}
              data-testid="theme-save-preset-name"
            />
            <Button size="sm" className="h-7 text-xs" onClick={handleSaveAsPreset} data-testid="theme-save-preset-confirm">
              Save
            </Button>
            <Button variant="ghost" size="sm" className="h-7 text-xs" onClick={() => setShowSaveDialog(false)}>
              Cancel
            </Button>
          </div>
        )}

        <Separator />

        {/* Tabbed sections */}
        <Tabs value={activeTab} onValueChange={setActiveTab} className="flex-1 min-h-0">
          <TabsList className="w-full justify-start">
            <TabsTrigger value="colors" className="text-xs" data-testid="theme-tab-trigger-colors">
              Colors
            </TabsTrigger>
            <TabsTrigger value="visualCard" className="text-xs" data-testid="theme-tab-trigger-card">
              Card Layout
            </TabsTrigger>
            <TabsTrigger value="fonts" className="text-xs" data-testid="theme-tab-trigger-fonts">
              Fonts
            </TabsTrigger>
            <TabsTrigger value="chart" className="text-xs" data-testid="theme-tab-trigger-chart">
              Chart & Canvas
            </TabsTrigger>
          </TabsList>

          <ScrollArea className="flex-1 mt-2" style={{ maxHeight: 'calc(85vh - 300px)' }}>
            <TabsContent value="colors" className="mt-0 p-1">
              <DataColorsTab />
            </TabsContent>
            <TabsContent value="visualCard" className="mt-0 p-1">
              <VisualCardTab />
            </TabsContent>
            <TabsContent value="fonts" className="mt-0 p-1">
              <FontsTab />
            </TabsContent>
            <TabsContent value="chart" className="mt-0 p-1">
              <ChartCanvasTab />
            </TabsContent>
          </ScrollArea>
        </Tabs>

        <DialogFooter className="flex items-center justify-between gap-2 pt-2">
          <Button
            variant="outline"
            size="sm"
            onClick={resetReportingTheme}
            data-testid="theme-reset-btn"
          >
            <RotateCcw className="h-3 w-3 mr-1" />
            Reset to Default
          </Button>
          <Button
            size="sm"
            onClick={() => onOpenChange(false)}
            data-testid="theme-close-btn"
          >
            Done
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

/**
 * DesignCellEditor - Editor for design cell properties in matrix edit mode
 * Allows editing cell formatting, alignment, and display options
 */

import { useState, useCallback } from 'react'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { Separator } from '@/components/ui/separator'
import { 
  AlignLeft, 
  AlignCenter, 
  AlignRight, 
  Bold, 
  Italic, 
  Underline,
} from 'lucide-react'

export interface CellFormat {
  fontFamily?: string
  fontSize?: string
  fontWeight?: 'normal' | 'bold'
  fontStyle?: 'normal' | 'italic'
  textDecoration?: 'none' | 'underline'
  textAlign?: 'left' | 'center' | 'right'
  backgroundColor?: string
  textColor?: string
  numberFormat?: string
  showBar?: boolean
  barColor?: string
  /** IBCS graphic type for value cells */
  ibcsGraphic?: 'varianceArrow' | 'statusDot' | 'deviationBar' | 'progressBar' | ''
  /** Custom label text from inline editing (overrides default cell text) */
  label?: string
}

export interface DesignCellEditorProps {
  cellId: string
  cellRegion: string
  cellText: string
  format: CellFormat
  onChange: (cellId: string, format: CellFormat) => void
  onClose: () => void
  className?: string
}

const NUMBER_FORMATS = [
  { value: 'auto', label: 'Auto' },
  { value: '#,##0', label: 'Number (1,234)' },
  { value: '#,##0.00', label: 'Decimal (1,234.00)' },
  { value: '0%', label: 'Percentage (12%)' },
  { value: '0.0%', label: 'Percentage (12.3%)' },
  { value: '$#,##0', label: 'Currency ($1,234)' },
  { value: '$#,##0.00', label: 'Currency ($1,234.00)' },
]

const FONT_FAMILIES = [
  { value: '', label: 'Default' },
  { value: 'Arial, sans-serif', label: 'Arial' },
  { value: 'Segoe UI, sans-serif', label: 'Segoe UI' },
  { value: 'Calibri, sans-serif', label: 'Calibri' },
  { value: 'Verdana, sans-serif', label: 'Verdana' },
  { value: 'Tahoma, sans-serif', label: 'Tahoma' },
  { value: 'Courier New, monospace', label: 'Courier New' },
  { value: 'Consolas, monospace', label: 'Consolas' },
]

const FONT_SIZES = [
  { value: '', label: 'Default' },
  { value: '8px', label: '8' },
  { value: '9px', label: '9' },
  { value: '10px', label: '10' },
  { value: '11px', label: '11' },
  { value: '12px', label: '12' },
  { value: '14px', label: '14' },
  { value: '16px', label: '16' },
  { value: '18px', label: '18' },
  { value: '20px', label: '20' },
  { value: '24px', label: '24' },
]

const IBCS_GRAPHIC_TYPES = [
  { value: '', label: 'None' },
  { value: 'varianceArrow', label: 'Variance Arrow (▲▼)' },
  { value: 'statusDot', label: 'Status Dot (●)' },
  { value: 'deviationBar', label: 'Deviation Bar' },
  { value: 'progressBar', label: 'Progress Bar' },
]

export function DesignCellEditor({
  cellId,
  cellRegion,
  cellText,
  format,
  onChange,
  onClose,
  className,
}: DesignCellEditorProps) {
  const [localFormat, setLocalFormat] = useState<CellFormat>(format)

  const updateFormat = useCallback((updates: Partial<CellFormat>) => {
    const newFormat = { ...localFormat, ...updates }
    setLocalFormat(newFormat)
    onChange(cellId, newFormat)
  }, [localFormat, cellId, onChange])

  const toggleBold = useCallback(() => {
    updateFormat({ fontWeight: localFormat.fontWeight === 'bold' ? 'normal' : 'bold' })
  }, [localFormat.fontWeight, updateFormat])

  const toggleItalic = useCallback(() => {
    updateFormat({ fontStyle: localFormat.fontStyle === 'italic' ? 'normal' : 'italic' })
  }, [localFormat.fontStyle, updateFormat])

  const toggleUnderline = useCallback(() => {
    updateFormat({ textDecoration: localFormat.textDecoration === 'underline' ? 'none' : 'underline' })
  }, [localFormat.textDecoration, updateFormat])

  return (
    <div 
      className={`p-4 space-y-4 bg-background border rounded-lg shadow-lg ${className || ''}`}
      data-testid="design-cell-editor"
    >
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h4 className="font-medium text-sm">Cell Format</h4>
          <p className="text-xs text-muted-foreground">
            {cellRegion} • {cellText || '(empty)'}
          </p>
        </div>
        <Button variant="ghost" size="sm" onClick={onClose} aria-label="Close cell format editor" title="Close">
          ×
        </Button>
      </div>

      <Separator />

      {/* Font Family & Size */}
      <div className="space-y-2">
        <Label className="text-xs font-medium">Font</Label>
        <div className="grid grid-cols-2 gap-2">
          <Select
            value={localFormat.fontFamily || ''}
            onValueChange={(value) => updateFormat({ fontFamily: value || undefined })}
          >
            <SelectTrigger data-testid="format-font-family" aria-label="Font family" className="text-xs">
              <SelectValue placeholder="Default" />
            </SelectTrigger>
            <SelectContent>
              {FONT_FAMILIES.map((ff) => (
                <SelectItem key={ff.value || '_default'} value={ff.value || '_default'}>
                  {ff.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Select
            value={localFormat.fontSize || ''}
            onValueChange={(value) => updateFormat({ fontSize: value || undefined })}
          >
            <SelectTrigger data-testid="format-font-size" aria-label="Font size" className="text-xs">
              <SelectValue placeholder="Default" />
            </SelectTrigger>
            <SelectContent>
              {FONT_SIZES.map((fs) => (
                <SelectItem key={fs.value || '_default'} value={fs.value || '_default'}>
                  {fs.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>

      {/* Text Formatting */}
      <div className="space-y-2">
        <Label className="text-xs font-medium">Text Style</Label>
        <div className="flex gap-1">
          <Button
            variant={localFormat.fontWeight === 'bold' ? 'default' : 'outline'}
            size="sm"
            onClick={toggleBold}
            data-testid="format-bold"
            aria-label="Bold"
            aria-pressed={localFormat.fontWeight === 'bold'}
            title="Bold"
          >
            <Bold className="h-4 w-4" />
          </Button>
          <Button
            variant={localFormat.fontStyle === 'italic' ? 'default' : 'outline'}
            size="sm"
            onClick={toggleItalic}
            data-testid="format-italic"
            aria-label="Italic"
            aria-pressed={localFormat.fontStyle === 'italic'}
            title="Italic"
          >
            <Italic className="h-4 w-4" />
          </Button>
          <Button
            variant={localFormat.textDecoration === 'underline' ? 'default' : 'outline'}
            size="sm"
            onClick={toggleUnderline}
            data-testid="format-underline"
            aria-label="Underline"
            aria-pressed={localFormat.textDecoration === 'underline'}
            title="Underline"
          >
            <Underline className="h-4 w-4" />
          </Button>
        </div>
      </div>

      {/* Alignment */}
      <div className="space-y-2">
        <Label className="text-xs font-medium">Alignment</Label>
        <div className="flex gap-1">
          <Button
            variant={localFormat.textAlign === 'left' ? 'default' : 'outline'}
            size="sm"
            onClick={() => updateFormat({ textAlign: 'left' })}
            data-testid="format-align-left"
            aria-label="Align left"
            title="Align left"
          >
            <AlignLeft className="h-4 w-4" />
          </Button>
          <Button
            variant={localFormat.textAlign === 'center' ? 'default' : 'outline'}
            size="sm"
            onClick={() => updateFormat({ textAlign: 'center' })}
            data-testid="format-align-center"
            aria-label="Align center"
            title="Align center"
          >
            <AlignCenter className="h-4 w-4" />
          </Button>
          <Button
            variant={localFormat.textAlign === 'right' ? 'default' : 'outline'}
            size="sm"
            onClick={() => updateFormat({ textAlign: 'right' })}
            data-testid="format-align-right"
            aria-label="Align right"
            title="Align right"
          >
            <AlignRight className="h-4 w-4" />
          </Button>
        </div>
      </div>

      {/* Number Format */}
      <div className="space-y-2">
        <Label className="text-xs font-medium">Number Format</Label>
        <Select
          value={localFormat.numberFormat || 'auto'}
          onValueChange={(value) => updateFormat({ numberFormat: value === 'auto' ? '' : value })}
        >
          <SelectTrigger data-testid="format-number-select" aria-label="Number format">
            <SelectValue placeholder="Auto" />
          </SelectTrigger>
          <SelectContent>
            {NUMBER_FORMATS.map((fmt) => (
              <SelectItem key={fmt.value} value={fmt.value}>
                {fmt.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {/* Colors */}
      <div className="space-y-2">
        <Label className="text-xs font-medium">Colors</Label>
        <div className="grid grid-cols-2 gap-2">
          <div className="space-y-1">
            <Label className="text-xs text-muted-foreground">Text</Label>
            <div className="flex items-center gap-2">
              <div
                className="w-6 h-6 rounded border border-border shadow-sm"
                style={{ backgroundColor: localFormat.textColor || '#000000' }}
              />
              <Input
                type="color"
                value={localFormat.textColor || '#000000'}
                onChange={(e) => updateFormat({ textColor: e.target.value })}
                className="w-16 h-8 p-0.5 border border-border rounded cursor-pointer"
                data-testid="format-text-color"
                aria-label="Text color"
              />
            </div>
          </div>
          <div className="space-y-1">
            <Label className="text-xs text-muted-foreground">Background</Label>
            <div className="flex items-center gap-2">
              <div
                className="w-6 h-6 rounded border border-border shadow-sm"
                style={{ backgroundColor: localFormat.backgroundColor || '#ffffff' }}
              />
              <Input
                type="color"
                value={localFormat.backgroundColor || '#ffffff'}
                onChange={(e) => updateFormat({ backgroundColor: e.target.value })}
                className="w-16 h-8 p-0.5 border border-border rounded cursor-pointer"
                data-testid="format-bg-color"
                aria-label="Background color"
              />
            </div>
          </div>
        </div>
      </div>

      {/* IBCS Visualization */}
      <div className="space-y-2">
        <Label className="text-xs font-medium">IBCS Visualization</Label>
        <Select
          value={localFormat.ibcsGraphic || ''}
          onValueChange={(value) => updateFormat({ 
            ibcsGraphic: (value || undefined) as CellFormat['ibcsGraphic'],
            // Auto-disable data bar when an IBCS graphic is selected
            showBar: value ? false : localFormat.showBar,
          })}
        >
          <SelectTrigger data-testid="format-ibcs-graphic" aria-label="IBCS graphic type" className="text-xs">
            <SelectValue placeholder="None" />
          </SelectTrigger>
          <SelectContent>
            {IBCS_GRAPHIC_TYPES.map((g) => (
              <SelectItem key={g.value || '_none'} value={g.value || '_none'}>
                {g.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        
        <div className="flex items-center justify-between">
          <Label className="text-xs font-medium">Show Data Bar</Label>
          <Switch
            checked={localFormat.showBar || false}
            onCheckedChange={(checked) => updateFormat({ 
              showBar: checked,
              // Auto-clear IBCS graphic when data bar is toggled on
              ibcsGraphic: checked ? '' : localFormat.ibcsGraphic,
            })}
            data-testid="format-show-bar"
            aria-label="Show data bar"
          />
        </div>
        {localFormat.showBar && (
          <div className="flex items-center gap-2">
            <Label className="text-xs text-muted-foreground">Bar Color</Label>
            <div
              className="w-6 h-6 rounded border border-border shadow-sm"
              style={{ backgroundColor: localFormat.barColor || '#3b82f6' }}
            />
            <Input
              type="color"
              value={localFormat.barColor || '#3b82f6'}
              onChange={(e) => updateFormat({ barColor: e.target.value })}
              className="w-16 h-8 p-0.5 border border-border rounded cursor-pointer"
              data-testid="format-bar-color"
              aria-label="Bar color"
            />
          </div>
        )}
      </div>

      <Separator />

      {/* Actions */}
      <div className="flex justify-end gap-2">
        <Button variant="outline" size="sm" onClick={onClose}>
          Close
        </Button>
      </div>
    </div>
  )
}

export default DesignCellEditor

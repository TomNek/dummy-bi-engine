/**
 * Editor panel for static visual content properties.
 * Appears in the right sidebar when a static visual (textbox, button, shape, image)
 * is selected.
 *
 * Button types: Power BI button catalog (blank, back, arrows, reset, info, help, bookmark, etc.)
 * Shapes: Rectangles, Basic Shapes, Block Arrows — matches Power BI.
 * Action editor: lets user assign bookmark / URL / page navigation to buttons & shapes.
 */

import { useState, useCallback, useEffect, useRef } from 'react'
import { Label } from '@/components/ui/label'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Slider } from '@/components/ui/slider'
import { Separator } from '@/components/ui/separator'
import { useAppStore } from '@/stores'
import { useReportStore } from '@/stores'
import { getBookmarks } from '@/lib/api'
import type { StaticContent, StaticAction, Bookmark } from '@/lib/api'

interface StaticContentEditorProps {
  visualType: string
  content: StaticContent
  onChange: (content: StaticContent) => void
}

export function StaticContentEditor({ visualType, content, onChange }: StaticContentEditorProps) {
  const type = visualType.toLowerCase()

  // Keep a ref to the latest content so the update callback never uses stale data
  const contentRef = useRef(content)
  useEffect(() => { contentRef.current = content }, [content])

  const update = useCallback((key: keyof StaticContent, value: unknown) => {
    const latest = { ...contentRef.current, [key]: value }
    contentRef.current = latest          // update ref immediately for rapid successive calls
    onChange(latest)
  }, [onChange])

  switch (type) {
    case 'textbox':
      return <TextBoxEditor content={content} update={update} />
    case 'button':
      return <ButtonEditor content={content} update={update} />
    case 'shape':
      return <ShapeEditor content={content} update={update} />
    case 'image':
      return <ImageEditor content={content} update={update} />
    default:
      return null
  }
}

// ─── Text Box Editor ─────────────────────────────────────────────────────────

function TextBoxEditor({ content, update }: { content: StaticContent; update: (k: keyof StaticContent, v: unknown) => void }) {
  const [localText, setLocalText] = useState(content.text ?? '')
  const textRef = useRef(localText)
  const pendingRef = useRef(false)

  // Sync when external content changes (e.g. undo / different visual selected)
  useEffect(() => {
    setLocalText(content.text ?? '')
    textRef.current = content.text ?? ''
  }, [content.text])

  const flush = useCallback(() => {
    if (pendingRef.current) {
      update('text', textRef.current)
      pendingRef.current = false
    }
  }, [update])

  // Flush on unmount so edits are never silently lost
  useEffect(() => {
    return () => { flush() }
  }, [flush])

  const handleChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setLocalText(e.target.value)
    textRef.current = e.target.value
    pendingRef.current = true
  }

  return (
    <div className="space-y-3" data-testid="static-content-editor-textbox">
      <div>
        <Label className="text-xs">Text</Label>
        <Textarea
          value={localText}
          onChange={handleChange}
          onBlur={flush}
          onKeyDown={(e) => {
            // Ctrl+Enter / Cmd+Enter also saves immediately
            if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
              flush()
            }
          }}
          className="text-xs min-h-[80px] mt-1"
          placeholder="Enter text..."
          data-testid="static-textbox-text"
        />
        <span className="text-[10px] text-muted-foreground">Press Ctrl+Enter or click away to save</span>
      </div>
      <div className="grid grid-cols-2 gap-2">
        <div>
          <Label className="text-xs">Font Size</Label>
          <Input
            type="number"
            value={content.fontSize ?? 14}
            onChange={(e) => update('fontSize', parseInt(e.target.value) || 14)}
            className="h-7 text-xs mt-1"
            min={8}
            max={72}
            data-testid="static-textbox-fontsize"
          />
        </div>
        <div>
          <Label className="text-xs">Weight</Label>
          <Select
            value={content.fontWeight ?? 'normal'}
            onValueChange={(v) => update('fontWeight', v)}
          >
            <SelectTrigger className="h-7 text-xs mt-1" data-testid="static-textbox-fontweight">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="normal">Normal</SelectItem>
              <SelectItem value="bold">Bold</SelectItem>
              <SelectItem value="lighter">Light</SelectItem>
            </SelectContent>
          </Select>
        </div>
      </div>
      <div>
        <Label className="text-xs">Alignment</Label>
        <Select
          value={content.textAlign ?? 'left'}
          onValueChange={(v) => update('textAlign', v)}
        >
          <SelectTrigger className="h-7 text-xs mt-1" data-testid="static-textbox-align">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="left">Left</SelectItem>
            <SelectItem value="center">Center</SelectItem>
            <SelectItem value="right">Right</SelectItem>
          </SelectContent>
        </Select>
      </div>
      <div className="grid grid-cols-2 gap-2">
        <div>
          <Label className="text-xs">Text Color</Label>
          <Input
            type="color"
            value={content.color ?? '#000000'}
            onChange={(e) => update('color', e.target.value)}
            className="h-7 mt-1 p-0.5"
            data-testid="static-textbox-color"
          />
        </div>
        <div>
          <Label className="text-xs">Background</Label>
          <Input
            type="color"
            value={content.backgroundColor === 'transparent' ? '#ffffff' : (content.backgroundColor ?? '#ffffff')}
            onChange={(e) => update('backgroundColor', e.target.value)}
            className="h-7 mt-1 p-0.5"
            data-testid="static-textbox-bgcolor"
          />
        </div>
      </div>
    </div>
  )
}

// ─── Button Editor ───────────────────────────────────────────────────────────

/** All Power BI button types */
const BUTTON_TYPES: { value: string; label: string }[] = [
  { value: 'blank', label: 'Blank' },
  { value: 'left-arrow', label: 'Left Arrow' },
  { value: 'right-arrow', label: 'Right Arrow' },
  { value: 'reset', label: 'Reset' },
  { value: 'back', label: 'Back' },
  { value: 'information', label: 'Information' },
  { value: 'help', label: 'Help' },
  { value: 'bookmark', label: 'Bookmark' },
  { value: 'apply-all-slicers', label: 'Apply All Slicers' },
  { value: 'clear-all-slicers', label: 'Clear All Slicers' },
  { value: 'navigator', label: 'Navigator' },
]

function ButtonEditor({ content, update }: { content: StaticContent; update: (k: keyof StaticContent, v: unknown) => void }) {
  const [localLabel, setLocalLabel] = useState(content.label ?? 'Button')
  const labelRef = useRef(localLabel)

  useEffect(() => {
    setLocalLabel(content.label ?? 'Button')
    labelRef.current = content.label ?? 'Button'
  }, [content.label])

  return (
    <div className="space-y-3" data-testid="static-content-editor-button">
      <div>
        <Label className="text-xs">Button Type</Label>
        <Select
          value={content.buttonType ?? 'blank'}
          onValueChange={(v) => update('buttonType', v)}
        >
          <SelectTrigger className="h-7 text-xs mt-1" data-testid="static-button-type">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {BUTTON_TYPES.map((bt) => (
              <SelectItem key={bt.value} value={bt.value}>{bt.label}</SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      <div>
        <Label className="text-xs">Label</Label>
        <Input
          value={localLabel}
          onChange={(e) => { setLocalLabel(e.target.value); labelRef.current = e.target.value }}
          onBlur={() => update('label', labelRef.current)}
          className="h-7 text-xs mt-1"
          placeholder="Button text"
          data-testid="static-button-label"
        />
      </div>
      <div className="grid grid-cols-2 gap-2">
        <div>
          <Label className="text-xs">Background</Label>
          <Input
            type="color"
            value={content.backgroundColor ?? '#0078d4'}
            onChange={(e) => update('backgroundColor', e.target.value)}
            className="h-7 mt-1 p-0.5"
            data-testid="static-button-bgcolor"
          />
        </div>
        <div>
          <Label className="text-xs">Text Color</Label>
          <Input
            type="color"
            value={content.color ?? '#ffffff'}
            onChange={(e) => update('color', e.target.value)}
            className="h-7 mt-1 p-0.5"
            data-testid="static-button-color"
          />
        </div>
      </div>
      <div>
        <Label className="text-xs">Border Radius</Label>
        <Slider
          value={[content.borderRadius ?? 4]}
          min={0}
          max={24}
          step={1}
          onValueChange={([v]) => update('borderRadius', v)}
          className="mt-2"
        />
        <span className="text-[10px] text-muted-foreground">{content.borderRadius ?? 4}px</span>
      </div>

      <Separator />
      <ActionEditor action={content.action} onChange={(a) => update('action', a)} />
    </div>
  )
}

// ─── Shape Editor ────────────────────────────────────────────────────────────

/** All Power BI shape types organized by category */
const SHAPE_CATEGORIES: { label: string; shapes: { value: string; label: string }[] }[] = [
  {
    label: 'Rectangles',
    shapes: [
      { value: 'rectangle', label: 'Rectangle' },
      { value: 'rounded-rectangle', label: 'Rounded Rectangle' },
      { value: 'snip-corner', label: 'Snip Corner' },
      { value: 'beveled', label: 'Beveled' },
    ],
  },
  {
    label: 'Basic Shapes',
    shapes: [
      { value: 'circle', label: 'Circle' },
      { value: 'ellipse', label: 'Ellipse' },
      { value: 'triangle', label: 'Triangle' },
      { value: 'diamond', label: 'Diamond' },
      { value: 'pentagon', label: 'Pentagon' },
      { value: 'hexagon', label: 'Hexagon' },
      { value: 'octagon', label: 'Octagon' },
      { value: 'heart', label: 'Heart' },
      { value: 'parallelogram', label: 'Parallelogram' },
      { value: 'trapezoid', label: 'Trapezoid' },
      { value: 'chevron', label: 'Chevron' },
      { value: 'line', label: 'Line' },
    ],
  },
  {
    label: 'Block Arrows',
    shapes: [
      { value: 'arrow-right', label: 'Arrow Right' },
      { value: 'arrow-left', label: 'Arrow Left' },
      { value: 'arrow-up', label: 'Arrow Up' },
      { value: 'arrow-down', label: 'Arrow Down' },
    ],
  },
]

function ShapeEditor({ content, update }: { content: StaticContent; update: (k: keyof StaticContent, v: unknown) => void }) {
  return (
    <div className="space-y-3" data-testid="static-content-editor-shape">
      <div>
        <Label className="text-xs">Shape</Label>
        <Select
          value={content.shapeType ?? 'rectangle'}
          onValueChange={(v) => update('shapeType', v)}
        >
          <SelectTrigger className="h-7 text-xs mt-1" data-testid="static-shape-type">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {SHAPE_CATEGORIES.map((cat) => (
              <div key={cat.label}>
                <div className="px-2 py-1 text-[10px] font-semibold text-muted-foreground uppercase tracking-wider">
                  {cat.label}
                </div>
                {cat.shapes.map((s) => (
                  <SelectItem key={s.value} value={s.value}>{s.label}</SelectItem>
                ))}
              </div>
            ))}
          </SelectContent>
        </Select>
      </div>
      <div className="grid grid-cols-2 gap-2">
        <div>
          <Label className="text-xs">Fill</Label>
          <Input
            type="color"
            value={content.fill ?? '#0078d4'}
            onChange={(e) => update('fill', e.target.value)}
            className="h-7 mt-1 p-0.5"
            data-testid="static-shape-fill"
          />
        </div>
        <div>
          <Label className="text-xs">Stroke</Label>
          <Input
            type="color"
            value={content.stroke ?? '#005a9e'}
            onChange={(e) => update('stroke', e.target.value)}
            className="h-7 mt-1 p-0.5"
            data-testid="static-shape-stroke"
          />
        </div>
      </div>
      <div>
        <Label className="text-xs">Stroke Width</Label>
        <Slider
          value={[content.strokeWidth ?? 1]}
          min={0}
          max={10}
          step={0.5}
          onValueChange={([v]) => update('strokeWidth', v)}
          className="mt-2"
        />
        <span className="text-[10px] text-muted-foreground">{content.strokeWidth ?? 1}px</span>
      </div>
      <div>
        <Label className="text-xs">Opacity</Label>
        <Slider
          value={[content.opacity ?? 1.0]}
          min={0}
          max={1}
          step={0.05}
          onValueChange={([v]) => update('opacity', v)}
          className="mt-2"
        />
        <span className="text-[10px] text-muted-foreground">{Math.round((content.opacity ?? 1.0) * 100)}%</span>
      </div>
      {(content.shapeType === 'rectangle' || !content.shapeType) && (
        <div>
          <Label className="text-xs">Corner Radius</Label>
          <Slider
            value={[content.borderRadius ?? 0]}
            min={0}
            max={50}
            step={1}
            onValueChange={([v]) => update('borderRadius', v)}
            className="mt-2"
          />
          <span className="text-[10px] text-muted-foreground">{content.borderRadius ?? 0}px</span>
        </div>
      )}

      <Separator />
      <ActionEditor action={content.action} onChange={(a) => update('action', a)} />
    </div>
  )
}

// ─── Image Editor ────────────────────────────────────────────────────────────

function ImageEditor({ content, update }: { content: StaticContent; update: (k: keyof StaticContent, v: unknown) => void }) {
  return (
    <div className="space-y-3" data-testid="static-content-editor-image">
      <div>
        <Label className="text-xs">Image URL</Label>
        <Input
          value={content.url ?? ''}
          onChange={(e) => update('url', e.target.value)}
          className="h-7 text-xs mt-1"
          placeholder="https://example.com/image.png"
          data-testid="static-image-url"
        />
      </div>
      <div>
        <Label className="text-xs">Alt Text</Label>
        <Input
          value={content.alt ?? ''}
          onChange={(e) => update('alt', e.target.value)}
          className="h-7 text-xs mt-1"
          placeholder="Image description"
          data-testid="static-image-alt"
        />
      </div>
      <div>
        <Label className="text-xs">Fit</Label>
        <Select
          value={content.fit ?? 'contain'}
          onValueChange={(v) => update('fit', v)}
        >
          <SelectTrigger className="h-7 text-xs mt-1" data-testid="static-image-fit">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="contain">Contain</SelectItem>
            <SelectItem value="cover">Cover</SelectItem>
            <SelectItem value="fill">Fill</SelectItem>
            <SelectItem value="none">None</SelectItem>
          </SelectContent>
        </Select>
      </div>
    </div>
  )
}

// ─── Action Editor (shared by Button & Shape) ────────────────────────────────

function ActionEditor({
  action,
  onChange,
}: {
  action?: StaticAction
  onChange: (action: StaticAction) => void
}) {
  const projectPath = useAppStore((s) => s.projectPath)
  const pages = useReportStore((s) => s.pages)
  const [bookmarks, setBookmarks] = useState<Bookmark[]>([])
  const [loadedBookmarks, setLoadedBookmarks] = useState(false)

  const actionType = action?.type ?? 'none'
  const actionTarget = action?.target ?? ''

  // Load bookmarks on first expand of the bookmark option
  useEffect(() => {
    if (actionType === 'bookmark' && !loadedBookmarks) {
      getBookmarks(projectPath ?? undefined).then((res) => {
        if (res.data?.bookmarks) {
          setBookmarks(res.data.bookmarks)
        }
        setLoadedBookmarks(true)
      })
    }
  }, [actionType, loadedBookmarks, projectPath])

  return (
    <div className="space-y-2" data-testid="static-action-editor">
      <Label className="text-xs font-medium">Action (on click)</Label>
      <Select
        value={actionType}
        onValueChange={(v) => onChange({ type: v as StaticAction['type'], target: v === actionType ? actionTarget : '' })}
      >
        <SelectTrigger className="h-7 text-xs" data-testid="static-action-type">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="none">None</SelectItem>
          <SelectItem value="bookmark">Bookmark</SelectItem>
          <SelectItem value="url">Web URL</SelectItem>
          <SelectItem value="page">Page Navigation</SelectItem>
        </SelectContent>
      </Select>

      {actionType === 'bookmark' && (
        <div>
          <Label className="text-xs">Bookmark</Label>
          {bookmarks.length > 0 ? (
            <Select
              value={actionTarget}
              onValueChange={(v) => onChange({ type: 'bookmark', target: v })}
            >
              <SelectTrigger className="h-7 text-xs mt-1" data-testid="static-action-bookmark">
                <SelectValue placeholder="Select bookmark..." />
              </SelectTrigger>
              <SelectContent>
                {bookmarks.map((b) => (
                  <SelectItem key={b.id} value={b.id}>{b.name}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          ) : (
            <p className="text-[10px] text-muted-foreground mt-1">
              {loadedBookmarks ? 'No bookmarks defined. Create one first.' : 'Loading bookmarks...'}
            </p>
          )}
        </div>
      )}

      {actionType === 'url' && (
        <div>
          <Label className="text-xs">URL</Label>
          <Input
            value={actionTarget}
            onChange={(e) => onChange({ type: 'url', target: e.target.value })}
            className="h-7 text-xs mt-1"
            placeholder="https://..."
            data-testid="static-action-url"
          />
        </div>
      )}

      {actionType === 'page' && (
        <div>
          <Label className="text-xs">Page</Label>
          <Select
            value={actionTarget}
            onValueChange={(v) => onChange({ type: 'page', target: v })}
          >
            <SelectTrigger className="h-7 text-xs mt-1" data-testid="static-action-page">
              <SelectValue placeholder="Select page..." />
            </SelectTrigger>
            <SelectContent>
              {pages.map((p) => (
                <SelectItem key={p.id} value={p.id}>{p.title || p.id}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      )}
    </div>
  )
}

import { useState, useRef, useEffect, useCallback } from 'react'
import { cn } from '@/lib/utils'
import { HAS_STORIES } from '@/lib/edition'
import { Button } from '@/components/ui/button'
import { useReportStore, useAppStore } from '@/stores'
import { useDrillthroughStore } from '@/stores/drillthrough-store'
import { useRuntimeState } from '@/hooks'
import { Plus, X, GripVertical, ArrowLeft, Eye, EyeOff, Pencil, Trash2, Copy, MessageSquare, Presentation, ChevronLeft, ChevronRight } from 'lucide-react'
import {
  ContextMenu,
  ContextMenuTrigger,
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuSeparator,
} from '@/components/ui/context-menu'

interface PageTabsProps {
  className?: string
}

export function PageTabs({ className }: PageTabsProps) {
  const pages = useReportStore(s => s.pages)
  const currentPageId = useReportStore(s => s.currentPageId)
  const addPage = useReportStore(s => s.addPage)
  const removePage = useReportStore(s => s.removePage)
  const renamePage = useReportStore(s => s.renamePage)
  const togglePageHidden = useReportStore(s => s.togglePageHidden)
  const setPageType = useReportStore(s => s.setPageType)
  const storeReorder = useReportStore(s => s.reorderPages)
  const { changePage } = useRuntimeState()
  const setDirty = useAppStore(s => s.setDirty)

  // Drillthrough back navigation
  const drillthroughActive = useDrillthroughStore(s => s.active)
  const drillthroughSource = useDrillthroughStore(s => s.sourcePageId)
  const endDrillthrough = useDrillthroughStore(s => s.endDrillthrough)

  const handleDrillthroughBack = useCallback(() => {
    if (!drillthroughSource) return
    changePage(drillthroughSource)
    endDrillthrough()
  }, [drillthroughSource, changePage, endDrillthrough])

  // ── Inline rename state ──
  const [editingPageId, setEditingPageId] = useState<string | null>(null)
  const [editTitle, setEditTitle] = useState('')
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (editingPageId && inputRef.current) {
      inputRef.current.focus()
      inputRef.current.select()
    }
  }, [editingPageId])

  const startRename = useCallback((pageId: string, currentTitle: string) => {
    setEditingPageId(pageId)
    setEditTitle(currentTitle)
  }, [])

  const commitRename = useCallback(() => {
    if (!editingPageId) return
    const trimmed = editTitle.trim()
    if (!trimmed) {
      setEditingPageId(null)
      return
    }
    renamePage(editingPageId, trimmed)
    setDirty(true)
    setEditingPageId(null)
  }, [editingPageId, editTitle, renamePage, setDirty])

  const cancelRename = useCallback(() => {
    setEditingPageId(null)
  }, [])

  // ── Add page (in-memory only, persisted via Save All) ──
  const handleAddPage = useCallback(() => {
    const id = `page_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`
    addPage({ id, title: `Page ${pages.length + 1}`, order: pages.length + 1 })
    setDirty(true)
  }, [pages.length, addPage, setDirty])

  // ── Delete page (in-memory only, persisted via Save All) ──
  const handleDeletePage = useCallback((pageId: string) => {
    if (pages.length <= 1) return
    removePage(pageId)
    setDirty(true)
  }, [pages.length, removePage, setDirty])

  // ── Hide/unhide page ──
  const handleToggleHidden = useCallback((pageId: string) => {
    togglePageHidden(pageId)
    setDirty(true)
  }, [togglePageHidden, setDirty])

  // ── Duplicate page (creates a new page with same title + " (Copy)") ──
  const handleDuplicatePage = useCallback((page: { id: string; title: string }) => {
    const id = `page_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`
    addPage({ id, title: `${page.title} (Copy)`, order: pages.length + 1 })
    setDirty(true)
  }, [pages.length, addPage, setDirty])

  // ── Toggle tooltip page type ──
  const handleToggleTooltipPage = useCallback((pageId: string, currentPageType?: string) => {
    const isTooltip = currentPageType === 'tooltip'
    setPageType(pageId, isTooltip ? undefined : 'tooltip')
    setDirty(true)
  }, [setPageType, setDirty])

  // ── Add tooltip page ──
  const handleAddTooltipPage = useCallback(() => {
    const id = `tooltip_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`
    addPage({ id, title: `Tooltip ${pages.filter(p => p.page_type === 'tooltip').length + 1}`, order: pages.length + 1, page_type: 'tooltip' })
    changePage(id)
    setDirty(true)
  }, [pages, addPage, changePage, setDirty])

  // ── Add story page ──
  const handleAddStoryPage = useCallback(() => {
    const id = `story_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`
    addPage({ id, title: `Story ${pages.filter(p => p.page_type === 'story').length + 1}`, order: pages.length + 1, page_type: 'story' })
    changePage(id)
    setDirty(true)
  }, [pages, addPage, changePage, setDirty])

  // ── Toggle story page type ──
  const handleToggleStoryPage = useCallback((pageId: string, currentPageType?: string) => {
    const isStory = currentPageType === 'story'
    setPageType(pageId, isStory ? undefined : 'story')
    setDirty(true)
  }, [setPageType, setDirty])

  // ── Show hidden pages toggle ──
  const [showHiddenPages, setShowHiddenPages] = useState(true)

  // ── Scroll arrows for overflow ──
  const scrollContainerRef = useRef<HTMLDivElement>(null)
  const [canScrollLeft, setCanScrollLeft] = useState(false)
  const [canScrollRight, setCanScrollRight] = useState(false)

  const updateScrollArrows = useCallback(() => {
    const el = scrollContainerRef.current
    if (!el) return
    setCanScrollLeft(el.scrollLeft > 1)
    setCanScrollRight(el.scrollLeft + el.clientWidth < el.scrollWidth - 1)
  }, [])

  useEffect(() => {
    const el = scrollContainerRef.current
    if (!el) return
    updateScrollArrows()
    el.addEventListener('scroll', updateScrollArrows, { passive: true })
    const ro = new ResizeObserver(updateScrollArrows)
    ro.observe(el)
    return () => {
      el.removeEventListener('scroll', updateScrollArrows)
      ro.disconnect()
    }
  }, [updateScrollArrows, pages])

  const scrollBy = useCallback((delta: number) => {
    scrollContainerRef.current?.scrollBy({ left: delta, behavior: 'smooth' })
  }, [])

  // ── Drag reorder state ──
  const [draggedPageId, setDraggedPageId] = useState<string | null>(null)
  const [dragOverPageId, setDragOverPageId] = useState<string | null>(null)

  const handleDragStart = useCallback((e: React.DragEvent, pageId: string) => {
    setDraggedPageId(pageId)
    e.dataTransfer.effectAllowed = 'move'
    e.dataTransfer.setData('text/plain', pageId)
  }, [])

  const handleDragOver = useCallback((e: React.DragEvent, pageId: string) => {
    e.preventDefault()
    e.dataTransfer.dropEffect = 'move'
    setDragOverPageId(pageId)
  }, [])

  const handleDrop = useCallback((e: React.DragEvent, targetPageId: string) => {
    e.preventDefault()
    setDragOverPageId(null)
    if (!draggedPageId || draggedPageId === targetPageId) {
      setDraggedPageId(null)
      return
    }
    // Compute new order
    const newPages = [...pages]
    const fromIx = newPages.findIndex((p) => p.id === draggedPageId)
    const toIx = newPages.findIndex((p) => p.id === targetPageId)
    if (fromIx < 0 || toIx < 0) { setDraggedPageId(null); return }
    const [moved] = newPages.splice(fromIx, 1)
    newPages.splice(toIx, 0, moved)
    // Re-assign order (in-memory only, persisted via Save All)
    const reordered = newPages.map((p, i) => ({ ...p, order: i + 1 }))
    storeReorder(reordered)
    setDirty(true)
    setDraggedPageId(null)
  }, [draggedPageId, pages, storeReorder, setDirty])

  const handleDragEnd = useCallback(() => {
    setDraggedPageId(null)
    setDragOverPageId(null)
  }, [])

  if (pages.length === 0) {
    return (
      <div
        className={cn(
          'flex items-center h-9 border-t bg-background px-2',
          className
        )}
        data-testid="page-tabs"
      >
        <span className="text-xs text-muted-foreground">No pages</span>
      </div>
    )
  }

  return (
    <div
      className={cn(
        'flex items-center h-9 border-t bg-background',
        className
      )}
      data-testid="page-tabs"
    >
      {/* Drillthrough back button */}
      {drillthroughActive && (
        <Button
          variant="outline"
          size="sm"
          className="h-7 px-2 text-xs rounded-sm gap-1 mr-1 border-amber-500 text-amber-700 hover:bg-amber-50"
          onClick={handleDrillthroughBack}
          data-testid="drillthrough-back-btn"
          aria-label="Back to source page"
          title="Back to source page"
        >
          <ArrowLeft className="h-3 w-3" />
          Back
        </Button>
      )}
      {/* Scroll left arrow — always rendered, disabled when at start */}
      <Button
        variant="ghost"
        size="sm"
        className={cn('h-7 w-6 p-0 shrink-0', !canScrollLeft && 'opacity-0 pointer-events-none')}
        onClick={() => scrollBy(-150)}
        data-testid="page-tabs-scroll-left"
        aria-label="Scroll tabs left"
        title="Scroll tabs left"
        tabIndex={canScrollLeft ? 0 : -1}
      >
        <ChevronLeft className="h-3.5 w-3.5" />
      </Button>
      <div ref={scrollContainerRef} className="flex-1 overflow-x-auto scrollbar-none">
        <div className="flex items-center gap-0.5 px-1 w-max">
          {pages.filter(p => p.page_type !== 'tooltip' && p.page_type !== 'story').filter(p => showHiddenPages || !p.hidden).map((page) => (
            <ContextMenu key={page.id}>
              <ContextMenuTrigger asChild>
                <div
                  draggable
                  onDragStart={(e) => handleDragStart(e, page.id)}
                  onDragOver={(e) => handleDragOver(e, page.id)}
                  onDrop={(e) => handleDrop(e, page.id)}
                  onDragEnd={handleDragEnd}
                  onDoubleClick={() => startRename(page.id, page.title)}
                  className={cn(
                    'flex items-center',
                    dragOverPageId === page.id && draggedPageId !== page.id && 'border-l-2 border-primary'
                  )}
                  data-testid={`page-tab-${page.id}`}
                >
                  {editingPageId === page.id ? (
                    <input
                      ref={inputRef}
                      type="text"
                      value={editTitle}
                      onChange={(e) => setEditTitle(e.target.value)}
                      onBlur={commitRename}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') commitRename()
                        if (e.key === 'Escape') cancelRename()
                      }}
                      className="h-7 px-2 text-xs bg-background border rounded-sm w-24"
                      data-testid={`page-tab-rename-input-${page.id}`}
                    />
                  ) : (
                    <Button
                      variant={currentPageId === page.id ? 'secondary' : 'ghost'}
                      size="sm"
                      className={cn(
                        'h-7 px-3 text-xs rounded-sm gap-1 group',
                        currentPageId === page.id && 'bg-muted',
                        page.hidden && 'opacity-50 italic'
                      )}
                      onClick={() => changePage(page.id)}
                      aria-label={`Page: ${page.title}${page.hidden ? ' (Hidden)' : ''}`}
                      title={page.hidden ? `${page.title} (Hidden)` : page.title}
                    >
                      <GripVertical className="h-3 w-3 opacity-0 group-hover:opacity-40 cursor-grab" />
                      {page.hidden && <EyeOff className="h-3 w-3 text-muted-foreground" />}
                      <span className="truncate max-w-[120px]">{page.title}</span>
                      {pages.length > 1 && (
                        <span
                          className="inline-flex items-center justify-center pointer-events-auto cursor-pointer opacity-0 group-hover:opacity-50 hover:!opacity-100"
                          onClick={(e) => {
                            e.stopPropagation()
                            handleDeletePage(page.id)
                          }}
                          data-testid={`page-tab-delete-${page.id}`}
                        >
                          <X className="h-3 w-3" />
                        </span>
                      )}
                    </Button>
                  )}
                </div>
              </ContextMenuTrigger>
              <ContextMenuContent>
                <ContextMenuItem
                  onClick={() => startRename(page.id, page.title)}
                  data-testid={`page-ctx-rename-${page.id}`}
                >
                  <Pencil className="h-3.5 w-3.5 mr-2" />
                  Rename
                </ContextMenuItem>
                <ContextMenuItem
                  onClick={() => handleDuplicatePage(page)}
                  data-testid={`page-ctx-duplicate-${page.id}`}
                >
                  <Copy className="h-3.5 w-3.5 mr-2" />
                  Duplicate Page
                </ContextMenuItem>
                <ContextMenuSeparator />
                <ContextMenuItem
                  onClick={() => handleToggleHidden(page.id)}
                  data-testid={`page-ctx-toggle-hidden-${page.id}`}
                >
                  {page.hidden ? (
                    <>
                      <Eye className="h-3.5 w-3.5 mr-2" />
                      Show Page
                    </>
                  ) : (
                    <>
                      <EyeOff className="h-3.5 w-3.5 mr-2" />
                      Hide Page
                    </>
                  )}
                </ContextMenuItem>
                <ContextMenuItem
                  onClick={() => handleToggleTooltipPage(page.id, page.page_type)}
                  data-testid={`page-ctx-toggle-tooltip-${page.id}`}
                >
                  <MessageSquare className="h-3.5 w-3.5 mr-2" />
                  {page.page_type === 'tooltip' ? 'Convert to Regular Page' : 'Convert to Tooltip Page'}
                </ContextMenuItem>
                {HAS_STORIES && <ContextMenuItem
                  onClick={() => handleToggleStoryPage(page.id, page.page_type)}
                  data-testid={`page-ctx-toggle-story-${page.id}`}
                >
                  <Presentation className="h-3.5 w-3.5 mr-2" />
                  {page.page_type === 'story' ? 'Convert to Regular Page' : 'Convert to Story Page'}
                </ContextMenuItem>}
                <ContextMenuSeparator />
                <ContextMenuItem
                  onClick={() => handleDeletePage(page.id)}
                  disabled={pages.length <= 1}
                  className="text-destructive focus:text-destructive"
                  data-testid={`page-ctx-delete-${page.id}`}
                >
                  <Trash2 className="h-3.5 w-3.5 mr-2" />
                  Delete Page
                </ContextMenuItem>
              </ContextMenuContent>
            </ContextMenu>
          ))}
          
          {/* Add page button */}
          <Button
            variant="ghost"
            size="sm"
            className="h-7 w-7 p-0"
            data-testid="add-page"
            aria-label="Add page"
            title="Add page"
            onClick={handleAddPage}
          >
            <Plus className="h-3 w-3" />
          </Button>

          {/* Toggle hidden pages visibility */}
          {pages.some(p => p.hidden) && (
            <Button
              variant="ghost"
              size="sm"
              className={cn(
                'h-7 px-2 text-xs gap-1',
                showHiddenPages ? 'text-muted-foreground' : 'text-muted-foreground/50'
              )}
              data-testid="toggle-hidden-pages"
              aria-label={showHiddenPages ? 'Hide hidden pages' : 'Show hidden pages'}
              title={showHiddenPages ? 'Hide hidden pages from tab bar' : 'Show hidden pages in tab bar'}
              onClick={() => setShowHiddenPages(!showHiddenPages)}
            >
              {showHiddenPages ? <Eye className="h-3 w-3" /> : <EyeOff className="h-3 w-3" />}
            </Button>
          )}

          {/* Tooltip pages separator & tabs */}
          {pages.some(p => p.page_type === 'tooltip') && (
            <>
              <div className="w-px h-5 bg-border mx-1" />
              <span className="text-[10px] text-muted-foreground mr-0.5" title="Tooltip pages">
                <MessageSquare className="h-3 w-3 inline" />
              </span>
              {pages.filter(p => p.page_type === 'tooltip').map((page) => (
                <ContextMenu key={page.id}>
                  <ContextMenuTrigger asChild>
                    <Button
                      variant={currentPageId === page.id ? 'secondary' : 'ghost'}
                      size="sm"
                      className={cn(
                        'h-7 px-2 text-xs rounded-sm gap-1 border-dashed border',
                        currentPageId === page.id && 'bg-muted'
                      )}
                      onClick={() => changePage(page.id)}
                      aria-label={`Tooltip page: ${page.title}`}
                      title={`Tooltip: ${page.title}`}
                      data-testid={`page-tab-tooltip-${page.id}`}
                    >
                      <MessageSquare className="h-3 w-3 text-muted-foreground" />
                      <span className="truncate max-w-[100px]">{page.title}</span>
                    </Button>
                  </ContextMenuTrigger>
                  <ContextMenuContent>
                    <ContextMenuItem
                      onClick={() => startRename(page.id, page.title)}
                      data-testid={`page-ctx-rename-${page.id}`}
                    >
                      <Pencil className="h-3.5 w-3.5 mr-2" />
                      Rename
                    </ContextMenuItem>
                    <ContextMenuItem
                      onClick={() => handleToggleTooltipPage(page.id, page.page_type)}
                      data-testid={`page-ctx-toggle-tooltip-${page.id}`}
                    >
                      <MessageSquare className="h-3.5 w-3.5 mr-2" />
                      Convert to Regular Page
                    </ContextMenuItem>
                    <ContextMenuSeparator />
                    <ContextMenuItem
                      onClick={() => handleDeletePage(page.id)}
                      disabled={pages.length <= 1}
                      className="text-destructive focus:text-destructive"
                      data-testid={`page-ctx-delete-${page.id}`}
                    >
                      <Trash2 className="h-3.5 w-3.5 mr-2" />
                      Delete Page
                    </ContextMenuItem>
                  </ContextMenuContent>
                </ContextMenu>
              ))}
            </>
          )}

          {/* Add tooltip page button */}
          <Button
            variant="ghost"
            size="sm"
            className="h-7 px-1.5 text-xs gap-0.5 text-muted-foreground"
            data-testid="add-tooltip-page"
            aria-label="Add tooltip page"
            title="Add tooltip page"
            onClick={handleAddTooltipPage}
          >
            <MessageSquare className="h-3 w-3" />
            <Plus className="h-2.5 w-2.5" />
          </Button>

          {/* Story pages separator & tabs */}
          {HAS_STORIES && pages.some(p => p.page_type === 'story') && (
            <>
              <div className="w-px h-5 bg-border mx-1" />
              <span className="text-[10px] text-muted-foreground mr-0.5" title="Story pages">
                <Presentation className="h-3 w-3 inline" />
              </span>
              {pages.filter(p => p.page_type === 'story').map((page) => (
                <ContextMenu key={page.id}>
                  <ContextMenuTrigger asChild>
                    <Button
                      variant={currentPageId === page.id ? 'secondary' : 'ghost'}
                      size="sm"
                      className={cn(
                        'h-7 px-2 text-xs rounded-sm gap-1 border-dashed border',
                        currentPageId === page.id && 'bg-muted'
                      )}
                      onClick={() => changePage(page.id)}
                      aria-label={`Story page: ${page.title}`}
                      title={`Story: ${page.title}`}
                      data-testid={`page-tab-story-${page.id}`}
                    >
                      <Presentation className="h-3 w-3 text-muted-foreground" />
                      <span className="truncate max-w-[100px]">{page.title}</span>
                    </Button>
                  </ContextMenuTrigger>
                  <ContextMenuContent>
                    <ContextMenuItem
                      onClick={() => startRename(page.id, page.title)}
                      data-testid={`page-ctx-rename-${page.id}`}
                    >
                      <Pencil className="h-3.5 w-3.5 mr-2" />
                      Rename
                    </ContextMenuItem>
                    <ContextMenuItem
                      onClick={() => handleToggleStoryPage(page.id, page.page_type)}
                      data-testid={`page-ctx-toggle-story-${page.id}`}
                    >
                      <Presentation className="h-3.5 w-3.5 mr-2" />
                      Convert to Regular Page
                    </ContextMenuItem>
                    <ContextMenuSeparator />
                    <ContextMenuItem
                      onClick={() => handleDeletePage(page.id)}
                      disabled={pages.length <= 1}
                      className="text-destructive focus:text-destructive"
                      data-testid={`page-ctx-delete-${page.id}`}
                    >
                      <Trash2 className="h-3.5 w-3.5 mr-2" />
                      Delete Page
                    </ContextMenuItem>
                  </ContextMenuContent>
                </ContextMenu>
              ))}
            </>
          )}

          {/* Add story page button */}
          {HAS_STORIES && <Button
            variant="ghost"
            size="sm"
            className="h-7 px-1.5 text-xs gap-0.5 text-muted-foreground"
            data-testid="add-story-page"
            aria-label="Add story page"
            title="Add story page"
            onClick={handleAddStoryPage}
          >
            <Presentation className="h-3 w-3" />
            <Plus className="h-2.5 w-2.5" />
          </Button>}
        </div>
      </div>
      {/* Scroll right arrow — always rendered, disabled when at end */}
      <Button
        variant="ghost"
        size="sm"
        className={cn('h-7 w-6 p-0 shrink-0', !canScrollRight && 'opacity-0 pointer-events-none')}
        onClick={() => scrollBy(150)}
        data-testid="page-tabs-scroll-right"
        aria-label="Scroll tabs right"
        title="Scroll tabs right"
        tabIndex={canScrollRight ? 0 : -1}
      >
        <ChevronRight className="h-3.5 w-3.5" />
      </Button>
    </div>
  )
}

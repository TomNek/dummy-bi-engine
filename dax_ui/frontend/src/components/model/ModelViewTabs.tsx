/**
 * ModelViewTabs — page tabs for the Model View (similar to PageTabs for Report View).
 *
 * Displays tabs for each model view layout/page. Supports:
 * - Switching between layouts
 * - Creating new custom layouts (+ button)
 * - Renaming layouts (double-click)
 * - Deleting custom layouts (right-click → Delete)
 */
import { useCallback, useRef, useState } from 'react'
import { Plus, X } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useModelViewStore } from '@/stores/model-view-store'

export function ModelViewTabs() {
  const layouts = useModelViewStore(s => s.layouts)
  const activeLayoutId = useModelViewStore(s => s.activeLayoutId)
  const setActiveLayout = useModelViewStore(s => s.setActiveLayout)
  const addLayout = useModelViewStore(s => s.addLayout)
  const renameLayout = useModelViewStore(s => s.renameLayout)
  const deleteLayout = useModelViewStore(s => s.deleteLayout)

  // Inline rename state
  const [renamingId, setRenamingId] = useState<string | null>(null)
  const [renameValue, setRenameValue] = useState('')
  const renameInputRef = useRef<HTMLInputElement>(null)

  // Context menu state
  const [contextMenu, setContextMenu] = useState<{
    x: number
    y: number
    layoutId: string
  } | null>(null)

  const handleStartRename = useCallback(
    (id: string, currentName: string) => {
      if (id === 'all') return // Can't rename the built-in
      setRenamingId(id)
      setRenameValue(currentName)
      setTimeout(() => renameInputRef.current?.select(), 0)
    },
    []
  )

  const handleFinishRename = useCallback(() => {
    if (renamingId && renameValue.trim()) {
      renameLayout(renamingId, renameValue.trim())
    }
    setRenamingId(null)
    setRenameValue('')
  }, [renamingId, renameValue, renameLayout])

  const handleAddLayout = useCallback(() => {
    const count = layouts.filter((l) => l.id !== 'all').length + 1
    addLayout(`Layout ${count}`)
  }, [layouts, addLayout])

  const handleContextMenu = useCallback(
    (e: React.MouseEvent, layoutId: string) => {
      if (layoutId === 'all') return // No context menu for built-in
      e.preventDefault()
      setContextMenu({ x: e.clientX, y: e.clientY, layoutId })
    },
    []
  )

  const handleDeleteLayout = useCallback(() => {
    if (contextMenu) {
      deleteLayout(contextMenu.layoutId)
      setContextMenu(null)
    }
  }, [contextMenu, deleteLayout])

  return (
    <>
      <div
        className="flex items-center gap-0.5 px-2 py-1 bg-muted/30 border-t overflow-x-auto shrink-0"
        data-testid="model-view-tabs"
      >
        {layouts.map((layout) => {
          const isActive = layout.id === activeLayoutId
          const isRenaming = renamingId === layout.id

          return (
            <div
              key={layout.id}
              className={cn(
                'flex items-center gap-1 px-3 py-1 text-xs rounded-t cursor-pointer select-none shrink-0',
                'border border-b-0 transition-colors',
                isActive
                  ? 'bg-background text-foreground font-medium border-border'
                  : 'bg-muted/50 text-muted-foreground hover:bg-muted hover:text-foreground border-transparent'
              )}
              onClick={() => setActiveLayout(layout.id)}
              onDoubleClick={() => handleStartRename(layout.id, layout.name)}
              onContextMenu={(e) => handleContextMenu(e, layout.id)}
              data-testid={`model-tab-${layout.id}`}
            >
              {isRenaming ? (
                <input
                  ref={renameInputRef}
                  className="bg-transparent border-b border-primary outline-none text-xs w-24"
                  value={renameValue}
                  onChange={(e) => setRenameValue(e.target.value)}
                  onBlur={handleFinishRename}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') handleFinishRename()
                    if (e.key === 'Escape') {
                      setRenamingId(null)
                      setRenameValue('')
                    }
                  }}
                  onClick={(e) => e.stopPropagation()}
                  autoFocus
                />
              ) : (
                <span className="truncate max-w-[120px]">{layout.name}</span>
              )}

              {/* Close button for custom layouts */}
              {layout.id !== 'all' && !isRenaming && (
                <button
                  className="ml-1 p-0.5 rounded hover:bg-destructive/10 hover:text-destructive opacity-0 group-hover:opacity-100 transition-opacity"
                  onClick={(e) => {
                    e.stopPropagation()
                    deleteLayout(layout.id)
                  }}
                  title="Delete layout"
                  data-testid={`model-tab-close-${layout.id}`}
                >
                  <X className="w-3 h-3" />
                </button>
              )}
            </div>
          )
        })}

        {/* Add layout button */}
        <button
          className="flex items-center gap-1 px-2 py-1 text-xs text-muted-foreground hover:text-foreground hover:bg-muted rounded transition-colors shrink-0"
          onClick={handleAddLayout}
          title="New layout"
          data-testid="model-tab-add"
        >
          <Plus className="w-3.5 h-3.5" />
        </button>
      </div>

      {/* Context menu */}
      {contextMenu && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setContextMenu(null)} />
          <div
            className="fixed z-50 bg-popover border rounded-lg shadow-xl py-1 min-w-[140px]"
            style={{ left: contextMenu.x, top: contextMenu.y }}
            data-testid="model-tab-context-menu"
          >
            <button
              className="w-full text-left px-3 py-1.5 text-sm hover:bg-accent"
              onClick={() => {
                const layout = layouts.find((l) => l.id === contextMenu.layoutId)
                if (layout) handleStartRename(layout.id, layout.name)
                setContextMenu(null)
              }}
            >
              Rename
            </button>
            <button
              className="w-full text-left px-3 py-1.5 text-sm hover:bg-accent text-destructive"
              onClick={handleDeleteLayout}
            >
              Delete
            </button>
          </div>
        </>
      )}
    </>
  )
}

import {
  Save,
  Loader2,
  Undo2,
  Redo2,
  RefreshCw,
  Zap,
  ZapOff,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { 
  Tooltip, 
  TooltipContent, 
  TooltipTrigger 
} from '@/components/ui/tooltip'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { useAppStore } from '@/stores'
import { useRuntimeState, useSaveAll, useUndoRedo, useIsViewer, useVisualRender } from '@/hooks'
import { FileMenu } from '@/components/layout/FileMenu'
import { InsertMenu } from '@/components/layout/InsertMenu'
import { ViewMenu } from '@/components/layout/ViewMenu'
import { ToolsMenu } from '@/components/layout/ToolsMenu'
import { HelpMenu } from '@/components/layout/HelpMenu'
import { MenuBarProvider } from '@/components/layout/MenuBarContext'
import { PRODUCT_NAME } from '@/lib/product'

interface TopbarProps {
  className?: string
}

export function Topbar({ className }: TopbarProps) {
  const projectPath = useAppStore(s => s.projectPath)
  const projectSource = useAppStore(s => s.projectSource)
  const roles = useAppStore(s => s.roles)
  const currentRole = useAppStore(s => s.currentRole)
  const isDirty = useAppStore(s => s.isDirty)
  const saveInProgress = useAppStore(s => s.saveInProgress)

  const { changeRole } = useRuntimeState()
  const { saveAll, canSave } = useSaveAll()
  const { undo, redo, canUndo, canRedo } = useUndoRedo()
  const isViewer = useIsViewer()
  const autoRefresh = useAppStore(s => s.autoRefresh)
  const toggleAutoRefresh = useAppStore(s => s.toggleAutoRefresh)
  const { renderAll } = useVisualRender()

  // Extract project name from path
  const projectName = projectPath 
    ? projectPath.split(/[\\/]/).filter(Boolean).pop() 
    : null
  const projectSourceLabel = projectSource ? ` (${projectSource})` : ''

  return (
    <header
      className={cn(
        'flex h-12 items-center justify-between border-b bg-background px-4',
        className
      )}
      data-testid="topbar"
    >
      {/* Left section: Logo + Menu Bar */}
      <div className="flex items-center gap-1">
        {/* Logo */}
        <div className="flex items-center gap-2 mr-2" data-testid="logo">
          <img src="/app-icon.png" alt={PRODUCT_NAME} className="h-6 w-6" />
          <span className="font-semibold text-sm">{PRODUCT_NAME}</span>
        </div>

        {/* Menu Bar — wrapped in MenuBarProvider for hover-to-switch behavior */}
        <nav className="flex items-center gap-0" data-testid="menu-bar">
          <MenuBarProvider>
            {!isViewer && <FileMenu />}
            {!isViewer && <InsertMenu />}
            <ViewMenu />
            {!isViewer && <ToolsMenu />}
            <HelpMenu />
          </MenuBarProvider>
        </nav>
      </div>

      {/* Center section: Project name + Save + Undo/Redo */}
      <div className="flex items-center gap-3" data-testid="project-info">
        <span className="text-sm text-muted-foreground truncate max-w-[340px]" data-testid="project-label">
          {projectName ? `Project: ${projectName}${projectSourceLabel}` : 'No project loaded'}
        </span>
        
        {/* Dirty indicator (hidden in viewer mode) */}
        {!isViewer && isDirty && (
          <span 
            className="text-xs text-orange-500 font-medium" 
            data-testid="dirty-indicator"
            title="You have unsaved changes. Click Save to persist."
          >
            ● Unsaved changes
          </span>
        )}

        {/* Divider */}
        {!isViewer && <div className="h-5 w-px bg-border" />}
        
        {/* Save button (hidden in viewer mode) */}
        {!isViewer && (
        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              variant="outline"
              size="sm"
              onClick={saveAll}
              disabled={!canSave || saveInProgress}
              data-testid="save-all-btn"
              aria-label="Save all changes"
            >
              {saveInProgress ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Save className="h-4 w-4" />
              )}
              <span className="ml-1 hidden sm:inline">Save</span>
            </Button>
          </TooltipTrigger>
          <TooltipContent>Save all changes</TooltipContent>
        </Tooltip>
        )}

        {/* Undo/Redo buttons (hidden in viewer mode) */}
        {!isViewer && (
        <>
        <div className="h-5 w-px bg-border" />
        <div className="flex items-center gap-1" data-testid="undo-redo">
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant="ghost"
                size="icon"
                onClick={undo}
                disabled={!canUndo}
                data-testid="undo-btn"
                aria-label="Undo last change"
              >
                <Undo2 className="h-4 w-4" />
              </Button>
            </TooltipTrigger>
            <TooltipContent>Undo</TooltipContent>
          </Tooltip>

          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant="ghost"
                size="icon"
                onClick={redo}
                disabled={!canRedo}
                data-testid="redo-btn"
                aria-label="Redo last change"
              >
                <Redo2 className="h-4 w-4" />
              </Button>
            </TooltipTrigger>
            <TooltipContent>Redo</TooltipContent>
          </Tooltip>
        </div>
        </>
        )}

        {/* Refresh / Auto-refresh buttons (hidden in viewer mode) */}
        {!isViewer && (
        <>
        <div className="h-5 w-px bg-border" />
        <div className="flex items-center gap-1" data-testid="refresh-controls">
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant="ghost"
                size="icon"
                onClick={() => renderAll({ force: true })}
                data-testid="refresh-all-btn"
                aria-label="Refresh all visuals"
              >
                <RefreshCw className="h-4 w-4" />
              </Button>
            </TooltipTrigger>
            <TooltipContent>Refresh all visuals</TooltipContent>
          </Tooltip>

          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant={autoRefresh ? 'default' : 'ghost'}
                size="icon"
                onClick={toggleAutoRefresh}
                data-testid="auto-refresh-btn"
                aria-label={autoRefresh ? 'Disable auto-refresh' : 'Enable auto-refresh'}
              >
                {autoRefresh ? (
                  <Zap className="h-4 w-4" />
                ) : (
                  <ZapOff className="h-4 w-4" />
                )}
              </Button>
            </TooltipTrigger>
            <TooltipContent>
              {autoRefresh ? 'Auto-refresh ON — click to pause' : 'Auto-refresh OFF — click to resume'}
            </TooltipContent>
          </Tooltip>
        </div>
        </>
        )}
      </div>

      {/* Right section: Role selector */}
      <div className="flex items-center gap-3">
        {roles.length > 0 && (
          <div className="flex items-center gap-2" data-testid="role-selector">
            <span className="text-xs text-muted-foreground">Role:</span>
            <Select 
              value={currentRole || '__none__'} 
              onValueChange={(value) => changeRole(value === '__none__' ? null : value)}
            >
              <SelectTrigger className="w-[140px] h-8 text-xs" data-testid="role-select" aria-label="Select security role">
                <SelectValue placeholder="No role" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="__none__" data-testid="role-option">Default (full access)</SelectItem>
                {roles.map((role) => (
                  <SelectItem key={role.name} value={role.name} data-testid="role-option">
                    {role.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        )}
      </div>
    </header>
  )
}

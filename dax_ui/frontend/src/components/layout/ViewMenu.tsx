import { useEffect } from 'react'
import {
  LayoutDashboard,
  Table2,
  Database,
  PanelLeft,
  PanelRight,
  Maximize2,
  Minimize2,
  Palette,
  Sun,
  Moon,
  Monitor,
  Timer,
  Sparkles,
  Check,
  Eye,
  Presentation,
  FileCode2,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { useMenuBar } from '@/components/layout/MenuBarContext'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
  DropdownMenuSeparator,
  DropdownMenuLabel,
  DropdownMenuSub,
  DropdownMenuSubTrigger,
  DropdownMenuSubContent,
} from '@/components/ui/dropdown-menu'
import { useAppStore, useReportStore } from '@/stores'
import { useTheme } from '@/hooks'
import { useRuntimeState } from '@/hooks'
import { usePerfStore } from '@/stores/perf-store'
import { useDaxAnalyzerStore } from '@/stores/dax-analyzer-store'
import { ReportingThemeEditor } from '@/components/settings/ReportingThemeEditor'
import { useState } from 'react'
import { HAS_STORIES, HAS_TRANSFORM_STUDIO } from '@/lib/edition'

export function ViewMenu() {
  const menuBar = useMenuBar('view')
  const viewMode = useAppStore(s => s.viewMode)
  const leftSidebarOpen = useAppStore(s => s.leftSidebarOpen)
  const rightSidebarOpen = useAppStore(s => s.rightSidebarOpen)
  const interactionSidebarOpen = useAppStore(s => s.interactionSidebarOpen)
  const isFullView = useAppStore(s => s.isFullView)
  const setViewMode = useAppStore(s => s.setViewMode)
  const setFullView = useAppStore(s => s.setFullView)
  const toggleLeftSidebar = useAppStore(s => s.toggleLeftSidebar)
  const toggleRightSidebar = useAppStore(s => s.toggleRightSidebar)
  const toggleInteractionSidebar = useAppStore(s => s.toggleInteractionSidebar)
  const { theme, setTheme } = useTheme()
  const perfOpen = usePerfStore(s => s.isOpen)
  const daxOpen = useDaxAnalyzerStore(s => s.isOpen)
  const [themeEditorOpen, setThemeEditorOpen] = useState(false)
  const pages = useReportStore(s => s.pages)
  const addPage = useReportStore(s => s.addPage)
  const setDirty = useAppStore(s => s.setDirty)
  const { changePage } = useRuntimeState()

  const storyPages = pages.filter(p => p.page_type === 'story')

  const handleAddStoryPage = () => {
    const id = `story_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`
    addPage({ id, title: `Story ${storyPages.length + 1}`, order: pages.length + 1, page_type: 'story' })
    changePage(id)
    setDirty(true)
  }

  // Ctrl+Shift+F keyboard shortcut for full-view toggle
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.ctrlKey && e.shiftKey && e.key === 'F') {
        e.preventDefault()
        setFullView(!isFullView)
      }
    }
    document.addEventListener('keydown', handleKeyDown)
    return () => document.removeEventListener('keydown', handleKeyDown)
  }, [isFullView, setFullView])

  return (
    <>
      <DropdownMenu modal={false} onOpenChange={menuBar?.onOpenChange}>
        <DropdownMenuTrigger asChild>
          <Button
            ref={menuBar?.triggerRef}
            variant="ghost"
            size="sm"
            data-testid="view-menu-trigger"
            aria-label="View menu"
            onMouseEnter={menuBar?.onTriggerMouseEnter}
          >
            <Eye className="h-4 w-4 mr-1" />
            <span>View</span>
          </Button>
        </DropdownMenuTrigger>

        <DropdownMenuContent align="start" className="w-56" data-testid="view-menu">
          {/* View Modes */}
          <DropdownMenuLabel>View Mode</DropdownMenuLabel>
          <DropdownMenuSeparator />

          <DropdownMenuItem
            onClick={() => setViewMode('report')}
            data-testid="view-menu-report"
          >
            <LayoutDashboard className="h-4 w-4 mr-2" />
            Report View
            {viewMode === 'report' && <Check className="h-4 w-4 ml-auto" />}
          </DropdownMenuItem>

          <DropdownMenuItem
            onClick={() => setViewMode('data')}
            data-testid="view-menu-data"
          >
            <Table2 className="h-4 w-4 mr-2" />
            Data View
            {viewMode === 'data' && <Check className="h-4 w-4 ml-auto" />}
          </DropdownMenuItem>

          <DropdownMenuItem
            onClick={() => setViewMode('model')}
            data-testid="view-menu-model"
          >
            <Database className="h-4 w-4 mr-2" />
            Model View
            {viewMode === 'model' && <Check className="h-4 w-4 ml-auto" />}
          </DropdownMenuItem>

          {HAS_TRANSFORM_STUDIO && <DropdownMenuItem
            onClick={() => setViewMode('transform')}
            data-testid="view-menu-transform"
          >
            <FileCode2 className="h-4 w-4 mr-2" />
            Transform View
            {viewMode === 'transform' && <Check className="h-4 w-4 ml-auto" />}
          </DropdownMenuItem>}

          <DropdownMenuSeparator />
          <DropdownMenuLabel>Panels</DropdownMenuLabel>
          <DropdownMenuSeparator />

          <DropdownMenuItem
            onClick={toggleLeftSidebar}
            data-testid="view-menu-left-sidebar"
          >
            <PanelLeft className="h-4 w-4 mr-2" />
            Left Sidebar
            {leftSidebarOpen && <Check className="h-4 w-4 ml-auto" />}
          </DropdownMenuItem>

          <DropdownMenuItem
            onClick={toggleRightSidebar}
            data-testid="view-menu-right-sidebar"
          >
            <PanelRight className="h-4 w-4 mr-2" />
            Right Sidebar
            {rightSidebarOpen && <Check className="h-4 w-4 ml-auto" />}
          </DropdownMenuItem>

          <DropdownMenuItem
            onClick={toggleInteractionSidebar}
            data-testid="view-menu-interaction-sidebar"
          >
            <PanelRight className="h-4 w-4 mr-2" />
            Interaction Sidebar
            {interactionSidebarOpen && <Check className="h-4 w-4 ml-auto" />}
          </DropdownMenuItem>

          <DropdownMenuItem
            onClick={() => setFullView(!isFullView)}
            data-testid="view-menu-full-view"
          >
            {isFullView ? (
              <Minimize2 className="h-4 w-4 mr-2" />
            ) : (
              <Maximize2 className="h-4 w-4 mr-2" />
            )}
            Full View
            <span className="ml-auto text-xs text-muted-foreground">Ctrl+Shift+F</span>
          </DropdownMenuItem>

          {HAS_STORIES && <>
          <DropdownMenuSeparator />
          <DropdownMenuLabel>Stories</DropdownMenuLabel>
          <DropdownMenuSeparator />

          {storyPages.map((sp) => (
            <DropdownMenuItem
              key={sp.id}
              onClick={() => { setViewMode('report'); changePage(sp.id) }}
              data-testid={`view-menu-story-${sp.id}`}
            >
              <Presentation className="h-4 w-4 mr-2" />
              {sp.title}
            </DropdownMenuItem>
          ))}

          <DropdownMenuItem
            onClick={handleAddStoryPage}
            data-testid="view-menu-add-story-page"
          >
            <Presentation className="h-4 w-4 mr-2" />
            New Story Page…
          </DropdownMenuItem>
          </>}

          <DropdownMenuSeparator />
          <DropdownMenuLabel>Appearance</DropdownMenuLabel>
          <DropdownMenuSeparator />

          <DropdownMenuItem
            onClick={() => setThemeEditorOpen(true)}
            data-testid="view-menu-theme-editor"
          >
            <Palette className="h-4 w-4 mr-2" />
            Reporting Theme…
          </DropdownMenuItem>

          <DropdownMenuSub>
            <DropdownMenuSubTrigger data-testid="view-menu-appearance">
              {theme === 'dark' ? (
                <Moon className="h-4 w-4 mr-2" />
              ) : theme === 'light' ? (
                <Sun className="h-4 w-4 mr-2" />
              ) : (
                <Monitor className="h-4 w-4 mr-2" />
              )}
              Appearance
            </DropdownMenuSubTrigger>
            <DropdownMenuSubContent>
              <DropdownMenuItem
                onClick={() => setTheme('light')}
                data-testid="view-menu-theme-light"
              >
                <Sun className="h-4 w-4 mr-2" />
                Light
                {theme === 'light' && <Check className="h-4 w-4 ml-auto" />}
              </DropdownMenuItem>
              <DropdownMenuItem
                onClick={() => setTheme('dark')}
                data-testid="view-menu-theme-dark"
              >
                <Moon className="h-4 w-4 mr-2" />
                Dark
                {theme === 'dark' && <Check className="h-4 w-4 ml-auto" />}
              </DropdownMenuItem>
              <DropdownMenuItem
                onClick={() => setTheme('system')}
                data-testid="view-menu-theme-system"
              >
                <Monitor className="h-4 w-4 mr-2" />
                System
                {theme === 'system' && <Check className="h-4 w-4 ml-auto" />}
              </DropdownMenuItem>
            </DropdownMenuSubContent>
          </DropdownMenuSub>

          <DropdownMenuSeparator />
          <DropdownMenuLabel>Analyzers</DropdownMenuLabel>
          <DropdownMenuSeparator />

          <DropdownMenuItem
            onClick={() => usePerfStore.getState().toggle()}
            data-testid="view-menu-perf-analyzer"
          >
            <Timer className="h-4 w-4 mr-2" />
            Performance Analyzer
            {perfOpen && <Check className="h-4 w-4 ml-auto" />}
          </DropdownMenuItem>

          <DropdownMenuItem
            onClick={() => useDaxAnalyzerStore.getState().toggle()}
            data-testid="view-menu-dax-analyzer"
          >
            <Sparkles className="h-4 w-4 mr-2" />
            DAX Analyzer
            {daxOpen && <Check className="h-4 w-4 ml-auto" />}
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>

      {/* Reporting Theme Editor Dialog */}
      <ReportingThemeEditor open={themeEditorOpen} onOpenChange={setThemeEditorOpen} />
    </>
  )
}

import { useState, useCallback, useEffect, useRef } from 'react'
import {
  Menu,
  FolderOpen,
  FolderPlus,
  Save,
  SaveAll,
  Download,
  Upload,
  Database,
  RefreshCw,
  X,
  Clock,
  ChevronRight,
  Folder,
  ArrowUp,
  Loader2,
  Trash2,
  FileBarChart,
  Palette,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
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
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { ScrollArea } from '@/components/ui/scroll-area'
import { useAppStore, useReportStore, useFilterStore } from '@/stores'
import { useRuntimeState, useSaveAll } from '@/hooks'
import { useMenuBar } from '@/components/layout/MenuBarContext'
import { toast } from '@/components/ui/toast'
import {
  getRecentProjects,
  addRecentProject,
  removeRecentProject,
  browseDirectories,
  createProject,
  saveProjectAs,
  getProjectExportUrl,
  importProjectZip,
  refreshProjectData,
  type RecentProject,
  type DirectoryItem,
} from '@/lib/api'
import { TmdlImportWizard } from '@/components/model/TmdlImportWizard'
import { ReportImportWizard } from '@/components/model/ReportImportWizard'
import { ThemeImportWizard } from '@/components/model/ThemeImportWizard'
import { HAS_POWER_BI_IMPORT } from '@/lib/edition'

// ─── Open Project Dialog ─────────────────────────────────────────────
function OpenProjectDialog({
  open,
  onOpenChange,
  onProjectSelected,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  onProjectSelected: (projectPath: string) => void
}) {
  const [recentProjects, setRecentProjects] = useState<RecentProject[]>([])
  const [currentDir, setCurrentDir] = useState<string>('')
  const [dirItems, setDirItems] = useState<DirectoryItem[]>([])
  const [loading, setLoading] = useState(false)
  const [tab, setTab] = useState<'recent' | 'browse'>('recent')
  const [pathInput, setPathInput] = useState('')

  // Load recent projects when dialog opens
  useEffect(() => {
    if (!open) return
    getRecentProjects().then((res) => {
      if (res.data?.projects) setRecentProjects(res.data.projects)
    })
    // Also load initial directory listing
    browseDirectories().then((res) => {
      if (res.data) {
        setCurrentDir(res.data.current)
        setDirItems(res.data.items)
        setPathInput(res.data.current)
      }
    })
  }, [open])

  const navigateTo = useCallback(async (path: string) => {
    setLoading(true)
    try {
      const res = await browseDirectories(path)
      if (res.data) {
        setCurrentDir(res.data.current)
        setDirItems(res.data.items)
        setPathInput(res.data.current)
      } else if (res.error) {
        toast(res.error, { variant: 'error' })
      }
    } finally {
      setLoading(false)
    }
  }, [])

  const goUp = useCallback(() => {
    const parent = currentDir.replace(/[\\/][^\\/]+$/, '') || currentDir
    if (parent !== currentDir) navigateTo(parent)
  }, [currentDir, navigateTo])

  const handlePathSubmit = useCallback(() => {
    if (pathInput.trim()) navigateTo(pathInput.trim())
  }, [pathInput, navigateTo])

  const selectProject = useCallback((path: string) => {
    onProjectSelected(path)
    onOpenChange(false)
  }, [onProjectSelected, onOpenChange])

  const handleRemoveRecent = useCallback(async (path: string, e: React.MouseEvent) => {
    e.stopPropagation()
    const res = await removeRecentProject(path)
    if (res.data?.projects) setRecentProjects(res.data.projects)
  }, [])

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl max-h-[80vh]" data-testid="open-project-dialog">
        <DialogHeader>
          <DialogTitle>Open Project</DialogTitle>
          <DialogDescription>Select a project folder or choose from recent projects</DialogDescription>
        </DialogHeader>

        {/* Tab switcher */}
        <div className="flex gap-2 border-b pb-2">
          <Button
            variant={tab === 'recent' ? 'secondary' : 'ghost'}
            size="sm"
            onClick={() => setTab('recent')}
            data-testid="open-tab-recent"
          >
            <Clock className="h-4 w-4 mr-1" />
            Recent
          </Button>
          <Button
            variant={tab === 'browse' ? 'secondary' : 'ghost'}
            size="sm"
            onClick={() => setTab('browse')}
            data-testid="open-tab-browse"
          >
            <FolderOpen className="h-4 w-4 mr-1" />
            Browse
          </Button>
        </div>

        {tab === 'recent' ? (
          <ScrollArea className="h-[400px]">
            {recentProjects.length === 0 ? (
              <div className="flex items-center justify-center h-full text-muted-foreground text-sm">
                No recent projects
              </div>
            ) : (
              <div className="space-y-1">
                {recentProjects.map((rp) => (
                  <div
                    key={rp.path}
                    className="flex items-center justify-between p-2 rounded-md hover:bg-accent cursor-pointer group"
                    onClick={() => selectProject(rp.path)}
                    data-testid="recent-project-item"
                  >
                    <div className="flex items-center gap-2 min-w-0">
                      <Folder className="h-4 w-4 text-muted-foreground shrink-0" />
                      <div className="min-w-0">
                        <div className="text-sm font-medium truncate">{rp.name}</div>
                        <div className="text-xs text-muted-foreground truncate">{rp.path}</div>
                      </div>
                    </div>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-6 w-6 opacity-0 group-hover:opacity-100"
                      onClick={(e) => handleRemoveRecent(rp.path, e)}
                      data-testid="remove-recent-btn"
                      aria-label="Remove from recent"
                    >
                      <Trash2 className="h-3 w-3" />
                    </Button>
                  </div>
                ))}
              </div>
            )}
          </ScrollArea>
        ) : (
          <div className="space-y-2">
            {/* Path bar */}
            <div className="flex gap-2">
              <Button variant="outline" size="icon" onClick={goUp} data-testid="browse-up-btn">
                <ArrowUp className="h-4 w-4" />
              </Button>
              <Input
                value={pathInput}
                onChange={(e) => setPathInput(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && handlePathSubmit()}
                placeholder="Enter directory path..."
                className="flex-1"
                data-testid="browse-path-input"
              />
              <Button variant="outline" size="sm" onClick={handlePathSubmit}>
                Go
              </Button>
            </div>

            {/* Directory listing */}
            <ScrollArea className="h-[350px] border rounded-md">
              {loading ? (
                <div className="flex items-center justify-center h-full">
                  <Loader2 className="h-6 w-6 animate-spin" />
                </div>
              ) : (
                <div className="p-1">
                  {dirItems.map((item) => (
                    <div
                      key={item.path}
                      className={`flex items-center justify-between p-2 rounded-md hover:bg-accent cursor-pointer ${
                        item.is_project ? 'border-l-2 border-primary' : ''
                      }`}
                      onClick={() =>
                        item.is_project ? selectProject(item.path) : navigateTo(item.path)
                      }
                      data-testid="browse-dir-item"
                    >
                      <div className="flex items-center gap-2">
                        <Folder className={`h-4 w-4 ${item.is_project ? 'text-primary' : 'text-muted-foreground'}`} />
                        <span className="text-sm">{item.name}</span>
                        {item.is_project && (
                          <span className="text-[10px] bg-primary/10 text-primary px-1.5 py-0.5 rounded">
                            Project
                          </span>
                        )}
                      </div>
                      {!item.is_project && (
                        <ChevronRight className="h-4 w-4 text-muted-foreground" />
                      )}
                    </div>
                  ))}
                  {dirItems.length === 0 && (
                    <div className="text-center text-sm text-muted-foreground py-8">
                      No subdirectories found
                    </div>
                  )}
                </div>
              )}
            </ScrollArea>
          </div>
        )}

        <DialogFooter>
          {tab === 'browse' && (
            <Button
              variant="secondary"
              onClick={() => selectProject(currentDir)}
              data-testid="open-current-dir-btn"
            >
              Open Current Directory
            </Button>
          )}
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

// ─── New Project Dialog ──────────────────────────────────────────────
function NewProjectDialog({
  open,
  onOpenChange,
  onProjectCreated,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  onProjectCreated: (projectPath: string) => void
}) {
  const [parentDir, setParentDir] = useState('')
  const [projectName, setProjectName] = useState('')
  const [creating, setCreating] = useState(false)
  const [dirItems, setDirItems] = useState<DirectoryItem[]>([])
  const [currentDir, setCurrentDir] = useState('')

  useEffect(() => {
    if (!open) return
    browseDirectories().then((res) => {
      if (res.data) {
        setCurrentDir(res.data.current)
        setParentDir(res.data.current)
        setDirItems(res.data.items)
      }
    })
    setProjectName('')
  }, [open])

  const navigateTo = useCallback(async (path: string) => {
    const res = await browseDirectories(path)
    if (res.data) {
      setCurrentDir(res.data.current)
      setParentDir(res.data.current)
      setDirItems(res.data.items)
    }
  }, [])

  const goUp = useCallback(() => {
    const parent = currentDir.replace(/[\\/][^\\/]+$/, '') || currentDir
    if (parent !== currentDir) navigateTo(parent)
  }, [currentDir, navigateTo])

  const handleCreate = useCallback(async () => {
    if (!projectName.trim()) {
      toast('Please enter a project name', { variant: 'error' })
      return
    }
    const sep = parentDir.includes('/') ? '/' : '\\'
    const targetPath = `${parentDir}${sep}${projectName.trim()}`
    setCreating(true)
    try {
      const res = await createProject(targetPath, projectName.trim())
      if (res.error) {
        toast(res.error, { variant: 'error' })
        return
      }
      if (res.data) {
        toast(`Project "${res.data.name}" created`, { variant: 'success' })
        onProjectCreated(res.data.project)
        onOpenChange(false)
      }
    } finally {
      setCreating(false)
    }
  }, [parentDir, projectName, onProjectCreated, onOpenChange])

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-xl" data-testid="new-project-dialog">
        <DialogHeader>
          <DialogTitle>New Project</DialogTitle>
          <DialogDescription>Create a new DAX Engine project with scaffolded structure</DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          {/* Project name */}
          <div>
            <label className="text-sm font-medium mb-1 block">Project Name</label>
            <Input
              value={projectName}
              onChange={(e) => setProjectName(e.target.value)}
              placeholder="My Project"
              data-testid="new-project-name"
              onKeyDown={(e) => e.key === 'Enter' && handleCreate()}
            />
          </div>

          {/* Location picker */}
          <div>
            <label className="text-sm font-medium mb-1 block">Location</label>
            <div className="flex gap-2">
              <Button variant="outline" size="icon" onClick={goUp}>
                <ArrowUp className="h-4 w-4" />
              </Button>
              <Input
                value={parentDir}
                onChange={(e) => setParentDir(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && navigateTo(parentDir)}
                className="flex-1"
                data-testid="new-project-location"
              />
            </div>
          </div>

          {/* Directory browser */}
          <ScrollArea className="h-[200px] border rounded-md">
            <div className="p-1">
              {dirItems.filter((d) => !d.is_project).map((item) => (
                <div
                  key={item.path}
                  className="flex items-center gap-2 p-2 rounded-md hover:bg-accent cursor-pointer"
                  onClick={() => navigateTo(item.path)}
                  data-testid="new-project-dir-item"
                >
                  <Folder className="h-4 w-4 text-muted-foreground" />
                  <span className="text-sm">{item.name}</span>
                </div>
              ))}
            </div>
          </ScrollArea>

          {/* Preview */}
          {projectName.trim() && (
            <div className="text-xs text-muted-foreground">
              Will create: <code className="bg-muted px-1 py-0.5 rounded">
                {parentDir}{parentDir.includes('/') ? '/' : '\\'}{projectName.trim()}
              </code>
            </div>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button onClick={handleCreate} disabled={creating || !projectName.trim()} data-testid="create-project-btn">
            {creating ? <Loader2 className="h-4 w-4 animate-spin mr-1" /> : <FolderPlus className="h-4 w-4 mr-1" />}
            Create Project
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

// ─── Save As Dialog ──────────────────────────────────────────────────
function SaveAsDialog({
  open,
  onOpenChange,
  onSaved,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  onSaved: (projectPath: string) => void
}) {
  const projectPath = useAppStore((s) => s.projectPath)
  const [targetPath, setTargetPath] = useState('')
  const [saving, setSaving] = useState(false)
  const [currentDir, setCurrentDir] = useState('')
  const [dirItems, setDirItems] = useState<DirectoryItem[]>([])

  useEffect(() => {
    if (!open) return
    // Start browsing from the parent of the current project
    const parentDir = (projectPath || '').replace(/[\\/][^\\/]+$/, '')
    browseDirectories(parentDir || undefined).then((res) => {
      if (res.data) {
        setCurrentDir(res.data.current)
        setDirItems(res.data.items)
      }
    })
    setTargetPath('')
  }, [open, projectPath])

  const navigateTo = useCallback(async (path: string) => {
    const res = await browseDirectories(path)
    if (res.data) {
      setCurrentDir(res.data.current)
      setDirItems(res.data.items)
    }
  }, [])

  const goUp = useCallback(() => {
    const parent = currentDir.replace(/[\\/][^\\/]+$/, '') || currentDir
    if (parent !== currentDir) navigateTo(parent)
  }, [currentDir, navigateTo])

  const handleSave = useCallback(async () => {
    if (!targetPath.trim() || !projectPath) return
    const sep = currentDir.includes('/') ? '/' : '\\'
    const fullTarget = `${currentDir}${sep}${targetPath.trim()}`
    setSaving(true)
    try {
      const res = await saveProjectAs(projectPath, fullTarget)
      if (res.error) {
        toast(res.error, { variant: 'error' })
        return
      }
      if (res.data) {
        toast(`Project saved as "${res.data.name}"`, { variant: 'success' })
        onSaved(res.data.project)
        onOpenChange(false)
      }
    } finally {
      setSaving(false)
    }
  }, [projectPath, targetPath, currentDir, onSaved, onOpenChange])

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-xl" data-testid="save-as-dialog">
        <DialogHeader>
          <DialogTitle>Save Project As</DialogTitle>
          <DialogDescription>Save a copy of the current project to a new location</DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          {/* Current location */}
          <div className="flex gap-2">
            <Button variant="outline" size="icon" onClick={goUp}>
              <ArrowUp className="h-4 w-4" />
            </Button>
            <Input
              value={currentDir}
              onChange={(e) => setCurrentDir(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && navigateTo(currentDir)}
              className="flex-1"
              data-testid="save-as-location"
            />
          </div>

          {/* Directory browser */}
          <ScrollArea className="h-[200px] border rounded-md">
            <div className="p-1">
              {dirItems.filter((d) => !d.is_project).map((item) => (
                <div
                  key={item.path}
                  className="flex items-center gap-2 p-2 rounded-md hover:bg-accent cursor-pointer"
                  onClick={() => navigateTo(item.path)}
                >
                  <Folder className="h-4 w-4 text-muted-foreground" />
                  <span className="text-sm">{item.name}</span>
                </div>
              ))}
            </div>
          </ScrollArea>

          {/* New name */}
          <div>
            <label className="text-sm font-medium mb-1 block">New Project Name</label>
            <Input
              value={targetPath}
              onChange={(e) => setTargetPath(e.target.value)}
              placeholder="my_project_copy"
              data-testid="save-as-name"
              onKeyDown={(e) => e.key === 'Enter' && handleSave()}
            />
          </div>

          {targetPath.trim() && (
            <div className="text-xs text-muted-foreground">
              Will save to: <code className="bg-muted px-1 py-0.5 rounded">
                {currentDir}{currentDir.includes('/') ? '/' : '\\'}{targetPath.trim()}
              </code>
            </div>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button onClick={handleSave} disabled={saving || !targetPath.trim()} data-testid="save-as-btn">
            {saving ? <Loader2 className="h-4 w-4 animate-spin mr-1" /> : <Save className="h-4 w-4 mr-1" />}
            Save As
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

// ─── Import Project Dialog ───────────────────────────────────────────
function ImportProjectDialog({
  open,
  onOpenChange,
  onImported,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  onImported: (projectPath: string) => void
}) {
  const [currentDir, setCurrentDir] = useState('')
  const [dirItems, setDirItems] = useState<DirectoryItem[]>([])
  const [targetName, setTargetName] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [importing, setImporting] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (!open) return
    browseDirectories().then((res) => {
      if (res.data) {
        setCurrentDir(res.data.current)
        setDirItems(res.data.items)
      }
    })
    setFile(null)
    setTargetName('')
  }, [open])

  const navigateTo = useCallback(async (path: string) => {
    const res = await browseDirectories(path)
    if (res.data) {
      setCurrentDir(res.data.current)
      setDirItems(res.data.items)
    }
  }, [])

  const goUp = useCallback(() => {
    const parent = currentDir.replace(/[\\/][^\\/]+$/, '') || currentDir
    if (parent !== currentDir) navigateTo(parent)
  }, [currentDir, navigateTo])

  const handleImport = useCallback(async () => {
    if (!file || !targetName.trim()) return
    const sep = currentDir.includes('/') ? '/' : '\\'
    const fullTarget = `${currentDir}${sep}${targetName.trim()}`
    setImporting(true)
    try {
      const res = await importProjectZip(file, fullTarget)
      if (res.error) {
        toast(res.error, { variant: 'error' })
        return
      }
      if (res.data) {
        toast(`Project "${res.data.name}" imported`, { variant: 'success' })
        onImported(res.data.project)
        onOpenChange(false)
      }
    } finally {
      setImporting(false)
    }
  }, [file, targetName, currentDir, onImported, onOpenChange])

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-xl" data-testid="import-project-dialog">
        <DialogHeader>
          <DialogTitle>Import Project from ZIP</DialogTitle>
          <DialogDescription>Upload a project archive and extract it to a folder</DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          {/* File picker */}
          <div>
            <label className="text-sm font-medium mb-1 block">ZIP File</label>
            <div className="flex gap-2">
              <Button
                variant="outline"
                onClick={() => fileInputRef.current?.click()}
                data-testid="import-file-btn"
              >
                <Upload className="h-4 w-4 mr-1" />
                {file ? file.name : 'Choose File...'}
              </Button>
              <input
                ref={fileInputRef}
                type="file"
                accept=".zip"
                className="hidden"
                onChange={(e) => {
                  const f = e.target.files?.[0]
                  if (f) {
                    setFile(f)
                    if (!targetName) setTargetName(f.name.replace(/\.zip$/i, ''))
                  }
                }}
              />
            </div>
          </div>

          {/* Target location */}
          <div>
            <label className="text-sm font-medium mb-1 block">Extract To</label>
            <div className="flex gap-2">
              <Button variant="outline" size="icon" onClick={goUp}>
                <ArrowUp className="h-4 w-4" />
              </Button>
              <Input
                value={currentDir}
                onChange={(e) => setCurrentDir(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && navigateTo(currentDir)}
                className="flex-1"
              />
            </div>
          </div>

          {/* Directory browser */}
          <ScrollArea className="h-[150px] border rounded-md">
            <div className="p-1">
              {dirItems.filter((d) => !d.is_project).map((item) => (
                <div
                  key={item.path}
                  className="flex items-center gap-2 p-2 rounded-md hover:bg-accent cursor-pointer"
                  onClick={() => navigateTo(item.path)}
                >
                  <Folder className="h-4 w-4 text-muted-foreground" />
                  <span className="text-sm">{item.name}</span>
                </div>
              ))}
            </div>
          </ScrollArea>

          {/* Folder name */}
          <div>
            <label className="text-sm font-medium mb-1 block">Project Folder Name</label>
            <Input
              value={targetName}
              onChange={(e) => setTargetName(e.target.value)}
              placeholder="imported_project"
              data-testid="import-target-name"
            />
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button onClick={handleImport} disabled={importing || !file || !targetName.trim()} data-testid="import-confirm-btn">
            {importing ? <Loader2 className="h-4 w-4 animate-spin mr-1" /> : <Upload className="h-4 w-4 mr-1" />}
            Import
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

// ─── Main FileMenu Component ─────────────────────────────────────────
export function FileMenu() {
  const menuBar = useMenuBar('file')
  const projectPath = useAppStore((s) => s.projectPath)
  const isDirty = useAppStore((s) => s.isDirty)
  const saveInProgress = useAppStore((s) => s.saveInProgress)
  const { saveAll, canSave } = useSaveAll()
  const { loadState } = useRuntimeState()

  const [openDialogOpen, setOpenDialogOpen] = useState(false)
  const [newDialogOpen, setNewDialogOpen] = useState(false)
  const [saveAsDialogOpen, setSaveAsDialogOpen] = useState(false)
  const [importDialogOpen, setImportDialogOpen] = useState(false)
  const [tmdlImportOpen, setTmdlImportOpen] = useState(false)
  const [reportImportOpen, setReportImportOpen] = useState(false)
  const [themeImportOpen, setThemeImportOpen] = useState(false)
  const [recentProjects, setRecentProjects] = useState<RecentProject[]>([])
  const [refreshing, setRefreshing] = useState(false)

  // Load recent projects for the submenu
  const loadRecent = useCallback(async () => {
    const res = await getRecentProjects()
    if (res.data?.projects) setRecentProjects(res.data.projects)
  }, [])

  // Switch to a project (used by Open, New, Import, Save As)
  const switchToProject = useCallback(async (path: string) => {
    // Add to recent projects
    await addRecentProject(path)

    // Update URL and load state
    const url = new URL(window.location.href)
    url.searchParams.set('project', path)
    window.history.replaceState(null, '', url.toString())

    useAppStore.getState().setProjectPath(path)
    useAppStore.getState().setProjectSource('manual')
    useAppStore.getState().setProjectError(null)

    await loadState({ project: path, projectSource: 'manual' })
  }, [loadState])

  // Export project as ZIP
  const handleExport = useCallback(() => {
    if (!projectPath) return
    const url = getProjectExportUrl(projectPath)
    // Trigger download via hidden link
    const a = document.createElement('a')
    a.href = url
    a.download = ''
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    toast('Project export started', { variant: 'success' })
  }, [projectPath])

  // Close project
  const handleCloseProject = useCallback(() => {
    useAppStore.getState().reset()
    useReportStore.getState().setPages([])
    useReportStore.getState().setVisuals([])
    useFilterStore.getState().clearFilters()

    // Clear URL project param
    const url = new URL(window.location.href)
    url.searchParams.delete('project')
    window.history.replaceState(null, '', url.toString())

    // Show project picker
    useAppStore.getState().setProjectError('Project closed. Select a project to continue.')
  }, [])

  // Refresh data
  const handleRefresh = useCallback(async () => {
    if (!projectPath) return
    setRefreshing(true)
    try {
      const res = await refreshProjectData(projectPath)
      if (res.error) {
        toast(res.error, { variant: 'error' })
      } else {
        toast('Data refreshed', { variant: 'success' })
        // Reload project state to pick up fresh data
        await loadState({})
      }
    } finally {
      setRefreshing(false)
    }
  }, [projectPath, loadState])

  return (
    <>
      <DropdownMenu modal={false} onOpenChange={(open) => { menuBar?.onOpenChange(open); if (open) loadRecent() }}>
        <Tooltip>
          <TooltipTrigger asChild>
            <DropdownMenuTrigger asChild>
              <Button
                ref={menuBar?.triggerRef}
                variant="ghost"
                size="sm"
                data-testid="file-menu-trigger"
                aria-label="File menu"
                onMouseEnter={menuBar?.onTriggerMouseEnter}
              >
                <Menu className="h-4 w-4" />
                <span className="ml-1 hidden sm:inline">File</span>
              </Button>
            </DropdownMenuTrigger>
          </TooltipTrigger>
          <TooltipContent>File operations</TooltipContent>
        </Tooltip>

        <DropdownMenuContent align="start" className="w-56" data-testid="file-menu">
          {/* New Project */}
          <DropdownMenuItem
            onClick={() => setNewDialogOpen(true)}
            data-testid="file-menu-new"
          >
            <FolderPlus className="h-4 w-4 mr-2" />
            New Project
            <span className="ml-auto text-xs text-muted-foreground">Ctrl+Shift+N</span>
          </DropdownMenuItem>

          {/* Open Project */}
          <DropdownMenuItem
            onClick={() => setOpenDialogOpen(true)}
            data-testid="file-menu-open"
          >
            <FolderOpen className="h-4 w-4 mr-2" />
            Open Project
            <span className="ml-auto text-xs text-muted-foreground">Ctrl+O</span>
          </DropdownMenuItem>

          {/* Recent Projects submenu */}
          <DropdownMenuSub>
            <DropdownMenuSubTrigger data-testid="file-menu-recent">
              <Clock className="h-4 w-4 mr-2" />
              Open Recent
            </DropdownMenuSubTrigger>
            <DropdownMenuSubContent className="w-72">
              {recentProjects.length === 0 ? (
                <DropdownMenuItem disabled>
                  <span className="text-muted-foreground text-xs">No recent projects</span>
                </DropdownMenuItem>
              ) : (
                recentProjects.slice(0, 10).map((rp) => (
                  <DropdownMenuItem
                    key={rp.path}
                    onClick={() => switchToProject(rp.path)}
                    data-testid="file-menu-recent-item"
                  >
                    <Folder className="h-4 w-4 mr-2 shrink-0" />
                    <div className="min-w-0">
                      <div className="text-sm truncate">{rp.name}</div>
                      <div className="text-[10px] text-muted-foreground truncate">{rp.path}</div>
                    </div>
                  </DropdownMenuItem>
                ))
              )}
            </DropdownMenuSubContent>
          </DropdownMenuSub>

          <DropdownMenuSeparator />

          {/* Save */}
          <DropdownMenuItem
            onClick={saveAll}
            disabled={!canSave || saveInProgress}
            data-testid="file-menu-save"
          >
            {saveInProgress ? (
              <Loader2 className="h-4 w-4 mr-2 animate-spin" />
            ) : (
              <Save className="h-4 w-4 mr-2" />
            )}
            Save
            <span className="ml-auto text-xs text-muted-foreground">Ctrl+S</span>
          </DropdownMenuItem>

          {/* Save As */}
          <DropdownMenuItem
            onClick={() => setSaveAsDialogOpen(true)}
            disabled={!projectPath}
            data-testid="file-menu-save-as"
          >
            <SaveAll className="h-4 w-4 mr-2" />
            Save As...
          </DropdownMenuItem>

          <DropdownMenuSeparator />

          {/* Export ZIP */}
          <DropdownMenuItem
            onClick={handleExport}
            disabled={!projectPath}
            data-testid="file-menu-export"
          >
            <Download className="h-4 w-4 mr-2" />
            Export Project (ZIP)
          </DropdownMenuItem>

          {/* Import ZIP */}
          <DropdownMenuItem
            onClick={() => setImportDialogOpen(true)}
            data-testid="file-menu-import"
          >
            <Upload className="h-4 w-4 mr-2" />
            Import Project (ZIP)
          </DropdownMenuItem>

          {/* Import from Power BI (TMDL) */}
          {HAS_POWER_BI_IMPORT && <DropdownMenuItem
            onClick={() => setTmdlImportOpen(true)}
            data-testid="file-menu-import-tmdl"
          >
            <Database className="h-4 w-4 mr-2" />
            Import Power BI Dataset (TMDL)
          </DropdownMenuItem>}

          {/* Import Power BI Report (PBIR) */}
          {HAS_POWER_BI_IMPORT && <DropdownMenuItem
            onClick={() => setReportImportOpen(true)}
            data-testid="file-menu-import-report"
          >
            <FileBarChart className="h-4 w-4 mr-2" />
            Import Power BI Report (PBIR)
          </DropdownMenuItem>}

          {/* Import Power BI Theme */}
          <DropdownMenuItem
            onClick={() => setThemeImportOpen(true)}
            data-testid="file-menu-import-theme"
          >
            <Palette className="h-4 w-4 mr-2" />
            Import Power BI Theme
          </DropdownMenuItem>

          <DropdownMenuSeparator />

          {/* Refresh Data */}
          <DropdownMenuItem
            onClick={handleRefresh}
            disabled={!projectPath || refreshing}
            data-testid="file-menu-refresh"
          >
            {refreshing ? (
              <Loader2 className="h-4 w-4 mr-2 animate-spin" />
            ) : (
              <RefreshCw className="h-4 w-4 mr-2" />
            )}
            Refresh Data
          </DropdownMenuItem>

          <DropdownMenuSeparator />

          {/* Close Project */}
          <DropdownMenuItem
            onClick={handleCloseProject}
            disabled={!projectPath}
            data-testid="file-menu-close"
          >
            <X className="h-4 w-4 mr-2" />
            Close Project
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>

      {/* Dialogs */}
      <OpenProjectDialog
        open={openDialogOpen}
        onOpenChange={setOpenDialogOpen}
        onProjectSelected={switchToProject}
      />
      <NewProjectDialog
        open={newDialogOpen}
        onOpenChange={setNewDialogOpen}
        onProjectCreated={switchToProject}
      />
      <SaveAsDialog
        open={saveAsDialogOpen}
        onOpenChange={setSaveAsDialogOpen}
        onSaved={switchToProject}
      />
      <ImportProjectDialog
        open={importDialogOpen}
        onOpenChange={setImportDialogOpen}
        onImported={switchToProject}
      />
      {HAS_POWER_BI_IMPORT && <TmdlImportWizard
        open={tmdlImportOpen}
        onOpenChange={setTmdlImportOpen}
        onConverted={switchToProject}
      />}
      {HAS_POWER_BI_IMPORT && <ReportImportWizard
        open={reportImportOpen}
        onOpenChange={setReportImportOpen}
        onTransferred={() => {
          // Reload the current project to pick up new report artifacts
          if (projectPath) switchToProject(projectPath)
        }}
      />}
      <ThemeImportWizard
        open={themeImportOpen}
        onOpenChange={setThemeImportOpen}
      />
    </>
  )
}

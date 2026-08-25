import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  ArrowUp,
  Clock,
  Folder,
  FolderOpen,
  FolderPlus,
  Loader2,
  Search,
  Trash2,
  X,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { ScrollArea } from '@/components/ui/scroll-area'
import { cn } from '@/lib/utils'
import {
  browseDirectories,
  createProject,
  getRecentProjects,
  removeRecentProject,
  type DirectoryItem,
  type RecentProject,
} from '@/lib/api'

interface ProjectPickerProps {
  open: boolean
  value: string
  error?: string | null
  onChange: (next: string) => void
  onSubmit: (path?: string) => Promise<boolean>
  onContinue: () => void
  className?: string
}

type PickerMode = 'open' | 'new'

function isTauriRuntime(): boolean {
  return typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window
}

function joinProjectPath(parent: string, name: string): string {
  const cleanParent = parent.replace(/[\\/]$/, '')
  const separator = cleanParent.includes('/') ? '/' : '\\'
  return `${cleanParent}${separator}${name.trim()}`
}

export function ProjectPicker({
  open,
  value,
  error,
  onChange,
  onSubmit,
  onContinue,
  className,
}: ProjectPickerProps) {
  const [mode, setMode] = useState<PickerMode>('open')
  const [recentProjects, setRecentProjects] = useState<RecentProject[]>([])
  const [currentDir, setCurrentDir] = useState('')
  const [dirItems, setDirItems] = useState<DirectoryItem[]>([])
  const [search, setSearch] = useState('')
  const [projectName, setProjectName] = useState('')
  const [loading, setLoading] = useState(false)
  const [creating, setCreating] = useState(false)
  const [localError, setLocalError] = useState<string | null>(null)
  const nativeDialogAvailable = isTauriRuntime()

  useEffect(() => {
    if (!open) return
    let active = true

    Promise.all([getRecentProjects(), browseDirectories()])
      .then(([recentResult, browseResult]) => {
        if (!active) return
        if (recentResult.data?.projects) setRecentProjects(recentResult.data.projects)
        if (browseResult.data) {
          setCurrentDir(browseResult.data.current)
          setDirItems(browseResult.data.items)
        } else if (browseResult.error) {
          setLocalError(browseResult.error)
        }
      })
      .finally(() => {
        if (active) setLoading(false)
      })

    return () => {
      active = false
    }
  }, [open])

  useEffect(() => {
    if (!open) return
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onContinue()
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [onContinue, open])

  const navigateTo = useCallback(async (path: string) => {
    const target = path.trim()
    if (!target) return
    setLoading(true)
    setLocalError(null)
    try {
      const result = await browseDirectories(target)
      if (result.data) {
        setCurrentDir(result.data.current)
        setDirItems(result.data.items)
        if (mode === 'new') onChange(result.data.current)
      } else {
        setLocalError(result.error || 'That folder could not be opened.')
      }
    } finally {
      setLoading(false)
    }
  }, [mode, onChange])

  const goUp = useCallback(() => {
    const parent = currentDir.replace(/[\\/][^\\/]+$/, '') || currentDir
    if (parent !== currentDir) void navigateTo(parent)
  }, [currentDir, navigateTo])

  const handleRemoveRecent = useCallback(async (path: string) => {
    const result = await removeRecentProject(path)
    if (result.data?.projects) setRecentProjects(result.data.projects)
  }, [])

  const handleCreate = useCallback(async () => {
    const parent = (value.trim() || currentDir).trim()
    const name = projectName.trim()
    if (!parent || !name) {
      setLocalError('Choose a location and enter a project name.')
      return
    }

    setCreating(true)
    setLocalError(null)
    try {
      const result = await createProject(joinProjectPath(parent, name), name)
      if (!result.data) {
        setLocalError(result.error || 'Project creation failed.')
        return
      }
      onChange(result.data.project)
      await onSubmit(result.data.project)
    } finally {
      setCreating(false)
    }
  }, [currentDir, onChange, onSubmit, projectName, value])

  const handleNativeDirectoryPick = useCallback(async () => {
    setLoading(true)
    setLocalError(null)
    try {
      const { open: openDialog } = await import('@tauri-apps/plugin-dialog')
      const selected = await openDialog({
        directory: true,
        multiple: false,
        title: mode === 'open' ? 'Open a Dummy BI Engine project' : 'Choose where to create the project',
        defaultPath: value.trim() || currentDir || undefined,
      })
      if (typeof selected !== 'string' || !selected.trim()) return
      onChange(selected)
      if (mode === 'open') {
        await onSubmit(selected)
      } else {
        setCurrentDir(selected)
      }
    } catch {
      setLocalError('The Windows folder picker could not be opened.')
    } finally {
      setLoading(false)
    }
  }, [currentDir, mode, onChange, onSubmit, value])

  const query = search.trim().toLocaleLowerCase()
  const filteredRecent = useMemo(() => {
    if (!query) return recentProjects
    return recentProjects.filter((project) =>
      `${project.name} ${project.path}`.toLocaleLowerCase().includes(query)
    )
  }, [query, recentProjects])
  const filteredDirectories = useMemo(() => {
    if (!query) return dirItems
    return dirItems.filter((item) =>
      `${item.name} ${item.path}`.toLocaleLowerCase().includes(query)
    )
  }, [dirItems, query])
  const visibleDirectories = mode === 'new'
    ? filteredDirectories.filter((item) => !item.is_project)
    : filteredDirectories
  const createPreview = projectName.trim() && (value.trim() || currentDir)
    ? joinProjectPath(value.trim() || currentDir, projectName.trim())
    : ''

  if (!open) return null

  return (
    <div
      className={cn('fixed inset-0 z-50 flex items-center justify-center bg-background/90 p-4', className)}
      data-testid="project-picker"
      role="dialog"
      aria-modal="true"
      aria-labelledby="project-picker-title"
    >
      <div className="flex max-h-[90vh] w-full max-w-2xl flex-col rounded-xl border bg-background shadow-xl">
        <div className="flex items-start justify-between gap-4 border-b p-6 pb-4">
          <div>
            <h2 id="project-picker-title" className="text-xl font-semibold" data-testid="project-picker-title">
              Open or create a project
            </h2>
            <p className="mt-1 text-sm text-muted-foreground" data-testid="project-picker-message">
              Choose an existing project, start a blank one, or continue without one.
            </p>
          </div>
          <Button variant="ghost" size="icon" onClick={onContinue} aria-label="Close project picker" data-testid="project-picker-close">
            <X className="h-4 w-4" />
          </Button>
        </div>

        <div className="flex gap-2 border-b px-6 py-3">
          <Button
            variant={mode === 'open' ? 'secondary' : 'ghost'}
            size="sm"
            onClick={() => { setMode('open'); setLocalError(null) }}
            data-testid="project-picker-open-tab"
          >
            <FolderOpen className="mr-2 h-4 w-4" /> Open existing
          </Button>
          <Button
            variant={mode === 'new' ? 'secondary' : 'ghost'}
            size="sm"
            onClick={() => { setMode('new'); setLocalError(null); onChange(currentDir) }}
            data-testid="project-picker-new-tab"
          >
            <FolderPlus className="mr-2 h-4 w-4" /> Create new
          </Button>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto p-6">
          <div className="relative">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder={nativeDialogAvailable ? 'Search recent projects...' : 'Search projects and folders...'}
              className="pl-9"
              data-testid="project-picker-search"
              autoFocus
            />
          </div>

          {mode === 'open' ? (
            <div className={cn('mt-5 grid gap-5', !nativeDialogAvailable && 'md:grid-cols-2')}>
              <section>
                <Label className="flex items-center gap-2 text-xs uppercase tracking-wide text-muted-foreground">
                  <Clock className="h-3.5 w-3.5" /> Recent projects
                </Label>
                <ScrollArea className="mt-2 h-48 rounded-md border">
                  <div className="p-1">
                    {filteredRecent.map((project) => (
                      <div key={project.path} className="group flex items-center gap-1 rounded-md hover:bg-accent">
                        <button
                          type="button"
                          className="flex min-w-0 flex-1 items-center gap-2 p-2 text-left"
                          onClick={() => { onChange(project.path); void onSubmit(project.path) }}
                          data-testid="recent-project-item"
                        >
                          <Folder className="h-4 w-4 shrink-0 text-muted-foreground" />
                          <span className="min-w-0">
                            <span className="block truncate text-sm font-medium">{project.name}</span>
                            <span className="block truncate text-[10px] text-muted-foreground">{project.path}</span>
                          </span>
                        </button>
                        <Button
                          variant="ghost"
                          size="icon"
                          className="mr-1 h-7 w-7 shrink-0 opacity-0 group-hover:opacity-100 group-focus-within:opacity-100"
                          onClick={() => void handleRemoveRecent(project.path)}
                          aria-label={`Remove ${project.name} from recent projects`}
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </Button>
                      </div>
                    ))}
                    {filteredRecent.length === 0 ? (
                      <p className="p-6 text-center text-sm text-muted-foreground">No matching recent projects</p>
                    ) : null}
                  </div>
                </ScrollArea>
              </section>

              {!nativeDialogAvailable ? <section>
                <Label className="text-xs uppercase tracking-wide text-muted-foreground">Browse folders</Label>
                <div className="mt-2 flex gap-2">
                  <Button variant="outline" size="icon" onClick={goUp} aria-label="Go to parent folder" data-testid="project-picker-up">
                    <ArrowUp className="h-4 w-4" />
                  </Button>
                  <Input
                    value={currentDir}
                    onChange={(event) => setCurrentDir(event.target.value)}
                    onKeyDown={(event) => event.key === 'Enter' && void navigateTo(currentDir)}
                    aria-label="Current folder"
                    data-testid="project-picker-current-dir"
                  />
                  <Button variant="outline" onClick={() => void navigateTo(currentDir)}>Go</Button>
                </div>
                <ScrollArea className="mt-2 h-36 rounded-md border">
                  <div className="p-1">
                    {loading ? (
                      <div className="flex h-28 items-center justify-center"><Loader2 className="h-5 w-5 animate-spin" /></div>
                    ) : visibleDirectories.map((item) => (
                      <button
                        key={item.path}
                        type="button"
                        className="flex w-full items-center gap-2 rounded-md p-2 text-left hover:bg-accent"
                        onClick={() => item.is_project ? onChange(item.path) : void navigateTo(item.path)}
                        onDoubleClick={() => item.is_project && void onSubmit(item.path)}
                        data-testid="project-picker-directory"
                      >
                        <Folder className={cn('h-4 w-4', item.is_project ? 'text-primary' : 'text-muted-foreground')} />
                        <span className="min-w-0 flex-1 truncate text-sm">{item.name}</span>
                        {item.is_project ? <span className="rounded bg-primary/10 px-1.5 py-0.5 text-[10px] text-primary">Project</span> : null}
                      </button>
                    ))}
                  </div>
                </ScrollArea>
              </section> : null}
            </div>
          ) : (
            <div className="mt-5 grid gap-4">
              <div className="grid gap-2">
                <Label htmlFor="new-project-name">Project name</Label>
                <Input
                  id="new-project-name"
                  value={projectName}
                  onChange={(event) => { setProjectName(event.target.value); setLocalError(null) }}
                  placeholder="My project"
                  data-testid="project-picker-new-name"
                />
              </div>
              <div className="grid gap-2">
                <Label htmlFor="new-project-location">Location</Label>
                <div className="flex gap-2">
                  {!nativeDialogAvailable ? <Button variant="outline" size="icon" onClick={goUp} aria-label="Go to parent folder"><ArrowUp className="h-4 w-4" /></Button> : null}
                  <Input
                    id="new-project-location"
                    value={value}
                    onChange={(event) => onChange(event.target.value)}
                    onKeyDown={(event) => event.key === 'Enter' && void navigateTo(value)}
                    readOnly={nativeDialogAvailable}
                    data-testid="project-picker-new-location"
                  />
                  {nativeDialogAvailable ? (
                    <Button variant="outline" onClick={() => void handleNativeDirectoryPick()} data-testid="project-picker-native-location">
                      <FolderOpen className="mr-2 h-4 w-4" /> Choose folder
                    </Button>
                  ) : (
                    <Button variant="outline" onClick={() => void navigateTo(value)}>Go</Button>
                  )}
                </div>
              </div>
              {!nativeDialogAvailable ? <ScrollArea className="h-36 rounded-md border">
                <div className="p-1">
                  {loading ? (
                    <div className="flex h-28 items-center justify-center"><Loader2 className="h-5 w-5 animate-spin" /></div>
                  ) : visibleDirectories.map((item) => (
                    <button
                      key={item.path}
                      type="button"
                      className="flex w-full items-center gap-2 rounded-md p-2 text-left hover:bg-accent"
                      onClick={() => void navigateTo(item.path)}
                      data-testid="project-picker-new-directory"
                    >
                      <Folder className="h-4 w-4 text-muted-foreground" />
                      <span className="truncate text-sm">{item.name}</span>
                    </button>
                  ))}
                </div>
              </ScrollArea> : null}
              {createPreview ? (
                <p className="text-xs text-muted-foreground" data-testid="project-picker-create-preview">
                  New project: <code className="rounded bg-muted px-1 py-0.5">{createPreview}</code>
                </p>
              ) : null}
            </div>
          )}

          {mode === 'open' && !nativeDialogAvailable ? (
            <div className="mt-5 grid gap-2">
              <Label htmlFor="project-path">Selected project path</Label>
              <Input
                id="project-path"
                value={value}
                onChange={(event) => onChange(event.target.value)}
                onKeyDown={(event) => event.key === 'Enter' && void onSubmit()}
                placeholder="C:\\path\\to\\project"
                data-testid="project-picker-input"
              />
            </div>
          ) : null}

          {(error || localError) ? (
            <div className="mt-4 rounded-md border border-destructive/50 bg-destructive/10 px-3 py-2 text-sm text-destructive" data-testid="project-picker-error">
              {error || localError}
            </div>
          ) : null}
        </div>

        <div className="flex flex-wrap items-center justify-between gap-3 border-t p-6 pt-4">
          <Button variant="ghost" onClick={onContinue} data-testid="project-picker-continue">Continue without project</Button>
          {mode === 'open' ? (
            <Button
              onClick={() => void (nativeDialogAvailable ? handleNativeDirectoryPick() : onSubmit())}
              disabled={loading}
              data-testid={nativeDialogAvailable ? 'project-picker-native-open' : 'project-picker-submit'}
            >
              {loading ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <FolderOpen className="mr-2 h-4 w-4" />}
              {nativeDialogAvailable ? 'Choose project folder' : 'Load project'}
            </Button>
          ) : (
            <Button onClick={() => void handleCreate()} disabled={creating || !projectName.trim()} data-testid="project-picker-create">
              {creating ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <FolderPlus className="mr-2 h-4 w-4" />}
              Create project
            </Button>
          )}
        </div>
      </div>
    </div>
  )
}

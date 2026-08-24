import { useState, useEffect, useCallback } from 'react'
import { Folder, FolderPlus, Trash2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { ScrollArea } from '@/components/ui/scroll-area'
import { cn } from '@/lib/utils'
import { getRecentProjects, removeRecentProject, type RecentProject } from '@/lib/api'

interface ProjectPickerProps {
  open: boolean
  value: string
  error?: string | null
  message?: string | null
  onChange: (next: string) => void
  onSubmit: () => void
  className?: string
}

export function ProjectPicker({
  open,
  value,
  error,
  message,
  onChange,
  onSubmit,
  className,
}: ProjectPickerProps) {
  const [recentProjects, setRecentProjects] = useState<RecentProject[]>([])

  useEffect(() => {
    if (!open) return
    getRecentProjects().then((res) => {
      if (res.data?.projects) setRecentProjects(res.data.projects)
    })
  }, [open])

  const handleRemoveRecent = useCallback(async (path: string, e: React.MouseEvent) => {
    e.stopPropagation()
    const res = await removeRecentProject(path)
    if (res.data?.projects) setRecentProjects(res.data.projects)
  }, [])

  if (!open) return null

  return (
    <div
      className={cn(
        'fixed inset-0 z-50 flex items-center justify-center bg-background/90',
        className
      )}
      data-testid="project-picker"
    >
      <div className="w-full max-w-lg rounded-lg border bg-background p-6 shadow-lg">
        <div className="flex flex-col gap-2">
          <h2 className="text-lg font-semibold" data-testid="project-picker-title">
            Select a project
          </h2>
          <p className="text-sm text-muted-foreground" data-testid="project-picker-message">
            {message || 'Enter a project path or select from recent projects.'}
          </p>
        </div>

        {/* Recent Projects */}
        {recentProjects.length > 0 && (
          <div className="mt-4">
            <Label className="text-xs text-muted-foreground uppercase tracking-wide">Recent Projects</Label>
            <ScrollArea className="h-[180px] mt-2 border rounded-md">
              <div className="p-1">
                {recentProjects.map((rp) => (
                  <div
                    key={rp.path}
                    className="flex items-center justify-between p-2 rounded-md hover:bg-accent cursor-pointer group"
                    onClick={() => {
                      onChange(rp.path)
                      // Auto-submit after a short delay to show selection
                      setTimeout(onSubmit, 100)
                    }}
                    data-testid="recent-project-item"
                  >
                    <div className="flex items-center gap-2 min-w-0">
                      <Folder className="h-4 w-4 text-muted-foreground shrink-0" />
                      <div className="min-w-0">
                        <div className="text-sm font-medium truncate">{rp.name}</div>
                        <div className="text-[10px] text-muted-foreground truncate">{rp.path}</div>
                      </div>
                    </div>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-6 w-6 opacity-0 group-hover:opacity-100 shrink-0"
                      onClick={(e) => handleRemoveRecent(rp.path, e)}
                      data-testid="remove-recent-btn"
                      aria-label="Remove from recent"
                    >
                      <Trash2 className="h-3 w-3" />
                    </Button>
                  </div>
                ))}
              </div>
            </ScrollArea>
          </div>
        )}

        <div className="mt-4 grid gap-2">
          <Label htmlFor="project-path">Project path</Label>
          <Input
            id="project-path"
            value={value}
            onChange={(event) => onChange(event.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && onSubmit()}
            placeholder="C:\\path\\to\\project"
            data-testid="project-picker-input"
          />
          {error && (
            <div className="rounded-md border border-destructive/50 bg-destructive/10 px-3 py-2 text-sm text-destructive" data-testid="project-picker-error">
              {error}
            </div>
          )}
        </div>

        <div className="mt-5 flex justify-end">
          <Button onClick={onSubmit} data-testid="project-picker-submit">
            Load project
          </Button>
        </div>
      </div>
    </div>
  )
}

import { useMemo, useState } from 'react'
import { ArrowRightLeft, Pencil, Plus, Trash2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { ScrollArea } from '@/components/ui/scroll-area'
import { useAppStore } from '@/stores'
import type { RelationshipDef } from '@/lib/api'
import { createRelationship, deleteRelationship, updateRelationship } from '@/lib/api'
import { RelationshipEditorDialog } from './RelationshipEditorDialog'

function relationshipLabel(rel: RelationshipDef): string {
  const dir = (rel.cross_filter_direction ?? 'single') === 'both' ? '↔' : '→'
  return `${rel.from_table}[${rel.from_column}] ${dir} ${rel.to_table}[${rel.to_column}]`
}

export function RelationshipManager() {
  const tables = useAppStore(s => s.tables)
  const relationships = useAppStore(s => s.relationships)
  const setRelationships = useAppStore(s => s.setRelationships)
  const projectPath = useAppStore(s => s.projectPath)

  const [createOpen, setCreateOpen] = useState(false)
  const [editing, setEditing] = useState<RelationshipDef | null>(null)
  const [error, setError] = useState<string | null>(null)

  const sortedRelationships = useMemo(
    () => [...(relationships ?? [])].sort((a, b) => relationshipLabel(a).localeCompare(relationshipLabel(b))),
    [relationships]
  )

  async function handleCreate(payload: Omit<RelationshipDef, 'rel_id'> & { rel_id?: string }) {
    const result = await createRelationship(payload, projectPath ?? undefined)
    if (result.error || !result.data) {
      throw new Error(result.error || 'Failed to create relationship')
    }
    setRelationships(result.data.relationships)
    setError(null)
  }

  async function handleUpdate(payload: Omit<RelationshipDef, 'rel_id'> & { rel_id?: string }) {
    if (!editing?.rel_id) return
    const result = await updateRelationship(editing.rel_id, payload, projectPath ?? undefined)
    if (result.error || !result.data) {
      throw new Error(result.error || 'Failed to update relationship')
    }
    setRelationships(result.data.relationships)
    setEditing(null)
    setError(null)
  }

  async function handleDelete(rel: RelationshipDef) {
    if (!rel.rel_id) return
    if (!confirm(`Delete relationship ${relationshipLabel(rel)}?`)) return
    const result = await deleteRelationship(rel.rel_id, projectPath ?? undefined)
    if (result.error || !result.data) {
      setError(result.error || 'Failed to delete relationship')
      return
    }
    setRelationships(result.data.relationships)
    setError(null)
  }

  return (
    <div className="space-y-2" data-testid="relationship-manager">
      <div className="flex items-center justify-between">
        <h4 className="text-xs font-medium flex items-center gap-2">
          <ArrowRightLeft className="h-4 w-4" />
          Relationships ({sortedRelationships.length})
        </h4>
        <Button
          variant="ghost"
          size="icon"
          className="h-6 w-6"
          onClick={() => setCreateOpen(true)}
          data-testid="add-relationship-btn"
          aria-label="Add relationship"
          title="Add relationship"
        >
          <Plus className="h-3 w-3" />
        </Button>
      </div>

      {error && <div className="text-xs text-destructive">{error}</div>}

      {sortedRelationships.length === 0 ? (
        <p className="text-xs text-muted-foreground py-2" data-testid="no-relationships">No relationships defined</p>
      ) : (
        <ScrollArea className="h-[260px]" data-testid="relationship-list">
          <div className="space-y-1 pr-2">
            {sortedRelationships.map((rel) => (
              <div
                key={rel.rel_id || `${rel.from_table}:${rel.from_column}:${rel.to_table}:${rel.to_column}`}
                className="text-xs px-2 py-1.5 bg-muted rounded"
                data-testid={`relationship-item-${(rel.rel_id || '').replace(/[^a-zA-Z0-9_-]/g, '_')}`}
              >
                <div className="min-w-0">
                  <span className="block truncate" title={relationshipLabel(rel)}>{relationshipLabel(rel)}</span>
                </div>
                <div className="mt-1 flex flex-wrap items-center gap-1.5">
                  <span className="text-[10px] px-1 py-0.5 rounded bg-background border" title="cross-filter direction">
                    {(rel.cross_filter_direction ?? 'single') === 'both' ? 'Both' : 'Single'}
                  </span>
                  {!rel.active && (
                    <span className="text-[10px] px-1 py-0.5 rounded bg-destructive/10 text-destructive">Inactive</span>
                  )}
                </div>
                <div className="mt-1 flex justify-end gap-1" data-testid="relationship-item-actions-row">
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-5 w-5"
                    onClick={() => setEditing(rel)}
                    data-testid={`edit-relationship-${(rel.rel_id || '').replace(/[^a-zA-Z0-9_-]/g, '_')}`}
                  >
                    <Pencil className="h-3 w-3" />
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-5 w-5 text-destructive"
                    onClick={() => void handleDelete(rel)}
                    data-testid={`delete-relationship-${(rel.rel_id || '').replace(/[^a-zA-Z0-9_-]/g, '_')}`}
                  >
                    <Trash2 className="h-3 w-3" />
                  </Button>
                </div>
              </div>
            ))}
          </div>
        </ScrollArea>
      )}

      <RelationshipEditorDialog
        open={createOpen}
        onOpenChange={setCreateOpen}
        tables={tables}
        title="Create Relationship"
        submitLabel="Create"
        onSubmit={handleCreate}
      />

      <RelationshipEditorDialog
        open={Boolean(editing)}
        onOpenChange={(open) => { if (!open) setEditing(null) }}
        tables={tables}
        initial={editing ?? undefined}
        title="Edit Relationship"
        submitLabel="Save"
        onSubmit={handleUpdate}
      />
    </div>
  )
}

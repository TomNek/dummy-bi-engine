/**
 * InteractionModePanel - Per-visual interaction settings
 * Controls affects_others, is_affected, mode (filter/highlight),
 * and per-visual-pair interaction targets (Edit Interactions mode).
 */

import { useState } from 'react'
import { ChevronDown, ChevronRight, MousePointer2, Settings2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { useReportStore } from '@/stores'

export interface InteractionSettings {
  affects_others?: boolean
  is_affected?: boolean
  mode?: 'filter' | 'highlight'
  interaction_targets?: Record<string, 'filter' | 'highlight' | 'none'>
}

interface InteractionModePanelProps {
  settings: InteractionSettings
  visualId?: string
  onUpdate: (key: keyof InteractionSettings, value: unknown) => void
}

export function InteractionModePanel({ settings, visualId, onUpdate }: InteractionModePanelProps) {
  const [isOpen, setIsOpen] = useState(true)
  const editInteractionsSourceId = useReportStore(s => s.editInteractionsSourceId)
  const setEditInteractionsSourceId = useReportStore(s => s.setEditInteractionsSourceId)

  // Defaults match old UI: { affects_others: true, is_affected: true, mode: 'filter' }
  const affectsOthers = settings.affects_others !== false
  const isAffected = settings.is_affected !== false
  const mode = settings.mode || 'filter'
  const isEditingInteractions = editInteractionsSourceId === visualId && !!visualId

  return (
    <div data-testid="interaction-mode-panel">
      <Collapsible open={isOpen} onOpenChange={setIsOpen}>
        <CollapsibleTrigger asChild>
          <Button
            variant="ghost"
            className="w-full justify-between px-0 h-7 font-medium hover:bg-transparent"
            data-testid="interaction-mode-toggle"
          >
            <div className="flex items-center gap-2">
              {isOpen ? (
                <ChevronDown className="h-3 w-3" />
              ) : (
                <ChevronRight className="h-3 w-3" />
              )}
              <MousePointer2 className="h-3 w-3" />
              <span className="text-xs">Interactions</span>
            </div>
          </Button>
        </CollapsibleTrigger>
        <CollapsibleContent>
          <div className="space-y-3 py-2 pl-5">
            <div className="flex items-center justify-between">
              <Label htmlFor="affects-others" className="text-xs">
                Affects other visuals
              </Label>
              <Switch
                id="affects-others"
                checked={affectsOthers}
                onCheckedChange={(checked: boolean) => onUpdate('affects_others', checked)}
                data-testid="interaction-affects-others"
              />
            </div>

            <div className="flex items-center justify-between">
              <Label htmlFor="is-affected" className="text-xs">
                Is affected by others
              </Label>
              <Switch
                id="is-affected"
                checked={isAffected}
                onCheckedChange={(checked: boolean) => onUpdate('is_affected', checked)}
                data-testid="interaction-is-affected"
              />
            </div>

            <div className="space-y-1">
              <Label className="text-xs">Interaction mode</Label>
              <Select
                value={mode}
                onValueChange={(val) => onUpdate('mode', val as 'filter' | 'highlight')}
              >
                <SelectTrigger className="h-7 text-xs" data-testid="interaction-mode-select">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="filter">Filter</SelectItem>
                  <SelectItem value="highlight">Highlight</SelectItem>
                </SelectContent>
              </Select>
            </div>

            {mode === 'highlight' && (
              <p className="text-xs text-muted-foreground">
                Highlight mode shows related data with reduced opacity instead of filtering
              </p>
            )}

            {/* Edit Interactions button — per-visual-pair targeting */}
            {affectsOthers && visualId && (
              <Button
                variant={isEditingInteractions ? 'default' : 'outline'}
                size="sm"
                className="w-full h-7 text-xs gap-1.5"
                data-testid="edit-interactions-btn"
                onClick={() => {
                  setEditInteractionsSourceId(isEditingInteractions ? null : visualId)
                }}
              >
                <Settings2 className="h-3 w-3" />
                {isEditingInteractions ? 'Exit Edit Interactions' : 'Edit Interactions'}
              </Button>
            )}
            {isEditingInteractions && (
              <p className="text-xs text-muted-foreground">
                Click the interaction badges on other visuals to cycle between filter, highlight, and none.
              </p>
            )}
          </div>
        </CollapsibleContent>
      </Collapsible>
    </div>
  )
}

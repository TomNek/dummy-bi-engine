/**
 * Hook for creating new visuals
 * 
 * Visuals are created in-memory only. They are persisted to disk
 * when the user clicks Save All (save-only persistence invariant).
 * 
 * Slicers are handled specially: they create a unified slicer
 * (definition + page entry) via the slicer API.
 */

import { useCallback, useState } from 'react'
import { useReportStore, useAppStore } from '@/stores'

import { createUnifiedSlicer, type StaticContent, type UnifiedSlicer } from '@/lib/api'
import { isVisualTypeAvailable } from '@/lib/edition'

export type VisualType = 'bar' | 'column' | 'line' | 'area' | 'pie' | 'scatter' | 'combo' | 'histogram' | 'box' | 'violin' | 'strip' | 'ecdf' | 'funnel' | 'funnel_area' | 'density_contour' | 'density_heatmap' | 'treemap' | 'sunburst' | 'icicle' | 'scatter_polar' | 'line_polar' | 'bar_polar' | 'scatter_3d' | 'line_3d' | 'table' | 'matrix' | 'card' | 'slicer' | 'textbox' | 'button' | 'shape' | 'image' | 'ibcs_bar' | 'ibcs_column' | 'ibcs_line' | 'ibcs_card' | 'ibcs_waterfall' | 'ibcs_table' | 'bubble' | 'bubble_3d' | 'candlestick' | 'ohlc' | 'waterfall' | 'gauge' | 'sankey'

export const STATIC_VISUAL_TYPES: VisualType[] = ['textbox', 'button', 'shape', 'image']

interface CreateVisualOptions {
  visualType: VisualType
  title?: string
  x?: number
  y?: number
  width?: number
  height?: number
  staticContent?: StaticContent
}

export function useCreateVisual() {
  const setDirty = useAppStore(s => s.setDirty)
  const projectPath = useAppStore(s => s.projectPath)
  const tables = useAppStore(s => s.tables)
  const currentPageId = useReportStore(s => s.currentPageId)
  const addVisual = useReportStore(s => s.addVisual)
  const selectVisual = useReportStore(s => s.selectVisual)
  const [creating, setCreating] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const createVisual = useCallback(async (options: CreateVisualOptions) => {
    if (!isVisualTypeAvailable(options.visualType)) {
      setError('This visual type is not available in this edition')
      return null
    }
    if (!currentPageId) {
      setError('No page selected')
      return null
    }

    setCreating(true)
    setError(null)

    try {
      // Slicers are created via the unified slicer API (def + page entry)
      if (options.visualType === 'slicer') {
        if (!projectPath) {
          setError('No project loaded')
          return null
        }

        // Find a default column binding: first column of first non-virtual table
        let defaultTable = ''
        let defaultColumn = ''
        const realTables = tables.filter(t => !t.virtual && t.columns.length > 0)
        if (realTables.length > 0) {
          defaultTable = realTables[0].name
          defaultColumn = realTables[0].columns[0]
        }
        if (!defaultTable || !defaultColumn) {
          setError('No tables available for slicer binding')
          return null
        }

        const slicerData: Omit<UnifiedSlicer, 'id'> = {
          name: options.title ?? `New Slicer`,
          column: { table: defaultTable, column: defaultColumn },
          type: 'list',
          behavior: { apply_to: 'all_visuals', auto_apply: true },
          selection: { mode: 'all', values: [] },
          ui: { multi: false, search: false },
          pages: {
            [currentPageId]: {
              visible: true,
              sync: true,
              layout: {
                x: options.x ?? 40 + Math.random() * 100,
                y: options.y ?? 40 + Math.random() * 100,
                w: options.width ?? 240,
                h: options.height ?? 260,
              },
            },
          },
        }

        const result = await createUnifiedSlicer(slicerData, projectPath)
        if (result.error) {
          setError(result.error)
          return null
        }
        setDirty(true)
        // Notify slicer dock panels to refresh
        window.dispatchEvent(new CustomEvent('slicers-changed'))
        // Return a synthetic created object for caller consistency
        return { id: `slicer_created`, visual_type: 'slicer' as const, page_id: currentPageId }
      }

      const isStatic = STATIC_VISUAL_TYPES.includes(options.visualType)
      // Static types get smaller default dimensions
      const defaultW = isStatic 
        ? (options.visualType === 'textbox' ? 300 : options.visualType === 'button' ? 160 : 200)
        : 400
      const defaultH = isStatic 
        ? (options.visualType === 'textbox' ? 100 : options.visualType === 'button' ? 50 : 200)
        : 300

      const layout = {
        x: options.x ?? 40 + Math.random() * 100,
        y: options.y ?? 40 + Math.random() * 100,
        w: options.width ?? defaultW,
        h: options.height ?? defaultH,
      }

      // Generate a client-side ID (will be reconciled on Save All)
      const id = `v_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`

      const created = {
        id,
        visual_type: options.visualType,
        title: options.title ?? (isStatic ? '' : `New ${options.visualType}`),
        page_id: currentPageId,
        x: layout.x,
        y: layout.y,
        width: layout.w,
        height: layout.h,
        layout: { x: layout.x, y: layout.y, w: layout.w, h: layout.h },
        encodings: {},
        format: {},
        interactions: {},
        ...(isStatic && options.staticContent ? { static_content: options.staticContent } : {}),
      }

      addVisual(created)
      selectVisual(created.id)
      setDirty(true)
      return created
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to create visual'
      setError(message)
      return null
    } finally {
      setCreating(false)
    }
  }, [currentPageId, addVisual, selectVisual, setDirty, projectPath, tables])

  const quickCreateVisual = useCallback((visualType: VisualType, opts?: Partial<Omit<CreateVisualOptions, 'visualType'>>) => {
    return createVisual({ visualType, ...opts })
  }, [createVisual])

  return {
    createVisual,
    quickCreateVisual,
    creating,
    error,
    clearError: () => setError(null),
  }
}

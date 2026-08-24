import type { CSSProperties } from 'react'
import type { TablixCell, TablixProperties } from '@/types/matrix'

export type MatrixColumnWidthMode = 'fit_to_content' | 'grow_to_fit' | 'fixed'

type WidthMap = Record<string, number>

function normalizeWidth(value: unknown): number | undefined {
  if (typeof value === 'number' && Number.isFinite(value) && value > 0) return value
  if (typeof value === 'string') {
    const parsed = Number(value.replace(/[dD]$/, ''))
    if (Number.isFinite(parsed) && parsed > 0) return parsed
  }
  return undefined
}

export function normalizeMatrixColumnWidthMode(properties: TablixProperties | undefined): MatrixColumnWidthMode {
  const raw = String(properties?.columnWidthMode ?? '').trim().toLowerCase()
  const compact = raw.replace(/[^a-z]/g, '')
  if (compact.includes('fixed')) return 'fixed'
  if (compact.includes('grow')) return 'grow_to_fit'
  if (compact.includes('snap')) return 'grow_to_fit'
  if (compact.includes('fit') || compact.includes('auto')) return 'fit_to_content'

  if (properties?.autofitColumns === false) return 'fixed'
  if (properties?.snapColumnsToFit !== false) return 'grow_to_fit'
  return 'fit_to_content'
}

function widthCandidates(cell: TablixCell, stableKey: string, colIdx: number): string[] {
  const candidates = [stableKey, `col-${colIdx}`]
  if (cell.colKey) candidates.push(cell.colKey, `ck-${cell.colKey}`)
  if (cell.measureName) candidates.push(cell.measureName)
  if (cell.label != null) candidates.push(String(cell.label))
  if (cell.formatted != null) candidates.push(String(cell.formatted))
  if (cell.colPath?.length) {
    const dotted = cell.colPath.join('.')
    const joined = cell.colPath.join('__')
    candidates.push(dotted, joined, `ck-${joined}`, `leaf:${dotted}`, `leaf:${joined}`)
    if (cell.measureName) {
      candidates.push(
        `${dotted}.${cell.measureName}`,
        `${joined}__${cell.measureName}`,
        `ck-${joined}__${cell.measureName}`,
        `leaf:${dotted}.${cell.measureName}`,
        `leaf:${joined}__${cell.measureName}`,
      )
    }
  }
  return Array.from(new Set(candidates.filter(Boolean)))
}

export function buildInitialMatrixColumnWidths(
  cells: TablixCell[],
  properties: TablixProperties | undefined,
  getStableColumnKey: (cell: TablixCell, colIdx: number) => string,
): WidthMap {
  const sources = [
    properties?.initialColumnWidths,
    properties?.columnWidths,
    properties?.matrixColumnWidths,
    properties?.moreGranularColumnWidths ? properties?.leafColumnWidths : undefined,
  ]
  const imported: WidthMap = {}
  for (const source of sources) {
    if (!source || typeof source !== 'object') continue
    for (const [key, value] of Object.entries(source)) {
      const width = normalizeWidth(value)
      if (width != null) imported[String(key)] = width
    }
  }
  if (Object.keys(imported).length === 0) return {}

  const resolved: WidthMap = {}
  for (const [key, width] of Object.entries(imported)) {
    if (key.startsWith('col-') || key.startsWith('ck-')) resolved[key] = width
  }

  for (const cell of cells) {
    if (cell.col == null || cell.col < 0) continue
    const stableKey = getStableColumnKey(cell, cell.col)
    for (const candidate of widthCandidates(cell, stableKey, cell.col)) {
      const width = imported[candidate]
      if (width != null) {
        resolved[stableKey] = width
        break
      }
    }
  }

  return resolved
}

export function getMatrixColumnWidthStyle(args: {
  columnKey: string
  widths: WidthMap
  mode: MatrixColumnWidthMode
  defaultWidth: number
  minWidth?: number
}): CSSProperties {
  const minWidth = args.minWidth ?? 40
  const explicitWidth = normalizeWidth(args.widths[args.columnKey])
  if (explicitWidth != null) return { width: explicitWidth, minWidth }
  if (args.mode === 'fixed') return { width: args.defaultWidth, minWidth }
  if (args.mode === 'grow_to_fit') return { minWidth }
  return {}
}

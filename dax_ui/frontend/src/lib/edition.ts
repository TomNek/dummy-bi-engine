import type { VisualType } from '@/hooks/useCreateVisual'

declare const __OPEN_CORE__: boolean

export const IS_OPEN_CORE = __OPEN_CORE__

export const HAS_TRANSFORM_STUDIO = !IS_OPEN_CORE
export const HAS_STORIES = !IS_OPEN_CORE
export const HAS_EDU_RELATIONSHIPS = !IS_OPEN_CORE
export const HAS_ML_ANALYTICS = !IS_OPEN_CORE
export const HAS_REPORT_AUTOGENERATION = !IS_OPEN_CORE
export const HAS_SUBSCRIPTIONS = !IS_OPEN_CORE
export const HAS_POWER_BI_IMPORT = !IS_OPEN_CORE
export const HAS_SERVER_PLATFORM = !IS_OPEN_CORE

export const OPEN_CORE_VISUAL_TYPES = new Set<VisualType>([
  'bar', 'column', 'line', 'scatter', 'area', 'pie', 'combo', 'histogram',
  'box', 'violin', 'strip', 'ecdf', 'funnel', 'funnel_area',
  'density_contour', 'density_heatmap', 'treemap', 'sunburst', 'icicle',
  'scatter_polar', 'line_polar', 'bar_polar', 'bubble', 'bubble_3d',
  'scatter_3d', 'line_3d', 'candlestick', 'ohlc', 'waterfall', 'gauge',
  'sankey', 'table',
])

export function isVisualTypeAvailable(type: VisualType): boolean {
  return !IS_OPEN_CORE || OPEN_CORE_VISUAL_TYPES.has(type)
}

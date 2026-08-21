import type { Data } from 'plotly.js'

export const CHART_TYPES = [
  'bar', 'column', 'line', 'scatter', 'area', 'pie', 'combo',
  'histogram', 'box', 'violin', 'strip', 'ecdf',
  'funnel', 'funnel_area', 'density_contour', 'density_heatmap',
  'treemap', 'sunburst', 'icicle', 'scatter_polar', 'line_polar', 'bar_polar',
  'bubble', 'bubble_3d', 'scatter_3d', 'line_3d',
  'candlestick', 'ohlc', 'waterfall', 'gauge', 'sankey',
] as const

export type ChartType = (typeof CHART_TYPES)[number]
export interface ChartSpec { label: string; slots: string[] }

export const CHART_SPECS: Record<ChartType, ChartSpec> = {
  bar: { label: 'Bar', slots: ['x', 'y', 'color'] },
  column: { label: 'Column', slots: ['x', 'y', 'color'] },
  line: { label: 'Line', slots: ['x', 'y', 'color'] },
  scatter: { label: 'Scatter', slots: ['x', 'y', 'color', 'size'] },
  area: { label: 'Area', slots: ['x', 'y', 'color'] },
  pie: { label: 'Pie', slots: ['names', 'values', 'color'] },
  combo: { label: 'Combo', slots: ['x', 'y', 'y2', 'color'] },
  histogram: { label: 'Histogram', slots: ['x', 'color'] },
  box: { label: 'Box plot', slots: ['x', 'y', 'color'] },
  violin: { label: 'Violin', slots: ['x', 'y', 'color'] },
  strip: { label: 'Strip', slots: ['x', 'y', 'color'] },
  ecdf: { label: 'ECDF', slots: ['x', 'color'] },
  funnel: { label: 'Funnel', slots: ['x', 'y', 'color'] },
  funnel_area: { label: 'Funnel area', slots: ['names', 'values'] },
  density_contour: { label: 'Density contour', slots: ['x', 'y', 'color'] },
  density_heatmap: { label: 'Density heatmap', slots: ['x', 'y'] },
  treemap: { label: 'Treemap', slots: ['path', 'values', 'color'] },
  sunburst: { label: 'Sunburst', slots: ['path', 'values', 'color'] },
  icicle: { label: 'Icicle', slots: ['path', 'values', 'color'] },
  scatter_polar: { label: 'Polar scatter', slots: ['r', 'theta', 'color'] },
  line_polar: { label: 'Radar', slots: ['r', 'theta', 'color'] },
  bar_polar: { label: 'Wind rose', slots: ['r', 'theta', 'color'] },
  bubble: { label: 'Bubble', slots: ['x', 'y', 'size', 'color'] },
  bubble_3d: { label: '3D bubble', slots: ['x', 'y', 'z', 'size', 'color'] },
  scatter_3d: { label: '3D scatter', slots: ['x', 'y', 'z', 'size', 'color'] },
  line_3d: { label: '3D line', slots: ['x', 'y', 'z', 'color'] },
  candlestick: { label: 'Candlestick', slots: ['x', 'open', 'high', 'low', 'close'] },
  ohlc: { label: 'OHLC', slots: ['x', 'open', 'high', 'low', 'close'] },
  waterfall: { label: 'Waterfall', slots: ['x', 'y', 'measure'] },
  gauge: { label: 'Gauge', slots: ['value', 'reference'] },
  sankey: { label: 'Sankey', slots: ['source', 'target', 'value'] },
}

const COLORS = ['#6d5bd0', '#16a394', '#e19046', '#4b7bec', '#d65a79', '#75818c']
const values = (rows: Record<string, unknown>[], field = '') => rows.map((row) => row[field] as never)

function singleTrace(rows: Record<string, unknown>[], chart: ChartType, fields: Record<string, string>, color = COLORS[0]): Data[] {
  const x = values(rows, fields.x || fields.names || fields.path || fields.theta || fields.source)
  const y = values(rows, fields.y || fields.values || fields.r || fields.value)
  const marker = { color }
  switch (chart) {
    case 'bar': return [{ type: 'bar', orientation: 'h', x: y, y: x, marker }]
    case 'column': return [{ type: 'bar', x, y, marker }]
    case 'line': return [{ type: 'scatter', mode: 'lines+markers', x, y, marker }]
    case 'area': return [{ type: 'scatter', mode: 'lines', fill: 'tozeroy', x, y, line: { color } }]
    case 'scatter': return [{ type: 'scatter', mode: 'markers', x, y, marker: { color, size: fields.size ? values(rows, fields.size) : 9 } }]
    case 'pie': return [{ type: 'pie', labels: x, values: y, hole: 0.18, marker }]
    case 'combo': return [
      { type: 'bar', x, y, name: fields.y || 'Value', marker },
      { type: 'scatter', mode: 'lines+markers', x, y: values(rows, fields.y2 || fields.y), name: fields.y2 || 'Line', yaxis: 'y2' },
    ]
    case 'histogram': return [{ type: 'histogram', x, marker }]
    case 'box': return [{ type: 'box', x, y, boxpoints: 'outliers', marker }]
    case 'violin': return [{ type: 'violin', x, y, box: { visible: true }, meanline: { visible: true }, line: { color } }]
    case 'strip': return [{ type: 'scatter', mode: 'markers', x, y, marker: { color, size: 7, opacity: 0.72 } }]
    case 'ecdf': {
      const sorted = x.map(Number).filter(Number.isFinite).sort((a, b) => a - b)
      return [{ type: 'scatter', mode: 'lines', line: { shape: 'hv', color }, x: sorted, y: sorted.map((_, i) => (i + 1) / sorted.length) }]
    }
    case 'funnel': return [{ type: 'funnel', orientation: 'h', x, y, marker }]
    case 'funnel_area': return [{ type: 'funnelarea', labels: x, values: y, marker }]
    case 'density_contour': return [{ type: 'histogram2dcontour', x, y, colorscale: 'Purples' }]
    case 'density_heatmap': return [{ type: 'histogram2d', x, y, colorscale: 'Purples' }]
    case 'treemap': return [{ type: 'treemap', labels: x, values: y, parents: x.map(() => ''), marker }]
    case 'sunburst': return [{ type: 'sunburst', labels: x, values: y, parents: x.map(() => ''), marker }]
    case 'icicle': return [{ type: 'icicle', labels: x, values: y, parents: x.map(() => ''), marker } as unknown as Data]
    case 'scatter_polar': return [{ type: 'scatterpolar', mode: 'markers', theta: x, r: y, marker }]
    case 'line_polar': return [{ type: 'scatterpolar', mode: 'lines+markers', fill: 'toself', theta: x, r: y, line: { color } }]
    case 'bar_polar': return [{ type: 'barpolar', theta: x, r: y, marker }]
    case 'bubble': return [{ type: 'scatter', mode: 'markers', x, y, marker: { color, size: values(rows, fields.size), sizemode: 'area', sizeref: 2 } }]
    case 'bubble_3d':
    case 'scatter_3d': return [{ type: 'scatter3d', mode: 'markers', x, y, z: values(rows, fields.z), marker: { color, size: fields.size ? values(rows, fields.size) : 5, sizemode: 'diameter' } }]
    case 'line_3d': return [{ type: 'scatter3d', mode: 'lines+markers', x, y, z: values(rows, fields.z), line: { color } }]
    case 'candlestick': return [{ type: 'candlestick', x, open: values(rows, fields.open), high: values(rows, fields.high), low: values(rows, fields.low), close: values(rows, fields.close) }]
    case 'ohlc': return [{ type: 'ohlc', x, open: values(rows, fields.open), high: values(rows, fields.high), low: values(rows, fields.low), close: values(rows, fields.close) }]
    case 'waterfall': return [{ type: 'waterfall', x, y, measure: fields.measure ? values(rows, fields.measure) : undefined } as unknown as Data]
    case 'gauge': return [{ type: 'indicator', mode: fields.reference ? 'gauge+number+delta' : 'gauge+number', value: Number(rows[0]?.[fields.value] ?? 0), delta: fields.reference ? { reference: Number(rows[0]?.[fields.reference] ?? 0) } : undefined, gauge: { axis: { visible: true } } }]
    case 'sankey': {
      const sourceLabels = values(rows, fields.source).map(String)
      const targetLabels = values(rows, fields.target).map(String)
      const labels = [...new Set([...sourceLabels, ...targetLabels])]
      return [{ type: 'sankey', node: { label: labels }, link: { source: sourceLabels.map((label) => labels.indexOf(label)), target: targetLabels.map((label) => labels.indexOf(label)), value: values(rows, fields.value).map(Number) } } as unknown as Data]
  }
}
}

export function buildTraces(rows: Record<string, unknown>[], chart: ChartType, fields: Record<string, string>): Data[] {
  const requiredField = CHART_SPECS[chart].slots.find((slot) => !['color', 'reference', 'measure'].includes(slot))
  if (!rows.length || (requiredField && !fields[requiredField])) return []
  const colorField = fields.color
  if (!colorField || ['pie', 'funnel_area', 'density_heatmap', 'treemap', 'sunburst', 'icicle', 'candlestick', 'ohlc', 'waterfall', 'gauge', 'sankey'].includes(chart)) {
    return singleTrace(rows, chart, fields)
  }
  const groups = new Map<string, Record<string, unknown>[]>()
  rows.forEach((row) => {
    const key = String(row[colorField] ?? 'Blank')
    groups.set(key, [...(groups.get(key) ?? []), row])
  })
  return [...groups.entries()].flatMap(([name, groupRows], index) =>
    singleTrace(groupRows, chart, fields, COLORS[index % COLORS.length]).map((trace) => ({ ...trace, name } as Data)),
  )
}

export function filterRows(rows: Record<string, unknown>[], field: string, operator: string, value: string) {
  if (!field || !value) return rows
  return rows.filter((row) => {
    const actual = row[field]
    const aNumber = Number(actual)
    const bNumber = Number(value)
    if (operator === 'gt') return Number.isFinite(aNumber) && aNumber > bNumber
    if (operator === 'lt') return Number.isFinite(aNumber) && aNumber < bNumber
    if (operator === 'contains') return String(actual ?? '').toLowerCase().includes(value.toLowerCase())
    return String(actual ?? '').toLowerCase() === value.toLowerCase()
  })
}

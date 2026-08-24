/**
 * Reporting Theme — Types & Defaults
 * 
 * Defines the ReportingTheme model covering:
 * - Data colors (chart series colors, Power BI–style)
 * - Visual card layout specs (border, shadow, padding, background)
 * - Font settings (family, sizes, colors)
 * - Chart defaults (gridlines, axes, legend)
 * - Canvas background
 * - Default visual dimensions
 */

// ─── ReportingTheme interface ────────────────────────────────

export interface ReportingThemeVisualCard {
  borderRadius: number       // px (0–20)
  borderWidth: number        // px (0–4)
  borderColor: string        // CSS color or '' for default
  shadow: 'none' | 'sm' | 'md' | 'lg'
  padding: number            // px (0–24)
  background: string         // CSS color or '' for default
}

export interface ReportingThemeFont {
  family: string             // font-family value or '' for default
  sizeBody: number           // px (8–24)
  sizeTitle: number          // px (10–32)
  colorBody: string          // CSS color or '' for default
  colorTitle: string         // CSS color or '' for default
}

export interface ReportingThemeChart {
  showGridlines: boolean
  gridlineColor: string      // CSS color or '' for default
  axisColor: string          // CSS color or '' for default
  plotBackground: string     // CSS color or '' for default
  legendPosition: 'right' | 'bottom' | 'top' | 'left'
}

export interface ReportingThemeCanvas {
  background?: string         // CSS color or '' for default
  backgroundImage?: string    // data URI or URL or '' for none
  showHeaderIcons?: boolean   // global toggle for visual header icons (default true)
  showVisualHeaders?: boolean  // global toggle for visual header bar with title (default true)
}

export interface ReportingThemeDefaultSize {
  width: number              // px (200–1200)
  height: number             // px (150–900)
}

/** Semantic / conditional-formatting colors from a Power BI theme. */
export interface ReportingThemeSemanticColors {
  foreground: string          // general text/icon foreground color, e.g. "#252423"
  tableAccent: string         // accent color for table headers / highlights, e.g. "#118DFF"
  good: string                // positive / good value, e.g. "#1AAB40"
  bad: string                 // negative / bad value, e.g. "#D64554"
  neutral: string             // neutral / warning value, e.g. "#D9B300"
  hyperlink: string           // hyperlink color, e.g. "#0078d4"
}

export interface ReportingTheme {
  name: string
  dataColors: string[]
  visualCard: ReportingThemeVisualCard
  font: ReportingThemeFont
  chart: ReportingThemeChart
  canvas: ReportingThemeCanvas
  defaultSize: ReportingThemeDefaultSize
  /** Optional semantic colors (imported from PBI themes). */
  semantic?: ReportingThemeSemanticColors
}

// ─── Default theme ───────────────────────────────────────────

export const DEFAULT_REPORTING_THEME: ReportingTheme = {
  name: 'Default',
  // Lavender-family palette: progressive darkening + slight hue
  // shifts (248°-292°) for maximum line chart distinction.
  // No red/green (reserved for positive/negative semantics).
  dataColors: [
    '#DED6FF',   // chart-1: lightest lavender  (252°, L92)
    '#BCA8F0',   // chart-2: soft violet         (255°, L78)
    '#E0A8E0',   // chart-3: light orchid        (300°, L78)
    '#9478E0',   // chart-4: medium violet       (255°, L67)
    '#CC68CC',   // chart-5: magenta-purple      (300°, L60)
    '#6C50D0',   // chart-6: dark vivid purple   (254°, L55)
    '#A050B0',   // chart-7: deep orchid         (288°, L50)
    '#4838A8',   // chart-8: darkest indigo      (248°, L44)
  ],
  visualCard: {
    borderRadius: 6,
    borderWidth: 1,
    borderColor: '',
    shadow: 'sm',
    padding: 0,
    background: '',
  },
  font: {
    family: 'Inter, system-ui, -apple-system, sans-serif',
    sizeBody: 11,
    sizeTitle: 14,
    colorBody: '',
    colorTitle: '',
  },
  chart: {
    showGridlines: true,
    gridlineColor: '',
    axisColor: '',
    plotBackground: 'transparent',
    legendPosition: 'bottom',
  },
  canvas: {
    background: '',
    backgroundImage: '',
    showHeaderIcons: true,
    showVisualHeaders: true,
  },
  defaultSize: {
    width: 400,
    height: 300,
  },
}

// ─── Preset themes ───────────────────────────────────────────

export const PRESET_THEMES: Record<string, ReportingTheme> = {
  Default: DEFAULT_REPORTING_THEME,

  'Power BI': {
    name: 'Power BI',
    dataColors: [
      '#118DFF', '#12239E', '#E66C37', '#6B007B',
      '#E044A7', '#744EC2', '#D9B300', '#D64550',
    ],
    visualCard: {
      borderRadius: 4,
      borderWidth: 1,
      borderColor: '',
      shadow: 'sm',
      padding: 0,
      background: '',
    },
    font: {
      family: 'Segoe UI, sans-serif',
      sizeBody: 11,
      sizeTitle: 14,
      colorBody: '',
      colorTitle: '',
    },
    chart: {
      showGridlines: true,
      gridlineColor: '',
      axisColor: '',
      plotBackground: 'transparent',
      legendPosition: 'bottom',
    },
    canvas: {
      background: '',
      backgroundImage: '',
    },
    defaultSize: {
      width: 420,
      height: 320,
    },
    semantic: {
      foreground: '#252423',
      tableAccent: '#118DFF',
      good: '#1AAB40',
      bad: '#D64554',
      neutral: '#D9B300',
      hyperlink: '#0078d4',
    },
  },

  'Executive': {
    name: 'Executive',
    dataColors: [
      '#1B2631', '#2E4053', '#566573', '#1A5276',
      '#148F77', '#B7950B', '#873600', '#6C3483',
    ],
    visualCard: {
      borderRadius: 2,
      borderWidth: 1,
      borderColor: '',
      shadow: 'md',
      padding: 4,
      background: '',
    },
    font: {
      family: 'Georgia, serif',
      sizeBody: 11,
      sizeTitle: 14,
      colorBody: '',
      colorTitle: '',
    },
    chart: {
      showGridlines: true,
      gridlineColor: '',
      axisColor: '',
      plotBackground: '',
      legendPosition: 'right',
    },
    canvas: {
      background: '',
      backgroundImage: '',
    },
    defaultSize: {
      width: 450,
      height: 320,
    },
  },

  'Colorful': {
    name: 'Colorful',
    dataColors: [
      '#E74C3C', '#3498DB', '#2ECC71', '#F39C12',
      '#9B59B6', '#1ABC9C', '#E67E22', '#2980B9',
    ],
    visualCard: {
      borderRadius: 12,
      borderWidth: 0,
      borderColor: '',
      shadow: 'lg',
      padding: 4,
      background: '',
    },
    font: {
      family: 'Inter, system-ui, sans-serif',
      sizeBody: 12,
      sizeTitle: 15,
      colorBody: '',
      colorTitle: '',
    },
    chart: {
      showGridlines: false,
      gridlineColor: '',
      axisColor: '',
      plotBackground: 'transparent',
      legendPosition: 'bottom',
    },
    canvas: {
      background: '',
      backgroundImage: '',
    },
    defaultSize: {
      width: 400,
      height: 300,
    },
  },

  'Minimal': {
    name: 'Minimal',
    dataColors: [
      '#333333', '#666666', '#999999', '#BBBBBB',
      '#1a73e8', '#34a853', '#fbbc04', '#ea4335',
    ],
    visualCard: {
      borderRadius: 0,
      borderWidth: 1,
      borderColor: '#E0E0E0',
      shadow: 'none',
      padding: 8,
      background: '',
    },
    font: {
      family: 'Inter, system-ui, sans-serif',
      sizeBody: 11,
      sizeTitle: 13,
      colorBody: '',
      colorTitle: '',
    },
    chart: {
      showGridlines: true,
      gridlineColor: '',
      axisColor: '',
      plotBackground: '',
      legendPosition: 'bottom',
    },
    canvas: {
      background: '',
      backgroundImage: '',
    },
    defaultSize: {
      width: 380,
      height: 280,
    },
  },

  'IBCS': {
    name: 'IBCS',
    // IBCS standard: monochrome palette — black for actuals,
    // grays for comparisons, structured by intensity.
    dataColors: [
      '#1A1A1A',   // AC (Actual) — near-black
      '#4D4D4D',   // PY (Previous Year) — dark gray
      '#808080',   // BU (Budget) — medium gray
      '#B3B3B3',   // FC (Forecast) — light gray
      '#333333',   // secondary dark
      '#666666',   // secondary medium
      '#999999',   // secondary light
      '#CCCCCC',   // secondary lightest
    ],
    visualCard: {
      borderRadius: 0,
      borderWidth: 1,
      borderColor: '#CCCCCC',
      shadow: 'none',
      padding: 4,
      background: '',
    },
    font: {
      family: 'Arial, Helvetica, sans-serif',
      sizeBody: 10,
      sizeTitle: 12,
      colorBody: '',
      colorTitle: '',
    },
    chart: {
      showGridlines: false,
      gridlineColor: '',
      axisColor: '',
      plotBackground: '',
      legendPosition: 'bottom',
    },
    canvas: {
      background: '',
      backgroundImage: '',
    },
    defaultSize: {
      width: 400,
      height: 280,
    },
  },
}

// ─── Custom Presets (localStorage) ───────────────────────────

const CUSTOM_PRESETS_KEY = 'dax-engine-custom-theme-presets'

/** Load custom presets from localStorage. */
export function loadCustomPresets(): Record<string, ReportingTheme> {
  try {
    const raw = localStorage.getItem(CUSTOM_PRESETS_KEY)
    if (!raw) return {}
    return JSON.parse(raw) as Record<string, ReportingTheme>
  } catch {
    return {}
  }
}

/** Save a custom preset to localStorage. */
export function saveCustomPreset(name: string, theme: ReportingTheme): void {
  const presets = loadCustomPresets()
  presets[name] = { ...theme, name }
  localStorage.setItem(CUSTOM_PRESETS_KEY, JSON.stringify(presets))
}

/** Delete a custom preset from localStorage. */
export function deleteCustomPreset(name: string): void {
  const presets = loadCustomPresets()
  delete presets[name]
  localStorage.setItem(CUSTOM_PRESETS_KEY, JSON.stringify(presets))
}

/** Get all presets: built-in + custom. Custom presets are prefixed with key "custom:" internally but displayed cleanly. */
export function getAllPresets(): { builtIn: Record<string, ReportingTheme>; custom: Record<string, ReportingTheme> } {
  return {
    builtIn: PRESET_THEMES,
    custom: loadCustomPresets(),
  }
}

/** Validate that a parsed JSON object looks like a ReportingTheme. */
export function validateThemeJson(obj: unknown): obj is ReportingTheme {
  if (!obj || typeof obj !== 'object') return false
  const t = obj as Record<string, unknown>
  if (typeof t.name !== 'string') return false
  if (!Array.isArray(t.dataColors) || t.dataColors.length === 0) return false
  if (!t.dataColors.every((c: unknown) => typeof c === 'string')) return false
  if (!t.visualCard || typeof t.visualCard !== 'object') return false
  if (!t.font || typeof t.font !== 'object') return false
  if (!t.chart || typeof t.chart !== 'object') return false
  return true
}

// ─── Helpers ─────────────────────────────────────────────────

/** Deep-merge partial theme over base (defaults). */
export function mergeTheme(
  base: ReportingTheme,
  partial: Partial<ReportingTheme>,
): ReportingTheme {
  return {
    name: partial.name ?? base.name,
    dataColors: partial.dataColors ?? [...base.dataColors],
    visualCard: { ...base.visualCard, ...partial.visualCard },
    font: { ...base.font, ...partial.font },
    chart: { ...base.chart, ...partial.chart },
    canvas: { ...base.canvas, ...partial.canvas },
    defaultSize: { ...base.defaultSize, ...partial.defaultSize },
    semantic: partial.semantic
      ? { ...(base.semantic ?? { foreground: '', tableAccent: '', good: '', bad: '', neutral: '', hyperlink: '' }), ...partial.semantic }
      : base.semantic,
  }
}

/** Get a shadow CSS class from the shadow level. */
export function shadowClass(shadow: ReportingThemeVisualCard['shadow']): string {
  switch (shadow) {
    case 'none': return 'shadow-none'
    case 'sm': return 'shadow-sm'
    case 'md': return 'shadow-md'
    case 'lg': return 'shadow-lg'
  }
}

/**
 * Theme Store — Zustand store for Reporting Theme state
 * 
 * Holds the in-memory reporting theme configuration. Changes are applied
 * immediately to the UI but only persist to disk via Save All (save-only
 * persistence invariant).
 */
import { create } from 'zustand'
import {
  type ReportingTheme,
  DEFAULT_REPORTING_THEME,
  mergeTheme,
  loadCustomPresets,
  saveCustomPreset,
  deleteCustomPreset,
} from '@/lib/theme-defaults'

export interface ThemeState {
  /** The active reporting theme (in-memory, may differ from saved). */
  reportingTheme: ReportingTheme

  /** Whether the theme has been modified since last save/load. */
  isThemeDirty: boolean

  /** Custom presets stored in localStorage. */
  customPresets: Record<string, ReportingTheme>

  /** Set the entire reporting theme (e.g., from server load or preset). */
  setReportingTheme: (theme: ReportingTheme) => void

  /** Partially update the reporting theme (merge over current). */
  updateReportingTheme: (partial: Partial<ReportingTheme>) => void

  /** Update a single data color at the given index. */
  setDataColor: (index: number, color: string) => void

  /** Add a new data color. */
  addDataColor: () => void

  /** Remove a data color by index. */
  removeDataColor: (index: number) => void

  /** Reset theme to defaults. */
  resetReportingTheme: () => void

  /** Mark theme as clean (after save). */
  markThemeClean: () => void

  /** Save the current theme as a custom preset. */
  saveAsPreset: (name: string) => void

  /** Remove a custom preset by name. */
  removeCustomPreset: (name: string) => void

  /** Reload custom presets from localStorage. */
  reloadCustomPresets: () => void
}

export const useThemeStore = create<ThemeState>()((set, get) => ({
  reportingTheme: { ...DEFAULT_REPORTING_THEME, dataColors: [...DEFAULT_REPORTING_THEME.dataColors] },
  isThemeDirty: false,
  customPresets: loadCustomPresets(),

  setReportingTheme: (theme) =>
    set({ reportingTheme: theme, isThemeDirty: true }),

  updateReportingTheme: (partial) =>
    set((state) => ({
      reportingTheme: mergeTheme(state.reportingTheme, partial),
      isThemeDirty: true,
    })),

  setDataColor: (index, color) =>
    set((state) => {
      const colors = [...state.reportingTheme.dataColors]
      if (index >= 0 && index < colors.length) {
        colors[index] = color
      }
      return {
        reportingTheme: { ...state.reportingTheme, dataColors: colors },
        isThemeDirty: true,
      }
    }),

  addDataColor: () =>
    set((state) => {
      if (state.reportingTheme.dataColors.length >= 12) return state
      const colors = [...state.reportingTheme.dataColors, '#888888']
      return {
        reportingTheme: { ...state.reportingTheme, dataColors: colors },
        isThemeDirty: true,
      }
    }),

  removeDataColor: (index) =>
    set((state) => {
      if (state.reportingTheme.dataColors.length <= 2) return state
      const colors = state.reportingTheme.dataColors.filter((_, i) => i !== index)
      return {
        reportingTheme: { ...state.reportingTheme, dataColors: colors },
        isThemeDirty: true,
      }
    }),

  resetReportingTheme: () =>
    set({
      reportingTheme: { ...DEFAULT_REPORTING_THEME, dataColors: [...DEFAULT_REPORTING_THEME.dataColors] },
      isThemeDirty: true,
    }),

  markThemeClean: () => set({ isThemeDirty: false }),

  saveAsPreset: (name: string) => {
    const theme = get().reportingTheme
    saveCustomPreset(name, theme)
    set({ customPresets: loadCustomPresets() })
  },

  removeCustomPreset: (name: string) => {
    deleteCustomPreset(name)
    set({ customPresets: loadCustomPresets() })
  },

  reloadCustomPresets: () => {
    set({ customPresets: loadCustomPresets() })
  },
}))

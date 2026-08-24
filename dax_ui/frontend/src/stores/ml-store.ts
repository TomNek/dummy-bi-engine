// Open-core compatibility stub.
export type MLActivity = Record<string, unknown>
export interface MLState {
  loadRegimeChanges: (...args: unknown[]) => Promise<void>
  hasRegimeChanges: (...args: unknown[]) => boolean
}
const state: MLState = {
  loadRegimeChanges: async () => undefined,
  hasRegimeChanges: () => false,
}
export const useMLStore = <T>(selector: (value: MLState) => T): T => selector(state)

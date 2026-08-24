// Open-core compatibility stub.
export type ServerState = Record<string, never>
const state: ServerState = {}
export const useServerStore = <T>(selector: (value: ServerState) => T): T => selector(state)

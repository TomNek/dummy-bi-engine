// Open-core compatibility stub.
export interface AutogenState { setOpen: (open: boolean) => void }
const state: AutogenState = { setOpen: () => undefined }
export const useAutogenStore = Object.assign(
  <T>(selector: (value: AutogenState) => T): T => selector(state),
  { getState: () => state },
)

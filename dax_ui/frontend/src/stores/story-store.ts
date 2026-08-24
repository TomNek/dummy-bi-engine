// Open-core compatibility stub.
export interface StoryState { presentingStoryId: string | null }
const state: StoryState = { presentingStoryId: null }
export const useStoryStore = <T>(selector: (value: StoryState) => T): T => selector(state)

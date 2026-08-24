// Open-core compatibility stub.
export type SubscriptionState = Record<string, never>
const state: SubscriptionState = {}
export const useSubscriptionStore = <T>(selector: (value: SubscriptionState) => T): T => selector(state)

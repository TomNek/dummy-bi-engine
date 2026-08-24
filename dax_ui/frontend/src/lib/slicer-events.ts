export const APPLY_ALL_SLICERS_EVENT = 'dummybi:apply-all-slicers'
export const CLEAR_ALL_SLICERS_EVENT = 'dummybi:clear-all-slicers'

export function dispatchSlicerEvent(eventName: string): void {
  const event = new CustomEvent(eventName)
  window.dispatchEvent(event)
  document.dispatchEvent(new CustomEvent(eventName))
}
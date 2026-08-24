export const CHECK_FOR_UPDATES_EVENT = 'smw:check-for-updates'

export function requestUpdateCheck(): void {
  window.dispatchEvent(new CustomEvent(CHECK_FOR_UPDATES_EVENT))
}

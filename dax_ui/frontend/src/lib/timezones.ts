const FALLBACK_TIMEZONES = [
  'UTC',
  'Etc/GMT+12',
  'Pacific/Honolulu',
  'America/Anchorage',
  'America/Los_Angeles',
  'America/Denver',
  'America/Chicago',
  'America/New_York',
  'America/Halifax',
  'America/Sao_Paulo',
  'Atlantic/Reykjavik',
  'Europe/London',
  'Europe/Dublin',
  'Europe/Paris',
  'Europe/Berlin',
  'Europe/Madrid',
  'Europe/Rome',
  'Europe/Warsaw',
  'Europe/Athens',
  'Europe/Helsinki',
  'Europe/Bucharest',
  'Africa/Cairo',
  'Africa/Johannesburg',
  'Asia/Jerusalem',
  'Asia/Riyadh',
  'Asia/Dubai',
  'Asia/Karachi',
  'Asia/Kolkata',
  'Asia/Dhaka',
  'Asia/Bangkok',
  'Asia/Singapore',
  'Asia/Hong_Kong',
  'Asia/Shanghai',
  'Asia/Tokyo',
  'Asia/Seoul',
  'Australia/Perth',
  'Australia/Adelaide',
  'Australia/Sydney',
  'Pacific/Auckland',
] as const

export function getTimezoneOptions(): string[] {
  try {
    const valuesFn = (Intl as unknown as { supportedValuesOf?: (key: string) => string[] }).supportedValuesOf
    if (typeof valuesFn === 'function') {
      const all = valuesFn('timeZone') || []
      if (Array.isArray(all) && all.length > 0) {
        const deduped = Array.from(new Set(['UTC', ...all]))
        return deduped.sort((a, b) => a.localeCompare(b))
      }
    }
  } catch {
    // fall back to curated list
  }
  return [...FALLBACK_TIMEZONES]
}

export function getTimezoneOffsetLabel(timeZone: string, date = new Date()): string {
  try {
    const parts = new Intl.DateTimeFormat('en-US', {
      timeZone,
      timeZoneName: 'shortOffset',
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
    }).formatToParts(date)
    const offsetPart = parts.find((p) => p.type === 'timeZoneName')?.value ?? ''
    const cleaned = offsetPart.replace('GMT', 'UTC')
    if (cleaned) return cleaned
  } catch {
    // ignore and return fallback
  }
  return 'UTC offset unavailable'
}

export function getTimezoneNowLabel(timeZone: string, date = new Date()): string {
  try {
    return new Intl.DateTimeFormat('en-GB', {
      timeZone,
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hour12: false,
    }).format(date)
  } catch {
    return 'Time unavailable'
  }
}

// Clock times the way people say them. The server speaks "HH:MM" (24-hour,
// zero-padded); an owner types "7am", "3:30 pm" or "15:00" and reads
// "7:00 AM – 3:00 PM". Both directions live here so every screen agrees.

/** "07:00" → "7:00 AM"; "15:30" → "3:30 PM"; "00:00" → "12:00 AM". */
export function to12(hhmm: string): string {
  const [h = '0', m = '00'] = hhmm.split(':')
  const hour = Number(h)
  if (!Number.isInteger(hour) || hour < 0 || hour > 23) return hhmm
  const twelve = hour % 12 === 0 ? 12 : hour % 12
  return `${twelve}:${m.padStart(2, '0').slice(0, 2)} ${hour < 12 ? 'AM' : 'PM'}`
}

/**
 * What a person typed → "HH:MM", or null when it is not a time. Accepts
 * "7", "7am", "7 a.m.", "7:30pm", "3p", "15:00", "noon", "midnight". A bare
 * number with no AM/PM is read as the 24-hour clock ("7" is 7 AM, "15" is
 * 3 PM), which is how a night auditor writes "23".
 */
export function parseClock(text: string): string | null {
  const s = text.trim().toLowerCase().replace(/\./g, '')
  if (s === '') return null
  if (s === 'noon' || s === 'midday') return '12:00'
  if (s === 'midnight') return '00:00'
  const m = /^(\d{1,2})(?::?(\d{2}))?\s*(a|am|p|pm)?$/.exec(s)
  if (m === null) return null
  let hour = Number(m[1])
  const minute = m[2] === undefined ? 0 : Number(m[2])
  const suffix = m[3]
  if (minute > 59) return null
  if (suffix !== undefined) {
    if (hour < 1 || hour > 12) return null
    if (suffix.startsWith('p') && hour !== 12) hour += 12
    if (suffix.startsWith('a') && hour === 12) hour = 0
  } else if (hour > 23) {
    return null
  }
  return `${String(hour).padStart(2, '0')}:${String(minute).padStart(2, '0')}`
}

/** "7:00 AM – 3:00 PM"; "11:00 PM – 7:00 AM (+1)"; "9:00 AM – Done". */
export function shiftText(
  start: string,
  end: string,
  crossesMidnight: boolean,
  untilDone = false,
): string {
  if (untilDone) return `${to12(start)} – Done`
  return `${to12(start)} – ${to12(end)}${crossesMidnight ? ' (+1)' : ''}`
}

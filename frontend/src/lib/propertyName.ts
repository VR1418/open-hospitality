// What an owner calls their hotel, from what the registry stores.
//
// The registry keeps the name as it is PRINTED on the reports, which is
// upper-case ("REDSTONE TEST INN, TX"), because that is what the detector
// matches against. Shouting it back at the owner is not what they call the
// place, so it is title-cased for display — in one module, because the top
// bar, the hotel dashboard and the all-hotels overview must agree.

import type { PropertyInfo } from '../api/types'

/** Title-case a registry name: "HOLIDAY INN & SUITES SAN JOSE" ->
 *  "Holiday Inn & Suites San Jose". */
export function titleCase(name: string): string {
  return name.toLowerCase().replace(/(^|[\s(/-])[a-z]/g, (m) => m.toUpperCase())
}

/** The hotel's name, or its code when the registry has no row for it — never
 *  the PMS identifier, which means nothing to the person reading it. */
export function propertyDisplayName(p: PropertyInfo | undefined): string | null {
  if (p === undefined) return null
  return p.name === null ? p.property_id : titleCase(p.name)
}

/** Name and code together, for a picker where two hotels could share a name
 *  ("Redstone Test Inn · RTI22"). */
export function propertyLabel(p: PropertyInfo): string {
  const name = propertyDisplayName(p)
  return name === null || name === p.property_id ? p.property_id : `${name} · ${p.property_id}`
}

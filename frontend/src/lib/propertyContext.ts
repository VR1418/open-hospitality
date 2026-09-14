// Global property selection: picked once in the top bar, consumed everywhere.
// The provider lives in Layout; `useGlobalProperty` FALLS BACK to page-local
// state when no provider is mounted, so pages render standalone in tests
// without wrapping. The choice persists per browser (localStorage).

import { createContext, useContext, useState } from 'react'
import { useQuery } from '@tanstack/react-query'

import { getProperties } from '../api/client'
import type { PropertyInfo } from '../api/types'
import { getWelcome, type WelcomeState } from '../api/desktop'

const STORAGE_KEY = 'usali.property'

export type GlobalProperty = {
  /** Selected property id; defaults to the first visible property. */
  property: string | undefined
  setProperty: (id: string) => void
  properties: PropertyInfo[] | undefined
  /** The full record for the selected property. */
  selected: PropertyInfo | undefined
}

export const GlobalPropertyContext = createContext<GlobalProperty | null>(null)

/** Desktop edition: every hotel the owner set up, not only those with
 * reports. `/api/properties` lists hotels by their promoted facts, so a hotel
 * added an hour ago — with no night audit read yet — was missing from every
 * picker until its first report landed, and the owner thought the setup had
 * failed. The wizard's own list fills the gap; a hotel with no facts gets
 * today as its only date, so date pickers have a sane window. */
export function withEveryHotel(
  facts: PropertyInfo[] | undefined,
  welcome: WelcomeState | null | undefined,
): PropertyInfo[] | undefined {
  if (facts === undefined) return undefined
  if (welcome === null || welcome === undefined) return facts
  const known = new Set(facts.map((p) => p.property_id))
  const today = new Date().toISOString().slice(0, 10)
  const extra = welcome.properties
    .filter((h) => !known.has(h.property_id))
    .map<PropertyInfo>((h) => ({
      property_id: h.property_id,
      pms_source: h.pms_source,
      first_date: today,
      last_date: today,
      name: h.name,
    }))
  return extra.length === 0 ? facts : [...facts, ...extra]
}

export function usePropertyState(persist: boolean): GlobalProperty {
  const propertiesQuery = useQuery({ queryKey: ['properties'], queryFn: getProperties })
  // Null on a hosted deployment (the route 404s); the list above then stands alone.
  const welcomeQuery = useQuery({ queryKey: ['welcome'], queryFn: getWelcome, retry: false })
  const [picked, setPicked] = useState<string | undefined>(() =>
    persist ? (localStorage.getItem(STORAGE_KEY) ?? undefined) : undefined,
  )
  const properties = withEveryHotel(propertiesQuery.data, welcomeQuery.data)
  // A persisted id that no longer exists (scope change, wiped DB) falls back
  // to the first visible property instead of wedging every page on a 403.
  const valid = picked !== undefined && properties?.some((p) => p.property_id === picked)
  const property = valid ? picked : properties?.[0]?.property_id
  return {
    property,
    setProperty: (id: string) => {
      setPicked(id)
      if (persist) localStorage.setItem(STORAGE_KEY, id)
    },
    properties,
    selected: properties?.find((p) => p.property_id === property),
  }
}

export function useGlobalProperty(): GlobalProperty {
  const ctx = useContext(GlobalPropertyContext)
  // Fallback keeps hook order stable: the state hook always runs, and is
  // simply ignored when a provider is present.
  const fallback = usePropertyState(false)
  return ctx ?? fallback
}

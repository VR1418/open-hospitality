// Desktop edition API (docs/desktop/adr/adr-d3-module-gating.md). Kept apart
// from client.ts/types.ts so upstream's files stay untouched; the header
// seam (bearer + active org) is upstream's own authHeaders.
import { authHeaders } from './client'

export type ModuleLimitation = { text: string; workaround: string | null }

export type DesktopModule = {
  id: string
  name: string
  summary: string
  status: 'available' | 'coming_soon'
  required: boolean
  enabled: boolean
  nav: string[]
  limitations: ModuleLimitation[]
}

export type ModulesResponse = { modules: DesktopModule[]; reloading: boolean }

async function detail(res: Response): Promise<string> {
  const body: unknown = await res.json().catch(() => ({}))
  const d = (body as { detail?: unknown }).detail
  return typeof d === 'string' ? d : `request failed (${res.status})`
}

/** The modules this install serves. A hosted deployment has no such route,
 * so a 404 here means "not the desktop edition" — callers treat it as null. */
export async function getModules(): Promise<ModulesResponse | null> {
  const res = await fetch('/api/me/modules', { headers: await authHeaders() })
  if (res.status === 404) return null
  if (!res.ok) throw new Error(await detail(res))
  return (await res.json()) as ModulesResponse
}

export async function saveModules(enabled: string[]): Promise<ModulesResponse> {
  const res = await fetch('/api/desktop/modules', {
    method: 'PUT',
    headers: await authHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ enabled }),
  })
  if (!res.ok) throw new Error(await detail(res))
  return (await res.json()) as ModulesResponse
}

/** Nav paths belonging to modules that are OFF. Hiding them is a courtesy —
 * those routes are not mounted, which is the enforcement. */
export function hiddenPaths(modules: DesktopModule[] | undefined): Set<string> {
  const hidden = new Set<string>()
  const shown = new Set<string>()
  for (const m of modules ?? []) {
    for (const path of m.nav) (m.enabled ? shown : hidden).add(path)
  }
  for (const path of shown) hidden.delete(path)
  return hidden
}

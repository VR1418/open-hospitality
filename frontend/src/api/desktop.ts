// Desktop edition API (docs/desktop/adr/adr-d3-module-gating.md). Kept apart
// from client.ts/types.ts so upstream's files stay untouched; the header
// seam (bearer + active org) is upstream's own authHeaders.
import { authHeaders, redirectToLogin } from './client'

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

/** The server's refusal, which names the next step (accounts_api.py). A
 * request-shape 422 carries a list, not a sentence; its first message is the
 * most useful thing we have. */
async function detail(res: Response): Promise<string> {
  const body: unknown = await res.json().catch(() => ({}))
  const d = (body as { detail?: unknown }).detail
  if (typeof d === 'string') return d
  if (Array.isArray(d) && typeof (d[0] as { msg?: unknown } | undefined)?.msg === 'string') {
    return (d[0] as { msg: string }).msg
  }
  return `request failed (${res.status})`
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

function sameSet(a: string[], b: string[]): boolean {
  return a.length === b.length && a.every((x) => b.includes(x))
}

/** After a module change the local server rebuilds itself; ask until it
 * answers with the new set mounted (a few seconds at most). */
export async function waitForModules(enabled: string[]): Promise<void> {
  for (let i = 0; i < 40; i++) {
    await new Promise((resolve) => setTimeout(resolve, 500))
    try {
      const now = await getModules()
      const on = (now?.modules ?? []).filter((m) => m.enabled).map((m) => m.id)
      if (sameSet(on, enabled)) return
    } catch {
      // The server is between builds; keep asking.
    }
  }
  throw new Error('Open Hospitality is taking longer than usual to switch. Reload this page.')
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

// --- Local sign-in (src/usali/desktop/accounts_api.py, PRD 6.2) -------------

/** What "Your sign-ins" calls this device: "Chrome on Windows". Only a label
 * the person reads back; nothing trusts it. */
export function deviceLabel(ua: string = navigator.userAgent): string {
  const browser = /Edg\//.test(ua)
    ? 'Edge'
    : /Firefox\//.test(ua)
      ? 'Firefox'
      : /Chrome\//.test(ua)
        ? 'Chrome'
        : /Safari\//.test(ua)
          ? 'Safari'
          : 'A browser'
  // iPad and Android user agents also say "Mac OS X" and "Linux".
  const os = /iPhone|iPad/.test(ua)
    ? 'iPhone or iPad'
    : /Android/.test(ua)
      ? 'Android'
      : /Windows/.test(ua)
        ? 'Windows'
        : /Macintosh|Mac OS X/.test(ua)
          ? 'Mac'
          : /Linux/.test(ua)
            ? 'Linux'
            : null
  return os === null ? browser : `${browser} on ${os}`
}

export type DesktopToken = {
  access_token: string
  expires_in: number
  /** Only from owner setup and recovery: shown once, never stored. */
  recovery_code: string | null
}

async function publicPost(path: string, body: Record<string, string>): Promise<DesktopToken> {
  const res = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ...body, device_label: deviceLabel() }),
  })
  if (!res.ok) throw new Error(await detail(res))
  return (await res.json()) as DesktopToken
}

/** True until this install has its owner. */
export async function getSetupRequired(): Promise<boolean> {
  const res = await fetch('/api/desktop/status')
  if (!res.ok) throw new Error(await detail(res))
  return ((await res.json()) as { setup_required: boolean }).setup_required
}

export function setUpOwner(body: {
  code: string
  full_name: string
  email: string
  password: string
}): Promise<DesktopToken> {
  return publicPost('/api/desktop/setup/owner', body)
}

export function signIn(body: { login: string; password: string }): Promise<DesktopToken> {
  return publicPost('/api/desktop/signin', body)
}

export function redeemSetupCode(body: {
  login: string
  code: string
  new_password: string
}): Promise<DesktopToken> {
  return publicPost('/api/desktop/setup-code', body)
}

export function recover(body: {
  login: string
  recovery_code: string
  new_password: string
}): Promise<DesktopToken> {
  return publicPost('/api/desktop/recover', body)
}

/** A signed-in call. A 401 from the session gate means this device was
 * signed out (or its session ran out), so it goes back to the sign-in page —
 * except where the endpoint itself answers 401 for a wrong password. */
async function signedIn(
  path: string,
  init: RequestInit = {},
  { redirectOn401 = true }: { redirectOn401?: boolean } = {},
): Promise<Response> {
  const res = await fetch(path, { ...init, headers: await authHeaders(init.headers) })
  if (res.status === 401 && redirectOn401) redirectToLogin()
  if (!res.ok) throw new Error(await detail(res))
  return res
}

export type DesktopSession = {
  session_id: string
  device_label: string
  created_at: string
  last_seen_at: string
  current: boolean
}

export async function getSessions(): Promise<DesktopSession[]> {
  return (await (await signedIn('/api/desktop/sessions')).json()) as DesktopSession[]
}

export async function signOutDevice(sessionId: string): Promise<void> {
  await signedIn(`/api/desktop/sessions/${encodeURIComponent(sessionId)}`, { method: 'DELETE' })
}

/** Signs this person's OTHER devices out; this one stays signed in. */
export async function changePassword(currentPassword: string, newPassword: string): Promise<void> {
  await signedIn(
    '/api/desktop/password',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
    },
    { redirectOn401: false },
  )
}

export type DesktopAccount = {
  subject: string
  full_name: string
  username: string
  email: string | null
  roles: string[]
  enabled: boolean
  has_password: boolean
  is_owner: boolean
}

/** Owner only: everyone who can sign in to this install. */
export async function getAccounts(): Promise<DesktopAccount[]> {
  return (await (await signedIn('/api/desktop/accounts')).json()) as DesktopAccount[]
}

export type SetupCode = { setup_code: string; valid_for_hours: number }

/** Owner only: a one-time code the person uses to set (or reset) their password. */
export async function giveSetupCode(subject: string): Promise<SetupCode> {
  const res = await signedIn(`/api/desktop/accounts/${encodeURIComponent(subject)}/setup-code`, {
    method: 'POST',
  })
  return (await res.json()) as SetupCode
}

// --- First-run wizard (src/usali/desktop/welcome_api.py) --------------------

export type WelcomeProperty = {
  property_id: string
  name: string
  pms_source: string
  has_fiscal_calendar: boolean
  has_rooms: boolean
}

/** A PMS this install can read, from the engine's own detection registry. */
export type PmsChoice = { id: string; name: string }

export type WelcomeState = {
  finished: boolean
  group_name: string
  /** False while the hotel group still has the name a fresh install gives it. */
  group_named: boolean
  properties: WelcomeProperty[]
  pms_choices: PmsChoice[]
}

/** The wizard's progress. Null on a hosted deployment, which has no such
 * route — so nothing there is ever sent to the wizard. */
export async function getWelcome(): Promise<WelcomeState | null> {
  const res = await fetch('/api/desktop/welcome', { headers: await authHeaders() })
  if (res.status === 404) return null
  if (res.status === 401) redirectToLogin()
  if (!res.ok) throw new Error(await detail(res))
  return (await res.json()) as WelcomeState
}

export async function nameGroup(name: string): Promise<void> {
  await signedIn('/api/desktop/welcome/group', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name }),
  })
}

export type FiscalChoice = {
  calendar_type: 'calendar_month' | '445'
  fiscal_year_start_month: number
  /** 0 = Monday … 6 = Sunday; only for a 4-4-5 calendar. */
  week_start_weekday: number | null
}

export type NewHotel = {
  name: string
  /** The hotel's name as the PMS prints it at the top of its reports. */
  report_name: string
  pms_source: string
  total_rooms: number
  timezone: string
  fiscal: FiscalChoice
}

/** One request: the property, the name its reports are recognised by, its
 * rooms and its fiscal calendar are saved together or not at all. */
export async function addHotel(body: NewHotel): Promise<{ property_id: string; name: string }> {
  const res = await signedIn('/api/desktop/welcome/property', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  return (await res.json()) as { property_id: string; name: string }
}

export async function finishWelcome(): Promise<void> {
  await signedIn('/api/desktop/welcome/finish', { method: 'POST' })
}

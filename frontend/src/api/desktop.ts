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
  /** The company that owns it, when the owner gave one. */
  ownership_entity: string | null
  has_fiscal_calendar: boolean
  has_rooms: boolean
}

/** A PMS this install can read, from the engine's own detection registry. */
export type PmsChoice = {
  id: string
  name: string
  /** Its reports print the hotel's code, so the code alone recognises them. */
  prints_code: boolean
}

export type WelcomeState = {
  finished: boolean
  group_name: string
  /** False while the hotel group still has the name a fresh install gives it. */
  group_named: boolean
  /** False until the owner has chosen where backups go (PRD I-6). */
  backup_folder_set: boolean
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
  /** The company that owns the hotel. */
  ownership_entity: string
  name: string
  /** The hotel's code (NM236) — becomes its id everywhere. */
  code: string
  /** How its reports name it, only for systems that print no code. Blank
   *  means the code (or the name). */
  report_name: string
  pms_source: string
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

// --- All hotels at a glance (src/usali/desktop/portfolio_api.py) ------------

export type PortfolioStaff = { staff: number; on_clock: number; timecards_to_approve: number }

export type PortfolioHotel = {
  property_id: string
  name: string
  pms_source: string
  /** in: the day's reports are read; missing: not yet; error: read but unusable. */
  status: 'in' | 'missing' | 'error'
  note: string | null
  revenue: string | null
  occupancy_pct: string | null
  adr: string | null
  revpar: string | null
  rooms_occupied: string | null
  rooms_total: string | null
  month_revenue: string | null
  month_labour_cost: string | null
  staff: PortfolioStaff | null
}

export type PortfolioTotals = {
  hotels: number
  hotels_in: number
  revenue: string | null
  occupancy_pct: string | null
  adr: string | null
  revpar: string | null
  month_revenue: string | null
  month_labour_cost: string | null
  month_labour_pct: string | null
  staff: PortfolioStaff | null
}

export type TrendPoint = {
  business_date: string
  /** Total across the hotels, from the reports read; null on a day none reported. */
  revenue: string | null
}

export type Finding = {
  property_id: string
  hotel: string
  kind:
    | 'no_reports'
    | 'missing_report'
    | 'check_failed'
    | 'not_in_books'
    | 'codes_to_confirm'
  label: string
  detail: string
  delta: string | null
}

export type Portfolio = {
  business_date: string | null
  month_start: string | null
  /** True when Payroll & People is on: the staff figures are filled in. */
  staff_shown: boolean
  hotels: PortfolioHotel[]
  totals: PortfolioTotals
  /** The fortnight ending on business_date, oldest first. */
  trend: TrendPoint[]
  findings: Finding[]
}

// --- Updates (src/usali/desktop/update_api.py) ------------------------------

export type UpdateStatus = {
  /** False until somewhere is published for the app to look. */
  configured: boolean
  current: string
  latest: string | null
  url: string | null
  notes: string | null
  checked_at: string | null
  error: string | null
  update_available: boolean
}

export async function getUpdate(): Promise<UpdateStatus | null> {
  const res = await fetch('/api/desktop/update', { headers: await authHeaders() })
  if (res.status === 404) return null
  if (res.status === 401) redirectToLogin()
  if (!res.ok) throw new Error(await detail(res))
  return (await res.json()) as UpdateStatus
}

export async function checkForUpdate(): Promise<UpdateStatus> {
  const res = await signedIn('/api/desktop/update/check', { method: 'POST' })
  return (await res.json()) as UpdateStatus
}

// --- Backups (src/usali/desktop/backup_api.py, ADR-D4) ---------------------

export type BackupFile = {
  name: string
  size_mb: number
  taken_at: string | null
  app_version: string | null
  readable: boolean
}

export type BackupStatus = {
  folder: string | null
  suggested_folder: string
  last_backup_at: string | null
  last_file: string | null
  /** True once the recovery code has been confirmed: only then can a backup
   * be opened on another computer. */
  armed: boolean
  /** True when the next start will take one. */
  due: boolean
  keep: number
  files: BackupFile[]
}

export async function getBackupStatus(): Promise<BackupStatus | null> {
  const res = await fetch('/api/desktop/backup', { headers: await authHeaders() })
  if (res.status === 404) return null
  if (res.status === 401) redirectToLogin()
  if (!res.ok) throw new Error(await detail(res))
  return (await res.json()) as BackupStatus
}

export async function setBackupFolder(folder: string): Promise<BackupStatus> {
  const res = await signedIn('/api/desktop/backup', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ folder }),
  })
  return (await res.json()) as BackupStatus
}

/** Confirm the recovery code once, so backups carry a copy of their key
 * wrapped under it. The server checks it before wrapping anything. */
export async function armBackups(recoveryCode: string): Promise<void> {
  await signedIn(
    '/api/desktop/backup/arm',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ recovery_code: recoveryCode }),
    },
    // A refused code is the endpoint's own 401, not a dead session.
    { redirectOn401: false },
  )
}

export async function backupNow(): Promise<{ detail: string }> {
  const res = await signedIn('/api/desktop/backup/now', { method: 'POST' })
  return (await res.json()) as { detail: string }
}

/** Every hotel the caller may see, for one day (default: the latest day any
 * has reports for). Null on a hosted deployment, which has no such route. */
export async function getPortfolio(date?: string): Promise<Portfolio | null> {
  const qs = date ? `?date=${encodeURIComponent(date)}` : ''
  const res = await fetch(`/api/desktop/portfolio${qs}`, { headers: await authHeaders() })
  if (res.status === 404) return null
  if (res.status === 401) redirectToLogin()
  if (!res.ok) throw new Error(await detail(res))
  return (await res.json()) as Portfolio
}

/** One USALI line a transaction code can be put on. Null `schedule_id` is
 * meaningful: it is what puts a code in taxes, settlements or non-operating
 * rather than in a revenue schedule. */
export type CodeLine = {
  schedule_id: number | null
  major: string
  sub: string
  line_item: string
  gl_account_code: string | null
}

export type CodeItem = {
  code: string
  description: string | null
  pms_source: string
  /** unknown — nothing decides it, so its money is not in the books.
   *  unconfirmed — the shipped dictionary guesses, nobody has agreed.
   *  confirmed — somebody here said what it means. */
  status: 'unknown' | 'unconfirmed' | 'confirmed'
  times_seen: number
  amount: string
  first_seen: string
  last_seen: string
  current: CodeLine | null
  decided_by: string | null
  decided_at: string | null
}

export type CodesState = {
  property_id: string
  edition: number
  money_not_in_the_books: string
  settled_count: number
  items: CodeItem[]
}

export type ConfirmResult = {
  code: string
  days_restated: string[]
  facts_written: number
  ledger_refused: Record<string, string>
}

/** Every code this hotel's reports have used. Null on a hosted deployment,
 * which has no such route. */
export async function getCodes(propertyId: string): Promise<CodesState | null> {
  const res = await fetch(`/api/desktop/codes?property=${encodeURIComponent(propertyId)}`, {
    headers: await authHeaders(),
  })
  if (res.status === 404) return null
  if (res.status === 401) redirectToLogin()
  if (!res.ok) throw new Error(await detail(res))
  return (await res.json()) as CodesState
}

/** The lines a code may be put on — the ones this product already knows. */
export async function getCodeLines(): Promise<CodeLine[]> {
  const res = await signedIn('/api/desktop/codes/choices')
  return ((await res.json()) as { lines: CodeLine[] }).lines
}

export async function confirmCode(
  code: string,
  body: {
    property_id: string
    pms_source: string
    line: CodeLine
    note?: string
    /** 'owner' chose it outright; 'ai-accepted' means they accepted what the
     * model suggested. Either way a person clicked, and their name is what
     * the decision records. */
    origin?: 'owner' | 'ai-accepted'
  },
): Promise<ConfirmResult> {
  const res = await signedIn(`/api/desktop/codes/${encodeURIComponent(code)}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  return (await res.json()) as ConfirmResult
}

// --- The owner's own AI helper (PRD §6.3, ADR-D7) ---------------------------
// The key is write-only here and read nowhere: the server returns
// `key_saved`, never the key itself.

export type AiProviderChoice = {
  id: string
  name: string
  needs_address: boolean
  needs_key: boolean
}

export type AiSpend = {
  month_start: string
  calls: number
  /** Null when some of the month's calls could not be priced — an honest
   * "we don't know", never a total that quietly omits them. */
  estimated_cost: string | null
  unpriced_calls: number
  cap: string
  max_calls: number
  stopped: boolean
}

export type AiSettings = {
  provider: string | null
  model: string
  base_url: string | null
  cap: string
  max_calls: number
  price_in: string | null
  price_out: string | null
  key_saved: boolean
  local: boolean
  spend: AiSpend
  providers: AiProviderChoice[]
  /** Which of `services` the saved choice is; null until set up. */
  service: string | null
  services: AiService[]
}

/** A service the owner recognises, and what it fixes for them. */
export type AiService = {
  id: string
  name: string
  provider: string
  base_url: string | null
  address_editable: boolean
  needs_key: boolean
  key_hint: string
  lists_models: boolean
}

export type AiModel = {
  id: string
  name: string
  maker: string
  price_in: string | null
  price_out: string | null
}

export type AiModels = {
  models: AiModel[]
  /** False when OpenRouter's public list couldn't be reached and this is
   *  the short built-in one, with no prices. */
  live: boolean
  recommended: string | null
}

export type AiConnectionCheck = {
  model: string
  said: string
  estimated_cost: string | null
  spend: AiSpend
}

export type AiSettingsIn = {
  provider: string
  model: string
  base_url?: string | null
  cap: string
  max_calls: number
  price_in?: string | null
  price_out?: string | null
  /** Only when setting or replacing it. It goes to this computer's password
   * store and never to the database. */
  key?: string
}

export type AiSuggestion = {
  code: string
  /** Null when the model declined, which it is required to be able to do on
   * tax and capitalisation questions. */
  line: CodeLine | null
  confidence: string
  reason: string
  decline_reason: string | null
  estimated_cost: string | null
  model: string
  spend: AiSpend
}

/** Null when the AI module is off — its routes are then not mounted at all. */
export async function getAiSettings(): Promise<AiSettings | null> {
  const res = await fetch('/api/desktop/ai', { headers: await authHeaders() })
  if (res.status === 404) return null
  if (res.status === 401) redirectToLogin()
  if (!res.ok) throw new Error(await detail(res))
  return (await res.json()) as AiSettings
}

export async function saveAiSettings(body: AiSettingsIn): Promise<AiSettings> {
  const res = await signedIn('/api/desktop/ai', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  return (await res.json()) as AiSettings
}

export async function getAiModels(service: string): Promise<AiModels> {
  const res = await signedIn(`/api/desktop/ai/models?service=${encodeURIComponent(service)}`)
  return (await res.json()) as AiModels
}

export async function checkAiConnection(): Promise<AiConnectionCheck> {
  const res = await signedIn('/api/desktop/ai/test', { method: 'POST' })
  return (await res.json()) as AiConnectionCheck
}

export async function forgetAiKey(): Promise<void> {
  await signedIn('/api/desktop/ai/key', { method: 'DELETE' })
}

export async function suggestCode(body: {
  property_id: string
  pms_source: string
  code: string
}): Promise<AiSuggestion> {
  const res = await signedIn('/api/desktop/ai/suggest', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  return (await res.json()) as AiSuggestion
}

// --- reading a report the product has no parser for (ADR-D7, phase 3) -------

export type AiReadRow = { code: string; description: string; amount: string }

/** A page the model was NOT shown, and the KIND of thing that held it back —
 *  never the thing itself. */
export type AiHeldBack = { page: number; why: string }

export type AiReading = {
  property_id: string
  file: string
  business_date: string | null
  rows: AiReadRow[]
  pages_read: number[]
  held_back: AiHeldBack[]
  decline_reason: string | null
  estimated_cost: string | null
  model: string
  spend: AiSpend
}

export type AiReadApplied = {
  property_id: string
  business_date: string
  staged: number
  unmapped: number
  ledger: string
}

/** Ask the owner's model what charges are on a report we cannot parse.
 *  Stages nothing: the rows come back to be looked at. */
export async function readReportWithAi(
  propertyId: string,
  file: File,
): Promise<AiReading> {
  const form = new FormData()
  form.append('file', file)
  form.append('property', propertyId)
  const res = await signedIn('/api/desktop/ai/read', { method: 'POST', body: form })
  return (await res.json()) as AiReading
}

/** Put the rows a person accepted into the books. */
export async function confirmAiReading(body: {
  property_id: string
  file: string
  business_date: string
  rows: AiReadRow[]
}): Promise<AiReadApplied> {
  const res = await signedIn('/api/desktop/ai/read/confirm', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  return (await res.json()) as AiReadApplied
}

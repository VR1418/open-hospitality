// App shell: collapsible left sidebar (brand, tabbed nav, settings, user
// card) plus a top bar holding the mobile menu button and a search stub.
// Everything is token-based (surface/ink/accent/nav-active) so dark mode
// needs no variants, and the whole chrome is print:hidden — the wall-grid
// print view (SchedulePage) shows ONLY the week grid.
//
// Desktop edition (docs/desktop/): the nav is three tabs — Accounting, the
// main part and first; People (the Payroll & People module); and Ops (the
// modules still to come) — each listing its pages in an owner's words, not
// an accountant's: "Profit and loss", not "SOS"; "Send to QuickBooks", not
// "QBO". Settings sit at the bottom of every tab and never hide, because the
// Setup checklist's badge lives there.
//
// Collapsed mode keeps every control's accessible name: labels go sr-only
// (never unmounted), so tests and screen readers see the same nav. The Setup
// link is the one nav entry whose accessible name carries data — match it
// with { name: /^Setup checklist/ } unless you are pinning the count.

import { useEffect, useState, type ComponentType, type SVGProps } from 'react'
import { Link, Outlet, useNavigate, useRouterState } from '@tanstack/react-router'
import { useQuery } from '@tanstack/react-query'

import { currentTheme, toggleTheme, type Theme } from './lib/theme'
import { GlobalPropertyProvider } from './lib/GlobalPropertyProvider'
import { useGlobalProperty } from './lib/propertyContext'
import { hasRole } from './lib/roles'
import { badgeLabel, useChecklist, type ChecklistBadge } from './lib/useChecklist'
import { useAuth } from './auth/authContext'
import { getMe } from './api/client'
import { getModules, getWelcome, hiddenPaths } from './api/desktop'
import type { Me } from './api/types'
import BuildStamp from './components/BuildStamp'
import OrgPicker from './components/OrgPicker'
import { badgeToneClasses } from './lib/badgeTones'
import {
  BankIcon,
  BanknoteIcon,
  CalendarIcon,
  ChecklistIcon,
  ClockIcon,
  CloseIcon,
  CollapseIcon,
  CoverageIcon,
  ExpandIcon,
  FileIcon,
  GaugeIcon,
  GridIcon,
  KioskIcon,
  LogoutIcon,
  MenuIcon,
  MoonIcon,
  PeopleIcon,
  ReportsIcon,
  SearchIcon,
  StatementIcon,
  SyncIcon,
  TrendUpIcon,
  UploadIcon,
  UserIcon,
} from './components/icons'

type IconComponent = ComponentType<SVGProps<SVGSVGElement>>

const COLLAPSED_KEY = 'usali.sidebar-collapsed'

// The one nav entry that carries a badge, so the route is named once rather
// than spelled twice — the settings item and the render-time match.
const SETUP_PATH = '/setup'

// `show` gates by role exactly as the old top bar did — the link is a
// convenience; enforcement stays server-side. `soon` renders a muted,
// non-interactive placeholder, and does NOT exempt an item from `show`.
type NavItem = {
  label: string
  icon: IconComponent
  to?: string
  exact?: boolean
  soon?: boolean
  show?: (me: Me | undefined) => boolean
  // Desktop edition only: shown when /api/me/modules answers (ADR-D3).
  desktopOnly?: boolean
}

type TabId = 'accounting' | 'people' | 'ops'

type NavTab = {
  id: TabId
  label: string
  icon: IconComponent
  items: NavItem[]
}

const isScheduler = (me: Me | undefined) => hasRole(me, 'org_admin', 'property_gm')
const isPayroll = (me: Me | undefined) => hasRole(me, 'payroll_admin')
// org_admin ONLY: the API is require_grants(ORG_ADMIN), stricter than
// isScheduler, and a nav entry is a promise about what this account can do.
const isOrgAdmin = (me: Me | undefined) => hasRole(me, 'org_admin')

// The main part, first, and the tab anything outside the tabs falls back to.
const ACCOUNTING_TAB: NavTab = {
  id: 'accounting',
  label: 'Accounting',
  icon: StatementIcon,
  items: [
    { to: '/overview', label: 'Overview', icon: GaugeIcon, desktopOnly: true },
    { to: '/dashboard', label: 'Hotel dashboard', icon: GaugeIcon },
    { to: '/sos', label: 'Profit and loss', icon: StatementIcon, exact: true },
    { to: '/performance', label: 'Occupancy and rates', icon: TrendUpIcon },
    { to: '/night-audit', label: 'Close the day', icon: MoonIcon, show: isScheduler },
    { to: '/upload', label: 'Add reports', icon: UploadIcon },
    {
      to: '/codes',
      label: 'Codes to confirm',
      icon: CoverageIcon,
      desktopOnly: true,
      show: isOrgAdmin,
    },
    { to: '/gl', label: 'Books', icon: BankIcon },
    { to: '/reports', label: 'For your accountant', icon: ReportsIcon },
    { to: '/qbo', label: 'Send to QuickBooks', icon: SyncIcon },
  ],
}

const TABS: NavTab[] = [
  ACCOUNTING_TAB,
  {
    id: 'people',
    label: 'People',
    icon: PeopleIcon,
    items: [
      { to: '/payroll-dashboard', label: 'Staff and labour', icon: GridIcon },
      { to: '/employees', label: 'Staff', icon: PeopleIcon, show: isScheduler },
      { to: '/schedule', label: 'Schedule', icon: CalendarIcon, show: isScheduler },
      { to: '/timecards', label: 'Timecards', icon: ClockIcon, show: isScheduler },
      { to: '/payroll', label: 'Pay runs', icon: BanknoteIcon, show: isPayroll },
      { to: '/kiosk-devices', label: 'Time clock tablets', icon: KioskIcon, show: isScheduler },
      { to: '/kiosk', label: 'Time clock screen', icon: KioskIcon },
    ],
  },
  {
    id: 'ops',
    label: 'Ops',
    icon: ChecklistIcon,
    // The Hotel Management Utilities module (usali.desktop.modules): shown so
    // an owner can see where it's going, never selectable.
    items: [
      { label: 'Housekeeping board', icon: ChecklistIcon, soon: true },
      { label: 'Maintenance tickets', icon: FileIcon, soon: true },
      { label: 'Documents', icon: FileIcon, soon: true },
      { label: 'Vendors', icon: PeopleIcon, soon: true },
      { label: 'Guest demand', icon: TrendUpIcon, soon: true },
    ],
  },
]

// No `show` on Setup: reading the checklist needs only the router's
// operator gate; the dismiss controls inside are gated separately.
const SETTINGS: NavItem[] = [
  { to: SETUP_PATH, label: 'Setup checklist', icon: ChecklistIcon },
  { to: '/property-config', label: 'Your hotels', icon: FileIcon, show: isScheduler },
  { to: '/backups', label: 'Backups', icon: FileIcon, desktopOnly: true },
  { to: '/updates', label: 'Updates', icon: SyncIcon, desktopOnly: true },
  { to: '/modules', label: 'Modules', icon: GridIcon, desktopOnly: true },
  { to: '/integrations', label: 'Connections', icon: SyncIcon, show: isOrgAdmin },
  { to: '/coverage', label: 'Report codes', icon: CoverageIcon },
  { to: '/account', label: 'Sign-in and security', icon: UserIcon, desktopOnly: true },
]

/** The tab a page belongs to, or null for pages outside the tabs (settings). */
function tabForPath(pathname: string): TabId | null {
  return TABS.find((t) => t.items.some((i) => i.to === pathname))?.id ?? null
}

const ROLE_LABELS: [string, string][] = [
  ['org_admin', 'Owner'],
  ['property_gm', 'Hotel manager'],
  ['payroll_admin', 'Payroll manager'],
  ['accountant', 'Bookkeeper'],
  ['department_manager', 'Department head'],
]

function primaryRoleLabel(me: Me | undefined): string | null {
  if (me === undefined) return null
  const found = ROLE_LABELS.find(([role]) => hasRole(me, role))
  return found === undefined ? null : found[1]
}

// The pill is a glyph: '!' is punctuation and most screen readers announce
// nothing for it at default verbosity, so the sentence goes into the link's
// `aria-label` (see `setupLinkName`) and the pill is hidden from the tree as
// the duplicate it is.
function SetupBadge({ badge, collapsed }: { badge: ChecklistBadge; collapsed: boolean }) {
  return (
    <span
      data-testid="setup-badge"
      aria-hidden="true"
      title={badge.title}
      // Collapsed, the rail centres a single chip per row; an `ml-auto` pill
      // would drag the icon off that centreline, so it sits over the chip's
      // corner instead (`itemBase` is already `relative`).
      className={`rounded-full px-1.5 py-0.5 text-[10px] font-bold ${badgeToneClasses[badge.tone]} ${
        collapsed ? 'absolute right-1 top-0.5' : 'ml-auto'
      }`}
    >
      {badge.text}
    </span>
  )
}

/**
 * The Setup link's accessible name: the visible label first, so Label-in-Name
 * (WCAG 2.5.3) still holds. `aria-label` rather than sr-only text so the name
 * is the same in jsdom and in a browser, and the checklist wording never
 * lands in the document for other suites' `getByText` to trip over.
 */
function setupLinkName(label: string, badge: ChecklistBadge | null): string | undefined {
  return badge === null ? undefined : `${label}: ${badge.title}`
}

function SidebarContent({
  me,
  theme,
  onToggleTheme,
  username,
  onLogout,
  onNavigate,
  collapsed = false,
  onToggleCollapse,
  hidden,
  desktop,
  peopleOff,
  activeTab,
  onPickTab,
}: {
  me: Me | undefined
  hidden: Set<string>
  desktop: boolean
  /** Desktop edition: Payroll & People is turned off. */
  peopleOff: boolean
  activeTab: TabId
  onPickTab: (tab: TabId) => void
  theme: Theme
  onToggleTheme: () => void
  username: string | undefined
  onLogout: () => void
  onNavigate?: () => void
  collapsed?: boolean
  onToggleCollapse?: () => void
}) {
  const roleLabel = primaryRoleLabel(me)
  const initials = (username ?? '?').slice(0, 2).toUpperCase()
  // No badge until the first successful read; a later background failure
  // keeps the last-known count (TanStack retains `data`). The loud failure
  // belongs on /setup.
  const checklist = useChecklist()
  const badge = checklist.data === undefined ? null : badgeLabel(checklist.data)

  const itemBase = `group relative flex w-full items-center gap-2.5 rounded-lg py-[7px] text-sm font-medium transition-colors ${
    collapsed ? 'justify-center px-2' : 'pl-2 pr-2.5'
  }`
  const chipBase = 'grid size-7 shrink-0 place-items-center rounded-md transition-colors'
  const navLink = `${itemBase} text-ink-muted hover:bg-surface-sunken hover:text-ink`
  const navLinkActive = {
    className: `${itemBase} bg-nav-active font-semibold text-nav-active-ink before:absolute before:-left-2 before:top-1/2 before:h-[18px] before:w-[3px] before:-translate-y-1/2 before:rounded-full before:bg-accent`,
  }
  const labelClass = collapsed ? 'sr-only' : 'min-w-0 flex-1 truncate text-left'

  const visible = (items: NavItem[]) =>
    items.filter(
      (e) =>
        (e.show === undefined || e.show(me)) &&
        // Desktop edition: a module that is off takes its pages with it.
        !(e.to !== undefined && hidden.has(e.to)) &&
        (e.desktopOnly !== true || desktop),
    )

  function renderItem(e: NavItem) {
    const IconGlyph = e.icon
    if (e.soon === true || e.to === undefined) {
      return (
        <span
          key={e.label}
          aria-disabled="true"
          title={collapsed ? `${e.label} (coming soon)` : undefined}
          className={`${itemBase} cursor-default text-ink-faint`}
        >
          <span className={chipBase}>
            <IconGlyph className="shrink-0" />
          </span>
          <span className={labelClass}>{e.label}</span>
          {!collapsed && (
            <span className="rounded-full bg-surface-sunken px-1.5 py-0.5 text-[9.5px] font-semibold uppercase tracking-wide">
              Soon
            </span>
          )}
        </span>
      )
    }
    const isSetup = e.to === SETUP_PATH
    return (
      <Link
        key={e.to}
        to={e.to}
        className={navLink}
        activeProps={navLinkActive}
        activeOptions={e.exact === true ? { exact: true } : undefined}
        onClick={onNavigate}
        title={collapsed ? e.label : undefined}
        aria-label={isSetup ? setupLinkName(e.label, badge) : undefined}
      >
        <span className={`${chipBase} group-hover:text-accent`}>
          <IconGlyph className="shrink-0" />
        </span>
        <span className={labelClass}>{e.label}</span>
        {/* Deliberately NOT inside `labelClass`: collapsed, the count is the
            only thing still pointing at setup. */}
        {isSetup && badge !== null && <SetupBadge badge={badge} collapsed={collapsed} />}
      </Link>
    )
  }

  const tab = TABS.find((t) => t.id === activeTab) ?? ACCOUNTING_TAB
  const tabItems = visible(tab.items)
  const settings = visible(SETTINGS)

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div
        className={
          collapsed
            ? 'flex flex-col items-center gap-1 px-2 pb-2 pt-4'
            : 'flex items-start justify-between px-4 pb-2 pt-4'
        }
      >
        <div className={collapsed ? 'text-center' : ''}>
          <span className="block text-lg font-semibold leading-tight tracking-tight">
            <span aria-hidden="true" className="text-accent">
              ◆
            </span>
            <span className={collapsed ? 'sr-only' : ''}>
              {' '}
              <span className="text-accent">Open</span> Hospitality
            </span>
          </span>
          <span
            className={
              collapsed
                ? 'sr-only'
                : 'block pl-5 text-[11px] font-semibold uppercase tracking-widest text-ink-faint'
            }
          >
            Hospitality Ops
          </span>
        </div>
        {onToggleCollapse !== undefined && (
          <button
            type="button"
            aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
            aria-expanded={!collapsed}
            title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
            onClick={onToggleCollapse}
            className="rounded-lg p-1.5 text-ink-faint hover:bg-surface-sunken hover:text-ink"
          >
            {collapsed ? <ExpandIcon /> : <CollapseIcon />}
          </button>
        )}
      </div>

      <div
        role="tablist"
        aria-label="Sections"
        className={
          collapsed
            ? 'flex flex-col items-center gap-1 px-2 pb-2'
            : 'mx-3 mb-2 grid grid-cols-3 gap-1 rounded-lg bg-surface-sunken p-1'
        }
      >
        {TABS.map((t) => {
          const selected = t.id === activeTab
          const TabGlyph = t.icon
          return (
            <button
              key={t.id}
              type="button"
              role="tab"
              id={`nav-tab-${t.id}`}
              aria-selected={selected}
              aria-controls="nav-panel"
              title={collapsed ? t.label : undefined}
              onClick={() => onPickTab(t.id)}
              className={
                collapsed
                  ? `grid size-9 place-items-center rounded-lg ${
                      selected ? 'bg-nav-active text-nav-active-ink' : 'text-ink-muted hover:bg-surface-sunken'
                    }`
                  : `rounded-md px-1 py-1.5 text-xs font-semibold transition-colors ${
                      selected
                        ? 'bg-surface-raised text-ink shadow-card'
                        : 'text-ink-muted hover:text-ink'
                    }`
              }
            >
              {collapsed ? (
                <>
                  <TabGlyph aria-hidden="true" />
                  <span className="sr-only">{t.label}</span>
                </>
              ) : (
                t.label
              )}
            </button>
          )
        })}
      </div>

      <div
        id="nav-panel"
        role="tabpanel"
        aria-labelledby={`nav-tab-${activeTab}`}
        className="flex min-h-0 flex-1 flex-col"
      >
        <nav aria-label="Primary" className="min-h-0 flex-1 overflow-y-auto px-3 pb-2">
          {tab.id === 'people' && peopleOff ? (
            <p className={collapsed ? 'sr-only' : 'px-2 py-2 text-sm text-ink-muted'}>
              Payroll &amp; People is off.{' '}
              <Link to="/modules" className="underline" onClick={onNavigate}>
                Turn it on in Modules
              </Link>
              .
            </p>
          ) : (
            <div className="flex flex-col gap-0.5">{tabItems.map(renderItem)}</div>
          )}
          {tab.id === 'ops' && !collapsed && (
            <p className="px-2 pt-2 text-xs text-ink-faint">Coming in a later version.</p>
          )}

          {settings.length > 0 &&
            (collapsed ? (
              <div aria-hidden="true" className="mx-1 my-3 border-t border-line" />
            ) : (
              <p className="mb-1 mt-5 flex items-center gap-2 px-2 text-[10.5px] font-bold uppercase tracking-[0.14em] text-ink-faint">
                <span aria-hidden="true" className="inline-block size-1.5 rounded-full bg-accent/70" />
                Settings
                <span aria-hidden="true" className="h-px flex-1 bg-line" />
              </p>
            ))}
          <div className="flex flex-col gap-0.5">{settings.map(renderItem)}</div>
        </nav>
      </div>

      <div className="border-t border-line p-3">
        <div
          className={`flex items-center gap-3 rounded-lg border border-line bg-surface p-2.5 ${
            collapsed ? 'flex-col gap-2 p-2' : ''
          }`}
        >
          <span
            aria-hidden="true"
            title={collapsed ? username : undefined}
            className="grid size-9 shrink-0 place-items-center rounded-full bg-accent-soft text-sm font-bold text-accent-ink"
          >
            {initials}
          </span>
          <span className={collapsed ? 'sr-only' : 'min-w-0 flex-1'}>
            <span className="block truncate text-sm font-semibold text-ink">{username ?? '—'}</span>
            <span className="block truncate text-xs text-ink-muted">{roleLabel ?? 'Staff'}</span>
          </span>
          <button
            type="button"
            aria-label="Toggle dark mode"
            aria-pressed={theme === 'dark'}
            title="Toggle dark mode"
            onClick={onToggleTheme}
            className="rounded-full px-1.5 py-0.5 text-base leading-none text-ink-muted hover:bg-surface-sunken hover:text-ink"
          >
            {theme === 'dark' ? '☀' : '☾'}
          </button>
        </div>
        <button
          type="button"
          onClick={onLogout}
          aria-label="Sign out"
          title="Sign out"
          className={`${navLink} mt-1 justify-center`}
        >
          <LogoutIcon className="shrink-0" />
          <span className={collapsed ? 'sr-only' : ''}>Sign out</span>
        </button>
        <BuildStamp collapsed={collapsed} />
      </div>
    </div>
  )
}

function GlobalPropertySelect() {
  const { property, setProperty, properties } = useGlobalProperty()
  if (properties === undefined || properties.length === 0) return null
  return (
    <select
      aria-label="Active property"
      title="Hotel (applies across the app)"
      className="rounded-full border border-line bg-surface px-3 py-1.5 text-sm font-medium text-ink"
      value={property ?? ''}
      onChange={(e) => setProperty(e.target.value)}
    >
      {properties.map((p) => (
        <option key={`${p.property_id}|${p.pms_source}`} value={p.property_id}>
          {p.property_id} — {p.pms_source}
        </option>
      ))}
    </select>
  )
}

export default function Layout() {
  const [theme, setTheme] = useState<Theme>(currentTheme)
  const [menuOpen, setMenuOpen] = useState(false)
  const [collapsed, setCollapsed] = useState<boolean>(
    () => localStorage.getItem(COLLAPSED_KEY) === '1',
  )
  const { user, logout } = useAuth()
  const me = useQuery({ queryKey: ['me'], queryFn: getMe })
  // Desktop edition (ADR-D3): null on a hosted deployment (the route 404s),
  // and a failed read hides nothing — the server's mount is the enforcement.
  const modules = useQuery({ queryKey: ['modules'], queryFn: getModules, retry: false })
  // Desktop edition: until the owner has finished the first-run wizard there
  // is no property for anything to describe, so every page sends them there.
  const welcome = useQuery({
    queryKey: ['welcome'],
    queryFn: getWelcome,
    retry: false,
    enabled: modules.data != null && isOrgAdmin(me.data),
  })
  const navigate = useNavigate()
  useEffect(() => {
    if (welcome.data?.finished === false) void navigate({ to: '/welcome', replace: true })
  }, [welcome.data, navigate])
  const username = user?.profile.preferred_username

  // The tab follows the page you're on; picking a tab only changes the list
  // until you move, so settings pages keep whichever tab you were in.
  const pathname = useRouterState({ select: (s) => s.location.pathname })
  const [picked, setPicked] = useState<{ tab: TabId; at: string } | null>(null)
  const activeTab: TabId =
    picked !== null && picked.at === pathname
      ? picked.tab
      : (tabForPath(pathname) ?? picked?.tab ?? 'accounting')

  function handleToggleCollapse() {
    setCollapsed((prev) => {
      const next = !prev
      localStorage.setItem(COLLAPSED_KEY, next ? '1' : '0')
      return next
    })
  }

  const sidebarProps = {
    me: me.data,
    hidden: hiddenPaths(modules.data?.modules),
    desktop: modules.data != null,
    peopleOff: modules.data?.modules.some((m) => m.id === 'payroll' && !m.enabled) ?? false,
    activeTab,
    onPickTab: (tab: TabId) => setPicked({ tab, at: pathname }),
    theme,
    onToggleTheme: () => setTheme(toggleTheme()),
    username,
    onLogout: () => logout(),
  }

  return (
    <GlobalPropertyProvider>
    <div
      className={`min-h-screen transition-[grid-template-columns] duration-200 md:grid ${
        collapsed ? 'md:grid-cols-[4.75rem_minmax(0,1fr)]' : 'md:grid-cols-[16.5rem_minmax(0,1fr)]'
      }`}
    >
      <aside className="sticky top-0 hidden h-screen border-r border-line bg-surface-raised md:block print:hidden">
        <SidebarContent
          {...sidebarProps}
          collapsed={collapsed}
          onToggleCollapse={handleToggleCollapse}
        />
      </aside>

      {menuOpen && (
        <div className="fixed inset-0 z-40 md:hidden print:hidden">
          <button
            type="button"
            aria-label="Close menu"
            className="absolute inset-0 bg-scrim"
            onClick={() => setMenuOpen(false)}
          />
          <div className="absolute inset-y-0 left-0 flex w-72 max-w-[85vw] flex-col bg-surface-raised shadow-overlay">
            <div className="flex justify-end p-2">
              <button
                type="button"
                aria-label="Close menu"
                onClick={() => setMenuOpen(false)}
                className="rounded-lg p-2 text-ink-muted hover:bg-surface-sunken hover:text-ink"
              >
                <CloseIcon />
              </button>
            </div>
            <div className="min-h-0 flex-1">
              <SidebarContent {...sidebarProps} onNavigate={() => setMenuOpen(false)} />
            </div>
          </div>
        </div>
      )}

      <div className="min-w-0">
        <header className="flex items-center gap-3 border-b border-line bg-surface-raised px-4 py-2.5 md:px-6 print:hidden">
          <button
            type="button"
            aria-label="Open menu"
            onClick={() => setMenuOpen(true)}
            className="rounded-lg p-2 text-ink-muted hover:bg-surface-sunken hover:text-ink md:hidden"
          >
            <MenuIcon />
          </button>
          {/* Search is a visual stub until a search API exists. */}
          <div className="relative max-w-md flex-1">
            <span className="pointer-events-none absolute inset-y-0 left-3 flex items-center text-ink-faint">
              <SearchIcon />
            </span>
            <input
              type="search"
              disabled
              aria-label="Search"
              title="Search is coming soon"
              placeholder="Search staff, reports… (soon)"
              className="w-full rounded-full border border-line bg-surface py-1.5 pl-10 pr-4 text-sm text-ink placeholder:text-ink-faint disabled:cursor-not-allowed"
            />
          </div>
          {/* Active org then property — the two selectors that scope every
              page, outermost first: an org switch invalidates the property. */}
          <div className="ml-auto flex items-center gap-3">
            <OrgPicker />
            <GlobalPropertySelect />
            {/* Pages portal their contextual filters here. */}
            <div id="topbar-slot" className="flex items-center gap-3" />
          </div>
        </header>
        <main className="mx-auto w-full max-w-[96rem] px-6 py-6">
          <Outlet />
        </main>
      </div>
    </div>
    </GlobalPropertyProvider>
  )
}

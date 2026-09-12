// Smoke tests on the nav shell: the router renders the layout with its
// tabbed nav (Accounting, People, Ops) and the Profit and loss page at
// `/sos`, plus the dark-mode toggle and the role gating on individual
// entries. Also covers the entry route `/`, which restores the last visited
// page and falls back to the dashboard on a first visit. The second describe
// covers the Setup checklist entry and its badge; the third, the desktop
// edition's module-aware tabs.

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createMemoryHistory, RouterProvider } from '@tanstack/react-router'

vi.mock('./api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('./api/client')>()),
  getMe: vi.fn(),
}))

vi.mock('./api/checklist', () => ({
  getChecklist: vi.fn(),
  dismissItem: vi.fn(),
  restoreItem: vi.fn(),
}))

// Hosted by default (no desktop routes answer); the desktop describe below
// makes them answer.
vi.mock('./api/desktop', async (importOriginal) => ({
  ...(await importOriginal<typeof import('./api/desktop')>()),
  getModules: vi.fn(),
  getWelcome: vi.fn(),
}))

import { getMe } from './api/client'
import { getChecklist } from './api/checklist'
import { getModules, getWelcome, type DesktopModule } from './api/desktop'
import { createAppRouter } from './router'
import type { Checklist } from './api/types'
import { CHECKLIST_KEY } from './lib/useChecklist'
import { AuthContext, type AuthContextValue } from './auth/authContext'
import { AUTHED_CONTEXT } from './test/fixtures'

function renderApp(auth: AuthContextValue = AUTHED_CONTEXT, initialPath = '/sos') {
  const router = createAppRouter(createMemoryHistory({ initialEntries: [initialPath] }))
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={queryClient}>
      <AuthContext.Provider value={auth}>
        <RouterProvider router={router} />
      </AuthContext.Provider>
    </QueryClientProvider>,
  )
  // Returned so a test can anchor on the query's own state rather than on a
  // link that is already in the DOM, and can drive a refetch.
  return queryClient
}

async function openTab(name: 'Accounting' | 'People' | 'Ops') {
  await userEvent.click(await screen.findByRole('tab', { name }))
}

// File-scoped rather than per-describe: the sidebar reads the checklist on
// every authenticated page, so every test in this file mounts that query and
// an unstubbed one would resolve undefined. `all_clear` by default so the
// badge stays out of the way of the tests that are not about it.
beforeEach(() => {
  vi.mocked(getMe).mockResolvedValue({ subject: '', username: '', roles: [] })
  vi.mocked(getChecklist).mockResolvedValue({
    items: [],
    open_count: 0,
    error_count: 0,
    all_clear: true,
  })
  vi.mocked(getModules).mockResolvedValue(null)
  vi.mocked(getWelcome).mockResolvedValue(null)
})

afterEach(() => {
  document.documentElement.classList.remove('dark')
  localStorage.clear()
})

describe('app shell', () => {
  it('renders the nav in plain words and the Profit and loss page at /sos', async () => {
    renderApp()
    // The Open Hospitality wordmark rides the header — "Open" is the
    // accented span, "Hospitality" the trailing text node.
    expect(await screen.findByText('Open')).toBeInTheDocument()
    expect(screen.getAllByText(/Hospitality/).length).toBeGreaterThan(0)
    // Accounting is the main part: it is the tab a Profit and loss page opens.
    expect(await screen.findByRole('tab', { name: 'Accounting' })).toHaveAttribute(
      'aria-selected',
      'true',
    )
    expect(await screen.findByRole('link', { name: 'Profit and loss' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Add reports' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'For your accountant' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Send to QuickBooks' })).toBeInTheDocument()
    // Accountant's set-up work lives under Settings, in the owner's words.
    expect(screen.getByRole('link', { name: 'Report codes' })).toBeInTheDocument()
    // No accountant's jargon in the menu.
    expect(screen.queryByRole('link', { name: 'SOS' })).toBeNull()
    expect(screen.queryByRole('link', { name: 'QBO' })).toBeNull()
    expect(await screen.findByRole('heading', { name: 'Profit and loss' })).toBeInTheDocument()
  })

  it('opens the dashboard at / on a first visit', async () => {
    localStorage.clear() // nothing remembered — a genuine first load
    renderApp(AUTHED_CONTEXT, '/')
    expect(await screen.findByRole('heading', { name: 'Hotel overview' })).toBeInTheDocument()
  })

  it('restores the last visited page at /', async () => {
    localStorage.setItem('usali.last-route', '/upload')
    renderApp(AUTHED_CONTEXT, '/')
    expect(await screen.findByRole('heading', { name: 'Add reports' })).toBeInTheDocument()
  })

  it('remembers the page you are on so the next / lands there', async () => {
    localStorage.clear()
    renderApp(AUTHED_CONTEXT, '/upload')
    await screen.findByRole('heading', { name: 'Add reports' })
    expect(localStorage.getItem('usali.last-route')).toBe('/upload')
  })

  it('dark-mode toggle flips the root class, aria-pressed, and back', async () => {
    renderApp()
    const toggle = await screen.findByRole('button', { name: 'Toggle dark mode' })
    expect(document.documentElement.classList.contains('dark')).toBe(false)
    expect(toggle).toHaveAttribute('aria-pressed', 'false')

    fireEvent.click(toggle)
    expect(document.documentElement.classList.contains('dark')).toBe(true)
    expect(toggle).toHaveAttribute('aria-pressed', 'true')

    fireEvent.click(toggle)
    expect(document.documentElement.classList.contains('dark')).toBe(false)
    expect(toggle).toHaveAttribute('aria-pressed', 'false')
  })

  it('Sign out button invokes logout', async () => {
    const logout = vi.fn()
    renderApp({ ...AUTHED_CONTEXT, logout })
    fireEvent.click(await screen.findByRole('button', { name: 'Sign out' }))
    expect(logout).toHaveBeenCalledOnce()
  })

  it('the People tab holds the staff pages, and shows Staff to an org_admin', async () => {
    vi.mocked(getMe).mockResolvedValue({ subject: 's', username: 'u', roles: ['org_admin'] })
    renderApp()
    await screen.findByRole('link', { name: 'Profit and loss' })
    // Not in the Accounting list...
    expect(screen.queryByRole('link', { name: 'Staff' })).toBeNull()
    // ...one tab away.
    await openTab('People')
    expect(await screen.findByRole('link', { name: 'Staff' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'People' })).toHaveAttribute('aria-selected', 'true')
  })

  it('hides Staff from a non-admin operator', async () => {
    vi.mocked(getMe).mockResolvedValue({ subject: 's', username: 'u', roles: ['accountant'] })
    const queryClient = renderApp()
    // Accountant unlocks no gated link, so there is nothing in the DOM whose
    // appearance could prove the role query resolved — anchor on the query.
    await waitFor(() => expect(queryClient.getQueryData(['me'])).toBeDefined())
    await openTab('People')
    expect(screen.queryByRole('link', { name: 'Staff' })).not.toBeInTheDocument()
    // The ungated staff overview is still there for them.
    expect(screen.getByRole('link', { name: 'Staff and labour' })).toBeInTheDocument()
  })

  it('shows Schedule to a property_gm and hides it from a non-admin', async () => {
    vi.mocked(getMe).mockResolvedValue({ subject: 's', username: 'u', roles: ['property_gm'] })
    renderApp()
    await openTab('People')
    expect(await screen.findByRole('link', { name: 'Schedule' })).toBeInTheDocument()
  })

  it('hides Schedule from a non-admin operator', async () => {
    vi.mocked(getMe).mockResolvedValue({ subject: 's', username: 'u', roles: ['accountant'] })
    const queryClient = renderApp()
    await waitFor(() => expect(queryClient.getQueryData(['me'])).toBeDefined())
    await openTab('People')
    expect(screen.queryByRole('link', { name: 'Schedule' })).not.toBeInTheDocument()
  })

  it('shows Connections to an org_admin', async () => {
    vi.mocked(getMe).mockResolvedValue({ subject: 's', username: 'u', roles: ['org_admin'] })
    renderApp()
    expect(await screen.findByRole('link', { name: 'Connections' })).toBeInTheDocument()
  })

  it('hides Connections from a property_gm', async () => {
    // The strongest non-admin the system has, and still not an org_admin:
    // connecting a tenant's payroll is not a GM's call.
    vi.mocked(getMe).mockResolvedValue({ subject: 's', username: 'u', roles: ['property_gm'] })
    renderApp()
    // "Your hotels" only appears once /api/me has resolved as a GM, which is
    // what pins the absence below to post-resolution state.
    await screen.findByRole('link', { name: 'Your hotels' })
    expect(screen.queryByRole('link', { name: 'Connections' })).not.toBeInTheDocument()
  })

  it('shows Pay runs to a payroll admin and never to a GM', async () => {
    vi.mocked(getMe).mockResolvedValue({ subject: 's', username: 'u', roles: ['payroll_admin'] })
    renderApp()
    await openTab('People')
    expect(await screen.findByRole('link', { name: 'Pay runs' })).toBeInTheDocument()
  })

  it('hides Pay runs from a role that will never own it', async () => {
    vi.mocked(getMe).mockResolvedValue({ subject: 's', username: 'u', roles: ['property_gm'] })
    renderApp()
    await openTab('People')
    await screen.findByRole('link', { name: 'Schedule' })
    expect(screen.queryByRole('link', { name: 'Pay runs' })).not.toBeInTheDocument()
  })

  // One entry per destination, and no "soon" placeholder beside a live page.
  it('carries no placeholder that duplicates a live route', async () => {
    vi.mocked(getMe).mockResolvedValue({ subject: 's', username: 'u', roles: ['property_gm'] })
    renderApp()
    await openTab('People')
    await screen.findByRole('link', { name: 'Schedule' })
    expect(screen.getAllByText('Schedule')).toHaveLength(1)
    expect(screen.queryByText('Payroll & Compensation')).toBeNull()
    expect(screen.queryByText('Employee Profile')).toBeNull()
  })

  it('the tab follows the page you are on', async () => {
    vi.mocked(getMe).mockResolvedValue({ subject: 's', username: 'u', roles: ['property_gm'] })
    renderApp(AUTHED_CONTEXT, '/timecards')
    expect(await screen.findByRole('tab', { name: 'People' })).toHaveAttribute(
      'aria-selected',
      'true',
    )
    expect(await screen.findByRole('link', { name: 'Timecards' })).toBeInTheDocument()
  })

  it('Ops shows what is coming, and none of it is a link', async () => {
    renderApp()
    await openTab('Ops')
    expect(await screen.findByText('Housekeeping board')).toBeInTheDocument()
    expect(screen.getByText('Coming in a later version.')).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Housekeeping board' })).toBeNull()
  })

  // No `show` gate: reads ride the mount's operator gates. The controls
  // inside the page are gated separately (GlPage.test.tsx).
  it('shows the Books link to any operator', async () => {
    renderApp()
    const link = await screen.findByRole('link', { name: 'Books' })
    expect(link).toHaveAttribute('href', '/gl')
  })

  it('the Financial Reports placeholder is gone', async () => {
    renderApp()
    await screen.findByRole('link', { name: 'Books' })
    expect(screen.queryByText(/financial reports/i)).toBeNull()
  })
})

describe('app shell — setup nav', () => {
  it('shows the Setup checklist entry with an open-item count', async () => {
    vi.mocked(getChecklist).mockResolvedValue({
      items: [],
      open_count: 3,
      error_count: 0,
      all_clear: false,
    })
    renderApp()
    // The accessible name is the user-facing contract, and the count belongs
    // in it: a pill whose text lands in the name would make exact-name
    // lookups miss.
    expect(
      await screen.findByRole('link', { name: 'Setup checklist: 3 items still to set up' }),
    ).toBeInTheDocument()
    expect(within(screen.getByTestId('setup-badge')).getByText('3')).toBeInTheDocument()
  })

  it('keeps the Setup checklist under Settings whichever tab is open', async () => {
    renderApp()
    await openTab('People')
    expect(await screen.findByRole('link', { name: 'Setup checklist' })).toBeInTheDocument()
    await openTab('Ops')
    expect(screen.getByRole('link', { name: 'Setup checklist' })).toBeInTheDocument()
  })

  // Two states in one test so neither is vacuous.
  it('renders no badge while the checklist is in flight, and none once it clears', async () => {
    let settle!: (c: Checklist) => void
    vi.mocked(getChecklist).mockReturnValue(
      new Promise((resolve) => {
        settle = resolve
      }),
    )
    const queryClient = renderApp()
    await screen.findByRole('link', { name: 'Setup checklist' })
    expect(screen.queryByTestId('setup-badge')).toBeNull()

    settle({ items: [], open_count: 0, error_count: 0, all_clear: true })
    await waitFor(() => expect(queryClient.getQueryData(CHECKLIST_KEY)).toBeDefined())
    expect(screen.queryByTestId('setup-badge')).toBeNull()
  })

  // A sidebar query that 500s must not take the shell down with it.
  it('renders no badge and keeps the shell when the checklist read fails', async () => {
    vi.mocked(getChecklist).mockRejectedValue(new Error('boom'))
    renderApp()
    expect(await screen.findByRole('heading', { name: 'Profit and loss' })).toBeInTheDocument()
    expect(await screen.findByRole('link', { name: 'Setup checklist' })).toBeInTheDocument()
    expect(screen.queryByTestId('setup-badge')).toBeNull()
  })

  // A failure *after* a good read keeps the last-known count.
  it('keeps the last-known count when a background refetch fails', async () => {
    vi.mocked(getChecklist)
      .mockResolvedValueOnce({ items: [], open_count: 3, error_count: 0, all_clear: false })
      .mockRejectedValue(new Error('boom'))
    const queryClient = renderApp()
    expect(await screen.findByTestId('setup-badge')).toHaveTextContent('3')

    void queryClient.invalidateQueries({ queryKey: CHECKLIST_KEY })
    await waitFor(() => expect(queryClient.getQueryState(CHECKLIST_KEY)?.error).toBeTruthy())
    expect(screen.getByTestId('setup-badge')).toHaveTextContent('3')
  })

  // THE divergence case, at the badge.
  it('badges "!" — not "0", not nothing — when every probe failed', async () => {
    vi.mocked(getChecklist).mockResolvedValue({
      items: [],
      open_count: 0,
      error_count: 4,
      all_clear: false,
    })
    renderApp()
    expect(await screen.findByTestId('setup-badge')).toHaveTextContent('!')
    expect(
      screen.getByRole('link', { name: 'Setup checklist: Could not check 4 items' }),
    ).toBeInTheDocument()
  })

  // The count is the whole reason a collapsed sidebar still points at setup,
  // so the pill must not ride along when the label goes sr-only.
  it('keeps the badge out of sr-only when the sidebar is collapsed', async () => {
    localStorage.setItem('usali.sidebar-collapsed', '1')
    vi.mocked(getChecklist).mockResolvedValue({
      items: [],
      open_count: 2,
      error_count: 0,
      all_clear: false,
    })
    renderApp()
    expect((await screen.findByTestId('setup-badge')).closest('.sr-only')).toBeNull()
  })
})

describe('app shell — desktop edition', () => {
  function mod(id: string, enabled: boolean): DesktopModule {
    return {
      id, name: id, summary: '', status: 'available', required: id === 'accounting',
      enabled, nav: id === 'payroll' ? ['/payroll-dashboard', '/employees', '/schedule'] : [],
      limitations: [{ text: 'A limit.', workaround: null }],
    }
  }

  beforeEach(() => {
    vi.mocked(getMe).mockResolvedValue({ subject: 'o', username: 'o', roles: ['org_admin'] })
    vi.mocked(getWelcome).mockResolvedValue({
      finished: true, backup_folder_set: true, group_name: 'G', group_named: true,
      properties: [], pms_choices: [],
    })
  })

  it('leads Accounting with the all-hotels Overview', async () => {
    vi.mocked(getModules).mockResolvedValue({
      modules: [mod('accounting', true), mod('payroll', true)], reloading: false,
    })
    renderApp()
    expect(await screen.findByRole('link', { name: 'Overview' })).toHaveAttribute('href', '/overview')
    expect(screen.getByRole('link', { name: 'Modules' })).toBeInTheDocument()
  })

  it('with Payroll & People off, the People tab says so and points at Modules', async () => {
    vi.mocked(getModules).mockResolvedValue({
      modules: [mod('accounting', true), mod('payroll', false)], reloading: false,
    })
    renderApp()
    await screen.findByRole('link', { name: 'Overview' })
    await openTab('People')
    expect(await screen.findByText(/Payroll & People is off/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Turn it on in Modules' })).toHaveAttribute(
      'href',
      '/modules',
    )
    expect(screen.queryByRole('link', { name: 'Staff' })).toBeNull()
  })
})

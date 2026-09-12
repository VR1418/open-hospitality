import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createMemoryHistory, RouterProvider } from '@tanstack/react-router'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api/client')>()),
  getMe: vi.fn(),
  getProperties: vi.fn(),
}))
vi.mock('../api/checklist', () => ({
  getChecklist: vi.fn(),
  dismissItem: vi.fn(),
  restoreItem: vi.fn(),
}))
vi.mock('../api/desktop', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api/desktop')>()),
  getPortfolio: vi.fn(),
  getModules: vi.fn(),
  getWelcome: vi.fn(),
  getBackupStatus: vi.fn(),
}))

import { getMe, getProperties } from '../api/client'
import { getChecklist } from '../api/checklist'
import {
  getBackupStatus,
  getModules,
  getPortfolio,
  getWelcome,
  type BackupStatus,
  type Portfolio,
} from '../api/desktop'
import { AuthContext } from '../auth/authContext'
import { createAppRouter } from '../router'
import { AUTHED_CONTEXT } from '../test/fixtures'

const PORTFOLIO: Portfolio = {
  business_date: '2026-07-07',
  month_start: '2026-07-01',
  staff_shown: true,
  hotels: [
    {
      property_id: 'HISJ', name: 'Holiday Inn San Jose', pms_source: 'OPERA', status: 'in',
      note: null, revenue: '9840.00', occupancy_pct: '76.0', adr: '131.25', revpar: '99.75',
      rooms_occupied: '60.0', rooms_total: '79.0', month_revenue: '61200.00',
      month_labour_cost: '14200.00', staff: { staff: 22, on_clock: 7, timecards_to_approve: 3 },
    },
    {
      property_id: 'LAKE', name: 'Lakeside Suites', pms_source: 'SKYTOUCH', status: 'missing',
      note: 'No reports for this day yet.', revenue: null, occupancy_pct: null, adr: null,
      revpar: null, rooms_occupied: null, rooms_total: null, month_revenue: '30000.00',
      month_labour_cost: null, staff: { staff: 11, on_clock: 2, timecards_to_approve: 0 },
    },
  ],
  totals: {
    hotels: 2, hotels_in: 1, revenue: '9840.00', occupancy_pct: '76.0', adr: '131.25',
    revpar: '99.75', month_revenue: '91200.00', month_labour_cost: '14200.00',
    month_labour_pct: '15.6', staff: { staff: 33, on_clock: 9, timecards_to_approve: 3 },
  },
  trend: [
    { business_date: '2026-07-05', revenue: '8100.00' },
    { business_date: '2026-07-06', revenue: null },
    { business_date: '2026-07-07', revenue: '9840.00' },
  ],
  findings: [
    {
      property_id: 'LAKE', hotel: 'Lakeside Suites', kind: 'no_reports',
      label: 'No reports yet', detail: 'No reports for this day yet.', delta: null,
    },
    {
      property_id: 'HISJ', hotel: 'Holiday Inn San Jose', kind: 'check_failed',
      label: 'AR roll-forward', detail: 'Prior close plus today’s activity doesn’t tie.',
      delta: '120.50',
    },
  ],
}

function renderAt(path = '/overview') {
  const router = createAppRouter(createMemoryHistory({ initialEntries: [path] }))
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <AuthContext.Provider value={AUTHED_CONTEXT}>
        <RouterProvider router={router} />
      </AuthContext.Provider>
    </QueryClientProvider>,
  )
  return router
}

describe('OverviewPage', () => {
  beforeEach(() => {
    vi.mocked(getMe).mockResolvedValue({ subject: 'o', username: 'o', roles: ['org_admin'] })
    vi.mocked(getProperties).mockResolvedValue([])
    vi.mocked(getChecklist).mockResolvedValue({
      items: [], open_count: 0, error_count: 0, all_clear: true,
    })
    vi.mocked(getModules).mockResolvedValue({ modules: [], reloading: false })
    vi.mocked(getWelcome).mockResolvedValue({
      finished: true, backup_folder_set: true, group_name: 'G', group_named: true,
      properties: [], pms_choices: [],
    })
    vi.mocked(getPortfolio).mockReset().mockResolvedValue(PORTFOLIO)
    vi.mocked(getBackupStatus).mockReset().mockResolvedValue({
      folder: 'D:\Sync', suggested_folder: 'D:\Sync', last_backup_at: new Date().toISOString(),
      last_file: 'x.ohbackup', armed: true, due: false, keep: 7, files: [],
    } as BackupStatus)
  })
  afterEach(() => localStorage.clear())

  it('leads with the hotels, so you know whose figures these are', async () => {
    renderAt()
    await screen.findByRole('region', { name: 'Hotels' })
    const regions = screen.getAllByRole('region').map((r) => r.getAttribute('aria-label'))
    // Before the portfolio totals: which hotels these cover is the question
    // an owner asks first.
    expect(regions.indexOf('Hotels')).toBeLessThan(regions.indexOf('Totals'))
  })

  it('names each hotel rather than showing its code alone', async () => {
    renderAt()
    const hotels = await screen.findByRole('region', { name: 'Hotels' })
    expect(within(hotels).getByText('Holiday Inn San Jose')).toBeInTheDocument()
    expect(within(hotels).getByText('Lakeside Suites')).toBeInTheDocument()
  })

  it('puts every hotel on one screen for the last closed day, with totals', async () => {
    renderAt()

    expect(await screen.findByRole('heading', { name: 'All hotels' })).toBeInTheDocument()
    expect(screen.getByText(/Last closed day · .*2026/)).toBeInTheDocument()
    const totals = screen.getByRole('region', { name: 'Totals' })
    expect(within(totals).getByText('$9,840')).toBeInTheDocument()
    expect(within(totals).getByText('76.0%')).toBeInTheDocument()
    expect(within(totals).getByText('1 of 2 hotels reported')).toBeInTheDocument()

    const hotels = screen.getByRole('region', { name: 'Hotels' })
    expect(within(hotels).getByRole('button', { name: 'Open Holiday Inn San Jose' })).toBeInTheDocument()
    // A hotel without the day's reports says so, and isn't a dead link.
    expect(within(hotels).getByText('No reports for this day yet.')).toBeInTheDocument()
    expect(within(hotels).getByText('Missing')).toBeInTheDocument()
    expect(within(hotels).queryByRole('button', { name: 'Open Lakeside Suites' })).toBeNull()
  })

  it('shows the revenue trend, saying which figures it draws', async () => {
    renderAt()
    const trend = await screen.findByRole('region', { name: 'Revenue trend' })
    expect(within(trend).getByText(/from the reports read/)).toBeInTheDocument()
    expect(within(trend).getByRole('img', { name: /Revenue per day, 3 days to 2026-07-07/ }))
      .toBeInTheDocument()
    expect(within(trend).getByText('Best day $9,840')).toBeInTheDocument()
  })

  it('shows what last night’s audit turned up, with the amount it is out by', async () => {
    renderAt()
    const audit = await screen.findByRole('region', { name: 'Last night’s audit' })
    expect(within(audit).getByText('2 to look at')).toBeInTheDocument()
    expect(within(audit).getByText('No reports yet')).toBeInTheDocument()
    expect(within(audit).getByText('AR roll-forward')).toBeInTheDocument()
    expect(within(audit).getByText('Out by $120.50')).toBeInTheDocument()
    expect(within(audit).getByRole('link', { name: 'Open Close the day' })).toHaveAttribute(
      'href',
      '/night-audit',
    )
  })

  it('says so plainly when the audit found nothing', async () => {
    vi.mocked(getPortfolio).mockResolvedValue({ ...PORTFOLIO, findings: [] })
    renderAt()
    const audit = await screen.findByRole('region', { name: 'Last night’s audit' })
    expect(within(audit).getByText(/every hotel’s reports are in/)).toBeInTheDocument()
  })

  it('shows the staff picture when Payroll & People is on', async () => {
    renderAt()
    const staff = await screen.findByRole('region', { name: 'Staff' })
    expect(within(staff).getByText('On the clock now')).toBeInTheDocument()
    expect(within(staff).getByText('15.6%')).toBeInTheDocument()
    expect(within(staff).getByRole('link', { name: 'Review timecards' })).toHaveAttribute(
      'href',
      '/timecards',
    )
  })

  it('shows no staff section when Payroll & People is off', async () => {
    vi.mocked(getPortfolio).mockResolvedValue({
      ...PORTFOLIO,
      staff_shown: false,
      totals: { ...PORTFOLIO.totals, staff: null },
    })
    renderAt()
    await screen.findByRole('region', { name: 'Hotels' })
    expect(screen.queryByRole('region', { name: 'Staff' })).toBeNull()
  })

  it('a hotel row opens that hotel’s dashboard, on the same day', async () => {
    const router = renderAt()
    await userEvent.click(await screen.findByRole('button', { name: 'Open Holiday Inn San Jose' }))
    await waitFor(() => expect(router.state.location.pathname).toBe('/dashboard'))
    expect(localStorage.getItem('usali.property')).toBe('HISJ')
    // Not "today", which usually has no reports yet: the day the row was for.
    expect(router.state.location.search).toEqual({ date: '2026-07-07' })
  })

  it('asks for another day when one is picked', async () => {
    renderAt()
    const picker = await screen.findByLabelText('Show a different day')
    // A date input takes a whole value at once (jsdom can't type into one).
    fireEvent.change(picker, { target: { value: '2026-06-21' } })
    await waitFor(() => expect(getPortfolio).toHaveBeenLastCalledWith('2026-06-21'))
    expect(await screen.findByRole('button', { name: 'Latest' })).toBeInTheDocument()
  })

  it('the owner can add a hotel from here', async () => {
    renderAt()
    expect(await screen.findByRole('link', { name: 'Add a hotel' })).toHaveAttribute(
      'href',
      '/welcome?add=hotel',
    )
  })

  it('keeps asking when the books are not being backed up', async () => {
    vi.mocked(getBackupStatus).mockResolvedValue({
      folder: null, suggested_folder: 'D:\Sync', last_backup_at: null, last_file: null,
      armed: false, due: false, keep: 7, files: [],
    } as BackupStatus)
    renderAt()
    const nag = await screen.findByRole('region', { name: 'Backups' })
    expect(within(nag).getByText(/aren’t being backed up/)).toBeInTheDocument()
    expect(within(nag).getByRole('link', { name: 'Set up backups' })).toHaveAttribute(
      'href',
      '/backups',
    )
  })

  it('says nothing about backups when one was taken today', async () => {
    renderAt()
    await screen.findByRole('region', { name: 'Hotels' })
    expect(screen.queryByRole('region', { name: 'Backups' })).toBeNull()
  })

  it('on a hosted deployment, points at the hotel dashboard instead', async () => {
    vi.mocked(getPortfolio).mockResolvedValue(null)
    renderAt()
    expect(await screen.findByText(/part of the desktop edition/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'hotel dashboard' })).toHaveAttribute('href', '/dashboard')
  })
})

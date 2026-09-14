import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { RouterProvider, createMemoryHistory, createRootRoute, createRoute, createRouter } from '@tanstack/react-router'
import { render, screen, within } from '@testing-library/react'
import type { JSX } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../api/desktop', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api/desktop')>()),
  getMorning: vi.fn(),
}))

import { getMorning, type Morning } from '../api/desktop'
import MorningCard from './MorningCard'
import RecentReportsCard from './RecentReportsCard'

const MORNING: Morning = {
  last_night: '2026-09-13',
  items: [
    { id: 'reports', state: 'done', text: 'RTI22: last night’s audit is in', page: '/upload' },
    { id: 'codes', state: 'todo', text: '11 codes to confirm.', page: '/codes' },
    { id: 'bank', state: 'todo', text: 'RTI22: no statement checked yet', page: '/bank' },
    { id: 'backup', state: 'attention', text: 'No backup folder chosen.', page: '/backups' },
  ],
  recent: [
    { file: 'RTI22 2026-09-13.pdf', state: 'read', property_id: 'RTI22', business_date: '2026-09-13',
      when: '2026-09-14T06:02:00', reason: null },
    { file: 'scan.pdf', state: 'unreadable', property_id: null, business_date: null,
      when: '2026-09-14T06:01:00', reason: 'could not detect report type from PDF header' },
  ],
}

function renderIn(component: () => JSX.Element | null) {
  const root = createRootRoute({ component })
  const index = createRoute({ getParentRoute: () => root, path: '/' })
  const router = createRouter({
    routeTree: root.addChildren([index]),
    history: createMemoryHistory({ initialEntries: ['/'] }),
  })
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  )
}

describe('MorningCard', () => {
  beforeEach(() => {
    vi.mocked(getMorning).mockReset().mockResolvedValue(MORNING)
  })

  it('gives the owner four lines: done, to do, needs attention, and where to go', async () => {
    renderIn(MorningCard)
    const card = await screen.findByRole('region', { name: 'This morning' })
    expect(await within(card).findByText('Last night’s reports')).toBeInTheDocument()
    expect(within(card).getByLabelText('Done')).toBeInTheDocument()
    expect(within(card).getAllByLabelText('To do')).toHaveLength(2)
    expect(within(card).getByLabelText('Needs attention')).toBeInTheDocument()
    expect(within(card).getByText('11 codes to confirm.')).toBeInTheDocument()
    const links = within(card).getAllByRole('link')
    expect(links.map((l) => l.textContent)).toEqual(['Open', 'Go', 'Go', 'Go'])
    expect(links[1]).toHaveAttribute('href', '/codes')
  })

  it('is nothing outside the desktop edition', async () => {
    vi.mocked(getMorning).mockResolvedValue(null)
    renderIn(MorningCard)
    await vi.waitFor(() => expect(getMorning).toHaveBeenCalled())
    expect(screen.queryByRole('region', { name: 'This morning' })).toBeNull()
  })
})

describe('RecentReportsCard', () => {
  beforeEach(() => {
    vi.mocked(getMorning).mockReset().mockResolvedValue(MORNING)
  })

  it('says what was just read, what was set aside and why, and what is waiting', async () => {
    renderIn(RecentReportsCard)
    const card = await screen.findByRole('region', { name: 'Just read' })
    expect(await within(card).findByText('RTI22 · 2026-09-13')).toBeInTheDocument()
    expect(within(card).getByText('Read')).toBeInTheDocument()
    expect(within(card).getByText('Couldn’t read')).toBeInTheDocument()
    expect(within(card).getByText(/could not detect report type/)).toBeInTheDocument()
    expect(within(card).getByRole('link', { name: 'Confirm them' })).toHaveAttribute('href', '/codes')
  })

  it('tells a fresh owner where reports go', async () => {
    vi.mocked(getMorning).mockResolvedValue({ ...MORNING, recent: [] })
    renderIn(RecentReportsCard)
    const card = await screen.findByRole('region', { name: 'Just read' })
    expect(within(card).getByText(/Drop reports here folder/)).toBeInTheDocument()
  })
})

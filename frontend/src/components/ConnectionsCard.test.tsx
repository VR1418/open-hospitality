import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { RouterProvider, createMemoryHistory, createRootRoute, createRoute, createRouter } from '@tanstack/react-router'
import { render, screen, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../api/desktop', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api/desktop')>()),
  getConnections: vi.fn(),
}))

import { getConnections } from '../api/desktop'
import ConnectionsCard from './ConnectionsCard'

function renderCard() {
  const root = createRootRoute({ component: ConnectionsCard })
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

describe('ConnectionsCard', () => {
  beforeEach(() => {
    vi.mocked(getConnections).mockReset().mockResolvedValue({
      connections: [
        { id: 'ai', name: 'AI helper', state: 'connected',
          detail: 'anthropic/claude-sonnet-5 via OpenRouter · checked 13 Sep 9:02 PM', page: '/ai' },
        { id: 'email', name: 'Reports by email', state: 'not_set_up',
          detail: 'Not set up. Optional: collects the night audit from a mailbox.', page: '/email' },
        { id: 'backups', name: 'Backups', state: 'attention',
          detail: 'No backup folder chosen.', page: '/backups' },
      ],
    })
  })

  it('says what is connected, what is not, and where to go', async () => {
    renderCard()
    const card = await screen.findByRole('region', { name: 'What’s connected' })
    expect(await within(card).findByText('Connected')).toBeInTheDocument()
    expect(within(card).getByText('Not set up')).toBeInTheDocument()
    expect(within(card).getByText('Needs attention')).toBeInTheDocument()
    expect(within(card).getByText(/checked 13 Sep 9:02 PM/)).toBeInTheDocument()
    const links = within(card).getAllByRole('link')
    expect(links.map((l) => l.textContent)).toEqual(['Open', 'Set up', 'Set up'])
    expect(links[1]).toHaveAttribute('href', '/email')
  })

  it('is nothing outside the desktop edition', async () => {
    vi.mocked(getConnections).mockResolvedValue(null)
    renderCard()
    await vi.waitFor(() => expect(getConnections).toHaveBeenCalled())
    expect(screen.queryByRole('region', { name: 'What’s connected' })).toBeNull()
  })
})

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { DesktopModule, ModulesResponse } from '../api/desktop'
import ModulesPage from './ModulesPage'

const getModules = vi.fn<() => Promise<ModulesResponse | null>>()
const saveModules = vi.fn<(enabled: string[]) => Promise<ModulesResponse>>()
const getMe = vi.fn()

vi.mock('../api/desktop', () => ({
  getModules: () => getModules(),
  saveModules: (enabled: string[]) => saveModules(enabled),
}))
vi.mock('../api/client', () => ({ getMe: () => getMe() }))

function mod(overrides: Partial<DesktopModule>): DesktopModule {
  return {
    id: 'x', name: 'X', summary: '', status: 'available', required: false,
    enabled: false, nav: [], limitations: [{ text: 'A limit.', workaround: null }],
    ...overrides,
  }
}

const MODULES: DesktopModule[] = [
  mod({ id: 'accounting', name: 'Accounting & Reporting', required: true, enabled: true }),
  mod({
    id: 'payroll', name: 'Payroll & People',
    limitations: [{ text: 'This doesn’t pay anybody.', workaround: 'Use your payroll provider.' }],
  }),
  mod({ id: 'utilities', name: 'Hotel Management Utilities', status: 'coming_soon' }),
]

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <ModulesPage />
    </QueryClientProvider>,
  )
}

describe('ModulesPage', () => {
  beforeEach(() => {
    getModules.mockReset().mockResolvedValue({ modules: MODULES, reloading: false })
    saveModules.mockReset().mockResolvedValue({ modules: MODULES, reloading: false })
    getMe.mockReset().mockResolvedValue({ subject: 'o', username: 'owner', roles: ['org_admin'] })
  })

  it('puts each module’s limits, and their workarounds, beside its switch', async () => {
    renderPage()
    const payroll = await screen.findByRole('region', { name: 'Payroll & People' })
    expect(within(payroll).getByText('This doesn’t pay anybody.')).toBeInTheDocument()
    expect(within(payroll).getByText(/Use your payroll provider/)).toBeInTheDocument()
    expect(
      within(screen.getByRole('region', { name: 'Accounting & Reporting' })).getByText('Always on'),
    ).toBeInTheDocument()
    // Coming soon is visible but never selectable.
    const utilities = screen.getByRole('region', { name: 'Hotel Management Utilities' })
    expect(within(utilities).getByText('Coming soon')).toBeInTheDocument()
    expect(within(utilities).queryByRole('button')).toBeNull()
  })

  it('turning a module on sends the whole new set', async () => {
    renderPage()
    await userEvent.click(await screen.findByRole('button', { name: 'Turn on Payroll & People' }))
    expect(saveModules).toHaveBeenCalledWith(['accounting', 'payroll'])
  })

  it('offers no switches to someone who is not the owner', async () => {
    getMe.mockResolvedValue({ subject: 'b', username: 'bookkeeper', roles: ['accountant'] })
    renderPage()
    await screen.findByRole('region', { name: 'Payroll & People' })
    expect(screen.queryByRole('button', { name: /Turn on/ })).toBeNull()
  })
})

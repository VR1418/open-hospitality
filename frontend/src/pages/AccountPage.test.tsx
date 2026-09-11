import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { DesktopAccount, DesktopSession, SetupCode } from '../api/desktop'
import AccountPage from './AccountPage'

const getSessions = vi.fn<() => Promise<DesktopSession[]>>()
const signOutDevice = vi.fn<(id: string) => Promise<void>>()
const changePassword = vi.fn<(current: string, next: string) => Promise<void>>()
const getAccounts = vi.fn<() => Promise<DesktopAccount[]>>()
const giveSetupCode = vi.fn<(subject: string) => Promise<SetupCode>>()
const getMe = vi.fn()
const logout = vi.fn()

vi.mock('../api/desktop', () => ({
  getSessions: () => getSessions(),
  signOutDevice: (id: string) => signOutDevice(id),
  changePassword: (current: string, next: string) => changePassword(current, next),
  getAccounts: () => getAccounts(),
  giveSetupCode: (subject: string) => giveSetupCode(subject),
}))
vi.mock('../api/client', () => ({ getMe: () => getMe() }))
vi.mock('../auth/authContext', () => ({ useAuth: () => ({ logout }) }))

const SESSIONS: DesktopSession[] = [
  {
    session_id: 'here', device_label: 'Chrome on Windows', current: true,
    created_at: '2026-09-11T09:00:00Z', last_seen_at: '2026-09-11T10:00:00Z',
  },
  {
    session_id: 'there', device_label: 'Safari on Mac', current: false,
    created_at: '2026-09-10T09:00:00Z', last_seen_at: '2026-09-10T18:00:00Z',
  },
]

function account(overrides: Partial<DesktopAccount>): DesktopAccount {
  return {
    subject: 's', full_name: 'Someone', username: 'someone@hotel.test',
    email: 'someone@hotel.test', roles: [], enabled: true, has_password: true, is_owner: false,
    ...overrides,
  }
}

const ACCOUNTS: DesktopAccount[] = [
  account({ subject: 'desktop-owner', full_name: 'Pat Owner', roles: ['org_admin'], is_owner: true }),
  account({
    subject: 'sam', full_name: 'Sam Books', email: 'sam@hotel.test', roles: ['accountant'],
    has_password: false,
  }),
  account({ subject: 'gone', full_name: 'Former Staff', enabled: false }),
]

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <AccountPage />
    </QueryClientProvider>,
  )
}

describe('AccountPage', () => {
  beforeEach(() => {
    getSessions.mockReset().mockResolvedValue(SESSIONS)
    signOutDevice.mockReset().mockResolvedValue(undefined)
    changePassword.mockReset().mockResolvedValue(undefined)
    getAccounts.mockReset().mockResolvedValue(ACCOUNTS)
    giveSetupCode.mockReset().mockResolvedValue({ setup_code: 'ABCD-EFGH', valid_for_hours: 24 })
    getMe.mockReset().mockResolvedValue({ subject: 'desktop-owner', username: 'pat', roles: ['org_admin'] })
    logout.mockReset()
  })

  it('lists each sign-in with its own sign-out (A-7)', async () => {
    renderPage()
    const region = await screen.findByRole('region', { name: 'Your sign-ins' })
    expect(await within(region).findByText('Safari on Mac')).toBeInTheDocument()
    expect(within(region).getByText('This device')).toBeInTheDocument()

    await userEvent.click(within(region).getByRole('button', { name: 'Sign out Safari on Mac' }))
    expect(signOutDevice).toHaveBeenCalledWith('there')
    expect(logout).not.toHaveBeenCalled()

    // This device's own sign-out is the ordinary sign-out.
    await userEvent.click(within(region).getByRole('button', { name: 'Sign out of this device' }))
    expect(logout).toHaveBeenCalled()
  })

  it('changes the password only when both new passwords match', async () => {
    renderPage()
    const region = await screen.findByRole('region', { name: 'Change your password' })
    await userEvent.type(within(region).getByLabelText('Current password'), 'old passphrase 1')
    await userEvent.type(within(region).getByLabelText('New password'), 'new passphrase 22')
    await userEvent.type(within(region).getByLabelText('Type the new password again'), 'new passphrase 2')
    await userEvent.click(within(region).getByRole('button', { name: 'Change password' }))
    expect(await within(region).findByRole('alert')).toHaveTextContent('don’t match')
    expect(changePassword).not.toHaveBeenCalled()

    await userEvent.type(within(region).getByLabelText('Type the new password again'), '2')
    await userEvent.click(within(region).getByRole('button', { name: 'Change password' }))
    expect(changePassword).toHaveBeenCalledWith('old passphrase 1', 'new passphrase 22')
    expect(await within(region).findByRole('status')).toHaveTextContent('Your password is changed.')
  })

  it('the owner hands someone a set-up code, shown once', async () => {
    renderPage()
    const region = await screen.findByRole('region', { name: 'People who can sign in' })
    expect(await within(region).findByText('Needs a set-up code')).toBeInTheDocument()
    // No code for the owner (they use their recovery code) or for someone who can't sign in.
    expect(within(region).queryByRole('button', { name: /Pat Owner/ })).toBeNull()
    expect(within(region).queryByRole('button', { name: /Former Staff/ })).toBeNull()

    await userEvent.click(within(region).getByRole('button', { name: 'Give Sam Books a set-up code' }))
    expect(giveSetupCode).toHaveBeenCalledWith('sam')
    const shown = await within(region).findByRole('status')
    expect(shown).toHaveTextContent('ABCD-EFGH')
    expect(shown).toHaveTextContent('24 hours')
    expect(shown).toHaveTextContent('sam@hotel.test')
  })

  it('shows someone who is not the owner only their own sign-ins and password', async () => {
    getMe.mockResolvedValue({ subject: 'sam', username: 'sam', roles: ['accountant'] })
    renderPage()
    await screen.findByRole('region', { name: 'Your sign-ins' })
    await screen.findByText('Safari on Mac')
    expect(screen.queryByRole('region', { name: 'People who can sign in' })).toBeNull()
    expect(getAccounts).not.toHaveBeenCalled()
  })
})

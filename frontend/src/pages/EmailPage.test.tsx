import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../api/desktop', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api/desktop')>()),
  getMailSettings: vi.fn(),
  saveMailSettings: vi.fn(),
  testMailConnection: vi.fn(),
  fetchMailNow: vi.fn(),
  allowMailSender: vi.fn(),
  forgetMailPassword: vi.fn(),
}))

import {
  allowMailSender,
  fetchMailNow,
  getMailSettings,
  saveMailSettings,
  testMailConnection,
  type MailSettings,
} from '../api/desktop'
import EmailPage from './EmailPage'

const FRESH: MailSettings = {
  enabled: false, preset: 'gmail', host: '', port: 993, username: '', folder: 'INBOX',
  mode: 'daily', at: '06:00', every_hours: 2, senders: [], password_saved: false,
  presets: [
    { id: 'gmail', name: 'Gmail / Google Workspace', host: 'imap.gmail.com', port: 993,
      hint: 'Use an app password, not your normal one.' },
    { id: 'other', name: 'Another mail service (IMAP)', host: '', port: 993,
      hint: 'Your provider’s IMAP server.' },
  ],
  status: { last_run_at: null, last_result: null, last_error: null, next_run_at: null,
            held: [], fetched: [] },
}

const RUNNING: MailSettings = {
  ...FRESH, enabled: true, host: 'imap.gmail.com', username: 'reports@example.com',
  password_saved: true, senders: ['audit@pms.example.com'],
  status: {
    last_run_at: '2026-09-14T06:00:00', last_result: '1 report fetched.', last_error: null,
    next_run_at: '2026-09-15T06:00:00',
    held: [{ sender: 'spam@example.com', count: 2, subjects: ['Great offer'] }],
    fetched: ['audit-2026-09-13.pdf'],
  },
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <EmailPage />
    </QueryClientProvider>,
  )
}

describe('EmailPage', () => {
  beforeEach(() => {
    vi.mocked(getMailSettings).mockReset().mockResolvedValue(FRESH)
    vi.mocked(saveMailSettings).mockReset().mockResolvedValue(RUNNING)
    vi.mocked(testMailConnection).mockReset().mockResolvedValue({ messages_seen: 3, days: 14 })
    vi.mocked(fetchMailNow).mockReset().mockResolvedValue({
      fetched: 1, held_senders: 0, files: ['a.pdf'], summary: '1 report fetched.',
    })
    vi.mocked(allowMailSender).mockReset().mockResolvedValue({
      fetched: 2, held_senders: 0, files: [], summary: '2 reports fetched.',
    })
  })

  it('sets up a Gmail mailbox with a time to look, and sends the password only when typed', async () => {
    renderPage()
    await userEvent.type(await screen.findByLabelText(/Email address the reports/), 'reports@example.com')
    await userEvent.type(screen.getByLabelText(/^Password/), 'app-pass')
    await userEvent.click(screen.getByLabelText('Collect reports from email'))
    const at = screen.getByLabelText('Time to look each day')
    await userEvent.clear(at)
    await userEvent.type(at, '05:30')
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() =>
      expect(saveMailSettings).toHaveBeenCalledWith(
        expect.objectContaining({
          enabled: true, preset: 'gmail', username: 'reports@example.com', mode: 'daily',
          at: '05:30', password: 'app-pass', senders: [],
        }),
      ),
    )
    // The Gmail hint says where the password comes from.
    expect(screen.getByText(/app password/)).toBeInTheDocument()
  })

  it('asks for a server only for another mail service', async () => {
    renderPage()
    await screen.findByLabelText(/Email address the reports/)
    expect(screen.queryByLabelText('IMAP server')).toBeNull()
    await userEvent.selectOptions(screen.getByLabelText('Mail service'), 'other')
    expect(screen.getByLabelText('IMAP server')).toBeInTheDocument()
  })

  it('shows the last look, and lets a held sender be allowed', async () => {
    vi.mocked(getMailSettings).mockResolvedValue(RUNNING)
    renderPage()
    const last = await screen.findByRole('region', { name: 'What has come in' })
    expect(within(last).getByText(/1 report fetched/)).toBeInTheDocument()
    expect(within(last).getByText('spam@example.com')).toBeInTheDocument()
    await userEvent.click(within(last).getByRole('button', { name: 'Allow this sender' }))
    await waitFor(() => expect(allowMailSender).toHaveBeenCalledWith('spam@example.com'))
    expect(within(last).getByText(/Collected so far: audit-2026-09-13.pdf/)).toBeInTheDocument()
  })

  it('looks now, and checks the connection, once a password is saved', async () => {
    vi.mocked(getMailSettings).mockResolvedValue(RUNNING)
    renderPage()
    await userEvent.click(await screen.findByRole('button', { name: 'Look now' }))
    await waitFor(() => expect(fetchMailNow).toHaveBeenCalled())
    expect(await screen.findByText('1 report fetched.')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Check it connects' }))
    expect(await screen.findByText(/Connected. 3 emails in the last 14 days/)).toBeInTheDocument()
  })

  it('never shows the password back', async () => {
    vi.mocked(getMailSettings).mockResolvedValue(RUNNING)
    renderPage()
    const field = await screen.findByLabelText(/^Password/)
    expect(field).toHaveValue('')
    expect(field).toHaveAttribute('type', 'password')
    expect(screen.getByText(/one is already saved/)).toBeInTheDocument()
  })

  it('shows why a look failed, in the service’s words', async () => {
    vi.mocked(getMailSettings).mockResolvedValue({
      ...RUNNING,
      status: { ...RUNNING.status, last_error: 'The mail service refused the sign-in.' },
    })
    renderPage()
    expect(await screen.findByRole('alert')).toHaveTextContent('refused the sign-in')
  })
})

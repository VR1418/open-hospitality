import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api/client')>()),
  getProperties: vi.fn(),
}))
vi.mock('../api/desktop', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api/desktop')>()),
  getStatements: vi.fn(),
  getStatement: vi.fn(),
  uploadStatement: vi.fn(),
  markStatementLine: vi.fn(),
  deleteStatement: vi.fn(),
  getCardCategories: vi.fn(),
}))

import { getProperties } from '../api/client'
import {
  getCardCategories,
  getStatement,
  getStatements,
  markStatementLine,
  uploadStatement,
  type StatementDetail,
} from '../api/desktop'
import BankPage from './BankPage'

const BANK: StatementDetail = {
  statement_id: 1, property_id: 'HR', kind: 'bank', account_label: 'Operating account',
  file_name: 'sept.csv', uploaded_at: '2026-09-14T10:00:00', first_date: '2026-09-10',
  last_date: '2026-09-13', lines: 3, matched: 2, unmatched: 1, money_in: '2996.13',
  money_out: '1800.00',
  rows: [
    { line_id: 11, posted_on: '2026-09-12', description: 'BANKCARD MERCH DEP', amount: '2406.13',
      balance: null, match_kind: 'settlement',
      match_note: 'Visa/MasterCard settled 9/10, less $60.15 in fees', matched_amount: '2466.28',
      category: null },
    { line_id: 12, posted_on: '2026-09-12', description: 'DEPOSIT', amount: '590.00',
      balance: null, match_kind: 'cash', match_note: 'Cash and checks settled 9/11',
      matched_amount: '590.00', category: null },
    { line_id: 13, posted_on: '2026-09-13', description: 'SBA LOAN PMT', amount: '-1800.00',
      balance: null, match_kind: 'unmatched',
      match_note: "Money out. If it isn't the hotel's business, mark it as such.",
      matched_amount: null, category: null },
  ],
  by_category: [],
}

const CARD: StatementDetail = {
  ...BANK, statement_id: 2, kind: 'card', account_label: 'Visa ending 4411', lines: 2,
  matched: 0, unmatched: 2, money_in: '0', money_out: '200.58',
  rows: [
    { line_id: 21, posted_on: '2026-09-02', description: 'HOME DEPOT #6512', amount: '-142.18',
      balance: null, match_kind: 'unmatched', match_note: null, matched_amount: null, category: null },
    { line_id: 22, posted_on: '2026-09-03', description: 'AMAZON MKTPL', amount: '-58.40',
      balance: null, match_kind: 'unmatched', match_note: null, matched_amount: null, category: null },
  ],
  by_category: [['Not sorted yet', '200.58']],
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <BankPage />
    </QueryClientProvider>,
  )
}

describe('BankPage', () => {
  beforeEach(() => {
    vi.mocked(getProperties).mockResolvedValue([
      { property_id: 'HR', name: 'HARBOUR REST', pms_source: 'SKYTOUCH',
        first_date: '2026-09-01', last_date: '2026-09-13' },
    ] as Awaited<ReturnType<typeof getProperties>>)
    vi.mocked(getStatements).mockReset().mockResolvedValue([BANK, CARD])
    vi.mocked(getStatement).mockReset().mockImplementation(async (id) => (id === 1 ? BANK : CARD))
    vi.mocked(uploadStatement).mockReset().mockResolvedValue(BANK)
    vi.mocked(markStatementLine).mockReset().mockResolvedValue(BANK.rows[2]!)
    vi.mocked(getCardCategories).mockReset().mockResolvedValue([
      'Repairs & maintenance', 'Office supplies', 'Other',
    ])
  })

  it('uploads a statement for the hotel on screen and opens the check', async () => {
    renderPage()
    const form = await screen.findByRole('form', { name: 'Upload a statement' })
    await userEvent.type(within(form).getByLabelText('Account name'), 'Operating account')
    await userEvent.upload(
      within(form).getByLabelText('Statement file'),
      new File(['Date,Description,Amount\n'], 'sept.csv', { type: 'text/csv' }),
    )
    await userEvent.click(within(form).getByRole('button', { name: 'Check it' }))
    await waitFor(() =>
      expect(uploadStatement).toHaveBeenCalledWith(
        expect.objectContaining({ property: 'HR', kind: 'bank', account_label: 'Operating account' }),
      ),
    )
    expect(await screen.findByRole('region', { name: 'Statement Operating account' })).toBeInTheDocument()
  })

  it('says what each bank line is, and lets an unmatched one be marked as not the hotel’s', async () => {
    renderPage()
    const list = await screen.findByRole('region', { name: 'Statements' })
    expect(await within(list).findByText('1 of 3 unmatched')).toBeInTheDocument()
    await userEvent.click(await within(list).findByRole('button', { name: 'Open Operating account 9/10/2026' }))
    const open = await screen.findByRole('region', { name: 'Statement Operating account' })
    expect(within(open).getByText(/Visa\/MasterCard settled 9\/10, less \$60.15/)).toBeInTheDocument()
    expect(within(open).getByText('Cash from the desk')).toBeInTheDocument()
    await userEvent.click(within(open).getByRole('button', { name: "Not the hotel's: SBA LOAN PMT" }))
    await waitFor(() =>
      expect(markStatementLine).toHaveBeenCalledWith(13, expect.objectContaining({ match_kind: 'ignored' })),
    )
  })

  it('sorts a card purchase into a category', async () => {
    renderPage()
    const list = await screen.findByRole('region', { name: 'Statements' })
    await userEvent.click(await within(list).findByRole('button', { name: 'Open Visa ending 4411 9/10/2026' }))
    const open = await screen.findByRole('region', { name: 'Statement Visa ending 4411' })
    expect(within(open).getByRole('region', { name: 'By category' })).toHaveTextContent('Not sorted yet')
    await userEvent.selectOptions(
      within(open).getByLabelText('Category for HOME DEPOT #6512'),
      'Repairs & maintenance',
    )
    await waitFor(() =>
      expect(markStatementLine).toHaveBeenCalledWith(21, { category: 'Repairs & maintenance' }),
    )
  })

  it('shows the upload refusal in the server’s words', async () => {
    vi.mocked(uploadStatement).mockRejectedValue(new Error('The first line should name the columns.'))
    renderPage()
    const form = await screen.findByRole('form', { name: 'Upload a statement' })
    await userEvent.upload(
      within(form).getByLabelText('Statement file'),
      new File(['x'], 'x.csv', { type: 'text/csv' }),
    )
    await userEvent.click(within(form).getByRole('button', { name: 'Check it' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('name the columns')
  })
})

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
  readReportWithAi: vi.fn(),
  confirmAiReading: vi.fn(),
}))

import { getProperties } from '../api/client'
import { confirmAiReading, readReportWithAi, type AiReading } from '../api/desktop'
import ReadWithAiPage from './ReadWithAiPage'

const READING: AiReading = {
  property_id: 'HR',
  file: 'audit.pdf',
  business_date: '2026-07-07',
  rows: [
    { code: 'RM', description: 'Room Charge', amount: '4000.0000' },
    { code: 'VI', description: 'Visa Payment', amount: '-3750.0000' },
  ],
  pages_read: [1, 2, 3, 4],
  held_back: [
    { page: 5, why: 'something shaped like a card number' },
    { page: 6, why: 'something shaped like a card number' },
    { page: 7, why: "something shaped like a person's name" },
  ],
  decline_reason: null,
  estimated_cost: '0.012',
  model: 'practice',
  spend: {
    month_start: '2026-07-01', calls: 2, estimated_cost: '0.02', unpriced_calls: 0,
    cap: '10.00', max_calls: 500, stopped: false,
  },
  learned: null,
  shape_changed: false,
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <ReadWithAiPage />
    </QueryClientProvider>,
  )
}

async function pickAndRead() {
  const input = await screen.findByLabelText('The report, as a PDF')
  await userEvent.upload(
    input,
    new File([new Uint8Array([37, 80, 68, 70])], 'audit.pdf', { type: 'application/pdf' }),
  )
  await userEvent.click(screen.getByRole('button', { name: 'Read it' }))
}

describe('ReadWithAiPage', () => {
  beforeEach(() => {
    vi.mocked(getProperties).mockResolvedValue([
      { property_id: 'HR', name: 'HARBOUR REST', pms_source: 'OTHER',
        first_date: '2026-07-01', last_date: '2026-07-07' },
    ] as Awaited<ReturnType<typeof getProperties>>)
    vi.mocked(readReportWithAi).mockReset().mockResolvedValue(READING)
    vi.mocked(confirmAiReading).mockReset().mockResolvedValue({
      property_id: 'HR', business_date: '2026-07-07', staged: 2, unmapped: 2,
      ledger: 'posted', learned: false,
    })
  })

  it('a report read from memory says no AI was asked, and can still go to the AI', async () => {
    vi.mocked(readReportWithAi).mockResolvedValue({
      ...READING, pages_read: [], held_back: [], estimated_cost: '0', model: '',
      learned: { confirmed_at: '2026-09-12', reads: 3 },
    })
    renderPage()
    await pickAndRead()
    const memory = await screen.findByRole('region', { name: 'Read from memory' })
    expect(within(memory).getByText(/the way you confirmed on 2026-09-12/)).toBeInTheDocument()
    expect(within(memory).getByText(/3 reports read this way/)).toBeInTheDocument()
    // Not "0 pages went to …": no model was involved at all.
    expect(screen.queryByRole('region', { name: 'What it was shown' })).toBeNull()
    await userEvent.click(
      within(memory).getByRole('button', { name: 'Ask the AI helper to read it instead' }),
    )
    expect(vi.mocked(readReportWithAi).mock.calls.at(-1)?.[2]).toBe(true)
  })

  it('says when the layout no longer matches what was remembered', async () => {
    vi.mocked(readReportWithAi).mockResolvedValue({ ...READING, shape_changed: true })
    renderPage()
    await pickAndRead()
    expect(await screen.findByText(/doesn’t look like the ones you confirmed before/))
      .toBeInTheDocument()
  })

  it('says when it learned the layout from the rows that went in', async () => {
    vi.mocked(confirmAiReading).mockResolvedValue({
      property_id: 'HR', business_date: '2026-07-07', staged: 2, unmapped: 0,
      ledger: 'posted', learned: true,
    })
    renderPage()
    await pickAndRead()
    await userEvent.click(await screen.findByRole('button', { name: 'Put these in the books' }))
    expect(await screen.findByText(/Next time it is read without the AI helper/))
      .toBeInTheDocument()
  })

  it('says what will and will not be sent, before anything is', async () => {
    renderPage()
    const before = await screen.findByRole('region', { name: 'What happens' })
    expect(within(before).getByText(/no guest names, no account numbers/))
      .toBeInTheDocument()
    expect(within(before).getByText(/Nothing reaches your books until you/))
      .toBeInTheDocument()
    expect(readReportWithAi).not.toHaveBeenCalled()
  })

  it('reports which pages were held back, grouped by reason', async () => {
    renderPage()
    await pickAndRead()
    const shown = await screen.findByRole('region', { name: 'What it was shown' })
    expect(within(shown).getByText(/4 pages went to practice/)).toBeInTheDocument()
    expect(within(shown).getByText(/about \$0.012/)).toBeInTheDocument()
    // Grouped: two card-number pages read as one line, not two.
    expect(within(shown).getByText(/2 pages held back — something shaped like a card number/))
      .toBeInTheDocument()
    expect(within(shown).getByText(/1 page held back — something shaped like a person's name/))
      .toBeInTheDocument()
  })

  it('shows the rows for checking, and stages nothing on its own', async () => {
    renderPage()
    await pickAndRead()
    const found = await screen.findByRole('region', { name: 'What it found' })
    expect(within(found).getByText('Room Charge')).toBeInTheDocument()
    expect(within(found).getByText('$4,000.00')).toBeInTheDocument()
    expect(within(found).getByText('-$3,750.00')).toBeInTheDocument()
    expect(within(found).getByText(/what you accept is what goes in/)).toBeInTheDocument()
    expect(confirmAiReading).not.toHaveBeenCalled()
  })

  it('puts the rows in the books only when a person says so', async () => {
    renderPage()
    await pickAndRead()
    await screen.findByRole('region', { name: 'What it found' })
    await userEvent.click(screen.getByRole('button', { name: 'Put these in the books' }))

    await waitFor(() =>
      expect(confirmAiReading).toHaveBeenCalledWith({
        property_id: 'HR',
        file: 'audit.pdf',
        business_date: '2026-07-07',
        rows: READING.rows,
      }),
    )
    const changed = await screen.findByRole('region', { name: 'What changed' })
    expect(within(changed).getByText(/2 rows went in for 2026-07-07/)).toBeInTheDocument()
    // And it points at the one job left.
    expect(within(changed).getByText(/Codes to confirm/)).toBeInTheDocument()
  })

  it('lets the rows be thrown away instead', async () => {
    renderPage()
    await pickAndRead()
    await screen.findByRole('region', { name: 'What it found' })
    await userEvent.click(screen.getByRole('button', { name: 'Discard' }))
    expect(screen.queryByRole('region', { name: 'What it found' })).toBeNull()
    expect(confirmAiReading).not.toHaveBeenCalled()
  })

  it('says so plainly when it found nothing it could read', async () => {
    vi.mocked(readReportWithAi).mockResolvedValue({
      ...READING, rows: [], business_date: null,
      decline_reason: 'I could not find any charge lines on these pages.',
    })
    renderPage()
    await pickAndRead()
    expect(await screen.findByRole('status')).toHaveTextContent(/didn’t find any charges/)
    expect(screen.getByRole('status')).toHaveTextContent(/could not find any charge lines/)
  })

  it('shows the refusal when nothing could be sent at all', async () => {
    vi.mocked(readReportWithAi).mockRejectedValue(
      new Error('refusing to send: nothing on any page of this report that could be shown'),
    )
    renderPage()
    await pickAndRead()
    expect(await screen.findByRole('alert')).toHaveTextContent(/refusing to send/)
  })
})

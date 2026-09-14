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
  getCodes: vi.fn(),
  getCodeLines: vi.fn(),
  confirmCode: vi.fn(),
  getAiSettings: vi.fn(),
  suggestCode: vi.fn(),
}))

import { getProperties } from '../api/client'
import {
  confirmCode,
  getAiSettings,
  getCodeLines,
  getCodes,
  suggestCode,
  type AiSettings,
  type AiSuggestion,
  type CodeLine,
  type CodesState,
} from '../api/desktop'
import CodesPage from './CodesPage'

const ROOMS: CodeLine = {
  schedule_id: 1, major: 'Operated Departments', sub: 'Rooms',
  line_item: 'Room Revenue', gl_account_code: '4000',
}
const OTHER: CodeLine = {
  schedule_id: 1, major: 'Operated Departments', sub: 'Rooms',
  line_item: 'Other Rooms Revenue', gl_account_code: '4000',
}

const STATE: CodesState = {
  property_id: 'HISJ',
  edition: 12,
  money_not_in_the_books: '250.0000',
  settled_count: 3,
  items: [
    {
      code: 'ZZQ', description: 'Cabana Rental', pms_source: 'SKYTOUCH', status: 'unknown',
      times_seen: 2, amount: '250.0000', first_seen: '2026-04-01', last_seen: '2026-04-02',
      current: null, decided_by: null, decided_at: null,
    },
    {
      code: 'RM', description: 'Room Charge', pms_source: 'SKYTOUCH', status: 'unconfirmed',
      times_seen: 31, amount: '61200.0000', first_seen: '2026-03-01', last_seen: '2026-03-31',
      current: ROOMS, decided_by: null, decided_at: null,
    },
    {
      code: 'PET', description: 'Pet Charge', pms_source: 'SKYTOUCH', status: 'confirmed',
      times_seen: 4, amount: '100.0000', first_seen: '2026-03-04', last_seen: '2026-03-20',
      current: OTHER, decided_by: 'priya', decided_at: '2026-04-03T10:00:00Z',
    },
  ],
}

const AI_ON: AiSettings = {
  provider: 'mock', model: 'practice', base_url: null, cap: '10.00', max_calls: 500,
  price_in: null, price_out: null, key_saved: false, local: false, checked_at: null,
  spend: {
    month_start: '2026-04-01', calls: 3, estimated_cost: '0.02', unpriced_calls: 0,
    cap: '10.00', max_calls: 500, stopped: false,
  },
  providers: [],
  service: 'mock',
  services: [],
}

const SUGGESTED: AiSuggestion = {
  code: 'ZZQ', line: OTHER, confidence: 'high',
  reason: 'A cabana is a rooms extra, not a separate department.',
  decline_reason: null, estimated_cost: '0.004', model: 'practice',
  spend: AI_ON.spend,
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <CodesPage />
    </QueryClientProvider>,
  )
}

describe('CodesPage', () => {
  beforeEach(() => {
    vi.mocked(getProperties).mockResolvedValue([
      { property_id: 'HISJ', name: 'Holiday Inn San Jose' },
    ] as Awaited<ReturnType<typeof getProperties>>)
    vi.mocked(getCodes).mockReset().mockResolvedValue(STATE)
    vi.mocked(getCodeLines).mockReset().mockResolvedValue([ROOMS, OTHER])
    vi.mocked(confirmCode).mockReset().mockResolvedValue({
      code: 'ZZQ', days_restated: ['2026-04-01', '2026-04-02'], facts_written: 2,
      ledger_refused: {},
    })
    // Off unless a test turns it on: with the module off the route is not
    // mounted at all, which is what the client's null stands for.
    vi.mocked(getAiSettings).mockReset().mockResolvedValue(null)
    vi.mocked(suggestCode).mockReset().mockResolvedValue(SUGGESTED)
  })

  it('leads with the money that is not on the profit and loss', async () => {
    renderPage()
    const headline = await screen.findByRole('region', { name: 'Money not in your books' })
    expect(within(headline).getByText('$250.00')).toBeInTheDocument()
    expect(within(headline).getByText(/parked in a holding account/)).toBeInTheDocument()
  })

  it('says which codes nobody has explained, and which are only a guess', async () => {
    renderPage()
    const list = await screen.findByRole('region', { name: 'Codes' })
    expect(within(list).getByText('Not in your books')).toBeInTheDocument()
    expect(within(list).getByText('A guess')).toBeInTheDocument()
    expect(within(list).getByText('Confirmed')).toBeInTheDocument()
    // A code with nowhere to go says so, rather than showing a blank cell.
    expect(within(list).getByText('Nowhere')).toBeInTheDocument()
    expect(within(list).getByText(/Confirmed by priya/)).toBeInTheDocument()
    expect(within(list).getByText(/3 other codes/)).toBeInTheDocument()
  })

  it('confirms a code on a line the product knows, and says what changed', async () => {
    renderPage()
    await userEvent.click(await screen.findByRole('button', { name: 'Confirm ZZQ' }))

    const picker = await screen.findByLabelText('Where should ZZQ go?')
    await userEvent.selectOptions(picker, '1')
    await userEvent.type(
      screen.getByLabelText(/^Why/),
      'Cabanas are a rooms extra here.',
    )
    await userEvent.click(screen.getByRole('button', { name: 'Confirm' }))

    await waitFor(() =>
      expect(confirmCode).toHaveBeenCalledWith('ZZQ', {
        property_id: 'HISJ',
        pms_source: 'SKYTOUCH',
        line: OTHER,
        note: 'Cabanas are a rooms extra here.',
        // A person picked it themselves, so the decision is theirs.
        origin: 'owner',
      }),
    )
    const changed = await screen.findByRole('region', { name: 'What changed' })
    expect(within(changed).getByText(/ZZQ is confirmed, and 2 days worked out again/))
      .toBeInTheDocument()
  })

  it('warns when the books would not take some of the days', async () => {
    vi.mocked(confirmCode).mockResolvedValue({
      code: 'ZZQ', days_restated: ['2026-04-01'], facts_written: 1,
      ledger_refused: { '2026-04-01': 'no chart of accounts; GL is off' },
    })
    renderPage()
    await userEvent.click(await screen.findByRole('button', { name: 'Confirm ZZQ' }))
    await userEvent.selectOptions(await screen.findByLabelText('Where should ZZQ go?'), '1')
    await userEvent.click(screen.getByRole('button', { name: 'Confirm' }))

    const changed = await screen.findByRole('region', { name: 'What changed' })
    expect(within(changed).getByText(/would not take 1 of those days/)).toBeInTheDocument()
  })

  it('shows the refusal when confirming is refused', async () => {
    vi.mocked(confirmCode).mockRejectedValue(
      new Error("These days are in a closed month, so they can't be restated: 2026-05-04."),
    )
    renderPage()
    await userEvent.click(await screen.findByRole('button', { name: 'Confirm ZZQ' }))
    await userEvent.selectOptions(await screen.findByLabelText('Where should ZZQ go?'), '1')
    await userEvent.click(screen.getByRole('button', { name: 'Confirm' }))

    expect(await screen.findByRole('alert')).toHaveTextContent(/closed month/)
  })

  it('says plainly when every code is one we recognise', async () => {
    vi.mocked(getCodes).mockResolvedValue({
      ...STATE, items: [], money_not_in_the_books: '0', settled_count: 12,
    })
    renderPage()
    const list = await screen.findByRole('region', { name: 'Codes' })
    expect(within(list).getByText(/Every code on your reports is one we recognise/))
      .toBeInTheDocument()
    expect(screen.queryByRole('region', { name: 'Money not in your books' })).toBeNull()
  })

  it('on a hosted deployment, says the page is not part of it', async () => {
    vi.mocked(getCodes).mockResolvedValue(null)
    renderPage()
    expect(await screen.findByText(/part of the desktop edition/)).toBeInTheDocument()
  })
})

describe('CodesPage with the AI helper', () => {
  beforeEach(() => {
    vi.mocked(getProperties).mockResolvedValue([
      { property_id: 'HISJ', name: 'Holiday Inn San Jose' },
    ] as Awaited<ReturnType<typeof getProperties>>)
    vi.mocked(getCodes).mockReset().mockResolvedValue(STATE)
    vi.mocked(getCodeLines).mockReset().mockResolvedValue([ROOMS, OTHER])
    vi.mocked(confirmCode).mockReset().mockResolvedValue({
      code: 'ZZQ', days_restated: ['2026-04-01'], facts_written: 1, ledger_refused: {},
    })
    vi.mocked(getAiSettings).mockReset().mockResolvedValue(AI_ON)
    vi.mocked(suggestCode).mockReset().mockResolvedValue(SUGGESTED)
  })

  it('with the helper off there is nothing to press (AI-8)', async () => {
    vi.mocked(getAiSettings).mockResolvedValue(null)
    renderPage()
    await userEvent.click(await screen.findByRole('button', { name: 'Confirm ZZQ' }))
    await screen.findByLabelText('Where should ZZQ go?')
    expect(screen.queryByRole('button', { name: /Ask the AI/ })).toBeNull()
  })

  it('asks, shows what it said, and says the decision is still yours', async () => {
    renderPage()
    await userEvent.click(await screen.findByRole('button', { name: 'Confirm ZZQ' }))
    await userEvent.click(await screen.findByRole('button', { name: 'Ask the AI about ZZQ' }))

    await waitFor(() =>
      expect(suggestCode).toHaveBeenCalledWith({
        property_id: 'HISJ', pms_source: 'SKYTOUCH', code: 'ZZQ',
      }),
    )
    expect(await screen.findByText(/A cabana is a rooms extra/)).toBeInTheDocument()
    expect(screen.getByText(/Nothing changes until you press Confirm/)).toBeInTheDocument()
    // What it cost, where the owner can see it (AI-3).
    expect(screen.getByText(/about \$0.004/)).toBeInTheDocument()
  })

  it('accepting what it said records that a person accepted it (AI-6)', async () => {
    renderPage()
    await userEvent.click(await screen.findByRole('button', { name: 'Confirm ZZQ' }))
    await userEvent.click(await screen.findByRole('button', { name: 'Ask the AI about ZZQ' }))
    await screen.findByText(/A cabana is a rooms extra/)
    await userEvent.click(screen.getByRole('button', { name: 'Confirm' }))

    await waitFor(() =>
      expect(confirmCode).toHaveBeenCalledWith('ZZQ', expect.objectContaining({
        line: OTHER,
        origin: 'ai-accepted',
      })),
    )
  })

  it('choosing something else instead is the owner’s own decision', async () => {
    renderPage()
    await userEvent.click(await screen.findByRole('button', { name: 'Confirm ZZQ' }))
    await userEvent.click(await screen.findByRole('button', { name: 'Ask the AI about ZZQ' }))
    await screen.findByText(/A cabana is a rooms extra/)
    // The model said line 1; the owner picks line 0 instead.
    await userEvent.selectOptions(screen.getByLabelText('Where should ZZQ go?'), '0')
    await userEvent.click(screen.getByRole('button', { name: 'Confirm' }))

    await waitFor(() =>
      expect(confirmCode).toHaveBeenCalledWith('ZZQ', expect.objectContaining({
        line: ROOMS,
        origin: 'owner',
      })),
    )
  })

  it('shows a refusal to guess as an answer, not an error (AI-7)', async () => {
    vi.mocked(suggestCode).mockResolvedValue({
      ...SUGGESTED, line: null, confidence: 'low', reason: '',
      decline_reason: 'This turns on your hotel’s tax treatment. Ask your accountant.',
    })
    renderPage()
    await userEvent.click(await screen.findByRole('button', { name: 'Confirm ZZQ' }))
    await userEvent.click(await screen.findByRole('button', { name: 'Ask the AI about ZZQ' }))

    expect(await screen.findByText(/It wouldn’t guess/)).toBeInTheDocument()
    expect(screen.getByText(/Ask your accountant/)).toBeInTheDocument()
    expect(screen.queryByRole('alert')).toBeNull()
  })

  it('shows the cap’s refusal in the owner’s words', async () => {
    vi.mocked(suggestCode).mockRejectedValue(
      new Error("You've used all 500 AI checks for this month."),
    )
    renderPage()
    await userEvent.click(await screen.findByRole('button', { name: 'Confirm ZZQ' }))
    await userEvent.click(await screen.findByRole('button', { name: 'Ask the AI about ZZQ' }))

    expect(await screen.findByRole('alert')).toHaveTextContent(/all 500 AI checks/)
  })
})

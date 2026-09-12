import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../api/desktop', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api/desktop')>()),
  getAiSettings: vi.fn(),
  saveAiSettings: vi.fn(),
  forgetAiKey: vi.fn(),
}))

import {
  forgetAiKey,
  getAiSettings,
  saveAiSettings,
  type AiSettings,
} from '../api/desktop'
import AiPage from './AiPage'

const SETTINGS: AiSettings = {
  provider: 'anthropic',
  model: 'claude-test',
  base_url: null,
  cap: '10.00',
  max_calls: 500,
  price_in: null,
  price_out: null,
  key_saved: true,
  local: false,
  spend: {
    month_start: '2026-06-01', calls: 12, estimated_cost: '0.34', unpriced_calls: 0,
    cap: '10.00', max_calls: 500, stopped: false,
  },
  providers: [
    { id: 'openai_compatible', name: 'OpenRouter, OpenAI, Ollama, or any compatible service',
      needs_address: true, needs_key: true },
    { id: 'anthropic', name: 'Anthropic', needs_address: false, needs_key: true },
    { id: 'mock', name: 'Practice mode (answers offline, costs nothing)',
      needs_address: false, needs_key: false },
  ],
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <AiPage />
    </QueryClientProvider>,
  )
}

describe('AiPage', () => {
  beforeEach(() => {
    vi.mocked(getAiSettings).mockReset().mockResolvedValue(SETTINGS)
    vi.mocked(saveAiSettings).mockReset().mockResolvedValue(SETTINGS)
    vi.mocked(forgetAiKey).mockReset().mockResolvedValue(undefined)
  })

  it('shows what it has cost this month against the limit (AI-3)', async () => {
    renderPage()
    const cost = await screen.findByRole('region', { name: 'What it has cost' })
    expect(within(cost).getByText('$0.34')).toBeInTheDocument()
    expect(within(cost).getByText(/12 questions asked since 2026-06-01/)).toBeInTheDocument()
    // Honest about what the figure is.
    expect(within(cost).getByText(/Your provider’s own bill is the real one/))
      .toBeInTheDocument()
  })

  it('says plainly when it cannot price the month, rather than showing zero', async () => {
    vi.mocked(getAiSettings).mockResolvedValue({
      ...SETTINGS,
      spend: { ...SETTINGS.spend, estimated_cost: null, unpriced_calls: 12 },
    })
    renderPage()
    const cost = await screen.findByRole('region', { name: 'What it has cost' })
    expect(within(cost).getByText('Not known')).toBeInTheDocument()
    expect(within(cost).getByText(/we don’t know what your provider charges/))
      .toBeInTheDocument()
    // The other half of the cap still holds, and is said so.
    expect(within(cost).getByText(/limit on the number of questions still applies/))
      .toBeInTheDocument()
  })

  it('a model on this computer costs nothing and says nothing leaves', async () => {
    vi.mocked(getAiSettings).mockResolvedValue({ ...SETTINGS, local: true })
    renderPage()
    const cost = await screen.findByRole('region', { name: 'What it has cost' })
    expect(within(cost).getByText('Nothing')).toBeInTheDocument()
    expect(within(cost).getByText(/nothing leaves the building/)).toBeInTheDocument()
  })

  it('says when the month has stopped it', async () => {
    vi.mocked(getAiSettings).mockResolvedValue({
      ...SETTINGS,
      spend: { ...SETTINGS.spend, estimated_cost: '10.00', stopped: true },
    })
    renderPage()
    const cost = await screen.findByRole('region', { name: 'What it has cost' })
    expect(within(cost).getByText('Stopped for this month')).toBeInTheDocument()
  })

  it('never shows the key back, and says where it lives', async () => {
    renderPage()
    const field = await screen.findByLabelText(/The key your provider gave you/)
    expect(field).toHaveValue('')
    expect(field).toHaveAttribute('type', 'password')
    expect(screen.getByText(/kept in this computer’s password store/)).toBeInTheDocument()
    expect(screen.getByText(/never in your books and never in a backup/)).toBeInTheDocument()
  })

  it('saves the choice, and the key only when one was typed', async () => {
    renderPage()
    await userEvent.type(
      await screen.findByLabelText(/The key your provider gave you/),
      'sk-typed-here',
    )
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() =>
      expect(saveAiSettings).toHaveBeenCalledWith(
        expect.objectContaining({ provider: 'anthropic', model: 'claude-test', key: 'sk-typed-here' }),
      ),
    )
  })

  it('leaves the saved key alone when the field is left blank', async () => {
    renderPage()
    await userEvent.click(await screen.findByRole('button', { name: 'Save' }))
    await waitFor(() => expect(saveAiSettings).toHaveBeenCalled())
    expect(vi.mocked(saveAiSettings).mock.calls[0][0]).not.toHaveProperty('key')
  })

  it('an address is asked for only by the helper that needs one', async () => {
    renderPage()
    await screen.findByLabelText(/Which model/)
    expect(screen.queryByLabelText(/web address/)).toBeNull()
    await userEvent.selectOptions(
      screen.getByLabelText(/Who you have an account with/),
      'openai_compatible',
    )
    expect(await screen.findByLabelText(/web address/)).toBeInTheDocument()
    expect(screen.getByText(/localhost:11434/)).toBeInTheDocument()
  })

  it('the owner can make it forget the key', async () => {
    renderPage()
    await userEvent.click(await screen.findByRole('button', { name: 'Forget the key' }))
    await waitFor(() => expect(forgetAiKey).toHaveBeenCalled())
  })

  it('shows the refusal when saving is refused', async () => {
    vi.mocked(saveAiSettings).mockRejectedValue(
      new Error('That helper needs the web address its service answers on.'),
    )
    renderPage()
    await userEvent.click(await screen.findByRole('button', { name: 'Save' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(/web address/)
  })

  it('says what the model is shown, and what it is never shown (AI-4)', async () => {
    renderPage()
    const what = await screen.findByRole('region', { name: 'What it is shown' })
    expect(within(what).getByText(/fixed in the app, not a setting/)).toBeInTheDocument()
    expect(
      within(what).getByText(/never shown a person’s name, a pay rate, a bank detail/),
    ).toBeInTheDocument()
    expect(within(what).getByText(/refuses to send it rather than tidying it away/))
      .toBeInTheDocument()
  })

  it('with the module off, it points at Modules rather than showing a form', async () => {
    vi.mocked(getAiSettings).mockResolvedValue(null)
    renderPage()
    expect(await screen.findByText(/Turn it on under Modules/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Save' })).toBeNull()
  })
})

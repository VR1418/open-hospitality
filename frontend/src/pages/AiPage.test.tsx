import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../api/desktop', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api/desktop')>()),
  getAiSettings: vi.fn(),
  saveAiSettings: vi.fn(),
  forgetAiKey: vi.fn(),
  getAiModels: vi.fn(),
  checkAiConnection: vi.fn(),
}))

import {
  checkAiConnection,
  forgetAiKey,
  getAiModels,
  getAiSettings,
  saveAiSettings,
  type AiModels,
  type AiService,
  type AiSettings,
} from '../api/desktop'
import AiPage from './AiPage'

function svc(over: Partial<AiService> & { id: string }): AiService {
  return {
    name: over.id, provider: 'openai_compatible', base_url: null, address_editable: false,
    needs_key: true, key_hint: 'Your key.', lists_models: false, ...over,
  }
}

const SERVICES: AiService[] = [
  svc({ id: 'openrouter', name: 'OpenRouter — one account for Claude, GPT, Gemini and more',
        base_url: 'https://openrouter.ai/api/v1', lists_models: true,
        key_hint: 'On openrouter.ai, open Keys and create one.' }),
  svc({ id: 'anthropic', name: 'Anthropic (Claude) — directly', provider: 'anthropic',
        lists_models: true }),
  svc({ id: 'local', name: 'A model on this computer (Ollama or LM Studio)',
        base_url: 'http://localhost:11434/v1', address_editable: true, needs_key: false }),
  svc({ id: 'mock', name: 'Practice mode', provider: 'mock', needs_key: false }),
]

const OPENROUTER_MODELS: AiModels = {
  live: true,
  recommended: 'anthropic/claude-sonnet-5',
  models: [
    { id: 'anthropic/claude-sonnet-5', name: 'Claude Sonnet 5', maker: 'Anthropic (Claude)',
      price_in: '2.00', price_out: '10.00' },
    { id: 'anthropic/claude-haiku-4.5', name: 'Claude Haiku 4.5', maker: 'Anthropic (Claude)',
      price_in: '1.00', price_out: '5.00' },
    { id: 'openai/gpt-5.6-sol', name: 'GPT-5.6 Sol', maker: 'OpenAI (GPT)',
      price_in: '2.00', price_out: '10.00' },
  ],
}

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
  checked_at: '2026-09-13T21:02:00',
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
  service: 'anthropic',
  services: SERVICES,
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
    vi.mocked(getAiModels).mockReset().mockImplementation(async (service) =>
      service === 'openrouter'
        ? OPENROUTER_MODELS
        : {
            live: true,
            recommended: 'claude-test',
            models: [{ id: 'claude-test', name: 'Claude Test', maker: 'Anthropic (Claude)',
                       price_in: '2.00', price_out: '10.00' }],
          },
    )
    vi.mocked(checkAiConnection).mockReset().mockResolvedValue({
      model: 'claude-test', said: 'OK', estimated_cost: '0.0001', spend: SETTINGS.spend,
    })
  })

  it('an OpenRouter owner picks Claude from a list, and its address and price fill themselves', async () => {
    // Reported: the owner had an OpenRouter key and no idea how to choose
    // Anthropic's model on it.
    vi.mocked(getAiSettings).mockResolvedValue({
      ...SETTINGS, provider: null, model: '', service: null, key_saved: false,
    })
    renderPage()
    await userEvent.selectOptions(
      await screen.findByLabelText(/Who you have an account with/), 'openrouter',
    )
    const pick = await screen.findByLabelText('Which model')
    await waitFor(() =>
      expect(within(pick).getByText(/Claude Sonnet 5 \(recommended\)/)).toBeInTheDocument(),
    )
    // Grouped by maker, with the price on the line.
    expect(within(pick).getByRole('group', { name: 'Anthropic (Claude)' })).toBeInTheDocument()
    expect(within(pick).getAllByText(/\$2\.00 in \/ \$10\.00 out per million/).length).toBeGreaterThan(0)
    // No web address to type for a hosted service, and where the key comes from.
    expect(screen.queryByLabelText(/web address/)).toBeNull()
    expect(screen.getByText(/On openrouter.ai, open Keys/)).toBeInTheDocument()

    await userEvent.selectOptions(pick, 'anthropic/claude-sonnet-5')
    await userEvent.type(screen.getByLabelText(/The key your provider gave you/), 'sk-or-typed')
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() =>
      expect(saveAiSettings).toHaveBeenCalledWith(
        expect.objectContaining({
          provider: 'openai_compatible',
          base_url: 'https://openrouter.ai/api/v1',
          model: 'anthropic/claude-sonnet-5',
          price_in: '2.00',
          price_out: '10.00',
          key: 'sk-or-typed',
        }),
      ),
    )
  })

  it('a model that is not listed can still be typed', async () => {
    vi.mocked(getAiSettings).mockResolvedValue({
      ...SETTINGS, service: null, provider: null, model: '',
    })
    renderPage()
    await userEvent.selectOptions(
      await screen.findByLabelText(/Who you have an account with/), 'openrouter',
    )
    const pick = await screen.findByLabelText('Which model')
    await waitFor(() => expect(pick).toBeEnabled())
    await userEvent.selectOptions(pick, '__typed__')
    await userEvent.type(screen.getByLabelText(/The model’s name/), 'meta/llama-9')
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() =>
      expect(saveAiSettings).toHaveBeenCalledWith(
        expect.objectContaining({ model: 'meta/llama-9', price_in: null, price_out: null }),
      ),
    )
  })

  it('keeps a saved model that is not on the shortlist as the current choice', async () => {
    vi.mocked(getAiSettings).mockResolvedValue({
      ...SETTINGS, service: 'openrouter', provider: 'openai_compatible',
      base_url: 'https://openrouter.ai/api/v1', model: 'anthropic/claude-sonnet-4.5',
    })
    renderPage()
    const pick = await screen.findByLabelText('Which model')
    await waitFor(() => expect(pick).toBeEnabled())
    expect(pick).toHaveValue('anthropic/claude-sonnet-4.5')
    expect(within(pick).getByText(/claude-sonnet-4.5 \(your current choice\)/)).toBeInTheDocument()
    // Not dropped into "type its name": the box for that is absent.
    expect(screen.queryByLabelText(/The model’s name/)).toBeNull()
  })

  it('says when the up-to-date list could not be reached', async () => {
    vi.mocked(getAiModels).mockResolvedValue({ ...OPENROUTER_MODELS, live: false })
    renderPage()
    expect(await screen.findByText(/couldn’t reach the up-to-date list/)).toBeInTheDocument()
  })

  it('checks the saved helper really answers, and says what that cost', async () => {
    renderPage()
    await userEvent.click(await screen.findByRole('button', { name: 'Check it works' }))
    expect(await screen.findByRole('status')).toHaveTextContent(
      /It works — claude-test answered “OK”.*about \$0\.0001/,
    )
  })

  it('shows why the check failed, in the service’s words', async () => {
    vi.mocked(checkAiConnection).mockRejectedValue(new Error('The service refused the key.'))
    renderPage()
    await userEvent.click(await screen.findByRole('button', { name: 'Check it works' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('refused the key')
  })

  it('says whether the helper is connected, and when it was last checked', async () => {
    renderPage()
    const status = await screen.findByRole('region', { name: 'Connection' })
    expect(within(status).getByText('Connected')).toBeInTheDocument()
    expect(within(status).getByText(/claude-test via Anthropic \(Claude\)/)).toBeInTheDocument()
    expect(within(status).getByText(/checked/)).toBeInTheDocument()
  })

  it('says a helper that was never checked is not yet known to work', async () => {
    vi.mocked(getAiSettings).mockResolvedValue({ ...SETTINGS, checked_at: null })
    renderPage()
    const status = await screen.findByRole('region', { name: 'Connection' })
    expect(within(status).getByText('Not checked yet')).toBeInTheDocument()
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
    expect(vi.mocked(saveAiSettings).mock.calls[0]?.[0]).not.toHaveProperty('key')
  })

  it('an address is asked for only by the helper that needs one', async () => {
    renderPage()
    await screen.findByLabelText('Which model')
    expect(screen.queryByLabelText(/web address/)).toBeNull()
    await userEvent.selectOptions(screen.getByLabelText(/Who you have an account with/), 'local')
    expect(await screen.findByLabelText(/web address/)).toBeInTheDocument()
    expect(screen.getByText(/localhost:11434/)).toBeInTheDocument()
    // A model on this computer needs no key.
    expect(screen.queryByLabelText(/The key your provider gave you/)).toBeNull()
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

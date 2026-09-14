// Desktop edition: the owner's own AI helper (PRD §6.3, ADR-D7).
//
// Three things this screen has to be honest about, because the PRD is:
// the key never leaves this computer's password store and is never shown
// back; the monthly limit is real and the app stops at it; and what the
// model is shown is fixed in code, not in a setting anyone can widen.
//
// The word "API key" does not appear here — appendix A. It is "the key your
// provider gave you", and the helper is "off", never "not connected".
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'

import {
  checkAiConnection,
  forgetAiKey,
  getAiModels,
  getAiSettings,
  saveAiSettings,
  type AiModel,
  type AiSettings,
  type AiSpend,
} from '../api/desktop'
import { Badge, Card, PageHeader, controlClass, sectionHeadClass } from '../components/ui'
import { errorMessage } from '../lib/errors'
import { fmtMoney } from '../lib/format'

const buttonClass =
  'rounded-lg border border-line px-3 py-1.5 text-sm font-medium text-ink hover:bg-surface-sunken disabled:cursor-not-allowed disabled:opacity-50'
const primaryButtonClass =
  'rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-accent-contrast hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50'
const fieldClass = 'flex flex-col gap-1 text-sm'
/** The model picker's "type it yourself" choice. */
const TYPED = '__typed__'
const labelClass = 'text-xs font-medium text-ink-muted'

function SpendCard({ spend, local }: { spend: AiSpend; local: boolean }) {
  return (
    <Card>
      <section aria-label="What it has cost" className="flex flex-col gap-2">
        <h2 className={sectionHeadClass}>This month</h2>
        <div className="flex flex-wrap items-baseline gap-x-6 gap-y-1">
          <p className="text-2xl font-semibold tabular-nums text-ink">
            {local
              ? 'Nothing'
              : spend.estimated_cost === null
                ? 'Not known'
                : `$${fmtMoney(spend.estimated_cost)}`}
          </p>
          <p className="text-sm text-ink-muted">
            {spend.calls} question{spend.calls === 1 ? '' : 's'} asked since{' '}
            {spend.month_start}, of {spend.max_calls} allowed.
          </p>
          {spend.stopped && <Badge tone="danger">Stopped for this month</Badge>}
        </div>
        {local ? (
          <p className="text-xs text-ink-muted">
            Your model runs on this computer, so it costs nothing and nothing leaves the
            building.
          </p>
        ) : spend.estimated_cost === null ? (
          <p className="text-xs text-ink-muted">
            We can’t work out the cost because we don’t know what your provider charges
            {spend.unpriced_calls > 0 && ` (${spend.unpriced_calls} question${
              spend.unpriced_calls === 1 ? '' : 's'
            } so far)`}
            . Add the two prices below and we will, or leave it and the limit on the number
            of questions still applies.
          </p>
        ) : (
          <p className="text-xs text-ink-muted">
            Our estimate, against your ${fmtMoney(spend.cap)} limit. Your provider’s own bill
            is the real one and will differ a little.
          </p>
        )}
      </section>
    </Card>
  )
}

function ModelPicker({
  models,
  live,
  loading,
  recommended,
  value,
  typing,
  onPick,
  onType,
}: {
  models: AiModel[]
  live: boolean
  loading: boolean
  recommended: string | null
  value: string
  typing: boolean
  onPick: (m: AiModel | null) => void
  onType: (model: string) => void
}) {
  const listed = models.some((m) => m.id === value)
  const selected = typing || (value !== '' && !listed && !loading) ? TYPED : value
  const makers = [...new Set(models.map((m) => m.maker))]
  const price = (m: AiModel) =>
    m.price_in !== null && m.price_out !== null
      ? ` — $${Number(m.price_in).toFixed(2)} in / $${Number(m.price_out).toFixed(2)} out per million`
      : ''
  return (
    <div className="flex flex-col gap-2">
      <label className={fieldClass} htmlFor="ai-model-pick">
        <span className={labelClass}>Which model</span>
        <select
          id="ai-model-pick"
          className={controlClass}
          value={selected}
          disabled={loading}
          onChange={(e) =>
            onPick(
              e.target.value === TYPED
                ? null
                : (models.find((m) => m.id === e.target.value) ?? null),
            )
          }
        >
          <option value="" disabled>
            {loading ? 'Loading the list…' : 'Choose a model'}
          </option>
          {makers.map((maker) => (
            <optgroup key={maker || 'models'} label={maker || 'Models'}>
              {models
                .filter((m) => m.maker === maker)
                .map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.name}
                    {m.id === recommended ? ' (recommended)' : ''}
                    {price(m)}
                  </option>
                ))}
            </optgroup>
          ))}
          <option value={TYPED}>Another model — type its name</option>
        </select>
        {!live && (
          <span className="text-xs text-ink-muted">
            We couldn’t reach the up-to-date list, so this is a short one without prices.
          </span>
        )}
      </label>
      {selected === TYPED && (
        <label className={fieldClass} htmlFor="ai-model">
          <span className={labelClass}>The model’s name, exactly as the service writes it</span>
          <input
            id="ai-model"
            className={controlClass}
            value={value}
            onChange={(e) => onType(e.target.value)}
          />
        </label>
      )}
    </div>
  )
}

export default function AiPage() {
  const queryClient = useQueryClient()
  const ai = useQuery({ queryKey: ['ai'], queryFn: getAiSettings, retry: false })
  const [form, setForm] = useState<Partial<AiSettings> & { key?: string }>({})
  const [saved, setSaved] = useState(false)
  const [typing, setTyping] = useState(false)

  const check = useMutation({
    mutationFn: checkAiConnection,
    onSettled: () => void queryClient.invalidateQueries({ queryKey: ['ai'] }),
  })

  const settings = ai.data
  const value = <K extends keyof AiSettings>(field: K): AiSettings[K] | undefined =>
    (form[field] as AiSettings[K] | undefined) ?? settings?.[field]
  const set = (patch: Partial<AiSettings> & { key?: string }) => {
    setSaved(false)
    check.reset()
    setForm({ ...form, ...patch })
  }

  const serviceId = value('service') ?? null
  const service = settings?.services.find((x) => x.id === serviceId)
  const models = useQuery({
    queryKey: ['ai-models', serviceId],
    queryFn: () => getAiModels(serviceId as string),
    enabled: service?.lists_models === true,
    staleTime: 60 * 60 * 1000,
    retry: false,
  })

  const save = useMutation({
    mutationFn: () =>
      saveAiSettings({
        // The service decides the adapter and, for hosted ones, the address:
        // the owner never types either.
        provider: service?.provider ?? String(value('provider') ?? ''),
        model: String(value('model') ?? ''),
        base_url: service?.address_editable
          ? (value('base_url') ?? service.base_url)
          : (service?.base_url ?? value('base_url') ?? null),
        cap: String(value('cap') ?? '10.00'),
        max_calls: Number(value('max_calls') ?? 500),
        price_in: value('price_in') ?? null,
        price_out: value('price_out') ?? null,
        ...(form.key ? { key: form.key } : {}),
      }),
    onSuccess: () => {
      setForm({})
      setSaved(true)
      void queryClient.invalidateQueries({ queryKey: ['ai'] })
    },
  })

  const forget = useMutation({
    mutationFn: forgetAiKey,
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['ai'] }),
  })

  if (settings === null) {
    return (
      <div className="flex flex-col gap-4">
        <PageHeader title="AI helper" />
        <Card>
          <p className="text-sm text-ink-muted">
            The AI helper is off. Turn it on under Modules if you want it.
          </p>
        </Card>
      </div>
    )
  }
  if (settings === undefined) {
    return (
      <div className="flex flex-col gap-4">
        <PageHeader title="AI helper" />
        <Card>
          {ai.isError ? (
            <p className="text-sm text-danger-red">{errorMessage(ai.error)}</p>
          ) : (
            <p className="text-sm text-ink-muted">Loading…</p>
          )}
        </Card>
      </div>
    )
  }

  const submit = (e: FormEvent) => {
    e.preventDefault()
    save.mutate()
  }

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        title="AI helper"
        subtitle="Your own AI account, used to suggest where charge codes belong"
      />

      <Card>
        <section aria-label="Connection" className="flex flex-wrap items-center gap-3">
          {settings.provider === null ? (
            <>
              <Badge tone="neutral">Not set up</Badge>
              <p className="text-sm text-ink">Choose who you have an account with below, then Save.</p>
            </>
          ) : settings.checked_at !== null ? (
            <>
              <Badge tone="ok">Connected</Badge>
              <p className="text-sm text-ink">
                {settings.model} via {settings.services.find((x) => x.id === settings.service)?.name.split(' — ')[0] ?? settings.provider}
                {' · '}checked {new Date(settings.checked_at).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })}
              </p>
            </>
          ) : (
            <>
              <Badge tone="warn">Not checked yet</Badge>
              <p className="text-sm text-ink">
                {settings.model || 'No model chosen'}
                {settings.key_saved || settings.local || settings.provider === 'mock'
                  ? ' — press “Check it works” below to be sure it answers.'
                  : ' — no key saved yet.'}
              </p>
            </>
          )}
        </section>
      </Card>

      <SpendCard spend={settings.spend} local={settings.local} />

      <Card>
        <form className="flex flex-col gap-4" onSubmit={submit}>
          <section aria-label="Your helper" className="flex flex-col gap-4">
            <h2 className={sectionHeadClass}>Your helper</h2>

            <label className={fieldClass} htmlFor="ai-service">
              <span className={labelClass}>Who you have an account with</span>
              <select
                id="ai-service"
                className={controlClass}
                value={serviceId ?? ''}
                onChange={(e) => {
                  const next = settings.services.find((x) => x.id === e.target.value)
                  setTyping(false)
                  set({
                    service: e.target.value,
                    provider: next?.provider ?? null,
                    base_url: next?.base_url ?? null,
                    model: next?.id === 'mock' ? 'practice' : '',
                    price_in: null,
                    price_out: null,
                  })
                }}
              >
                <option value="" disabled>
                  Choose one
                </option>
                {settings.services.map((x) => (
                  <option key={x.id} value={x.id}>
                    {x.name}
                  </option>
                ))}
              </select>
            </label>

            {service?.lists_models && (
              <ModelPicker
                models={models.data?.models ?? []}
                live={models.data?.live ?? true}
                loading={models.isLoading}
                recommended={models.data?.recommended ?? null}
                value={String(value('model') ?? '')}
                typing={typing}
                onPick={(m) => {
                  if (m === null) {
                    setTyping(true)
                    set({ model: '', price_in: null, price_out: null })
                    return
                  }
                  setTyping(false)
                  // A listed model brings its price, so the monthly limit
                  // counts dollars from the first question.
                  set({ model: m.id, price_in: m.price_in, price_out: m.price_out })
                }}
                onType={(model) => set({ model })}
              />
            )}

            {service !== undefined && !service.lists_models && service.id !== 'mock' && (
              <label className={fieldClass} htmlFor="ai-model">
                <span className={labelClass}>Which model, exactly as the service writes it</span>
                <input
                  id="ai-model"
                  className={controlClass}
                  placeholder={service.id === 'local' ? 'llama3.1' : ''}
                  value={value('model') ?? ''}
                  onChange={(e) => set({ model: e.target.value })}
                />
              </label>
            )}

            {service?.address_editable && (
              <label className={fieldClass} htmlFor="ai-address">
                <span className={labelClass}>The web address it answers on</span>
                <input
                  id="ai-address"
                  className={controlClass}
                  placeholder={service.base_url ?? 'https://…/v1'}
                  value={value('base_url') ?? ''}
                  onChange={(e) => set({ base_url: e.target.value })}
                />
                {service.id === 'local' && (
                  <span className="text-xs text-ink-muted">
                    Ollama answers on http://localhost:11434/v1 and LM Studio on
                    http://localhost:1234/v1. Nothing then leaves the building.
                  </span>
                )}
              </label>
            )}

            {service?.needs_key && (
              <label className={fieldClass} htmlFor="ai-key">
                <span className={labelClass}>
                  The key your provider gave you
                  {settings.key_saved && ' — one is already saved'}
                </span>
                <input
                  id="ai-key"
                  type="password"
                  className={controlClass}
                  placeholder={settings.key_saved ? 'Leave blank to keep the one saved' : ''}
                  value={form.key ?? ''}
                  onChange={(e) => set({ key: e.target.value })}
                />
                <span className="text-xs text-ink-muted">
                  {service.key_hint} It is kept in this computer’s password store, never in
                  your books and never in a backup. We can’t show it back to you, and we never send it anywhere
                  but your provider.
                </span>
              </label>
            )}
          </section>

          <section aria-label="Limits" className="flex flex-col gap-4">
            <h2 className={sectionHeadClass}>Limits</h2>
            <div className="flex flex-wrap gap-4">
              <label className={fieldClass} htmlFor="ai-cap">
                <span className={labelClass}>Most it may cost in a month</span>
                <input
                  id="ai-cap"
                  className={controlClass}
                  value={value('cap') ?? '10.00'}
                  onChange={(e) => set({ cap: e.target.value })}
                />
              </label>
              <label className={fieldClass} htmlFor="ai-calls">
                <span className={labelClass}>Most questions in a month</span>
                <input
                  id="ai-calls"
                  className={controlClass}
                  inputMode="numeric"
                  value={String(value('max_calls') ?? 500)}
                  onChange={(e) => set({ max_calls: Number(e.target.value) || 1 })}
                />
              </label>
            </div>
            <p className="text-xs text-ink-muted">
              Both apply. The app stops when either is reached and tells you which.
            </p>

            <div className="flex flex-wrap gap-4">
              <label className={fieldClass} htmlFor="ai-price-in">
                <span className={labelClass}>Your price per million words in (optional)</span>
                <input
                  id="ai-price-in"
                  className={controlClass}
                  value={value('price_in') ?? ''}
                  onChange={(e) => set({ price_in: e.target.value })}
                />
              </label>
              <label className={fieldClass} htmlFor="ai-price-out">
                <span className={labelClass}>…and per million words out</span>
                <input
                  id="ai-price-out"
                  className={controlClass}
                  value={value('price_out') ?? ''}
                  onChange={(e) => set({ price_out: e.target.value })}
                />
              </label>
            </div>
            <p className="text-xs text-ink-muted">
              From your provider’s own pricing page. We don’t guess at these: without them we
              count questions instead of dollars, and say so.
            </p>
          </section>

          {save.isError && (
            <p role="alert" className="text-sm text-danger-red">
              {errorMessage(save.error)}
            </p>
          )}
          {saved && (
            <p role="status" className="text-sm text-ink-muted">
              Saved.
            </p>
          )}

          {check.isSuccess && (
            <p role="status" className="text-sm text-ink">
              It works — {check.data.model} answered
              {check.data.said ? ` “${check.data.said}”` : ''}.
              {check.data.estimated_cost !== null &&
                ` That check cost about $${Number(check.data.estimated_cost).toFixed(4)}.`}
            </p>
          )}
          {check.isError && (
            <p role="alert" className="text-sm text-danger-red">
              {errorMessage(check.error)}
            </p>
          )}

          <div className="flex flex-wrap gap-2">
            <button type="submit" className={primaryButtonClass} disabled={save.isPending}>
              {save.isPending ? 'Saving…' : 'Save'}
            </button>
            {settings.provider !== null && Object.keys(form).length === 0 && (
              <button
                type="button"
                className={buttonClass}
                disabled={check.isPending}
                onClick={() => check.mutate()}
              >
                {check.isPending ? 'Checking…' : 'Check it works'}
              </button>
            )}
            {settings.key_saved && (
              <button
                type="button"
                className={buttonClass}
                disabled={forget.isPending}
                onClick={() => forget.mutate()}
              >
                Forget the key
              </button>
            )}
          </div>
        </form>
      </Card>

      <Card>
        <section aria-label="What it is shown" className="flex flex-col gap-2">
          <h2 className={sectionHeadClass}>What it is shown</h2>
          <p className="text-sm text-ink">
            The charge code, how your report describes it, the dates it appeared and the
            amounts. That list is fixed in the app, not a setting.
          </p>
          <p className="text-sm text-ink-muted">
            It is never shown a person’s name, a pay rate, a bank detail or an account
            number — and if any of those ever turned up in a request, the app refuses to send
            it rather than tidying it away.
          </p>
          <p className="text-sm text-ink-muted">
            It only ever suggests. Nothing reaches your books until you click to accept it,
            and your name goes on that decision.
          </p>
        </section>
      </Card>
    </div>
  )
}

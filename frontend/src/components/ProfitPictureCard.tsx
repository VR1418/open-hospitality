// Desktop edition: which hotels are making money, by the owner's own number
// (src/usali/desktop/portfolio_api.py, docs/desktop/PLAN-multi-hotel.md B3).
//
// The owner types one figure per hotel — the revenue it needs in a YEAR to
// cover its costs — and, until a report or the books supply it, last year's
// total revenue. The server divides the breakeven by the days in the year and
// compares last night, and the year to date, against it; the projection for
// the year is shaped by last year where the report prints it, and by a plain
// run rate otherwise. This card says the verdict in words and names which.
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'

import { putTargets, type BreakevenSummary, type PortfolioHotel } from '../api/desktop'
import { Badge, Card, controlClass, sectionHeadClass } from './ui'
import { errorMessage } from '../lib/errors'

const buttonClass =
  'rounded-lg border border-line px-3 py-1.5 text-sm font-medium text-ink hover:bg-surface-sunken disabled:opacity-50'
const primaryButtonClass =
  'rounded-lg bg-accent px-3 py-1.5 text-sm font-semibold text-accent-contrast hover:opacity-90 disabled:opacity-50'

function money(value: string | null | undefined, digits = 0): string {
  if (value === null || value === undefined) return '—'
  return Number(value).toLocaleString(undefined, {
    style: 'currency', currency: 'USD', minimumFractionDigits: digits, maximumFractionDigits: digits,
  })
}

function sinceLabel(iso: string): string {
  const d = new Date(`${iso}T00:00:00`)
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleDateString(undefined, { day: 'numeric', month: 'short' })
}

/** The verdict, in the owner's words. */
function verdict(h: PortfolioHotel): { tone: 'ok' | 'warn' | 'neutral'; head: string; detail: string } {
  const o = h.outlook
  if (o === null) {
    return { tone: 'neutral', head: 'No breakeven set', detail: 'Type this hotel’s annual breakeven to see where it stands.' }
  }
  const night =
    o.night_gap === null
      ? 'no report for last night'
      : Number(o.night_gap) >= 0
        ? `${money(o.night_gap)} above last night`
        : `${money(String(-Number(o.night_gap)))} short last night`
  // "for the year so far" when the books go back to January; otherwise say
  // where the count starts, so August books aren't judged on January.
  const span = o.since.endsWith('-01-01') ? 'for the year so far' : `since ${sinceLabel(o.since)}`
  const year =
    o.year_gap === null
      ? ''
      : Number(o.year_gap) >= 0
        ? `; ${money(o.year_gap)} ahead ${span}`
        : `; ${money(String(-Number(o.year_gap)))} behind ${span}`
  const heading =
    o.projected_year === null
      ? ''
      : `. Heading for ${money(o.projected_year)} this year against ${money(h.targets.breakeven_annual)} needed` +
        (o.projection_basis === 'last_year'
          ? ` (shaped by last year’s ${money(o.last_year_total)}${o.last_year_source === 'owner' ? ', the figure you typed' : ', from your books'})`
          : ' (a plain run rate — type last year’s revenue for a seasonal projection)')
  const behind = o.year_gap !== null ? Number(o.year_gap) < 0 : o.night_gap !== null && Number(o.night_gap) < 0
  return {
    tone: behind ? 'warn' : 'ok',
    head: behind ? 'Behind breakeven' : 'Above breakeven',
    detail: `Needs ${money(o.breakeven_per_day)} a day: ${night}${year}${heading}.`,
  }
}

function TargetsForm({ hotel, onDone }: { hotel: PortfolioHotel; onDone: () => void }) {
  const queryClient = useQueryClient()
  const [breakeven, setBreakeven] = useState(hotel.targets.breakeven_annual ?? '')
  const [lastYear, setLastYear] = useState(hotel.targets.last_year_revenue ?? '')
  const save = useMutation({
    mutationFn: () =>
      putTargets(hotel.property_id, {
        breakeven_annual: breakeven.trim() === '' ? null : breakeven.replace(/[$,\s]/g, ''),
        last_year_revenue: lastYear.trim() === '' ? null : lastYear.replace(/[$,\s]/g, ''),
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['portfolio'] })
      onDone()
    },
  })
  const perDay = breakeven.trim() === '' ? null : Number(breakeven.replace(/[$,\s]/g, '')) / 365
  return (
    <form
      className="mt-2 flex flex-col gap-2 rounded-lg border border-line bg-surface-sunken p-3"
      onSubmit={(e: FormEvent) => {
        e.preventDefault()
        save.mutate()
      }}
    >
      <label className="flex flex-col gap-1 text-sm">
        <span className="text-xs font-medium text-ink-muted">
          Annual breakeven for {hotel.name} — the revenue it needs in a year to cover its costs
        </span>
        <input
          aria-label={`Annual breakeven for ${hotel.name}`}
          className={controlClass}
          inputMode="decimal"
          value={breakeven}
          onChange={(e) => setBreakeven(e.target.value)}
          placeholder="540000"
        />
        {perDay !== null && Number.isFinite(perDay) && (
          <span className="text-xs text-ink-muted">That is {money(String(perDay))} a day.</span>
        )}
      </label>
      <label className="flex flex-col gap-1 text-sm">
        <span className="text-xs font-medium text-ink-muted">
          Last year’s total revenue (optional — shapes the projection by your seasons until the books have a full year)
        </span>
        <input
          aria-label={`Last year’s revenue for ${hotel.name}`}
          className={controlClass}
          inputMode="decimal"
          value={lastYear}
          onChange={(e) => setLastYear(e.target.value)}
          placeholder="580000"
        />
      </label>
      {save.isError && (
        <p role="alert" className="text-sm text-danger-red">{errorMessage(save.error)}</p>
      )}
      <div className="flex gap-2">
        <button type="submit" className={primaryButtonClass} disabled={save.isPending}>
          {save.isPending ? 'Saving…' : 'Save'}
        </button>
        <button type="button" className={buttonClass} onClick={onDone} disabled={save.isPending}>
          Cancel
        </button>
      </div>
    </form>
  )
}

function Bar({ hotel }: { hotel: PortfolioHotel }) {
  const o = hotel.outlook
  if (o === null || o.year_revenue === null) return null
  const expected = Number(o.expected_year_to_date)
  const actual = Number(o.year_revenue)
  const max = Math.max(expected, actual, 1)
  const behind = actual < expected
  return (
    <div className="relative mt-2 h-2.5 w-full rounded-full bg-surface-sunken" aria-hidden="true">
      <div
        className={`h-2.5 rounded-full ${behind ? 'bg-warn-amber' : 'bg-ok-green'}`}
        style={{ width: `${Math.max(2, (actual / max) * 100)}%` }}
      />
      <div
        className="absolute top-[-3px] h-4 w-0.5 bg-ink"
        style={{ left: `${(expected / max) * 100}%` }}
        title="Where the year should be by today"
      />
    </div>
  )
}

export default function ProfitPictureCard({
  hotels, summary, canEdit,
}: { hotels: PortfolioHotel[]; summary: BreakevenSummary; canEdit: boolean }) {
  const [editing, setEditing] = useState<string | null>(null)
  // Worst first: behind, then above, then not set — the eye goes to the top.
  const rank = (h: PortfolioHotel) => {
    const v = verdict(h)
    return v.tone === 'warn' ? 0 : v.tone === 'ok' ? 1 : 2
  }
  const ordered = [...hotels].sort((a, b) => rank(a) - rank(b) || a.name.localeCompare(b.name))
  const line =
    summary.above + summary.behind === 0
      ? 'Type each hotel’s annual breakeven and this card says which are making money.'
      : `${hotels.length} hotel${hotels.length === 1 ? '' : 's'} · ${summary.above} above breakeven, ${summary.behind} behind` +
        (summary.unset > 0 ? `, ${summary.unset} not set` : '') +
        (summary.year_gap !== null
          ? ` · ${money(String(Math.abs(Number(summary.year_gap))))} ${Number(summary.year_gap) >= 0 ? 'ahead' : 'behind'} for the year so far`
          : '')

  return (
    <Card role="region" aria-label="Profit picture">
      <h2 className={sectionHeadClass}>Profit picture</h2>
      <p className="mt-1 text-sm text-ink">{line}</p>
      <ul className="mt-2 divide-y divide-line">
        {ordered.map((h) => {
          const v = verdict(h)
          return (
            <li key={h.property_id} className="py-3">
              <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-1">
                <div className="min-w-0 flex-1">
                  <p className="flex flex-wrap items-center gap-2 text-sm font-medium text-ink">
                    {h.name}
                    <Badge tone={v.tone}>{v.head}</Badge>
                  </p>
                  <p className="text-xs text-ink-muted">{v.detail}</p>
                  <Bar hotel={h} />
                </div>
                {canEdit && editing !== h.property_id && (
                  <button
                    type="button"
                    className={buttonClass}
                    aria-label={`Set breakeven for ${h.name}`}
                    onClick={() => setEditing(h.property_id)}
                  >
                    {h.targets.breakeven_annual === null ? 'Set breakeven' : 'Change'}
                  </button>
                )}
              </div>
              {editing === h.property_id && (
                <TargetsForm hotel={h} onDone={() => setEditing(null)} />
              )}
            </li>
          )
        })}
      </ul>
    </Card>
  )
}

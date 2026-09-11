// Desktop edition home: every hotel at a glance (src/usali/desktop/
// portfolio_api.py). One day — by default the last one any hotel has
// reports for — with totals across hotels, a row per hotel that opens its
// own dashboard, and, when Payroll & People is on, the staff picture.
// Every figure is the statement's own: the server computes them with the
// same function the Profit and loss page uses.
import { useQuery } from '@tanstack/react-query'
import { Link, useNavigate } from '@tanstack/react-router'
import { useState, type ReactNode } from 'react'

import { getMe } from '../api/client'
import { getPortfolio, type PortfolioHotel } from '../api/desktop'
import {
  Badge,
  Card,
  PageHeader,
  cellClass,
  controlClass,
  headCellClass,
  sectionHeadClass,
  tableClass,
} from '../components/ui'
import { errorMessage } from '../lib/errors'
import { useGlobalProperty } from '../lib/propertyContext'
import { hasRole } from '../lib/roles'

const buttonClass =
  'rounded-lg border border-line px-3 py-1.5 text-sm font-medium text-ink hover:bg-surface-sunken'

function dollars(value: string | null, digits = 0): string {
  if (value === null) return '—'
  return Number(value).toLocaleString(undefined, {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })
}

function percent(value: string | null): string {
  return value === null ? '—' : `${Number(value).toFixed(1)}%`
}

function longDate(iso: string): string {
  const d = new Date(`${iso}T00:00:00`)
  return Number.isNaN(d.getTime())
    ? iso
    : d.toLocaleDateString(undefined, { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' })
}

function Metric({ label, value, detail }: { label: string; value: string; detail?: ReactNode }) {
  return (
    <div className="rounded-card bg-surface-sunken p-4">
      <p className="text-xs font-medium text-ink-muted">{label}</p>
      <p className="mt-1 text-2xl font-semibold tabular-nums text-ink">{value}</p>
      {detail !== undefined && <p className="mt-0.5 text-xs text-ink-muted">{detail}</p>}
    </div>
  )
}

function ReportsBadge({ hotel }: { hotel: PortfolioHotel }) {
  if (hotel.status === 'in') return <Badge tone="ok">In</Badge>
  if (hotel.status === 'error') return <Badge tone="danger">Needs a look</Badge>
  return <Badge tone="warn">Missing</Badge>
}

export default function OverviewPage() {
  const [date, setDate] = useState<string | undefined>(undefined)
  const portfolio = useQuery({
    queryKey: ['portfolio', date ?? 'latest'],
    queryFn: () => getPortfolio(date),
    retry: false,
  })
  const me = useQuery({ queryKey: ['me'], queryFn: getMe })
  const { setProperty } = useGlobalProperty()
  const navigate = useNavigate()

  /** The hotel's own dashboard, on the day this page is showing. */
  function openHotel(propertyId: string) {
    setProperty(propertyId)
    const day = date ?? portfolio.data?.business_date ?? undefined
    void navigate({ to: '/dashboard', search: { date: day } })
  }

  if (portfolio.isPending) {
    return (
      <Card>
        <p className="text-sm text-ink-muted">Loading …</p>
      </Card>
    )
  }
  if (portfolio.isError) {
    return (
      <Card>
        <p role="alert" className="text-sm text-danger-red">
          Couldn’t load your hotels: {errorMessage(portfolio.error)}
        </p>
      </Card>
    )
  }
  const data = portfolio.data
  if (data === null) {
    return (
      <Card>
        <p className="text-sm text-ink-muted">
          The all-hotels overview is part of the desktop edition. Open the{' '}
          <Link to="/dashboard" className="underline">
            hotel dashboard
          </Link>{' '}
          instead.
        </p>
      </Card>
    )
  }

  const { totals, hotels } = data
  const canAdd = hasRole(me.data, 'org_admin')
  const day = date ?? data.business_date ?? undefined

  return (
    <div className="flex flex-col gap-5">
      <PageHeader
        title="All hotels"
        subtitle={
          data.business_date === null
            ? 'No reports read yet.'
            : `${date === undefined ? 'Last closed day' : 'Day'} · ${longDate(data.business_date)}`
        }
        actions={
          <>
            <label className="flex items-center gap-2 text-sm text-ink-muted">
              <span className="sr-only">Show a different day</span>
              <input
                type="date"
                aria-label="Show a different day"
                className={controlClass}
                value={day ?? ''}
                onChange={(e) => setDate(e.target.value || undefined)}
              />
            </label>
            {date !== undefined && (
              <button type="button" className={buttonClass} onClick={() => setDate(undefined)}>
                Latest
              </button>
            )}
            {canAdd && (
              <a href="/welcome?add=hotel" className={buttonClass}>
                Add a hotel
              </a>
            )}
          </>
        }
      />

      <section aria-label="Totals" className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Metric
          label="Revenue"
          value={dollars(totals.revenue)}
          detail={`${totals.hotels_in} of ${totals.hotels} ${totals.hotels === 1 ? 'hotel' : 'hotels'} reported`}
        />
        <Metric label="Occupancy" value={percent(totals.occupancy_pct)} detail="Rooms sold ÷ rooms" />
        <Metric
          label="Average rate"
          value={dollars(totals.adr, 2)}
          detail={`Revenue per available room ${dollars(totals.revpar, 2)}`}
        />
        <Metric label="Month so far" value={dollars(totals.month_revenue)} detail="Total revenue" />
      </section>

      <Card role="region" aria-label="Hotels">
        <h2 className={sectionHeadClass}>Hotels</h2>
        {hotels.length === 0 ? (
          <p className="mt-2 text-sm text-ink-muted">
            No hotels yet.{canAdd && ' Use “Add a hotel” to set one up.'}
          </p>
        ) : (
          <div className="mt-2 overflow-x-auto">
            <table className={tableClass}>
              <thead>
                <tr>
                  <th className={headCellClass}>Hotel</th>
                  <th className={headCellClass}>Reports</th>
                  <th className={`${headCellClass} text-right`}>Revenue</th>
                  <th className={`${headCellClass} text-right`}>Occupancy</th>
                  <th className={`${headCellClass} text-right`}>Average rate</th>
                  <th className={`${headCellClass} text-right`}>RevPAR</th>
                  <th className={`${headCellClass} text-right`}>Month so far</th>
                </tr>
              </thead>
              <tbody>
                {hotels.map((h) => (
                  <tr key={h.property_id} className="border-t border-line">
                    <td className={cellClass}>
                      {h.status === 'in' ? (
                        <button
                          type="button"
                          className="text-left font-medium text-accent hover:underline"
                          aria-label={`Open ${h.name}`}
                          onClick={() => openHotel(h.property_id)}
                        >
                          {h.name}
                        </button>
                      ) : (
                        <span className="font-medium text-ink">{h.name}</span>
                      )}
                      <span className="block text-xs text-ink-muted">
                        {h.note ?? h.property_id}
                      </span>
                    </td>
                    <td className={cellClass}>
                      <ReportsBadge hotel={h} />
                    </td>
                    <td className={`${cellClass} text-right tabular-nums`}>{dollars(h.revenue)}</td>
                    <td className={`${cellClass} text-right tabular-nums`}>{percent(h.occupancy_pct)}</td>
                    <td className={`${cellClass} text-right tabular-nums`}>{dollars(h.adr, 2)}</td>
                    <td className={`${cellClass} text-right tabular-nums`}>{dollars(h.revpar, 2)}</td>
                    <td className={`${cellClass} text-right tabular-nums`}>
                      {dollars(h.month_revenue)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {data.staff_shown && totals.staff !== null && (
        <Card role="region" aria-label="Staff">
          <h2 className={sectionHeadClass}>Staff</h2>
          <div className="mt-3 grid grid-cols-2 gap-3 lg:grid-cols-4">
            <Metric label="On the clock now" value={String(totals.staff.on_clock)} />
            <Metric label="Staff" value={String(totals.staff.staff)} detail="Active, across your hotels" />
            <Metric
              label="Timecards to approve"
              value={String(totals.staff.timecards_to_approve)}
              detail={
                totals.staff.timecards_to_approve > 0 ? (
                  <Link to="/timecards" className="underline">
                    Review timecards
                  </Link>
                ) : (
                  'For pay periods that have ended'
                )
              }
            />
            <Metric
              label="Labour vs revenue"
              value={percent(totals.month_labour_pct)}
              detail={`Estimated ${dollars(totals.month_labour_cost)} this month`}
            />
          </div>
          <div className="mt-4 overflow-x-auto">
            <table className={tableClass}>
              <thead>
                <tr>
                  <th className={headCellClass}>Hotel</th>
                  <th className={`${headCellClass} text-right`}>On the clock</th>
                  <th className={`${headCellClass} text-right`}>Staff</th>
                  <th className={`${headCellClass} text-right`}>Timecards to approve</th>
                  <th className={`${headCellClass} text-right`}>Labour this month</th>
                </tr>
              </thead>
              <tbody>
                {hotels.map((h) => (
                  <tr key={h.property_id} className="border-t border-line">
                    <td className={cellClass}>{h.name}</td>
                    <td className={`${cellClass} text-right tabular-nums`}>{h.staff?.on_clock ?? '—'}</td>
                    <td className={`${cellClass} text-right tabular-nums`}>{h.staff?.staff ?? '—'}</td>
                    <td className={`${cellClass} text-right tabular-nums`}>
                      {h.staff?.timecards_to_approve ?? '—'}
                    </td>
                    <td className={`${cellClass} text-right tabular-nums`}>
                      {dollars(h.month_labour_cost)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="mt-3 text-xs text-ink-muted">
            Labour is estimated from approved timecards. Someone clocked in is counted at the
            hotel whose time clock they used.
          </p>
        </Card>
      )}
    </div>
  )
}

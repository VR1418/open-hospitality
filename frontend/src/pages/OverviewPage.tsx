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
import {
  getBackupStatus,
  getPortfolio,
  type BackupStatus,
  type Finding,
  type PortfolioHotel,
  type TrendPoint,
} from '../api/desktop'
import ConnectionsCard from '../components/ConnectionsCard'
import FoldersCard from '../components/FoldersCard'
import MorningCard from '../components/MorningCard'
import { barRampCss } from '../lib/chartBars'
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

function shortDate(iso: string): string {
  const d = new Date(`${iso}T00:00:00`)
  return Number.isNaN(d.getTime())
    ? iso
    : d.toLocaleDateString(undefined, { day: 'numeric', month: 'short' })
}

/** Revenue per day across the hotels. Bars, not a line: each day is a
 * separate night's takings, and a missing day is a gap, never a slope. */
function TrendBars({ points }: { points: TrendPoint[] }) {
  const values = points.map((p) => (p.revenue === null ? null : Number(p.revenue)))
  const max = Math.max(1, ...values.map((v) => v ?? 0))
  const best = values.reduce<number>((a, v) => (v !== null && v > a ? v : a), 0)
  return (
    <div>
      <div className="flex h-32 items-end gap-1.5" role="img"
           aria-label={`Revenue per day, ${points.length} days to ${points.at(-1)?.business_date ?? ''}`}>
        {points.map((p, i) => {
          const value = values[i] ?? null
          return (
            <div key={p.business_date} className="flex min-w-0 flex-1 flex-col justify-end">
              <div
                className="rounded-t"
                style={{
                  height: value === null ? 2 : `${Math.max(2, (value / max) * 100)}%`,
                  background: value === null ? 'var(--color-line)' : barRampCss('var(--color-chart-1)'),
                }}
                title={value === null ? `${p.business_date}: no reports` : `${p.business_date}: ${dollars(String(value))}`}
              />
            </div>
          )
        })}
      </div>
      <div className="mt-1 flex justify-between text-[11px] text-ink-faint">
        <span>{points[0] !== undefined ? shortDate(points[0].business_date) : ''}</span>
        <span>Best day {dollars(String(best))}</span>
        <span>{points.at(-1) !== undefined ? shortDate(points.at(-1)!.business_date) : ''}</span>
      </div>
    </div>
  )
}

function FindingRow({ finding }: { finding: Finding }) {
  const tone: Record<Finding['kind'], 'warn' | 'danger' | 'neutral'> = {
    no_reports: 'warn',
    missing_report: 'warn',
    check_failed: 'danger',
    not_in_books: 'danger',
    codes_to_confirm: 'danger',
  }
  return (
    <li className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5 border-t border-line py-2 text-sm">
      <Badge tone={tone[finding.kind]}>{finding.label}</Badge>
      <span className="font-medium text-ink">{finding.hotel}</span>
      <span className="text-ink-muted">{finding.detail}</span>
      {finding.delta !== null && (
        <span className="tabular-nums text-danger-red">Out by {dollars(finding.delta, 2)}</span>
      )}
    </li>
  )
}

/** PRD's risks table: "Backup is in the setup flow, not settings. Nag until
 * configured." The wizard asks; this is what keeps asking. */
function backupNag(status: BackupStatus | null | undefined): string | null {
  if (status === null || status === undefined) return null
  if (status.folder === null) {
    return 'Your books aren’t being backed up. If this computer goes, so do they.'
  }
  if (status.last_backup_at === null) return 'No backup has been taken yet.'
  const days = Math.floor(
    (Date.now() - new Date(status.last_backup_at).getTime()) / (24 * 60 * 60 * 1000),
  )
  return days >= 2 ? `The last backup was ${days} days ago.` : null
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
  // Owner only: the endpoint is theirs, and so is the decision.
  const backup = useQuery({
    queryKey: ['backup'],
    queryFn: getBackupStatus,
    enabled: hasRole(me.data, 'org_admin'),
    retry: false,
  })
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
  const nag = backupNag(backup.data)
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

      {nag !== null && (
        <Card role="region" aria-label="Backups">
          <p className="text-sm text-ink">
            <Badge tone="warn">Backups</Badge> {nag}{' '}
            <Link to="/backups" className="underline">
              Set up backups
            </Link>
          </p>
        </Card>
      )}

      {canAdd && <MorningCard />}
      {canAdd && <ConnectionsCard />}

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

      <FoldersCard only={['saved', 'read', 'unreadable']} />

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

      <div className="grid gap-5 lg:grid-cols-[3fr_2fr]">
        <Card role="region" aria-label="Revenue trend">
          <h2 className={sectionHeadClass}>Revenue, last 14 days</h2>
          <p className="mb-3 mt-0.5 text-xs text-ink-muted">
            All hotels together, from the reports read.
          </p>
          {data.trend.length === 0 ? (
            <p className="text-sm text-ink-muted">No reports read yet.</p>
          ) : (
            <TrendBars points={data.trend} />
          )}
        </Card>

        <Card role="region" aria-label="Last night’s audit">
          <h2 className={sectionHeadClass}>Last night’s audit</h2>
          {data.findings.length === 0 ? (
            <p className="mt-2 text-sm text-ink">
              Nothing to look at — every hotel’s reports are in and their balances tie.
            </p>
          ) : (
            <>
              <p className="mb-1 mt-0.5 text-xs text-ink-muted">
                {data.findings.length} to look at
              </p>
              <ul className="flex flex-col">
                {data.findings.map((f) => (
                  <FindingRow key={`${f.property_id}-${f.kind}-${f.label}`} finding={f} />
                ))}
              </ul>
              <Link to="/night-audit" className="mt-3 inline-block text-sm text-accent underline">
                Open Close the day
              </Link>
            </>
          )}
        </Card>
      </div>


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

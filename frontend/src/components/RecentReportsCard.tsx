// Desktop edition: what just happened on the Add reports page — the last few
// files read into the books, and the ones set aside with why
// (src/usali/desktop/morning_api.py, `recent`). Before this the page showed
// only how many files each folder held, so an owner who dropped a report in
// saw nothing change. Renders nothing outside the desktop edition.
import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'

import { getMorning } from '../api/desktop'
import { Badge, Card, sectionHeadClass } from './ui'

function when(iso: string): string {
  const d = new Date(iso)
  return Number.isNaN(d.getTime())
    ? iso
    : d.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
}

export default function RecentReportsCard() {
  // Polled while the page is open: the folder watcher reads a dropped file
  // within seconds, and the owner is looking at this card to see it land.
  const morning = useQuery({
    queryKey: ['morning'],
    queryFn: getMorning,
    retry: false,
    refetchInterval: 5_000,
  })
  if (morning.data === null || morning.data === undefined) return null
  const codes = morning.data.items.find((i) => i.id === 'codes')

  return (
    <Card role="region" aria-label="Just read">
      <h2 className={sectionHeadClass}>Just read</h2>
      {morning.data.recent.length === 0 ? (
        <p className="mt-2 text-sm text-ink-muted">
          Nothing yet. Drop a night audit PDF above, or into the Drop reports here folder, and
          it appears here within a few seconds.
        </p>
      ) : (
        <ul className="mt-2 divide-y divide-line">
          {morning.data.recent.map((r) => (
            <li key={r.file} className="flex flex-wrap items-start justify-between gap-x-4 gap-y-1 py-2">
              <div className="min-w-0 flex-1">
                <p className="flex flex-wrap items-center gap-2 text-sm text-ink">
                  {r.state === 'read' ? (
                    <Badge tone="ok">Read</Badge>
                  ) : (
                    <Badge tone="danger">Couldn’t read</Badge>
                  )}
                  <span className="font-medium">
                    {r.property_id !== null && r.business_date !== null
                      ? `${r.property_id} · ${r.business_date}`
                      : r.file}
                  </span>
                </p>
                <p className="truncate text-xs text-ink-muted" title={r.file}>
                  {r.reason ?? r.file} · {when(r.when)}
                </p>
              </div>
            </li>
          ))}
        </ul>
      )}
      {codes !== undefined && codes.state !== 'done' && (
        <p className="mt-3 text-sm text-ink">
          {codes.text}{' '}
          <Link to="/codes" className="text-accent underline">
            Confirm them
          </Link>
        </p>
      )}
    </Card>
  )
}

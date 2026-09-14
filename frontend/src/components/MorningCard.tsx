// Desktop edition: the owner's morning in four lines
// (src/usali/desktop/morning_api.py) — last night's reports in? anything to
// confirm? bank still checked? books backed up? Each line is a tick or a
// thing to do, with where to go. Renders nothing outside the desktop edition.
import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'

import { getMorning, type MorningItem } from '../api/desktop'
import { Card, sectionHeadClass } from './ui'
import { errorMessage } from '../lib/errors'

const MARK: Record<MorningItem['state'], { glyph: string; className: string; label: string }> = {
  done: { glyph: '✓', className: 'text-ok-green', label: 'Done' },
  todo: { glyph: '○', className: 'text-ink-muted', label: 'To do' },
  attention: { glyph: '!', className: 'text-danger-red', label: 'Needs attention' },
}

const NAME: Record<string, string> = {
  reports: 'Last night’s reports',
  codes: 'Codes to confirm',
  bank: 'Bank check',
  backup: 'Backup',
}

export default function MorningCard() {
  const morning = useQuery({ queryKey: ['morning'], queryFn: getMorning, retry: false })
  if (morning.data === null) return null

  return (
    <Card role="region" aria-label="This morning">
      <h2 className={sectionHeadClass}>This morning</h2>
      {morning.data === undefined ? (
        <p className="mt-2 text-sm text-ink-muted">
          {morning.isError ? errorMessage(morning.error) : 'Looking…'}
        </p>
      ) : (
        <ul className="mt-2 divide-y divide-line">
          {morning.data.items.map((item) => (
            <li key={item.id} className="flex items-start gap-3 py-2">
              <span
                aria-label={MARK[item.state].label}
                className={`w-4 shrink-0 text-center text-base font-semibold leading-5 ${MARK[item.state].className}`}
              >
                {MARK[item.state].glyph}
              </span>
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium text-ink">{NAME[item.id] ?? item.id}</p>
                <p className="text-xs text-ink-muted">{item.text}</p>
              </div>
              <Link to={item.page} className="shrink-0 text-sm text-accent underline">
                {item.state === 'done' ? 'Open' : 'Go'}
              </Link>
            </li>
          ))}
        </ul>
      )}
    </Card>
  )
}

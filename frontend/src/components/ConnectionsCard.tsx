// Desktop edition: what's connected and what isn't, in one card
// (src/usali/desktop/connections_api.py). Each row is a state, a line of
// detail in the owner's words, and where to go. Renders nothing outside the
// desktop edition.
import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'

import { getConnections, type Connection } from '../api/desktop'
import { Badge, Card, sectionHeadClass } from './ui'
import { errorMessage } from '../lib/errors'

const LABEL: Record<Connection['state'], { text: string; tone: 'ok' | 'warn' | 'neutral' }> = {
  connected: { text: 'Connected', tone: 'ok' },
  attention: { text: 'Needs attention', tone: 'warn' },
  not_set_up: { text: 'Not set up', tone: 'neutral' },
}

export default function ConnectionsCard() {
  const connections = useQuery({ queryKey: ['connections'], queryFn: getConnections, retry: false })
  if (connections.data === null) return null

  return (
    <Card role="region" aria-label="What’s connected">
      <h2 className={sectionHeadClass}>What’s connected</h2>
      {connections.data === undefined ? (
        <p className="mt-2 text-sm text-ink-muted">
          {connections.isError ? errorMessage(connections.error) : 'Loading…'}
        </p>
      ) : (
        <ul className="mt-2 divide-y divide-line">
          {connections.data.connections.map((c) => (
            <li key={c.id} className="flex flex-wrap items-start justify-between gap-x-4 gap-y-1 py-2.5">
              <div className="min-w-0 flex-1">
                <p className="flex flex-wrap items-center gap-2 text-sm font-medium text-ink">
                  {c.name}
                  <Badge tone={LABEL[c.state].tone}>{LABEL[c.state].text}</Badge>
                </p>
                <p className="text-xs text-ink-muted">{c.detail}</p>
              </div>
              <Link to={c.page} className="shrink-0 text-sm text-accent underline">
                {c.state === 'connected' ? 'Open' : 'Set up'}
              </Link>
            </li>
          ))}
        </ul>
      )}
    </Card>
  )
}

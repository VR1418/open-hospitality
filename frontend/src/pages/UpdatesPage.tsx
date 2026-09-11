// Desktop edition: is there a newer version? (PRD I-5, adapted — see
// src/usali/desktop/updates.py.) The app tells the owner and links to the
// download; it never installs anything by itself, and it sends nothing about
// this install when it asks.
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { checkForUpdate, getUpdate } from '../api/desktop'
import { Badge, Card, PageHeader, sectionHeadClass } from '../components/ui'
import { errorMessage } from '../lib/errors'

const buttonClass =
  'rounded-lg border border-line px-3 py-1.5 text-sm font-medium text-ink hover:bg-surface-sunken disabled:cursor-not-allowed disabled:opacity-50'

function when(iso: string | null): string {
  if (iso === null) return 'not yet'
  const d = new Date(iso)
  return Number.isNaN(d.getTime())
    ? iso
    : d.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
}

export default function UpdatesPage() {
  const queryClient = useQueryClient()
  const update = useQuery({ queryKey: ['update'], queryFn: getUpdate, retry: false })
  const check = useMutation({
    mutationFn: checkForUpdate,
    onSuccess: (fresh) => queryClient.setQueryData(['update'], fresh),
  })

  if (update.isPending) {
    return (
      <Card>
        <p className="text-sm text-ink-muted">Loading …</p>
      </Card>
    )
  }
  if (update.isError) {
    return (
      <Card>
        <p role="alert" className="text-sm text-danger-red">
          {errorMessage(update.error)}
        </p>
      </Card>
    )
  }
  const data = update.data
  if (data === null) {
    return (
      <Card>
        <p className="text-sm text-ink-muted">Updates are part of the desktop edition.</p>
      </Card>
    )
  }

  return (
    <div className="flex flex-col gap-5">
      <PageHeader
        title="Updates"
        subtitle="Open Hospitality tells you when a new version is out. It never installs one by itself."
      />

      <Card role="region" aria-label="This copy">
        <h2 className={sectionHeadClass}>This copy</h2>
        <p className="mt-1 text-2xl font-semibold tabular-nums text-ink">Version {data.current}</p>
      </Card>

      <Card role="region" aria-label="Newer version">
        <h2 className={sectionHeadClass}>Newer version</h2>
        {!data.configured ? (
          <p className="mt-2 text-sm text-ink">
            Update checks aren’t set up yet. Once Open Hospitality has a published home, this
            page will tell you when a new version is out.
          </p>
        ) : data.update_available ? (
          <>
            <p className="mt-2 text-sm text-ink">
              <Badge tone="info">Version {data.latest}</Badge> is available.
            </p>
            {data.notes !== null && <p className="mt-2 text-sm text-ink-muted">{data.notes}</p>}
            {data.url !== null && (
              <p className="mt-3">
                <a className="text-sm font-medium text-accent underline" href={data.url}>
                  Download version {data.latest}
                </a>
              </p>
            )}
            <p className="mt-3 text-xs text-ink-muted">
              Your books stay where they are. Install it when it suits you.
            </p>
          </>
        ) : (
          <p className="mt-2 text-sm text-ink">You’re on the latest version.</p>
        )}
        {data.error !== null && (
          <p role="status" className="mt-2 text-sm text-ink-muted">
            Couldn’t check just now: {data.error}
          </p>
        )}
        <div className="mt-4 flex flex-wrap items-center gap-3">
          <button
            type="button"
            className={buttonClass}
            disabled={!data.configured || check.isPending}
            onClick={() => check.mutate()}
          >
            {check.isPending ? 'Checking…' : 'Check now'}
          </button>
          <span className="text-sm text-ink-muted">Last checked: {when(data.checked_at)}</span>
        </div>
        {check.isError && (
          <p role="alert" className="mt-2 text-sm text-danger-red">
            {errorMessage(check.error)}
          </p>
        )}
      </Card>

      <Card role="region" aria-label="What is sent">
        <h2 className={sectionHeadClass}>What is sent</h2>
        <p className="mt-2 text-sm text-ink">
          Nothing about you or your hotels. The check reads one published file and compares the
          version in it with this one.
        </p>
      </Card>
    </div>
  )
}

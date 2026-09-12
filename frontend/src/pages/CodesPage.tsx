// Desktop edition: the transaction codes a hotel's reports use, and what
// each one means HERE (PRD M4 phase 1, src/usali/desktop/codes_api.py).
//
// The page exists because of what happens when nobody has said. A code the
// shipped dictionary has never heard of does not stop a report — its money is
// banked as a mapping exception, no fact is made, and the journal balances by
// sweeping the difference into a clearing account that the parity check
// excludes. The books tie; the profit and loss is short. This is the only
// place that figure is ever shown.
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Fragment, useState } from 'react'

import {
  confirmCode,
  getCodeLines,
  getCodes,
  type CodeItem,
  type CodeLine,
  type ConfirmResult,
} from '../api/desktop'
import {
  Badge,
  Card,
  PageHeader,
  cellClass,
  controlClass,
  headCellClass,
  tableClass,
} from '../components/ui'
import { errorMessage } from '../lib/errors'
import { fmtMoney } from '../lib/format'
import { useGlobalProperty } from '../lib/propertyContext'

const buttonClass =
  'rounded-lg border border-line px-3 py-1.5 text-sm font-medium text-ink hover:bg-surface-sunken disabled:cursor-not-allowed disabled:opacity-50'
const primaryButtonClass =
  'rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-accent-contrast hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50'

function lineLabel(line: CodeLine): string {
  return `${line.major} › ${line.sub} › ${line.line_item}`
}

function sameLine(a: CodeLine, b: CodeLine): boolean {
  return (
    a.schedule_id === b.schedule_id &&
    a.major === b.major &&
    a.sub === b.sub &&
    a.line_item === b.line_item &&
    a.gl_account_code === b.gl_account_code
  )
}

function StatusBadge({ status }: { status: CodeItem['status'] }) {
  if (status === 'unknown') return <Badge tone="danger">Not in your books</Badge>
  if (status === 'unconfirmed') return <Badge tone="warn">A guess</Badge>
  return <Badge tone="ok">Confirmed</Badge>
}

/** The one-line reason this code is on the list, in the owner's words. */
function why(item: CodeItem): string {
  if (item.status === 'unknown') {
    return 'Nothing here knows this code, so its money is not on your profit and loss.'
  }
  if (item.status === 'unconfirmed') {
    return 'This is where we guessed it goes. Nobody at your hotel has agreed yet.'
  }
  return `Confirmed by ${item.decided_by ?? 'someone here'}.`
}

function Editor({
  item,
  lines,
  busy,
  onCancel,
  onConfirm,
}: {
  item: CodeItem
  lines: CodeLine[]
  busy: boolean
  onCancel: () => void
  onConfirm: (line: CodeLine, note: string) => void
}) {
  const startsAt = item.current === null ? -1 : lines.findIndex((l) => sameLine(l, item.current!))
  const [chosen, setChosen] = useState<number>(startsAt)
  const [note, setNote] = useState('')
  const selectId = `line-for-${item.code}`
  const noteId = `note-for-${item.code}`

  return (
    <tr className="border-t border-line bg-surface-sunken">
      <td className={cellClass} colSpan={6}>
        <div className="flex flex-col gap-3 py-2">
          <label className="flex flex-col gap-1 text-sm" htmlFor={selectId}>
            <span className="text-xs font-medium text-ink-muted">
              Where should {item.code} go?
            </span>
            <select
              id={selectId}
              className={controlClass}
              value={chosen}
              onChange={(e) => setChosen(Number(e.target.value))}
            >
              <option value={-1} disabled>
                Choose a line
              </option>
              {lines.map((line, i) => (
                <option key={lineLabel(line)} value={i}>
                  {lineLabel(line)}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1 text-sm" htmlFor={noteId}>
            <span className="text-xs font-medium text-ink-muted">
              Why (optional — worth writing for whoever looks next)
            </span>
            <input
              id={noteId}
              className={controlClass}
              value={note}
              onChange={(e) => setNote(e.target.value)}
            />
          </label>
          <p className="text-xs text-ink-muted">
            Every day this code appears on will be worked out again and your books reposted.
            Days in a month you have already closed are left alone.
          </p>
          <div className="flex gap-2">
            <button
              type="button"
              className={primaryButtonClass}
              disabled={busy || chosen < 0}
              onClick={() => onConfirm(lines[chosen], note)}
            >
              {busy ? 'Working…' : 'Confirm'}
            </button>
            <button type="button" className={buttonClass} onClick={onCancel} disabled={busy}>
              Cancel
            </button>
          </div>
        </div>
      </td>
    </tr>
  )
}

export default function CodesPage() {
  const queryClient = useQueryClient()
  const { property, selected } = useGlobalProperty()
  const [editing, setEditing] = useState<string | null>(null)
  const [done, setDone] = useState<ConfirmResult | null>(null)

  const codes = useQuery({
    queryKey: ['codes', property],
    queryFn: () => getCodes(property!),
    enabled: property !== undefined,
    retry: false,
  })
  const lines = useQuery({ queryKey: ['code-lines'], queryFn: getCodeLines, retry: false })

  const confirm = useMutation({
    mutationFn: ({ item, line, note }: { item: CodeItem; line: CodeLine; note: string }) =>
      confirmCode(item.code, {
        property_id: property!,
        pms_source: item.pms_source,
        line,
        note: note.trim() === '' ? undefined : note.trim(),
      }),
    onSuccess: (result) => {
      setEditing(null)
      setDone(result)
      void queryClient.invalidateQueries({ queryKey: ['codes', property] })
    },
  })

  if (property === undefined) {
    return (
      <div className="flex flex-col gap-4">
        <PageHeader title="Codes to confirm" />
        <Card>
          <p className="text-sm text-ink-muted">Add a hotel first, then its reports.</p>
        </Card>
      </div>
    )
  }

  if (codes.data === null) {
    return (
      <div className="flex flex-col gap-4">
        <PageHeader title="Codes to confirm" />
        <Card>
          <p className="text-sm text-ink-muted">
            This page is part of the desktop edition.
          </p>
        </Card>
      </div>
    )
  }

  const state = codes.data
  if (state === undefined) {
    return (
      <div className="flex flex-col gap-4">
        <PageHeader title="Codes to confirm" />
        <Card>
          {codes.isError ? (
            <p className="text-sm text-danger-red">{errorMessage(codes.error)}</p>
          ) : (
            <p className="text-sm text-ink-muted">Reading your reports…</p>
          )}
        </Card>
      </div>
    )
  }
  const missing = Number(state.money_not_in_the_books)

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        title="Codes to confirm"
        subtitle={`What ${selected?.name ?? property} calls each charge, and where it goes`}
      />

      {missing !== 0 && (
        <Card>
          <section aria-label="Money not in your books" className="flex flex-col gap-1">
            <p className="text-2xl font-semibold tabular-nums text-danger-red">
              ${fmtMoney(state.money_not_in_the_books)}
            </p>
            <p className="text-sm text-ink">
              is on your reports but not on your profit and loss, because nothing here knows
              what those codes are. Your books still balance — the money is parked in a holding
              account, which is why no other check mentions it.
            </p>
          </section>
        </Card>
      )}

      {done !== null && (
        <Card>
          <section aria-label="What changed" className="flex flex-col gap-1">
            <p className="text-sm text-ink">
              {done.days_restated.length === 0
                ? `${done.code} is confirmed. It hasn’t appeared on a report yet.`
                : `${done.code} is confirmed, and ${done.days_restated.length} day${
                    done.days_restated.length === 1 ? '' : 's'
                  } worked out again.`}
            </p>
            {Object.keys(done.ledger_refused).length > 0 && (
              <p className="text-sm text-danger-red">
                Your books would not take {Object.keys(done.ledger_refused).length} of those
                days: {Object.values(done.ledger_refused)[0]}
              </p>
            )}
          </section>
        </Card>
      )}

      {confirm.isError && (
        <Card>
          <p className="text-sm text-danger-red" role="alert">
            {errorMessage(confirm.error)}
          </p>
        </Card>
      )}

      <Card>
        <section aria-label="Codes">
          {state.items.length === 0 ? (
            <p className="text-sm text-ink-muted">
              Every code on your reports is one we recognise. Nothing to do.
            </p>
          ) : (
            <table className={tableClass}>
              <thead>
                <tr>
                  <th className={headCellClass}>Code</th>
                  <th className={headCellClass}>On your report</th>
                  <th className={headCellClass}>Seen</th>
                  <th className={`${headCellClass} text-right`}>Amount</th>
                  <th className={headCellClass}>Goes to</th>
                  <th className={headCellClass}> </th>
                </tr>
              </thead>
              <tbody>
                {state.items.map((item) => (
                  <Fragment key={item.code}>
                    <tr className="border-t border-line">
                      <td className={`${cellClass} font-medium`}>{item.code}</td>
                      <td className={cellClass}>
                        <div>{item.description ?? '—'}</div>
                        <div className="text-xs text-ink-muted">{why(item)}</div>
                      </td>
                      <td className={cellClass}>
                        <div className="tabular-nums">{item.times_seen}×</div>
                        <div className="text-xs text-ink-muted">
                          {item.first_seen === item.last_seen
                            ? item.first_seen
                            : `${item.first_seen} to ${item.last_seen}`}
                        </div>
                      </td>
                      <td className={`${cellClass} text-right tabular-nums`}>
                        ${fmtMoney(item.amount)}
                      </td>
                      <td className={cellClass}>
                        <div>{item.current === null ? 'Nowhere' : lineLabel(item.current)}</div>
                        <StatusBadge status={item.status} />
                      </td>
                      <td className={cellClass}>
                        <button
                          type="button"
                          className={buttonClass}
                          onClick={() => {
                            setDone(null)
                            setEditing(editing === item.code ? null : item.code)
                          }}
                        >
                          {item.status === 'confirmed' ? `Change ${item.code}` : `Confirm ${item.code}`}
                        </button>
                      </td>
                    </tr>
                    {editing === item.code && lines.data !== undefined && (
                      <Editor
                        item={item}
                        lines={lines.data}
                        busy={confirm.isPending}
                        onCancel={() => setEditing(null)}
                        onConfirm={(line, note) => confirm.mutate({ item, line, note })}
                      />
                    )}
                  </Fragment>
                ))}
              </tbody>
            </table>
          )}
          {state.settled_count > 0 && (
            <p className="pt-3 text-xs text-ink-muted">
              {state.settled_count} other code{state.settled_count === 1 ? '' : 's'} on your
              reports {state.settled_count === 1 ? 'is' : 'are'} already settled.
            </p>
          )}
        </section>
      </Card>
    </div>
  )
}

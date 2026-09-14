// Desktop edition: check the books against the bank, and sort the card
// (src/usali/desktop/statements.py). The owner uploads a CSV statement; bank
// lines are matched to the night audits' settlements, card lines are sorted
// into expense categories that are remembered by merchant.
//
// Nothing on this page writes to the books. It is a check, and a sorting.
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type ChangeEvent } from 'react'

import {
  deleteStatement,
  getCardCategories,
  getStatement,
  getStatements,
  markStatementLine,
  uploadStatement,
  type StatementLine,
  type StatementSummary,
} from '../api/desktop'
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
import { fmtDollars } from '../lib/format'
import { useGlobalProperty } from '../lib/propertyContext'
import { propertyDisplayName } from '../lib/propertyName'

const buttonClass =
  'rounded-lg border border-line px-3 py-1.5 text-sm font-medium text-ink hover:bg-surface-sunken disabled:cursor-not-allowed disabled:opacity-50'
const primaryButtonClass =
  'rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-accent-contrast hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50'

const MATCH_LABELS: Record<string, { text: string; tone: 'ok' | 'warn' | 'neutral' | 'info' }> = {
  settlement: { text: 'Matches the night audits', tone: 'ok' },
  cash: { text: 'Cash from the desk', tone: 'ok' },
  payroll: { text: 'Payroll', tone: 'info' },
  ignored: { text: 'Not the hotel’s', tone: 'neutral' },
  unmatched: { text: 'Unmatched', tone: 'warn' },
}

function usDate(iso: string): string {
  const [y = '', m = '', d = ''] = iso.split('-')
  return `${Number(m)}/${Number(d)}/${y}`
}

export default function BankPage() {
  const qc = useQueryClient()
  const { property, selected } = useGlobalProperty()
  const [kind, setKind] = useState<'bank' | 'card'>('bank')
  const [label, setLabel] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [openId, setOpenId] = useState<number | null>(null)

  const statements = useQuery({
    queryKey: ['statements', property],
    queryFn: () => getStatements(property!),
    enabled: property !== undefined,
    retry: false,
  })
  const detail = useQuery({
    queryKey: ['statement', openId],
    queryFn: () => getStatement(openId!),
    enabled: openId !== null,
    retry: false,
  })
  const categories = useQuery({ queryKey: ['card-categories'], queryFn: getCardCategories })

  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ['statements'] })
    void qc.invalidateQueries({ queryKey: ['statement'] })
  }
  const upload = useMutation({
    mutationFn: () => uploadStatement({ property: property!, kind, account_label: label, file: file! }),
    onSuccess: (made) => {
      setFile(null)
      setOpenId(made.statement_id)
      refresh()
    },
  })
  const mark = useMutation({
    mutationFn: (args: { lineId: number; body: Parameters<typeof markStatementLine>[1] }) =>
      markStatementLine(args.lineId, args.body),
    onSettled: refresh,
  })
  const remove = useMutation({
    mutationFn: (id: number) => deleteStatement(id),
    onSuccess: () => setOpenId(null),
    onSettled: refresh,
  })

  const hotel = propertyDisplayName(selected) ?? property ?? 'your hotel'
  const open = detail.data ?? null

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        title="Check against your bank"
        subtitle={`For ${hotel}: does the money in the bank match what the night audits said?`}
      />

      <Card>
        <form
          className="flex flex-col gap-3"
          aria-label="Upload a statement"
          onSubmit={(e) => { e.preventDefault(); upload.mutate() }}
        >
          <h2 className={sectionHeadClass}>Add a statement</h2>
          <p className="text-sm text-ink-muted">
            Download the statement from your bank or card as a <strong>CSV</strong> (every bank
            offers one, usually under “Download” or “Export”), then choose it here.
          </p>
          <div className="flex flex-wrap items-end gap-3">
            <fieldset className="flex items-center gap-4 text-sm">
              <legend className="mb-1 text-xs font-medium text-ink-muted">What is it</legend>
              <label className="flex items-center gap-1.5">
                <input type="radio" name="kind" checked={kind === 'bank'} onChange={() => setKind('bank')} />
                Bank account
              </label>
              <label className="flex items-center gap-1.5">
                <input type="radio" name="kind" checked={kind === 'card'} onChange={() => setKind('card')} />
                Credit card (the hotel’s purchases)
              </label>
            </fieldset>
            <label className="flex flex-col gap-1 text-sm">
              <span className="text-xs font-medium text-ink-muted">Call it</span>
              <input
                className={controlClass}
                placeholder={kind === 'bank' ? 'Operating account' : 'Visa ending 4411'}
                aria-label="Account name"
                value={label}
                onChange={(e) => setLabel(e.target.value)}
              />
            </label>
            <label className="flex flex-col gap-1 text-sm">
              <span className="text-xs font-medium text-ink-muted">The statement (CSV)</span>
              <input
                type="file"
                accept=".csv,text/csv"
                aria-label="Statement file"
                className={controlClass}
                onChange={(e: ChangeEvent<HTMLInputElement>) => setFile(e.target.files?.[0] ?? null)}
              />
            </label>
            <button
              type="submit"
              className={primaryButtonClass}
              disabled={file === null || property === undefined || upload.isPending}
            >
              {upload.isPending ? 'Checking…' : kind === 'bank' ? 'Check it' : 'Sort it'}
            </button>
          </div>
          {upload.isError && (
            <p role="alert" className="text-sm text-danger-red">{errorMessage(upload.error)}</p>
          )}
        </form>
      </Card>

      <Card role="region" aria-label="Statements">
        <h2 className={sectionHeadClass}>Statements</h2>
        {statements.data === undefined ? (
          <p className="mt-2 text-sm text-ink-muted">
            {statements.isError ? errorMessage(statements.error) : 'Loading…'}
          </p>
        ) : statements.data.length === 0 ? (
          <p className="mt-2 text-sm text-ink-muted">None yet for {hotel}.</p>
        ) : (
          <table className={`${tableClass} mt-2`}>
            <thead>
              <tr>
                <th className={headCellClass}>Account</th>
                <th className={headCellClass}>Covers</th>
                <th className={`${headCellClass} text-right`}>Money in</th>
                <th className={`${headCellClass} text-right`}>Money out</th>
                <th className={headCellClass}>Checked</th>
                <th className={headCellClass}></th>
              </tr>
            </thead>
            <tbody>
              {statements.data.map((s: StatementSummary) => (
                <tr key={s.statement_id} className="border-t border-line">
                  <td className={cellClass}>
                    <span className="font-medium">{s.account_label}</span>{' '}
                    <span className="text-ink-muted">· {s.kind === 'bank' ? 'bank' : 'card'}</span>
                  </td>
                  <td className={`${cellClass} tabular-nums`}>{usDate(s.first_date)} – {usDate(s.last_date)}</td>
                  <td className={`${cellClass} text-right tabular-nums`}>{fmtDollars(s.money_in)}</td>
                  <td className={`${cellClass} text-right tabular-nums`}>{fmtDollars(s.money_out)}</td>
                  <td className={cellClass}>
                    {s.unmatched === 0 ? (
                      <Badge tone="ok">{s.kind === 'bank' ? 'All matched' : 'All sorted'}</Badge>
                    ) : (
                      <Badge tone="warn">
                        {s.unmatched} of {s.lines} {s.kind === 'bank' ? 'unmatched' : 'to sort'}
                      </Badge>
                    )}
                  </td>
                  <td className={cellClass}>
                    <button
                      type="button"
                      className={buttonClass}
                      aria-label={`Open ${s.account_label} ${usDate(s.first_date)}`}
                      onClick={() => setOpenId(s.statement_id)}
                    >
                      Open
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>

      {open !== null && (
        <Card role="region" aria-label={`Statement ${open.account_label}`}>
          <PageHeader
            level={2}
            title={`${open.account_label} — ${usDate(open.first_date)} to ${usDate(open.last_date)}`}
            subtitle={
              open.kind === 'bank'
                ? `${open.matched} of ${open.lines} lines match the night audits or are accounted for; ${open.unmatched} to look at.`
                : `${open.unmatched} of ${open.lines} purchases still to sort. Sorting one remembers the merchant.`
            }
            actions={
              <span className="flex gap-2">
                <button type="button" className={buttonClass} onClick={() => setOpenId(null)}>
                  Close
                </button>
                <button
                  type="button"
                  className={`${buttonClass} text-danger-red`}
                  disabled={remove.isPending}
                  onClick={() => remove.mutate(open.statement_id)}
                >
                  Remove statement
                </button>
              </span>
            }
          />
          {open.kind === 'card' && open.by_category.length > 0 && (
            <section aria-label="By category" className="mb-4">
              <h3 className={sectionHeadClass}>Spent, by category</h3>
              <ul className="mt-1 flex flex-wrap gap-x-6 gap-y-1 text-sm">
                {open.by_category.map(([category, total]) => (
                  <li key={category}>
                    <span className={category === 'Not sorted yet' ? 'text-warn-amber' : 'text-ink'}>
                      {category}
                    </span>{' '}
                    <span className="tabular-nums text-ink-muted">{fmtDollars(total)}</span>
                  </li>
                ))}
              </ul>
            </section>
          )}
          <table className={tableClass}>
            <thead>
              <tr>
                <th className={headCellClass}>Date</th>
                <th className={headCellClass}>On the statement</th>
                <th className={`${headCellClass} text-right`}>Amount</th>
                <th className={headCellClass}>{open.kind === 'bank' ? 'What it is' : 'Category'}</th>
              </tr>
            </thead>
            <tbody>
              {open.rows.map((row: StatementLine) => (
                <tr key={row.line_id} className="border-t border-line align-top">
                  <td className={`${cellClass} tabular-nums`}>{usDate(row.posted_on)}</td>
                  <td className={cellClass}>{row.description}</td>
                  <td className={`${cellClass} text-right tabular-nums`}>{fmtDollars(row.amount)}</td>
                  <td className={cellClass}>
                    {open.kind === 'bank' ? (
                      <div className="flex flex-wrap items-center gap-2">
                        <Badge tone={MATCH_LABELS[row.match_kind]?.tone ?? 'neutral'}>
                          {MATCH_LABELS[row.match_kind]?.text ?? row.match_kind}
                        </Badge>
                        {row.match_note !== null && (
                          <span className="text-xs text-ink-muted">{row.match_note}</span>
                        )}
                        {row.match_kind === 'unmatched' && (
                          <button
                            type="button"
                            className={buttonClass}
                            aria-label={`Not the hotel's: ${row.description}`}
                            disabled={mark.isPending}
                            onClick={() =>
                              mark.mutate({
                                lineId: row.line_id,
                                body: { match_kind: 'ignored', match_note: 'Marked by you as not the hotel’s' },
                              })
                            }
                          >
                            Not the hotel’s
                          </button>
                        )}
                        {row.match_kind === 'ignored' && (
                          <button
                            type="button"
                            className={buttonClass}
                            disabled={mark.isPending}
                            onClick={() =>
                              mark.mutate({ lineId: row.line_id, body: { match_kind: 'unmatched', match_note: null } })
                            }
                          >
                            Undo
                          </button>
                        )}
                      </div>
                    ) : row.amount.startsWith('-') ? (
                      <select
                        className={controlClass}
                        aria-label={`Category for ${row.description}`}
                        value={row.category ?? ''}
                        disabled={mark.isPending}
                        onChange={(e) =>
                          mark.mutate({
                            lineId: row.line_id,
                            body: { category: e.target.value === '' ? null : e.target.value },
                          })
                        }
                      >
                        <option value="">Not sorted yet</option>
                        {(categories.data ?? []).map((c) => (
                          <option key={c} value={c}>{c}</option>
                        ))}
                      </select>
                    ) : (
                      <span className="text-xs text-ink-muted">A payment to the card</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {mark.isError && (
            <p role="alert" className="mt-2 text-sm text-danger-red">{errorMessage(mark.error)}</p>
          )}
        </Card>
      )}

      <Card>
        <section aria-label="How it checks" className="flex flex-col gap-2">
          <h2 className={sectionHeadClass}>How the check works</h2>
          <p className="text-sm text-ink">
            Card payouts (Visa, MasterCard, American Express, Discover) are matched to the card
            payments the front desk recorded, one to a few nights at a time, allowing for the
            processor’s fee. Cash deposits are matched to cash taken at the desk. Payroll is
            marked as payroll. Anything left is listed for you.
          </p>
          <p className="text-sm text-ink-muted">
            It works well for card settlements and payroll, less well for cash deposits and
            anything paid from other accounts. Nothing here changes your books.
          </p>
        </section>
      </Card>
    </div>
  )
}

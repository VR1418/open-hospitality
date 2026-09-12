// Desktop edition: reading a report the product has no parser for
// (ADR-D7 phase 3, src/usali/desktop/ai_api.py).
//
// The screen has to be honest about two things a normal upload screen never
// has to mention: which pages were kept from the model and why, and that
// nothing reaches the books until the person reading this says so.
import { useMutation } from '@tanstack/react-query'
import { useState, type ChangeEvent } from 'react'

import {
  confirmAiReading,
  readReportWithAi,
  type AiReadApplied,
  type AiReading,
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

/** Group the withheld pages by reason: "11 pages — something shaped like a
 *  card number" reads better than eleven identical lines. */
function heldBackSummary(reading: AiReading): [string, number][] {
  const counts = new Map<string, number>()
  for (const held of reading.held_back) {
    counts.set(held.why, (counts.get(held.why) ?? 0) + 1)
  }
  return [...counts.entries()].sort((a, b) => b[1] - a[1])
}

export default function ReadWithAiPage() {
  const { property, selected } = useGlobalProperty()
  const [file, setFile] = useState<File | null>(null)
  const [rows, setRows] = useState<AiReading['rows']>([])
  const [day, setDay] = useState('')
  const [applied, setApplied] = useState<AiReadApplied | null>(null)

  const read = useMutation({
    mutationFn: () => readReportWithAi(property!, file!),
    onSuccess: (result) => {
      setRows(result.rows)
      setDay(result.business_date ?? '')
      setApplied(null)
    },
  })

  const confirm = useMutation({
    mutationFn: () =>
      confirmAiReading({
        property_id: property!,
        file: read.data!.file,
        business_date: day,
        rows,
      }),
    onSuccess: (result) => setApplied(result),
  })

  const pick = (e: ChangeEvent<HTMLInputElement>) => {
    setFile(e.target.files?.[0] ?? null)
    read.reset()
    confirm.reset()
    setApplied(null)
    setRows([])
  }

  const reading = read.data ?? null

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        title="Read a report with AI"
        subtitle={`For ${propertyDisplayName(selected) ?? property ?? 'your hotel'}, whose system we have no reader for`}
      />

      <Card>
        <section aria-label="What happens" className="flex flex-col gap-2">
          <h2 className={sectionHeadClass}>Before you start</h2>
          <p className="text-sm text-ink">
            Your AI helper is shown the pages of this report that contain nothing private —
            no guest names, no account numbers, no card numbers. Pages that do are never
            sent, and you will see how many were held back and why.
          </p>
          <p className="text-sm text-ink-muted">
            It proposes the charges it can find. Nothing reaches your books until you look
            at them and press Put these in the books.
          </p>
        </section>
      </Card>

      <Card>
        <div className="flex flex-col gap-3">
          <label className="flex flex-col gap-1 text-sm" htmlFor="ai-report">
            <span className="text-xs font-medium text-ink-muted">The report, as a PDF</span>
            <input
              id="ai-report"
              type="file"
              accept="application/pdf"
              className={controlClass}
              onChange={pick}
            />
          </label>
          <div>
            <button
              type="button"
              className={primaryButtonClass}
              disabled={file === null || property === undefined || read.isPending}
              onClick={() => read.mutate()}
            >
              {read.isPending ? 'Reading…' : 'Read it'}
            </button>
          </div>
          {read.isError && (
            <p role="alert" className="text-sm text-danger-red">
              {errorMessage(read.error)}
            </p>
          )}
        </div>
      </Card>

      {reading !== null && (
        <Card>
          <section aria-label="What it was shown" className="flex flex-col gap-2">
            <h2 className={sectionHeadClass}>What it was shown</h2>
            <p className="text-sm text-ink">
              {reading.pages_read.length} page{reading.pages_read.length === 1 ? '' : 's'} went
              to {reading.model}
              {reading.estimated_cost !== null && `, costing about $${reading.estimated_cost}`}.
            </p>
            {reading.held_back.length > 0 ? (
              <ul className="flex flex-col gap-1 text-sm text-ink-muted">
                {heldBackSummary(reading).map(([why, count]) => (
                  <li key={why}>
                    {count} page{count === 1 ? '' : 's'} held back — {why}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-ink-muted">No page had to be held back.</p>
            )}
          </section>
        </Card>
      )}

      {reading !== null && reading.rows.length === 0 && (
        <Card>
          <p className="text-sm text-ink" role="status">
            It didn’t find any charges it could read.
            {reading.decline_reason !== null && ` ${reading.decline_reason}`}
          </p>
        </Card>
      )}

      {reading !== null && rows.length > 0 && (
        <Card>
          <section aria-label="What it found" className="flex flex-col gap-3">
            <h2 className={sectionHeadClass}>What it found</h2>
            <p className="text-sm text-ink-muted">
              Check these against the report. Change anything that looks wrong — what you
              accept is what goes in, and your name is on it.
            </p>
            <label className="flex max-w-xs flex-col gap-1 text-sm" htmlFor="ai-day">
              <span className="text-xs font-medium text-ink-muted">Business date</span>
              <input
                id="ai-day"
                type="date"
                className={controlClass}
                value={day}
                onChange={(e) => setDay(e.target.value)}
              />
            </label>
            <table className={tableClass}>
              <thead>
                <tr>
                  <th className={headCellClass}>Code</th>
                  <th className={headCellClass}>Description</th>
                  <th className={`${headCellClass} text-right`}>Amount</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row, i) => (
                  <tr key={`${row.code}-${i}`} className="border-t border-line">
                    <td className={`${cellClass} font-medium`}>{row.code}</td>
                    <td className={cellClass}>{row.description}</td>
                    <td className={`${cellClass} text-right tabular-nums`}>
                      {fmtDollars(row.amount)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                className={primaryButtonClass}
                disabled={day === '' || confirm.isPending}
                onClick={() => confirm.mutate()}
              >
                {confirm.isPending ? 'Working…' : 'Put these in the books'}
              </button>
              <button type="button" className={buttonClass} onClick={() => setRows([])}>
                Discard
              </button>
            </div>
            {confirm.isError && (
              <p role="alert" className="text-sm text-danger-red">
                {errorMessage(confirm.error)}
              </p>
            )}
          </section>
        </Card>
      )}

      {applied !== null && (
        <Card>
          <section aria-label="What changed" className="flex flex-col gap-1">
            <p className="text-sm text-ink">
              {applied.staged} row{applied.staged === 1 ? '' : 's'} went in for{' '}
              {applied.business_date}.
            </p>
            <p className="text-sm text-ink-muted">
              {applied.unmapped > 0 ? (
                <>
                  <Badge tone="warn">{applied.unmapped} to confirm</Badge>{' '}
                  Nothing here knows what these codes mean yet, so their money isn’t on your
                  profit and loss. Open <strong>Codes to confirm</strong> to say where each
                  one belongs — you only do this once.
                </>
              ) : (
                'Every code was already known.'
              )}
            </p>
          </section>
        </Card>
      )}
    </div>
  )
}

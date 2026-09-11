// Desktop edition first-run wizard (PRD M2): hotel group → first hotel →
// fiscal year → modules. The owner is sent here after their first sign-in,
// and after every launch until it is finished (Layout does the sending).
//
// What a real owner needs before their first report can become a statement:
// a property the report's header resolves to, its rooms, and a fiscal
// calendar — without the calendar, reports are read but nothing posts to the
// ledger, so the statement stays empty. The hotel and its fiscal year are
// saved in ONE request at the end of step 3, so there is never a half-made
// hotel to resume from; the group name is saved as soon as it is given.
import { useMutation, useQuery } from '@tanstack/react-query'
import { useEffect, useState, type FormEvent, type ReactNode } from 'react'

import {
  addHotel,
  finishWelcome,
  getModules,
  getWelcome,
  nameGroup,
  saveModules,
  waitForModules,
  type DesktopModule,
  type FiscalChoice,
  type WelcomeState,
} from '../api/desktop'
import { Card, controlLargeClass, sectionHeadClass } from '../components/ui'
import { errorMessage } from '../lib/errors'

type Step = 'group' | 'hotel' | 'fiscal' | 'modules' | 'done'
const STEP_NUMBER: Record<Exclude<Step, 'done'>, number> = {
  group: 1,
  hotel: 2,
  fiscal: 3,
  modules: 4,
}

type HotelDraft = { name: string; report_name: string; pms_source: string; total_rooms: number }

const MONTHS = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December',
]
// Python's weekday(): 0 is Monday (src/usali/fiscal.py).
const WEEKDAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
const OTHER_PMS = 'other'

const primaryButtonClass =
  'h-11 rounded-lg bg-accent px-5 text-sm font-semibold text-accent-contrast shadow-sm ' +
  'transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50'
const secondaryButtonClass =
  'h-11 rounded-lg border border-line px-5 text-sm font-medium text-ink hover:bg-surface-sunken ' +
  'disabled:cursor-not-allowed disabled:opacity-50'

/** Where a returning owner picks up: the first question not yet answered. */
function firstStep(w: WelcomeState): Step {
  if (!w.group_named) return 'group'
  if (w.properties.length === 0) return 'hotel'
  return 'modules'
}

function localTimezone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone
  } catch {
    return ''
  }
}

export default function WelcomePage() {
  const welcome = useQuery({ queryKey: ['welcome'], queryFn: getWelcome, retry: false })
  // Null until the owner moves: until then the step is wherever their saved
  // answers leave off.
  const [chosenStep, setStep] = useState<Step | null>(null)
  const [draft, setDraft] = useState<HotelDraft | null>(null)
  // "Add a hotel" on the Overview reopens just the hotel steps
  // (/welcome?add=hotel), however long ago the install was set up.
  const [addMode] = useState(
    () => new URLSearchParams(window.location.search).get('add') === 'hotel',
  )
  const finishedBefore = !addMode && welcome.data?.finished === true && chosenStep === null
  const step =
    chosenStep ??
    (welcome.data != null && !finishedBefore ? (addMode ? 'hotel' : firstStep(welcome.data)) : null)

  useEffect(() => {
    if (finishedBefore) window.location.replace('/overview')
  }, [finishedBefore])

  if (welcome.isError) {
    return (
      <Shell title="Something went wrong">
        <p role="alert" className="text-sm text-danger-red">
          {errorMessage(welcome.error)}
        </p>
      </Shell>
    )
  }
  if (welcome.data === null) {
    return (
      <Shell title="Nothing to set up here">
        <p className="text-sm text-ink-muted">This page belongs to the desktop edition.</p>
      </Shell>
    )
  }
  if (welcome.data === undefined || step === null) {
    return (
      <Shell>
        <p className="text-sm text-ink-muted">Loading …</p>
      </Shell>
    )
  }

  const state = welcome.data
  switch (step) {
    case 'group':
      return (
        <GroupStep
          initial={state.group_named ? state.group_name : ''}
          onDone={() => setStep(state.properties.length === 0 ? 'hotel' : 'modules')}
        />
      )
    case 'hotel':
      return (
        <HotelStep
          state={state}
          draft={draft}
          addMode={addMode}
          onNext={(d) => {
            setDraft(d)
            setStep('fiscal')
          }}
          onSkip={() => setStep('modules')}
        />
      )
    case 'fiscal':
      return (
        <FiscalStep
          draft={draft as HotelDraft}
          addMode={addMode}
          onBack={() => setStep('hotel')}
          onDone={() => (addMode ? window.location.assign('/overview') : setStep('modules'))}
        />
      )
    case 'modules':
      return <ModulesStep onDone={() => setStep('done')} />
    case 'done':
      return <DoneStep />
  }
}

// --- pieces -----------------------------------------------------------------

function Shell({ step, title, children }: { step?: Step; title?: string; children: ReactNode }) {
  const number = step !== undefined && step !== 'done' ? STEP_NUMBER[step] : null
  return (
    <main className="mx-auto flex min-h-screen max-w-xl flex-col justify-center px-6 py-10">
      <p className="mb-6 text-lg font-semibold tracking-tight">
        <span aria-hidden="true" className="text-accent">
          ◆
        </span>{' '}
        <span className="text-accent">Open</span> Hospitality
      </p>
      <Card>
        {number !== null && <p className={sectionHeadClass}>Step {number} of 4</p>}
        {title !== undefined && <h1 className="mb-3 mt-1 text-xl font-semibold text-ink">{title}</h1>}
        {children}
      </Card>
    </main>
  )
}

function Label({ text, hint, children }: { text: string; hint?: string; children: ReactNode }) {
  return (
    <label className="block text-sm">
      <span className="mb-1 block text-xs font-medium text-ink-muted">{text}</span>
      {children}
      {hint !== undefined && <span className="mt-1 block text-xs text-ink-muted">{hint}</span>}
    </label>
  )
}

function Refusal({ error }: { error: unknown }) {
  if (error === null || error === undefined) return null
  return (
    <p role="alert" className="text-sm text-danger-red">
      {errorMessage(error)}
    </p>
  )
}

function GroupStep({ initial, onDone }: { initial: string; onDone: () => void }) {
  const [name, setName] = useState(initial)
  const save = useMutation({ mutationFn: () => nameGroup(name.trim()), onSuccess: onDone })

  return (
    <Shell step="group" title="Welcome — let’s set up your books">
      <p className="mb-5 text-sm text-ink-muted">
        Four short questions. You can change every answer later.
      </p>
      <form
        className="flex flex-col gap-4"
        onSubmit={(e: FormEvent) => {
          e.preventDefault()
          save.mutate()
        }}
      >
        <Label
          text="Your hotel group’s name"
          hint="The company or family name your hotels trade under — it’s fine if you have just one hotel."
        >
          <input
            aria-label="Your hotel group’s name"
            className={controlLargeClass}
            required
            maxLength={200}
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </Label>
        <Refusal error={save.error} />
        <div>
          <button type="submit" className={primaryButtonClass} disabled={save.isPending}>
            {save.isPending ? 'Saving…' : 'Continue'}
          </button>
        </div>
      </form>
    </Shell>
  )
}

function HotelStep({
  state,
  draft,
  addMode,
  onNext,
  onSkip,
}: {
  state: WelcomeState
  draft: HotelDraft | null
  addMode: boolean
  onNext: (d: HotelDraft) => void
  onSkip: () => void
}) {
  const existing = state.properties
  const [adding, setAdding] = useState(addMode || existing.length === 0)
  const [name, setName] = useState(draft?.name ?? '')
  const [reportName, setReportName] = useState(draft?.report_name ?? '')
  const [pms, setPms] = useState(draft?.pms_source ?? state.pms_choices[0]?.id ?? '')
  const [rooms, setRooms] = useState(draft === null ? '' : String(draft.total_rooms))

  if (!adding) {
    return (
      <Shell step="hotel" title="Your hotels">
        <p className="mb-3 text-sm text-ink-muted">This copy of Open Hospitality already has:</p>
        <ul className="mb-5 list-disc pl-5 text-sm text-ink">
          {existing.map((p) => (
            <li key={p.property_id}>
              {p.name} <span className="text-ink-muted">({p.property_id})</span>
            </li>
          ))}
        </ul>
        <div className="flex flex-wrap gap-3">
          <button type="button" className={primaryButtonClass} onClick={onSkip}>
            Continue
          </button>
          <button type="button" className={secondaryButtonClass} onClick={() => setAdding(true)}>
            Add another hotel
          </button>
        </div>
      </Shell>
    )
  }

  const unsupported = pms === OTHER_PMS
  const roomCount = Number(rooms)

  return (
    <Shell
      step={addMode ? undefined : 'hotel'}
      title={addMode ? 'Add a hotel' : 'Your first hotel'}
    >
      <form
        className="flex flex-col gap-4"
        onSubmit={(e: FormEvent) => {
          e.preventDefault()
          onNext({
            name: name.trim(),
            report_name: reportName.trim() || name.trim(),
            pms_source: pms,
            total_rooms: roomCount,
          })
        }}
      >
        <Label text="Hotel name">
          <input
            aria-label="Hotel name"
            className={controlLargeClass}
            required
            maxLength={200}
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </Label>
        <Label
          text="The hotel’s name on your reports"
          hint="Look at the top of any night audit report and type the hotel name exactly as it’s printed there — it’s how Open Hospitality knows which hotel a report belongs to. Capital letters don’t matter. Leave it blank if it’s the same as above."
        >
          <input
            aria-label="The hotel’s name on your reports"
            className={controlLargeClass}
            maxLength={200}
            placeholder={name.toUpperCase()}
            value={reportName}
            onChange={(e) => setReportName(e.target.value)}
          />
        </Label>
        <Label text="Front-desk system (PMS)">
          <select
            aria-label="Front-desk system (PMS)"
            className={controlLargeClass}
            value={pms}
            onChange={(e) => setPms(e.target.value)}
          >
            {state.pms_choices.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
            <option value={OTHER_PMS}>Something else</option>
          </select>
        </Label>
        {unsupported && (
          <p role="status" className="text-sm text-ink">
            Open Hospitality can only read reports from{' '}
            {state.pms_choices.map((c) => c.name).join(', ')} so far. If your hotel uses another
            system, it can’t read your reports yet.
          </p>
        )}
        <Label text="Rooms you can sell" hint="All the rooms at the hotel that can be let to guests.">
          <input
            aria-label="Rooms you can sell"
            className={controlLargeClass}
            type="number"
            inputMode="numeric"
            min={1}
            step={1}
            required
            value={rooms}
            onChange={(e) => setRooms(e.target.value)}
          />
        </Label>
        <div className="flex flex-wrap items-center gap-3">
          <button
            type="submit"
            className={primaryButtonClass}
            disabled={unsupported || !(Number.isInteger(roomCount) && roomCount > 0)}
          >
            Continue
          </button>
          {addMode && (
            <a href="/overview" className={`${secondaryButtonClass} inline-flex items-center`}>
              Cancel
            </a>
          )}
        </div>
      </form>
    </Shell>
  )
}

function FiscalStep({
  draft,
  addMode,
  onBack,
  onDone,
}: {
  draft: HotelDraft
  addMode: boolean
  onBack: () => void
  onDone: () => void
}) {
  const [type, setType] = useState<FiscalChoice['calendar_type']>('calendar_month')
  const [startMonth, setStartMonth] = useState(1)
  const [weekday, setWeekday] = useState(0)
  const save = useMutation({
    mutationFn: () =>
      addHotel({
        ...draft,
        timezone: localTimezone(),
        fiscal: {
          calendar_type: type,
          fiscal_year_start_month: startMonth,
          week_start_weekday: type === '445' ? weekday : null,
        },
      }),
    onSuccess: onDone,
  })

  return (
    <Shell step={addMode ? undefined : 'fiscal'} title={`${draft.name}’s financial year`}>
      <p className="mb-5 text-sm text-ink-muted">
        Your statements are grouped into the periods of your financial year. Most hotels use
        calendar months starting in January — if you’re not sure, ask your accountant. You can
        change this later on the Property config page.
      </p>
      <form
        className="flex flex-col gap-4"
        onSubmit={(e: FormEvent) => {
          e.preventDefault()
          save.mutate()
        }}
      >
        <fieldset className="flex flex-col gap-2 text-sm text-ink">
          <legend className="mb-1 text-xs font-medium text-ink-muted">Periods</legend>
          <label className="flex items-start gap-2">
            <input
              type="radio"
              name="calendar"
              className="mt-0.5"
              checked={type === 'calendar_month'}
              onChange={() => setType('calendar_month')}
            />
            <span>
              Calendar months <span className="text-ink-muted">— most hotels</span>
            </span>
          </label>
          <label className="flex items-start gap-2">
            <input
              type="radio"
              name="calendar"
              className="mt-0.5"
              checked={type === '445'}
              onChange={() => setType('445')}
            />
            <span>
              4-4-5 weeks{' '}
              <span className="text-ink-muted">— each quarter is two 4-week periods and a 5-week one</span>
            </span>
          </label>
        </fieldset>
        <Label text="The financial year starts in">
          <select
            aria-label="The financial year starts in"
            className={controlLargeClass}
            value={startMonth}
            onChange={(e) => setStartMonth(Number(e.target.value))}
          >
            {MONTHS.map((m, i) => (
              <option key={m} value={i + 1}>
                {m}
              </option>
            ))}
          </select>
        </Label>
        {type === '445' && (
          <Label text="Weeks start on">
            <select
              aria-label="Weeks start on"
              className={controlLargeClass}
              value={weekday}
              onChange={(e) => setWeekday(Number(e.target.value))}
            >
              {WEEKDAYS.map((d, i) => (
                <option key={d} value={i}>
                  {d}
                </option>
              ))}
            </select>
          </Label>
        )}
        <Refusal error={save.error} />
        <div className="flex flex-wrap gap-3">
          <button type="button" className={secondaryButtonClass} onClick={onBack} disabled={save.isPending}>
            Back
          </button>
          <button type="submit" className={primaryButtonClass} disabled={save.isPending}>
            {save.isPending ? 'Saving…' : 'Save and continue'}
          </button>
        </div>
      </form>
    </Shell>
  )
}

function ModulesStep({ onDone }: { onDone: () => void }) {
  const modules = useQuery({ queryKey: ['modules'], queryFn: getModules, retry: false })
  const [chosen, setChosen] = useState<Set<string> | null>(null)
  const [switching, setSwitching] = useState(false)
  const list = modules.data?.modules ?? []
  const picked = chosen ?? new Set(list.filter((m) => m.enabled).map((m) => m.id))

  const finish = useMutation({
    mutationFn: async () => {
      await finishWelcome()
      const saved = await saveModules([...picked])
      if (saved.reloading) {
        setSwitching(true)
        await waitForModules(saved.modules.filter((m) => m.enabled).map((m) => m.id))
      }
    },
    onSuccess: onDone,
    onSettled: () => setSwitching(false),
  })

  function toggle(m: DesktopModule) {
    const next = new Set(picked)
    if (next.has(m.id)) next.delete(m.id)
    else next.add(m.id)
    setChosen(next)
  }

  return (
    <Shell step="modules" title="What would you like to use?">
      <p className="mb-5 text-sm text-ink-muted">
        Turn on only what you need. You can change this at any time on the Modules page — turning
        something off hides it and deletes nothing.
      </p>
      {modules.isPending && <p className="text-sm text-ink-muted">Loading …</p>}
      <Refusal error={modules.error} />
      <div className="flex flex-col gap-3">
        {list.map((m) => (
          <ModuleChoice key={m.id} module={m} on={picked.has(m.id)} onToggle={() => toggle(m)} />
        ))}
      </div>
      {switching && (
        <p role="status" className="mt-4 text-sm text-ink-muted">
          Switching… this takes a few seconds.
        </p>
      )}
      <div className="mt-4">
        <Refusal error={finish.error} />
      </div>
      <div className="mt-4">
        <button
          type="button"
          className={primaryButtonClass}
          disabled={finish.isPending || modules.data == null}
          onClick={() => finish.mutate()}
        >
          {finish.isPending ? 'Finishing…' : 'Finish'}
        </button>
      </div>
    </Shell>
  )
}

function ModuleChoice({
  module: m,
  on,
  onToggle,
}: {
  module: DesktopModule
  on: boolean
  onToggle: () => void
}) {
  const selectable = m.status === 'available' && !m.required
  return (
    <div role="group" aria-label={m.name} className="rounded-lg border border-line p-3">
      <label className={`flex items-start gap-2 ${selectable ? '' : 'cursor-default'}`}>
        <input
          type="checkbox"
          className="mt-1"
          checked={m.required || (m.status === 'available' && on)}
          disabled={!selectable}
          onChange={onToggle}
        />
        <span>
          <span className="block text-sm font-semibold text-ink">
            {m.name}
            {m.required && <span className="ml-2 text-xs font-normal text-ink-muted">Always on</span>}
            {m.status === 'coming_soon' && (
              <span className="ml-2 text-xs font-normal text-ink-muted">Coming soon</span>
            )}
          </span>
          <span className="block text-sm text-ink-muted">{m.summary}</span>
        </span>
      </label>
      <details className="mt-2 pl-6 text-sm">
        <summary className="cursor-pointer text-ink-muted">What this can’t do</summary>
        <ul className="mt-1 list-disc pl-5 text-ink">
          {m.limitations.map((lim) => (
            <li key={lim.text} className="py-0.5">
              {lim.text}
              {lim.workaround !== null && (
                <span className="block text-ink-muted">What you can do: {lim.workaround}</span>
              )}
            </li>
          ))}
        </ul>
      </details>
    </div>
  )
}

function DoneStep() {
  return (
    <Shell title="You’re set up">
      <p className="text-sm text-ink">
        Now give Open Hospitality your night audit reports. Put them in the{' '}
        <strong>Drop reports here</strong> folder inside <strong>Documents › Open Hospitality</strong>
        , or use <strong>Upload</strong> in the app. Each report is read within a few seconds.
      </p>
      <p className="mt-3 text-sm text-ink-muted">
        The Setup page shows anything still left to do.
      </p>
      <button
        type="button"
        className={`${primaryButtonClass} mt-5`}
        onClick={() => window.location.assign('/setup')}
      >
        Open my books
      </button>
    </Shell>
  )
}
